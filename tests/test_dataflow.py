"""Data-flow extraction from the Python AST (no LLM, no fixtures on disk)."""

from __future__ import annotations

from repowiki.core.dataflow import build_dataflow_edges, to_mermaid
from repowiki.core.models import FileInfo, ProjectContext


def _project(sources: dict[str, str]) -> ProjectContext:
    return ProjectContext(
        name="demo",
        root="/demo",
        files=[
            FileInfo(path=path, size=len(src), language="python", content=src)
            for path, src in sources.items()
        ],
    )


def test_constructor_call_marks_creator_and_annotation_marks_consumer():
    project = _project(
        {
            "models.py": "class Config:\n    pass\n",
            "app.py": (
                "from models import Config\n\n"
                "def load() -> Config:\n"
                "    return Config()\n\n"
                "def run(cfg: Config) -> None:\n"
                "    pass\n"
            ),
        }
    )

    edges = build_dataflow_edges(project)
    assert edges["app.py:load"] == {"models.py:Config"}
    assert edges["models.py:Config"] == {"app.py:run"}


def test_transform_shape_yields_no_edge():
    # creates AND receives the same class: a common transform, edges add noise
    project = _project(
        {
            "m.py": (
                "class Token:\n    pass\n\n"
                "def refresh(t: Token) -> Token:\n"
                "    return t\n"
            ),
        }
    )

    assert build_dataflow_edges(project) == {}


def test_wrapped_annotations_resolve():
    project = _project(
        {
            "m.py": "class Item:\n    pass\n",
            "u.py": (
                "from typing import Optional\n"
                "from m import Item\n\n"
                "def fetch() -> Optional[Item]:\n"
                "    return None\n"
            ),
        }
    )

    edges = build_dataflow_edges(project)
    assert edges["u.py:fetch"] == {"m.py:Item"}


def test_same_name_in_two_files_stays_unresolved():
    project = _project(
        {
            "a.py": "class Config:\n    pass\n",
            "b.py": "class Config:\n    pass\n",
            "c.py": "def make():\n    return Config()\n",
        }
    )

    # bare Config() matches two project classes: no unique resolution, no edge
    assert build_dataflow_edges(project) == {}


def test_self_parameter_is_ignored():
    project = _project(
        {
            "m.py": (
                "class Repo:\n    pass\n\n"
                "class Worker:\n"
                "    def handle(self, repo: Repo) -> None:\n"
                "        pass\n"
            ),
        }
    )

    edges = build_dataflow_edges(project)
    assert edges["m.py:Repo"] == {"m.py:Worker.handle"}


def test_empty_when_no_classes():
    project = _project({"app.py": "def main():\n    pass\n"})
    assert build_dataflow_edges(project) == {}
    assert to_mermaid({}) == ""


def test_mermaid_uses_distinct_class_shape():
    project = _project(
        {
            "models.py": "class Config:\n    pass\n",
            "app.py": (
                "from models import Config\n\n"
                "def load() -> Config:\n"
                "    return Config()\n"
            ),
        }
    )

    text = to_mermaid(build_dataflow_edges(project))
    assert "graph LR" in text
    assert '(["Config"])' in text
    assert '["load"]' in text
