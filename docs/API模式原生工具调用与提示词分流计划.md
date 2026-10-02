# API 工具协议与提示词分流

> 复核日期：2026-09-26。本文描述当前协议选择、执行链路和待验收范围。

## 使用入口

在 API 设置页选择 Profile，保存模型与连接参数，运行“探测原生工具支持”。探测结果通过 RPC 返回设置页，并记录在 Profile 的 `tool_capability` 中。发送请求时，API Source 根据有效会话配置选择工具协议。

## 协议选择

协议由 `APIModeConfigManager.resolve_tool_protocol()` 解析：

| 条件 | 返回协议 |
| --- | --- |
| `kind=browser_stateless` | `markdown_fallback_only` |
| 显式设置 `tool_calling_mode=markdown_fallback` | `markdown_fallback` |
| 显式选择 `native_tools`，能力状态为 `supported`、`partial` 或空值 | `native_tools` |
| 自动模式中能力为 `supported`，或 `supports_tools=true` | `native_tools` |
| 其它情况 | `markdown_fallback` |

能力状态包括 `unknown`、`supported`、`unsupported`、`partial`。原生工具选择与 Provider 的实际实现共同决定请求行为；`browser_stateless` 使用网页文本通道并跳过 HTTP tools 探测。

## 请求与执行

1. PromptAssembler 按 `tool_protocol` 组装系统策略，SkillsManager 输出相应的技能说明。
2. native 模式向 Provider 传入启用 Skills 的工具定义；文本通道使用 `tool_call` 围栏说明。
3. OpenAI-compatible 的 `chat_with_tools()` 解析完整 tool calls，`stream_chat_with_tools()` 累积流式 tool call delta。
4. 调用归一化为 `ToolIntent`，交给工具运行时执行；结果用 `ToolExecutionResult` 和 `ToolRoundResult` 表达。
5. API Source 保存结构化 `tool_feedback`，后续请求携带工具调用及结果，继续生成回答。

普通 API 流式回答可展示并保存 thinking 段。native tools 的多轮 reasoning 回放仍需补齐。

## 失败与 fallback

非流式 native 请求异常可将能力降为 `partial`，然后进入普通请求通道。流式 native 在尚未输出内容时可回落普通流式通道；已输出内容的路径需要避免重复播放。

Provider 错误分类由 `provider_errors.py` 提供，fallback 事件包含分类、可重试性和用户提示。不同 Provider 的具体错误映射、协议降级提示及统一能力展示仍需验收和完善。

## 代码位置

| 位置 | 职责 |
| --- | --- |
| `app/core/api_mode_config.py` | Profile 字段、工具能力和协议选择 |
| `app/core/prompt_runtime/prompt_assembler.py` | Prompt 分流 |
| `app/core/skills/manager.py` | Skills 描述与工具定义 |
| `app/core/llm_provider.py` | 请求、能力探测和流式 tool calls |
| `app/core/api_source.py` | 工具执行、反馈持久化和后续请求 |
| `app/core/model_capabilities.py` | 模型 reasoning 能力归一化 |
| `app/core/provider_errors.py` | 错误分类与重试判断 |

## 待验收与后续工作

- [ ] Gemini native tools 接入与回归。
- [ ] native tools + thinking 多轮 reasoning 回放。
- [ ] 真实 Provider 验证调用、执行、回灌、续答和最终完成状态。
- [ ] 验证断网、超时、限流、不支持 tools、输出后失败与取消时的表现。
- [ ] 对齐 API、Browser 和 browser_stateless 的协议选择、提示词与 UI 提示。

自动化覆盖位置：`tests/test_api_tool_protocol_config.py`、`tests/test_api_prompt_tool_protocol.py`、`tests/test_api_native_tools.py`、`tests/test_api_tool_capability_probe.py`、`tests/test_api_tool_feedback_projection.py`。结果记录见 [AI_JOURNAL.md](../AI_JOURNAL.md)。
