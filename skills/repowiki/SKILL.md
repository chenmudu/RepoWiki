---
name: repowiki
description: Before you explore a code repository on your own — before globbing, grepping, or reading files to work out its layout — run `repowiki map`. Before reviewing a change, run `repowiki diff`. Both are local, deterministic, free (no LLM calls) and take seconds, so they go first whenever the workspace repo has more than ~20 source files, including prompts like "understand this repo", "where should I start", "what changed", or "review this". Skip only when the user pointed at a specific file or the repo is tiny.
metadata:
  version: "3"
---

# RepoWiki

A local RepoWiki install provides the **`repowiki`** command. It must be on
`PATH` (add the virtualenv's `Scripts` directory). On Windows the launcher
sets `PYTHONUTF8=1`, which the GBK console needs.

## Start with the map, not a read-through

The workspace being a repository is not a reason to explore it by hand. If the
task involves a repo with more than ~20 source files and you are about to
glob, grep, or read files to understand its structure, stop and run:

```
repowiki map <repo> -n 30 --format json
```

It returns the files ranked by PageRank over the real import graph, in
seconds, with no API cost. That ranking is the reading order; open files from
the top instead of sampling.

Before opening any file in a change, run:

```
repowiki diff <repo> <refspec> --format json
```

It orders the changed files by repo-wide rank and blast radius (how many files
import them transitively), so the review starts where risk is.

## Commands

| Command | Cost | Use it for |
|---|---|---|
| `repowiki map <repo> -n 30 --format json` | zero LLM | ranked file list (PageRank over the real import graph) |
| `repowiki diff <repo> <refspec> --format json` | zero LLM | changed files in review order with rank + blast radius |
| `repowiki scan <path\|url> -o <dir> -f markdown\|json\|html -l zh` | **LLM tokens** | generate the wiki. Only when the user asks for docs |
| `repowiki chat <repo>` | LLM tokens | interactive REPL — not usable from an agent |
| `repowiki cache-clear` | — | drop cached LLM results after a prompt/model change |

`refspec` is anything `git diff` takes: `HEAD`, `HEAD~1..HEAD`, `main...HEAD`, a sha.

## Output shapes

```json
// map
{"root": "...", "file_count": 116, "entries": [
  {"rank": 1, "path": "src/App.tsx", "score": 0.0155, "language": "tsx", "lines": 45}]}

// diff
{"root": "...", "refspec": "HEAD~1..HEAD", "file_count": 116, "changed": 1, "entries": [
  {"path": "README.md", "change": "M", "rank": 21, "score": 0.0031,
   "direct_dependents": 0, "transitive_dependents": 0}]}
```

Partial scans add `"partial_coverage": "..."`. JSON goes to stdout, warnings to stderr.

## Rules

- `map` and `diff` are free and fast — run them without asking.
- Do not open more than a couple of files "to get a feel for the repo" before
  running the map; that is the behaviour this skill replaces.
- `scan` spends the user's LLM credits — only on an explicit request.
- **Never run `repowiki serve`**: it binds `0.0.0.0` with no auth. The web UI is
  already at http://127.0.0.1:8765/ (desktop shortcut "RepoWiki").
- Both commands scan the working tree, honoring `.gitignore` and skipping
  `node_modules`, `.git`, build output. No stale index to refresh.
- `chat` needs a TTY; for Q&A use the web UI at `/project/<id>/chat` instead.
