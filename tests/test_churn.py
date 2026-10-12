"""change hotspots on knowledge cards: git churn, module bucketing, floors."""

from __future__ import annotations

from collections import Counter
from unittest.mock import Mock, patch

from repowiki.core import wiki_builder
from repowiki.core.churn import file_churn, module_hotspots
from repowiki.core.graph import DependencyGraph
from repowiki.core.models import (
    FileDoc,
    FileInfo,
    ModuleDoc,
    ProjectContext,
    ProjectOverview,
    Symbol,
    WikiData,
)
from repowiki.core.wiki_builder import WikiBuilder


def _git(stdout: str = "", returncode: int = 0) -> Mock:
    return Mock(stdout=stdout, stderr="", returncode=returncode)


def test_file_churn_counts_touches_per_commit() -> None:
    out = "\nalpha/core.py\nbeta/runner.py\n\nalpha/core.py\n"
    with patch("repowiki.core.churn.subprocess.run", return_value=_git(out)):
        churn, commits = file_churn("/tmp/whatever")
    assert churn == Counter({"alpha/core.py": 2, "beta/runner.py": 1})
    assert commits == 2


def test_file_churn_swallows_git_failures() -> None:
    with patch("repowiki.core.churn.subprocess.run", return_value=_git("", 128)):
        assert file_churn("/tmp/nope") == (Counter(), 0)
    with patch("repowiki.core.churn.subprocess.run", side_effect=OSError("no git")):
        assert file_churn("/tmp/nope") == (Counter(), 0)


def test_module_hotspots_respects_the_commit_floor() -> None:
    churn = Counter({"alpha/core.py": 30, "beta/runner.py": 20})
    # a depth-1 clone has nothing to rank: every file touched exactly once
    assert module_hotspots(churn, commits=3, module="alpha") == []
    assert module_hotspots(churn, commits=50, module="alpha") == [("alpha/core.py", 30)]


def test_module_hotspots_strips_wrapper_dirs_like_the_graph() -> None:
    churn = Counter({"src/mypkg/cli.py": 12, "src/other/x.py": 40})
    assert module_hotspots(churn, 50, "mypkg") == [("src/mypkg/cli.py", 12)]


def _project() -> ProjectContext:
    return ProjectContext(
        name="demo",
        root="/tmp/demo",
        files=[
            FileInfo(
                path="alpha/core.py",
                size=30,
                language="python",
                lines=2,
                content="import beta.runner\nX = 1\n",
            ),
            FileInfo(
                path="beta/runner.py",
                size=10,
                language="python",
                lines=2,
                content="Y = 2\n",
            ),
        ],
    )


def _wiki_data() -> WikiData:
    return WikiData(
        overview=ProjectOverview(name="demo", one_liner="demo project"),
        modules=[
            ModuleDoc(
                name="alpha",
                purpose="alpha package",
                files=[
                    FileDoc(
                        path="alpha/core.py",
                        purpose="core alpha pieces",
                        key_symbols=[Symbol(name="AlphaEngine", kind="class")],
                    ),
                ],
            ),
            ModuleDoc(
                name="beta",
                purpose="beta package",
                files=[FileDoc(path="beta/runner.py", purpose="runs beta")],
            ),
        ],
    )


def _build(churn: Counter[str], commits: int):
    project = _project()
    graph = DependencyGraph.build_from_project(project)
    with patch.object(wiki_builder, "file_churn", return_value=(churn, commits)):
        return WikiBuilder().build(project, _wiki_data(), graph)


def test_card_shows_change_hotspots_from_git_history() -> None:
    wiki = _build(Counter({"alpha/core.py": 17, "beta/runner.py": 9}), commits=42)
    cards = wiki.get_page("cards")
    assert cards is not None
    # known file paths get cross-linked like every other path on the page
    assert "Hot (most commits): [`alpha/core.py`](modules/alpha.md) (17)" in cards.content
    beta_section = cards.content.split("### `beta`", 1)[1]
    assert "Hot (most commits): [`beta/runner.py`](modules/beta.md) (9)" in beta_section


def test_card_omits_hotspots_when_history_is_thin() -> None:
    wiki = _build(Counter({"alpha/core.py": 1}), commits=1)
    cards = wiki.get_page("cards")
    assert cards is not None
    assert "Hot" not in cards.content
