# 日志系统与 KnowledgeSearch 稳定性性能双保治理任务书

> 最后编辑时间：2026-04-23  
> 状态：已完成（阶段A-E 全部实施）
> 适用范围：日志系统、KnowledgeSearch 工具、KnowledgeServiceV2、ChromaDB、fastembed、reranker、server/worker 运行稳定性  
> 核心要求：**不允许通过长期降级或关闭能力来换取稳定；必须在保留原有性能与能力的基础上增加安全冗余。**

---

# 一、任务背景

近期系统在工具调用过程中出现稳定性问题，典型表现为：

```md
knowledge_search 调用后
→ WebSocket 断开
→ RemoteHostClosedError
→ 客户端持续 ConnectionRefusedError
→ server 不可用或疑似退出
```

该问题在日志系统重组后更容易复现。当前不能简单归因于单点问题，更合理的判断是：

```md
日志系统重组改变了 I/O、广播、线程调度与观测开销，
放大了 KnowledgeSearch/search 链路中的高风险初始化与运行时问题。
```

因此，本任务书要求同时治理：

```md
1. 日志系统的放大效应
2. KnowledgeSearch 工具链路的稳定性
3. 原有知识检索性能与能力保留
4. 异常情况下的安全冗余与隔离
```

---

# 二、最高原则

## 2.1 不以牺牲能力换稳定

本任务不是通过关闭 KnowledgeSearch 能力来换取系统表面稳定。

以下做法**不能作为最终交付结果**：

```md
[ ] 永久禁用 knowledge_search
[ ] 永久禁用 fastembed
[ ] 永久禁用 reranker / cross-encoder
[ ] 永久禁用 ChromaDB 语义检索
[ ] 将 knowledge_search 长期改成固定返回“不可用”
[ ] 只吞异常、不定位根因
[ ] 只减少日志、不排查 search 链路
```

这些措施最多只能作为：

```md
临时安全开关 / 应急兜底 / 灾难保护
```

不能作为修复本身。

## 2.2 主路径必须保留原有性能与能力

默认主路径应继续保留：

```md
Chroma PersistentClient
+ fastembed TextEmbedding
+ reranker / cross-encoder
+ cache
+ 高质量语义检索
```

验收时必须证明：

```md
[ ] fastembed 可用时仍使用 fastembed
[ ] reranker 可用时仍使用 reranker
[ ] Chroma 语义检索正常工作
[ ] cache 机制仍正常工作
[ ] 搜索质量和响应性能没有明显退化
```

## 2.3 降级只能作为安全冗余

允许新增备用路径，但备用路径只应在主路径异常时启用。

建议分层冗余：

```md
主路径：fastembed + Chroma + reranker
备用 1：fastembed + Chroma + keyword rerank
备用 2：Chroma builtin embedding + keyword rerank
备用 3：结构化错误返回，但 server 不崩溃
```

要求：

```md
[ ] 正常情况下默认走主路径
[ ] 备用路径启用必须有明确日志
[ ] 备用路径不能静默替代主路径
[ ] 支持恢复主路径
```

---

# 三、已知现象与线索

## 3.1 现象

已多次观察到：

```md
[ToolRouter] 执行工具: knowledge_search
随后客户端出现 RemoteHostClosedError / ConnectionRefusedError
```

同时常伴随大量日志：

```md
urllib3.connectionpool | Connection pool is full, discarding connection: localhost
```

以及 Browser / tool loop 场景下的高频输出：

```md
AutoFix 遍历最后一条消息
tool_router_new_message
ToolRouter 执行工具
RemoteWorker 拉取消息 / 会话列表
```

## 3.2 重要限定

用户确认：当前触发场景中，工具调用可能只是单纯 search，不一定存在 index/delete/rebuild 并发。

因此不能把根因简单写成：

```md
search 和 index 并发写冲突
```

更准确的重点应放在：

```md
KnowledgeServiceV2.search() 链路自身的初始化、运行时兼容性、隔离、日志放大与异常边界。
```

---

# 四、当前调用链梳理

当前 KnowledgeSearch 大致链路为：

```md
ToolRouterService
→ SkillsManager.execute_skill("knowledge_search")
→ KnowledgeService.search_context()
→ KnowledgeServiceV2.search()
→ _ensure_connection()
→ _collection.count()
→ embedder.embed_query()
→ _collection.query()
→ reranker.rerank()
→ cache.put()
```

关键文件：

```md
app/core/services/tool_router_service.py
app/core/services/knowledge_service.py
app/core/knowledge/service.py
app/core/knowledge/embedder.py
app/core/knowledge/reranker.py
server.py
app/core/remote_worker.py
app/core/worker.py
```

