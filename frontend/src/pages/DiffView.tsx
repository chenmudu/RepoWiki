import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getDiffReview } from "../lib/api";
import type { DiffReview } from "../lib/api";

const CHANGE_STYLE: Record<string, string> = {
  M: "bg-amber-100 text-amber-700",
  A: "bg-green-100 text-green-700",
  D: "bg-red-100 text-red-700",
  R: "bg-blue-100 text-blue-700",
};

export default function DiffView() {
  const { id } = useParams<{ id: string }>();
  const [refspec, setRefspec] = useState("HEAD");
  const [report, setReport] = useState<DiffReview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const run = (ref: string) => {
    if (!id || !ref.trim()) return;
    setLoading(true);
    setError("");
    getDiffReview(id, ref.trim()).then((r) => {
      setLoading(false);
      if (!r || r.error) {
        setReport(null);
        setError(r?.error ?? "diff 生成失败");
      } else {
        setReport(r);
      }
    });
  };

  useEffect(() => {
    run("HEAD");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <div className="px-6 py-3 border-b border-slate-200 flex items-center gap-4">
        <Link to={`/project/${id}`} className="text-sm text-slate-500 hover:text-slate-700">
          ← Wiki
        </Link>
        <Link to={`/project/${id}/chat`} className="text-sm text-slate-500 hover:text-slate-700">
          问答
        </Link>
        <Link to={`/project/${id}/map`} className="text-sm text-slate-500 hover:text-slate-700">
          仓库地图
        </Link>
        <span className="text-sm font-medium text-slate-800">Diff 评审</span>
        {report && (
          <span className="text-xs text-slate-400">
            {report.changed} 个变更 / 共 {report.file_count} 个文件 · 按评审顺序
          </span>
        )}
      </div>

      <div className="px-6 py-3 border-b border-slate-100 flex items-center gap-3">
        <input
          value={refspec}
          onChange={(e) => setRefspec(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run(refspec)}
          placeholder="HEAD、HEAD~3、main...feature、提交 SHA…"
          className="w-80 px-3 py-1.5 text-sm font-mono border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={() => run(refspec)}
          disabled={loading}
          className="px-3 py-1.5 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
        >
          {loading ? "正在分析…" : "评审此 diff"}
        </button>
        <span className="text-xs text-slate-400">最近一次提交可试 HEAD~1..HEAD</span>
      </div>

      <div className="flex-1 overflow-auto px-6 py-4">
        {error ? (
          <div>
            <p className="text-sm text-red-600 whitespace-pre-wrap">{error}</p>
            <p className="text-xs text-slate-500 mt-2">
              提示：如果提示仓库没有提交，请先创建提交；如果提示 Git 所有权问题，可检查仓库 ACL 或
              safe.directory。
            </p>
          </div>
        ) : !report ? (
          <p className="text-sm text-slate-400 animate-pulse">正在分析 diff…</p>
        ) : report.entries.length === 0 ? (
          <p className="text-sm text-slate-500">
            相对 {report.refspec} 没有变更。
            {report.refspec === "HEAD" ? " 可输入 HEAD~1..HEAD 查看最近一次提交。" : ""}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-400 border-b border-slate-200">
                <th className="py-2 pr-4 w-10">#</th>
                <th className="py-2 pr-4 w-14">变更</th>
                <th className="py-2 pr-4 w-16">排名</th>
                <th className="py-2 pr-4 w-20" title="间接 import 该文件的文件数">
                  影响范围
                </th>
                <th className="py-2">路径</th>
              </tr>
            </thead>
            <tbody>
              {report.entries.map((e, i) => (
                <tr key={e.path} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-1.5 pr-4 text-slate-400">{i + 1}</td>
                  <td className="py-1.5 pr-4">
                    <span
                      className={`inline-block w-6 text-center text-xs font-semibold rounded px-1 py-0.5 ${CHANGE_STYLE[e.change] ?? "bg-slate-100 text-slate-600"}`}
                    >
                      {e.change}
                    </span>
                  </td>
                  <td className="py-1.5 pr-4 text-xs text-slate-500">
                    {e.rank ? `#${e.rank}` : "—"}
                  </td>
                  <td
                    className="py-1.5 pr-4 text-xs text-slate-500"
                    title={`${e.direct_dependents} 个直接 import 者`}
                  >
                    {e.transitive_dependents || "—"}
                  </td>
                  <td className="py-1.5">
                    {e.change === "D" ? (
                      <span className="font-mono text-xs text-slate-400 line-through">{e.path}</span>
                    ) : (
                      <Link
                        to={`/project/${id}/file/${e.path}`}
                        className="font-mono text-xs text-slate-700 hover:text-blue-600"
                      >
                        {e.path}
                      </Link>
                    )}
                    {e.old_path && (
                      <span className="font-mono text-xs text-slate-400">（原路径：{e.old_path}）</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
