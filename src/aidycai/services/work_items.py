from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class WorkItem:
    id: int
    kind: str
    title: str
    description: str = ""
    project: str = ""
    status: str = "Pendiente"
    priority: str = "Media"
    created_at: str = ""


class WorkItemStore:
    """Small local JSON store for AIDYCAI's tasks, orders and incidents."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path(__file__).resolve().parents[3] / "data" / "work_items.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[WorkItem]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [WorkItem(**item) for item in raw if isinstance(item, dict)]

    def save(self, items: list[WorkItem]) -> None:
        self.path.write_text(
            json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create(self, kind: str, title: str, description: str = "", project: str = "", priority: str = "Media") -> WorkItem:
        items = self.load()
        next_id = max((item.id for item in items), default=0) + 1
        item = WorkItem(
            id=next_id,
            kind=kind,
            title=title.strip(),
            description=description.strip(),
            project=project.strip(),
            priority=priority,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        items.append(item)
        self.save(items)
        return item

    def update_status(self, item_id: int, status: str) -> bool:
        items = self.load()
        for item in items:
            if item.id == item_id:
                item.status = status
                self.save(items)
                return True
        return False

    def delete(self, item_id: int) -> bool:
        items = self.load()
        filtered = [item for item in items if item.id != item_id]
        if len(filtered) == len(items):
            return False
        self.save(filtered)
        return True
