from __future__ import annotations

from pathlib import Path


def resolve_python_import(importer_rel: str, module: str, level: int, known_paths: set[str]) -> str | None:
    """Resolve a Python import to a project-relative path when possible.

    Limitations: no sys.path, no namespace packages, no dynamic imports,
    no installed third-party packages, star-imports are not expanded.
    """
    if level:
        importer_dir = Path(importer_rel).parent
        parts = list(importer_dir.parts)
        climb = level - 1
        if climb:
            if climb > len(parts):
                return None
            parts = parts[: len(parts) - climb]
        base = Path(*parts) if parts else Path()
        extra = module.replace(".", "/") if module else ""
        candidate = base / extra if extra else base
    else:
        if not module:
            return None
        candidate = Path(module.replace(".", "/"))

    posix = candidate.as_posix().lstrip("./")
    options = []
    if posix and posix != ".":
        options.extend([f"{posix}.py", f"{posix}/__init__.py"])
    else:
        options.append("__init__.py")
    for option in options:
        normalized = option.lstrip("/")
        if normalized in known_paths:
            return normalized
    return None
