"""The Test Map page: which tests reach which sources, wired into the wiki."""

from __future__ import annotations

from repowiki.core.graph import DependencyGraph
from repowiki.core.models import FileInfo, ProjectContext, ProjectOverview, WikiData
from repowiki.core.wiki_builder import WikiBuilder


def _file(path: str, content: str, language: str = "python") -> FileInfo:
    return FileInfo(
        path=path,
        size=len(content),
        language=language,
        lines=content.count("\n") + 1,
        content=content,
    )


def _wiki_data() -> WikiData:
    return WikiData(overview=ProjectOverview(name="demo", one_liner="demo project"))


def _project(files: list[FileInfo]) -> ProjectContext:
    return ProjectContext(name="demo", root="/demo", files=files)


def test_page_lists_reach_untested_and_unreferencing():
    project = _project(
        [
            _file("app.py", "def main():\n    pass\n"),
            _file("orphan.py", "def unused():\n    pass\n"),
            _file(
                "tests/test_app.py",
                "from app import main\n\ndef test_main():\n    main()\n",
            ),
            _file("tests/test_mocked.py", "def test_pure():\n    assert True\n"),
        ]
    )
    wiki = WikiBuilder().build(project, _wiki_data(), DependencyGraph())

    page = wiki.get_page("tests")
    assert page is not None
    assert page.title == "Test Map"
    assert "| `app.py` | `tests/test_app.py` | `main` |" in page.content
    assert "Sources no test file imports" in page.content
    assert "`orphan.py`" in page.content
    assert "Test files that reach no source file" in page.content
    assert "`tests/test_mocked.py`" in page.content
    # the sidebar lists it after the overview
    titles = [i.title for i in wiki.sidebar]
    assert "Test Map" in titles
    assert titles.index("Test Map") > titles.index("Overview")


def test_page_absent_without_test_files():
    project = _project([_file("app.py", "x = 1\n")])
    wiki = WikiBuilder().build(project, _wiki_data(), DependencyGraph())

    assert wiki.get_page("tests") is None
    assert "Test Map" not in [i.title for i in wiki.sidebar]
