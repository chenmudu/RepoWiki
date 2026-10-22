"""Test-to-source map extraction (no LLM, no fixtures on disk)."""

from __future__ import annotations

from repowiki.core.models import FileInfo, ProjectContext
from repowiki.core.testmap import build_test_map, is_test_path


def _project(sources: dict[str, tuple[str, str]]) -> ProjectContext:
    """sources: path -> (language, content)."""
    return ProjectContext(
        name="demo",
        root="/demo",
        files=[
            FileInfo(path=path, size=len(src), language=lang, content=src)
            for path, (lang, src) in sources.items()
        ],
    )


def test_test_path_detection():
    assert is_test_path("tests/test_foo.py")
    assert is_test_path("pkg/foo_test.py")
    assert is_test_path("src/app.test.ts")
    assert is_test_path("src/app.spec.tsx")
    assert is_test_path("src/__tests__/app.ts")
    assert not is_test_path("src/app.py")
    assert not is_test_path("src/testing_utils.py")
    assert not is_test_path("docs/test_plan.md")


def test_python_symbol_reach_and_untested_sources():
    project = _project(
        {
            "app.py": ("python", "def main():\n    pass\n"),
            "lib.py": ("python", "def helper():\n    pass\n"),
            "orphan.py": ("python", "def unused():\n    pass\n"),
            "tests/test_app.py": (
                "python",
                "from app import main\nfrom lib import helper\n\ndef test_main():\n    main()\n",
            ),
        }
    )
    m = build_test_map(project)

    assert m.by_test["tests/test_app.py"] == {"app.py": {"main"}, "lib.py": {"helper"}}
    assert [r.test for r in m.by_source["app.py"]] == ["tests/test_app.py"]
    assert m.by_source["lib.py"][0].symbols == {"helper"}
    assert m.untested_sources == ["orphan.py"]
    assert m.unreferencing_tests == []
    assert m.test_file_count == 1
    assert m.reached_source_count == 2


def test_module_level_import_reaches_source_without_symbols():
    project = _project(
        {
            "mod.py": ("python", "class Thing:\n    pass\n"),
            "tests/test_mod.py": ("python", "import mod\n\ndef test_thing():\n    assert mod\n"),
        }
    )
    m = build_test_map(project)

    assert m.by_test["tests/test_mod.py"] == {"mod.py": set()}
    assert m.untested_sources == []


def test_js_test_reaches_relative_module():
    project = _project(
        {
            "src/util.ts": ("typescript", "export function f(): number { return 1 }\n"),
            "src/deep/helper.ts": ("typescript", "export const H = 1\n"),
            "src/util.test.ts": (
                "typescript",
                "import { f } from './util'\nimport { H } from './deep/helper'\n",
            ),
        }
    )
    m = build_test_map(project)

    assert set(m.by_test["src/util.test.ts"]) == {"src/util.ts", "src/deep/helper.ts"}
    assert m.unreferencing_tests == []


def test_test_reaching_only_test_helpers_is_unreferencing():
    project = _project(
        {
            "src/core.py": ("python", "def work():\n    pass\n"),
            "tests/conftest.py": ("python", "VALUE = 1\n"),
            "tests/test_something.py": (
                "python",
                "from tests.conftest import VALUE\n\ndef test_v():\n    assert VALUE\n",
            ),
        }
    )
    m = build_test_map(project)

    assert m.by_test["tests/test_something.py"] == {}
    assert m.unreferencing_tests == ["tests/test_something.py"]
    assert m.untested_sources == ["src/core.py"]


def test_syntax_error_test_file_counts_as_unreferencing():
    project = _project(
        {
            "app.py": ("python", "x = 1\n"),
            "tests/test_broken.py": ("python", "def test_x(:\n"),
        }
    )
    m = build_test_map(project)

    assert m.by_test["tests/test_broken.py"] == {}
    assert m.unreferencing_tests == ["tests/test_broken.py"]
