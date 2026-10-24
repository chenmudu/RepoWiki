"""scan and project management endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, replace

from fastapi import APIRouter, BackgroundTasks, Header
from fastapi.responses import JSONResponse, StreamingResponse

from repowiki.config import Config, resolve_model
from repowiki.core.projects import ProjectRecord
from repowiki.server.app import ensure_loaded, get_cache, get_projects, get_registry
from repowiki.server.models import ProjectInfo, ReindexRequest, ScanRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/scan", response_model=ProjectInfo)
async def start_scan(req: ScanRequest, background_tasks: BackgroundTasks,
                     x_api_key: str | None = Header(None)):
    projects = get_projects()

    # the same repo keeps one entry in the history, so its URL stays stable
    match = get_registry().find_by_source(path=req.path or "", url=req.url or "")
    if match is not None:
        live = projects.get(match.id)
        if live is not None and live["info"].status in ("pending", "scanning"):
            return live["info"]  # already indexing this repo
        project_id = match.id
    else:
        project_id = str(uuid.uuid4())[:8]

    info = ProjectInfo(id=project_id, name=match.name if match else "", status="pending")
    projects[project_id] = {"info": info, "wiki": None, "project": None, "progress": []}
    _register(project_id, req, "pending")

    background_tasks.add_task(_run_scan, project_id, req, x_api_key)
    return info


@router.get("/projects")
def list_projects():
    """indexed projects, newest first; live scans report their current status."""
    projects = get_projects()
    records = []
    for record in get_registry().list():
        live = projects.get(record.id)
        if live is not None:
            record = replace(
                record,
                status=live["info"].status,
                error=live["info"].error,
                name=live["info"].name or record.name,
            )
        entry = asdict(record)
        entry.update(_staleness(record))
        records.append(entry)
    return {"projects": records}


_STALE_TTL = 15.0
_stale_cache: dict[str, tuple[float, dict]] = {}


def _staleness(record: ProjectRecord) -> dict:
    """whether the source tree changed since the last index.

    Only local-path projects are checked: a cloned GitHub repo would need a
    fetch before the comparison means anything.
    """
    empty = {"stale": False, "changed_files": 0}
    if record.status != "done" or not record.path:
        return empty

    key = f"{record.id}:{record.updated_at}"
    hit = _stale_cache.get(key)
    if hit is not None and time.time() - hit[0] < _STALE_TTL:
        return hit[1]

    from repowiki.core.staleness import detect_changes
    from repowiki.core.store import load_file_stats

    stats = load_file_stats(record.id)
    result = detect_changes(record.path, stats) if stats else empty

    if len(_stale_cache) > 200:
        cutoff = time.time() - 60
        for old_key in [k for k, (ts, _) in _stale_cache.items() if ts < cutoff]:
            _stale_cache.pop(old_key, None)
    _stale_cache[key] = (time.time(), result)
    return result


@router.post("/projects/{project_id}/reindex")
async def reindex_project(project_id: str, background_tasks: BackgroundTasks,
                          req: ReindexRequest | None = None,
                          x_api_key: str | None = Header(None)):
    """make a project usable again: reuse what is already there, or scan it.

    Without ``force`` this never repeats work: a project that is loaded (or
    whose artifacts are still on disk) comes back as it is. ``force`` is the
    explicit "re-index this" action and always runs a fresh scan.
    """
    record = get_registry().get(project_id)
    if record is None:
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    force = bool(req.force) if req else False
    projects = get_projects()
    live = projects.get(project_id)
    if not force and live is not None and live["info"].status in ("pending", "scanning", "done"):
        return live["info"]

    if not force:
        # the server was restarted: the artifacts on disk are the project
        restored = ensure_loaded(project_id)
        if restored is not None and restored.get("wiki") is not None:
            return restored["info"]

    language = (req.language if req and req.language else record.language) or "zh"
    info = ProjectInfo(id=project_id, name=record.name, status="pending")
    projects[project_id] = {"info": info, "wiki": None, "project": None, "progress": []}

    scan_req = ScanRequest(path=record.path, url=record.url, language=language)
    _register(project_id, scan_req, "pending")
    background_tasks.add_task(_run_scan, project_id, scan_req, x_api_key)
    return info


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """drop a project from the history and forget its working copy."""
    record = get_registry().get(project_id)
    if record is None:
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    get_registry().remove(project_id)
    get_projects().pop(project_id, None)
    from repowiki.core.store import clear_artifacts

    clear_artifacts(project_id)
    return {"deleted": project_id}


@router.get("/project/{project_id}")
async def get_project(project_id: str):
    projects = get_projects()
    if project_id not in projects:
        return {"error": "项目不存在"}
    return projects[project_id]["info"]


@router.get("/project/{project_id}/status")
async def stream_status(project_id: str):
    """SSE endpoint for scan progress updates."""
    async def event_stream():
        projects = get_projects()
        if project_id not in projects:
            yield f"data: {json.dumps({'error': '项目不存在'})}\n\n"
            return

        seen = 0
        while True:
            proj = projects.get(project_id)
            if not proj:
                break

            progress = proj.get("progress", [])
            while seen < len(progress):
                yield f"data: {json.dumps({'step': progress[seen]})}\n\n"
                seen += 1

            if proj["info"].status in ("done", "error"):
                yield f"data: {json.dumps({'status': proj['info'].status})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _register(project_id: str, req: ScanRequest, status: str) -> ProjectRecord:
    """put the project into the history before the scan runs, so a scan that
    dies early still leaves a listable entry."""
    registry = get_registry()
    record = registry.get(project_id) or ProjectRecord(id=project_id)
    record.path = req.path or record.path
    record.url = req.url or record.url
    record.language = req.language or record.language
    record.status = status
    record.error = ""
    return registry.upsert(record)


async def _run_scan(project_id: str, req: ScanRequest, user_api_key: str | None):
    """background task that runs the full scan + analysis pipeline."""
    projects = get_projects()
    proj = projects[project_id]
    proj["info"].status = "scanning"

    registry = get_registry()
    record = registry.get(project_id) or ProjectRecord(id=project_id)
    record.path = req.path or record.path
    record.url = req.url or record.url
    record.language = req.language or record.language
    record.status = "scanning"
    record.error = ""
    registry.upsert(record)

    try:
        cfg = Config.load()
        if req.language:
            cfg.language = req.language
        if req.model:
            cfg.model = resolve_model(req.model)
        if user_api_key:
            cfg.api_key = user_api_key
        elif req.api_key:
            cfg.api_key = req.api_key

        def progress(msg: str):
            proj["progress"].append(msg)

        # ingest
        progress("正在导入项目...")
        if req.url:
            from repowiki.ingest.github import ingest_github
            project = ingest_github(req.url, max_file_size=cfg.max_file_size, max_files=cfg.max_files)
        elif req.path:
            from repowiki.ingest.local import ingest_local
            project = ingest_local(req.path, max_file_size=cfg.max_file_size, max_files=cfg.max_files)
        else:
            raise ValueError("必须提供本地路径（path）或仓库地址（url）")

        proj["project"] = project
        proj["info"].name = project.name
        proj["info"].total_files = len(project.files)
        proj["info"].total_lines = project.total_lines

        # check if we have an API key
        if not cfg.api_key:
            proj["info"].status = "error"
            proj["info"].error = "未配置 API Key"
            _save_scan_result(registry, project_id, proj)
            return

        # analyze
        from repowiki.core.analyzer import Analyzer
        from repowiki.core.graph import DependencyGraph
        from repowiki.core.wiki_builder import WikiBuilder
        from repowiki.llm.client import LLMClient

        cache = get_cache()
        llm = LLMClient(model=cfg.model, api_key=cfg.api_key, api_base=cfg.api_base)
        analyzer = Analyzer(
            llm=llm,
            cache=cache,
            language=cfg.language,
            concurrency=cfg.concurrency,
            max_tokens=cfg.max_tokens,
        )

        wiki_data = await analyzer.analyze(project, on_progress=progress)

        graph = DependencyGraph.build_from_project(project)
        builder = WikiBuilder()
        wiki = builder.build(project, wiki_data, graph, language=cfg.language)

        proj["wiki"] = wiki
        proj["info"].status = "done"
        progress("完成！")
        _save_scan_result(registry, project_id, proj)
        _store_artifacts(project_id, project, wiki, cfg.max_file_size)

    except Exception as e:
        proj["info"].status = "error"
        proj["info"].error = str(e)
        proj["progress"].append(f"错误：{e}")
        _save_scan_result(registry, project_id, proj)


def _store_artifacts(project_id: str, project, wiki, max_file_size: int) -> None:
    """keep the finished project on disk, so a restart can restore it."""
    from repowiki.core.store import save_file_stats, save_project, save_wiki

    try:
        save_project(project_id, project)
        save_wiki(project_id, wiki)
        save_file_stats(project_id, project.files, max_file_size)
    except OSError as exc:
        # a broken disk write must not fail the scan that already succeeded
        logger.warning("could not store artifacts for %s: %s", project_id, exc)


def _save_scan_result(registry, project_id: str, proj: dict) -> None:
    """record the outcome so the home page shows it and a later run can resume."""
    info = proj["info"]
    record = registry.get(project_id) or ProjectRecord(id=project_id)
    record.name = info.name or record.name
    record.file_count = info.total_files or record.file_count
    record.total_lines = info.total_lines or record.total_lines
    record.status = info.status
    record.error = info.error
    registry.upsert(record)
