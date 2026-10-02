<h1 align="center">AI-Bridge</h1>

<p align="center">
  <strong>把网页 AI、模型 API 和本地工具放进同一个工作台。</strong><br />
  在项目中对话、调用工具、检索资料，用桌面端和手机连接你的 AI 工作环境。
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&amp;logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/PySide6-41CD52?logo=qt&amp;logoColor=white" alt="PySide6 桌面客户端" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&amp;logoColor=white" alt="FastAPI 服务端" />
  <img src="https://img.shields.io/badge/Browser%20%2B%20API-5865F2" alt="Browser 与 API 双模式" />
</p>

<p align="center">
  <a href="#quick-start">快速开始</a> ·
  <a href="docs/文档入口.md">文档</a> ·
  <a href="docs/当前项目状态.md">项目进展</a> ·
  <a href="https://github.com/ZhiweiXiao98/AI-Bridge/issues">反馈问题</a>
</p>

---

AI-Bridge 是一套面向中文开发者的 AI 智能体工作台。通过 Browser 模式接入 AI 网页，或在 API 模式中配置模型服务，让对话使用同一套项目上下文、Skills 和工具运行时。

## 特性

<table>
<tr>
<td width="50%" valign="top">
<h3>网页与 API，按任务选择</h3>
<p>连接 AI 网页，或配置 Gemini、OpenAI-compatible、MiMo 等模型服务。API 模式支持多个 Profile、流式回复、会话级模型设置与思考过程展示。</p>
<p><a href="docs/API模式原生工具调用与提示词分流计划.md">模型与工具协议 →</a></p>
</td>
<td width="50%" valign="top">
<h3>让对话调用工具</h3>
<p>通过 Skills 读写文件、执行代码、操作 Git 和搜索资料。工具结果回到对话中，支持继续处理任务；输入 <code>/</code> 可选择 Skill 引用。</p>
<p><a href="app/core/skills/SKILLS_GUIDE.md">Skills 指南 →</a></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<h3>看清每次请求的上下文</h3>
<p>查看系统提示、长期记忆、工作记忆和对话历史的预算，按需压缩历史。请求快照随会话保存，方便核对模型收到的内容。</p>
<p><a href="docs/上下文系统建设计划.md">上下文与快照 →</a></p>
</td>
<td width="50%" valign="top">
<h3>让项目资料参与回答</h3>
<p>通过 KnowledgeSearch 检索项目知识，使用向量索引和重排定位相关内容。知识索引按项目隔离，可查看检索健康状态。</p>
<p><a href="docs/知识库V2重构计划.md">项目知识库 →</a></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<h3>组织自己的工作空间</h3>
<p>使用可停靠和浮动的面板组织聊天、日志、资料与工具。内置浏览器可以预览网页和本地 HTML，也可以通过面板插件扩展工作台。</p>
<p><a href="docs/内置浏览器面板.md">内置浏览器 →</a> · <a href="docs/插件开发指南.md">插件开发 →</a></p>
</td>
<td width="50%" valign="top">
<h3>在手机上继续对话</h3>
<p>手机通过轻量 Web/PWA 客户端连接电脑服务，查看消息、切换会话、发送提示并检查状态。模型请求和工具执行由服务端处理。</p>
<p><a href="mobile/README.md">移动端说明 →</a></p>
</td>
</tr>
</table>

还有这些工作流：

- **项目切换**：在桌面端选择当前项目，查看会话中的项目关联。见[项目与路径](docs/项目切换功能改造计划书.md)。
- **资料整理**：把 Markdown 转成 HTML，在工作台中生成和预览。见[资料整理](docs/资料整理Agent实施计划书.md)。
- **后台建议**：由 Subagent 根据对话上下文生成建议。见[后台任务](docs/守护进程方案.md)。

各能力的实现范围和待验收项见[当前项目状态](docs/当前项目状态.md)。

## 接入方式

| 方式 | 连接什么 | 准备什么 |
| --- | --- | --- |
| Browser | 通过 Chrome CDP 与已适配的 AI 网页交互 | Chrome、网页登录状态与调试端口 `9527` |
| API | Gemini、OpenAI-compatible、MiMo 等模型服务 | 服务地址、模型和 API Key |
| 无上下文网页 Profile | 在 API 模式中按本地上下文组织网页请求 | `browser_stateless` Profile 与对应网页配置 |

