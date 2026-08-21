from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path

from aidycai.domain.index_models import WalkedFile
from aidycai.domain.models import ScanStats

DEFAULT_EXCLUDES = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


class FileSystemScanner:
    """Shallow inventory of a project tree. No AST, no indexing."""

    def __init__(self, default_excludes: frozenset[str] | None = None) -> None:
        self.default_excludes = default_excludes or DEFAULT_EXCLUDES

    def scan(self, path: Path, extra_excludes: Sequence[str] = ()) -> ScanStats:
        resolved = Path(path)
        if not resolved.exists():
            return ScanStats(exists=False, is_dir=False)
        if not resolved.is_dir():
            return ScanStats(exists=True, is_dir=False)

        excludes = self._exclude_names(extra_excludes)
        file_count = 0
        dir_count = 0
        total_bytes = 0
        skipped_dir_count = 0
        extensions: dict[str, int] = {}

        for dirpath, dirnames, filenames in os.walk(resolved, topdown=True, followlinks=False):
            skipped = [name for name in dirnames if name.lower() in excludes]
            skipped_dir_count += len(skipped)
            dirnames[:] = [name for name in dirnames if name.lower() not in excludes]
            dir_count += len(dirnames)

            for filename in filenames:
                if filename.lower() in excludes:
                    continue
                file_count += 1
                file_path = Path(dirpath) / filename
                try:
                    total_bytes += file_path.stat().st_size
                except OSError:
                    pass
                ext = file_path.suffix.lower() or "(none)"
                extensions[ext] = extensions.get(ext, 0) + 1

        return ScanStats(
            exists=True,
            is_dir=True,
            file_count=file_count,
            dir_count=dir_count,
            total_bytes=total_bytes,
            skipped_dir_count=skipped_dir_count,
            extensions=dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        )

    def iter_files(self, path: Path, extra_excludes: Sequence[str] = ()) -> list[WalkedFile]:
        resolved = Path(path)
        if not resolved.exists() or not resolved.is_dir():
            return []
        return list(self._iter_files(resolved, extra_excludes))

    def _exclude_names(self, extra_excludes: Sequence[str]) -> set[str]:
        excludes = {name.lower() for name in self.default_excludes}
        excludes.update(name.lower() for name in extra_excludes if name.strip())
        return excludes

    def _iter_files(self, resolved: Path, extra_excludes: Sequence[str]) -> Iterator[WalkedFile]:
        excludes = self._exclude_names(extra_excludes)
        for dirpath, dirnames, filenames in os.walk(resolved, topdown=True, followlinks=False):
            dirnames[:] = [name for name in dirnames if name.lower() not in excludes]
            current = Path(dirpath)
            for filename in filenames:
                if filename.lower() in excludes:
                    continue
                file_path = current / filename
                try:
                    stat = file_path.stat()
                except OSError:
                    continue
                yield WalkedFile(
                    rel_path=file_path.relative_to(resolved).as_posix(),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    extension=file_path.suffix.lower(),
                )
