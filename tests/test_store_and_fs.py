"""artifacts on disk: restart restore, forced re-index, folder browsing."""

from __future__ import annotations

import os
import subprocess

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # TestClient dependency

from fastapi.testclient import TestClient

from repowiki.core import store as store_module
from repowiki.core.cache import Cache
from repowiki.core.models import FileInfo, ProjectContext
from repowiki.core.projects import ProjectRecord, ProjectRegistry
from repowiki.core.scanner import scan_directory
from repowiki.core.staleness import classify, detect_changes, detect_drift, head_commit
from repowiki.core.wiki_builder import ModuleCard, SidebarItem, Wiki, WikiPage
from repowiki.server import app as app_module
from repowiki.server.models import ProjectInfo
from repowiki.server.routers import scan as scan_module


def _project() -> ProjectContext:
    return ProjectContext(
        name="demo",
        root="/demo",
        files=[
            FileInfo(
                path="app.py",
                size=27,
                language="python",
                lines=2,
                preview="import util",
                content="import util\nutil.run()\n",
            )
        ],
        file_tree="app.py",
    )


def _wiki() -> Wiki:
    return Wiki(
        project_name="demo",
        pages=[WikiPage(id="index", title="概览", content="# demo\n", order=0)],
        sidebar=[
            SidebarItem(
                title="概览",
                page_id="index",
                children=[SidebarItem(title="app", page_id="modules/app")],
            )
        ],
        cards=[
            ModuleCard(
                name="app",
                purpose="入口",
                hotspots=[("app.py", 3)],
                relationships=[("app", "util")],
                page_id="modules/app",
            )
        ],
    )


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "Cache", lambda: Cache(tmp_path / "cache.db"))
    return TestClient(app_module.create_app(static_dir=tmp_path / "missing"))


def _artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(store_module, "ARTIFACT_DIR", tmp_path / "projects")


def _registry(monkeypatch, tmp_path, *, project_id: str = "p1") -> ProjectRegistry:
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.upsert(ProjectRecord(id=project_id, name="demo", language="zh"))
    monkeypatch.setattr(scan_module, "get_registry", lambda: registry)
    monkeypatch.setattr(app_module, "get_registry", lambda: registry)
    return registry


def _stored(monkeypatch, tmp_path):
    _artifacts(monkeypatch, tmp_path)
    store_module.save_project("p1", _project())
    store_module.save_wiki("p1", _wiki())


# --- store round-trip ---

def test_store_round_trips_project_and_wiki(monkeypatch, tmp_path):
    _artifacts(monkeypatch, tmp_path)
    store_module.save_project("p1", _project())
    store_module.save_wiki("p1", _wiki())

    project = store_module.load_project("p1")
    assert project is not None
    assert project.name == "demo"
    assert project.files[0].content == "import util\nutil.run()\n"

    wiki = store_module.load_wiki("p1")
    assert wiki is not None
    assert wiki.pages[0].title == "概览"
    assert wiki.sidebar[0].children[0].page_id == "modules/app"
    assert wiki.cards[0].hotspots == [("app.py", 3)]
    assert wiki.cards[0].relationships == [("app", "util")]


def test_store_tolerates_a_corrupt_wiki(monkeypatch, tmp_path):
    _artifacts(monkeypatch, tmp_path)
    path = store_module.artifact_dir("p1")
    path.mkdir(parents=True)
    (path / "wiki.json").write_text("not json", encoding="utf-8")

    assert store_module.load_wiki("p1") is None
    assert store_module.load_project("p1") is None
    assert store_module.has_artifacts("p1") is False


# --- restore after a restart ---

def test_wiki_is_restored_from_disk_after_a_restart(monkeypatch, tmp_path):
    _stored(monkeypatch, tmp_path)
    _registry(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "_projects", {})

    with _client(monkeypatch, tmp_path) as client:
        structure = client.get("/api/project/p1/wiki").json()
        assert structure["pages"][0]["title"] == "概览"

        page = client.get("/api/project/p1/wiki/index").json()
        assert page["content"] == "# demo\n"

        cards = client.get("/api/project/p1/cards").json()
        assert cards["cards"][0]["hotspots"] == [["app.py", 3]]

        restored = app_module._projects["p1"]
        assert restored["info"].status == "done"
        assert restored["project"].files[0].content


def test_an_unknown_project_stays_unknown_after_a_restart(monkeypatch, tmp_path):
    _artifacts(monkeypatch, tmp_path)
    _registry(monkeypatch, tmp_path, project_id="other")
    monkeypatch.setattr(app_module, "_projects", {})

    with _client(monkeypatch, tmp_path) as client:
        body = client.get("/api/project/gone/wiki").json()

    assert "尚未生成完成" in body["error"]


# --- reindex: open vs forced rebuild ---