模型和工具能力随 Provider 与 Profile 配置而定。OpenAI-compatible 已有同步和流式原生工具调用；具体选择和回退规则见[工具协议](docs/API模式原生工具调用与提示词分流计划.md)。

<a id="quick-start"></a>

## 快速开始

以下是 Windows PowerShell 下的源码启动流程，需要 Git 和 Python。

### 1. 获取项目并安装依赖

```powershell
git clone https://github.com/ZhiweiXiao98/AI-Bridge.git
cd AI-Bridge
py -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 -m pip check
```

已有仓库和虚拟环境时，直接检查或安装依赖即可。`requirements.txt` 声明全项目依赖；`requirements.lock` 保存环境快照。仅部署桌面客户端可参考 `requirements_client.txt`。

### 2. 启动服务端与桌面端

在仓库根目录打开两个终端，分别运行：

```powershell
# 终端一：服务端
.\.venv\Scripts\python.exe -X utf8 server.py --mode api
```

```powershell
# 终端二：桌面客户端
.\.venv\Scripts\python.exe -X utf8 boot_remote.py --mode api
```

客户端登录窗口填写服务端地址；本机使用 `127.0.0.1`，默认端口为 `8765`。登录后，在 API 设置页保存 Provider、模型和 API Key，完成模型/工具探测，再新建对话。

### 3. 选择其他入口

<details>
<summary><strong>图形启动器与 Browser 模式</strong></summary>

运行图形启动器，选择 Browser / API 模式：

```powershell
.\.venv\Scripts\python.exe -X utf8 start_server.py
.\.venv\Scripts\python.exe -X utf8 start_client.py
```

Browser 模式需要安装 Chrome、配置 AI 网页并连接调试端口 `9527`。使用无上下文网页源时，参阅 [Browser Profile 说明](docs/无上下文浏览器Profile计划书.md)。

</details>

<details>
<summary><strong>手机访问</strong></summary>

保持电脑上的 Data-Bridge 服务运行，另开终端启动移动端页面：

```powershell
.\mobile\serve_mobile.ps1 -Port 8787
```

在可访问电脑的网络中，用手机浏览器打开 `http://<电脑 IP>:8787`。在页面中填写电脑的服务地址、端口 `8765` 和登录信息。使用与维护见[移动端文档](mobile/README.md)。

</details>

<details>
<summary><strong>本地配置与生成文件</strong></summary>

- API Key 和服务配置保存在 `config/api_mode.json`、`config.json`、`server_config.json` 等本地文件。
- 会话、最近项目、布局和知识索引由运行时保存，路径见[结构导航](docs/项目结构导航.md)。
- Docker 用于沙盒代码执行；相关测试环境见[沙盒说明](app/core/sandbox/README.md)。
- `docs/导出HTML/` 是本地生成目录；批量导出方法见[资料整理](docs/资料整理Agent实施计划书.md)。
- `tools/smart_update_structure.py` 生成独立的 `docs/PROJECT_STRUCTURE_DUMP.md` 辅助清单。

</details>

## 文档

| 想了解什么 | 从这里开始 |
| --- | --- |
| 全部主题资料 | [文档入口](docs/文档入口.md) |
| 当前能力与开发重点 | [项目状态](docs/当前项目状态.md) |
| 代码结构与模块职责 | [结构导航](docs/项目结构导航.md) |
| 开发约定与 AI 协作 | [AGENTS.md](AGENTS.md) |
| 历史决策与验证记录 | [AI_JOURNAL.md](AI_JOURNAL.md) |

## 开发与反馈

在仓库根目录执行默认协议回归：

```powershell
.\run_checks.ps1
```

按模块运行测试、UI 测试和集成测试的方法见[测试说明](tests/README.md)。提交前检查 `git status --short` 和 `git diff --check`，本地配置与生成物按 `.gitignore` 管理。

欢迎通过 [Issues](https://github.com/ZhiweiXiao98/AI-Bridge/issues) 反馈问题或提出想法。报告问题时附上运行模式、复现步骤与相关日志；开发前先阅读[协作规则](docs/AI协作规则.md)。

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
