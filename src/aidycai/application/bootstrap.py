from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType

from aidycai.application.context_engine import ContextEngine
from aidycai.application.defaults import DEFAULT_PROJECTS
from aidycai.application.project_actions import ProjectActions, serialize_actions
from aidycai.application.indexer import IndexService
from aidycai.application.registry import ProjectRegistry, utcnow
from aidycai.application.system import SystemInfo, build_system_info
from aidycai.domain.exceptions import DuplicateProjectError, InvalidPathError
from aidycai.domain.models import Project
from aidycai.infrastructure.database import connect, migrate
from aidycai.infrastructure.paths import DataLayout, skip_seed
from aidycai.infrastructure.project_repository import SqliteProjectRepository
from aidycai.infrastructure.scanner import FileSystemScanner

logger = logging.getLogger("aidycai")


@dataclass
class AppContext:
    layout: DataLayout
    registry: ProjectRegistry
    _connection: object

    def system_info(self) -> SystemInfo:
        return build_system_info(self.layout, len(self.registry.list_projects()))

    def index_service(self) -> IndexService:
        return IndexService(self.layout, self.registry, FileSystemScanner())

    def context_engine(self) -> ContextEngine:
        return ContextEngine(self.layout, self.registry)

    def ensure_project_data(self, project_id: str) -> None:
        self.layout.project_data_dir(project_id).mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        connection = self._connection
        if connection is not None:
            connection.commit()
            connection.close()
            self._connection = None

    def __enter__(self) -> AppContext:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is None:
            connection = self._connection
            if connection is not None:
                connection.commit()
        else:
            connection = self._connection
            if connection is not None:
                connection.rollback()
        self.close()


def configure_logging(layout: DataLayout) -> None:
    layout.ensure()
    log_file = layout.logs_dir / "aidycai.log"
    if logger.handlers:
        return
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def open_app(layout: DataLayout | None = None, *, seed: bool | None = None) -> AppContext:
    resolved = layout or DataLayout()
    resolved.ensure()
    configure_logging(resolved)
    connection = connect(resolved.database_path)
    migrate(connection)
    repository = SqliteProjectRepository(connection)
    registry = ProjectRegistry(repository, FileSystemScanner())
    context = AppContext(layout=resolved, registry=registry, _connection=connection)
    should_seed = skip_seed() is False if seed is None else seed
    if should_seed:
        seed_default_projects(context)
    repair_default_project_paths(context)
    return context


def seed_default_projects(context: AppContext) -> list[Project]:
    if context.registry.list_projects():
        return []
    seeded: list[Project] = []
    for spec in DEFAULT_PROJECTS:
        try:
            project = context.registry.add(
                spec.name,
                spec.path,
                extra_excludes=list(spec.extra_excludes),
            )
        except (DuplicateProjectError, InvalidPathError) as exc:
            logger.warning("No se pudo registrar %s: %s", spec.name, exc)
            continue
        context.ensure_project_data(project.id)
        if spec.actions != ProjectActions():
            context.registry.set_setting(project.id, "actions", serialize_actions(spec.actions))
        logger.info("Registrado proyecto por defecto %s -> %s", project.name, project.path)
        seeded.append(project)
    return seeded


def repair_default_project_paths(context: AppContext) -> None:
    """Repair only stale built-in paths when the new default path exists.

    This does not overwrite a valid custom project path.
    """
    current = {p.id: p for p in context.registry.list_projects()}
    for spec in DEFAULT_PROJECTS:
        project = current.get(spec.name.lower().replace(" ", "-"))
        if project is None:
            continue
        if project.path.exists():
            continue
        if not spec.path.exists():
            continue
        try:
            context.registry.set_path(project.id, spec.path, require_existing=True)
            context.ensure_project_data(project.id)
            context.registry.set_setting(project.id, "actions", serialize_actions(spec.actions))
            logger.info("Ruta reparada para %s -> %s", project.name, spec.path)
        except Exception as exc:
            logger.warning("No se pudo reparar la ruta de %s: %s", project.name, exc)
