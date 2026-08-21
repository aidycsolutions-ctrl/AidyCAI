from __future__ import annotations

import sqlite3
from pathlib import Path

INDEX_SCHEMA_VERSION = 2

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    files_found INTEGER NOT NULL DEFAULT 0,
    files_code INTEGER NOT NULL DEFAULT 0,
    files_unchanged INTEGER NOT NULL DEFAULT 0,
    files_modified INTEGER NOT NULL DEFAULT 0,
    files_created INTEGER NOT NULL DEFAULT 0,
    files_deleted INTEGER NOT NULL DEFAULT 0,
    files_renamed INTEGER NOT NULL DEFAULT 0,
    symbols INTEGER NOT NULL DEFAULT 0,
    imports INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path TEXT NOT NULL UNIQUE,
    extension TEXT NOT NULL,
    language TEXT,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    hash TEXT NOT NULL,
    status TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash);
CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind);
CREATE INDEX IF NOT EXISTS idx_files_language ON files(language);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_qname ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(type);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    import_type TEXT NOT NULL,
    module TEXT NOT NULL,
    names TEXT NOT NULL DEFAULT '[]',
    alias TEXT,
    resolved_rel_path TEXT,
    line INTEGER,
    level INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_id);
CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module);

CREATE TABLE IF NOT EXISTS import_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    to_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
    to_module TEXT NOT NULL,
    UNIQUE(from_file_id, to_module)
);

CREATE TABLE IF NOT EXISTS index_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path TEXT NOT NULL,
    phase TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    run_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_errors_path ON index_errors(rel_path);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    rel_path,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    qualified_name,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

_MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS sql_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    resource TEXT NOT NULL,
    line INTEGER,
    columns TEXT NOT NULL DEFAULT '[]',
    predicates TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_sql_operations_resource_kind
    ON sql_operations(resource, kind);
CREATE INDEX IF NOT EXISTS idx_sql_operations_symbol
    ON sql_operations(symbol_id);
"""


def connect_index(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    migrate_index(connection)
    return connection


def migrate_index(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    current = 0
    if row is not None:
        version_row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
        current = int(version_row["version"]) if version_row else 0
    if current < 1:
        connection.executescript(_MIGRATION_1)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
            "VALUES (1, datetime('now'))"
        )
        current = 1
    if current < 2:
        connection.executescript(_MIGRATION_2)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
            "VALUES (2, datetime('now'))"
        )
    connection.commit()
