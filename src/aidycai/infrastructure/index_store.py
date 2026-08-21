from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aidycai.domain.index_models import (
    ExtractedImport,
    ExtractedSymbol,
    FileRecord,
    ImportRecord,
    IndexStats,
    SearchHit,
    SymbolRecord,
)
from aidycai.infrastructure.index_database import connect_index


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class SqliteIndexStore:
    def __init__(self, path: Path, project_id: str, project_name: str) -> None:
        self.path = path
        self.project_id = project_id
        self.project_name = project_name
        self.connection = connect_index(path)

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()

    def begin_run(self) -> int:
        cursor = self.connection.execute(
            "INSERT INTO index_runs (started_at, status) VALUES (?, 'running')",
            (_iso(utcnow()),),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, counts: dict[str, int]) -> None:
        self.connection.execute(
            """
            UPDATE index_runs
            SET finished_at = ?, status = ?,
                files_found = ?, files_code = ?, files_unchanged = ?,
                files_modified = ?, files_created = ?, files_deleted = ?,
                files_renamed = ?, symbols = ?, imports = ?, error_count = ?
            WHERE id = ?
            """,
            (
                _iso(utcnow()),
                status,
                counts.get("files_found", 0),
                counts.get("files_code", 0),
                counts.get("files_unchanged", 0),
                counts.get("files_modified", 0),
                counts.get("files_created", 0),
                counts.get("files_deleted", 0),
                counts.get("files_renamed", 0),
                counts.get("symbols", 0),
                counts.get("imports", 0),
                counts.get("error_count", 0),
                run_id,
            ),
        )
        self.connection.commit()

    def list_files(self) -> dict[str, FileRecord]:
        rows = self.connection.execute(
            "SELECT id, rel_path, extension, language, kind, size, mtime, hash, status, indexed_at FROM files"
        ).fetchall()
        return {row["rel_path"]: self._file_from_row(row) for row in rows}

    def get_by_hash(self, digest: str) -> list[FileRecord]:
        rows = self.connection.execute(
            "SELECT id, rel_path, extension, language, kind, size, mtime, hash, status, indexed_at "
            "FROM files WHERE hash = ?",
            (digest,),
        ).fetchall()
        return [self._file_from_row(row) for row in rows]

    def insert_file(
        self,
        *,
        rel_path: str,
        extension: str,
        language: str | None,
        kind: str,
        size: int,
        mtime: float,
        digest: str,
        status: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO files (rel_path, extension, language, kind, size, mtime, hash, status, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rel_path, extension, language, kind, size, mtime, digest, status, _iso(utcnow())),
        )
        return int(cursor.lastrowid)

    def update_file_identity(
        self,
        file_id: int,
        *,
        rel_path: str,
        extension: str,
        size: int,
        mtime: float,
        digest: str,
        language: str | None | object = ...,
        kind: str | None = None,
        status: str | None = None,
    ) -> None:
        row = self.connection.execute(
            "SELECT language, kind, status FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()
        if row is None:
            return
        new_language = row["language"] if language is ... else language
        new_kind = row["kind"] if kind is None else kind
        new_status = row["status"] if status is None else status
        self.connection.execute(
            """
            UPDATE files
            SET rel_path = ?, extension = ?, language = ?, kind = ?, size = ?, mtime = ?,
                hash = ?, status = ?, indexed_at = ?
            WHERE id = ?
            """,
            (
                rel_path,
                extension,
                new_language,
                new_kind,
                size,
                mtime,
                digest,
                new_status,
                _iso(utcnow()),
                file_id,
            ),
        )

    def touch_unchanged(self, file_id: int, size: int, mtime: float) -> None:
        self.connection.execute(
            "UPDATE files SET size = ?, mtime = ? WHERE id = ?",
            (size, mtime, file_id),
        )

    def delete_file(self, file_id: int) -> None:
        self._delete_fts_for_file(file_id)
        self.connection.execute("DELETE FROM files WHERE id = ?", (file_id,))

    def replace_analysis(
        self,
        file_id: int,
        rel_path: str,
        body: str | None,
        symbols: list[ExtractedSymbol],
        imports: list[ExtractedImport],
    ) -> None:
        self._delete_fts_for_file(file_id)
        self.connection.execute("DELETE FROM sql_operations WHERE symbol_id IN (SELECT id FROM symbols WHERE file_id = ?)", (file_id,))
        self.connection.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        self.connection.execute("DELETE FROM imports WHERE file_id = ?", (file_id,))
        self.connection.execute("DELETE FROM import_edges WHERE from_file_id = ?", (file_id,))
        if body is not None:
            self.connection.execute(
                "INSERT INTO files_fts(rowid, rel_path, body) VALUES (?, ?, ?)",
                (file_id, rel_path, body),
            )
        else:
            self.connection.execute(
                "INSERT INTO files_fts(rowid, rel_path, body) VALUES (?, ?, ?)",
                (file_id, rel_path, ""),
            )
        for symbol in symbols:
            cursor = self.connection.execute(
                """
                INSERT INTO symbols (file_id, type, name, qualified_name, line_start, line_end, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    symbol.type,
                    symbol.name,
                    symbol.qualified_name,
                    symbol.line_start,
                    symbol.line_end,
                    json.dumps(symbol.metadata, ensure_ascii=False),
                ),
            )
            symbol_id = int(cursor.lastrowid)
            self.connection.execute(
                "INSERT INTO symbols_fts(rowid, name, qualified_name) VALUES (?, ?, ?)",
                (symbol_id, symbol.name, symbol.qualified_name),
            )
            operations = symbol.metadata.get("sql_operations", []) if isinstance(symbol.metadata, dict) else []
            for operation in operations if isinstance(operations, list) else []:
                if not isinstance(operation, dict):
                    continue
                self.connection.execute(
                    """
                    INSERT INTO sql_operations (symbol_id, kind, resource, line, columns, predicates)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol_id,
                        str(operation.get("kind", "")).upper(),
                        str(operation.get("resource", "")),
                        operation.get("line"),
                        json.dumps(operation.get("columns", []), ensure_ascii=False),
                        json.dumps(operation.get("predicates", []), ensure_ascii=False),
                    ),
                )
        for item in imports:
            self.connection.execute(
                """
                INSERT INTO imports (file_id, import_type, module, names, alias, resolved_rel_path, line, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    item.import_type,
                    item.module,
                    json.dumps(list(item.names), ensure_ascii=False),
                    item.alias,
                    None,
                    item.line,
                    item.level,
                ),
            )

    def update_fts_path(self, file_id: int, rel_path: str) -> None:
        body_row = self.connection.execute(
            "SELECT body FROM files_fts WHERE rowid = ?",
            (file_id,),
        ).fetchone()
        body = body_row["body"] if body_row else ""
        self.connection.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))
        self.connection.execute(
            "INSERT INTO files_fts(rowid, rel_path, body) VALUES (?, ?, ?)",
            (file_id, rel_path, body or ""),
        )

    def set_import_resolution(self, file_id: int, module: str, resolved_rel_path: str | None) -> None:
        self.connection.execute(
            "UPDATE imports SET resolved_rel_path = ? WHERE file_id = ? AND module = ?",
            (resolved_rel_path, file_id, module),
        )

    def rebuild_edges(self) -> None:
        self.connection.execute("DELETE FROM import_edges")
        rows = self.connection.execute(
            "SELECT file_id, module, resolved_rel_path FROM imports"
        ).fetchall()
        path_to_id = {
            row["rel_path"]: row["id"]
            for row in self.connection.execute("SELECT id, rel_path FROM files").fetchall()
        }
        seen: set[tuple[int, str]] = set()
        for row in rows:
            key = (int(row["file_id"]), row["module"])
            if key in seen:
                continue
            seen.add(key)
            to_id = path_to_id.get(row["resolved_rel_path"]) if row["resolved_rel_path"] else None
            self.connection.execute(
                "INSERT OR IGNORE INTO import_edges (from_file_id, to_file_id, to_module) VALUES (?, ?, ?)",
                (row["file_id"], to_id, row["module"]),
            )

    def list_imports(self) -> list[ImportRecord]:
        rows = self.connection.execute(
            "SELECT file_id, import_type, module, names, alias, resolved_rel_path, line, level FROM imports"
        ).fetchall()
        result: list[ImportRecord] = []
        for row in rows:
            try:
                names = json.loads(row["names"] or "[]")
            except json.JSONDecodeError:
                names = []
            result.append(
                ImportRecord(
                    file_id=row["file_id"],
                    import_type=row["import_type"],
                    module=row["module"],
                    names=list(names),
                    alias=row["alias"],
                    resolved_rel_path=row["resolved_rel_path"],
                    line=row["line"],
                    level=row["level"],
                )
            )
        return result

    def list_edges(self) -> list[tuple[str, str | None, str]]:
        rows = self.connection.execute(
            """
            SELECT src.rel_path AS src, dst.rel_path AS dst, e.to_module
            FROM import_edges e
            JOIN files src ON src.id = e.from_file_id
            LEFT JOIN files dst ON dst.id = e.to_file_id
            """
        ).fetchall()
        return [(row["src"], row["dst"], row["to_module"]) for row in rows]

    def add_error(self, rel_path: str, phase: str, message: str, run_id: int) -> None:
        self.connection.execute(
            "INSERT INTO index_errors (rel_path, phase, message, created_at, run_id) VALUES (?, ?, ?, ?, ?)",
            (rel_path, phase, message, _iso(utcnow()), run_id),
        )

    def clear_errors_for(self, rel_path: str) -> None:
        self.connection.execute("DELETE FROM index_errors WHERE rel_path = ?", (rel_path,))

    def counts(self) -> dict[str, int]:
        def scalar(sql: str) -> int:
            row = self.connection.execute(sql).fetchone()
            return int(list(row)[0]) if row else 0

        return {
            "files": scalar("SELECT COUNT(*) FROM files"),
            "files_code": scalar("SELECT COUNT(*) FROM files WHERE kind = 'code'"),
            "files_binary": scalar("SELECT COUNT(*) FROM files WHERE kind = 'binary'"),
            "symbols": scalar("SELECT COUNT(*) FROM symbols"),
            "imports": scalar("SELECT COUNT(*) FROM imports"),
            "import_edges": scalar("SELECT COUNT(*) FROM import_edges"),
            "errors": scalar("SELECT COUNT(*) FROM index_errors"),
        }

    def stats(self) -> IndexStats:
        counts = self.counts()
        last_file = self.connection.execute(
            "SELECT MAX(indexed_at) AS ts FROM files"
        ).fetchone()
        last_run = self.connection.execute(
            "SELECT started_at, finished_at, status FROM index_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_error = self.connection.execute(
            "SELECT rel_path || ': ' || message AS msg FROM index_errors ORDER BY id DESC LIMIT 1"
        ).fetchone()
        size = self.path.stat().st_size if self.path.exists() else 0
        last_run_at = None
        last_run_status = None
        if last_run is not None:
            last_run_at = _parse_dt(last_run["finished_at"] or last_run["started_at"])
            last_run_status = last_run["status"]
        return IndexStats(
            project_id=self.project_id,
            project_name=self.project_name,
            last_indexed_at=_parse_dt(last_file["ts"] if last_file else None),
            last_run_at=last_run_at,
            last_run_status=last_run_status,
            files_indexed=counts["files"],
            files_code=counts["files_code"],
            files_binary=counts["files_binary"],
            symbols=counts["symbols"],
            imports=counts["imports"],
            import_edges=counts["import_edges"],
            errors=counts["errors"],
            index_bytes=size,
            last_error=last_error["msg"] if last_error else None,
        )

    def search(self, query: str, *, limit: int = 25) -> list[SearchHit]:
        match = _fts_match(query)
        if match is None:
            return []
        hits: list[SearchHit] = []
        file_rows = self.connection.execute(
            """
            SELECT f.rel_path AS rel_path, f.kind AS kind,
                   snippet(files_fts, 1, '', '', '…', 12) AS snippet,
                   bm25(files_fts) AS score
            FROM files_fts
            JOIN files f ON f.id = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY bm25(files_fts)
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        for row in file_rows:
            hits.append(
                SearchHit(
                    kind="file",
                    project_id=self.project_id,
                    project_name=self.project_name,
                    rel_path=row["rel_path"],
                    snippet=row["snippet"] or "",
                    score=float(row["score"]),
                )
            )
        symbol_rows = self.connection.execute(
            """
            SELECT s.type AS type, s.name AS name, s.qualified_name AS qname,
                   s.line_start AS line_start, s.line_end AS line_end,
                   f.rel_path AS rel_path, bm25(symbols_fts) AS score
            FROM symbols_fts
            JOIN symbols s ON s.id = symbols_fts.rowid
            JOIN files f ON f.id = s.file_id
            WHERE symbols_fts MATCH ?
            ORDER BY bm25(symbols_fts)
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        for row in symbol_rows:
            hits.append(
                SearchHit(
                    kind="symbol",
                    project_id=self.project_id,
                    project_name=self.project_name,
                    rel_path=row["rel_path"],
                    snippet=row["qname"],
                    score=float(row["score"]),
                    symbol_type=row["type"],
                    symbol_name=row["name"],
                    qualified_name=row["qname"],
                    line_start=row["line_start"],
                    line_end=row["line_end"],
                )
            )
        hits.sort(key=lambda item: item.score)
        return hits[:limit]

    def find_symbols_named(self, name: str) -> list[SymbolRecord]:
        rows = self.connection.execute(
            """
            SELECT s.id, s.file_id, s.type, s.name, s.qualified_name,
                   s.line_start, s.line_end, s.metadata, f.rel_path
            FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE s.name = ? COLLATE NOCASE
               OR s.qualified_name = ? COLLATE NOCASE
               OR s.qualified_name LIKE ? COLLATE NOCASE
            """,
            (name, name, f"%.{name}"),
        ).fetchall()
        return [self._symbol_from_row(row) for row in rows]

    def sql_writers(self, resource: str) -> list[SymbolRecord]:
        """Return all indexed INSERT/UPDATE writers for one exact SQL resource."""
        rows = self.connection.execute(
            """
            SELECT DISTINCT s.id, s.file_id, s.type, s.name, s.qualified_name,
                   s.line_start, s.line_end, s.metadata, f.rel_path
            FROM sql_operations o
            JOIN symbols s ON s.id = o.symbol_id
            JOIN files f ON f.id = s.file_id
            WHERE o.resource = ? COLLATE NOCASE
              AND o.kind IN ('INSERT', 'UPDATE')
            ORDER BY s.qualified_name
            """,
            (resource,),
        ).fetchall()
        return [self._symbol_from_row(row) for row in rows]

    def sql_operations_for_symbol(self, symbol_id: int) -> list[dict[str, object]]:
        rows = self.connection.execute(
            "SELECT kind, resource, line, columns, predicates FROM sql_operations WHERE symbol_id = ? ORDER BY line",
            (symbol_id,),
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            try:
                columns = json.loads(row["columns"] or "[]")
            except json.JSONDecodeError:
                columns = []
            try:
                predicates = json.loads(row["predicates"] or "[]")
            except json.JSONDecodeError:
                predicates = []
            result.append({"kind": row["kind"], "resource": row["resource"], "line": row["line"], "columns": columns, "predicates": predicates})
        return result

    def find_files_named(self, stem: str) -> list[FileRecord]:
        pattern = f"%{stem}%"
        rows = self.connection.execute(
            "SELECT id, rel_path, extension, language, kind, size, mtime, hash, status, indexed_at "
            "FROM files WHERE rel_path LIKE ? COLLATE NOCASE AND kind != 'binary'",
            (pattern,),
        ).fetchall()
        return [self._file_from_row(row) for row in rows]

    def symbols_for_path(self, rel_path: str) -> list[SymbolRecord]:
        rows = self.connection.execute(
            """
            SELECT s.id, s.file_id, s.type, s.name, s.qualified_name,
                   s.line_start, s.line_end, s.metadata, f.rel_path
            FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE f.rel_path = ?
            ORDER BY s.line_start
            """,
            (rel_path,),
        ).fetchall()
        return [self._symbol_from_row(row) for row in rows]

    def text_file_sizes(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT rel_path, size FROM files WHERE kind IN ('code', 'text')"
        ).fetchall()
        return {row["rel_path"]: int(row["size"]) for row in rows}

    def neighbor_map(self) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = {}
        for src, dst, _module in self.list_edges():
            if not dst:
                continue
            adjacency.setdefault(src, set()).add(dst)
            adjacency.setdefault(dst, set()).add(src)
        return adjacency

    def outgoing_map(self) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = {}
        for src, dst, _module in self.list_edges():
            if not dst:
                continue
            adjacency.setdefault(src, set()).add(dst)
        return adjacency

    def commit(self) -> None:
        self.connection.commit()

    def _delete_fts_for_file(self, file_id: int) -> None:
        symbol_ids = self.connection.execute(
            "SELECT id FROM symbols WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        for row in symbol_ids:
            self.connection.execute("DELETE FROM symbols_fts WHERE rowid = ?", (row["id"],))
        self.connection.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))

    def _file_from_row(self, row: sqlite3.Row) -> FileRecord:
        indexed = _parse_dt(row["indexed_at"]) or utcnow()
        return FileRecord(
            id=row["id"],
            rel_path=row["rel_path"],
            extension=row["extension"],
            language=row["language"],
            kind=row["kind"],
            size=row["size"],
            mtime=row["mtime"],
            hash=row["hash"],
            status=row["status"],
            indexed_at=indexed,
        )

    def _symbol_from_row(self, row: sqlite3.Row) -> SymbolRecord:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return SymbolRecord(
            id=row["id"],
            file_id=row["file_id"],
            type=row["type"],
            name=row["name"],
            qualified_name=row["qualified_name"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            metadata=metadata,
            rel_path=row["rel_path"],
        )


_TOKEN = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]+", re.UNICODE)


def _fts_match(raw: str) -> str | None:
    tokens = [token for token in _TOKEN.findall(raw.lower()) if token]
    if not tokens:
        return None
    parts = []
    for token in tokens:
        cleaned = token.replace('"', "")
        if not cleaned:
            continue
        parts.append(f"{cleaned}*")
    return " AND ".join(parts) if parts else None
