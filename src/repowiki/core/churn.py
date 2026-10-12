"""file churn from git history: which files keep getting touched.

One `git log` pass counts commits per path, and the knowledge cards use it
to flag each module's change hotspots: the files a newcomer is most likely
to trip over. Repos without usable history (zip downloads, depth-1 clones)
just have nothing to flag.
"""

from __future__ import annotations

import logging
import subprocess
from collections import Counter

from repowiki.core.graph import _get_module

log = logging.getLogger(__name__)

_LOG_COMMITS = 500  # history window per scan; enough signal, bounded runtime
_TIMEOUT = 10  # seconds for the single git log pass; warm repos answer in ms
_MIN_COMMITS = 10  # below this the ranking is a coin flip, so show nothing


def file_churn(root: str) -> tuple[Counter[str], int]:
    """(touches per path, commits scanned) for root; empty on any failure."""
    try:
        out = subprocess.run(
            [
                "git", "-c", "core.quotepath=false", "-C", root,
                "log", "-n", str(_LOG_COMMITS), "--name-only", "--pretty=format:",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.debug("git log unavailable for %s: %s", root, e)
        return Counter(), 0
    if out.returncode != 0:
        log.debug("git log failed for %s: %s", root, out.stderr.strip()[:200])
        return Counter(), 0

    churn: Counter[str] = Counter()
    commits = 0
    # the empty --pretty=format: prints one blank line per commit, so every
    # non-blank line is a path that commit touched
    for line in out.stdout.splitlines():
        if line:
            churn[line] += 1
        else:
            commits += 1
    return churn, commits


def module_hotspots(
    churn: Counter[str], commits: int, module: str, limit: int = 3
) -> list[tuple[str, int]]:
    """most-touched paths inside one module; [] when history is too thin."""
    if commits < _MIN_COMMITS:
        return []
    return [(p, n) for p, n in churn.most_common() if _get_module(p) == module][:limit]
