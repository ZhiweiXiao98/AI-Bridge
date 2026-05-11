# AI Bridge

> 云-端协同的 AI 智能体开发平台，采用 **Server（云端中台）+ Client（远程客户端）+ Mobile（移动端）** 三端架构，支持浏览器模式与 API 模式双通道 LLM 交互，集成 RAG 知识检索、Docker 沙箱执行、技能系统、守护进程等能力。

---

## 功能特性

- **双通道 LLM 交互** — 浏览器模式（Selenium 驱动 Web AI 页面）+ API 模式（OpenAI/Gemini/DeepSeek 兼容接口）
- **RAG 知识检索** — 基于 ChromaDB + fastembed 的自研向量检索引擎，支持增量索引与重排序
- **Docker 沙箱** — 隔离的代码执行环境，安全运行用户代码
- **技能系统** — 可扩展的 Skill 插件架构，内置文件操作、代码执行、知识搜索、网络搜索
- **守护进程** — 后台建议助手，基于对话上下文主动提供建议
- **上下文管理** — 多层上下文窗口（系统/长期/工作/短期），支持自动压缩
- **Fallback Chain** — 多 Profile 级联降级，API 限流时自动切换备用模型
- **移动端** — 基于 Flet 的 Android 客户端，支持局域网远程连接
- **Rhino 集成** — Rhino 3D 建模软件插件，AI 辅助 BIM 设计
- **插件系统** — 面板插件架构，支持自定义 UI 扩展

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    AI Bridge Server                           │
│                    (server.py - FastAPI)                      │
│  ┌─────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │ FastAPI  │  │ WorkerThread │  │  KnowledgeServiceV2  │    │
│  │ + WS     │  │ (Qt Thread)  │  │  (ChromaDB+fastembed)│    │
│  └────┬─────┘  └──────┬───────┘  └──────────────────────┘    │
│       │               │                                       │
│  ┌────┴─────┐  ┌──────┴───────┐  ┌──────────────────────┐    │
│  │ Signal   │  │ AgentManager │  │  DaemonThread         │    │
│  │ Bridge   │  │ + LLMProvider│  │  (Background Suggest) │    │
│  └────┬─────┘  └──────────────┘  └──────────────────────┘    │
│       │                                                       │
│  ┌────┴──────────────────────────────────────────────────┐   │
│  │            ConnectionManager (WebSocket Hub)           │   │
│  └──────────────────────┬────────────────────────────────┘   │
└─────────────────────────┼────────────────────────────────────┘
                          │ WebSocket
          ┌───────────────┼───────────────┐
          │               │               │
   ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐
   │ RemoteWorker│ │  Mobile App │ │  Browser    │
   │ (Client)    │ │  (Flet)     │ │  (Selenium) │
   └─────────────┘ └─────────────┘ └─────────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| Server | FastAPI + Uvicorn + WebSocket |
| Client | PySide6 (Qt) + Selenium |
| Mobile | Flet (Flutter for Python) |
| RAG | ChromaDB + fastembed |
| LLM | OpenAI API / Google Gemini / DeepSeek (兼容接口) |
| 沙箱 | Docker |
| 认证 | JWT + SQLite |

## 快速开始

### 环境要求

- Python 3.10+
- Chrome 浏览器（浏览器模式需要）
- Docker（沙箱功能需要，可选）

### 1. 克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/ai-bridge-open.git
cd ai-bridge-open
```

### 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

### 3. 配置

所有可配置项集中在 [app/core/app_constants.py](app/core/app_constants.py) 中，支持两种修改方式：

1. **环境变量（推荐）** — 复制 `.env.example` 为 `.env`，修改对应值即可
2. **直接修改常量** — 编辑 `app/core/app_constants.py` 中的默认值

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入你的配置
# 关键配置项：
#   UPSTREAM_AI_URL        — 浏览器模式的上游 AI 网页地址
#   AUTH_ADMIN_PASSWORD    — 管理员密码（生产环境务必修改）
#   DEFAULT_API_BASE_URL   — API 模式的默认 Base URL
#   DEFAULT_API_MODEL      — 默认模型名称
#   SERVER_HOST / SERVER_PORT — 服务器监听地址和端口
#   CHROME_PORT            — Chrome 远程调试端口
```

详细配置说明请参考 [.env.example](.env.example) 中的注释。

### 4. 配置 API 模式

```bash
# 复制 API 模式配置模板
cp config/api_mode.example.json config/api_mode.json

# 编辑 config/api_mode.json，填入你的 API Key 和模型配置
```

`api_mode.json` 支持多个 Profile，每个 Profile 可配置不同的 LLM 提供商。详见 [config/api_mode.example.json](config/api_mode.example.json)。

