"""Chinese localization of the generated wiki, prompts and JSON retry."""

from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from repowiki.core.analyzer import Analyzer
from repowiki.core.graph import DependencyGraph
from repowiki.core.models import (
    ArchitectureDiagram,
    FileDoc,
    FileInfo,
    ModuleDoc,
    ProjectContext,
    ProjectOverview,
    ReadingGuide,
    WikiData,
)
from repowiki.core.scanner import scan_directory
from repowiki.core.wiki_builder import WikiBuilder
from repowiki.ingest import github as github_mod
from repowiki.ingest.github import ingest_github
from repowiki.ingest.local import ingest_local
from repowiki.llm.prompts import build_chat_prompt, build_overview_prompt


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
        file_tree="alpha/core.py\nbeta/runner.py",
    )


def _wiki_data() -> WikiData:
    return WikiData(
        overview=ProjectOverview(
            name="demo",
            one_liner="demo project",
            description="a demo",
            tech_stack=[{"name": "Python", "category": "language"}],
            key_features=["feature one"],
        ),
        architecture=ArchitectureDiagram(
            architecture_type="library", description="layered"
        ),
        modules=[
            ModuleDoc(
                name="alpha",
                purpose="alpha package",
                files=[FileDoc(path="alpha/core.py", purpose="core alpha pieces")],
            )
        ],
        reading_guide=ReadingGuide(
            introduction="start here",
            steps=[{"order": 1, "title": "read alpha"}],
            tips=["keep it small"],
        ),
    )


def _build(language: str):
    project = _project()
    graph = DependencyGraph.build_from_project(project)
    return WikiBuilder().build(project, _wiki_data(), graph, language=language)


# --- prompts ---

def test_prompts_ask_for_simplified_chinese():
    zh = build_overview_prompt("tree", "files", language="zh")
    assert any("简体中文" in m["content"] for m in zh)
    en = build_overview_prompt("tree", "files", language="en")
    assert not any("简体中文" in m["content"] for m in en)


def test_chat_prompt_asks_for_simplified_chinese():
    zh = build_chat_prompt("这个项目怎么跑？", "ctx", language="zh")
    assert any("简体中文" in m["content"] for m in zh)


# --- wiki pages ---

def test_zh_build_localizes_page_and_sidebar_titles():
    wiki = _build("zh")
    assert wiki.get_page("index").title == "概览"
    assert wiki.get_page("architecture").title == "架构"
    assert wiki.get_page("reading-guide").title == "阅读指南"
    assert [item.title for item in wiki.sidebar][:2] == ["概览", "架构"]
    assert "模块" in [item.title for item in wiki.sidebar]


def test_zh_build_localizes_page_headings():
    wiki = _build("zh")
    index = wiki.get_page("index").content
    assert "## 技术栈" in index
    assert "## Tech Stack" not in index


def test_english_build_keeps_english_titles():
    wiki = _build("en")
    assert wiki.get_page("index").title == "Overview"
    assert wiki.get_page("architecture").title == "Architecture"


# --- analyzer JSON retry ---

class _FlakyLLM:
    """returns unparseable text first, valid JSON afterwards."""

    def __init__(self, payloads: list[str]):
        self.payloads = payloads
        self.calls: list[dict] = []

    async def complete(self, messages, max_tokens=4096, response_format=None):
        self.calls.append({"max_tokens": max_tokens, "response_format": response_format})
        return self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]


def test_analyzer_retries_once_when_json_is_unparseable():
    llm = _FlakyLLM(["not json at all", json.dumps({"ok": True})])
    analyzer = Analyzer(llm=llm, cache=None, language="en")

    data = asyncio.run(analyzer._complete_json([{"role": "user", "content": "x"}]))

    assert data == {"ok": True}
    assert len(llm.calls) == 2


def test_analyzer_gives_up_after_two_failed_attempts():
    llm = _FlakyLLM(["still not json"])
    analyzer = Analyzer(llm=llm, cache=None, language="en")

    data = asyncio.run(analyzer._complete_json([{"role": "user", "content": "x"}]))

    assert data is None
    assert len(llm.calls) == 2


def test_analyzer_requests_json_object_format():
    llm = _FlakyLLM([json.dumps({"ok": True})])
    analyzer = Analyzer(llm=llm, cache=None, language="en", max_tokens=32768)

    asyncio.run(analyzer._complete_json([{"role": "user", "content": "x"}]))

    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    assert llm.calls[0]["max_tokens"] == 32768


# --- progress text ---

def test_progress_text_follows_the_wiki_language():
    zh = Analyzer(llm=_FlakyLLM(["{}"]), cache=None, language="zh")
    en = Analyzer(llm=_FlakyLLM(["{}"]), cache=None, language="en")
    assert zh._t("Done!", "完成！") == "完成！"
    assert en._t("Done!", "完成！") == "Done!"


# --- user-facing error messages ---

def test_missing_directory_errors_are_chinese(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError) as excinfo:
        ingest_local(missing)
    assert "目录不存在或不是文件夹" in str(excinfo.value)

    with pytest.raises(FileNotFoundError) as excinfo:
        scan_directory(str(missing))
    assert "目录不存在或不是文件夹" in str(excinfo.value)


def test_unparsable_git_url_error_is_chinese():
    with pytest.raises(ValueError) as excinfo:
        ingest_github("not-a-repo-url")
    assert "无法解析仓库地址" in str(excinfo.value)


def test_clone_failure_error_is_chinese_and_redacts_the_token(monkeypatch, tmp_path):
    monkeypatch.setattr(github_mod, "_CLONE_DIR", tmp_path / "repos")
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr(
        github_mod.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(
            subprocess.CalledProcessError(
                128, "git", stderr="fatal: bad credentials secret-token"
            )
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        ingest_github("https://github.com/octo/private-repo")

    message = str(excinfo.value)
    assert "克隆失败" in message
    assert "secret-token" not in message
    assert "***" in message
