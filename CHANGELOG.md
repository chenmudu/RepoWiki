# Changelog

Fork-local history. One line per change that affects use; code-level detail is
in `git log`, and the current divergence from upstream is in [FORK.md](FORK.md).

## 2026-10-25

- A finished scan is settled by the project list: a refresh or a dropped
  progress stream no longer loses the result; the list polls to done and opens
  the project.
- Rebuild is split into incremental / full, and the card shows the changed-file
  count and what the last index cost.
- Agent entry points: `docs/agent-cli` and `skills/repowiki` — map first, then
  read.
- The Chinese single-user fork lands: Chinese output, errors and UI, Windows
  `safe.directory`, the path picker, persistent project history, and cache keys
  over the full prompt inputs.

## 2026-10-23

- Branched from upstream `29d9029`.