def test_reindex_without_force_reuses_the_stored_artifacts(monkeypatch, tmp_path):
    _stored(monkeypatch, tmp_path)
    _registry(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "_projects", {})
    calls = []

    async def stub_scan(project_id, req, api_key, full=False):
        calls.append(project_id)

    monkeypatch.setattr(scan_module, "_run_scan", stub_scan)

    with _client(monkeypatch, tmp_path) as client:
        body = client.post("/api/projects/p1/reindex", json={}).json()

    assert body["status"] == "done"
    assert calls == []


def test_forced_reindex_runs_a_fresh_scan(monkeypatch, tmp_path):
    _stored(monkeypatch, tmp_path)
    _registry(monkeypatch, tmp_path)
    calls = []

    async def stub_scan(project_id, req, api_key, full=False):
        calls.append((project_id, req.path, full))

    monkeypatch.setattr(scan_module, "_run_scan", stub_scan)

    with _client(monkeypatch, tmp_path) as client:
        body = client.post("/api/projects/p1/reindex", json={"force": True}).json()

    assert body["status"] == "pending"
    assert calls == [("p1", "", False)]
    assert app_module._projects["p1"]["wiki"] is None


def test_deleting_a_project_removes_its_artifacts(monkeypatch, tmp_path):
    _stored(monkeypatch, tmp_path)
    _registry(monkeypatch, tmp_path)

    with _client(monkeypatch, tmp_path) as client:
        assert client.delete("/api/projects/p1").json() == {"deleted": "p1"}

    assert store_module.artifact_dir("p1").exists() is False


# --- change detection ---

def test_file_stats_round_trip(monkeypatch, tmp_path):
    _artifacts(monkeypatch, tmp_path)
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")

    files = scan_directory(root)
    store_module.save_file_stats("p1", files, 200 * 1024)

    stats = store_module.load_file_stats("p1")
    assert stats["files"] == [
        {
            "path": "a.py",
            "size": (root / "a.py").stat().st_size,
            "mtime_ns": files[0].mtime_ns,
        }
    ]


def test_change_detection_flags_edits_additions_and_deletions(monkeypatch, tmp_path):
    _artifacts(monkeypatch, tmp_path)
    root = tmp_path / "src"
    root.mkdir()
    source = root / "a.py"
    source.write_text("x = 1\n", encoding="utf-8")

    store_module.save_file_stats("p1", scan_directory(root), 200 * 1024)
    stats = store_module.load_file_stats("p1")

    assert detect_changes(str(root), stats) == {
        "stale": False,
        "changed_files": 0,
        "sample": [],
        "deleted": 0,
    }

    source.write_text("x = 2\n", encoding="utf-8")
    assert detect_changes(str(root), stats)["changed_files"] == 1

    (root / "b.py").write_text("y = 3\n", encoding="utf-8")
    assert detect_changes(str(root), stats)["changed_files"] == 2

    source.unlink()
    after = detect_changes(str(root), stats)
    assert after["changed_files"] == 2
    assert after["deleted"] == 1


def test_change_detection_reports_a_vanished_directory(tmp_path):
    stats = {
        "indexed_at": 0,
        "max_file_size": 1024,
        "files": [{"path": "a.py", "size": 1, "mtime_ns": 0}],
    }

    result = detect_changes(str(tmp_path / "gone"), stats)

    assert result["stale"] is True
    assert result["reason"] == "目录不存在"


def test_projects_endpoint_reports_stale_after_an_edit(monkeypatch, tmp_path):
    _stored(monkeypatch, tmp_path)
    root = tmp_path / "src"
    root.mkdir()
    source = root / "a.py"
    source.write_text("x = 1\n", encoding="utf-8")

    store_module.save_file_stats("p1", scan_directory(root), 200 * 1024)
    _registry(monkeypatch, tmp_path).upsert(
        ProjectRecord(id="p1", name="demo", path=str(root), status="done")
    )
    monkeypatch.setattr(app_module, "_projects", {})
    scan_module._stale_cache.clear()

    with _client(monkeypatch, tmp_path) as client:
        first = client.get("/api/projects").json()["projects"][0]
        assert first["stale"] is False

        source.write_text("x = 2\n", encoding="utf-8")
        scan_module._stale_cache.clear()
        second = client.get("/api/projects").json()["projects"][0]

    assert second["stale"] is True
    assert second["changed_files"] == 1


# --- drift against a git baseline ---

def _run_git(root, *args, date: str = "") -> str:
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    proc = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=str(root),
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def _git_repo(root) -> str:
    """a committed repo of five source files; returns its first commit sha."""
    root.mkdir(parents=True)
    for name in ("a.py", "b.py", "c.py", "d.py", "e.py"):
        (root / name).write_text("x = 1\n", encoding="utf-8")
    _run_git(root, "init", "-q")
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-q", "-m", "first", date="2026-01-01T00:00:00+00:00")
    return _run_git(root, "rev-parse", "--short", "HEAD")


def test_head_commit_names_the_baseline_and_skips_non_repos(tmp_path):
    root = tmp_path / "repo"
    commit = _git_repo(root)

    assert head_commit(str(root)) == commit
    assert head_commit(str(tmp_path / "plain")) == ""


