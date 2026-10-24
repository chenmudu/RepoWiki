"""detect source changes after a project was indexed."""

from __future__ import annotations

from pathlib import Path

from repowiki.core.scanner import iter_candidate_paths


def detect_changes(root: str, stats: dict) -> dict:
    """compare the file stats stored at scan time with the current tree.

    ``stats`` comes from ``store.load_file_stats``:
    ``{"indexed_at": ts, "max_file_size": n, "files": [{path, size, mtime}]}``.

    Modifications and deletions are found by re-statting the known files;
    additions are files the scan never saw whose mtime is newer than the
    index. Nothing reads file contents, so a check costs one walk.
    """
    result = {"stale": False, "changed_files": 0, "sample": []}
    files = (stats or {}).get("files") or []
    if not files:
        return result

    base = Path(root)
    if not base.is_dir():
        return {"stale": True, "changed_files": len(files), "sample": [], "reason": "目录不存在"}

    indexed_at = float(stats.get("indexed_at") or 0)
    changed: list[str] = []
    known = {f.get("path"): f for f in files if f.get("path")}

    for path, stored in known.items():
        try:
            stat = (base / path).stat()
        except OSError:
            changed.append(path)
            continue
        if stat.st_size != stored.get("size") or stat.st_mtime_ns != stored.get(
            "mtime_ns"
        ):
            changed.append(path)

    max_file_size = int(stats.get("max_file_size") or 200 * 1024)
    for path, stat in iter_candidate_paths(base, max_file_size=max_file_size):
        if path in known:
            continue
        if stat.st_mtime > indexed_at:
            changed.append(path)

    result["changed_files"] = len(changed)
    result["stale"] = bool(changed)
    result["sample"] = changed[:5]
    return result
