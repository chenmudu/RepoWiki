"""orchestrates the multi-step LLM analysis pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from repowiki.core.cache import Cache, content_hash
from repowiki.core.graph import DependencyGraph
from repowiki.core.models import (
    ArchitectureDiagram,
    FileInfo,
    ModuleDoc,
    ProjectContext,
    ProjectOverview,
    ReadingGuide,
    WikiData,
)
from repowiki.core.skeleton import context_for_file
from repowiki.llm.client import LLMClient
from repowiki.llm.prompts import (
    PROMPT_VERSION,
    build_architecture_prompt,
    build_module_prompt,
    build_overview_prompt,
    build_reading_guide_prompt,
    extract_json,
)

logger = logging.getLogger(__name__)


class Analyzer:
    """runs the full wiki generation pipeline."""

    def __init__(
        self,
        llm: LLMClient,
        cache: Cache,
        language: str = "en",
        concurrency: int = 5,
        max_tokens: int = 4096,
        use_cache: bool = True,
    ):
        self.llm = llm
        self.cache = cache
        self.language = language
        self.max_tokens = max_tokens
        # a full re-index regenerates every page: it writes the cache but does
        # not read it, so unchanged modules are not silently served from before
        self.use_cache = use_cache
        self._sem = asyncio.Semaphore(concurrency)
        # cache keys embed model, language and the prompt templates themselves,
        # so switching any of the three misses the cache instead of serving an
        # answer written for different instructions
        self._key_prefix = f"{getattr(llm, 'model', '')}:{language}:p{PROMPT_VERSION}"
        # page id -> cache key used this run; the incremental export compares
        # these against the state file to decide which pages to rewrite
        self.cache_keys: dict[str, str] = {}
        # modules that fell back to placeholder docs after LLM/parse failures;
        # surfaced at the end of the run so a half-degraded wiki isn't silent
        self.degraded_modules: list[str] = []

    def _t(self, en: str, zh: str) -> str:
        """progress text in the wiki's language."""
        return zh if self.language == "zh" else en

    async def _read_cache(self, cache_key: str) -> dict | list | None:
        """a cached result, or None when this run is not allowed to reuse one."""
        return await self.cache.get(cache_key) if self.use_cache else None

    async def analyze(
        self,
        project: ProjectContext,
        on_progress: Callable[[str], None] | None = None,
    ) -> WikiData:
        """run the full analysis pipeline and return WikiData."""
        self.cache_keys = {}
        self.degraded_modules = []

        def progress(msg: str):
            if on_progress:
                on_progress(msg)

        # 1. prepare context
        progress(self._t("Preparing file context...", "正在准备文件上下文..."))
        key_files_text = self._build_key_files_context(project)
        tree_hash = content_hash(project.file_tree + key_files_text)

        # 2. generate overview
        progress(self._t("Generating project overview...", "正在生成项目概览..."))
        overview = await self._generate_overview(project, key_files_text, tree_hash)

        # 3. group files into modules and analyze each
        modules_map = self._group_into_modules(project.files)
        progress(self._t(f"Analyzing {len(modules_map)} modules...",
                         f"正在分析 {len(modules_map)} 个模块..."))
        module_docs = await self._analyze_modules(modules_map, progress)

        # 4. generate architecture diagram
        progress(self._t("Detecting architecture...", "正在识别架构..."))
        architecture = await self._generate_architecture(project, key_files_text, tree_hash)

        # 4b. deterministic call graph from the AST — cheap, never cached, so
        # it stays correct even when the LLM-written diagram comes from cache
        from .callgraph import build_call_edges, to_mermaid

        architecture.call_graph = to_mermaid(build_call_edges(project))

        # 4c. deterministic data-flow view, same guarantees: who creates each
        # project class, who receives it
        from .dataflow import build_dataflow_edges
        from .dataflow import to_mermaid as dataflow_to_mermaid

        architecture.data_flow_graph = dataflow_to_mermaid(build_dataflow_edges(project))

        # 5. generate reading guide (needs module summaries + rankings placeholder)
        progress(self._t("Creating reading guide...", "正在生成阅读指南..."))
        reading_guide = await self._generate_reading_guide(project, module_docs, tree_hash)

        if self.degraded_modules:
            logger.warning("Modules with placeholder docs: %s", ", ".join(self.degraded_modules))
            progress(
                self._t(
                    f"{len(self.degraded_modules)} module(s) fell back to placeholder docs "
                    f"after LLM failures: {', '.join(self.degraded_modules)}",
                    f"{len(self.degraded_modules)} 个模块在 LLM 调用失败后退化为占位文档："
                    f"{', '.join(self.degraded_modules)}",
                )
            )

        progress(self._t("Done!", "完成！"))
        return WikiData(
            overview=overview,
            modules=module_docs,
            architecture=architecture,
            reading_guide=reading_guide,
        )

    def _build_key_files_context(self, project: ProjectContext) -> str:
        """collect config files and entrypoints for the overview prompt."""
        parts = []
        for f in project.files:
            if f.is_config or f.is_entrypoint:
                content = context_for_file(f.content if f.content else f.preview, f.language)
                parts.append(f"### {f.path}\n```{f.language}\n{content}\n```")
        return "\n\n".join(parts)

    async def _complete_json(self, messages: list[dict], attempts: int = 2):
        """Ask for JSON, retrying once if the model returns unparseable text."""
        for attempt in range(attempts):
            raw = await self.llm.complete(
                messages,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            data = extract_json(raw)
            if data is not None:
                return data
            logger.warning("JSON parse failed (attempt %d/%d)", attempt + 1, attempts)
        return None

    async def _generate_overview(
        self, project: ProjectContext, key_files: str, tree_hash: str
    ) -> ProjectOverview:
        cache_key = f"{self._key_prefix}:overview:{tree_hash}"
        self.cache_keys["index"] = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            try:
                return ProjectOverview(**cached)
            except Exception:
                pass

        messages = build_overview_prompt(project.file_tree, key_files, self.language)
        data = await self._complete_json(messages)
        if not data or not isinstance(data, dict):
            logger.warning("Failed to parse overview JSON, using defaults")
            return ProjectOverview(name=project.name)

        filtered = {k: v for k, v in data.items() if k in ProjectOverview.model_fields}
        try:
            overview = ProjectOverview(**filtered)
        except Exception:
            overview = ProjectOverview(name=project.name)
        await self.cache.put(cache_key, overview.model_dump())
        return overview

    def _group_into_modules(self, files: list[FileInfo]) -> dict[str, list[FileInfo]]:
        """group files by their top-level directory."""
        from pathlib import Path

        modules: dict[str, list[FileInfo]] = {}
        for f in files:
            parts = Path(f.path).parts
            if len(parts) == 1:
                # root-level files go into a "root" module
                modules.setdefault("root", []).append(f)
            else:
                # use the first directory as module name
                mod = parts[0]
                # if it's a common wrapper like "src", use the second level
                if mod in ("src", "lib", "pkg", "internal", "app") and len(parts) > 2:
                    mod = parts[1]
                modules.setdefault(mod, []).append(f)
        return modules

    async def _analyze_modules(
        self,
        modules: dict[str, list[FileInfo]],
        progress: Callable[[str], None],
    ) -> list[ModuleDoc]:
        tasks = []
        for name, files in modules.items():
            tasks.append(self._analyze_one_module(name, files))

        results = []
        reused = 0
        regenerated = 0
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            doc, was_cached = await coro
            if doc:
                results.append(doc)
                if was_cached:
                    reused += 1
                else:
                    regenerated += 1
            progress(self._t(f"Analyzed module {i + 1}/{len(tasks)}",
                             f"已分析模块 {i + 1}/{len(tasks)}"))

        if reused:
            progress(self._t(
                f"Module analysis: {reused} reused from cache, {regenerated} regenerated",
                f"模块分析：{reused} 个复用缓存，{regenerated} 个重新生成",
            ))

        # sort by number of files (largest first); name tiebreak keeps the
        # order deterministic, otherwise the reading guide's cache key
        # flickers with as_completed timing
        results.sort(key=lambda m: (-len(m.files), m.name))
        return results

    async def _analyze_one_module(
        self,
        name: str,
        files: list[FileInfo],
    ) -> tuple[ModuleDoc | None, bool]:
        async with self._sem:
            # build context for this module
            files_text_parts = []
            for f in files:
                content = context_for_file(f.content if f.content else f.preview, f.language)
                files_text_parts.append(
                    f"### {f.path} ({f.language})\n```{f.language}\n{content}\n```"
                )

            files_context = "\n\n".join(files_text_parts)
            # the key covers every input the prompt is built from — path and
            # language tag included — so a rename cannot leave a doc behind
            cache_key = f"{self._key_prefix}:module:{name}:{content_hash(files_context)}"
            self.cache_keys[f"modules/{name}"] = cache_key

            cached = await self._read_cache(cache_key)
            if cached:
                try:
                    return ModuleDoc(**cached), True
                except Exception:
                    pass

            messages = build_module_prompt(name, files_context, self.language)
            data = await self._complete_json(messages)
            if not data or not isinstance(data, dict):
                logger.warning("Failed to parse module '%s' JSON", name)
                self.degraded_modules.append(name)
                return ModuleDoc(name=name, purpose=f"Module containing {len(files)} files"), False

            # ensure name is present (LLM sometimes omits it)
            data.setdefault("name", name)
            filtered = {k: v for k, v in data.items() if k in ModuleDoc.model_fields}
            try:
                doc = ModuleDoc(**filtered)
            except Exception:
                self.degraded_modules.append(name)
                doc = ModuleDoc(name=name, purpose=data.get("purpose", ""))
            await self.cache.put(cache_key, doc.model_dump())
            return doc, False

    async def _generate_architecture(
        self, project: ProjectContext, key_files: str, tree_hash: str
    ) -> ArchitectureDiagram:
        cache_key = f"{self._key_prefix}:arch:{tree_hash}"
        self.cache_keys["architecture"] = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            try:
                return ArchitectureDiagram(**cached)
            except Exception:
                pass

        messages = build_architecture_prompt(project.file_tree, key_files, self.language)
        data = await self._complete_json(messages)
        if not data or not isinstance(data, dict):
            logger.warning("Failed to parse architecture JSON")
            return ArchitectureDiagram()

        filtered = {k: v for k, v in data.items() if k in ArchitectureDiagram.model_fields}
        try:
            arch = ArchitectureDiagram(**filtered)
        except Exception:
            arch = ArchitectureDiagram()
        await self.cache.put(cache_key, arch.model_dump())
        return arch

    async def _generate_reading_guide(
        self,
        project: ProjectContext,
        module_docs: list[ModuleDoc],
        tree_hash: str,
    ) -> ReadingGuide:
        # PageRank over the import graph decides which files matter; scan order
        # only fills the tail when the graph is smaller than the display limit.
        ranked = DependencyGraph.build_from_project(project).rank_files()
        by_path = {f.path: f for f in project.files}
        ranked_paths = [path for path, _ in ranked[:20]]
        seen = set(ranked_paths)
        for f in project.files:
            if len(ranked_paths) >= 20:
                break
            if f.path not in seen:
                ranked_paths.append(f.path)
                seen.add(f.path)

        rankings_parts = []
        for i, path in enumerate(ranked_paths, 1):
            f = by_path[path]
            tag = ""
            if f.is_entrypoint:
                tag = " [entrypoint]"
            elif f.is_config:
                tag = " [config]"
            rankings_parts.append(f"{i}. {path}{tag} ({f.lines} lines)")
        rankings = "\n".join(rankings_parts)

        module_parts = []
        for m in module_docs:
            module_parts.append(f"- **{m.name}**: {m.purpose}")
        module_summaries = "\n".join(module_parts)

        # key on the actual prompt inputs so an import-only edit that reshuffles
        # the ranking also invalidates the cached guide
        cache_key = (
            f"{self._key_prefix}:guide:{tree_hash}:{content_hash(rankings + module_summaries)}"
        )
        self.cache_keys["reading-guide"] = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            try:
                return ReadingGuide(**cached)
            except Exception:
                pass

        messages = build_reading_guide_prompt(rankings, module_summaries, self.language)
        data = await self._complete_json(messages)
        if not data or not isinstance(data, dict):
            logger.warning("Failed to parse reading guide JSON")
            return ReadingGuide()

        filtered = {k: v for k, v in data.items() if k in ReadingGuide.model_fields}
        try:
            guide = ReadingGuide(**filtered)
        except Exception:
            guide = ReadingGuide()
        await self.cache.put(cache_key, guide.model_dump())
        return guide