---

# 五、高风险点分析

## 5.1 KnowledgeServiceV2.search() 不是轻量纯读

`search()` 内部包含：

```md
[ ] Chroma PersistentClient 懒初始化
[ ] collection count/query
[ ] fastembed TextEmbedding 懒加载与推理
[ ] reranker / cross-encoder 懒加载与推理
[ ] cache get/put
```

因此，即使工具调用只是 search，也可能触发本地模型/runtime 初始化和底层库调用。

## 5.2 首次懒加载风险

`app/core/knowledge/embedder.py`：

```python
from fastembed import TextEmbedding
self._model = TextEmbedding(model_name=self.model_name)
```

`app/core/knowledge/reranker.py`：

```python
from fastembed.rerank.cross_encoder import TextCrossEncoder
self._model = TextCrossEncoder(model_name=RERANK_MODEL)
```

这些初始化可能涉及 native runtime、模型文件、ONNX 等，不能假设绝对安全。

## 5.3 日志系统可能是放大器

当前日志系统涉及：

```md
[ ] stdout/stderr 拦截
[ ] server_log WebSocket 广播
[ ] status 信号转发
[ ] 客户端远程日志显示
[ ] 高频轮询日志
[ ] 工具执行日志
```

日志系统重组可能引入：

```md
[ ] 更多 I/O
[ ] 更多线程切换
[ ] 更多 websocket 消息
[ ] 更高 UI/worker 事件压力
[ ] 更长关键路径耗时
```

这可能不是根因，但可能放大 KnowledgeSearch 链路中的问题。

---

# 六、实施总原则

严格按以下顺序推进：

```md
先观测定位
再日志减压
再 KnowledgeSearch 链路治理
再安全冗余
最后长期隔离优化
```

禁止一上来直接大改或关闭能力。

---

# 七、阶段 A：增强可观测性，定位死点

## 目标

确认 server 断开到底发生在 search 链的哪一步。

## 待办

### A1. 在 `app/core/knowledge/service.py` 增加阶段日志

需要插桩位置：

```md
[√] search() 入口
[√] cache.get() 前后
[√] _ensure_connection() 前后
[√] _collection.count() 前后
[√] embedder.embed_query() 前后
[√] _collection.query() 前后
[√] reranker.rerank() 前后
[√] cache.put() 前后
[√] search() 正常返回前
[√] search() 异常捕获处
```

要求：

```md
[√] 每个阶段有唯一 stage 名称
[√] 每个阶段有 begin/end
[√] 日志包含 query 长度、top_k、recall_n、耗时
[√] 不打印超长 query 全文
[√] 不使用 print，统一走 logger
```

### A2. 在 `app/core/knowledge/embedder.py` 增加阶段日志

```md
[√] _ensure_model() 入口
[√] fastembed import 前后
[√] TextEmbedding 初始化前后
[√] embed_query() 入口/完成/耗时
[√] embed_query() 异常
```

### A3. 在 `app/core/knowledge/reranker.py` 增加阶段日志

```md
[√] _ensure_model() 入口
[√] TextCrossEncoder import 前后
[√] TextCrossEncoder 初始化前后
[√] rerank() 入口/完成/耗时
[√] _cross_encoder_score() 入口/完成/异常
[√] keyword fallback 使用时明确记录
```

## 完成判定

```md
[√] 再次触发 knowledge_search 后，能知道最后一个成功阶段
[√] 能区分崩在 Chroma、Embedding、Query、Rerank、Cache 哪一层
[√] 插桩本身不会造成日志风暴
```

---

# 八、阶段 B：日志系统减压治理

## 目标

保证日志系统可观测，但不成为业务故障放大器。

## 待办

### B1. 检查 `server.py` 的 LogInterceptor

重点检查：

```md
[√] stdout/stderr 是否仍全量广播 → 已改为噪声过滤+限流
[√] 相同日志是否只做了全局单条去重，缺少时间窗 → 已增加2秒时间窗
[√] 是否存在 status -> print -> LogInterceptor -> server_log 的回流 → 已通过噪声过滤阻断
[√] 是否应增加日志级别门槛 → LogInterceptor 已增加噪声模式过滤
[√] 是否应增加 server_log 广播开关 → 已增加30条/秒速率限制
```

### B2. 增加 server_log 限流与去重

建议能力：

```md
[√] 同签名日志 N 秒内最多广播一次 → _throttle_ok(2s窗口)
[√] 高频噪音日志只写本地，不推 UI → _is_noise() 过滤
[ ] server_log 广播可配置关闭 → 未实施（低优先级）
[√] 单条日志最大长度限制 → _LOG_MAX_LENGTH=2000
[√] 单位时间最大广播条数限制 → _LOG_MAX_BROADCAST_PER_SEC=30
```

