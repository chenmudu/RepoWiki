# Local patches on top of he-yufeng/RepoWiki

This clone carries local changes that are **not** upstream. They exist because
the upstream release does not handle Chinese output, Windows Git ownership
checks, or the local-path flow in the web UI.

- Upstream base: `29d9029b4c770b66772c1d565f2d5b5980074147` (2026-10-23)
- This repository (`chenmudu/RepoWiki`, branch `main`) is the source of truth;
  every patch below is committed here.
- Virtualenv: any virtualenv with `pip install -e ".[web]"`; the CLI is `repowiki`
- Previous wheel install (rollback): a separate virtualenv with the PyPI 0.6.0 wheel

## Why each patch exists

| Area | Problem | Fix |
| --- | --- | --- |
| `llm/prompts.py` | The LLM answered in English even with `language: zh` | Added a Simplified Chinese instruction to every prompt |
| `core/analyzer.py` | JSON answers were truncated or unparseable, so pages fell back to placeholders | Request `response_format={"type":"json_object"}` and retry once (`_complete_json`) |
| `core/analyzer.py` | Scan progress was shown in English in the web UI | Progress text follows the wiki language |
| `core/wiki_builder.py` | Page titles and section headings stayed English | `build(..., language="zh")` localizes titles, headings and labels |
| `core/diff.py`, `core/churn.py` | Git refused to read repos owned by another Windows SID (`exit 129`) | Every git call carries `-c safe.directory=<repo>`; the global git config is never touched |
| `core/diff.py` | A missing commit or an empty repo produced raw git output | Readable Chinese errors for unknown refspec, no commits, and non-repos |
| `server/routers/*.py` | API errors surfaced in English | Chinese error messages |
| `core/scanner.py`, `ingest/local.py`, `ingest/github.py` | Scan failures surfaced English errors ("Not a directory", "Clone failed") | Chinese messages for a missing directory, an unparsable repo URL, a clone timeout or failure, and an oversized repo; the clone credential stays redacted |
| `export/markdown.py` | Exported README had an English table of contents | Chinese `## 目录` for `zh` |
| `core/projects.py`, `server/routers/scan.py` | The web UI had no project list, and a restart lost every indexed project | A registry at `~/.repowiki/projects.json`, `GET /api/projects`, `POST /api/projects/{id}/reindex`; scanning the same repo reuses its project id |
| `frontend/` | The whole web UI was English | Full Chinese localization, `lang="zh-CN"` |
| `frontend/src/pages/Home.tsx` | The input accepted a local path but always sent `url` | Detects Windows/Unix absolute paths and sends `path` |
| `frontend/src/pages/Home.tsx` | The landing page advertised features the tool does not have | Four real capability cards |
| `frontend/src/pages/Home.tsx` | The feature cards were static text with no action | They now open the wiki, cards, map and chat views of the project in focus |
| `frontend/src/pages/Home.tsx` | Indexed projects were nowhere to be found | A "最近的项目" list that re-indexes a project with one click |
| `frontend/src/pages/Home.tsx` | The capability cards silently acted on the newest project, whatever the user wanted | One explicit "current project": the cards only render for the project selected in the list; the list itself carries 打开 / 重新索引 / 删除 |
| `core/store.py`, `server/app.py` | A restart emptied the in-memory project store, so opening a project re-ran the whole scan | The wiki and the scanned project are stored per project id and restored on first access |
| `server/routers/scan.py` | "Open a project" and "re-index it" were the same call | `reindex` only rebuilds with `force: true`; otherwise it reuses memory or disk |
| `server/routers/fs.py`, `frontend/src/components/PathPicker.tsx` | The UI asked the user to type an absolute path | `GET /api/fs/browse` lists drives and sub-directories for a folder-picker dialog |
| `core/staleness.py`, `server/routers/scan.py`, `frontend/` | An indexed project kept showing its old wiki after the source changed, with no hint | The scan records the commit the tree was at; the list diffs the repo against that commit and flags 源文件已更新 with the count. A directory git does not track falls back to per-file size/mtime. Nothing reads file contents or calls an LLM |
| `core/staleness.py`, `frontend/src/pages/Home.tsx` | The flag said "stale" but not what a rebuild would cost, and a project indexed before the stats existed could never be flagged | Drift is diffed against `last_indexed_commit` (or, for those older records, the commit that was current when the scan ran), and classified: deletions, renames, build-config edits or over half the repo changed mean 需全量, otherwise 可增量 |
| `server/models.py`, `server/routers/scan.py`, `core/analyzer.py` | Re-indexing was one size: cached analysis was always reused, so a repo whose structure moved could not be regenerated | `ReindexRequest.full` makes the run skip cache reads and regenerate every page; the results are still written to the cache |
| `llm/prompts.py`, `core/analyzer.py` | Incremental runs silently served module docs written for different inputs: the key hashed only the file bodies, while the prompt also carried the paths and the project overview, and editing a template never invalidated anything | The module key now hashes the full `files_context` (path + language + body), the overview is no longer part of the module prompt, and `PROMPT_VERSION` — a hash of `prompts.py` itself — is embedded in every key. The key now covers everything the prompt is built from |
| `llm/client.py`, `core/projects.py`, `server/routers/scan.py`, `frontend/src/pages/Home.tsx` | The web UI gave no sign of what an index cost: tokens were accumulated and thrown away | `LLMClient.total_requests` counts every request sent (retries included), a finished scan stores `last_scan_usage` on its record, and the project card shows requests / in / out / $ |
| `frontend/src/lib/api.ts`, `frontend/src/pages/Home.tsx` | A finished scan only reached the one page instance that started it: reload the page, or lose the SSE connection, and the result was silent — a dropped connection was even reported as a scan failure | The project list is the single completion path. While any record is `pending`/`scanning` the list is polled every 3 s, the card reads 索引中… from the server's status, and a dropped progress stream means the text stopped, not that the scan failed |
| `server/models.py`, `server/routers/chat.py` | The model picked in Settings applied to scans but not to Q&A | `ChatRequest.model` follows the same override as a scan |
| `frontend/src/stores/wiki.ts` | The default model `deepseek` overrode the server-side config | Model defaults to empty ("use server config"); persisted state is migrated to Chinese |

