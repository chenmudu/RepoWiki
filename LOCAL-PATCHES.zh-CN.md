# 本地补丁（基于 he-yufeng/RepoWiki）

这份克隆包含**上游没有**的本地改动。之所以需要它们：上游版本不处理中文输出、
Windows Git 所有权检查，也不支持 WebUI 的本地路径流程。

- 上游基线：`29d9029b4c770b66772c1d565f2d5b5980074147`（2026-10-23）
- 本仓库（`chenmudu/RepoWiki`，`main` 分支）就是源头，下面每一项改动都已提交在这里。
- 虚拟环境：任意一个执行过 `pip install -e ".[web]"` 的 venv；CLI 命令是 `repowiki`
- 旧 wheel 安装（回滚用）：另一个装有 PyPI 0.6.0 wheel 的 venv

## 每个补丁解决什么问题

| 位置 | 问题 | 修法 |
| --- | --- | --- |
| `llm/prompts.py` | `language: zh` 时 LLM 仍然用英文回答 | 每条 prompt 追加简体中文指令 |
| `core/analyzer.py` | JSON 回答被截断或无法解析，页面退化成占位内容 | 请求 `response_format={"type":"json_object"}` 并重试一次（`_complete_json`） |
| `core/analyzer.py` | WebUI 里的扫描进度是英文 | 进度文案跟随 wiki 语言 |
| `core/wiki_builder.py` | 页面标题和小节标题仍是英文 | `build(..., language="zh")` 本地化标题、小节与标签 |
| `core/diff.py`、`core/churn.py` | Git 拒绝读取属主是另一个 Windows SID 的仓库（`exit 129`） | 每次 git 调用都带 `-c safe.directory=<仓库>`；绝不修改全局 git 配置 |
| `core/diff.py` | 提交不存在或仓库为空时直接抛原始 git 输出 | 对未知 refspec、无提交、非 Git 仓库给出可读的中文报错 |
| `server/routers/*.py` | API 报错是英文 | 改为中文报错 |
| `core/scanner.py`、`ingest/local.py`、`ingest/github.py` | 扫描失败时抛英文错误（"Not a directory"、"Clone failed"） | 目录不存在、仓库地址无法解析、克隆超时/失败、仓库体积过大均改为中文；克隆凭据仍然脱敏 |
| `export/markdown.py` | 导出的 README 目录是英文 | `zh` 时输出 `## 目录` |
| `core/projects.py`、`server/routers/scan.py` | WebUI 没有项目列表，服务一重启已索引项目全丢 | 新增 `~/.repowiki/projects.json` 注册表、`GET /api/projects`、`POST /api/projects/{id}/reindex`；同一个仓库重复扫描复用同一个项目 ID |
| `frontend/` | 整个 WebUI 是英文 | 完整汉化，`lang="zh-CN"` |
| `frontend/src/pages/Home.tsx` | 输入框能填本地路径，但永远提交成 `url` | 识别 Windows/Unix 绝对路径并提交 `path` |
| `frontend/src/pages/Home.tsx` | 首页宣传的功能工具并不具备 | 换成 4 张真实能力卡 |
| `frontend/src/pages/Home.tsx` | 能力卡是纯文字，没有动作 | 改为跳转到当前项目的 Wiki、卡片、地图、问答视图 |
| `frontend/src/pages/Home.tsx` | 已索引项目无处可寻 | 新增"最近的项目"列表，一键重新索引 |
| `frontend/src/pages/Home.tsx` | 能力卡总是静默作用于"最新的项目"，与用户的选择无关 | 引入显式"当前项目"：卡片只为列表中选中的项目渲染；卡片本身带 打开 / 重新索引 / 删除 |
| `core/store.py`、`server/app.py` | 服务重启后内存里的项目全丢，打开项目要整个重扫 | Wiki 与扫描结果按项目 ID 落盘，首次访问时恢复 |
| `server/routers/scan.py` | "打开项目"和"重新索引"是同一个调用 | `reindex` 只有 `force: true` 才重建，否则复用内存或磁盘 |
| `server/routers/fs.py`、`frontend/src/components/PathPicker.tsx` | UI 要求用户手输绝对路径 | `GET /api/fs/browse` 列出盘符与子目录，供文件夹选择弹层使用 |
| `core/staleness.py`、`server/routers/scan.py`、`frontend/` | 源文件改了以后已索引项目仍显示旧 Wiki，且没有任何提示 | 扫描时记下工作区当时所在的提交，列表用它 diff 仓库，打出"源文件已更新 N"。不在 Git 里的目录退回逐文件 大小/mtime 比对。检测不读文件内容、不调 LLM |
| `core/staleness.py`、`frontend/src/pages/Home.tsx` | 提示只说"过期"，不说重建要花多少代价；而且在开始记录提交之前索引的项目永远标不出来 | 漂移改为 diff `last_indexed_commit`（老记录用扫描当时最新的提交）并给出分类：删除、重命名、构建配置变化，或超过一半文件变化 → 需全量，其余 → 可增量 |
| `server/models.py`、`server/routers/scan.py`、`core/analyzer.py` | 重新索引只有一种尺寸：总是复用已缓存的分析结果，仓库结构变了也无法重生 | `ReindexRequest.full` 让本次运行跳过缓存读取、重生全部页面；结果仍会写回缓存 |
| `llm/prompts.py`、`core/analyzer.py` | 增量会静默端出为另一套输入写的模块文档：缓存键只 hash 文件正文，而 prompt 还带了路径和项目概览；改了 prompt 模板也从不失效 | 模块键改为 hash 完整的 `files_context`（路径 + 语言 + 正文），概览从模块 prompt 中移除，`PROMPT_VERSION`（`prompts.py` 自身的源码哈希）进入每个键。现在键覆盖了 prompt 的全部输入 |
| `llm/client.py`、`core/projects.py`、`server/routers/scan.py`、`frontend/src/pages/Home.tsx` | WebUI 看不出一次索引花了多少 LLM：token 一直在累计，然后被丢掉 | `LLMClient.total_requests` 统计真正发出的每个请求（含重试），扫描结束把 requests/tokens/cost 写进 `last_scan_usage`，项目卡显示 请求数 / in / out / $ |
| `server/models.py`、`server/routers/chat.py` | 设置里选的模型只作用于扫描，问答不受影响 | `ChatRequest.model` 与扫描走同一套覆盖逻辑 |
| `frontend/src/stores/wiki.ts` | 默认模型 `deepseek` 会覆盖服务端配置 | 模型默认留空（使用服务端配置）；持久化状态迁移为中文 |

