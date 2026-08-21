from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "AIDYCAI_DATA_DIR"
ENV_SKIP_SEED = "AIDYCAI_SKIP_SEED"
APP_DIR_NAME = "AIDYCAI"


def get_data_dir() -> Path:
    """Resolve the runtime data directory.

    Honor AIDYCAI_DATA_DIR first (tests and custom installs), otherwise
    %LOCALAPPDATA%\\AIDYCAI on Windows / ~/.local/share/AIDYCAI elsewhere.
    """
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / APP_DIR_NAME

    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg) / APP_DIR_NAME

    return Path.home() / ".local" / "share" / APP_DIR_NAME


def skip_seed() -> bool:
    value = os.environ.get(ENV_SKIP_SEED, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


class DataLayout:
    """Known subfolders under the data directory."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or get_data_dir()).resolve()

    @property
    def database_dir(self) -> Path:
        return self.root / "database"

    @property
    def database_path(self) -> Path:
        return self.database_dir / "aidycai.sqlite"

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def project_data_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def project_index_path(self, project_id: str) -> Path:
        return self.project_data_dir(project_id) / "index.sqlite"

    def ensure(self) -> None:
        for path in (
            self.root,
            self.database_dir,
            self.projects_dir,
            self.logs_dir,
            self.cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
