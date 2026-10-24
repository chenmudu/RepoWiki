import { useEffect, useState } from "react";
import { browseDirectories } from "../lib/api";
import type { BrowseResult } from "../lib/api";
import { ChevronUpIcon, CloseIcon, FolderIcon } from "./icons";

interface Props {
  initialPath?: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

export default function PathPicker({ initialPath = "", onSelect, onClose }: Props) {
  const [data, setData] = useState<BrowseResult | null>(null);
  const [typed, setTyped] = useState(initialPath);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const go = async (path: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await browseDirectories(path);
      if (!res || res.error) {
        setError(res?.error ?? "无法读取该目录");
        return;
      }
      setData(res);
      setTyped(res.path);
    } catch {
      setError("无法读取该目录");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void go(initialPath);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const atRoot = !!data && data.path === "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-800">选择项目文件夹</h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            title="关闭"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
          <button
            onClick={() => data?.parent && go(data.parent)}
            disabled={!data?.parent}
            className="rounded-md border border-slate-300 p-2 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            title="上一级"
          >
            <ChevronUpIcon />
          </button>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go(typed)}
            placeholder={atRoot ? "选择一个磁盘，或直接输入绝对路径" : "绝对路径"}
            className="h-9 flex-1 rounded-md border border-slate-300 px-3 font-mono text-xs text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          />
          <button
            onClick={() => go(typed)}
            className="h-9 rounded-md border border-slate-300 px-3 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            跳转
          </button>
        </div>

        <div className="h-72 overflow-y-auto px-2 py-2">
          {error && <p className="px-3 py-2 text-xs text-red-600">{error}</p>}

          {atRoot && (
            <div className="grid grid-cols-2 gap-1 px-1 pb-2">
              {data?.drives.map((drive) => (
                <button
                  key={drive}
                  onClick={() => go(drive)}
                  className="flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
                >
                  <FolderIcon className="h-4 w-4 text-slate-400" />
                  {drive}
                </button>
              ))}
            </div>
          )}

          {!atRoot &&
            data?.dirs.map((dir) => (
              <button
                key={dir.path}
                onClick={() => go(dir.path)}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
              >
                <FolderIcon className="h-4 w-4 shrink-0 text-slate-400" />
                <span className="truncate">{dir.name}</span>
              </button>
            ))}

          {!atRoot && data && data.dirs.length === 0 && (
            <p className="px-3 py-6 text-center text-xs text-slate-400">
              这个目录下没有子文件夹。可以直接选择它。
            </p>
          )}

          {loading && <p className="px-3 py-2 text-xs text-slate-400">读取中…</p>}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-5 py-3">
          <p className="min-w-0 truncate font-mono text-xs text-slate-500">
            {atRoot ? "未选择目录" : data?.path}
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={onClose}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              onClick={() => data?.path && onSelect(data.path)}
              disabled={!data?.path}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              选择此目录
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
