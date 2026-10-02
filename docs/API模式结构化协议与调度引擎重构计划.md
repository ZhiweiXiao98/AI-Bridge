# API 结构化消息与调度

> 复核日期：2026-09-26。本文说明现有消息、工具结果和流式状态的职责边界。

## 消息与执行结果

消息携带会话、角色、内容和 segments。`ConversationMessage` 提供历史与请求字典转换；聊天气泡根据消息内容及 segment 类型展示正文、思考与工具信息。

工具运行时使用 `ToolIntent` 表达调用，`ToolExecutionResult` 表达执行结果，`ToolRoundResult` 表达一轮结果。API Source 将反馈保存为结构化 `tool_feedback`，并将工具结果交给后续请求。

## 状态与投影

`APIStreamHandler`、`APIStreamState` 和 Worker 的 API 流桥接处理流式增量；上游事件通过 consumer 投影到状态信号与聊天 UI。流结束、工具执行和整个回合完成是不同事件，UI 按对应状态更新。

会话切换与流重载需要保持 `conversation_id`、消息标识和流标识对应，验证过期事件的处理及工具结果绑定。

## 代码位置

- `app/core/context_message_models.py`、`app/core/conversation_store.py`
- `app/core/tool_runtime/models.py`、`app/core/tool_runtime/conversation_loop.py`
- `app/core/api/`、`app/core/worker_modules/worker_api_stream.py`
- `app/core/worker_modules/upstream_events.py`、`app/core/worker_modules/upstream_consumer.py`
- `app/ui/components/chat.py`、`app/ui/components/chat_bubble_stream.py`、`app/ui/pages/chat/`

## 验收范围

- [ ] 连续工具调用期间状态、结果和最终回答保持对应。
- [ ] 快速切换会话、取消和重载时，流式内容进入正确的目标会话。
- [ ] 断网、超时、限流及 Provider 参数错误得到可识别的状态与反馈。
- [ ] 工具结果重复、并发操作和陈旧请求的处理规则获得实测证据。

原生工具选择与 fallback 见[工具协议](API模式原生工具调用与提示词分流计划.md)，实施细节见[回合状态机方案](API模式回合状态机与双协议工具调用改造计划书.md)。
