from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from aidycai.domain.exceptions import (
    DuplicateProjectError,
    InvalidPathError,
    ProjectNotFoundError,
)
from aidycai.domain.models import Project, ProjectInfo
from aidycai.domain.ports import ProjectRepository, Scanner

_ID_RE = re.compile(r"[^a-z0-9]+")
EXCLUDE_SETTING_KEY = "excludes"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def make_project_id(name: str) -> str:
    slug = _ID_RE.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise InvalidPathError("El nombre del proyecto no produce un id válido.")
    return slug


def parse_excludes(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(loaded, list):
        return [str(item).strip() for item in loaded if str(item).strip()]
    return []


class ProjectRegistry:
    def __init__(self, repository: ProjectRepository, scanner: Scanner) -> None:
        self._repository = repository
        self._scanner = scanner

    def list_projects(self) -> list[Project]:
        return self._repository.list_all()

    def add(
        self,
        name: str,
        path: str | Path,
        *,
        extra_excludes: list[str] | None = None,
        active: bool = True,
        require_existing: bool = True,
    ) -> Project:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise InvalidPathError("El nombre del proyecto no puede estar vacío.")

        resolved = self._validate_path(path, require_existing=require_existing)
        project_id = make_project_id(cleaned_name)
        self._assert_available(project_id, cleaned_name, resolved)

        now = utcnow()
        project = Project(
            id=project_id,
            name=cleaned_name,
            path=resolved,
            active=active,
            created_at=now,
            updated_at=now,
        )
        self._repository.add(project)
        if extra_excludes:
            self._repository.set_setting(
                project.id,
                EXCLUDE_SETTING_KEY,
                json.dumps(extra_excludes),
            )
        return project

    def remove(self, name_or_id: str) -> Project:
        project = self._require(name_or_id)
        self._repository.remove(project.id)
        return project

    def set_path(self, name_or_id: str, path: str | Path, *, require_existing: bool = True) -> Project:
        project = self._require(name_or_id)
        resolved = self._validate_path(path, require_existing=require_existing)
        duplicate_path = next(
            (item for item in self._repository.list_all() if item.path == resolved and item.id != project.id),
            None,
        )
        if duplicate_path is not None:
            raise DuplicateProjectError(f"La ruta ya está registrada como '{duplicate_path.name}'.")

        updated = Project(
            id=project.id,
            name=project.name,
            path=resolved,
            active=project.active,
            created_at=project.created_at,
            updated_at=utcnow(),
        )
        self._repository.update(updated)
        return updated

    def set_active(self, name_or_id: str, active: bool) -> Project:
        project = self._require(name_or_id)
        updated = Project(
            id=project.id,
            name=project.name,
            path=project.path,
            active=active,
            created_at=project.created_at,
            updated_at=utcnow(),
        )
        self._repository.update(updated)
        return updated

    def info(self, name_or_id: str) -> ProjectInfo:
        project = self._require(name_or_id)
        settings = self._repository.get_settings(project.id)
        extra = parse_excludes(settings.get(EXCLUDE_SETTING_KEY))
        scan = self._scanner.scan(project.path, extra)
        return ProjectInfo(project=project, settings=settings, scan=scan)

    def find(self, name_or_id: str) -> Project | None:
        return self._repository.find(name_or_id.strip())

    def path_exists(self, name_or_id: str) -> bool:
        project = self._require(name_or_id)
        return project.path.exists()

    def extra_excludes(self, name_or_id: str) -> list[str]:
        project = self._require(name_or_id)
        settings = self._repository.get_settings(project.id)
        return parse_excludes(settings.get(EXCLUDE_SETTING_KEY))

    def get_settings(self, name_or_id: str) -> dict[str, str]:
        project = self._require(name_or_id)
        return self._repository.get_settings(project.id)

    def set_setting(self, name_or_id: str, key: str, value: str) -> None:
        project = self._require(name_or_id)
        self._repository.set_setting(project.id, key, value)

    def require(self, name_or_id: str) -> Project:
        return self._require(name_or_id)

    def _require(self, name_or_id: str) -> Project:
        project = self._repository.find(name_or_id.strip())
        if project is None:
            raise ProjectNotFoundError(f"No hay un proyecto registrado como '{name_or_id}'.")
        return project

    def _assert_available(self, project_id: str, name: str, path: Path) -> None:
        if self._repository.get_by_id(project_id) is not None:
            raise DuplicateProjectError(f"Ya existe un proyecto con id '{project_id}'.")
        by_name = self._repository.find(name)
        if by_name is not None:
            raise DuplicateProjectError(f"Ya existe un proyecto llamado '{by_name.name}'.")
        for item in self._repository.list_all():
            if item.path == path:
                raise DuplicateProjectError(f"La ruta ya está registrada como '{item.name}'.")

    def _validate_path(self, path: str | Path, *, require_existing: bool) -> Path:
        raw = Path(path).expanduser()
        try:
            resolved = raw.resolve()
        except OSError as exc:
            raise InvalidPathError(f"No se pudo resolver la ruta: {path}") from exc
        if require_existing:
            if not resolved.exists():
                raise InvalidPathError(f"La ruta no existe: {resolved}")
            if not resolved.is_dir():
                raise InvalidPathError(f"La ruta no es un directorio: {resolved}")
        return resolved
