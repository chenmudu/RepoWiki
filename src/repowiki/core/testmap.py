"""Deterministic test-to-source map, built from the AST — no LLM involved.

Scope is deliberately narrow and language-bound (Python and JS/TS): a test
file "reaches" a source file when it imports that file explicitly
(`from x import y` in Python, `import`/`require` of a relative or project
path in JS/TS). Symbol-level notes are Python-only:
the names pulled in by `from x import y` are recorded per source file.
Dynamic loading (importlib, plugin strings, string-based require) is not
chased, so a file listed as untested may still be exercised indirectly. The
map answers "where should I look for tests of this file?", not "is this
covered?".
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from .graph import _resolve_import
from .models import ProjectContext

# Orientation aid: a megarepo with a test pyramid this tall is still shown as
# a table, but the per-file symbol lists stop growing past this many names.
MAX_SYMBOLS_PER_SOURCE = 12

_PY_TEST_BASENAME = re.compile(r"^(test_.+|.+_test)\.pyi?$")
_JS_TEST_BASENAME = re.compile(r".+\.(test|spec)\.(mjs|cjs|js|jsx|ts|tsx)$", re.IGNORECASE)


def is_test_file(path: str) -> bool:
    """Whether the basename follows a test-file convention (pytest/vitest/jest)."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return bool(_PY_TEST_BASENAME.match(name) or _JS_TEST_BASENAME.match(name))


def is_test_path(path: str) -> bool:
    """Whether a path is test code: a test file or test infrastructure.

    Helpers, fixtures and conftest live under the test directories too, so a
    file there counts as test code even when its basename says nothing.
    """
    posix = path.replace("\\", "/")
    parts = posix.split("/")
    if any(p in ("tests", "test", "__tests__", "spec") for p in parts[:-1]):
        return True
    return is_test_file(path)


@dataclass
class TestRef:
    """One test file's reach into one source file."""

    test: str
    symbols: set[str] = field(default_factory=set)


@dataclass
class TestMap:
    """Test-to-source index plus the two honest gaps around it."""

    # source file -> the test files that import it
    by_source: dict[str, list[TestRef]] = field(default_factory=dict)
    # test file -> source file -> the names it pulls from there
    by_test: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    # non-test source files no test file imports
    untested_sources: list[str] = field(default_factory=list)
    # test files that reach no in-project source at all
    unreferencing_tests: list[str] = field(default_factory=list)

    @property
    def test_file_count(self) -> int:
        return len(self.by_test) + len(self.unreferencing_tests)

    @property
    def reached_source_count(self) -> int:
        return len(self.by_source)


def _py_reach(tree: ast.Module, path: str, path_set: set[str]) -> dict[str, set[str]]:
    """Source file -> names imported from it by one Python test file."""
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            target = _resolve_import(node.module, path, "python", path_set)
            if target:
                names = out.setdefault(target, set())
                for alias in node.names:
                    if alias.name != "*":
                        names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve_import(alias.name, path, "python", path_set)
                if target:
                    out.setdefault(target, set())
    return out


_TRACKED_LANGUAGES = frozenset(
    ("python", "pyi", "javascript", "typescript", "jsx", "tsx", "mjs", "cjs")
)

_JS_IMPORT = re.compile(
    r"""(?:import\s+(?:type\s+)?(?:[\w*{},\s]+)\s+from\s+|import\s+|require\s*\(\s*|export\s+[\w*{},\s]+\s+from\s+)"""
    r"""['"]([^'"]+)['"]"""
)


def _js_reach(content: str, path: str, path_set: set[str]) -> dict[str, set[str]]:
    """Source file -> empty symbol set (module-level reach) for one JS/TS test."""
    out: dict[str, set[str]] = {}
    for match in _JS_IMPORT.finditer(content):
        target = _resolve_import(match.group(1), path, "typescript", path_set)
        if target:
            out.setdefault(target, set())
    return out


def build_test_map(project: ProjectContext) -> TestMap:
    """Index which test files import which source files, and name the gaps."""
    path_set = {f.path for f in project.files}
    test_map = TestMap()

    for f in project.files:
        if not is_test_file(f.path):
            continue
        content = f.content or f.preview or ""
        if f.language in ("python", "pyi"):
            try:
                reach = _py_reach(ast.parse(content), f.path, path_set)
            except SyntaxError:
                reach = {}
        elif f.language in ("javascript", "typescript", "jsx", "tsx", "mjs", "cjs"):
            reach = _js_reach(content, f.path, path_set)
        else:
            reach = {}
        # A test that reaches itself (a conftest importing a sibling helper
        # that lives under tests/) is still a test with no product reach.
        reach = {src: names for src, names in reach.items() if not is_test_path(src)}
        test_map.by_test[f.path] = reach
        if not reach:
            test_map.unreferencing_tests.append(f.path)
        for src, names in reach.items():
            test_map.by_source.setdefault(src, []).append(TestRef(test=f.path, symbols=names))

    for src in sorted(test_map.by_source):
        for ref in test_map.by_source[src]:
            if len(ref.symbols) > MAX_SYMBOLS_PER_SOURCE:
                ref.symbols = set(sorted(ref.symbols)[:MAX_SYMBOLS_PER_SOURCE])

    # Only the languages whose imports this map resolves can be judged
    # untested; a Go file it cannot see into is not evidence of a gap.
    test_map.untested_sources = sorted(
        f.path
        for f in project.files
        if f.language in _TRACKED_LANGUAGES
        and not is_test_path(f.path)
        and f.path not in test_map.by_source
    )
    test_map.unreferencing_tests.sort()
    return test_map