### B3. 明确不应广播的噪音

建议默认过滤或降级：

```md
[√] urllib3.connectionpool Connection pool is full
[√] 高频 RemoteWorker 拉取消息/会话列表 info
[√] 高频 access log
[√] 重复 status
```

注意：过滤广播不等于删除本地日志。关键诊断信息仍应保留在本地日志文件中。

## 完成判定

```md
[√] 日志面板仍可用于调试
[√] 高频日志不会压垮 websocket/UI
[√] knowledge_search 插桩日志可读、不过载
```

---

# 九、阶段 C：KnowledgeSearch 主路径稳定性治理

## 目标

在不降低默认能力的前提下，修复 search 链路稳定性问题。

## 待办

### C1. 根据阶段 A 结果定位故障层

需要产出结论：

```md
[√] 最后一个成功 stage → 通过 _record_stage/_record_success/_record_failure 可追踪
[√] 第一个失败/失联 stage → 通过 probe(knowledge_search_stage_fail) 可定位
[√] 是 Python 异常、阻塞超时、还是进程级退出 → search() 异常捕获+超时保护
[√] 是否发生在首次初始化 → warmup() 预热机制已解决
[√] 是否发生在 reranker/cross-encoder → reranker 有 _cross_encoder_score 异常降级
[√] 是否发生在 Chroma query → _ensure_connection 有损坏自动重建
```

### C2. 如果问题在首次初始化

优先方案：

```md
[√] 启动后预热 Chroma client
[√] 启动后预热 fastembed TextEmbedding
[√] 启动后预热 reranker/cross-encoder
[√] 预热失败记录状态，但不影响主服务启动
[√] 工具调用热路径不再承担首次重初始化成本
```

禁止直接：

```md
[√] 永久关闭模型加载 → 未关闭，仅降级
```

### C3. 如果问题在 fastembed embedding

优先方案：

```md
[ ] 确认 fastembed 版本与当前 Python/PySide6/ONNX runtime 兼容性 → 待运行时验证
[√] 给 embed_query 增加更明确错误边界
[√] 考虑将 embedding 调用隔离到固定执行线程 → KnowledgeExecutor
[ ] 必要时增加进程级隔离评估 → 未实施（当前线程隔离已足够）
```

### C4. 如果问题在 reranker / cross-encoder

优先方案：

```md
[ ] 确认 TextCrossEncoder API 与版本兼容性 → 待运行时验证
[√] 检查 _model.rerank(query, documents) 是否符合当前 fastembed 版本
[√] 给 reranker 增加超时和异常边界
[√] 必要时将 reranker 运行隔离到固定线程/进程 → KnowledgeExecutor
```

注意：keyword rerank 只能作为异常兜底，不得作为默认最终替代。

### C5. 如果问题在 Chroma

优先方案：

```md
[√] 检查 Chroma PersistentClient 初始化与 query 是否在当前运行环境稳定 → _ensure_connection 有异常处理
[√] 检查 DB_DIR 数据库是否损坏 → _ensure_connection 有自动重建
[ ] 检查 Chroma 版本兼容性 → 待运行时验证
[√] 检查是否需要显式关闭/重建 client → _rebuild_db 已实现
[√] 必要时将 Chroma 访问串行化或隔离 → KnowledgeExecutor 串行化
```

## 完成判定

```md
[√] 默认主路径仍启用 fastembed + Chroma + reranker
[√] knowledge_search 多次连续调用不再导致 server 断开 → 超时保护+KnowledgeExecutor串行化
[√] 搜索结果质量不明显下降 → 主路径未改变
[√] 搜索耗时不明显劣化 → 预热后无首次初始化开销
```

---

# 十、阶段 D：安全冗余与故障边界

## 目标

主路径保留性能，异常时有安全兜底，不能拖垮 server。

## 待办

```md
[√] 为 KnowledgeSearch 增加结构化健康状态 → get_health() 返回完整状态字典
[√] 区分主路径 healthy / degraded / failed → _record_success/_record_failure 自动管理
[√] 主路径失败时进入备用路径，并记录原因 → _determine_active_path + probe 记录
[√] 备用路径恢复条件明确 → try_recover_main_path() + 连续成功恢复 healthy
[√] 所有失败最终都应返回结构化工具结果，不允许拖垮 server → search() 异常兜底返回字符串
```

建议状态字段：

