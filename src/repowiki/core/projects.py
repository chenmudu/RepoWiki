"""persistent registry of the projects this machine has indexed.

The server keeps a project's working copy in memory, so a restart loses it.
The registry remembers what was scanned (path or url) plus the metadata the
home page lists, so a project can be re-opened from history later.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_FILENAME = "projects.json"
_REGISTRY_DIR = Path.home() / ".repowiki"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ProjectRecord:
    """one indexed project; `path` xor `url` says where it came from."""

    id: str
    name: str = ""
    path: str = ""
    url: str = ""
    file_count: int = 0
    total_lines: int = 0
    language: str = "zh"
    status: str = "done"
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


class ProjectRegistry:
    """json-file registry of the projects this machine has indexed."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _REGISTRY_DIR / REGISTRY_FILENAME
        self._records: dict[str, ProjectRecord] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in data.get("projects", []):
            if not isinstance(item, dict) or "id" not in item:
                continue
            known = {k: v for k, v in item.items() if k in ProjectRecord.__dataclass_fields__}
            self._records[known["id"]] = ProjectRecord(**known)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"projects": [asdict(r) for r in self._records.values()]}
        # write-then-rename so a crash mid-write cannot corrupt the registry
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, self.path)

    def list(self) -> list[ProjectRecord]:
        return sorted(self._records.values(), key=lambda r: r.updated_at, reverse=True)

    def get(self, project_id: str) -> ProjectRecord | None:
        return self._records.get(project_id)

    def find_by_source(self, path: str = "", url: str = "") -> ProjectRecord | None:
        """the record of a previously indexed repo, matched on its source."""
        for record in self.list():
            if path and record.path == path:
                return record
            if url and record.url == url:
                return record
        return None

    def upsert(self, record: ProjectRecord) -> ProjectRecord:
        existing = self._records.get(record.id)
        if existing:
            record.created_at = existing.created_at
        if not record.created_at:
            record.created_at = _now()
        record.updated_at = _now()
        self._records[record.id] = record
        self.save()
        return record

    def remove(self, project_id: str) -> None:
        if self._records.pop(project_id, None) is not None:
            self.save()
