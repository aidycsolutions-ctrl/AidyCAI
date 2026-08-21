from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aidycai import __version__
from aidycai.infrastructure.paths import ENV_DATA_DIR, DataLayout


@dataclass(frozen=True)
class SystemInfo:
    version: str
    data_dir: Path
    database_path: Path
    projects_dir: Path
    logs_dir: Path
    cache_dir: Path
    project_count: int
    using_local_app_data: bool


def build_system_info(layout: DataLayout, project_count: int) -> SystemInfo:
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    using_local = False
    if not override and local_app_data:
        try:
            using_local = layout.root.is_relative_to(Path(local_app_data))
        except (ValueError, OSError):
            using_local = False

    return SystemInfo(
        version=__version__,
        data_dir=layout.root,
        database_path=layout.database_path,
        projects_dir=layout.projects_dir,
        logs_dir=layout.logs_dir,
        cache_dir=layout.cache_dir,
        project_count=project_count,
        using_local_app_data=using_local,
    )
