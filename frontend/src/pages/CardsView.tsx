import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useWikiStore } from "../stores/wiki";
import { getCards } from "../lib/api";
import type { ModuleCard } from "../lib/api";

export default function CardsView() {
  const { id } = useParams<{ id: string }>();
  const [cards, setCards] = useState<ModuleCard[] | null>(null);
  const [projectName, setProjectName] = useState("");
  const navigate = useNavigate();
  const setCurrentPage = useWikiStore((s) => s.setCurrentPage);

  const openModule = (pageId: string) => {
    // the wiki view reads the persisted currentPageId, so set it before routing
    setCurrentPage(pageId);
    navigate(`/project/${id}`);
  };
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    getCards(id).then((r) => {
      if (!r || r.error) setError(r?.error ?? "知识卡片加载失败");
      else {
        setCards(r.cards);
        setProjectName(r.project_name);
      }
    });
  }, [id]);

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <div className="px-6 py-3 border-b border-slate-200 flex items-center gap-4">
        <Link to={`/project/${id}`} className="text-sm text-slate-500 hover:text-slate-700">
          ← Wiki
        </Link>
        <Link to={`/project/${id}/map`} className="text-sm text-slate-500 hover:text-slate-700">
          仓库地图
        </Link>
        <Link to={`/project/${id}/diff`} className="text-sm text-slate-500 hover:text-slate-700">
          Diff 评审
        </Link>
        <span className="text-sm font-medium text-slate-800">知识卡片</span>
        {cards && (
          <span className="text-xs text-slate-400">
            {projectName} · {cards.length} 个模块 · 先选卡片，再打开完整模块页
          </span>
        )}
      </div>

      <div className="flex-1 overflow-auto px-6 py-4">
        {error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : !cards ? (
          <p className="text-sm text-slate-400 animate-pulse">正在加载卡片…</p>
        ) : cards.length === 0 ? (
          <p className="text-sm text-slate-500">
            没有知识卡片：本次分析没有产出带用途或文件的模块。
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {cards.map((c) => (
              <div
                key={c.name}
                className="border border-slate-200 rounded-lg p-4 flex flex-col gap-2 hover:border-slate-300 hover:shadow-sm transition"
              >
                <div className="flex items-center justify-between gap-2">
                  <button
                    onClick={() => openModule(c.page_id)}
                    className="font-mono text-sm font-semibold text-slate-800 hover:text-blue-600 truncate text-left"
                  >
                    {c.name}
                  </button>
                  {c.in_cycle && (
                    <span
                      title="该模块内的文件互相 import，建议作为一组阅读"
                      className="shrink-0 text-[10px] font-medium uppercase tracking-wide text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5"
                    >
                      循环
                    </span>
                  )}
                </div>

                {c.purpose && (
                  <p className="text-sm text-slate-600 leading-snug line-clamp-3">{c.purpose}</p>
                )}

                <div className="text-xs text-slate-500 flex flex-wrap gap-x-2 gap-y-1">
                  {c.file_count > 0 && <span>{c.file_count} 个文件</span>}
                  {c.key_symbols.length > 0 && (
                    <span>
                      符号{" "}
                      {c.key_symbols.map((s) => (
                        <code key={s} className="px-1 bg-slate-100 rounded text-slate-700 mr-1">
                          {s}
                        </code>
                      ))}
                      {c.extra_symbols > 0 && <span>等 {c.extra_symbols} 个</span>}
                    </span>
                  )}
                  {c.key_concepts.length > 0 && <span>概念 {c.key_concepts.join(", ")}</span>}
                </div>

                {c.entry_files.length > 0 && (
                  <div className="text-xs text-slate-500">
                    入口：
                    {c.entry_files.map((f) => (
                      <code key={f} className="px-1 bg-slate-100 rounded text-slate-700 mr-1">
                        {f}
                      </code>
                    ))}
                    {c.extra_entries > 0 && <span>等 {c.extra_entries} 个</span>}
                  </div>
                )}

                {c.hotspots.length > 0 && (
                  <div className="text-xs text-slate-500">
                    热点：
                    {c.hotspots.map(([p, n]) => (
                      <span key={p} className="mr-2">
                        <code className="px-1 bg-slate-100 rounded text-slate-700">{p}</code> ({n})
                      </span>
                    ))}
                  </div>
                )}

                {c.relationships.length > 0 && (
                  <div className="text-xs text-slate-400">
                    {c.relationships.map(([s, t]) => `${s} → ${t}`).join(" · ")}
                  </div>
                )}

                <div className="mt-auto pt-2">
                  <button
                    onClick={() => openModule(c.page_id)}
                    className="text-xs text-blue-600 hover:underline text-left"
                  >
                    打开完整页面 →
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
