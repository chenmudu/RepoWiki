"""diff command: review order for changed files."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from repowiki.cli import cli
from repowiki.core.diff import build_diff_report, diff_files
from repowiki.core.graph import DependencyGraph
from repowiki.core.models import ProjectContext
from repowiki.core.scanner import scan_directory


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _make_git_repo(tmp_path):
    subprocess.run(
        ["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True
    )
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "engine.py").write_text(
        "from .store import save\n\ndef run(): ...\n"
    )
    (tmp_path / "core" / "store.py").write_text("from .cache import warm\n\ndef save(): ...\n")
    (tmp_path / "core" / "cache.py").write_text("def warm(): ...\n")
    (tmp_path / "notes.py").write_text("# orphan\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")


def _report(tmp_path, refspec):
    files = scan_directory(str(tmp_path))
    project = ProjectContext(name=str(tmp_path), root=str(tmp_path), files=files)
    graph = DependencyGraph.build_from_project(project)
    return build_diff_report(str(tmp_path), refspec, graph)


def test_diff_files_parses_modified_added_deleted(tmp_path):
    _make_git_repo(tmp_path)
    (tmp_path / "core" / "cache.py").write_text("def warm(): ...\n# changed\n")
    (tmp_path / "core" / "new_mod.py").write_text("def fresh(): ...\n")
    (tmp_path / "notes.py").unlink()
    # untracked files are not part of a diff; staging makes the add visible
    _git(tmp_path, "add", "core/new_mod.py")

    triples = diff_files(str(tmp_path), "HEAD")
    by_path = {path: status for status, path, _ in triples}
    assert by_path == {
        "core/cache.py": "M",
        "core/new_mod.py": "A",
        "notes.py": "D",
    }


def test_diff_files_between_commits(tmp_path):
    _make_git_repo(tmp_path)
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, check=True
    ).stdout.decode().strip()
    (tmp_path / "notes.py").write_text("# v2\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "second")

    triples = diff_files(str(tmp_path), f"{base}..HEAD")
    assert [(s, p, o) for s, p, o in triples] == [("M", "notes.py", "")]


def test_diff_files_rename_carries_old_path(tmp_path):
    _make_git_repo(tmp_path)
    _git(tmp_path, "mv", "notes.py", "renamed.py")
    triples = diff_files(str(tmp_path), "HEAD")
    assert triples == [("R", "renamed.py", "notes.py")]


def test_report_ranks_changed_files_by_pagerank_and_blast_radius(tmp_path):
    _make_git_repo(tmp_path)
    (tmp_path / "core" / "cache.py").write_text("def warm(): ...\n# changed\n")
    (tmp_path / "core" / "engine.py").write_text("from .store import save\n\n# changed\n")

    report = _report(tmp_path, "HEAD")
    assert [f.path for f in report.files] == ["core/cache.py", "core/engine.py"]
    cache = report.files[0]
    assert cache.rank == 1
    # store.py imports it directly, engine.py transitively
    assert cache.direct_dependents == 1
    assert cache.transitive_dependents == 2
    engine = report.files[1]
    assert engine.transitive_dependents == 0


def test_deleted_files_rank_last_and_stay_listed(tmp_path):
    _make_git_repo(tmp_path)
    (tmp_path / "core" / "cache.py").unlink()
    (tmp_path / "core" / "engine.py").write_text("from .store import save\n\n# changed\n")

    report = _report(tmp_path, "HEAD")
    assert report.files[-1].change == "D"
    assert report.files[-1].path == "core/cache.py"
    assert report.files[-1].rank == 0
    assert report.files[0].path == "core/engine.py"


def test_cli_diff_json(tmp_path):
    _make_git_repo(tmp_path)
    (tmp_path / "core" / "cache.py").write_text("def warm(): ...\n# changed\n")

    result = CliRunner().invoke(cli, ["diff", str(tmp_path), "HEAD", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["refspec"] == "HEAD"
    assert payload["changed"] == 1
    entry = payload["entries"][0]
    assert entry["path"] == "core/cache.py"
    assert entry["change"] == "M"
    assert entry["rank"] == 1
    assert entry["transitive_dependents"] == 2


# --- git invocation and error reporting ---

def test_git_runs_with_a_scoped_safe_directory(tmp_path):
    """a repo owned by another Windows SID makes git refuse to read it;
    the fix is a per-command safe.directory, never a global config write."""
    _make_git_repo(tmp_path)

    with patch("repowiki.core.diff.subprocess.run", wraps=subprocess.run) as run:
        diff_files(str(tmp_path), "HEAD")

    first = run.call_args_list[0].args[0]
    assert first[:2] == ["git", "-c"]
    assert first[2] == f"safe.directory={Path(str(tmp_path)).resolve().as_posix()}"
    # the override is scoped to this repo, not the user's global config
    assert all(
        any(str(arg).startswith("safe.directory=") for arg in call.args[0])
        for call in run.call_args_list
    )


def test_unknown_refspec_reports_a_readable_error(tmp_path):
    _make_git_repo(tmp_path)

    with pytest.raises(RuntimeError, match="refspec"):
        diff_files(str(tmp_path), "HEAD~99")


def test_repo_without_commits_says_there_is_no_baseline(tmp_path):
    subprocess.run(
        ["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True
    )

    with pytest.raises(RuntimeError, match="还没有任何提交"):
        diff_files(str(tmp_path), "HEAD")