def test_drift_diffs_a_git_repo_against_its_baseline(tmp_path):
    root = tmp_path / "repo"
    commit = _git_repo(root)

    assert detect_drift(str(root), commit=commit, total_files=5) == {
        "stale": False,
        "changed_files": 0,
        "sample": [],
        "reindex_mode": "incremental",
        "reason": "",
    }

    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    (root / "new.py").write_text("y = 1\n", encoding="utf-8")
    result = detect_drift(str(root), commit=commit, total_files=5)

    assert result["stale"] is True
    assert result["changed_files"] == 2  # the edit, plus the untracked file
    assert result["reindex_mode"] == "incremental"


def test_drift_reconstructs_the_baseline_of_a_record_without_a_commit(tmp_path):
    root = tmp_path / "repo"
    _git_repo(root)
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-q", "-m", "second", date="2026-01-02T00:00:00+00:00")

    between = detect_drift(str(root), indexed_at="2026-01-01T12:00:00+00:00", total_files=5)
    after = detect_drift(str(root), indexed_at="2026-01-02T12:00:00+00:00", total_files=5)

    assert (between["stale"], between["changed_files"]) == (True, 1)
    assert after["stale"] is False


def test_drift_falls_back_to_stats_when_git_cannot_answer(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    source = root / "a.py"
    source.write_text("x = 1\n", encoding="utf-8")
    stat = source.stat()
    stats = {
        "indexed_at": stat.st_mtime,
        "max_file_size": 1024,
        "files": [{"path": "a.py", "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}],
    }

    assert detect_drift(str(root), stats=stats, total_files=1)["stale"] is False

    source.unlink()
    result = detect_drift(str(root), stats=stats, total_files=1)

    assert result["stale"] is True
    # a vanished file may be a rename, and stats cannot tell the two apart
    assert result["reindex_mode"] == "full"


def test_classification_decides_what_a_rebuild_must_cover():
    assert classify([("M", "a.py")])[0] == "incremental"
    assert classify([("A", "new.py")])[0] == "incremental"
    assert classify([("D", "gone.py")])[0] == "full"
    assert classify([("R", "moved.py")])[0] == "full"
    assert classify([("M", "frontend/package.json")])[0] == "full"
    assert classify([("M", ".github/workflows/ci.yml")])[0] == "full"
    assert classify([("M", "a.py")] * 4, total_files=10)[0] == "incremental"
    assert classify([("M", "a.py")] * 6, total_files=10)[0] == "full"


def test_projects_endpoint_reports_the_recommended_reindex_mode(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    commit = _git_repo(root)
    (root / "a.py").rename(root / "moved.py")
    _stored(monkeypatch, tmp_path)
    _registry(monkeypatch, tmp_path).upsert(
        ProjectRecord(
            id="p1",
            name="demo",
            path=str(root),
            status="done",
            file_count=5,
            last_indexed_commit=commit,
        )
    )
    monkeypatch.setattr(app_module, "_projects", {})
    scan_module._stale_cache.clear()

    with _client(monkeypatch, tmp_path) as client:
        body = client.get("/api/projects", params={"refresh": True}).json()["projects"][0]

    assert body["stale"] is True
    assert body["last_indexed_commit"] == commit
    assert body["reindex_mode"] == "full"


def test_a_finished_scan_records_its_baseline_and_its_spend(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    commit = _git_repo(root)
    registry = _registry(monkeypatch, tmp_path)
    registry.upsert(ProjectRecord(id="p1", name="demo", path=str(root)))
    info = ProjectInfo(id="p1", name="demo", status="done")
    usage = {"requests": 11, "input_tokens": 900, "output_tokens": 400, "cost": 0.02}

    scan_module._save_scan_result(registry, "p1", {"info": info}, usage)

    record = registry.get("p1")
    assert record.last_indexed_commit == commit
    assert record.last_scan_usage == usage
    # and it survives a reload of the registry file
    assert ProjectRegistry(tmp_path / "projects.json").get("p1").last_scan_usage == usage


# --- folder browsing ---
def test_browse_lists_only_subdirectories(monkeypatch, tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    with _client(monkeypatch, tmp_path) as client:
        body = client.get("/api/fs/browse", params={"path": str(tmp_path)}).json()

    assert [d["name"] for d in body["dirs"]] == ["alpha", "beta"]
    assert body["path"] == str(tmp_path.resolve())
    assert body["drives"]


def test_browse_without_a_path_lists_the_drives(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        body = client.get("/api/fs/browse").json()

    assert body["path"] == ""
    assert body["dirs"] == []
    assert body["drives"]


def test_browse_rejects_a_missing_directory(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        resp = client.get("/api/fs/browse", params={"path": str(tmp_path / "nope")})

    assert resp.status_code == 400
    assert "目录不存在" in resp.json()["error"]
