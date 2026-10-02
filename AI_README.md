# AI Bridge 运行与文件协议

AI Bridge 由服务端执行工具、管理项目和对话，桌面客户端通过 HTTP/WebSocket 提交请求并显示结果。开发入口为 [AGENTS.md](AGENTS.md)，当前能力见[项目状态](docs/当前项目状态.md)。

## 桌面客户端

源码环境安装 `requirements.txt` 后，运行 `python start_client.py` 打开启动器，或运行 `python boot_remote.py --mode api` 直接进入 API 客户端。登录窗口填写服务器地址，默认端口 `8765`。Browser 模式选择 `browser`，需要服务端连接 Chrome 调试会话。

## 文件操作协议

- 通过带 `# filename:` 的代码块提交给代码暂存/应用流程时，内容代表完整文件，必须保留原文件必要部分。
- 使用原生编辑工具时，按工具支持的补丁、行编辑或完整写入语义操作，并读取结果验证。
- `AI_JOURNAL.md` 的新记录追加写入，日记轮换须先完整保存归档。
- `tool_call` Markdown 围栏内部避免嵌套三反引号；工具内容使用参数字符串表达。
- 工具调用格式和参数按 Skills schema；需要细节时使用 `get_skill_detail`。API 工具协议由 Profile 能力及运行时选择。

## 执行与路径

- 普通代码展示、文件暂存与执行是不同操作。通过结构化 `code_execution` Skill 执行代码；兼容代码块执行规则由解析器和执行策略决定。
- 沙盒将选定的宿主机项目挂载到 `/workspace`；写入挂载目录会影响项目文件。
- 原生 Windows 开发使用项目 `.venv`，无须假设当前代理处于 Docker 内。
- 服务端业务使用 `APP_ROOT` 定位软件资源，使用 `ProjectContext` 定位当前项目。
- 远程客户端通过 RPC 获取服务端结果；需返回值的接口必须提供响应通道并处理失败和超时。

## 验证与文档

改动后运行相应模块测试，检查真实调用契约与持久化行为。修改启动、面板或通信链路时，需要导入和交互验证；报告说明测试范围与尚未验证的环境。

开发用 Python 命令：`.\.venv\Scripts\python.exe -X utf8`。测试说明在 `tests/README.md`；新功能使用说明写入对应文档，历史证据记入 `AI_JOURNAL.md`。
