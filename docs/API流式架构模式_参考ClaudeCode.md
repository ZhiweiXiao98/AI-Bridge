# API 流式架构可借鉴模式（来自 Claude Code）

> 来源：用户提供的 Claude Code 源码笔记（2026-03-31）
> 目标：筛选可落地到本项目（Qt 客户端 + RemoteWorker + API Stream）的工程模式

---

## 1. 采用原则

- **先契约后实现**：先定义事件协议、状态机、渲染契约，再改代码。
- **可观测优先**：每个关键机制都要有指标与日志，不做“黑盒优化”。
- **渐进迁移**：兼容旧路径，灰度切换，保留回滚开关。
- **Fail-Closed**：权限、安全、并发默认保守，显式放开。

---

## 2. 可直接复用（优先级 P0）

### 2.1 多层状态机 + 单向数据流

借鉴点：
- 流式工具执行状态机（queued/executing/completed）
- 上下文/记忆提取中的门控与互斥

落地到本项目：
- 定义 `PendingUser -> StreamingAI -> CommittedAI` 三态流
- 事件只进 Store，UI 不直接拼状态
- Store 输出投影（Projector），Renderer 只消费 patch

验收：
- 状态迁移单测覆盖 >= 90%
- 不再出现“页面层多处拼装同一状态”

---

### 2.2 并发控制与可中断执行

借鉴点：
- `canExecuteTool()` 并发安全判定
- 兄弟任务 abort 级联（仅特定错误触发）

落地到本项目：
- 对流式事件处理建立串行队列（同 stream_id）+ 会话级并发隔离
- 定义错误级联策略（仅协议破坏错误触发全链中止）
- 引入可中断控制器（会话切换、模式切换时清理）

验收：
- 切会话中途流式不串线
- 中断后无孤儿 stream

---

### 2.3 指数退避 + 抖动 + 过载分级

借鉴点：
- withRetry：指数退避 + 抖动
- 529/429 分层处理

落地到本项目：
- 对拉取消息/重连加入统一 RetryPolicy
- 前台交互与后台任务分级重试
- 增加 idle watchdog（空闲超时）

验收：
- 网络抖动下不雪崩重试
- 过载时前台响应优先

---

### 2.4 Diff/Patch 渲染思路

借鉴点：
- 双缓冲 + damage diff + patch 优化

落地到本项目：
- MessageArea 从全量渲染转为 patch（append/update/remove）
- 流式路径只更新“最后一个 stream bubble”
- 维持滚动策略独立（tail policy）

验收：
- `delta_to_paint_ms_p95` 明显下降
- 高频 chunk 下可见连续更新

---

## 3. 裁剪后复用（优先级 P1）

### 3.1 权限级联模型（8 步）

借鉴点：
- deny > ask > allow 优先级
- 复杂命令拆分、AST + fallback

落地建议：
- 先在本项目工具执行前增加轻量规则层（路径、命令、模式）
- 不一次性引入完整 Tree-sitter，可先做规则框架 + 日志 shadow 模式

---

### 3.2 Auto-Mode 分类器（两阶段）

借鉴点：
- 快速判定 + 深度判定升级
- 200ms 竞赛机制

落地建议：
- 仅用于“是否自动批准低风险操作”场景
- 先保守启用（只建议，不自动执行）

---

### 3.3 记忆提取/召回

借鉴点：
- 抽取与召回分离，节流与互斥完整

落地建议：
- 本项目先实现“会话摘要 + 规则召回”
- LLM 选择器后置，先做 deterministic baseline

---

## 4. 暂不建议引入（优先级 P2）

- 终端引擎级双缓冲 Int32 打包细节（当前 Qt 组件体系不匹配）
- 全量 Swarm（in-process + pane 双后端）
- 纯 TS 原生模块移植（与当前 Python/Qt 技术栈错位）

可保留思想，不直接移植实现。

---

## 5. 对本项目的映射清单

- 状态层：`app/ui/pages/chat/services/api_chat_state_store.py`
- 编排层：`app/ui/pages/chat/page.py`
- 事件桥：`app/ui/pages/chat/chat_page_stream.py`
- 渲染层：`app/ui/pages/chat/message_area.py`
- 后端流：`app/core/api/api_stream_handler.py`
- worker桥：`app/core/worker_modules/worker_api_stream.py`
- 远端分发：`app/core/remote_worker.py`

---

## 6. 建议的实施顺序

### Phase A（契约化）
1. 定义统一事件协议（conversation_id/round_id/stream_id/seq/kind）
2. 定义状态机与非法转移处理
3. 增加指标与日志规范

### Phase B（渲染升级）
1. 新增 Projector + RenderPatch
2. 流式路径切到 patch（灰度开关）
3. 验证 tail policy 与可见性

### Phase C（可靠性）
1. RetryPolicy 统一化
2. watchdog 与中断机制完善
3. 故障注入测试（乱序/丢包/重连）

---

## 7. 验证矩阵（最小必测）

1. 新建会话流式：首帧出现、逐步增长、完成收敛
2. 长会话窗口裁剪：流式项始终可见
3. 模式切换中断：无串线、无幽灵气泡
4. 高频 chunk：无明显卡顿、无重复渲染抖动
5. 重连恢复：状态可重建、最终一致

---

## 8. 与主 RFC 的关系

本文件是《API流式状态架构RFC.md》的“参考模式附录”，用于指导实现选型，不直接替代主 RFC 的约束与验收标准。

建议在每次架构评审中将本文件作为“模式候选库”更新维护。