## 项目历史

服务端把项目的工作副本放在内存里，所以过去一重启就没了。现在注册表保存的是每次扫描的**输入**：

- `~/.repowiki/projects.json` —— 每个仓库一条记录：ID、名称、本地路径或仓库地址、文件数、行数、语言、状态、错误、时间戳、扫描完成时工作区所在的提交，以及那次扫描的花费（请求数、token、成本）。
- `GET /api/projects` —— 项目历史，最新的在前；正在扫描的项目会显示实时状态。每条记录带 `stale`、`changed_files` 和 `reindex_mode`。`?refresh=1` 会重跑漂移检测，而不吃 15 秒的结果缓存。
- `POST /api/projects/{id}/reindex` —— 让项目可用：内存里有就复用，没有就扫描；`force: true` 时强制重扫，再加 `full: true` 就重生全部页面。
- `~/.repowiki/projects/<id>/wiki.json` —— 生成的 Wiki（页面、侧边栏、知识卡片）。
- `~/.repowiki/projects/<id>/project.json.gz` —— 扫描结果，含文件内容（kiro 实测 gzip 后 298 KB）。服务重启后首次访问即恢复，因此文件查看、仓库地图、Diff 和问答都不需要重扫。
- 同一个路径或仓库地址重复扫描会复用同一个项目 ID，因此历史里每个仓库只有一条记录，`/project/<id>` 链接长期有效。

## 打开 与 重新索引

- **新项目**：输入路径或地址后点「生成 Wiki」，立即开始扫描，进度流式显示在页面上。
- **已索引项目**：点「打开」直接读取已落盘的 Wiki，不触发任何扫描。重启后实测：一次点击，零次重索引请求。
- **重新索引**：「重新索引」按钮每次都跑一遍新扫描（LLM 缓存让 kiro 约 6 秒完成）。
- 上次索引之后源文件有变化时，项目卡显示"源文件已更新 N"，并说明重建的代价：只有新增和修改时是 可增量；出现删除、重命名、构建配置变化，或超过一半文件变化时是 需全量。主按钮直接用这个名字，旁边的「全量」是你不信任缓存时的出口。
- 检测 diff 的基准是扫描完成时记下的提交——早于这个字段的记录，用其时间戳当时最新的提交——所以代价是一次 `git diff`，不读任何文件正文。不在 Git 仓库里时退回逐文件的 大小/mtime 比对。
- 复用一条模块文档不再是近似做法：它的键覆盖了模块 prompt 的全部输入，所以复用的答案就等于同样的 prompt 现在会产出的答案。两种模式都不知道的是任何 prompt 都不曾包含的东西——依赖模块的内部实现——因此全量只是重新采样，不是更正确。
- 服务端只在被明确要求时才重建。

## 重新构建

```bash
cd frontend
npm ci
npm run build          # tsc --noEmit && vite build -> src/repowiki/server/static

cd ..
pip install -e ".[web]"
```

## 运行

`repowiki serve` 会绑定 `0.0.0.0` 且没有鉴权，所以 WebUI 显式只监听回环地址
（在仓库根目录、虚拟环境已激活的情况下）：

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
  python -m uvicorn repowiki.server.app:create_app \
  --factory --host 127.0.0.1 --port 8765
```

必须带 `PYTHONUTF8=1`：Windows 控制台代码页是 GBK，Rich 的 emoji 会让 CLI 崩掉。

仓库外的一个小启动脚本跑的是同一条命令，双击即可。

## 验证

```bash
python -m pytest -q          # 261 passed
repowiki diff <repo> HEAD~1..HEAD
```

## 回滚

另建一个装 PyPI 0.6.0 wheel 的 venv 仍然可用，把 `repowiki` 指回它即可。

## 回滚

旧 wheel 安装仍可用：`D:\Tools\repowiki-venv\Scripts\repowiki.exe`。
把 `D:\Tools\repowiki.cmd` 指回它即可切回旧版。
