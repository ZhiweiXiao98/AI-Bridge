# 工具路由与降级排查

## 当前链路

Browser 工具输入由 `worker_browser_tool_input.py` 提取，消息同步由 `worker_browser_message_sync.py` 处理。`ToolRouterService` 将工具意图交给 `app/core/tool_runtime/`，结果随后投影到消息、状态与 UI。

API 工具协议由 Profile 与能力状态选择，原生工具和文本工具调用统一为工具运行时数据。具体规则见[API 工具协议](API模式原生工具调用与提示词分流计划.md)。

## 排查顺序

1. 确认消息源、Profile、目标会话和工具协议。
2. 核对工具输入提取结果、`ToolIntent` 及启用 Skills。
3. 检查回合事件、调度与工具执行结果。
4. 检查 `tool_feedback`、调用 ID 和 UI 结果绑定。
5. 对 Provider 失败检查错误分类、重试判断和 fallback 事件。

Browser 回合转换使用状态机契约，相关规则见[状态约定](状态管理宣言.md)。日志与实现定位使用模块和方法名。

## 验收

工具调用需要覆盖快速回复、连续工具、重复消息、取消、请求失败和会话切换；确认工具结果能够回到正确会话，并最终得到可理解的完成或失败状态。
