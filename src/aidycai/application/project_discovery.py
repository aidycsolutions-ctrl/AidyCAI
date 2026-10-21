from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aidycai.application.project_config import _expand_path
from aidycai.domain.models import Project

PROJECT_MARKERS = frozenset({
    ".git",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Pipfile",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "composer.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
})

SKIP_DIR_NAMES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "target",
    "vendor",
})

DEFAULT_SEARCH_ROOTS = (
    "~/Documentos/Proyectos_AidyC",
    "~/Documents/Proyectos_AidyC",
    "~/Documentos",
    "~/Documents",
)


@dataclass(frozen=True)
class DiscoveredProject:
    name: str
    path: Path
    markers: tuple[str, ...]
    already_registered: bool


def looks_like_project(path: Path) -> tuple[bool, tuple[str, ...]]:
    if not path.is_dir() or path.name.lower() in SKIP_DIR_NAMES:
        return False, ()
    found: list[str] = []
    try:
        entries = {child.name for child in path.iterdir()}
    except OSError:
        return False, ()
    for marker in sorted(PROJECT_MARKERS):
        if marker in entries:
            found.append(marker)
    return (bool(found), tuple(found))


def default_search_root() -> Path:
    for candidate in DEFAULT_SEARCH_ROOTS:
        path = _expand_path(candidate)
        if path.is_dir():
            return path
    return Path.cwd().resolve()


def discover_projects(
    root: str | Path,
    *,
    depth: int = 1,
    registered: list[Project] | None = None,
) -> list[DiscoveredProject]:
    """Find candidate project folders under *root* without registering them."""
    base = _expand_path(str(root))
    if not base.is_dir():
        raise FileNotFoundError(f"La carpeta no existe: {base}")
    if depth < 0:
        raise ValueError("depth debe ser >= 0")

    registered_paths = {
        project.path.resolve()
        for project in (registered or [])
        if project.path.exists()
    }
    results: list[DiscoveredProject] = []
    seen: set[Path] = set()

    def visit(directory: Path, remaining: int) -> None:
        try:
            children = sorted(
                (child for child in directory.iterdir() if not child.is_symlink()),
                key=lambda item: item.name.lower(),
            )
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.lower() in SKIP_DIR_NAMES:
                continue
            ok, markers = looks_like_project(child)
            if ok:
                resolved = child.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                results.append(
                    DiscoveredProject(
                        name=child.name,
                        path=resolved,
                        markers=markers,
                        already_registered=resolved in registered_paths,
                    )
                )
                continue
            if remaining > 0:
                visit(child, remaining - 1)

    # depth=0 checks root itself; depth=1 checks immediate children (usual workspace folder).
    if depth == 0:
        ok, markers = looks_like_project(base)
        if ok:
            resolved = base.resolve()
            results.append(
                DiscoveredProject(
                    name=base.name,
                    path=resolved,
                    markers=markers,
                    already_registered=resolved in registered_paths,
                )
            )
        return results

    visit(base, depth - 1)
    return results
