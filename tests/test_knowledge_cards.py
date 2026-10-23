"""Knowledge cards: one compact card per module for picking a starting point."""

from __future__ import annotations

from repowiki.core.graph import DependencyGraph
from repowiki.core.models import (
    Concept,
    FileDoc,
    FileInfo,
    ModuleDoc,
    ProjectContext,
    ProjectOverview,
    Relationship,
    Symbol,
    WikiData,
)
from repowiki.core.wiki_builder import WikiBuilder
from repowiki.export.markdown import export_markdown


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


def _graph() -> DependencyGraph:
    return DependencyGraph.build_from_project(_project())


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
                        key_symbols=[
                            Symbol(name="AlphaEngine", kind="class"),
                            Symbol(name="start", kind="method", description="boots alpha"),
                        ],
                    ),
                ],
                key_concepts=[Concept(name="Engine lifecycle", explanation="boot to stop")],
                relationships=[Relationship(source="alpha", target="beta", description="drives")],
            ),
            ModuleDoc(
                name="beta",
                purpose="beta package",
                files=[
                    FileDoc(
                        path="beta/runner.py",
                        purpose="runs beta",
                        key_symbols=[Symbol(name="run_beta", kind="function")],
                    ),
                ],
            ),
        ],
    )


def _build(wiki_data: WikiData | None = None):
    return WikiBuilder().build(_project(), wiki_data or _wiki_data(), _graph())


def test_cards_page_lists_one_card_per_module() -> None:
    wiki = _build()
    cards = wiki.get_page("cards")
    assert cards is not None
    assert cards.title == "Knowledge Cards"
    assert "### `alpha`" in cards.content
    assert "### `beta`" in cards.content
    assert "> alpha package" in cards.content
    assert "1 files" in cards.content
    assert "`AlphaEngine`" in cards.content
    assert "concepts Engine lifecycle" in cards.content
    assert "`alpha` → `beta`" in cards.content
    # every card points at its full module page
    assert "[Open the full page](modules/alpha.md)" in cards.content


def test_card_shows_the_entry_file_from_the_dependency_graph() -> None:
    wiki = _build()
    cards = wiki.get_page("cards")
    assert cards is not None
    # alpha/core.py imports beta/runner.py, so it is the way in for alpha
    assert "Entry: [`alpha/core.py`](modules/alpha.md)" in cards.content
    # beta has no entry-point file, so its card omits the line entirely
    beta_section = cards.content.split("### `beta`", 1)[1]
    assert "Entry:" not in beta_section


def test_cards_page_sits_between_architecture_and_modules_in_sidebar() -> None:
    wiki = _build()
    titles = [item.title for item in wiki.sidebar]
    assert "Knowledge Cards" in titles
    assert titles.index("Knowledge Cards") < titles.index("Modules")


def test_empty_wiki_gets_no_cards_page() -> None:
    wiki = _build(WikiData(overview=ProjectOverview(name="demo")))
    assert wiki.get_page("cards") is None
    assert "Knowledge Cards" not in [item.title for item in wiki.sidebar]


def test_card_symbols_cross_link_to_the_module_page() -> None:
    wiki = _build()
    cards = wiki.get_page("cards")
    assert cards is not None
    # the shared cross-linker turns bare symbol names into module-page links
    assert "[`AlphaEngine`](modules/alpha.md)" in cards.content


def test_markdown_export_writes_cards_md(tmp_path) -> None:
    wiki = _build()
    export_markdown(wiki, tmp_path, page_inputs={})
    out = tmp_path / "cards.md"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "# Knowledge Cards" in text
    assert "### `beta`" in text


