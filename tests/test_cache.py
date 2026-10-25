"""Tests for the long-lived content-addressed LLM cache."""

from __future__ import annotations

import asyncio
import json
import time

from repowiki.core.cache import Cache, content_hash


def _run(coro):
    return asyncio.run(coro)


def _make_cache(tmp_path) -> Cache:
    c = Cache(db_path=tmp_path / "cache.db")
    asyncio.run(c.init())
    return c


def test_fresh_entry_survives_default_ttl(tmp_path):
    c = _make_cache(tmp_path)
    asyncio.run(c.put("k1", {"a": 1}))
    assert asyncio.run(c.get("k1")) == {"a": 1}
    asyncio.run(c.close())


def test_expired_entry_is_deleted(tmp_path):
    c = _make_cache(tmp_path)
    old = time.time() - 10 * 365 * 24 * 3600
    asyncio.run(c._db.execute(
        "INSERT INTO cache (key, value, created_at) VALUES (?, ?, ?)",
        ("k2", json.dumps({"b": 2}), old),
    ))
    asyncio.run(c._db.commit())
    assert asyncio.run(c.get("k2")) is None
    cursor = asyncio.run(c._db.execute("SELECT COUNT(*) FROM cache WHERE key = ?", ("k2",)))
    (n,) = asyncio.run(cursor.fetchone())
    assert n == 0
    asyncio.run(c.close())


def test_clear_wipes_results_but_keeps_projects(tmp_path):
    c = _make_cache(tmp_path)
    asyncio.run(c.put("k3", {"c": 3}))
    asyncio.run(c.put("k4", {"d": 4}))
    asyncio.run(c.save_project("p1", {"name": "demo"}))

    removed = asyncio.run(c.clear())

    assert removed == 2
    assert asyncio.run(c.get("k3")) is None
    assert asyncio.run(c.get("k4")) is None
    assert asyncio.run(c.load_project("p1")) == {"name": "demo"}
    asyncio.run(c.close())


class _StubLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, max_tokens=4096, response_format=None):
        self.calls += 1
        return '{"name": "mod", "purpose": "test module", "files": []}'


def test_module_analysis_reuses_cache_on_second_run(tmp_path):
    from repowiki.core.analyzer import Analyzer
    from repowiki.core.models import FileInfo

    c = _make_cache(tmp_path)
    llm = _StubLLM()
    analyzer = Analyzer(llm=llm, cache=c, language="en")
    files = [FileInfo(path="mod/a.py", size=10, language="python", content="x = 1\n")]

    doc1, cached1 = asyncio.run(analyzer._analyze_one_module("mod", files))
    doc2, cached2 = asyncio.run(analyzer._analyze_one_module("mod", files))

    assert cached1 is False
    assert cached2 is True
    assert llm.calls == 1
    assert doc1.name == doc2.name == "mod"
    asyncio.run(c.close())


def test_a_rename_inside_a_module_invalidates_its_cached_doc(tmp_path):
    """the key covers the paths the prompt was built from, not just the bodies."""
    from repowiki.core.analyzer import Analyzer
    from repowiki.core.models import FileInfo

    c = _make_cache(tmp_path)
    llm = _StubLLM()
    analyzer = Analyzer(llm=llm, cache=c, language="en")
    body = "x = 1\n"

    asyncio.run(
        analyzer._analyze_one_module("mod", [FileInfo(path="mod/a.py", size=6, language="python", content=body)])
    )
    doc, cached = asyncio.run(
        analyzer._analyze_one_module(
            "mod", [FileInfo(path="mod/renamed.py", size=6, language="python", content=body)]
        )
    )

    assert cached is False
    assert llm.calls == 2
    asyncio.run(c.close())


def test_cache_keys_embed_the_prompt_template_version(tmp_path):
    """editing a template must invalidate, or the cache keeps answering a
    question nobody asked any more."""
    import hashlib
    from pathlib import Path

    from repowiki.core.analyzer import Analyzer
    from repowiki.llm import prompts

    c = _make_cache(tmp_path)
    llm = _StubLLM()
    llm.model = "m1"

    assert prompts.PROMPT_VERSION == hashlib.sha256(
        Path(prompts.__file__).read_bytes()
    ).hexdigest()[:12]
    assert Analyzer(llm=llm, cache=c, language="en")._key_prefix == (
        f"m1:en:p{prompts.PROMPT_VERSION}"
    )
    asyncio.run(c.close())


def test_a_module_prompt_is_self_contained():
    """nothing but the module's own files may feed it, or the key cannot cover it."""
    from repowiki.llm.prompts import build_module_prompt

    messages = build_module_prompt("core", "### core/a.py\n```python\nx = 1\n```", "en")

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Project:" not in messages[1]["content"]
    assert "core/a.py" in messages[1]["content"]


def test_a_full_reindex_ignores_the_cached_result(tmp_path):
    from repowiki.core.analyzer import Analyzer
    from repowiki.core.models import FileInfo

    c = _make_cache(tmp_path)
    files = [FileInfo(path="mod/a.py", size=10, language="python", content="x = 1\n")]
    asyncio.run(
        Analyzer(llm=_StubLLM(), cache=c, language="en")._analyze_one_module("mod", files)
    )

    llm = _StubLLM()
    doc, cached = asyncio.run(
        Analyzer(llm=llm, cache=c, language="en", use_cache=False)._analyze_one_module(
            "mod", files
        )
    )

    assert cached is False
    assert llm.calls == 1
    asyncio.run(c.close())


def test_content_hash_is_stable_and_distinct():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
