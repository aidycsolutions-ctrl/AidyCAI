from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: Path
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ScanStats:
    exists: bool
    is_dir: bool
    file_count: int = 0
    dir_count: int = 0
    total_bytes: int = 0
    skipped_dir_count: int = 0
    extensions: dict[str, int] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.exists:
            return "missing"
        if not self.is_dir:
            return "not-a-directory"
        return "ok"


@dataclass(frozen=True)
class ProjectInfo:
    project: Project
    settings: dict[str, str]
    scan: ScanStats

    @property
    def status(self) -> str:
        if not self.project.active:
            return "inactive"
        return self.scan.status