## Project history

The server keeps a project's working copy in memory, so a restart used to lose
it. The registry keeps the *input* of every scan instead:

- `~/.repowiki/projects.json` — one record per repo: id, name, path or url,
  file count, lines, language, status, error, timestamps, the commit the tree
  was at when the scan finished, and what that scan spent (requests, tokens,
  cost).
- `GET /api/projects` — the history, newest first; a scan that is running
  reports its live status. Each entry carries `stale`, `changed_files` and
  `reindex_mode`. `?refresh=1` re-runs the drift check instead of reusing the
  15-second cached answer.
- `POST /api/projects/{id}/reindex` — make a project usable: reuse it when it
  is loaded, otherwise scan it. `force: true` always runs a fresh scan;
  `full: true` on top of that regenerates every page.
- `~/.repowiki/projects/<id>/wiki.json` — the generated wiki (pages, sidebar,
  knowledge cards).
- `~/.repowiki/projects/<id>/project.json.gz` — the scanned project, file
  contents included (kiro: 298 KB gzipped). The server restores it on first
  access after a restart, so the file view, repo map, diff and chat keep
  working without a rescan.
- Scanning the same path or url twice reuses the same project id, so the
  history has one entry per repo and `/project/<id>` URLs stay valid.

## Open vs re-index

- **New project**: entering a path or URL and pressing 生成 Wiki starts the
  scan right away and streams the progress into the page.
- **Already indexed**: 打开 reads the stored wiki and opens it without
  scanning anything. Verified after a restart: one click, zero re-index
  requests.
- **Re-index**: 重新索引 always runs a fresh scan (the LLM cache keeps kiro
  around 6 s).
- If the source tree moved after the last index, the card shows 源文件已更新 N
  and says what a rebuild would cost: 可增量 when files were only added or
  edited, 需全量 when something was deleted or renamed, when a build config
  changed, or when over half the repo moved. The main button takes that name,
  and a 全量 next to it is the escape hatch for when the cache itself is what
  you distrust.
- The check diffs the repo against the commit recorded when the scan finished
  — for a record written before that existed, against the commit that was
  current at its timestamp — so it costs one `git diff` and reads no file
  body. Outside a git repo it falls back to the stored per-file size/mtime.
- Reusing a cached module doc is not an approximation: the key covers every
  input the module prompt is built from, so a reused answer is exactly what
  the same prompt would produce now. What neither mode can know is what no
  prompt ever contained — a dependency's internals — so a full run is a fresh
  sample, not a more correct one.
- Finishing needs no manual refresh: while any record is `pending`/`scanning`
  the list is polled every 3 s, and the scan's own page jumps into the project
  as soon as the list reports `done`.
- The server only rebuilds when it is asked to.

## Rebuild

```bash
cd frontend
npm ci
npm run build          # tsc --noEmit && vite build -> src/repowiki/server/static

cd ..
pip install -e ".[web]"
```

## Run

`repowiki serve` binds `0.0.0.0` without authentication, so the web UI is
started explicitly on the loopback interface instead (from the repository
root, with the virtualenv active):

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
  python -m uvicorn repowiki.server.app:create_app \
  --factory --host 127.0.0.1 --port 8765
```

`PYTHONUTF8=1` is required: the Windows console codepage is GBK and Rich's
emoji crash the CLI without it.

A small launcher script outside the repository starts the same command in a
double-clicked console.

## Verify

```bash
python -m pytest -q          # 261 passed
repowiki diff <repo> HEAD~1..HEAD
```

## Rollback

A separate virtualenv with the PyPI 0.6.0 wheel still works; point `repowiki`
at it to switch back.
