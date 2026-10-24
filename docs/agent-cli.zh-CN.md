# 让 coding agent 使用 RepoWiki

RepoWiki 暴露两条「给 agent 用的」命令（`map`、`diff`）和一条生成命令
（`scan`）。它们适合被 agent 调用，不只是给人在终端里看的。

## CLI 现在提供什么

| 命令 | LLM 开销 | 输出 | 用途 |
| --- | --- | --- | --- |
| `map <repo> -n 30 --format json` | 无 | 按依赖排序的文件 + 语言 + 行数 | 决定先读哪些文件 |
| `diff <repo> <refspec> --format json` | 无 | 变更文件、评审排名、影响范围 | 决定先评审哪个改动 |
| `scan <path\|url> -o dir -f markdown\|json\|html -l zh` | 有 | 落盘的 wiki 文件 | 生成文档 |
| `chat <repo>` | 有 | 交互式 REPL | 只给人用，需要 TTY |
| `cache-clear` | 无 | — | 改 prompt 或换模型之后 |

`map` 和 `diff` 是确定性的：只构建 import 图并跑 PageRank，不需要 API key，
也不联网。

输出结构：

```json
// map
{"root": "…", "file_count": 116, "entries": [
  {"rank": 1, "path": "src/App.tsx", "score": 0.0155, "language": "tsx", "lines": 45}]}

// diff
{"root": "…", "refspec": "HEAD~1..HEAD", "file_count": 116, "changed": 1, "entries": [
  {"path": "README.md", "change": "M", "rank": 21, "score": 0.0031,
   "direct_dependents": 0, "transitive_dependents": 0}]}
```

JSON 走 stdout，警告走 stderr，退出码 0/1。扫描有截断时会额外带
`partial_coverage`，说明丢了哪些文件。

## 怎么接进 agent

### Skill（Qoder、ZCode、Claude Code）

Skill 的源头在本仓库 `skills/repowiki/SKILL.md`。复制到各 agent 的 skill 目录：

```bash
cp -r skills/repowiki ~/.qoder-cn/skills/
cp -r skills/repowiki ~/.zcode/skills/
```

之后 agent 的技能列表里就会出现 `repowiki`，任务匹配时（「从哪里开始读？」
「这次改动该先看哪个文件？」）会自动加载。

### 纯指令方式

不支持 skill 的 agent，把下面这段放进 `AGENTS.md` 同样有效：

```markdown
## RepoWiki
遇到陌生的仓库，先跑：
  repowiki map <repo> -n 30 --format json
改完代码要评审时：
  repowiki diff <repo> HEAD~1..HEAD --format json
这两条不花钱。`scan` 会消耗 LLM token，只在用户明确要求时跑。
不要运行 `repowiki serve`（绑定 0.0.0.0 且无鉴权）。
```

### 不做 MCP 封装

刻意选择 CLI 而不是 MCP：`map` 和 `diff` 就是一行 shell 调用，包成 tool schema
只多一层，不增加能力。只有 agent 无法执行命令时才需要包一层。

## 注意

- `repowiki` 必须在 `PATH` 上 —— 把虚拟环境的 `Scripts` 目录加进去。Windows
  下安装的入口脚本会自己设置 `PYTHONUTF8=1`，GBK 控制台需要它。
- WebUI 提供更完整的能力（Wiki、知识卡片、RAG 问答）：
  http://127.0.0.1:8765/ ，用桌面快捷方式启动。
