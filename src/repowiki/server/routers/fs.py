"""local directory browsing, so the web UI can pick a project folder."""

from __future__ import annotations

import string
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


def _drives() -> list[str]:
    """the mount points of this machine (Windows: drive letters, else "/")."""
    if Path("C:/").exists() and hasattr(Path("C:/"), "drive"):
        found = []
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            if root.exists():
                found.append(f"{letter}:\\")
        return found
    return ["/"]


def _list_dirs(root: Path) -> list[dict]:
    entries = []
    try:
        for child in root.iterdir():
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child)})
    except (PermissionError, OSError):
        return []
    entries.sort(key=lambda e: e["name"].lower())
    return entries


@router.get("/fs/browse")
def browse(path: str = ""):
    """list the sub-directories of a path, plus its parent and the drives.

    The web UI uses this for the folder picker: remembering absolute paths
    by hand is the one thing the tool must not ask of the user.
    """
    raw = (path or "").strip().strip('"')
    if not raw:
        return {"path": "", "parent": "", "dirs": [], "drives": _drives()}

    root = Path(raw)
    if not root.is_dir():
        return JSONResponse({"error": f"目录不存在：{raw}"}, status_code=400)

    resolved = root.resolve()
    parent = resolved.parent
    # a drive root is its own parent; there is nowhere above it
    parent_path = "" if str(parent) == str(resolved) else str(parent)

    return {
        "path": str(resolved),
        "parent": parent_path,
        "dirs": _list_dirs(resolved),
        "drives": _drives(),
    }
