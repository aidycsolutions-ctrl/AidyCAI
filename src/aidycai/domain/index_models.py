from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WalkedFile:
    rel_path: str
    size: int
    mtime: float
    extension: str


@dataclass(frozen=True)
class FileRecord:
    id: int
    rel_path: str
    extension: str
    language: str | None
    kind: str
    size: int
    mtime: float
    hash: str
    status: str
    indexed_at: datetime


@dataclass(frozen=True)
class SymbolRecord:
    id: int
    file_id: int
    type: str
    name: str
    qualified_name: str
    line_start: int | None
    line_end: int | None
    metadata: dict[str, Any]
    rel_path: str = ""


@dataclass(frozen=True)
class ImportRecord:
    file_id: int
    import_type: str
    module: str
    names: list[str]
    alias: str | None
    resolved_rel_path: str | None
    line: int | None
    level: int = 0


@dataclass(frozen=True)
class ExtractedSymbol:
    type: str
    name: str
    qualified_name: str
    line_start: int | None
    line_end: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedImport:
    import_type: str
    module: str
    names: tuple[str, ...] = ()
    alias: str | None = None
    line: int | None = None
    level: int = 0


@dataclass(frozen=True)
class FileAnalysis:
    symbols: tuple[ExtractedSymbol, ...] = ()
    imports: tuple[ExtractedImport, ...] = ()


@dataclass(frozen=True)
class SearchHit:
    kind: str
    project_id: str
    project_name: str
    rel_path: str
    snippet: str
    score: float
    symbol_type: str | None = None
    symbol_name: str | None = None
    qualified_name: str | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass(frozen=True)
class IndexSummary:
    project_id: str
    project_name: str
    files_found: int
    files_code: int
    files_text: int
    files_binary: int
    files_unchanged: int
    files_modified: int
    files_created: int
    files_deleted: int
    files_renamed: int
    symbols: int
    imports: int
    errors: int
    duration_s: float = 0.0


@dataclass(frozen=True)
class IndexStats:
    project_id: str
    project_name: str
    last_indexed_at: datetime | None
    last_run_at: datetime | None
    last_run_status: str | None
    files_indexed: int
    files_code: int
    files_binary: int
    symbols: int
    imports: int
    import_edges: int
    errors: int
    index_bytes: int
    last_error: str | None = None
