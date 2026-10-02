# 无上下文浏览器 Profile

> 复核日期：2026-09-26。`browser_stateless` 是 API 模式可选择的一类网页消息源。

## 作用与使用

选择 `browser_stateless` Profile 后，Data-Bridge 使用本地会话上下文构造网页请求，再通过浏览器发送、读取 DOM 和解析回复，将结果交回本地对话与工具运行时。

本地会话保存上下文事实。网页会话需要根据目标站点的能力进行清理或重置；每次请求是否完成重置必须由页面状态确认。

用户可为会话选择 Profile 或 Fallback Chain。设置页管理 Profile 本身，运行时按当前会话的有效配置选择来源。Browser 和 API 都可承担对话任务，具体调用方式由用户选择、模型能力和配置决定。

## 当前处理链

1. API Source 读取会话的模型使用配置。
2. `browser_stateless_profile.py` 编译请求上下文并归一化响应。
3. `worker_browser_stateless.py` 协调网页发送与结果读取。
4. 浏览器驱动复用消息提取、segments 和 transient 解析能力。
5. `UpstreamEvent` / `UpstreamConsumer` 投影流式、消息、回合与上下文状态。
6. 本地对话保存最终结果；工具意图交给共享工具运行时。

工具协议固定为 `markdown_fallback_only`。该类型跳过 HTTP 原生 tools 探测，网页工具调用使用文本协议。

## 实现位置

| 位置 | 职责 |
| --- | --- |
| `app/core/api_mode_config.py` | Profile 配置与工具协议选择 |
| `app/core/api_source.py` | 会话配置、上游来源与本地上下文 |
| `app/core/worker_modules/browser_stateless_profile.py` | 请求编译与响应归一化 |
| `app/core/worker_modules/worker_browser_stateless.py` | 网页请求流程 |
| `app/core/worker_modules/upstream_events.py` | 上游事件结构 |
| `app/core/worker_modules/upstream_consumer.py` | 状态和 UI 投影 |
| `app/core/driver/` | 浏览器连接、交互和解析 |

## 运行边界

- 网页消息经渲染后的 DOM 读取，选择器与按钮行为需要根据目标页面核对。
- 目标会话、发送前准备、重置、生成中 transient 内容和最终回复都需要明确识别。
- 单个浏览器资源上的请求需要协调占用和取消，避免不同会话互相影响。
- 后台 Subagent 使用 API 源；其配置与当前聊天会话的 Profile 选择独立。
- 请求失败时按配置的 fallback 处理，并保留超时、目标不存在、解析失败等阶段信息。

## 待验收

- [ ] 目标会话选择、发送前重置和重置结果确认。
- [ ] 普通回复、思考、代码块和工具调用的解析与本地保存。
- [ ] 生成中 transient 更新到最终内容的切换。
- [ ] 取消、断网、超时和站点 UI 变化时的状态与用户提示。
- [ ] 会话切换、浏览器资源占用和 fallback 顺序。
- [ ] API 与网页来源经统一上游事件后的消费语义一致。

聚焦用例见 `tests/test_browser_stateless_profile.py`、`tests/test_api_mode_browser_stateless.py`、`tests/test_upstream_consumer.py`。真实站点验收需要单独记录。

设计沿革见[2026-05-16 方案原文](归档/无上下文浏览器Profile方案记录_2026-05-16.md)，当前能力见[项目状态](当前项目状态.md)。
