from __future__ import annotations

from pathlib import Path


def discover_git_projects(folder: str | Path) -> list[Path]:
    """Find Git repositories directly inside a folder, including the folder itself.

    Discovery is intentionally limited to one level so choosing a broad directory
    such as Documents does not trigger an expensive recursive walk.
    """
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        return []

    candidates: list[Path] = []
    if _is_git_repository(root):
        candidates.append(root)

    try:
        children = sorted(root.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        return candidates

    candidates.extend(
        child.resolve()
        for child in children
        if child.is_dir() and _is_git_repository(child)
    )
    return candidates


def _is_git_repository(path: Path) -> bool:
    git_marker = path / ".git"
    return git_marker.is_dir() or git_marker.is_file()
