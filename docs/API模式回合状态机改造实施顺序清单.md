# API 回合维护检查顺序

> 复核日期：2026-09-26。回合状态、工具循环和客户端投影已有实现，后续改动沿现有调用链验证。

## 修改顺序

1. 确认目标会话、Profile、协议与问题复现条件，查看最近请求快照。
2. 在 `app/core/api_source.py` 和 `app/core/tool_runtime/conversation_loop.py` 核对消息生成、工具检测、执行和最终收口。
3. 核对 `app/core/api/` 的流事件以及 `app/core/worker_modules/worker_api_stream.py` 的转换。
4. 核对 `upstream_events.py`、`upstream_consumer.py` 与 `app/core/remote_protocol.py` 的字段和信号路由。
5. 核对 `app/ui/pages/chat/page.py`、`chat_page_stream.py`、`message_area_stream.py` 的目标会话、状态提示和气泡更新。
6. 涉及会话或快照写入时，重新加载 `ConversationStore` 检查最终内容。
7. 执行相关自动化测试，并在真实 Provider 下记录受影响流程。

## 修改前后都要核对

| 边界 | 检查内容 |
| --- | --- |
| 协议选择 | Profile、能力探测、原生工具定义和 Markdown 工具说明一致 |
| 状态 | 流式、工具执行、后续生成与回合结束的含义清楚 |
| 事件目标 | 会话、请求和流标识沿服务端、RPC、客户端保持对应 |
| 持久化 | 历史、thinking、工具反馈、快照可重新读取 |
| 异常 | 取消、断流、超时、工具错误和 Provider 错误有可见结果 |
| UI | 空状态、切换会话、重载和结束后的显示可读 |

相关测试包括 `tests/test_worker_api_stream_consumer.py`、`tests/test_upstream_events.py`、`tests/test_upstream_consumer.py` 和 `tests/test_remote_protocol.py`。执行方法见[测试说明](../tests/README.md)。

当前机制见[API 回合说明](API模式回合状态机与双协议工具调用改造计划书.md)，验收场景见[回归清单](API模式回合状态机改造回归测试清单.md)。

## 历史资料

[阶段方案与实施记录](归档/API模式回合状态机改造实施顺序清单_历史原文_2026-09-26.md)保留本轮整理前原文。当前变更与验证证据追加到 [AI_JOURNAL.md](../AI_JOURNAL.md)。
