"""Route-level test for the structured knowledge cards endpoint."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # TestClient dependency

from fastapi.testclient import TestClient

from repowiki.core.cache import Cache
from repowiki.core.graph import DependencyGraph
from repowiki.core.models import (
    Concept,
    FileDoc,
    FileInfo,
    ModuleDoc,
    ProjectContext,
    ProjectOverview,
    Symbol,
    WikiData,
)
from repowiki.core.wiki_builder import WikiBuilder
from repowiki.server import app as app_module
from repowiki.server.models import ProjectInfo


def _client(monkeypatch, tmp_path):
    # keep the lifespan cache out of the real home directory
    monkeypatch.setattr(app_module, "Cache", lambda: Cache(tmp_path / "cache.db"))
    return TestClient(app_module.create_app(static_dir=tmp_path / "missing"))


def test_cards_endpoint_returns_the_structured_cards(monkeypatch, tmp_path):
    project = ProjectContext(
        name="demo",
        root=str(tmp_path),
        files=[
            FileInfo(path="alpha/core.py", size=10, language="python", lines=1, content="X = 1\n")
        ],
    )
    graph = DependencyGraph.build_from_project(project)
    data = WikiData(
        overview=ProjectOverview(name="demo"),
        modules=[
            ModuleDoc(
                name="alpha",
                purpose="alpha package",
                files=[
                    FileDoc(
                        path="alpha/core.py",
                        purpose="core alpha pieces",
                        key_symbols=[Symbol(name="AlphaEngine", kind="class")],
                    )
                ],
                key_concepts=[Concept(name="Engine lifecycle")],
            )
        ],
    )
    wiki = WikiBuilder().build(project, data, graph)
    monkeypatch.setitem(
        app_module._projects,
        "p1",
        {
            "info": ProjectInfo(id="p1", name="demo", status="done"),
            "wiki": wiki,
            "project": project,
            "progress": [],
        },
    )

    with _client(monkeypatch, tmp_path) as client:
        body = client.get("/api/project/p1/cards").json()
        missing = client.get("/api/project/p2/cards").json()

    assert body["project_name"] == "demo"
    (card,) = body["cards"]
    assert card["name"] == "alpha"
    assert card["purpose"] == "alpha package"
    assert card["key_symbols"] == ["AlphaEngine"]
    assert card["key_concepts"] == ["Engine lifecycle"]
    assert card["in_cycle"] is False
    assert card["page_id"] == "modules/alpha"
    assert "error" in missing
