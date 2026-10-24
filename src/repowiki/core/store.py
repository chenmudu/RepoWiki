"""persist a finished project so a restart does not need a rescan.

The wiki is the expensive part (LLM output); the project context is what
every other view reads from. Both are stored per project id so a restarted
server can rebuild its in-memory project slot from disk.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import os
import shutil
from pathlib import Path

from repowiki.core.models import ProjectContext
from repowiki.core.wiki_builder import ModuleCard, SidebarItem, Wiki, WikiPage

ARTIFACT_DIR = Path.home() / ".repowiki" / "projects"


def artifact_dir(project_id: str) -> Path:
    return ARTIFACT_DIR / project_id


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def _sidebar_to_dict(items: list[SidebarItem]) -> list[dict]:
    out = []
    for item in items:
        entry = {"title": item.title, "page_id": item.page_id}
        if item.children:
            entry["children"] = _sidebar_to_dict(item.children)
        out.append(entry)
    return out


def _sidebar_from_dict(items: list[dict]) -> list[SidebarItem]:
    return [
        SidebarItem(
            title=str(item.get("title", "")),
            page_id=str(item.get("page_id", "")),
            children=_sidebar_from_dict(item.get("children") or []),
        )
        for item in items
    ]


def _card_to_dict(card: ModuleCard) -> dict:
    data = dataclasses.asdict(card)
    # json has no tuple type; the pairs come back as lists
    data["hotspots"] = [list(pair) for pair in card.hotspots]
    data["relationships"] = [list(pair) for pair in card.relationships]
    return data


def _card_from_dict(data: dict) -> ModuleCard:
    return ModuleCard(
        name=str(data.get("name", "")),
        purpose=str(data.get("purpose", "")),
        file_count=int(data.get("file_count", 0)),
        key_symbols=list(data.get("key_symbols") or []),
        extra_symbols=int(data.get("extra_symbols", 0)),
        key_concepts=list(data.get("key_concepts") or []),
        entry_files=list(data.get("entry_files") or []),
        extra_entries=int(data.get("extra_entries", 0)),
        in_cycle=bool(data.get("in_cycle", False)),
        hotspots=[tuple(p) for p in data.get("hotspots") or []],
        relationships=[tuple(p) for p in data.get("relationships") or []],
        page_id=str(data.get("page_id", "")),
    )


def save_project(project_id: str, project: ProjectContext) -> None:
    """store the scanned project (file contents included, gzipped)."""
    payload = json.dumps(project.model_dump(), ensure_ascii=False).encode("utf-8")
    _write_atomic(artifact_dir(project_id) / "project.json.gz", gzip.compress(payload))


def load_project(project_id: str) -> ProjectContext | None:
    path = artifact_dir(project_id) / "project.json.gz"
    if not path.is_file():
        return None
    try:
        with gzip.open(path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
        return ProjectContext.model_validate(data)
    except (OSError, ValueError, TypeError):
        return None


def save_wiki(project_id: str, wiki: Wiki) -> None:
    payload = {
        "project_name": wiki.project_name,
        "pages": [dataclasses.asdict(p) for p in wiki.pages],
        "sidebar": _sidebar_to_dict(wiki.sidebar),
        "cards": [_card_to_dict(c) for c in wiki.cards],
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    _write_atomic(artifact_dir(project_id) / "wiki.json", raw)


def load_wiki(project_id: str) -> Wiki | None:
    path = artifact_dir(project_id) / "wiki.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        pages = [
            WikiPage(
                id=str(p.get("id", "")),
                title=str(p.get("title", "")),
                content=str(p.get("content", "")),
                parent_id=str(p.get("parent_id", "")),
                order=int(p.get("order", 0)),
            )
            for p in data.get("pages", [])
        ]
        return Wiki(
            pages=pages,
            sidebar=_sidebar_from_dict(data.get("sidebar") or []),
            project_name=str(data.get("project_name", "")),
            cards=[_card_from_dict(c) for c in data.get("cards") or []],
        )
    except (AttributeError, TypeError, ValueError):
        return None


def save_file_stats(project_id: str, files, max_file_size: int) -> None:
    """record path/size/mtime per scanned file, for the change detector."""
    import time

    payload = {
        "indexed_at": time.time(),
        "max_file_size": max_file_size,
        "files": [
            {"path": f.path, "size": f.size, "mtime_ns": f.mtime_ns}
            for f in files
            if f.path
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _write_atomic(artifact_dir(project_id) / "files.json", raw)


def load_file_stats(project_id: str) -> dict | None:
    path = artifact_dir(project_id) / "files.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return None
    return data


def has_artifacts(project_id: str) -> bool:
    return load_wiki(project_id) is not None or load_project(project_id) is not None


def clear_artifacts(project_id: str) -> None:
    """drop the stored artifacts of a project (used when it is deleted)."""
    path = artifact_dir(project_id)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
