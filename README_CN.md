# RepoWiki

个人自用的 [RepoWiki](https://github.com/he-yufeng/RepoWiki) 分支：从终端或浏览器
给代码库生成 wiki。中文优先，在 Windows 上跑。

不发布到 PyPI，也不承诺提供支持。为什么和上游不同见
[FORK.zh-CN.md](FORK.zh-CN.md)，改了什么见
[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)。

## 跑起来

首次构建：

```bash
cd frontend && npm ci && npm run build
pip install -e ".[web]"
repowiki config set api_key <key>     # 也可用 DEEPSEEK_API_KEY 等环境变量
```

启动（只监听回环；桌面快捷方式 “RepoWiki Restart” 跑的是同一条命令）：

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
  python -m uvicorn repowiki.server.app:create_app \
  --factory --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765/>。项目列表存在 `~/.repowiki/projects.json`，重启不丢。

## 能做什么

- 结构化 wiki：概览、模块文档、架构图（含确定性的调用图/数据流图）、阅读路径。
- 增量重扫：只重生成源码变了的页面，LLM 结果走内容哈希缓存。
- 知识卡片、测试地图、仓库地图、diff 评审顺序。
- Web UI 加 `repowiki chat` 终端问答，答案带 `file:start-end` 出处。
- 导出 Markdown / JSON / 自包含 HTML，`--site` 可直接上 GitHub Pages。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `repowiki scan <path\|url>` | 生成 wiki（花 token） |
| `repowiki chat <repo>` | 终端多轮问答 |
| `repowiki map <repo> --format json` | 阅读顺序，零 LLM 调用 |
| `repowiki diff <repo> <refspec>` | 变更评审顺序，零 LLM 调用 |

模型用 `repowiki config set model deepseek`（claude / gpt / gemini / qwen / kimi /
glm / mimo 等），中文输出用 `-l zh`。

## 文档

- [FORK.zh-CN.md](FORK.zh-CN.md) — 这个分支是什么、怎么决定改动、怎么跟上游同步
- [CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md) — 改动时间线
- [docs/agent-cli.zh-CN.md](docs/agent-cli.zh-CN.md) — 给 coding agent 的 CLI 说明
- [skills/repowiki/SKILL.md](skills/repowiki/SKILL.md) — 让 agent 先 map 再读代码

## 上游与许可

基于 [he-yufeng/RepoWiki](https://github.com/he-yufeng/RepoWiki)，MIT 许可，
原始版权归 Yufeng He。