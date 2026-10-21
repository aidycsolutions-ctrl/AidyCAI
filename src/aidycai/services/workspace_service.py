from __future__ import annotations

from pathlib import Path
from typing import Iterable

DEFAULT_IGNORED_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules", ".pytest_cache",
})

TEXT_EXTENSIONS = frozenset({
    ".py", ".pyw", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".txt", ".md", ".sql", ".sh",
    ".bat", ".ps1", ".xml", ".csv", ".env", ".gitignore",
})


def visible_children(path: Path, ignored_dirs: Iterable[str] = DEFAULT_IGNORED_DIRS) -> list[Path]:
    """Return a stable, safe file-tree listing without traversing ignored folders."""
    ignored = {name.lower() for name in ignored_dirs}
    try:
        children = [item for item in path.iterdir() if not item.is_symlink()]
    except OSError:
        return []
    children = [item for item in children if not (item.is_dir() and item.name.lower() in ignored)]
    return sorted(children, key=lambda item: (not item.is_dir(), item.name.lower()))


def is_probably_text(path: Path) -> bool:
    if path.name in {".env", ".gitignore"}:
        return True
    return path.suffix.lower() in TEXT_EXTENSIONS


def read_text_file(path: Path, max_bytes: int = 2_000_000) -> str:
    """Read a source/config text file with a bounded size."""
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"Archivo demasiado grande para el editor ({size:,} bytes).")
    return path.read_text(encoding="utf-8", errors="replace")


def write_text_file(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def resolve_user_path(value: str) -> Path:
    from aidycai.application.project_config import _expand_path

    return _expand_path(value)