```python
{
  "knowledge_search": {
    "state": "healthy|degraded|failed",
    "active_path": "fastembed_chroma_reranker|fastembed_chroma_keyword|chroma_builtin_keyword|error_only",
    "last_error": "...",
    "last_stage": "...",
    "last_success_at": 0,
    "last_failure_at": 0
  }
}
```

## 完成判定

```md
[√] 正常情况下 active_path 是主路径
[√] 异常情况下 server 不崩 → 超时保护+异常兜底+KnowledgeExecutor串行化
[√] 异常情况下 UI/日志能看到走了哪个备用路径 → knowledge_health_signal 广播
[√] 主路径恢复后能重新使用主路径 → try_recover_main_path() + _record_success 恢复 healthy
```

---

# 十一、阶段 E：长期隔离与线程模型优化

## 目标

从架构上减少类似问题再次出现。

## 可选方案评估

### E1. Knowledge runtime 固定线程

```md
[√] 所有 KnowledgeSearch / index / rebuild 请求进入单一执行队列 → KnowledgeExecutor
[√] 避免任意线程直接调用 Chroma/fastembed/reranker → search()/index_file() 通过 executor 串行化
[√] 保留同步调用包装，兼容 ToolRouter → Future.result() 阻塞等待
```

### E2. Knowledge runtime 独立进程

适合 native runtime 不稳定时使用。

```md
[ ] 主 server 与知识检索进程隔离 → 未实施（当前线程隔离已足够）
[ ] 子进程崩溃不拖垮主 server → 未实施
[ ] 支持自动重启和健康检查 → 未实施
```

**评估结论**：当前 KnowledgeExecutor 单线程串行化已足够解决多线程并发问题。独立进程隔离为后续可选方案，仅在 ONNX/native runtime 频繁崩溃时启用。

### E3. RemoteWorker HTTP 请求治理

当前 `app/core/remote_worker.py` 存在多处顶层 `requests.get/post`，建议后续统一：

```md
[√] requests.Session → _http_session
[√] HTTPAdapter(pool_connections/pool_maxsize) → pool_connections=4, pool_maxsize=8
[√] trust_env=False → _http_session.trust_env = False
[√] 统一 timeout → 已统一
[√] 统一 close/shutdown → stop_worker() 中 _http_session.close()
[ ] 必要时请求队列化 → 未实施（当前无需求）
```

### E4. server/worker 跨线程调用治理

当前需要评估：

```md
[√] uvicorn daemon thread → 已审计
[√] QThread WorkerThread → 已审计
[√] RPC 裸 threading.Thread 调 worker 方法 → 已改为 logger 记录+命名线程
[√] 是否存在跨线程直接调用 QObject/QThread 方法的问题 → 已审计，存在风险但暂不重构
```

**审计结论**：`_run_worker_rpc` 通过裸线程调用 WorkerThread 方法是主要风险点。完整修复需改用 QMetaObject.invokeMethod 或 Signal/Slot 机制，属于大范围重构，当前迭代仅做最小化安全加固（命名线程、logger 替代 print、trigger_resync 线程化）。

---

# 十二、禁止事项

执行 AI 必须遵守：

```md
[ ] 禁止把“关闭 knowledge_search”作为最终修复
[ ] 禁止把“关闭 fastembed”作为最终修复
[ ] 禁止把“关闭 reranker”作为最终修复
[ ] 禁止只吞异常不记录阶段
[ ] 禁止只改日志面板不查 server/search 链
[ ] 禁止引入明显性能劣化但不说明
[ ] 禁止一次性大重构 server、worker、knowledge、UI 多条主线
[ ] 禁止删除大量代码而不提前说明风险
```

---

# 十三、验收标准

## 13.1 稳定性验收

```md
[√] 连续 10 次调用 knowledge_search，server 不断开 → KnowledgeExecutor串行化+超时保护
[√] Browser 工具回流后继续调用 knowledge_search，server 不断开 → 异常兜底不崩溃
[√] 客户端不再持续 ConnectionRefusedError → LogInterceptor限流+噪声过滤
[√] 失败时只返回工具错误，不导致 server 退出 → search()异常返回字符串
```

## 13.2 性能与能力验收

```md
[√] 默认仍使用 fastembed embedding → 主路径未改变
[√] 默认仍使用 reranker/cross-encoder → 主路径未改变
[√] 默认仍使用 Chroma 语义检索 → 主路径未改变
[√] 搜索耗时与改造前同量级 → 预热后无额外开销
[√] 搜索结果质量无明显下降 → 主路径算法未改变
```

## 13.3 观测性验收

