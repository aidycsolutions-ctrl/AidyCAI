from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from aidycai.domain.index_models import FileAnalysis, IndexStats, IndexSummary, SearchHit, WalkedFile
from aidycai.domain.models import Project, ScanStats
from aidycai.domain.context_models import AIHandoff


class ProjectRepository(Protocol):
    def add(self, project: Project) -> None: ...

    def remove(self, project_id: str) -> None: ...

    def update(self, project: Project) -> None: ...

    def list_all(self) -> list[Project]: ...

    def get_by_id(self, project_id: str) -> Project | None: ...

    def find(self, name_or_id: str) -> Project | None: ...

    def get_settings(self, project_id: str) -> dict[str, str]: ...

    def set_setting(self, project_id: str, key: str, value: str) -> None: ...

    def delete_setting(self, project_id: str, key: str) -> None: ...


class Scanner(Protocol):
    def scan(self, path: Path, extra_excludes: Sequence[str] = ()) -> ScanStats: ...

    def iter_files(self, path: Path, extra_excludes: Sequence[str] = ()) -> Sequence[WalkedFile]: ...


class LanguageAnalyzer(Protocol):
    language: str

    def analyze(self, rel_path: str, source: str) -> FileAnalysis: ...


class ProjectIndex(Protocol):
    """Persisted project intelligence. Future Context Engine depends on this, not on LLMs."""

    def index_project(self, name_or_id: str) -> IndexSummary: ...

    def search(self, name_or_id: str, query: str, *, limit: int = 25) -> list[SearchHit]: ...

    def stats(self, name_or_id: str) -> IndexStats: ...


class ContextEnginePort(Protocol):
    """Task → ContextBundle. Providers consume the bundle later; they are not part of Core."""

    def build(self, name_or_id: str, task: str) -> object: ...


class AIHandoffConsumer(Protocol):
    """Boundary for a future provider adapter; the Core does not implement one."""

    def consume(self, handoff: AIHandoff) -> object: ...
