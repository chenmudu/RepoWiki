import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getRepoMap } from "../lib/api";
import type { RepoMap } from "../lib/api";

export default function MapView() {
  const { id } = useParams<{ id: string }>();
  const [map, setMap] = useState<RepoMap | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    getRepoMap(id).then((m) => {
      if (!m || m.error) setError(m?.error ?? "仓库地图加载失败");
      else setMap(m);
    });
  }, [id]);

  const peak = map?.entries.length ? map.entries[0].score : 1;

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <div className="px-6 py-3 border-b border-slate-200 flex items-center gap-4">
        <Link to={`/project/${id}`} className="text-sm text-slate-500 hover:text-slate-700">
          ← Wiki
        </Link>
        <Link to={`/project/${id}/chat`} className="text-sm text-slate-500 hover:text-slate-700">
          问答
        </Link>
        <Link to={`/project/${id}/diff`} className="text-sm text-slate-500 hover:text-slate-700">
          Diff 评审
        </Link>
        <span className="text-sm font-medium text-slate-800">仓库地图</span>
        {map && (
          <span className="text-xs text-slate-400">
            {map.root} · {map.file_count} 个文件 · 按依赖 PageRank 排序
          </span>
        )}
      </div>

      <div className="flex-1 overflow-auto px-6 py-4">
        {error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : !map ? (
          <p className="text-sm text-slate-400 animate-pulse">正在构建仓库地图…</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-400 border-b border-slate-200">
                <th className="py-2 pr-4 w-10">#</th>
                <th className="py-2 pr-4 w-48">得分</th>
                <th className="py-2 pr-4">路径</th>
                <th className="py-2 pr-4 w-24">语言</th>
                <th className="py-2 w-20 text-right">行数</th>
              </tr>
            </thead>
            <tbody>
              {map.entries.map((e) => (
                <tr key={e.path} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-1.5 pr-4 text-slate-400">{e.rank}</td>
                  <td className="py-1.5 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="h-2 rounded bg-blue-100 flex-1">
                        <div
                          className="h-2 rounded bg-blue-500"
                          style={{ width: `${Math.max(4, (e.score / peak) * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs text-slate-400 w-12 text-right">
                        {(e.score * 100).toFixed(1)}
                      </span>
                    </div>
                  </td>
                  <td className="py-1.5 pr-4">
                    <Link
                      to={`/project/${id}/file/${e.path}`}
                      className="font-mono text-xs text-slate-700 hover:text-blue-600"
                    >
                      {e.path}
                    </Link>
                  </td>
                  <td className="py-1.5 pr-4 text-xs text-slate-500">{e.language}</td>
                  <td className="py-1.5 text-xs text-slate-500 text-right">{e.lines}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