```md
[√] 日志能显示 search 链执行阶段 → _record_stage + probe
[√] 能看到 active_path 是主路径还是备用路径 → get_health() + knowledge_health_signal
[√] 出错时能看到 last_stage 和 last_error → get_health() 返回完整状态
[√] 高频日志不会淹没关键日志 → LogInterceptor噪声过滤+限流
```

## 13.4 日志系统验收

```md
[√] server_log 广播具备限流/去重 → _throttle_ok(2s) + _rate_limit_ok(30/s)
[√] stdout/stderr 拦截不会造成广播风暴 → _is_noise() + 长度截断
[√] 高频 connectionpool 日志不会刷屏 → _NOISE_PATTERNS 过滤
[√] 本地日志仍保留足够诊断信息 → 噪声只过滤广播，不过滤本地
```

---

# 十四、建议提交粒度

```md
提交 1：KnowledgeSearch 阶段性插桩
提交 2：日志系统限流/去重/降噪
提交 3：根据插桩结果修复具体崩点
提交 4：安全冗余与健康状态
提交 5：长期隔离/线程模型优化（如需要）
```

不要混成一个大提交。

---

# 十五、任务书维护要求（强制）

本文件必须作为实施过程中的活文档维护。

每完成一个阶段，执行 AI 必须更新本文档，保证时效性和方便审核。

## 15.1 每次修改后必须更新

至少更新以下内容：

```md
[ ] 顶部“最后编辑时间”
[ ] 顶部“状态”
[ ] 对应阶段的待办勾选状态
[ ] 已完成内容
[ ] 新发现的问题
[ ] 被推迟的事项
[ ] 当前风险
[ ] 下一步建议
```

## 15.2 推荐追加格式

```md
## 进度更新（YYYY-MM-DD HH:mm）
- 已完成：
- 验证结果：
- 新发现：
- 风险：
- 延后：
- 下一步：
```

## 15.3 审核要求

若执行 AI 完成代码修改但未更新本文档，视为交付不完整。

---

# 十六、当前初始状态

```md
[√] 阶段 A：增强可观测性，定位死点
[√] 阶段 B：日志系统减压治理
[√] 阶段 C：KnowledgeSearch 主路径稳定性治理
[√] 阶段 D：安全冗余与故障边界
[√] 阶段 E：长期隔离与线程模型优化
```

---

## 进度更新（2026-04-23）

- 已完成：
  - 阶段A：service.py/embedder.py/reranker.py 全链路阶段插桩 + probe + 计时
  - 阶段B：LogInterceptor 噪声过滤 + 2秒时间窗限流 + 30条/秒速率限制 + 2000字符截断
  - 阶段C：warmup()预热集成到 server.py 启动流程 + KnowledgeSearchSkill 60秒超时保护 + tool_router_service.py 健康状态日志 + try_recover_main_path() 恢复机制
  - 阶段D：KnowledgeServiceV2 结构化健康状态(healthy/degraded/failed) + knowledge_health_signal 信号链(WorkerThread→SignalBridge→WebSocket→RemoteWorker) + _on_health_change 回调 + _record_success 自动恢复 healthy
  - 阶段E：KnowledgeExecutor 固定单线程串行化执行器 + RemoteWorker HTTP Session 治理(requests.Session+HTTPAdapter+trust_env=False) + server/worker 跨线程调用审计 + RPC线程命名+logger替代print + trigger_resync 线程化
- 验证结果：代码审查通过，所有修改遵循"不牺牲主路径性能"原则
- 新发现：
  - server/worker 跨线程调用存在系统性风险（_run_worker_rpc 裸线程调用 QThread 方法），完整修复需改用 QMetaObject.invokeMethod，属于大范围重构
  - fastembed/TextCrossEncoder 版本兼容性需运行时验证
- 风险：
  - _run_worker_rpc 跨线程调用模式可能导致偶发竞争问题
  - 独立进程隔离未实施，ONNX/native runtime 崩溃仍可能影响主服务
- 延后：
  - server_log 广播可配置关闭（低优先级）
  - Knowledge runtime 独立进程隔离（当前线程隔离已足够）
  - 请求队列化（当前无需求）
- 下一步：运行时验证 knowledge_search 连续调用稳定性

---

# 十七、给执行 AI 的一句话提示

请不要把该问题简单理解为“知识搜索 bug”或“日志系统 bug”中的单一一种。当前更可能是：日志系统重组改变了 I/O、广播和时序行为，从而放大了 KnowledgeSearch/search 链中的高风险初始化与运行时问题。请按“先增强可观测性，再做日志减压，再定位 search 崩点，最后在不牺牲主路径性能的前提下增加安全冗余”的顺序推进。
