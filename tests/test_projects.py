"""project history: the persistent registry and the re-open endpoints."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # TestClient dependency

from fastapi.testclient import TestClient

from repowiki.core.cache import Cache
from repowiki.core.projects import ProjectRecord, ProjectRegistry
from repowiki.server import app as app_module
from repowiki.server.models import ProjectInfo
from repowiki.server.routers import scan as scan_module


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "Cache", lambda: Cache(tmp_path / "cache.db"))
    return TestClient(app_module.create_app(static_dir=tmp_path / "missing"))


def _registry(monkeypatch, tmp_path) -> ProjectRegistry:
    registry = ProjectRegistry(tmp_path / "projects.json")
    monkeypatch.setattr(scan_module, "get_registry", lambda: registry)
    return registry


# --- registry ---

def test_registry_persists_records_across_instances(tmp_path):
    path = tmp_path / "projects.json"
    registry = ProjectRegistry(path)
    registry.upsert(ProjectRecord(id="p1", name="demo", path="/tmp/demo"))

    reloaded = ProjectRegistry(path)
    record = reloaded.get("p1")
    assert record is not None
    assert record.name == "demo"
    assert record.path == "/tmp/demo"
    assert record.created_at


def test_registry_lists_newest_first(tmp_path):
    registry = ProjectRegistry(tmp_path / "projects.json")
    first = registry.upsert(ProjectRecord(id="p1", name="first"))
    second = registry.upsert(ProjectRecord(id="p2", name="second"))
    second.updated_at = "9999-01-01T00:00:00+00:00"

    assert [r.id for r in registry.list()] == ["p2", "p1"]
    assert first.updated_at


def test_registry_finds_a_project_by_its_source(tmp_path):
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.upsert(ProjectRecord(id="p1", name="demo", path="D:/code/demo"))

    assert registry.find_by_source(path="D:/code/demo").id == "p1"
    assert registry.find_by_source(path="D:/code/other") is None
    assert registry.find_by_source(url="https://github.com/a/b") is None


def test_registry_ignores_a_corrupt_file(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text("not json", encoding="utf-8")

    registry = ProjectRegistry(path)

    assert registry.list() == []


# --- routes ---

def test_projects_endpoint_lists_the_registry(monkeypatch, tmp_path):
    registry = _registry(monkeypatch, tmp_path)
    registry.upsert(ProjectRecord(id="p1", name="demo", path="/tmp/demo", file_count=3))

    with _client(monkeypatch, tmp_path) as client:
        body = client.get("/api/projects").json()

    assert len(body["projects"]) == 1
    assert body["projects"][0]["name"] == "demo"
    assert body["projects"][0]["file_count"] == 3


def test_projects_endpoint_reports_the_live_status(monkeypatch, tmp_path):
    registry = _registry(monkeypatch, tmp_path)
    registry.upsert(ProjectRecord(id="p1", name="demo", status="done"))
    monkeypatch.setitem(
        app_module._projects,
        "p1",
        {"info": ProjectInfo(id="p1", name="demo", status="scanning"), "wiki": None,
         "project": None, "progress": []},
    )

    with _client(monkeypatch, tmp_path) as client:
        body = client.get("/api/projects").json()

    assert body["projects"][0]["status"] == "scanning"


def test_reindex_of_an_unknown_project_is_rejected(monkeypatch, tmp_path):
    _registry(monkeypatch, tmp_path)

    with _client(monkeypatch, tmp_path) as client:
        resp = client.post("/api/projects/nope/reindex", json={})

    assert resp.status_code == 404
    assert resp.json()["error"] == "项目不存在"


def test_reindex_reuses_a_project_that_is_still_loaded(monkeypatch, tmp_path):
    registry = _registry(monkeypatch, tmp_path)
    registry.upsert(ProjectRecord(id="p1", name="demo", path="/tmp/demo"))
    monkeypatch.setitem(
        app_module._projects,
        "p1",
        {"info": ProjectInfo(id="p1", name="demo", status="done"), "wiki": None,
         "project": None, "progress": []},
    )

    def fail_scan(*args, **kwargs):
        raise AssertionError("a loaded project must not be scanned again")

    monkeypatch.setattr(scan_module, "_run_scan", fail_scan)

    with _client(monkeypatch, tmp_path) as client:
        body = client.post("/api/projects/p1/reindex", json={}).json()

    assert body["status"] == "done"
    app_module._projects.pop("p1", None)


def test_reindex_reruns_the_scan_for_a_project_that_was_loaded_before_a_restart(
    monkeypatch, tmp_path
):
    registry = _registry(monkeypatch, tmp_path)
    registry.upsert(ProjectRecord(id="p1", name="demo", path="/tmp/demo", language="zh"))
    seen = {}

    async def stub_scan(project_id, req, user_api_key):
        seen["args"] = (project_id, req.path, req.language)
        app_module._projects[project_id]["info"].status = "done"

    monkeypatch.setattr(scan_module, "_run_scan", stub_scan)

    with _client(monkeypatch, tmp_path) as client:
        body = client.post("/api/projects/p1/reindex", json={}).json()

    assert body["id"] == "p1"
    assert seen["args"] == ("p1", "/tmp/demo", "zh")
    app_module._projects.pop("p1", None)


def test_scanning_the_same_repo_twice_keeps_one_history_entry(monkeypatch, tmp_path):
    registry = _registry(monkeypatch, tmp_path)

    async def stub_scan(project_id, req, user_api_key):
        app_module._projects[project_id]["info"].status = "done"

    monkeypatch.setattr(scan_module, "_run_scan", stub_scan)

    with _client(monkeypatch, tmp_path) as client:
        first = client.post("/api/scan", json={"path": "/tmp/demo", "language": "zh"}).json()
        second = client.post("/api/scan", json={"path": "/tmp/demo", "language": "zh"}).json()

    assert first["id"] == second["id"]
    for pid in {first["id"], second["id"]}:
        app_module._projects.pop(pid, None)


def test_a_failed_scan_is_recorded_with_its_error(monkeypatch, tmp_path):
    registry = _registry(monkeypatch, tmp_path)

    async def failing_scan(project_id, req, user_api_key):
        proj = app_module._projects[project_id]
        proj["info"].status = "error"
        proj["info"].error = "目录不存在"
        scan_module._save_scan_result(registry, project_id, proj)

    monkeypatch.setattr(scan_module, "_run_scan", failing_scan)

    with _client(monkeypatch, tmp_path) as client:
        pid = client.post("/api/scan", json={"path": "/tmp/gone"}).json()["id"]

    record = registry.get(pid)
    assert record is not None
    assert record.status == "error"
    assert record.error == "目录不存在"
    app_module._projects.pop(pid, None)


def test_delete_removes_the_project_from_the_history(monkeypatch, tmp_path):
    registry = _registry(monkeypatch, tmp_path)
    registry.upsert(ProjectRecord(id="p1", name="demo", path="/tmp/demo"))
    monkeypatch.setitem(
        app_module._projects,
        "p1",
        {"info": ProjectInfo(id="p1", name="demo", status="done"), "wiki": None,
         "project": None, "progress": []},
    )

    with _client(monkeypatch, tmp_path) as client:
        assert client.delete("/api/projects/p1").status_code == 200
        assert client.get("/api/projects").json()["projects"] == []
        assert client.delete("/api/projects/p1").status_code == 404

    assert registry.get("p1") is None
    assert "p1" not in app_module._projects