### 5. 启动 Server

```bash
python server.py
```

Server 默认监听 `0.0.0.0:8765`（可通过 `SERVER_HOST`/`SERVER_PORT` 环境变量修改）。

### 6. 启动 Client

```bash
python start_client.py
```

Client 会自动连接本地 Server。

### 7. 启动移动端（可选）

```bash
cd mobile
pip install -r requirements_mobile.txt
python main.py
```

## 浏览器模式配置

浏览器模式通过 Selenium 驱动 Chrome 浏览器与 Web AI 页面交互。

### 配置上游 AI 网页地址

在 `.env` 文件中设置 `UPSTREAM_AI_URL`：

```bash
# 示例：适配不同的 AI 网站
UPSTREAM_AI_URL=https://chat.openai.com
# UPSTREAM_AI_URL=https://claude.ai
# UPSTREAM_AI_URL=https://poe.com
```

此配置全局生效，Server 启动 Chrome 时会自动打开该地址。

### 前置条件

1. 安装 Chrome 浏览器
2. 以远程调试模式启动 Chrome：

```bash
# Linux/macOS
google-chrome --remote-debugging-port=9527

# Windows
chrome.exe --remote-debugging-port=9527
```

3. 在 Chrome 中打开并登录你的 AI 网页

### 适配不同的 Web AI 页面

本项目默认适配一种 Web AI 页面的 DOM 结构。如果你使用不同的 AI 网站，需要修改以下文件中的 CSS 选择器：

- [app/core/driver/config.py](app/core/driver/config.py) — `SELECTORS` 字典，定义了聊天消息、输入框、发送按钮等元素的 CSS 选择器
- [app/core/driver/interaction.py](app/core/driver/interaction.py) — 交互逻辑，如消息发送、会话切换等

关键选择器说明：

| 选择器 | 用途 |
|--------|------|
| `chat_items` | 聊天消息气泡 |
| `input_area` | 输入框 textarea |
| `send_buttons_xpath` | 发送按钮（多个备选） |
| `session_item` | 左侧会话列表项 |
| `scroll_container_xpath` | 滚动容器 |

> **提示**：打开你的 AI 网页，使用浏览器开发者工具（F12）检查元素，将对应的 CSS 选择器替换到 `config.py` 中即可。

## 项目结构

```
ai-bridge-open/
├── app/
│   ├── core/                  # 核心引擎层
│   │   ├── api/               # API 流式处理
│   │   ├── browser_sync/      # 浏览器消息同步
│   │   ├── daemon/            # 守护进程
│   │   ├── driver/            # Selenium 浏览器驱动
│   │   ├── engine/            # 对话引擎
│   │   ├── knowledge/         # RAG 知识检索
│   │   ├── logging/           # 日志系统
│   │   ├── prompt_runtime/    # 提示词运行时
│   │   ├── round_state/       # 回合状态机
│   │   ├── sandbox/           # Docker 沙箱
│   │   ├── services/          # 业务服务
│   │   ├── skills/            # 技能系统
│   │   ├── tool_runtime/      # 工具运行时
│   │   ├── utils/             # 工具函数
│   │   └── worker_modules/    # Worker 子模块
│   └── ui/                    # PySide6 界面层
│       ├── components/        # UI 组件
│       ├── dialogs/           # 对话框
│       ├── managers/          # UI 管理器
│       ├── pages/             # 页面
│       └── plugins/           # UI 插件
├── mobile/                    # Flet 移动端
├── rhino/                     # Rhino 3D 集成
├── rhino_plugin/              # Rhino 插件
├── plugins/                   # 面板插件
├── Prompt/                    # 提示词模板
├── config/                    # 配置文件
├── tests/                     # 测试
├── docs/                      # 文档
├── server.py                  # Server 入口
├── start_server.py            # Server 启动器
├── start_client.py            # Client 启动器
└── boot_remote.py             # 远程客户端引导
```

详细的项目结构说明请参考 [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)。

## 配置文件说明

| 文件 | 说明 | 是否必须 |
|------|------|----------|
| `.env` | 环境变量（API Key、密码等） | ✅ 必须创建 |
| `config/api_mode.json` | API 模式 Profile 配置 | ✅ API 模式必须 |
| `config.example.json` | 主配置示例 | 首次启动自动生成 |
| `config/workspace_presets/` | 工作区布局预设 | 可选 |
| `config/plugins.json` | 插件注册 | 可选 |

## 运行测试

```bash
pip install pytest pytest-cov pytest-mock pytest-asyncio httpx
python -m pytest tests/ -v
```

## License

MIT License
