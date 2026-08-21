from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Real paths discovered on this machine. AIDYCAI stores the path, never a copy.


@dataclass(frozen=True)
class DefaultProject:
    name: str
    path: Path
    extra_excludes: tuple[str, ...] = ()


DEFAULT_PROJECTS: tuple[DefaultProject, ...] = (
    DefaultProject(
        name="AIDYC",
        path=Path(r"C:\Users\USUARIO\OneDrive\Documents\Aidyc"),
    ),
    DefaultProject(
        name="AIDYCWeb",
        path=Path(r"C:\Users\USUARIO\OneDrive\Documents\AidyCWeb\AidyC-web"),
        extra_excludes=("uploads",),
    ),
    DefaultProject(
        name="catalog-studio",
        path=Path(r"C:\Users\USUARIO\OneDrive\Documents\Deuna\catalog-studio"),
    ),
    DefaultProject(
        name="deunacolombia",
        path=Path(r"C:\Users\USUARIO\OneDrive\Documents\Deuna\deunacolombia"),
    ),
)
