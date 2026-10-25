"""detect source changes after a project was indexed."""

from __future__ import annotations

import subprocess
from pathlib import Path

from repowiki.core.scanner import iter_candidate_paths

# a change to one of these invalidates the module grouping itself, so the
# rebuild has to regenerate every page instead of only the touched modules
_BUILD_CONFIGS = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "tsconfig.json",
    "vite.config.ts",
    "webpack.config.js",
    "rollup.config.js",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Makefile",
    "Dockerfile",
    "CMakeLists.txt",
}


def detect_changes(root: str, stats: dict) -> dict:
    """compare the file stats stored at scan time with the current tree.

    ``stats`` comes from ``store.load_file_stats``:
    ``{"indexed_at": ts, "max_file_size": n, "files": [{path, size, mtime_ns}]}``.

    Modifications and deletions are found by re-statting the known files;
    additions are files the scan never saw whose mtime is newer than the
    index. Nothing reads file contents, so a check costs one walk.
    """
    result = {"stale": False, "changed_files": 0, "sample": [], "deleted": 0}
    files = (stats or {}).get("files") or []
    if not files:
        return result

    base = Path(root)
    if not base.is_dir():
        return {
            "stale": True,
            "changed_files": len(files),
            "sample": [],
            "deleted": len(files),
            "reason": "目录不存在",
        }

    indexed_at = float(stats.get("indexed_at") or 0)
    changed: list[str] = []
    deleted: list[str] = []
    known = {f.get("path"): f for f in files if f.get("path")}

    for path, stored in known.items():
        try:
            stat = (base / path).stat()
        except OSError:
            changed.append(path)
            deleted.append(path)
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
    result["deleted"] = len(deleted)
    return result


def _git_out(root: str, *args: str) -> str:
    """stdout of a git command, or "" when git has nothing useful to say."""
    safe_root = Path(root).resolve().as_posix()
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={safe_root}", "-C", root, *args],
        capture_output=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace")


def head_commit(root: str) -> str:
    """the commit a working tree points at, "" when this is not a repo."""
    return _git_out(root, "rev-parse", "--short", "HEAD").strip()


def commit_at(root: str, when: str) -> str:
    """the newest commit made at or before an ISO timestamp.

    Reconstructs the baseline of a project indexed before its commit was
    recorded: the tree the scan saw was the last commit made at that moment.
    """
    if not when:
        return ""
    return _git_out(root, "rev-list", "-1", f"--before={when}", "HEAD").strip()[:12]


def changes_since(root: str, commit: str) -> list[tuple[str, str]] | None:
    """(status, path) pairs since ``commit``, untracked files included.

    ``None`` means git could not answer — not a repo, or a baseline that no
    longer resolves — so the caller has to fall back to file stats.
    """
    if not commit:
        return None
    from repowiki.core.diff import diff_files

    try:
        changed = [(s, p) for s, p, _ in diff_files(root, commit)]
    except RuntimeError:
        return None
    untracked = _git_out(root, "ls-files", "--others", "--exclude-standard").splitlines()
    changed += [("A", p.strip()) for p in untracked if p.strip()]
    return changed


def classify(changes: list[tuple[str, str]], total_files: int = 0) -> tuple[str, str]:
    """how a rebuild has to cover these changes, and why, in the UI's language."""
    if not changes:
        return ("incremental", "")
    for status, path in changes:
        if status in ("D", "R"):
            return ("full", "有文件被删除或重命名，模块划分需要重建")
        if Path(path).name in _BUILD_CONFIGS or path.startswith(".github/workflows/"):
            return ("full", "构建配置发生变化")
    if total_files and len(changes) * 2 > total_files:
        return ("full", f"{len(changes)} 个文件变化，超过仓库的一半")
    return ("incremental", "只有新增和修改")


def detect_drift(
    root: str,
    *,
    commit: str = "",
    indexed_at: str = "",
    stats: dict | None = None,
    total_files: int = 0,
) -> dict:
    """what moved since the project was indexed, and what a rebuild costs.

    Git answers when it can: the recorded baseline commit, or for a project
    indexed before commits were stored, the commit that was current then. File
    stats are the fallback for a directory git does not track.
    """
    if not Path(root).is_dir():
        return {
            "stale": True,
            "changed_files": total_files,
            "sample": [],
            "reindex_mode": "full",
            "reason": "目录不存在",
        }

    changes = changes_since(root, commit or commit_at(root, indexed_at))
    if changes is not None:
        mode, reason = classify(changes, total_files)
        return {
            "stale": bool(changes),
            "changed_files": len(changes),
            "sample": [p for _, p in changes[:5]],
            "reindex_mode": mode,
            "reason": reason,
        }

    if not stats:
        return {"stale": False, "changed_files": 0, "sample": [], "deleted": 0}
    result = detect_changes(root, stats)
    result["reindex_mode"] = "full" if result.get("deleted") else "incremental"
    return result
