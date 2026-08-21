from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aidycai.domain.models import Project


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        path=Path(row["path"]),
        active=bool(row["active"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


class SqliteProjectRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, project: Project) -> None:
        self._connection.execute(
            """
            INSERT INTO projects (id, name, path, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project.id,
                project.name,
                str(project.path),
                1 if project.active else 0,
                _iso(project.created_at),
                _iso(project.updated_at),
            ),
        )

    def remove(self, project_id: str) -> None:
        self._connection.execute(
            "DELETE FROM projects WHERE id = ?",
            (project_id,),
        )

    def update(self, project: Project) -> None:
        self._connection.execute(
            """
            UPDATE projects
            SET name = ?, path = ?, active = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                project.name,
                str(project.path),
                1 if project.active else 0,
                _iso(project.updated_at),
                project.id,
            ),
        )

    def list_all(self) -> list[Project]:
        rows = self._connection.execute(
            "SELECT id, name, path, active, created_at, updated_at "
            "FROM projects ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [row_to_project(row) for row in rows]

    def get_by_id(self, project_id: str) -> Project | None:
        row = self._connection.execute(
            "SELECT id, name, path, active, created_at, updated_at "
            "FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return row_to_project(row) if row else None

    def find(self, name_or_id: str) -> Project | None:
        row = self._connection.execute(
            "SELECT id, name, path, active, created_at, updated_at "
            "FROM projects WHERE id = ? OR name = ? COLLATE NOCASE",
            (name_or_id, name_or_id),
        ).fetchone()
        return row_to_project(row) if row else None

    def get_settings(self, project_id: str) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT key, value FROM project_settings WHERE project_id = ? ORDER BY key",
            (project_id,),
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_setting(self, project_id: str, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO project_settings (project_id, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(project_id, key) DO UPDATE SET value = excluded.value
            """,
            (project_id, key, value),
        )

    def delete_setting(self, project_id: str, key: str) -> None:
        self._connection.execute(
            "DELETE FROM project_settings WHERE project_id = ? AND key = ?",
            (project_id, key),
        )
