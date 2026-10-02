# API 回合状态与工具调用

> 复核日期：2026-09-26。本文说明当前回合、流式事件与工具执行的协作方式。

## 回合与流式事件

API Source 保存请求快照及回合状态；工具循环记录检测、执行、后续生成与结束。`APIStreamHandler` 负责流式读取，`WorkerStreamBridge` 将上游事件交给 `UpstreamConsumer`，客户端根据事件更新聊天与工具展示。

| 状态或事件 | 含义 |
| --- | --- |
| `streaming_initial_reply` | 初始回复生成 |
| `detecting_tools` | 识别工具候选 |
| `running_tools` | 执行本轮工具 |
| `generating_followup` | 根据工具反馈继续生成 |
| `finalized` | 回合快照完成 |
| `started` / `streaming` / `completed` | 单个流的开始、增量与完成 |
| `error` / `cancelled` | 单个流失败或取消 |

这些状态由对应调用路径维护。流完成、工具完成和回合完成分别承载自己的含义；排查时同时检查 `conversation_id`、`stream_id` 与请求快照。

## 工具协议

Markdown 工具循环由 `app/core/tool_runtime/conversation_loop.py` 协调；原生工具循环位于 `app/core/api_source.py`。两类入口使用工具运行时的意图、执行结果和反馈结构。Profile 的协议选择、能力探测和 fallback 规则见[工具协议与提示词分流](API模式原生工具调用与提示词分流计划.md)。

OpenAI-compatible 已有同步和流式原生工具路径。Gemini 原生工具、多轮 reasoning 回放及真实 Provider 验收仍属于当前开发范围。

## 客户端投影

`app/ui/pages/chat/page.py` 接收回合状态并协调历史展示；`chat_page_stream.py` 与 `message_area_stream.py` 处理流式事件和临时气泡。工具运行阶段需要保持状态提示，最终展示应与会话持久化内容一致。

## 验收

- [ ] 无工具请求、单次工具和连续工具调用均能收口到最终答复。
- [ ] 工具结果、后续回复与流式临时气泡正确对应。
- [ ] 取消、超时、Provider 错误和会话切换得到明确状态。
- [ ] 重载后会话内容、工具反馈与最近请求快照一致。

[回归清单](API模式回合状态机改造回归测试清单.md)用于记录运行证据；[维护检查顺序](API模式回合状态机改造实施顺序清单.md)用于定位变更范围。

## 历史资料

[阶段方案与实施记录](归档/API模式回合状态机与双协议工具调用改造计划书_历史原文_2026-09-26.md)保留本轮整理前原文。当前变更与验证证据追加到 [AI_JOURNAL.md](../AI_JOURNAL.md)。
