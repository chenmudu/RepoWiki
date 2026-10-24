---
name: repowiki
description: Use the RepoWiki CLI to map an unfamiliar repository, plan a reading order, or order a diff review by real impact. Run `map` / `diff` before reading a large codebase, when asked where to start, or when asked what to review first after a change. Skip it for tiny repos or when the user already named the exact files.
metadata:
  version: "2"
---

# RepoWiki

A local RepoWiki install provides the **`repowiki`** command. It must be on
`PATH` (add the virtualenv's `Scripts` directory). On Windows the launcher
sets `PYTHONUTF8=1`, which the GBK console needs.

## Commands

| Command | Cost | Use it for |
|---|---|---|
| `repowiki map <repo> -n 30 --format json` | zero LLM | ranked file list (PageRank over the real import graph) — "where should I start reading?" |
| `repowiki diff <repo> <refspec> --format json` | zero LLM | changed files in review order with rank + blast radius — "what should I review first?" |
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
- `scan` spends the user's LLM credits — only on an explicit request.
- **Never run `repowiki serve`**: it binds `0.0.0.0` with no auth. The web UI is
  already at http://127.0.0.1:8765/ (desktop shortcut "RepoWiki").
- Both commands scan the working tree, honoring `.gitignore` and skipping
  `node_modules`, `.git`, build output. No stale index to refresh.
- `chat` needs a TTY; for Q&A use the web UI at `/project/<id>/chat` instead.
