
# API 聊天状态架构落地方案（产品级）

> 目标：将当前“补丁式渲染”升级为可维护、可扩展、可验证的产品级状态架构。  
> 适用范围：API 模式聊天、流式输出、工具回流、自动续答、多会话切换。

---

## 1. 背景与问题定义

当前主要问题：
1. 用户消息与流式消息存在顺序竞争（错位/前插）
2. 流式临时气泡在 completed/error/cancelled 后清理不稳定
3. 本地 pending 与服务端 committed 重复显示
4. 工具回流（tool_feedback）与续答流式在复杂场景下顺序不可控
5. 切会话/切模式容易残留临时状态

根因：
- UI 直接消费多路信号并立即改列表，缺乏统一状态中枢
- 缺乏严格 ID 协议（只靠文本匹配）
- 缺乏明确状态机与收口逻辑（finalize 不统一）

---

## 2. 设计目标（验收标准）

必须满足：
1. UI 不出现重复消息、错位消息
2. 流式在 `completed/error/cancelled` 后进入可预期终态（完成覆盖或错误保留）
3. 工具回流 + 自动续答顺序稳定
4. 会话/模式切换后不残留临时状态
5. 去重与替换只基于 ID，不基于文本内容

---

## 3. 总体架构

采用三层模型：

1. **CommittedStore（真源）**
   - 仅存放服务端已确认/已持久化消息
   - 数据来源：`messages_signal` / 历史拉取

2. **EphemeralStore（临时层）**
   - `pending_user`（本地回显）
   - `streaming_assistant`（流式中间态）
   - `tool_running`（可选中间态）

3. **ViewProjector（投影器）**
   - 输入：Committed + Ephemeral + 当前会话上下文
   - 输出：最终可渲染消息列表
   - UI 只渲染投影结果，不直接拼接原始事件

---

## 4. ID 协议（强制）

每轮消息要求：

- `client_msg_id`：前端发送动作唯一 ID（请求级）
- `round_id`：一轮对话唯一 ID（聚合 user/tool/assistant）
- `stream_id`：一次流式实例 ID
- `message_id`：服务端持久化消息 ID（可后续增强）

约束：
- pending_user 以 `client_msg_id` 索引
- streaming 以 `(round_id, stream_id)` 索引
- committed 消息必须透传 `meta.round_id` 与 `meta.client_msg_id`

---

## 5. 事件模型与状态机

### 5.1 事件

- `USER_PENDING_CREATED(client_msg_id, round_id, text)`
- `STREAM_STARTED(stream_id, round_id)`
- `STREAM_CHUNK(stream_id, delta)`
- `STREAM_FINISHED(stream_id, status)`  
  - status ∈ `completed | error | cancelled`
- `COMMITTED_MESSAGES_REPLACED(messages)`

### 5.2 流式状态机

`IDLE -> STARTED -> STREAMING -> FINALIZING -> CLOSED`

要求：
- 任意退出路径都必须进入 `FINALIZING`
- 清理逻辑在 `finally` 保证执行
- `CLOSED` 后才允许物理移除对应临时流式块
- 新 stream 开始前，旧 stream 必须终态化（或隔离为不同 round）

---

## 6. 渲染规则（按 round 投影）

每个 round 内顺序：

1. User（pending 或 committed）
2. Assistant Streaming（0..n 段）
3. Tool Feedback（committed）
4. Assistant Final（committed，可多段续答）

说明：
- 不再使用“插入某个 widget 位置”的临时规则
- 统一由 projector 决定最终顺序
- 工具回流后续答同 round 追加 segment，避免错位

---

## 7. 数据结构建议

```python
class ApiChatStateStore:
    committed_messages: list[dict]
    pending_users: dict[str, dict]      # key=client_msg_id
    streams: dict[str, dict]            # key=stream_id, value={round_id, status, accumulated...}

    def apply_committed(self, messages: list[dict]) -> None: ...
    def add_pending_user(self, client_msg_id: str, round_id: str, text: str) -> None: ...
    def start_stream(self, stream_id: str, round_id: str) -> None: ...
    def append_stream_chunk(self, stream_id: str, delta: str) -> None: ...
    def finish_stream(self, stream_id: str, status: str) -> None: ...
    def reconcile(self) -> None: ...
    def project_view(self) -> list[dict]: ...
```

`reconcile()` 核心：
- 若 committed 已存在同 `client_msg_id` 的 user => 删除 pending_user
- 若 committed 已出现同 `round_id` assistant final => 关闭/移除对应 streaming
- error/cancelled stream 可保留错误态卡片，待用户重试/确认后清理

---

## 8. 后端改造清单

### 8.1 APISource
- `send_message_sync/send_message_stream` 写入 meta：
  - `meta.client_msg_id`
  - `meta.round_id`
- `build_message_for_signal` 透传顶层字段：
  - `client_msg_id`, `round_id`, `kind`, `meta`, `raw_content`

### 8.2 Worker / StreamHandler
- `api_send` 统一生成并透传 `client_msg_id + round_id`
- `WorkerStreamBridge.start_stream` 透传到 `APIStreamHandler`
- `APIStreamHandler` 再透传到 `api_source.send_message_stream`
- 保证 stream 状态结束事件稳定发出

---

## 9. 前端改造清单

### 9.1 ChatPage
- 新增 `ApiChatStateStore` 实例
- `_on_mode_messages`：
  - 仅调用 `apply_committed -> reconcile -> project -> render`
- `_on_api_stream_chunk/_status`：
  - 仅更新 store 的 stream 状态
  - 不直接改 committed 列表

### 9.2 MessageArea / StreamManager
- 渲染输入统一为 projector 输出
- 流式完成统一走 finalize
- 禁止多处散落的“直接 delete active bubble”逻辑

---

## 10. 迁移计划（3天）

### Day 1：协议与后端元数据
- round_id/client_msg_id 全链路透传
- APISource 入库与输出统一

### Day 2：前端状态层
- 引入 ApiChatStateStore + projector
- ChatPage 改为“状态驱动渲染”

### Day 3：复杂场景收敛
- 工具回流、自动续答、错误态、取消态
- 切会话/切模式清理
- 集成测试与回归

---

## 11. 测试用例（上线门槛）

1. 单轮流式：无重复，终态正确
2. 连续两轮：顺序稳定
3. 工具回流 + 自动续答：结构正确
4. 流式 error/cancel：终态可解释
5. 切会话中流式：无残留
6. 切模式中流式：无串屏
7. 删除消息后再发：ID 不冲突
8. 重启后加载历史：无 pending 幽灵
9. 长对话 compact 后继续：round 连续
10. Browser/API 来回切换：互不污染

---

## 12. 约束与红线

- 禁止文本匹配去重（仅可临时兜底，不可主逻辑）
- 禁止多入口直接改 UI 列表（必须经过 store+projector）
- 禁止在不同模块维护“各自的一份真实状态”

---

## 13. 交付物定义

阶段性完成标志：
- [ ] 后端消息全部带 round_id/client_msg_id
- [ ] 前端已启用 ApiChatStateStore
- [ ] `_on_mode_messages` 与 stream 事件已接入统一 reconcile/project
- [ ] 10 条用例全部通过
- [ ] 删除旧补丁逻辑（文本去重、位置猜测插入）

---

## 14. 备注

本方案面向“实际用户产品”而非 demo/mod。  
强调一致性、可维护性、可测试性，优先级高于“短期能跑”。
```

