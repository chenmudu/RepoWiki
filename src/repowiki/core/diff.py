"""review-order analysis for a git diff: rank changed files by real importance."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from repowiki.core.graph import DependencyGraph


@dataclass
class ChangedFile:
    """one file touched by the diff, in review order."""

    path: str
    change: str  # M / A / D / R
    old_path: str = ""  # rename source, when change == R
    rank: int = 0  # position in the repo-wide PageRank order; 0 = unranked
    score: float = 0.0
    direct_dependents: int = 0  # files that import it
    transitive_dependents: int = 0  # files that transitively import it


@dataclass
class DiffReport:
    """the full review guide for one refspec."""

    root: str
    refspec: str
    files: list[ChangedFile] = field(default_factory=list)

    @property
    def deleted(self) -> list[ChangedFile]:
        return [f for f in self.files if f.change == "D"]


def _git(root: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    safe_root = Path(root).resolve().as_posix()
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={safe_root}", "-C", root, *args],
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(_git_error(proc.stderr.decode("utf-8", errors="replace")))
    return proc


def _git_error(stderr: str) -> str:
    text = stderr.strip()
    lowered = text.lower()
    if "dubious ownership" in lowered:
        return (
            "Git 拒绝访问该仓库：仓库所有者与当前 Windows 用户不一致。"
            "请修正仓库 ACL，或为该仓库添加 safe.directory 例外。"
        )
    if "unknown revision" in lowered or "ambiguous argument" in lowered:
        return "无法解析该 refspec：对应提交或分支不存在。"
    if "not a git repository" in lowered:
        return "该目录不是 Git 仓库，无法生成 diff。"
    return f"git 执行失败：{text[:300]}"


def diff_files(root: str, refspec: str) -> list[tuple[str, str, str]]:
    """changed (status, path, old_path) triples for a refspec.

    Accepts A...B, A..B, or a single ref (diffed against the worktree);
    `git diff --name-status` treats them the same at this layer.
    """
    head = _git(root, "rev-parse", "--verify", "HEAD", check=False)
    if head.returncode != 0:
        stderr = head.stderr.decode("utf-8", errors="replace")
        if "needed a single revision" in stderr.lower():
            raise RuntimeError("该仓库还没有任何提交，无法以 HEAD 为基准生成 diff。")
        raise RuntimeError(_git_error(stderr))
    out = _git(root, "diff", "--name-status", "-z", refspec).stdout.decode(
        "utf-8", errors="replace"
    )
    # -z format: STATUS\0PATH\0, renames: R100\0OLD\0NEW\0
    parts = [p for p in out.split("\0") if p != ""]
    result: list[tuple[str, str, str]] = []
    i = 0
    while i < len(parts):
        status = parts[i]
        if status.startswith("R") or status.startswith("C"):
            old_path, new_path = parts[i + 1], parts[i + 2]
            result.append(("R", new_path, old_path))
            i += 3
        else:
            result.append((status[:1], parts[i + 1], ""))
            i += 2
    return result


def build_diff_report(root: str, refspec: str, graph: DependencyGraph) -> DiffReport:
    """rank the diff's files into review order.

    Changed files are ranked by the graph of the current worktree: a file's
    PageRank plus how many files (transitively) import it. Deleted files are
    listed last — they are gone from the graph but still deserve a look.
    """
    changes = diff_files(root, refspec)
    ranked = graph.rank_files()
    rank_of = {path: i + 1 for i, (path, _) in enumerate(ranked)}
    score_of = dict(ranked)

    files: list[ChangedFile] = []
    for status, path, old_path in changes:
        entry = ChangedFile(path=path, change=status, old_path=old_path)
        if status != "D" and path in graph.graph:
            entry.rank = rank_of.get(path, 0)
            entry.score = score_of.get(path, 0.0)
            entry.direct_dependents = len(list(graph.graph.predecessors(path)))
            # ancestors = everything that imports this file, directly or not
            entry.transitive_dependents = len(nx.ancestors(graph.graph, path))
        files.append(entry)

    files.sort(key=lambda f: (f.change == "D", -f.score, f.rank, f.path))
    return DiffReport(root=root, refspec=refspec, files=files)
