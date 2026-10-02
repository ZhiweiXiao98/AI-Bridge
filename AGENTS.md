# Agent 入口

面向中文开发者，优先用中文日志和中文文档。

按顺序阅读当前事实：

1. [文档入口](docs/文档入口.md)
2. [当前项目状态](docs/当前项目状态.md)
3. [行驶记录](AI_JOURNAL.md)
4. [项目结构导航](docs/项目结构导航.md)

## 开发约定

- 先检查 Git 工作区，保留已有改动；历史计划的未勾选项需与代码核对。
- 工程协作细则见 [AI 协作规则](docs/AI协作规则.md)，运行时文件协议见 [AI_README.md](AI_README.md)。
- 使用 `.\.venv\Scripts\python.exe -X utf8` 运行 Python；测试分组见 [tests/README.md](tests/README.md)。
- 服务端保持无界面运行；UI 请求通过 Worker / RemoteWorker 传递，变更 RPC 时同步检查 [remote_protocol.py](app/core/remote_protocol.py)。
- 软件资源路径使用 `APP_ROOT`，项目文件使用 `ProjectContext`；项目切换需同步客户端和服务端。
- 状态、会话和请求快照的持久化改动需验证重新加载，UI 空状态也需可读。
- 当前事实就地更新，历史证据追加到日记；轮换归档时保留原文并验证 `journal_search` 可检索。

`AGENT.md` 是此入口的短链接；模块说明统一维护在结构导航中。
