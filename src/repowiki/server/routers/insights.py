"""zero-LLM project insights: repo map and diff review order."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from repowiki.server.app import ensure_loaded
from repowiki.server.models import DiffRequest

router = APIRouter()


def _project_or_404(project_id: str):
    proj = ensure_loaded(project_id)
    if not proj or proj.get("project") is None:
        return None, JSONResponse({"error": "项目不存在"}, status_code=404)
    return proj["project"], None


@router.get("/project/{project_id}/map")
def get_repo_map(project_id: str, top: int = 50):
    """files ranked by dependency PageRank, the same analysis `repowiki map` prints."""
    project, err = _project_or_404(project_id)
    if err:
        return err
    if top <= 0:
        return JSONResponse({"error": "top 必须大于 0"}, status_code=400)

    from repowiki.core.graph import DependencyGraph

    ranked = DependencyGraph.build_from_project(project).rank_files()
    entries = [
        {
            "rank": i + 1,
            # scan paths are platform-native; publish canonical forward-slash form
            "path": p.replace(os.sep, "/"),
            "score": round(score, 6),
            "language": next((f.language for f in project.files if f.path == p), "unknown"),
            "lines": next((f.lines for f in project.files if f.path == p), 0),
        }
        for i, (p, score) in enumerate(ranked[:top])
    ]
    return {"root": project.name, "file_count": len(project.files), "entries": entries}


@router.post("/project/{project_id}/diff")
def get_diff_review(project_id: str, req: DiffRequest):
    """changed files in review order, the same analysis `repowiki diff` prints."""
    project, err = _project_or_404(project_id)
    if err:
        return err
    refspec = req.refspec.strip()
    if not refspec:
        return JSONResponse({"error": "refspec 不能为空"}, status_code=400)

    from repowiki.core.diff import build_diff_report
    from repowiki.core.graph import DependencyGraph

    graph = DependencyGraph.build_from_project(project)
    try:
        report = build_diff_report(project.root, refspec, graph)
    except Exception as exc:
        detail = f"无法在 {project.name} 上生成 diff（{refspec}）：{exc}"
        if _is_shallow_clone(project.root):
            detail += (
                "。该仓库是浅克隆（depth 1），只能解析浅历史中的 ref；"
                "扫描本地完整克隆可解锁任意 refspec。"
            )
        return JSONResponse({"error": detail}, status_code=400)

    entries = [
        {
            "path": f.path.replace(os.sep, "/"),
            "change": f.change,
            **({"old_path": f.old_path.replace(os.sep, "/")} if f.old_path else {}),
            "rank": f.rank or None,
            "score": round(f.score, 6),
            "direct_dependents": f.direct_dependents,
            "transitive_dependents": f.transitive_dependents,
        }
        for f in report.files
    ]
    return {
        "root": project.name,
        "refspec": refspec,
        "file_count": len(project.files),
        "changed": len(entries),
        "entries": entries,
    }


def _is_shallow_clone(root: str) -> bool:
    try:
        out = subprocess.run(
            [
                "git", "-c", f"safe.directory={Path(root).resolve().as_posix()}",
                "-C", root, "rev-parse", "--is-shallow-repository",
            ],
            capture_output=True,
            timeout=5,
        )
        return out.stdout.decode().strip() == "true"
    except Exception:
        return False
