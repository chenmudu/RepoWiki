import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  scanProject,
  streamScanProgress,
  getWiki,
  getProjects,
  reindexProject,
  deleteProject,
} from "../lib/api";
import type { ProjectRecord } from "../lib/api";
import { useWikiStore } from "../stores/wiki";
import SettingsModal from "../components/SettingsModal";
import PathPicker from "../components/PathPicker";
import {
  BookIcon,
  ChatIcon,
  CheckIcon,
  GridIcon,
  MapIcon,
  RefreshIcon,
  TrashIcon,
  ArrowRightIcon,
} from "../components/icons";

const SELECTED_KEY = "repowiki_selected_project";

const FEATURES = [
  { title: "结构化 Wiki", desc: "概览、模块、架构与阅读指南", path: "", Icon: BookIcon },
  { title: "知识卡片", desc: "每个模块一张卡", path: "/cards", Icon: GridIcon },
  { title: "仓库地图与 Diff", desc: "PageRank 排序与变更评审", path: "/map", Icon: MapIcon },
  { title: "中文问答", desc: "带文件与行号的回答", path: "/chat", Icon: ChatIcon },
];

function apiError(value: unknown): string | null {
  if (!value || typeof value !== "object") return "响应为空";
  const message = (value as Record<string, unknown>).error;
  return typeof message === "string" && message ? message : null;
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, { label: string; className: string }> = {
    done: { label: "已索引", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
    error: { label: "索引失败", className: "border-red-200 bg-red-50 text-red-700" },
    pending: { label: "索引中", className: "border-amber-200 bg-amber-50 text-amber-700" },
    scanning: { label: "索引中", className: "border-amber-200 bg-amber-50 text-amber-700" },
  };
  const style = styles[status] ?? {
    label: status || "未知",
    className: "border-slate-200 bg-slate-50 text-slate-600",
  };
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] ${style.className}`}>
      {style.label}
    </span>
  );
}

export default function Home() {
  const [input, setInput] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [selectedId, setSelectedId] = useState(
    () => localStorage.getItem(SELECTED_KEY) || "",
  );
  const [busyId, setBusyId] = useState("");
  // the scan we are waiting on, if any. The project list settles it, not the
  // progress stream, so a dropped connection cannot lose the finish event.
  const waitingRef = useRef<{ id: string; target?: string; force: boolean } | null>(null);
  const {
    loading,
    setLoading,
    scanProgress,
    addProgress,
    setProjectId,
    projectId,
    setProject,
    setWiki,
    setError,
    error,
    reset,
    settings,
  } = useWikiStore();
  const navigate = useNavigate();

  const isLocalPath = (value: string) =>
    /^[a-zA-Z]:[\\/]/.test(value) || value.startsWith("/") || value.startsWith("\\\\");

  const refreshProjects = (bypassServerCache = false) => {
    getProjects(bypassServerCache)
      .then((list) => {
        setProjects(list);
        setSelectedId((current) => {
          if (current && list.some((p) => p.id === current)) return current;
          localStorage.removeItem(SELECTED_KEY);
          return "";
        });
        settleWaiting(list);
      })
      .catch(() => setProjects([]));
  };

  // a scan is over when the list says so: this is the single completion path,
  // reachable whether or not the progress stream survived
  function settleWaiting(list: ProjectRecord[]) {
    const waiting = waitingRef.current;
    if (!waiting) return;
    const record = list.find((p) => p.id === waiting.id);
    if (!record || (record.status !== "done" && record.status !== "error")) return;
    waitingRef.current = null;
    if (record.status === "done") {
      void finishOpen(waiting.id, waiting.target);
      return;
    }
    setLoading(false);
    setError(
      waiting.force
        ? "重新索引失败，请查看服务端日志。"
        : "索引失败，请查看服务端日志。",
    );
  }

  useEffect(() => {
    refreshProjects();
  }, []);

  // while anything is indexing, keep pulling the list so completion and the
  // stale badge land without the user having to refresh
  const scanning = projects.some(
    (p) => p.status === "pending" || p.status === "scanning",
  );
  useEffect(() => {
    if (!scanning) return;
    const timer = setInterval(() => refreshProjects(true), 3000);
    return () => clearInterval(timer);
  }, [scanning]);

  const selectProject = (id: string) => {
    localStorage.setItem(SELECTED_KEY, id);
    setSelectedId(id);
  };

  const finishOpen = async (id: string, target?: string) => {
    const wiki = await getWiki(id);
    if (wiki && !apiError(wiki)) setWiki(wiki);
    setLoading(false);
    refreshProjects();
    navigate(target ?? `/project/${id}`);
  };

  // the one place a scan is started; `force` is the explicit re-index action,
  // `full` adds the regeneration of every page instead of reusing cached modules
  async function runScan(record: ProjectRecord, force: boolean, target?: string, full = false) {
    reset();
    setProjectId(record.id);
    setLoading(true);

    if (settings.apiKey) {
      localStorage.setItem("repowiki_api_key", settings.apiKey);
    }

    const info = await reindexProject(
      record.id,
      settings.language || undefined,
      force,
      full,
    );
    const infoError = apiError(info);
    if (!info || infoError) {
      throw new Error(infoError || "启动索引失败");
    }
    setProject(info);

    if (info.status === "done") {
      await finishOpen(info.id, target);
      return;
    }

    waitingRef.current = { id: info.id, target, force };
    streamScanProgress(info.id, (step) => addProgress(step));
    refreshProjects(true);
  }

  async function handleScan() {
    const value = input.trim();
    if (!value) return;
    reset();
    setLoading(true);

    if (settings.apiKey) {
      localStorage.setItem("repowiki_api_key", settings.apiKey);
    }

    try {
      const request = isLocalPath(value)
        ? { path: value, language: settings.language, model: settings.model || undefined }
        : { url: value, language: settings.language, model: settings.model || undefined };
      const info = await scanProject(request);
      const infoError = apiError(info);
      if (!info || infoError) {
        throw new Error(infoError || "扫描启动失败");
      }
      setProjectId(info.id);
      setProject(info);
      selectProject(info.id);

      waitingRef.current = { id: info.id, force: false };
      streamScanProgress(info.id, (step) => addProgress(step));
      refreshProjects(true);
    } catch (e: any) {
      setError(e?.message || "扫描启动失败");
      setLoading(false);
    }
  }

  // open = show the stored wiki; a project that was never indexed gets scanned
  async function openProject(record: ProjectRecord, target?: string) {
    if (busyId || loading) return;
    selectProject(record.id);
    setError("");
    setBusyId(record.id);
    try {
      const cached = await getWiki(record.id);
      if (cached && !apiError(cached)) {
        setProjectId(record.id);
        setWiki(cached);
        navigate(target ?? `/project/${record.id}`);
        return;
      }
      await runScan(record, false, target);
    } catch (e: any) {
      setError(e?.message || "打开项目失败");
    } finally {
      setBusyId("");
    }
  }

  async function rebuildProject(record: ProjectRecord, full = false) {
    if (busyId || loading) return;
    selectProject(record.id);
    setError("");
    setBusyId(record.id);
    try {
      await runScan(record, true, `/project/${record.id}`, full);
    } catch (e: any) {
      setError(e?.message || "重新索引失败");
    } finally {
      setBusyId("");
    }
  }

  async function removeProject(record: ProjectRecord) {
    const name = record.name || record.path || record.id;
    if (!window.confirm(`从历史中删除「${name}」？已生成的 Wiki 会一并删除。`)) return;
    await deleteProject(record.id);
    if (selectedId === record.id) {
      localStorage.removeItem(SELECTED_KEY);
      setSelectedId("");
    }
    if (projectId === record.id) reset();
    refreshProjects();
  }

  const selected = useMemo(
    () => projects.find((p) => p.id === selectedId) ?? null,
    [projects, selectedId],
  );

  const formatTime = (value: string) => {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  // a stale repo says what its rebuild costs; a current one just re-indexes
  const reindexLabel = (p: ProjectRecord) => {
    if (busyId === p.id || p.status === "pending" || p.status === "scanning") {
      return "索引中…";
    }
    if (!p.stale) return "重新索引";
    return p.reindex_mode === "full" ? "全量重建" : "增量索引";
  };

  // what the last scan spent, so 增量 and 全量 can be compared in real numbers
  const usageLine = (p: ProjectRecord) => {
    const u = p.last_scan_usage;
    if (!u?.requests) return "";
    const cost = u.cost ? ` · $${u.cost.toFixed(4)}` : "";
    return `上次索引 ${u.requests} 次 LLM 请求 · ${(u.input_tokens ?? 0).toLocaleString()} in / ${(
      u.output_tokens ?? 0
    ).toLocaleString()} out${cost}`;
  };

  const busy = loading || !!busyId;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <h1 className="text-xl font-bold text-slate-800">
          <span className="text-blue-600">Repo</span>Wiki
        </h1>
        <button
          onClick={() => setShowSettings(true)}
          className="text-sm text-slate-500 hover:text-slate-700"
        >
          设置
        </button>
      </header>

      <main className="mx-auto max-w-5xl px-6 pb-16">
        {/* new index */}
        <section className="pb-10">
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
            理解任何代码库
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            粘贴 GitHub 仓库地址，或选择一个本地文件夹，生成结构化 Wiki 并支持中文问答。
          </p>

          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleScan()}
              placeholder="GitHub 仓库 URL 或本地绝对路径"
              className="h-11 flex-1 rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              disabled={busy}
            />
            <button
              onClick={() => setShowPicker(true)}
              disabled={busy}
              className="h-11 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50"
            >
              浏览…
            </button>
            <button
              onClick={handleScan}
              disabled={busy || !input.trim()}
              className="h-11 rounded-lg bg-blue-600 px-5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "生成中…" : "生成 Wiki"}
            </button>
          </div>

          {error && (
            <p className="mt-3 whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}

          {scanProgress.length > 0 && (
            <div className="mt-4 max-h-44 overflow-y-auto rounded-lg border border-slate-200 bg-white p-3">
              {scanProgress.map((step, i) => (
                <div key={i} className="flex items-center gap-2 py-0.5 text-sm text-slate-600">
                  <CheckIcon className="h-3.5 w-3.5 text-emerald-500" />
                  {step}
                </div>
              ))}
              {loading && (
                <div className="animate-pulse py-0.5 text-sm text-blue-600">处理中…</div>
              )}
            </div>
          )}
        </section>

        {/* project history */}
        <section>
          <div className="mb-3 flex items-baseline justify-between">
            <h3 className="text-sm font-semibold text-slate-800">最近的项目</h3>
            <button
              onClick={() => refreshProjects(true)}
              className="text-xs text-slate-500 hover:text-slate-700"
            >
              刷新
            </button>
          </div>

          {projects.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-400">
              还没有已索引的项目。扫描一个本地文件夹或 GitHub 仓库后会出现在这里。
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {projects.map((p) => {
                const isSelected = p.id === selectedId;
                const usage = usageLine(p);
                return (
                  <div
                    key={p.id}
                    className={`rounded-xl border bg-white p-4 transition-all ${
                      isSelected
                        ? "border-blue-500 shadow-sm ring-1 ring-blue-500"
                        : "border-slate-200 hover:border-slate-300 hover:shadow-sm"
                    }`}
                  >
                    <button
                      onClick={() => selectProject(p.id)}
                      className="flex w-full items-start gap-3 text-left"
                    >
                      <span
                        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                          isSelected
                            ? "border-blue-600 bg-blue-600 text-white"
                            : "border-slate-300 text-transparent"
                        }`}
                      >
                        <CheckIcon className="h-3 w-3" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-semibold text-slate-800">
                            {p.name || p.path || p.url || p.id}
                          </span>
                          <span className="flex shrink-0 items-center gap-1">
                            {p.stale && (
                              <span
                                title={
                                  p.reason ||
                                  (p.changed_files
                                    ? `上次索引后有 ${p.changed_files} 个文件发生变化`
                                    : "上次索引后源文件有变化")
                                }
                                className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-800"
                              >
                                源文件已更新
                                {typeof p.changed_files === "number" && p.changed_files > 0
                                  ? ` ${p.changed_files}`
                                  : ""}
                                {" · "}
                                {p.reindex_mode === "full" ? "需全量" : "可增量"}
                              </span>
                            )}
                            <StatusBadge status={p.status} />
                          </span>
                        </span>
                        <span className="mt-0.5 block truncate font-mono text-xs text-slate-500">
                          {p.path || p.url}
                        </span>
                        <span className="mt-2 block text-xs text-slate-400">
                          {p.file_count} 个文件 · {p.total_lines} 行 · {formatTime(p.updated_at)}
                        </span>
                        {usage && (
                          <span className="mt-0.5 block truncate font-mono text-[11px] text-slate-400">
                            {usage}
                          </span>
                        )}
                      </span>
                    </button>

                    <div className="mt-3 flex items-center gap-2 border-t border-slate-100 pt-3">
                      <button
                        onClick={() => openProject(p)}
                        disabled={busy}
                        className="flex items-center gap-1 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
                      >
                        打开
                        <ArrowRightIcon className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() =>
                          rebuildProject(p, p.stale && p.reindex_mode === "full")
                        }
                        disabled={busy}
                        title={p.stale ? p.reason : undefined}
                        className={`flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${
                          p.stale
                            ? "bg-amber-500 text-white hover:bg-amber-600"
                            : "border border-slate-300 text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        <RefreshIcon className="h-3.5 w-3.5" />
                        {reindexLabel(p)}
                      </button>
                      {p.stale && p.reindex_mode !== "full" && (
                        <button
                          onClick={() => rebuildProject(p, true)}
                          disabled={busy}
                          title="忽略缓存，重新生成全部页面"
                          className="rounded-md px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-100 disabled:opacity-50"
                        >
                          全量
                        </button>
                      )}
                      <button
                        onClick={() => removeProject(p)}
                        disabled={busy}
                        title="从历史中删除"
                        className="ml-auto rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* capabilities of the selected project */}
        {selected ? (
          <section className="mt-8">
            <div className="mb-3 flex items-baseline justify-between">
              <h3 className="text-sm font-semibold text-slate-800">能力入口</h3>
              <p className="text-xs text-slate-500">
                当前项目：
                <span className="font-medium text-slate-700">
                  {selected.name || selected.path}
                </span>
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {FEATURES.map((f) => (
                <button
                  key={f.title}
                  onClick={() =>
                    openProject(selected, `/project/${selected.id}${f.path}`)
                  }
                  disabled={busy}
                  className="group flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left transition-all hover:border-blue-300 hover:shadow-sm disabled:opacity-50"
                >
                  <span className="mt-0.5 text-slate-400 transition-colors group-hover:text-blue-600">
                    <f.Icon className="h-5 w-5" />
                  </span>
                  <span>
                    <span className="block text-sm font-medium text-slate-800">{f.title}</span>
                    <span className="mt-0.5 block text-xs text-slate-500">{f.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        ) : (
          projects.length > 0 && (
            <p className="mt-8 rounded-lg border border-slate-200 bg-white px-4 py-3 text-center text-xs text-slate-500">
              先在上方选中一个项目，这里会出现它的 Wiki、知识卡片、仓库地图和问答入口。
            </p>
          )
        )}
      </main>

      <footer className="pb-6 text-center text-xs text-slate-400">
        <a href="https://github.com/he-yufeng/RepoWiki" className="hover:text-slate-600">
          RepoWiki
        </a>
        {" · "}开源的 DeepWiki 替代品
      </footer>

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
      {showPicker && (
        <PathPicker
          initialPath={isLocalPath(input.trim()) ? input.trim() : ""}
          onSelect={(path) => {
            setInput(path);
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}
