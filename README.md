# RepoWiki

My personal fork of [RepoWiki](https://github.com/he-yufeng/RepoWiki): generate
wiki docs for a codebase from the terminal or the browser. Chinese-first, and I
run it on Windows.

Not published to PyPI, no support offered. Why it differs from upstream:
[FORK.md](FORK.md). What changed: [CHANGELOG.md](CHANGELOG.md).

## Run it

First build:

```bash
cd frontend && npm ci && npm run build
pip install -e ".[web]"
repowiki config set api_key <key>     # or DEEPSEEK_API_KEY etc.
```

Start (loopback only; the "RepoWiki Restart" desktop shortcut runs the same
command):

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
  python -m uvicorn repowiki.server.app:create_app \
  --factory --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/>. The project list lives in
`~/.repowiki/projects.json` and survives a restart.

## What it does

- Structured wiki: overview, per-module docs, architecture diagrams (including
  deterministic call and data-flow graphs), reading path.
- Incremental re-runs: only pages whose source changed are regenerated; LLM
  results come from a content-hash cache.
- Knowledge cards, test map, repo map, diff review order.
- Web UI plus `repowiki chat`, with `file:start-end` sources under every answer.
- Export Markdown / JSON / self-contained HTML; `--site` produces a GitHub
  Pages-ready site.

## Commands

| Command | Purpose |
| --- | --- |
| `repowiki scan <path\|url>` | generate the wiki (spends tokens) |
| `repowiki chat <repo>` | multi-turn Q&A in the terminal |
| `repowiki map <repo> --format json` | reading order, zero LLM calls |
| `repowiki diff <repo> <refspec>` | review order, zero LLM calls |

Pick a model with `repowiki config set model deepseek` (claude / gpt / gemini /
qwen / kimi / glm / mimo ...), and Chinese output with `-l zh`.

## Docs

- [FORK.md](FORK.md) — what this fork is, how it decides changes, how it tracks upstream
- [CHANGELOG.md](CHANGELOG.md) — fork-local history
- [docs/agent-cli.md](docs/agent-cli.md) — the CLI as seen by a coding agent
- [skills/repowiki/SKILL.md](skills/repowiki/SKILL.md) — make an agent map before it reads

## Upstream & license

Forked from [he-yufeng/RepoWiki](https://github.com/he-yufeng/RepoWiki), MIT
licensed; the original copyright is Yufeng He's.