def test_card_entry_line_works_for_src_layout() -> None:
    # module grouping strips wrapper dirs (src/, lib/, ...), so a src-layout
    # repo's entry paths are src/<mod>/... while the module name is <mod>;
    # the Entry line must match on the stripped module, not the raw prefix
    project = ProjectContext(
        name="demo-src",
        root="/tmp/demo-src",
        files=[
            FileInfo(
                path="src/mypkg/cli.py",
                size=40,
                language="python",
                lines=2,
                content="import mypkg.core\nmain = 1\n",
            ),
            FileInfo(
                path="src/mypkg/core.py",
                size=10,
                language="python",
                lines=2,
                content="Y = 2\n",
            ),
        ],
    )
    wiki_data = WikiData(
        overview=ProjectOverview(name="demo-src", one_liner="src layout"),
        modules=[
            ModuleDoc(
                name="mypkg",
                purpose="the package",
                files=[
                    FileDoc(path="src/mypkg/cli.py", purpose="entry"),
                    FileDoc(path="src/mypkg/core.py", purpose="core"),
                ],
            ),
        ],
    )
    graph = DependencyGraph.build_from_project(project)
    wiki = WikiBuilder().build(project, wiki_data, graph)
    cards = wiki.get_page("cards")
    assert cards is not None
    assert "Entry: [`src/mypkg/cli.py`](modules/mypkg.md)" in cards.content


def test_card_flags_a_module_caught_in_an_import_cycle() -> None:
    # alpha and beta import each other, so both cards carry the cycle line
    project = ProjectContext(
        name="demo-cycle",
        root="/tmp/demo-cycle",
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
                size=30,
                language="python",
                lines=2,
                content="import alpha.core\nY = 2\n",
            ),
        ],
    )
    graph = DependencyGraph.build_from_project(project)
    wiki = WikiBuilder().build(project, _wiki_data(), graph)
    cards = wiki.get_page("cards")
    assert cards is not None
    alpha_section = cards.content.split("### `alpha`", 1)[1]
    beta_section = cards.content.split("### `beta`", 1)[1]
    assert "Cycle: files here import each other in a loop" in alpha_section
    assert "Cycle: files here import each other in a loop" in beta_section
    # the line points at the dependencies page, where the cycle is listed
    assert "[Dependencies](dependencies.md)" in cards.content


def test_card_cycle_line_stays_off_acyclic_modules() -> None:
    # the shared fixture is one-way (alpha imports beta), so no card shows it
    wiki = _build()
    cards = wiki.get_page("cards")
    assert cards is not None
    assert "Cycle:" not in cards.content


def test_wiki_object_carries_structured_cards_matching_the_page() -> None:
    wiki = _build()
    assert [c.name for c in wiki.cards] == ["alpha", "beta"]
    alpha = wiki.cards[0]
    assert alpha.purpose == "alpha package"
    assert alpha.file_count == 1
    assert alpha.key_symbols == ["AlphaEngine", "start"]
    assert alpha.extra_symbols == 0
    assert alpha.key_concepts == ["Engine lifecycle"]
    assert alpha.entry_files == ["alpha/core.py"]
    assert alpha.in_cycle is False
    assert alpha.relationships == [("alpha", "beta")]
    assert alpha.page_id == "modules/alpha"
    # the beta card has no entry-point file, matching the markdown omission
    assert wiki.cards[1].entry_files == []


def test_empty_wiki_carries_no_cards() -> None:
    assert _build(WikiData(overview=ProjectOverview(name="demo"))).cards == []


def test_card_flags_a_module_in_an_import_cycle() -> None:
    project = ProjectContext(
        name="cyc",
        root="/tmp/cyc",
        files=[
            FileInfo(
                path="a/one.py", size=10, language="python", lines=1, content="import b.two\n"
            ),
            FileInfo(
                path="b/two.py", size=10, language="python", lines=1, content="import a.one\n"
            ),
        ],
    )
    graph = DependencyGraph.build_from_project(project)
    data = WikiData(
        overview=ProjectOverview(name="cyc"),
        modules=[
            ModuleDoc(name="a", purpose="a package", files=[FileDoc(path="a/one.py", purpose="")]),
            ModuleDoc(name="b", purpose="b package", files=[FileDoc(path="b/two.py", purpose="")]),
        ],
    )
    wiki = WikiBuilder().build(project, data, graph)
    by_name = {c.name: c for c in wiki.cards}
    assert by_name["a"].in_cycle and by_name["b"].in_cycle
    cards_page = wiki.get_page("cards")
    assert cards_page is not None
    assert cards_page.content.count("Cycle: files here import each other") == 2
