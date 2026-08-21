from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import replace
from pathlib import Path
from collections.abc import Callable

from aidycai.application.registry import ProjectRegistry
from aidycai.domain.exceptions import InvalidPathError
from aidycai.domain.index_models import (
    ExtractedImport,
    ExtractedSymbol,
    FileRecord,
    IndexStats,
    IndexSummary,
    SearchHit,
    WalkedFile,
)
from aidycai.domain.models import Project
from aidycai.infrastructure.analyzers.python_ast import PythonAstAnalyzer
from aidycai.infrastructure.classify import KIND_BINARY, KIND_CODE, classify_file, decode_text
from aidycai.infrastructure.import_graph import resolve_python_import
from aidycai.infrastructure.index_store import SqliteIndexStore
from aidycai.infrastructure.paths import DataLayout
from aidycai.infrastructure.scanner import FileSystemScanner

logger = logging.getLogger("aidycai")

_MAX_FTS_CHARS = 400_000
_MTIME_EPS = 1e-6

ProgressCallback = Callable[[str, int, int, str | None], None]


class IndexService:
    """Project → Index → Search. No LLM providers."""

    def __init__(self, layout: DataLayout, registry: ProjectRegistry, scanner: FileSystemScanner) -> None:
        self._layout = layout
        self._registry = registry
        self._scanner = scanner
        self._python = PythonAstAnalyzer()

    def index_project(
        self,
        name_or_id: str,
        *,
        rebuild: bool = False,
        progress: ProgressCallback | None = None,
    ) -> IndexSummary:
        project = self._registry.require(name_or_id)
        if not project.path.is_dir():
            raise InvalidPathError(f"La ruta del proyecto no existe: {project.path}")
        self._layout.project_data_dir(project.id).mkdir(parents=True, exist_ok=True)
        index_path = self._layout.project_index_path(project.id)
        if rebuild:
            self._remove_index_files(index_path)
        store = SqliteIndexStore(index_path, project.id, project.name)
        started = time.perf_counter()
        run_id = store.begin_run()
        try:
            summary = self._index_into(store, project, run_id, progress=progress)
            summary = replace(summary, duration_s=time.perf_counter() - started)
            store.finish_run(
                run_id,
                "ok",
                {
                    "files_found": summary.files_found,
                    "files_code": summary.files_code,
                    "files_unchanged": summary.files_unchanged,
                    "files_modified": summary.files_modified,
                    "files_created": summary.files_created,
                    "files_deleted": summary.files_deleted,
                    "files_renamed": summary.files_renamed,
                    "symbols": summary.symbols,
                    "imports": summary.imports,
                    "error_count": summary.errors,
                },
            )
            return summary
        except Exception:
            try:
                store.finish_run(run_id, "error", {"error_count": 1})
            except Exception:
                logger.exception("No se pudo cerrar correctamente la ejecución de indexación %s", project.name)
            raise
        finally:
            store.close()
            logger.info("Index %s in %.2fs", project.name, time.perf_counter() - started)

    @staticmethod
    def _remove_index_files(index_path: Path) -> None:
        """Remove the SQLite database and its WAL sidecars for an explicit rebuild."""
        for path in (
            index_path,
            Path(str(index_path) + "-wal"),
            Path(str(index_path) + "-shm"),
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def index_all_active(self) -> list[IndexSummary]:
        results: list[IndexSummary] = []
        for project in self._registry.list_projects():
            if not project.active:
                continue
            results.append(self.index_project(project.id))
        return results

    def search(self, name_or_id: str, query: str, *, limit: int = 25) -> list[SearchHit]:
        project = self._registry.require(name_or_id)
        index_path = self._layout.project_index_path(project.id)
        if not index_path.exists():
            return []
        store = SqliteIndexStore(index_path, project.id, project.name)
        try:
            return store.search(query, limit=limit)
        finally:
            store.close()

    def stats(self, name_or_id: str) -> IndexStats:
        project = self._registry.require(name_or_id)
        index_path = self._layout.project_index_path(project.id)
        if not index_path.exists():
            return IndexStats(
                project_id=project.id,
                project_name=project.name,
                last_indexed_at=None,
                last_run_at=None,
                last_run_status=None,
                files_indexed=0,
                files_code=0,
                files_binary=0,
                symbols=0,
                imports=0,
                import_edges=0,
                errors=0,
                index_bytes=0,
                last_error=None,
            )
        store = SqliteIndexStore(index_path, project.id, project.name)
        try:
            return store.stats()
        finally:
            store.close()

    def _index_into(
        self,
        store: SqliteIndexStore,
        project: Project,
        run_id: int,
        *,
        progress: ProgressCallback | None = None,
    ) -> IndexSummary:
        extra = self._registry.extra_excludes(project.id)
        walked = self._scanner.iter_files(project.path, extra)
        total = len(walked)
        existing = store.list_files()
        if progress:
            progress("scan", 0, total, None)
        seen = {item.rel_path for item in walked}

        unchanged = 0
        modified = 0
        created = 0
        deleted = 0
        renamed = 0
        error_count = 0

        created_walked = [item for item in walked if item.rel_path not in existing]
        maybe_deleted = [record for path, record in existing.items() if path not in seen]
        created_hashes: dict[str, tuple[WalkedFile, str]] = {}

        for index, item in enumerate(created_walked, 1):
            if progress:
                progress("prepare", index, len(created_walked), item.rel_path)
            try:
                digest = _hash_file(project.path / item.rel_path)
            except OSError:
                continue
            created_hashes[item.rel_path] = (item, digest)

        deleted_by_hash: dict[str, list[FileRecord]] = {}
        for record in maybe_deleted:
            deleted_by_hash.setdefault(record.hash, []).append(record)

        renamed_from: set[int] = set()
        renamed_to: set[str] = set()
        created_hash_counts: dict[str, int] = {}
        for _path, (_item, digest) in created_hashes.items():
            created_hash_counts[digest] = created_hash_counts.get(digest, 0) + 1

        for rel_path, (item, digest) in list(created_hashes.items()):
            candidates = deleted_by_hash.get(digest, [])
            if (
                len(candidates) == 1
                and created_hash_counts.get(digest, 0) == 1
                and candidates[0].id not in renamed_from
            ):
                old = candidates[0]
                store.update_file_identity(
                    old.id,
                    rel_path=item.rel_path,
                    extension=item.extension,
                    size=item.size,
                    mtime=item.mtime,
                    digest=digest,
                )
                store.update_fts_path(old.id, item.rel_path)
                store.clear_errors_for(old.rel_path)
                renamed_from.add(old.id)
                renamed_to.add(item.rel_path)
                renamed += 1

        remaining_deleted = [record for record in maybe_deleted if record.id not in renamed_from]
        for record in remaining_deleted:
            store.delete_file(record.id)
            deleted += 1

        for index, item in enumerate(walked, 1):
            if progress:
                progress("analyze", index, total, item.rel_path)
            if item.rel_path in renamed_to:
                continue
            record = existing.get(item.rel_path)
            if record is not None and _same_mtime_size(record, item):
                unchanged += 1
                continue
            if record is not None:
                digest = _hash_file(project.path / item.rel_path)
                if digest == record.hash:
                    store.touch_unchanged(record.id, item.size, item.mtime)
                    unchanged += 1
                    continue
                ok = self._reanalyze(store, project, item, digest, record.id, run_id)
                modified += 1
                if not ok:
                    error_count += 1
                continue
            if item.rel_path in created_hashes:
                _walked, digest = created_hashes[item.rel_path]
                ok = self._analyze_new(store, project, item, digest, run_id)
                created += 1
                if not ok:
                    error_count += 1

        if progress:
            progress("graph", total, total, None)
        self._refresh_import_graph(store)
        store.commit()
        if progress:
            progress("done", total, total, None)
        counts = store.counts()
        duration = 0.0
        return IndexSummary(
            project_id=project.id,
            project_name=project.name,
            files_found=len(walked),
            files_code=counts["files_code"],
            files_text=max(0, counts["files"] - counts["files_code"] - counts["files_binary"]),
            files_binary=counts["files_binary"],
            files_unchanged=unchanged,
            files_modified=modified,
            files_created=created,
            files_deleted=deleted,
            files_renamed=renamed,
            symbols=counts["symbols"],
            imports=counts["imports"],
            errors=error_count,
            duration_s=duration,
        )

    def _analyze_new(
        self,
        store: SqliteIndexStore,
        project: Project,
        item: WalkedFile,
        digest: str,
        run_id: int,
    ) -> bool:
        kind, language, status, symbols, imports, body, error = self._inspect(project, item, run_id)
        file_id = store.insert_file(
            rel_path=item.rel_path,
            extension=item.extension,
            language=language,
            kind=kind,
            size=item.size,
            mtime=item.mtime,
            digest=digest,
            status=status,
        )
        store.replace_analysis(file_id, item.rel_path, body, symbols, imports)
        if error:
            store.add_error(item.rel_path, error[0], error[1], run_id)
            return False
        store.clear_errors_for(item.rel_path)
        return True

    def _reanalyze(
        self,
        store: SqliteIndexStore,
        project: Project,
        item: WalkedFile,
        digest: str,
        file_id: int,
        run_id: int,
    ) -> bool:
        kind, language, status, symbols, imports, body, error = self._inspect(project, item, run_id)
        store.update_file_identity(
            file_id,
            rel_path=item.rel_path,
            extension=item.extension,
            size=item.size,
            mtime=item.mtime,
            digest=digest,
            language=language,
            kind=kind,
            status=status,
        )
        store.replace_analysis(file_id, item.rel_path, body, symbols, imports)
        if error:
            store.add_error(item.rel_path, error[0], error[1], run_id)
            return False
        store.clear_errors_for(item.rel_path)
        return True

    def _inspect(
        self, project: Project, item: WalkedFile, run_id: int
    ) -> tuple[str, str | None, str, list[ExtractedSymbol], list[ExtractedImport], str | None, tuple[str, str] | None]:
        path = project.path / item.rel_path
        try:
            data = path.read_bytes()
        except OSError as exc:
            return KIND_BINARY, None, "error", [], [], None, ("read", str(exc))

        kind, language = classify_file(path, item.extension, data[:8192])
        if kind == KIND_BINARY:
            return kind, language, "binary", [], [], None, None

        text = decode_text(data)
        body = text[:_MAX_FTS_CHARS]
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []
        if language == "python" and kind == KIND_CODE:
            try:
                analysis = self._python.analyze(item.rel_path, text)
                symbols = list(analysis.symbols)
                imports = list(analysis.imports)
            except SyntaxError as exc:
                logger.warning("AST error in %s: %s", item.rel_path, exc)
                return kind, language, "error", [], [], body, ("ast", f"{exc.msg} (línea {exc.lineno})")
            except Exception as exc:  # noqa: BLE001 — isolate analyzer failures per file
                logger.warning("Analyzer error in %s: %s", item.rel_path, exc)
                return kind, language, "error", [], [], body, ("ast", str(exc))
        return kind, language, "ok", symbols, imports, body, None

    def _refresh_import_graph(self, store: SqliteIndexStore) -> None:
        files = store.list_files()
        known = set(files.keys())
        imports = store.list_imports()
        for item in imports:
            rel = next((path for path, rec in files.items() if rec.id == item.file_id), None)
            if rel is None:
                continue
            resolved = resolve_python_import(rel, item.module, item.level, known)
            store.set_import_resolution(item.file_id, item.module, resolved)
        store.rebuild_edges()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _same_mtime_size(record: FileRecord, item: WalkedFile) -> bool:
    return record.size == item.size and abs(record.mtime - item.mtime) <= _MTIME_EPS
