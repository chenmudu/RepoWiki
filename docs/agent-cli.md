# Using RepoWiki from a coding agent

RepoWiki exposes two prompt-ready commands (`map`, `diff`) and one generator
(`scan`). They are meant to be called by an agent, not only by a human.

## What the CLI offers

| Command | LLM cost | Output | Use it for |
| --- | --- | --- | --- |
| `map <repo> -n 30 --format json` | none | ranked files + language + lines | deciding where to start reading |
| `diff <repo> <refspec> --format json` | none | changed files, review rank, blast radius | deciding what to review first |
| `scan <path\|url> -o dir -f markdown\|json\|html -l zh` | tokens | wiki files on disk | generating documentation |
| `chat <repo>` | tokens | interactive REPL | humans only – needs a TTY |
| `cache-clear` | none | — | after a prompt or model change |

`map` and `diff` are deterministic: they build the import graph and run
PageRank. No API key needed, no network.

Output shapes:

```json
// map
{"root": "…", "file_count": 116, "entries": [
  {"rank": 1, "path": "src/App.tsx", "score": 0.0155, "language": "tsx", "lines": 45}]}

// diff
{"root": "…", "refspec": "HEAD~1..HEAD", "file_count": 116, "changed": 1, "entries": [
  {"path": "README.md", "change": "M", "rank": 21, "score": 0.0031,
   "direct_dependents": 0, "transitive_dependents": 0}]}
```

JSON goes to stdout, warnings to stderr, exit code 0/1. A partial scan adds
`partial_coverage` with the dropped-file summary.

## Wiring it into an agent

### Skill (Qoder, ZCode, Claude Code)

The skill lives in this repo at `skills/repowiki/SKILL.md`. Copy it to each
agent's skill directory:

```bash
cp -r skills/repowiki ~/.qoder-cn/skills/
cp -r skills/repowiki ~/.zcode/skills/
```

The agent then sees `repowiki` in its skill list and loads it when the task
matches ("where do I start reading?", "what should I review first?").

### Plain instructions

Agents without skills can get the same behaviour from an `AGENTS.md` block:

```markdown
## RepoWiki
For an unfamiliar repo, before reading files:
  repowiki map <repo> -n 30 --format json
After a change, before reviewing:
  repowiki diff <repo> HEAD~1..HEAD --format json
Both are free. `scan` costs LLM tokens — only run it on request.
Never run `repowiki serve` (binds 0.0.0.0 without auth).
```

### No MCP wrapper

CLI over MCP by design: `map` and `diff` are one-line shell calls, and a tool
schema would add a layer without adding capability. Wrap them only if an
agent cannot execute commands.

## Notes

- `repowiki` must be on `PATH` — put the virtualenv's `Scripts` directory there.
  On Windows the installed launcher sets `PYTHONUTF8=1`, which the GBK console
  needs.
- The web UI keeps a richer surface (wiki, knowledge cards, RAG chat) at
  http://127.0.0.1:8765/ — start it with the desktop shortcut.
