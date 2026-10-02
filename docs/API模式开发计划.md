# API 模式开发计划（阶段版）

> 历史阶段记录（2026-09-05 整理）：以下原文用于追溯当时的设计、实现与验证；当前能力见[项目状态](当前项目状态.md)，当前测试命令见[测试说明](../tests/README.md)。

> 版本: V1.0
> 日期: 2026-03-20
> 状态: 持续推进中 / Phase A 已完成核心闭环，Phase B 待继续深化
> 定位: Browser 为当前主生产模式；API 为副模式 / 孵化模式 / 商业化预备模式

---

## 1. 背景与目标

经过近阶段接入与验证，API 模式已经具备基础多对话能力，但整体仍停留在“能跑”的层面，距离“好用、可控、可扩展”的产品状态还有明显距离。

当前阶段项目策略如下：
- Browser 模式：主生产模式（Primary Production Mode）
- API 模式：副模式 / 孵化模式 / 商业化预备模式（Secondary Incubation Mode）

因此，API 模式近期目标不是追求与 Browser 完全对称，也不是推动“API 主导式架构统一”，而是：

1. 建立可持续迭代的 API 配置中心
2. 把上下文系统从“引擎原型”推进为“可管理的产品能力”
3. 接入并验证工具调用、代码审查等无状态能力
4. 在不影响 Browser 主链稳定性的前提下，逐步提升 API 模式可用性与体验

---

## 2. 当前现状盘点

### 2.1 已有能力

当前 API 模式已经具备以下基础：
- `APISource`：负责 API 模式消息收发、对话管理、配置加载
- `ConversationStore`：负责多对话持久化、切换、删除、重命名、置顶
- `ContextManager`：具备 system / long_term / working / short_term 四层骨架，以及 token 预算统计能力
- `ContextVisualPanel`：可展示各层 token 占比与总体利用率
- API 对话列表：支持新建、删除、原位重命名、置顶、排序
- API 基础消息收发：支持同步发送与流式发送
- API 多对话排序：已按 `last_message_at` 稳定排序，切换不会再导致列表乱跳

### 2.2 当前关键缺口

当前 API 模式仍存在以下核心缺口：

#### A. 配置层
- 设置页中的 API 配置与实际运行配置来源不一致
- 默认值显示与真实生效值不一定一致
- 缺少独立的 API 配置中心
- provider profile / fallback chain / 自动降级能力已完成第一版闭环，后续重点转向异常分类与体验精修
- “当前生效配置”已完成第一版明确展示，并已区分“配置主 Profile”与“当前运行 Profile”
- 缺少“深度思考”等 API 特性开关的统一归位

#### B. 上下文层
- `ContextManager` 目前更像底层引擎，而非完整产品能力
- System Layer 无法编辑最终组合提示词
- Long-term Memory 尚未形成稳定的 RAG 注入策略
- Working Memory 尚未升级为 Agent 任务状态机
- Short-term Memory 的滑动窗口缺少用户级可调参数与策略
- Output Reserve 与 Safety Margin 目前主要停留在静态配置层面

#### C. 工具能力层
- 尚未系统验证 API 模式下的工具调用闭环
- 尚未明确哪些工具属于“已可用”，哪些只是“理论可接入”
- 代码审查等无状态工具尚未建立稳定验证矩阵

#### D. 体验层
- 流式打字效果、加载态、任务框架显示仍不完整
- 工具返回消息与普通 AI 消息尚未在视觉上分层
- 缺少对工具消息的自动折叠与摘要展示能力

---

## 3. 当前阶段开发原则

### 原则 A：不伤 Browser 主链
凡是可能影响 Browser 主生产链稳定性的全局改造，当前阶段一律降级优先级。

### 原则 B：共享能力，不强求共享状态机
短期内建议共享：
- ToolRouter
- DockerManager
- FileService
- Skills 能力
- 代码渲染组件

短期内不强求共享：
- 会话状态机
- 页面生命周期
- 消息视图状态
- 当前视图 ID 管理

### 原则 C：先把 API 模式做成“可控工具”，再考虑“优雅产品”
当前阶段不追求短期完全统一，而优先推进：
- 配置可控
- 上下文可控
- 工具可控
- 反馈可控

---

## 4. Phase A：API 配置中心（P0）

### 4.1 目标
建立独立、明确、可切换、可降级的 API 配置中心，解决“设置页配置 != 实际生效配置”的问题。

### 4.2 重点问题
- API 配置来源分散：主配置、独立 json、运行时更新混在一起
- 用户无法明确知道当前到底在用哪套模型与参数
- 不能快速切换 provider / model profile
- 不能配置失败自动降级链
- 缺少“深度思考”能力开关与对应参数入口

### 4.3 建议能力
- API 专属配置对象与配置文件
- 当前生效配置展示（已完成第一版，支持配置主 / 当前运行分离展示）
- 多 profile 管理（已完成第一版：切换 / 新建 / 删除 / 重命名）
- fallback / downgrade chain（已完成第一版配置与运行时自动切换）
- 失败后自动切换策略（已完成第一版；后续需补异常分类与更细边界）
- 深度思考开关与相关参数配置（已完成最小入口）
- 模型能力标签（是否流式、是否工具调用、是否深度思考）

### 4.4 本阶段不追求
- 不要求一步到位支持所有 provider 私有参数
- 不要求 Browser 与 API 共用同一套配置 UI

---

## 5. Phase B：上下文管理系统产品化（P0）

### 5.1 目标
把当前 `ContextManager` 从“内部引擎”推进为“用户可管理、Agent 可依赖、未来商业化可扩展”的上下文系统。

### 5.2 分层目标

#### System Layer
- 支持用户编辑系统提示词
- 支持 Skills Prompt 注入
- 支持 AI_README / 系统规范注入策略
- 支持查看最终组合后的 system prompt

#### Long-term Memory
- 明确 RAG 注入入口与预算策略
- 支持开关、预算、条数、优先级策略
- 支持查看当前注入的长期记忆片段摘要

#### Working Memory
- 从普通 dict 升级为任务状态容器
- 为后续 Agent 状态机提供结构基础
- 支持记录当前目标、当前步骤、当前文件、当前失败原因、当前工具结果摘要

#### Short-term Memory
- 支持滑动窗口参数可调
- 支持最大轮数、最大 token、截断策略配置
- 允许后续扩展为摘要压缩策略

#### Output Reserve / Safety Margin
- 明确进入高级配置区
- 支持按模型窗口大小联动设置默认值

### 5.3 本阶段关键产物
- 上下文配置面板 / 页
- system prompt 可视化与编辑
- working memory 可视化
- short-term 窗口配置入口
- token 预算调整入口

---

## 6. Phase C：无状态工具能力接入 / 验证（P1）

### 6.1 目标
明确 API 模式下哪些工具已经真正可用，并建立验证矩阵，避免“理论支持但实际不可用”。

### 6.2 优先验证对象
- `file_operations`
- `code_execution`
- `knowledge_search`
- `web_search`
- 代码审查相关无状态链路

### 6.3 核心问题
- 工具是否真的能在 API 模式下触发
- 工具返回是否能正确回灌给 UI / 上下文
- 错误时是否有清晰反馈
- 不同模型的工具调用能力是否需要配置层区分

### 6.4 本阶段输出
- 工具能力清单
- API 模式工具验证清单
- 已验证 / 未验证 / 不支持 三态矩阵

---

## 7. Phase D：体验增强（P2）

### 7.1 目标
在主链稳定之后，提升 API 模式的阅读体验、反馈体验与任务可见性。

### 7.2 方向
- 流式文字打字效果
- 加载动效
- 图表显示
- 任务框架显示
- 更清晰的上下文状态反馈

### 7.3 新增重点：消息类型识别与工具消息折叠
API 模式后续需要明确区分以下消息：
- 用户消息
- AI 回复消息
- 工具返回消息

其中，工具返回消息通常信息量大、结构化强、对普通阅读干扰大，因此建议：
- 自动识别工具消息
- 默认折叠工具返回详情
- 仅显示摘要（如：执行成功 / 找到 12 个结果 / 读取 3 个文件）
- 用户可手动展开查看完整原文

### 7.4 价值
该能力将显著降低 API 模式对话区噪音，提高长任务、多工具调用时的可读性。

---

## 8. 当前推荐执行顺序

### P0
1. Phase A：API 配置中心
2. Phase B：上下文管理系统产品化

### P1
3. Phase C：无状态工具能力接入 / 验证

### P2
4. Phase D：体验增强

---

## 9. 本文档当前状态说明

本文档为第一阶段骨架版，当前先明确：
- 主线方向
- 缺口分类
- Phase 划分
- 优先级排序

后续轮次再继续补充：
- 更细的执行步骤
- 每阶段验收标准
- 风险与取舍
- 与现有文件结构的映射关系


---

## 10. 建议执行步骤（按阶段拆分）

### 10.1 Phase A：API 配置中心

#### 2026-03-21 当前落地状态补充（运行时热应用最小闭环）

#### 2026-03-21 当前落地状态补充（多 Profile / Fallback Chain 配置中心）
- ✅ 已完成：API 配置中心支持多 Profile 的第一版管理（切换 / 新建 / 删除 / 重命名）
- ✅ 已完成：设置页支持以列表方式管理 `fallback_chain`，包括候选选择、添加、顺序调整、移除、空状态提示与人话说明
- ✅ 已完成：切换 active profile 时自动清理 fallback chain 中与当前 active 相同的项，避免配置自指
- ✅ 已完成：`fallback_chain` 已接入运行时自动切换逻辑；当前 active profile 调用失败后，会按顺序切换到下一 Profile 并重试
- ✅ 已完成：fallback 成功后会记录最近一次切换事件，并通过 Worker 向用户发出“已自动切换备用模型”的人话提示
- ✅ 已完成：fallback 顺序调整改为操作即自动保存，关闭后仍能记忆优先级顺序
- 🚧 待补：后续需在 `APISource` / provider 调用路径中进一步细化哪些异常属于“可降级重试”，并补充更精细的重试边界与最终失败说明

- ✅ 已完成：设置页 API 区保存后，可通过 `SettingsPage -> Worker(薄桥) -> APISource.reload_runtime_config()` 热更新 provider 运行时配置
- ✅ 已完成：以下参数可在保存后对 **下一次 API 请求** 生效：`api_key` / `base_url` / `model` / `temperature` / `max_output_tokens` / `timeout`
- ✅ 已确认：该实现不要求把 API 专属配置逻辑塞回 Browser 主链，也不要求让 Worker 成为 API 配置中心
- 🚧 待补：当前活跃对话的 `ContextManager` 配置仍未完全热应用，例如 `max_window_tokens`、system 组合提示词、以及更深层的 conversation defaults 仍主要依赖后续请求 / 后续阶段补强
- 🚧 待补：如果后续要实现“保存后当前会话上下文立刻重建并完全生效”，建议在 Phase B 中为 `ContextManager / ConversationStore` 增加明确的 runtime rebind / rehydrate 能力，而不是继续扩写 Worker 分支


#### Step A.1：统一配置来源
目标：明确 API 模式运行时到底读取哪一份配置，结束“设置页配置 / 独立 json / 运行时更新”混杂状态。

建议动作：
- 定义 API 专属配置结构
- 明确主配置与 API 配置的覆盖优先级
- 为“当前生效配置”提供只读快照接口

#### Step A.2：引入 Profile 概念
目标：让用户可以在多套 API 配置之间切换，而不是每次手动改字段。

建议动作：
- 支持多个 provider profile
- 每个 profile 至少包含：name / provider / model / base_url / temperature / max_output_tokens
- UI 上支持切换当前激活 profile

#### Step A.3：加入 fallback / downgrade chain
目标：当主模型失败、超时、额度耗尽时，能自动切换到次级模型。

建议动作：
- 为 profile 增加 fallback 列表
- 记录失败原因与当前切换到的模型
- 区分“首选模型”和“兜底模型”

#### 2026-03-21 当前补充（配置主 / 当前运行状态分离）
- ✅ 已完成：设置页“当前生效配置”已升级为双状态展示：`配置主 Profile` 与 `当前运行 Profile`
- ✅ 已完成：本地模式下可直接读取 `worker.api_source.current_runtime_profile_key`
- ✅ 已完成：远程模式下改为通过 `context_status_signal` 同步 `configured_profile_key` / `runtime_profile_key`，避免客户端错误猜测服务端当前实际运行配置
- 🚧 待补：当前运行状态摘要已解决“状态真相”问题，但视觉表达与长期信息展示仍可继续优化

#### Step A.4：加入“深度思考”配置位
目标：把深度思考从零散参数变成正式能力位。

建议动作：
- 为支持该能力的模型提供开关
- 支持相关参数配置（如 reasoning effort / 思考强度）
- 在 UI 上标明哪些模型支持深度思考

---

### 10.2 Phase B：上下文管理系统产品化

#### 2026-03-24 当前落地状态补充（上下文工作台跨对话控制 / API Conversation Control Plane）
- ✅ 已完成：`ContextWorkspacePanel` 从“当前 active API 对话查看器”升级为“API 多对话状态控制台”的第一版。
- ✅ 已完成：工作台顶部新增 API 对话选择框、刷新列表按钮、跟随当前 API 对话开关。
- ✅ 已完成：工作台所有核心操作支持显式 `conversation_id`：
  - `get_context_workspace_payload(conversation_id=None)`
  - `update_context_workspace_system_prompt(..., conversation_id=None)`
  - `update_context_workspace_working_memory(..., conversation_id=None)`
  - `clear_context_workspace_working_memory(conversation_id=None)`
  - `clear_context_workspace_long_term(conversation_id=None)`
- ✅ 已完成：`ConversationStore` 增加无副作用接口：
  - `load_conversation_snapshot()`
  - `build_context_manager_for()`
  - `save_context_manager_for()`
  正式避免通过临时 `switch()` 污染 active conversation。
- ✅ 已完成：`APISource` 增加 `get_api_conversations()`，并支持按指定 `conversation_id` 无副作用读写上下文工作台目标对话。
- ✅ 已完成：`WorkerThread` / `server.py` / `RemoteWorker` 已打通 `api_conversations_signal -> api_conversations` 远程链路。
- ✅ 已完成：`MainWindow` 已完成面板桥接与初始化请求，支持本地 / 远程统一语义。
- ✅ 已确认：当前实现允许“Browser 前台 + API 后台 + 工作台管理指定 API 对话”并存，不再要求用户先切到目标 API 对话再刷新工作台。
- 🚧 待补：后续可继续增强“跟随模式 / 锁定模式”的细节表现、最近目标记忆、以及工作台对 Browser/API 共存状态的更强可视化反馈。
- 🚧 待补：本轮尚未进入 Browser 对话的对等上下文工作台管理；当前边界仍保持在 API conversation control plane。


#### Step B.1：System Layer 可视化与可编辑
目标：让用户知道 system prompt 到底是什么，而不是只能猜。

建议动作：
- 提供用户 system prompt 编辑入口
- 提供 Skills Prompt 注入预览
- 提供最终 system prompt 合成预览

#### Step B.2：Working Memory 升级为任务状态容器
目标：让 working memory 成为 Agent 可依赖的中间状态，而不只是一个普通 dict。

建议动作：
- 约定 working memory 基础字段
- 至少包含：current_goal / current_step / current_files / recent_tool_results / failure_reason
- 提供清理与重置操作

#### Step B.3：Short-term Memory 配置化
目标：让滑动窗口可控，而不是只能依赖写死参数。

建议动作：
- 暴露 max_history_turns
- 暴露 short_term_budget
- 增加截断策略配置入口

#### Step B.4：Long-term Memory / RAG 接入策略化
目标：把长期记忆从“可注入”推进到“可管理”。

建议动作：
- 提供开关、预算、条数、注入时机配置
- 显示当前已注入的长期记忆摘要
- 为未来自动 RAG 检索留接口

#### Step B.5：高级预算配置
目标：将 output reserve 与 safety margin 纳入高级设置，而不是静态常量。

建议动作：
- 根据模型窗口大小生成默认值
- 支持高级用户手动调整
- 增加预算冲突校验

---

### 10.3 Phase C：无状态工具能力接入 / 验证

#### Step C.1：梳理工具能力矩阵
目标：明确哪些工具已经接入，哪些只是理论存在。

建议动作：
- 列出工具名称、入口、当前状态
- 区分“API 模式可用 / 浏览器模式可用 / 双模式可用”

#### Step C.2：逐个验证高价值无状态工具
目标：先打通最有价值、最稳定的一批工具。

建议顺序：
1. `file_operations`
2. `code_execution`
3. `knowledge_search`
4. `web_search`
5. 代码审查链路

#### Step C.3：补工具结果反馈协议
目标：让工具结果不只是“执行了”，而是能正确进入 UI 与上下文。

建议动作：
- 区分工具摘要与完整结果
- 为 UI 渲染提供标准字段
- 为 working memory 回灌预留结构

---

### 10.4 Phase D：体验增强

#### Step D.1：消息类型识别
目标：把 API 模式消息流明确拆成：用户 / AI / 工具 三类。

建议动作：
- 在消息结构中增加类型字段
- 渲染层按类型走不同样式

#### Step D.2：工具消息自动折叠
目标：降低多工具调用时的阅读噪音。

建议动作：
- 默认显示工具摘要
- 支持展开完整原始内容
- 支持对长工具结果做截断与分页

#### Step D.3：流式与状态反馈增强
目标：提升 API 模式主观可用性。

建议动作：
- 流式文字逐步显示
- 请求中 loading 动效
- 工具调用进行中状态
- 当前任务阶段展示

---

## 11. 阶段验收标准

### 11.1 Phase A 验收标准
- ✅ 用户可以明确看到当前 API 模式使用的实际配置，并区分“配置主 Profile”与“当前运行 Profile”
- ✅ 至少支持 2 组 profile 切换，且已完成新建 / 删除 / 重命名
- ✅ 至少支持 1 条 fallback 链，且已完成运行时自动切换第一版闭环
- ✅ 深度思考能力可以被明确开启 / 关闭
- 🚧 后续补充：对“可降级异常”的细分、fallback 更细的 UI 表达与连接测试能力

### 11.2 Phase B 验收标准
- 用户可查看并编辑 system prompt
- working memory 有明确结构与可视化入口
- short-term 窗口参数可以调整
- long-term 注入状态可查看
- context panel 不再只是“只读仪表盘”

### 11.3 Phase C 验收标准
- 至少 3 个核心无状态工具在 API 模式下稳定可用
- 工具成功/失败均有明确反馈
- 建立“已验证 / 未验证 / 不支持”矩阵

### 11.4 Phase D 验收标准
- 用户消息 / AI 消息 / 工具消息可以被正确区分
- 工具消息默认折叠，只显示摘要
- 长任务对话区的噪音明显下降

---

## 12. 风险与取舍

### 风险 1：Browser 主链回归
说明：如果 API 模式改造直接侵入共享 UI 状态或共享消息链路，可能影响当前主生产模式。
应对：优先新增 API 专属配置与 UI，不做全局强收敛。

### 风险 2：上下文系统过度理想化
说明：如果一步到位追求完整 Agent 平台，开发节奏会失控。
应对：先做可编辑、可查看、可配置，不急于一步做完完整智能状态机。

### 风险 3：工具链“理论接入，实际不可用”
说明：文档和代码上都写着支持，不代表模型、协议、UI 三端真的打通。
应对：必须建立逐项验证矩阵，不以“看起来可以”代替“已经可用”。

### 风险 4：体验优化抢占主线
说明：打字效果、动画、图表很容易消耗大量时间，但并不解决基础能力缺失。
应对：严格遵守 P0 / P1 / P2 顺序，体验优化后置。

---

## 13. 与现有代码文件的映射关系

### Phase A 重点文件
- `app/core/api_source.py`
- `app/core/llm_provider.py`
- `app/core/config.py`
- `app/ui/settings_page.py`

### Phase B 重点文件
- `app/core/context_manager.py`
- `app/core/conversation_store.py`
- `app/ui/components/panels/context_visual_panel.py`
- `app/ui/pages/context_page.py`
- `docs/上下文系统建设计划.md`

### Phase C 重点文件
- `app/core/agent_manager.py`
- `app/core/services/tool_router_service.py`
- `app/core/worker.py`
- `app/core/skills/core/` 下各工具实现
- `docs/函数调用总结.md`

### Phase D 重点文件
- `app/ui/pages/chat/message_area.py`
- `app/ui/components/chat.py`
- `app/ui/pages/chat/page.py`
- `app/core/api_source.py`

---

## 14. 下一轮建议

建议下一轮不继续扩写抽象文档，而是开始进入 Phase A 的现状梳理与方案设计：
- 当前设置页 API 配置入口到底在哪里
- 当前主配置与 API 独立配置如何冲突
- 怎样定义第一版 profile 结构
- 怎样把“深度思考”纳入配置模型

---

## 15. 对话级参数与 Agent 级参数分层

为了避免 API 配置中心继续滑向“所有东西都塞进一个表单”的混乱状态，后续设计必须明确区分：哪些参数属于对话生成，哪些参数属于 Agent 执行策略。

### 15.1 对话级参数（Conversation-level）
这类参数影响某一次会话的生成行为与上下文装配方式。

#### 典型包括
- `model`
- `temperature`
- `max_output_tokens`
- `reasoning.enabled`
- `reasoning.effort`
- `conversation_defaults.context.*`
- `conversation_defaults.system.user_prompt`
- `inject_skills_prompt`
- `inject_ai_readme`

#### 说明
它们本质上决定的是：
- 这一段对话用什么模型思考
- 以什么风格生成
- 用多少上下文预算
- 注入哪些系统层信息

因此，它们应优先归入“对话配置”，而不应与工具权限、任务步数等 Agent 策略混在一起。

### 15.2 Agent 级参数（Agent-level）
这类参数决定 AI 是否能执行任务、如何执行任务、失败时如何恢复，以及工具结果如何进入状态系统。

#### 典型包括
- `agent.enabled`
- `agent.max_steps`
- `agent.auto_execute_tools`
- `agent.retry_count`
- `agent.allow_tools`
- `agent.tool_summary_mode`

#### 说明
它们本质上决定的是：
- Agent 是否有“手脚”
- 可以调用哪些工具
- 最多走几步
- 是否自动继续执行
- 工具结果在 UI 与 working memory 中如何被摘要化处理

### 15.3 当前配置结构的意义
本轮已落地的 `config/api_mode.json`，正是基于这个分层思路进行组织：
- `profiles` / `active_profile`：承载模型与推理配置
- `conversation_defaults`：承载上下文与系统层配置
- `agent`：承载任务执行策略

这为后续 Phase B / C / D 的实现提供了统一底座。

---

## 16. OpenClaw 借鉴点（产品方向）

OpenClaw 的价值不只是“又一个 AI 工具”，而是把 AI 从聊天框中解放出来，变成可以真正执行任务的宿主系统。对于当前项目，至少有以下几点值得吸收：

### 16.1 模型无关（Model-agnostic）
模型只是大脑，不应成为产品结构的中心。当前 API 配置中心已经开始向这一方向调整：
- 不再把 API 配置写死在旧设置扁平字段中
- 使用 `profiles` 承载模型配置
- 为 fallback / reasoning / capability 预留结构

### 16.2 Agent 是“手脚”，不只是聊天增强
产品目标不应停留在“做一个像网页聊天的 API 页面”，而应逐步推进为：
- 能读写文件
- 能执行代码
- 能使用知识检索
- 能通过技能系统扩展能力

这也是当前保留 `agent` 配置块的重要原因。

### 16.3 Skills 是生态主干，而不是点缀
项目本身已有 Skills 系统，因此后续应继续强化：
- 工具能力清单
- 工具结果摘要协议
- 有状态 / 无状态能力区分
- 面向任务执行的技能编排

### 16.4 多通道交互的宿主思维
ChatPage 只是当前入口之一，不应被误认为 Agent 本体。后续如果扩展远程通道、插件入口、自动化通道，应尽量保持消息结构与任务结构独立于单一 UI 页面。

### 16.5 本地优先、隐私可控、执行闭环
当前项目已具备本地文件、Docker 沙盒、浏览器自动化、Skills 扩展等基础，因此更适合沿着“本地优先的可执行 Agent”方向演化，而不是重新退回纯聊天产品思路。

---

## 17. Phase A V1 已落地说明

本轮已完成 Phase A V1 的核心底座改造：

### 已完成
- 新增 `app/core/api_mode_config.py`
- 新增正式配置文件 `config/api_mode.json`
- 将 `APISource` 切换为使用新配置单一真源
- 保留从 `experimental/config.json` 与 `config.json` 的兼容迁移逻辑
- 将设置页 API 区块切换为读写 `api_mode.json`
- 增加“深度思考”与“思考强度”最小配置入口
- 在配置结构中正式引入 `agent` 块

### 当前状态
这并不意味着完整的 API 配置中心已全部完成，而是意味着：
- 数据结构已从“临时兼容层”升级为“正式底座”
- Phase B / C / D 已经有统一配置宿主
- 后续再加工具摘要策略、异常分类、连接测试与更强的上下文热应用能力时，不需要推翻本轮结构

## 18. 2026-03-21 Phase A 阶段验收补充（运行时与远程状态闭环）

在本轮推进中，Phase A 已从“配置中心底座”继续补到“运行时闭环 + 用户可感知闭环 + 远程状态同步闭环”的阶段。

### 已完成补充
- ✅ `fallback_chain` 已从“纯配置层”推进为“运行时自动切换第一版”
- ✅ fallback 成功后，系统会通过状态提示明确告知用户已自动切换到备用模型
- ✅ 设置页支持 Profile 重命名
- ✅ 设置页支持 API Key 显示 / 隐藏
- ✅ 设置页 Fallback 顺序支持添加 / 上移 / 下移 / 移除，并具备操作反馈
- ✅ Fallback 顺序调整改为自动保存，可在关闭后记忆优先级顺序
- ✅ 设置页摘要支持“配置主 Profile / 当前运行 Profile”分离展示
- ✅ 本地模式与远程模式的“当前运行 Profile”状态源已统一：
  - 本地模式：读取 `worker.api_source.current_runtime_profile_key`
  - 远程模式：通过 `context_status_signal` 同步 `configured_profile_key / runtime_profile_key`

### 当前判断
这意味着 Phase A 的核心目标——“建立独立、明确、可切换、可降级的 API 配置中心，解决设置页配置与实际运行状态不一致问题”——已经完成第一阶段验收。

### 仍待后续推进
- 🚧 对 provider 调用异常做更细的“可降级 / 不应降级”分类
- 🚧 补充连接测试 / Profile 健康检查能力
- 🚧 继续优化配置中心视觉表达与运行状态展示美观度
- 🚧 将 Context / System 更深层热应用能力放入 Phase B 继续推进

## 18. 2026-03-21 Phase B 方案补充：上下文工作台（Context Workspace Panel）

### 18.1 设计结论
本轮确认：运行时上下文管理不应继续堆入 `SettingsPage`，也不应由 `ChatPage` 底部的 `ContextVisualPanel` 继续承担主入口。当前项目主窗口已具备标准 `QDockWidget + PanelManager + WorkspaceManager` 体系，因此上下文系统产品化的正确落点应为标准工作台面板。

### 18.2 方案选型
采用新增标准 Dock 面板的方式落地：
- 新增 `ContextWorkspacePanel`
- 支持显隐、拖拽、浮窗、停靠、标签化与工作区布局记忆
- 保持 `ContextPage` 继续承担“架构扫描 / Context Pack”职责，不与运行时上下文管理混用
- `ChatPage` 中现有 `ContextVisualPanel` 降级为轻量摘要视图，不再作为完整管理入口

### 18.3 工作台 V1 内容结构
`ContextWorkspacePanel` 第一版包含以下标签页：
1. **System**
   - 展示默认 user prompt、Skills Prompt 注入开关、AI_README 注入开关
   - 展示当前对话级 system prompt
   - 展示最终组合后的 system prompt
2. **Working**
   - 使用 JSON 形式展示并编辑 working memory
   - 支持保存 / 清空
3. **Long-term**
   - 展示当前长期记忆片段列表
   - 支持清空当前 long-term
4. **Budget**
   - 复用 `ContextVisualPanel` 展示 token 预算占用
   - 展示 runtime profile / context config / 历史预览数量等运行时信息

### 18.4 System Prompt 设计原则
System Prompt 不再被视为单一字符串，而应被视为多来源组合结果。当前至少区分：
- 默认 user prompt
- Skills Prompt 注入
- AI_README 注入
- 当前对话级 system prompt
- 最终组合结果（final system prompt）

该结构是未来多 Agent 协同的基础，避免后续再次退回“单文本框 prompt”模型。

### 18.5 第一轮落地边界
本轮优先打通 API 模式下的上下文工作台 V1：
- ✅ `ContextManager` 增加标准 getter
- ✅ `APISource` 增加上下文工作台读取 / 写入接口
- ✅ `WorkerThread` 增加桥接方法
- ✅ `RemoteWorker` 预留 RPC 包装方法
- ✅ `MainWindow` 注册标准 Dock 面板 `ContextWorkspacePanel`

### 18.6 本轮仍未完成的部分
- Browser 模式上下文工作台的对等接入
- 真正的多 Agent 作用域切换器
- Long-term Memory 的策略化 RAG 管理
- Short-term 截断策略编辑器
- 最终 system prompt 的来源树可视化

### 18.7 Phase B 第一轮阶段验收建议
- 用户可打开标准“上下文工作台”面板，并自由移动 / 浮窗 / 关闭
- 用户可查看当前对话的 system prompt 来源摘要与最终组合结果
- 用户可编辑当前对话 system prompt
- 用户可查看并编辑 working memory
- 用户可查看 long-term memory 片段
- 用户可查看 runtime budget / token 占用状态

## 19. 2026-03-24 Phase B 执行进展补充：上下文工作台 V1 已完成第一轮产品化闭环

### 19.1 当前判断
截至 2026-03-24，本轮 `Context Workspace Panel` 已从“方案确认 / 初步 UI 落地”推进到“产品主链闭环 + 布局记忆闭环 + 远程回包闭环”的阶段。

换言之，Phase B 当前不再只是“面板已经出现”，而是已经完成：
- 标准 Dock 面板注册
- 面板布局保存 / 恢复闭环
- API 模式上下文读取 / 写入闭环
- 本地 / 远程统一的工作台 payload 分发链
- System / Working / Long-term / Budget 四页 V1 可用形态

---

### 19.2 本轮已完成补充(2026-3-24)

#### A. 旧入口退场，工作台成为主入口
- ✅ 已移除 `ChatPage` 底部旧 `ContextVisualPanel` 作为完整管理入口
- ✅ 已清理相关残留引用，避免 `context_panel` 属性缺失崩溃
- ✅ 当前“上下文工作台”已成为运行时上下文管理的标准主入口

#### B. 工作台已真正进入 Dock / Workspace 体系
- ✅ `ContextWorkspacePanel` 已注册进标准面板系统
- ✅ 支持显隐、拖拽、浮窗、停靠、标签化
- ✅ 已修复布局记忆失效问题
- ✅ 已修复启动后面板菜单勾选状态不同步问题

#### C. 启动收尾改为显式流程，不再依赖脆弱计数器
- ✅ 已去除对 `expected_panels_count / all_panels_registered` 的核心依赖
- ✅ 改为在内置面板与插件面板处理完成后显式执行 `finalize_panel_startup()`
- ✅ 启动流程不再要求后续开发者 / AI 记住维护某个“系统面板数量”

#### D. API 模式上下文工作台真实链路已打通
- ✅ `WorkerThread` 已具备 `context_workspace_signal`
- ✅ `server.py` 已能将上下文工作台 payload 定向回送到发起请求的远程客户端
- ✅ `RemoteWorker` 已能接收 `context_workspace` 专用消息类型
- ✅ `MainWindow` 已从“同步直拉 payload”改为“异步桥接 signal”
- ✅ 刷新 / 保存 system / 保存 working / 清空 working / 清空 long-term 已形成真实回包闭环

#### E. Working Memory 已在 API 模式实装
- ✅ 当前任务记录支持：
  - 查看
  - JSON 编辑
  - 保存
  - 清空
- ✅ 当前 working memory 结构已按 V1 约定字段落地：
  - `current_goal`
  - `current_step`
  - `current_files`
  - `recent_tool_results`
  - `failure_reason`

#### F. System 页已完成一轮产品化收口
- ✅ 不再平铺三个长文本框
- ✅ 当前结构已改为：
  - 1 个主编辑区：当前对话 system prompt
  - 2 个折叠参考区：来源摘要 / 最终发送内容
- ✅ 避免用户误认为存在“两个重复系统说明窗口”

---

### 19.3 对当前 Phase B 验收标准的回看

对照 11.2 的 Phase B 验收标准：

#### 1. 用户可查看并编辑 system prompt
- ✅ 已完成

#### 2. working memory 有明确结构与可视化入口
- ✅ 已完成（API 模式）

#### 3. short-term 窗口参数可以调整
- 🚧 尚未完成
- 当前仍主要停留在运行时配置 / budget 展示层，未形成正式用户级调参入口

#### 4. long-term 注入状态可查看
- ✅ 已完成第一版查看
- 🚧 但“策略化管理 / RAG 注入策略”仍未完成

#### 5. context panel 不再只是“只读仪表盘”
- ✅ 已完成
- 当前工作台已具备 system 编辑、working memory 编辑、long-term 查看/清空、budget 展示等真实操作能力

---

### 19.4 当前边界再次确认
本轮继续坚持以下边界：

#### 已确认正确的边界
- ✅ 仅优先打通 API 模式的上下文工作台
- ✅ 不强求 Browser 模式对等接入
- ✅ 不让 Browser 主生产链承担 API 模式产品化试验成本

#### 说明
这意味着：
- Browser 模式当前不做 Working Memory 对等编辑链
- Browser 模式不做上下文工作台完整实装
- 该取舍是主动边界控制，而不是“忘了做”

---

### 19.5 仍待 Phase B 后续推进的部分
以下内容仍属于 Phase B 后续深化，不应误判为本轮已完成：

- 🚧 Browser 模式上下文工作台的对等接入（当前不做）
- 🚧 真正的多 Agent 作用域切换器
- 🚧 Long-term Memory 的策略化 RAG 管理
- 🚧 Short-term 截断策略编辑器
- 🚧 Output Reserve / Safety Margin 的正式高级配置入口
- 🚧 最终 system prompt 的来源树可视化

---

### 19.6 当前阶段结论
截至当前，Phase B 可以给出更准确的阶段判断：

- **不是**“上下文工作台方案已提出”
- **也不是**“只有一个可展示的 UI 壳”

而是：

> `Context Workspace Panel V1` 已完成第一轮产品化落地，
> 并已在 API 模式下形成“可查看、可编辑、可保存、可回包、可记忆布局”的主链闭环。

这意味着后续 Phase B 可以从“搭骨架”转入：
- Short-term 参数入口
- Long-term 策略化
- 多 Agent 作用域
- 更强的来源树可视化
等深化阶段。

## 20. 2026-03-24 Phase B 方案深化：上下文工作台跨对话控制（API Conversation Control Plane）

### 20.1 问题重述
当前 `ContextWorkspacePanel` 虽已完成第一轮产品化落地，但其控制模型仍主要绑定于“当前 active API 对话”。这在单对话调试阶段尚可接受，但在以下场景中已明显不够用：

- 前台处于 Browser 模式时，仍需要查看与调整 API 模式下各个对话/Agent 的状态
- 后续引入多 Agent / 高并发时，不能要求用户每次都“先切到目标对话，再刷新工作台”
- API 后台任务应能继续运行，而上下文工作台应作为独立控制台查看和管理它们

因此，下一阶段需要把 `ContextWorkspacePanel` 从：

- “当前 active API 对话查看器”

升级为：

- “API 多对话状态控制台（API Conversation Control Plane）”

---

### 20.2 目标定义
本轮目标不是做 Browser / API 的全统一上下文系统，也不是做完整多 Agent 平台，而是：

#### 目标 A：工作台可选择任意 API 对话
用户在上下文工作台中，应能直接选择某个 API conversation，而不依赖聊天页当前是否切到了它。

#### 目标 B：工作台可读写指定 API 对话状态
至少支持对指定 conversation 执行：
- 查看 system prompt 来源摘要与最终组合结果
- 编辑当前对话 system prompt
- 查看 / 编辑 working memory
- 查看 / 清空 long-term memory
- 查看 budget / runtime 状态

#### 目标 C：不干扰 Browser 主链
当前前台处于 Browser 模式时：
- Browser 主链继续正常工作
- API 后台对话继续运行
- 工作台仍可针对 API conversation 进行管理

#### 目标 D：不污染 active conversation
实现方式必须避免通过临时 `switch()` 切换 active conversation 再切回。  
正式方案应采用：
- `conversation_id` 显式定位
- 无副作用读取 / 写入指定 conversation 快照

---

### 20.3 为什么不能继续绑定 active conversation
当前 `APISource` 的上下文工作台接口主要围绕：
- `self.conv_store.active_id`
- `self.conv_store.context_manager`

这意味着现在的工作台实质上仍是：
- “当前 active conversation 的管理视图”

这种模型的问题在于：

1. **前台视图与后台状态耦合**
   - 只要前台不是 API active conversation，工作台就难以准确管理目标对话

2. **无法适配多 Agent**
   - 多个 API 对话并发运行时，工作台必须能盯住其中任意一个，而不是只能盯当前 active

3. **不利于 Browser 前台 + API 后台并行**
   - 你在 Browser 聊天时，API Agent 仍应继续推进
   - 工作台不应被 Browser 当前 UI 模式“锁死”

因此，跨对话控制不是“体验优化”，而是 `ContextWorkspacePanel` 从 V1 进入多对话控制台阶段的必要升级。

---

### 20.4 产品形态（你最终看到的 UI）
工作台顶部从当前的：

- meta label
- 刷新按钮

升级为以下结构：

#### 第一行：目标对话控制区
- `目标对话` 标签
- `QComboBox`：列出所有 API conversations
- `刷新列表` 按钮
- `跟随当前 API 对话` 开关（默认开启）
- `刷新` 按钮

#### 第二行：目标对话状态摘要
继续保留当前 meta 信息，但含义调整为：
- 当前工作台目标对话 title
- conversation id
- configured profile / runtime profile
- 当前 mode 提示（Browser 前台 / API 后台可并存）

#### 行为说明
- 默认情况下，工作台跟随当前 active API 对话
- 用户可手动切换到任意 API 对话
- 一旦手动切换，可进入“锁定模式”
- 锁定后，工作台不再跟随聊天页 active conversation 变化
- 即使前台切回 Browser 模式，工作台仍保留最后选择的 API 对话并可继续管理其状态

---

### 20.5 控制模式设计

#### 模式 A：跟随模式（默认）
- 如果当前 active 是 API conversation，则工作台自动跟随它
- 如果前台切回 Browser，工作台不自动清空，而是保留最近一次 API 目标

#### 模式 B：锁定模式
- 用户手动从下拉框选择某个 API conversation
- 工作台固定管理该目标
- 不因聊天页切换或前台模式变化而改变目标对话

#### 设计意义
这两种模式可以同时满足：
- 普通用户的“跟随当前对话”直觉
- 高级用户 / 多 Agent 场景下的“固定盯住某个后台 Agent”需求

---

### 20.6 数据层正式方案

#### 20.6.1 当前基础已具备
从现有实现看，`ConversationStore` 已经满足以下前提：
- 每个 API 对话独立存储为 JSON 文件
- 每个对话都有独立：
  - `system_prompt`
  - `history`
  - `long_term`
  - `working`
- `list_conversations()` 可列出所有 API 对话
- `get_meta(conv_id)` 可读取对话元数据

这说明“跨对话控制”不是推翻重做，而是在现有数据模型上补齐无副作用接口。

---

#### 20.6.2 `ConversationStore` 建议新增的无副作用接口
为避免污染 active conversation，建议增加以下正式接口：

##### A. `load_conversation_snapshot(conv_id: str) -> dict | None`
读取指定 conversation 文件，返回完整快照：
- `meta`
- `system_prompt`
- `history`
- `long_term`
- `working`

##### B. `build_context_manager_for(conv_id: str) -> ContextManager | None`
根据指定对话文件临时构建一个 `ContextManager`，用于：
- 查询 payload
- 计算 token usage
- 读取 working / long-term / history
- 但**不修改** `active_id` 与 `context_manager`

##### C. `save_context_manager_for(conv_id: str, cm: ContextManager) -> bool`
将指定 `ContextManager` 的状态写回指定 conversation 文件，**不切换 active**。

#### 说明
禁止采用：
- `switch(target_conv_id) -> 读取/修改 -> switch(back)`
这样的临时切换方案。  
因为这会污染 active 状态，影响聊天页、消息渲染和后续多 Agent 扩展。

---

### 20.7 `APISource` 升级方案

#### 20.7.1 当前问题
当前以下方法都隐式依赖 active conversation：
- `get_context_workspace_payload()`
- `update_conversation_system_prompt()`
- `set_working_memory()`
- `clear_working_memory()`
- `clear_long_term()`
- `get_context_status()`

这意味着工作台还不能显式操作某个指定的 conversation。

---

#### 20.7.2 目标改造
建议为这些方法增加可选参数：

- `get_context_workspace_payload(conversation_id: Optional[str] = None)`
- `update_conversation_system_prompt(content: str, conversation_id: Optional[str] = None)`
- `set_working_memory(data: dict, conversation_id: Optional[str] = None)`
- `clear_working_memory(conversation_id: Optional[str] = None)`
- `clear_long_term(conversation_id: Optional[str] = None)`
- `get_context_status(conversation_id: Optional[str] = None)`

#### 参数语义
- `conversation_id is None`
  - 保持现有行为：作用于 active conversation
- `conversation_id is not None`
  - 作用于指定 conversation
  - 不修改 active conversation
  - 不污染前台聊天页状态

---

#### 20.7.3 内部辅助方法建议
建议在 `APISource` 中新增：

##### A. `_get_cm_for(conversation_id: Optional[str] = None) -> ContextManager`
- 无参数时沿用当前 `_get_cm()`
- 有 `conversation_id` 时调用：
  - `conv_store.build_context_manager_for(conversation_id)`

##### B. `_save_cm_for(conversation_id: Optional[str], cm: ContextManager)`
- 无参数时保存 active conversation
- 有 `conversation_id` 时调用：
  - `conv_store.save_context_manager_for(conversation_id, cm)`

这样可最大限度复用现有 payload 构建和状态计算逻辑，而不破坏当前 active conversation 工作流。

---

### 20.8 Worker / Remote / Server 链路升级方案

#### 20.8.1 WorkerThread
为工作台相关桥接方法增加 `conversation_id` 参数：

- `get_context_workspace_payload(conversation_id=None, ...)`
- `update_context_workspace_system_prompt(content, conversation_id=None, ...)`
- `update_context_workspace_working_memory(data, conversation_id=None, ...)`
- `clear_context_workspace_working_memory(conversation_id=None, ...)`
- `clear_context_workspace_long_term(conversation_id=None, ...)`

同时，`context_workspace_signal` 发回 payload 时，应保留目标 `conversation_id` 信息，供 UI 确认当前回包属于哪一个目标对话。

---

#### 20.8.2 API 对话列表专用信号
当前工作台若要独立管理 API conversation，不建议继续混用 chat 页现有 `sessions_signal`。

建议新增专用能力：

##### WorkerThread
- 新增：
  - `api_conversations_signal = Signal(object)` 或 `Signal(list)`
- 新增方法：
  - `get_api_conversations()`

##### RemoteWorker
- 新增：
  - `api_conversations_signal = Signal(list)`
- 新增 RPC 包装：
  - `get_api_conversations()`
- 在 `on_agent_msg()` 中处理：
  - `mtype == "api_conversations"`

##### server.py
- 在 `SignalBridge` 或 RPC 回包链中新增：
  - `type: "api_conversations"`

#### 原因
工作台关心的是：
- API conversation 列表
而不是：
- Browser/API 混合的聊天页会话列表语义

因此应使用独立信号，保持职责清晰。

---

### 20.9 `ContextWorkspacePanel` UI 升级方案

#### 20.9.1 新增能力
在面板中新增：
- API 对话选择下拉框
- 刷新列表入口
- 跟随开关
- 目标 conversation_id 的内部状态持有

#### 20.9.2 信号调整建议
现有：
- `refresh_requested`
- `save_system_requested`
- `save_working_requested`
- `clear_working_requested`
- `clear_long_term_requested`

建议升级为带 `conversation_id` 参数的版本，例如：
- `refresh_requested(str)`
- `save_system_requested(str, str)`  # conv_id, content
- `save_working_requested(str, object)`  # conv_id, data
- `clear_working_requested(str)`
- `clear_long_term_requested(str)`

若需要兼容“当前目标为空”的状态，可约定：
- 空字符串表示当前 active conversation
但正式实现更建议始终显式持有当前 target id。

---

#### 20.9.3 工作流
##### 启动时
1. 请求 API conversation 列表
2. 填充下拉框
3. 默认选中 active API conversation 或最近一次目标对话
4. 请求该 conversation 的 payload

##### 用户手动切换目标对话
1. 工作台更新 `target_conversation_id`
2. 自动请求该 conversation payload
3. 不要求用户再额外点刷新

##### 保存 / 清空
所有操作都针对当前 `target_conversation_id`，不依赖聊天页当前 active conversation。

---

### 20.10 与 Browser 模式并行的设计边界

#### 本轮明确允许
当前前台处于 Browser 模式时：
- API conversation 仍继续存在
- API conversation 后台 Agent 仍可继续运行
- 工作台仍可读取/修改 API conversation 的：
  - system prompt
  - working memory
  - long-term
  - budget 相关状态

#### 本轮明确不做
- Browser conversation 的对等上下文工作台编辑
- Browser / API 统一 conversation control plane
- Browser 模式 working memory 对等实装

#### 说明
这不是缺口，而是当前阶段的主动边界控制：
- API 模式先形成稳定控制台
- Browser 主链保持低风险稳定运行

---

### 20.11 当前不纳入本轮范围的内容
为控制复杂度，本轮建议不同时推进以下内容：

- Browser 对话上下文对等编辑
- 多 Agent 专属分组 / 标签 / 看板 UI
- 工作台内直接创建 / 删除 / 重命名 API 对话
- Short-term 参数编辑器
- Long-term RAG 策略面板
- 最终 system prompt 来源树可视化
- Agent 执行步骤看板

这些能力应放入后续 Phase B 深化或更后续的 Agent 控制台阶段。

---

### 20.12 当前阶段结论
本节方案一旦落地，`ContextWorkspacePanel` 的定位将从：

- “API 当前对话上下文查看器”

升级为：

- “API 多对话状态控制台”

它将满足以下关键需求：
- 用户可在 Browser 前台时继续管理 API 后台对话
- 用户可直接切换目标 API conversation，而不是先切聊天页再刷新
- 工作台的上下文读写将正式从“隐式 active 模型”升级为“显式 conversation_id 模型”
- 为未来多 Agent / 高并发状态管理奠定接口基础

---

### 20.13 拍板建议
建议通过本方案，并作为 `Phase B` 下一步正式实施方向。

#### 建议决议文本
> 决定将 `ContextWorkspacePanel` 从“当前 active API 对话查看器”升级为“API 多对话状态控制台”。
> 本轮仅实现 API 对话跨对话控制，不做 Browser 模式对等接入；
> 采用 `conversation_id` 显式读写 + `ConversationStore` 无副作用快照接口方案，
> 严禁通过临时 `switch()` 污染 active 会话状态。

---

## 21. 2026-03-25 Phase B 实施进展补充：上下文工作台跨对话控制已落地

### 21.1 当前结论
截至 2026-03-25，上一节（第 20 节）提出的 `API Conversation Control Plane` 方案已完成第一轮真实落地，不再停留在“方案深化”阶段，而是已经形成从数据层、API Source、Worker、远程桥接到 UI 工作台的完整闭环。

---

### 21.2 已完成内容

#### A. 数据层：无副作用跨对话接口已补齐
- ✅ `ConversationStore` 已新增：
  - `load_conversation_snapshot(conv_id)`
  - `build_context_manager_for(conv_id)`
  - `save_context_manager_for(conv_id, cm)`
- ✅ 当前实现已正式避免通过临时 `switch(target) -> switch(back)` 的方式读写指定对话。
- ✅ 指定 API conversation 的快照读取、临时 `ContextManager` 构建、回写保存均可在不污染 active conversation 的前提下完成。

#### B. `APISource`：显式 `conversation_id` 读写已落地
- ✅ 以下接口已支持 `conversation_id=None` / 指定对话两种模式：
  - `get_context_workspace_payload(conversation_id=None)`
  - `update_conversation_system_prompt(content, conversation_id=None)`
  - `set_working_memory(data, conversation_id=None)`
  - `clear_working_memory(conversation_id=None)`
  - `clear_long_term(conversation_id=None)`
  - `get_context_status(conversation_id=None)`
- ✅ 已新增 `get_api_conversations()`，用于为工作台提供独立的 API conversation 列表。
- ✅ 已补齐 `_get_cm_for(...)` / `_save_cm_for(...)` 内部辅助路径，最大限度复用现有上下文构建逻辑。

#### C. Worker / Server / RemoteWorker：跨对话控制链已打通
- ✅ `WorkerThread` 已新增：
  - `api_conversations_signal`
  - `get_api_conversations()`
- ✅ 上下文工作台相关桥接方法全部支持 `conversation_id` 参数。
- ✅ `server.py` 已打通：
  - `api_conversations_signal -> api_conversations`
- ✅ `RemoteWorker` 已新增：
  - `api_conversations_signal`
  - `get_api_conversations()`
  - `on_agent_msg()` 对 `api_conversations` 的处理
- ✅ 本地 / 远程当前均可按统一语义处理“指定 conversation 的上下文工作台请求”。

#### D. `ContextWorkspacePanel`：已升级为多对话控制台 UI
- ✅ 面板顶部已升级为：
  - `目标对话` 标签
  - API 对话下拉框
  - `刷新列表` 按钮
  - `跟随当前 API 对话` 开关
  - `刷新` 按钮
- ✅ 工作台已持有内部目标 `conversation_id` 状态，不再只依赖聊天页当前 active conversation。
- ✅ 工作台信号已升级为带 `conversation_id` 的显式版本：
  - `refresh_requested(str)`
  - `save_system_requested(str, str)`
  - `save_working_requested(str, object)`
  - `clear_working_requested(str)`
  - `clear_long_term_requested(str)`
- ✅ 已新增 `update_conversation_list(...)`，可接收本地 list 或远程 payload dict，并统一填充目标对话下拉框。

#### E. `MainWindow`：桥接与初始化请求已完成
- ✅ `MainWindow` 已完成上下文工作台 handler 升级，统一支持 `conversation_id`。
- ✅ 已完成：
  - `request_conversations -> worker.get_api_conversations()`
  - `worker.api_conversations_signal -> panel.update_conversation_list()`
  - `worker.context_workspace_signal -> panel.update_payload()`
- ✅ 面板初始化后会主动请求：
  - API conversation 列表
  - 当前工作台 payload

---

### 21.3 当前能力边界

#### 已实现
- ✅ 用户可在 Browser 前台时继续管理 API 后台对话。
- ✅ 用户可直接切换目标 API conversation，而不必先切聊天页。
- ✅ 工作台读写已从“隐式 active conversation 模型”升级为“显式 `conversation_id` 模型”。

#### 尚未纳入本轮
- 🚧 Browser conversation 的对等上下文工作台管理
- 🚧 Browser / API 统一 conversation control plane
- 🚧 Short-term 参数编辑器
- 🚧 Long-term RAG 策略面板
- 🚧 最终 system prompt 来源树可视化
- 🚧 多 Agent 专属看板 / 分组 / 执行步骤视图

---

### 21.4 当前阶段判断
可以将本轮更准确地表述为：

> `ContextWorkspacePanel` 已从“当前 active API 对话查看器”升级为“API 多对话状态控制台”的第一版，
> 并已完成跨对话目标选择、显式 `conversation_id` 读写、本地 / 远程统一桥接三条主链闭环。

这意味着 Phase B 后续可以在当前实现之上继续深化“跟随 / 锁定模式细节”、“最近目标记忆”、“更强的多 Agent 作用域表达”与“更细的上下文策略可视化”，而不需要重新推翻这一轮的底层方向。



---

## 22. 2026-03-25 Phase C 规划：API 模式无状态工具能力接入 / 验证

### 22.1 阶段目标
Phase C 的目标不是再发明一套新的工具系统，而是把当前已经存在的 Skills / ToolRouter / Docker / Knowledge / Search 能力，以更稳健、可扩展、适合多轮 AI 协作开发的方式接入 API 模式。

当前优先聚焦的无状态工具包括：
- `file_operations`
- `code_execution`
- `knowledge_search`
- `web_search`

Phase C 的核心关注点包括：
1. API 模式下工具是否能被稳定识别并执行
2. 工具结果是否能正确回灌上下文并驱动后续回答
3. Browser / API 两条链的代码块 / tool_call 协议是否统一
4. 当前设计是否为未来多对话、多 Agent、原生 tools/function calling 预留扩展空间

---

### 22.2 当前问题判断
经过本轮审计，当前 API 模式虽然已经具备文本型工具调用加 ToolRouter 执行的雏形，但仍存在明显的协议层与闭环层缺口。

#### A. 工具协议尚未统一
- Browser 侧更接近整条文本加后处理提取模型。
- API 侧已经把回复切分为 `segments(type=text/code)`，但 `ToolRouter` 仍主要从 text segment 中二次正则提取代码块。
- 现有实现同时混用三反引号 fenced block 与旧式三单引号风格代码块匹配。
- `ToolRouter._extract_raw_text()` 当前只取第一个 segment，无法可靠覆盖复杂回复。

#### B. API 模式代码块提取存在 Markdown 污染风险
已观测到 API 模式下执行的代码正文混入 fence 外残留文本，导致实际送入 Docker 的并非纯 Python 代码，而是代码加 Markdown 残片的脏内容。

#### C. API 工具调用尚未形成完整自动闭环
当前链路基本是：
1. 用户提问
2. API 返回文本回复
3. Worker 调 ToolRouter 尝试执行工具
4. 工具结果被加回上下文

但目前尚未形成稳定的工具执行后自动继续向模型发起二轮补全并返回最终回答的产品化闭环。

#### D. 并发与多 Agent 尚不宜过早承诺
虽然上下文工作台已进入显式 `conversation_id` 模型，但 API 发送主链、ToolRouter、Docker 与 Skill 执行链当前仍更适合单对话串行闭环场景。未来多对话与多 Agent 并发工具执行必须建立在显式作用域与协议统一之后。

---

### 22.3 架构原则
为避免再次把工具协议、代码块提取、执行回灌全部堆叠在 `worker.py` 与 `api_source.py` 内，本阶段采用以下架构原则：

#### 原则 1：协议层与执行层分离
消息分段、Markdown 解析、tool_call 提取、技能执行、结果回灌、二轮推理不能继续混在单个函数内。解析只负责识别意图，执行只负责执行，对话回环只负责控制多轮。

#### 原则 2：Browser 与 API 共用中间协议
Browser 与 API 不应长期维持两套工具识别逻辑，应抽象出独立中间层，把不同来源的消息统一解析成标准化 `ToolIntent`。

#### 原则 3：先支持文本协议，保留升级到原生 tools 的接口位
Phase C 第一轮继续兼容文本型 `tool_call` 与 `# EXEC` 入口，但设计上不把正则扫 Markdown 写死为最终方案，为后续 OpenAI 与 Anthropic 原生 tools 留接口。

#### 原则 4：conversation scope 显式化
工具相关数据结构逐步显式携带 `conversation_id`、`source` 等作用域信息。即便第一轮仍以单对话串行为主，也要为未来多 Agent 并发保留演化空间。

#### 原则 5：先保证单轮正确，再谈并发
第一轮优先目标是单 API 对话、同步调用、工具识别正确、执行正确、回灌正确、自动续答正确。多对话并发工具调用不是当前轮次的交付承诺。

#### 原则 6：多文件、小模块、强命名
新逻辑应拆成小文件，文件名直接体现职责，方便未来人类开发者与 AI 协作者快速定位与定点修改。

---

### 22.4 建议新增模块：`app/core/tool_runtime/`
为承接 Phase C 的协议层与执行层拆分，计划新增独立目录：

```text
app/core/tool_runtime/
  __init__.py
  models.py                 # ToolIntent / ToolExecutionResult / ToolRoundResult
  markdown_parser.py        # fenced code / tool_call / 正文提纯
  segment_parser.py         # 从 messages/segments 提取标准化工具意图
  executor.py               # 执行 ToolIntent（SkillsManager / Docker）
  conversation_loop.py      # 工具执行后的单轮 / 多轮闭环控制
  policies.py               # 工具白名单、轮数、自动执行策略等
```

此目录的目标不是立即推翻现有 `ToolRouterService`，而是提供一个更稳定的内部中间层，使得未来 Browser 与 API 可共用同一解析语义，`ToolRouterService` 逐步转为薄桥与兼容入口，新需求也不再继续堆进超大文件 `worker.py`。

---

### 22.5 各模块职责规划

#### A. `models.py`
定义标准中间对象，至少包括：
- `ToolIntent`：`kind`、`name`、`arguments`、`code`、`lang`、`source`、`conversation_id`、`raw_block`
- `ToolExecutionResult`：`success`、`kind`、`name`、`output`、`error`、`conversation_id`、`display_text`
- `ToolRoundResult`：`intents`、`results`、`has_any_tool`、`combined_feedback`

#### B. `markdown_parser.py`
专门处理 Markdown、fenced block、tool_call 的文本解析：
- `split_fenced_blocks(text)`
- `strip_fence(block_text)`
- `detect_fence_lang(block_text)`
- `extract_tool_call_json(block_text)`
- `extract_exec_code(block_text)`

重点要求：同时兼容三反引号与旧式三单引号，兼容 `python`、`py`、`tool_call`、`json`，并且只负责提纯与识别，不负责执行。

#### C. `segment_parser.py`
从统一 message 与 segment 结构中提取 `ToolIntent`：
- 优先消费 `type=code` segment
- 如有 `code` 字段则直接取纯正文
- 如只有原始 Markdown block，则先 strip fence 再判断类型
- 只有在没有 code segment 时，才回退到 text 中搜索 fenced block
- 不再只看第一个 segment，而是处理整条消息的全部 segment

#### D. `executor.py`
专门执行标准化 `ToolIntent`：
- `skill_call` 走 `SkillsManager.execute_skill()`
- `exec_code` 走 `DockerManager.execute_code()`
- 统一返回 `ToolExecutionResult`

未来可在此处扩展安全白名单、风险等级、每类工具超时策略与不同会话的执行隔离。

#### E. `conversation_loop.py`
负责 API 工具轮控制：
- 执行一轮工具识别与执行
- 把工具结果回灌上下文
- 决定是否自动继续请求模型生成最终回答
- 控制最大自动轮数，避免无限循环

第一阶段先实现单轮工具执行加自动续答，后续再扩展为更强的多轮 loop。

#### F. `policies.py`
统一管理策略边界：
- API 模式是否允许自动 `exec_code`
- 每轮最大工具数
- 自动续答轮数限制
- 白名单与黑名单策略
- 未来多 Agent 后台执行开关

---

### 22.6 分阶段实施路线图

#### Phase C-1：协议统一层
目标：先解决当前最影响可靠性的协议问题，而不是急于堆叠更多功能。

交付重点：
- 新建：
  - `app/core/tool_runtime/models.py`
  - `app/core/tool_runtime/markdown_parser.py`
  - `app/core/tool_runtime/segment_parser.py`
- 改造：
  - `app/core/api_source.py`
  - `app/core/services/tool_router_service.py`

本阶段重点修正：
- API code segment 增加 `code` 与 `lang` 等显式字段
- ToolRouter 不再只看 text segment
- ToolRouter 同时兼容三反引号与旧式三单引号
- `_extract_raw_text()` 不再只取第一个 segment
- API 与 Browser 工具提取语义开始统一
- 修复代码块正文混入 Markdown 文本问题

#### Phase C-2：单轮工具闭环
目标：在协议统一后，补上 API 模式下的最小产品化体验。

交付重点：
- 新建：
  - `app/core/tool_runtime/conversation_loop.py`
- 改造：
  - `app/core/worker.py`
  - `app/core/api_source.py`

本阶段完成：
- 工具执行后自动回灌上下文
- 自动触发二轮模型补全
- 向用户返回工具执行加最终自然语言回答的完整闭环
- 暂时以同步模式为主，不先碰流式工具链

#### Phase C-3：策略与安全边界
目标：把能跑升级为可控。

交付重点：
- 新建：
  - `app/core/tool_runtime/policies.py`
- 统一管理：
  - 自动执行白名单
  - `exec_code` 风险边界
  - 自动轮数
  - 每轮最大工具数
  - 错误回灌格式

#### Phase C-4：显式 conversation 作用域
目标：为未来多对话与多 Agent 工具系统打基础。

本阶段重点：
- ToolIntent 与 ToolExecutionResult 显式携带 `conversation_id`
- API 发送主链逐步支持显式目标对话执行
- 工具结果回灌按目标对话分流
- 避免未来前台切换对话时后台工具结果串台

#### Phase C-5：原生 tools 与 function calling
目标：在文本协议稳定后，再评估是否切换到标准化原生工具调用。

本阶段可能涉及：
- `llm_provider.py` 扩展 `tools=` 与 `tool_calls`
- 原生 `role=tool` 回灌
- 更标准的 OpenAI 与 Anthropic 工具消息模型

此阶段不作为 Phase C 第一轮强制目标，以避免过早抬高复杂度。

---

### 22.7 当前边界声明
为避免误判当前能力，现阶段明确以下边界：

#### 当前优先承诺
- 单 API 对话中的同步工具调用可靠性
- 统一 Browser 与 API 的工具解析语义
- 代码块提纯与执行输入正确性
- 工具执行后自动续答的最小闭环

#### 当前暂不承诺
- 多 API 对话并发工具执行完全隔离
- 多 Agent 后台自动并发工具调度
- 流式工具调用与流式 tool_calls 完整闭环
- 原生 OpenAI tools 与 function calling 全量接入

这并非否认未来方向，而是避免在协议层尚未统一前过早引入更复杂的并发与流式问题。

---

### 22.8 对项目结构文档的同步要求
随着 Phase C 启动，项目导航文档 `docs/项目结构导航.md` 也应同步升级，反映新的工具运行时拆分方向。重点包括：
- 在 App Core 中新增 `tool_runtime/` 相关模块导航
- 在理解 API 模式、代码执行、Skills 系统等快速导航项中补充 `tool_runtime` 层
- 明确 `ToolRouterService` 未来定位为兼容层与薄桥，而不是无限膨胀的单点逻辑容器

---

### 22.9 当前阶段结论
Phase C 第一轮不应简单理解为把四个工具接上就完事，而应更准确地表述为：

以 `tool_runtime` 中间层为核心，先统一 Browser 与 API 的工具协议、代码块提取语义与执行输入，再在此基础上补齐 API 模式下的单轮工具闭环与自动续答能力，并为未来多对话、多 Agent、原生 tools 演进预留结构化接口。

这一路径的价值在于：
- 不为短期修 bug 牺牲长期可演进性
- 使人类开发者与 AI 协作者更容易在小模块中协同推进
- 为后续 Phase C 深化与更长期的 Agent 化能力留下清晰骨架

---

## 23. 2026-03-27 主线需求收口：从继续规划转入可执行清单

### 23.1 当前判断
截至当前，API 模式主线已经不是“完全没骨架”，而是进入了一个更容易误判的阶段：
- Phase A 已完成第一阶段验收
- Phase B 已完成上下文工作台与 API 多对话控制台第一轮落地
- Phase C 已完成方向明确、文档规划与部分基础设施准备

但与此同时，仍有若干关键缺口没有真正收口。如果继续只做抽象规划，而不把需求压成可执行清单，后续开发会反复在“看起来方向很多”与“实际上不知道先改哪里”之间来回打转。

因此，本节目标不是再引入新抽象，而是把近期已明确的主线需求收拢成可行动项目，推动开发从“继续讨论”转入“逐项实施”。

---

### 23.2 已形成共识的关键缺口

#### A. Prompt Assembly 仍未完整收口（Phase B）
当前 API 模式并没有真正完成稳定的 Skills Prompt / `SKILL.md` 自动注入链，`inject_skills_prompt` 与 `inject_ai_readme` 虽已有配置位与部分工作台展示，但距离“最终 system prompt 真实装配、可观测、可验证、可控”仍有明显缺口。

这意味着当前问题不是“提示词注入过重”，而是“注入链本身尚未完整建立”。因此，Phase B 仍需继续推进：
- Skills Prompt 注入链
- AI_README 注入链（已更改为docs\API模式开发计划.md）
- 最终 system prompt 合成链
- 对话级 system 装配结果可观测与可校验

#### B. API 对话缺少精细历史控制能力（Phase B）
当前 API 模式可以追加消息、切换对话、保存上下文，但仍缺少最基本的对话回退能力：
- 删除最近一轮 user + assistant
- 删除最后一条 assistant 并重新生成
- 为未来按消息位置回滚预留接口

这会导致：
- 用户说错一句话，整个后续上下文被污染
- AI 理解偏了，只能继续堆纠错，而不能优雅重试
- working memory 与 short-term history 容易残留错误前提

因此，Phase B 需要正式补上“对话历史可管理性”，而不是只把上下文工作台停留在查看与局部编辑层面。

#### C. 上下文工作台仍偏状态面板，尚未成为运行时控制台（Phase B）
当前很多关键上下文参数仍然：
- 不可编辑
- 或只能去设置页全局修改
- 无法针对某个 conversation 单独调整
- 更无法为未来 agent 单独覆盖

用户真实需求不是“只看当前上下文占用”，而是：
- 针对某个对话调上下文容量
- 针对某个对话调历史轮数上限
- 针对某个对话开关 AI_README / Skills Prompt
- 未来甚至针对某个 Agent 单独调参

因此，需要明确参数分层：
- 设置页负责全局默认值（defaults）
- 上下文工作台负责 conversation-scoped overrides
- future：为 agent-scoped overrides 预留位置

#### D. 工具执行链存在多入口并存问题（Phase C）
近期读码已确认，当前项目中同时参与“工具执行 / 触发 / 协议解释”的位置至少包括：
- `SkillsManager`
- `ToolRouterService`
- `WorkerThread`
- `AgentManager`
- `APISource` 上游消息结构层

同时，工具协议也仍然并存：
- 旧式 `[TOOL: ...]`
- ```tool_call JSON
- ```python + `# EXEC`

这说明当前系统处于“旧 Agent 工具协议 → 新 Skills / ToolRouter / Function Calling 协议”的过渡期，而且尚未收口。

因此，Phase C 的首要工作之一不是继续叠逻辑，而是先明确：
- 哪些是未来主干
- 哪些是兼容层
- 哪些是待退役旧层
- 哪个位置才是正式的工具执行硬闸

#### E. 工具可见性 / 工具执行权尚未统一（Phase C）
当前至少仍然存在以下分裂：
- UI 中的 Skill 启用/禁用状态
- `get_all_tool_definitions()` 的工具暴露逻辑
- `generate_system_prompt()` 的提示词暴露逻辑
- `execute_skill()` 的执行期 enabled 检查
- 旧 Agent wrapper 的 legacy fallback

这会导致典型问题：
- UI 看起来禁用了，但某些路径仍可调用
- prompt 暴露集合与实际可执行集合不一致
- Browser / API / ToolRouter / 手动触发之间没有共享同一个最终可用集合

因此，后续必须引入统一的工具可用性解析层，例如：
- `ToolAvailabilityEntry`
- `ToolAvailabilitySnapshot`
- `ToolAvailabilityService`

并把 prompt / tools / UI / execute 都逐步挂到同一份 conversation-scoped 快照之上。

#### F. 工作空间（workspace）仍未进入正式作用域模型（跨 Phase）
当前很多能力默认绑定“IDE 当前项目 = 唯一工作空间”，包括：
- `file_operations` 安全路径
- Docker 沙盒挂载目录
- knowledge_search 索引根目录
- AI_README / PROJECT_STRUCTURE 注入来源
- context pack / project map / project scanner

但未来明确会需要工作空间切换，因此不能继续默认全局唯一项目根。更合理的方向是：
- 建立正式 `workspace` 概念
- 让 conversation 显式绑定 workspace
- 让文件安全边界、Docker mount、知识索引、Prompt 注入都按 workspace 作用域运行

这一需求虽然不必立刻全量落地，但从现在开始，相关新接口与新模型都应开始预留：
- `workspace_id`
- `workspace_root`

否则未来再补会代价更高。

---

### 23.3 已确认的阶段结论（后续无需反复怀疑）
为避免上下文裁剪后重复投入，当前保留以下明确结论：

#### A. `file_operations` 已是近期专门增强并验证过的基础设施
它已具备并验证以下能力：
- 写入、追加、替换、前后插入
- 删除、区块级编辑、行级编辑
- 风险删除保护
- Python / JSON / TOML 写盘前验证
- 文件尾部读取验证

后续文档维护、长 Markdown 写入、局部文件编辑应优先复用 `file_operations`，不要退回 `code_execution + 长字符串写文件` 的旧路径。

#### B. `docs/API模式开发计划.md` 的 Phase C 文档已成功落地
第 22 节 Phase C 详细规划已追加写入成功，后续不必重复怀疑是否落盘。

#### C. `docs/项目结构导航.md` 已同步补充 `tool_runtime` 与 `file_operations` 子模块关键文件
项目结构文档已反映新的工具运行时方向与文件工具链拆分方向，可作为当前导航依据继续使用。

---

### 23.4 从现在开始的执行优先级（行动导向版）

#### P0：立即进入实施
1. 补齐 Phase B 的 Prompt Assembly 主链：
   - Skills Prompt / `SKILL.md` 注入路径
   - AI_README 注入路径
   - final system prompt 合成与可观测
2. 补齐 API 对话历史控制：
   - 删除最近一轮
   - 重新生成最后回复
3. 把上下文工作台从“状态面板”升级为“conversation-scoped runtime control surface”：
   - 允许直接编辑关键上下文参数
   - 支持 conversation overrides
4. 对当前工具执行链做现状审计并开始收口：
   - 主干 / 兼容 / 退役分类
   - 明确正式工具执行硬闸位置
5. 开始建设工具可用性统一解析层：
   - availability / snapshot
   - 让 prompt / tools / execute 共享同一决策源

#### P1：紧随其后推进
1. history 回退与 working memory 污染关系治理
2. 参数作用域 UI：默认值 / 当前值 / override / 恢复默认
3. workspace 正式模型预留
4. conversation 与 workspace 绑定设计
5. API 模式工具验证矩阵持续补齐

#### P2：后续深化
1. agent-scoped overrides
2. 指定消息位置回滚
3. 更细粒度 tool visibility（manual-only / model-visible）
4. Browser 模式对等上下文工作台
5. 多 workspace / 多 agent / 更复杂运行时作用域

---

### 23.5 当前执行原则
为了避免项目继续陷入“计划越来越多，动作越来越少”的状态，后续主线推进采用以下原则：

#### 原则 1：继续小步快跑，但不再只停留在文档规划
后续每一轮优先输出：
- 现状定位
- 最小改造方案
- 动手落地
- 立即验证

#### 原则 2：已验证的基础设施优先复用
尤其是文件修改类需求，优先走已增强并验证过的 `file_operations`。

#### 原则 3：Phase B 与 Phase C 并行推进，但不混淆
- `SKILL.md` / AI_README / system prompt 注入归 Phase B
- tool protocol / tool runtime / executor / snapshot 归 Phase C

#### 原则 4：所有新运行时对象尽量显式作用域化
从现在开始，相关接口与数据结构应优先预留：
- `conversation_id`
- future: `workspace_id`
- source / mode / policy scope

这样才能为后续多对话、多 Agent、多 workspace 发展留出空间。

---

### 23.6 当前阶段结论
截至当前，API 模式的主线瓶颈已经非常明确：

不是“系统完全没做”，而是：
- Prompt Assembly 仍未收口
- 对话历史控制缺失
- 上下文工作台缺少作用域化运行时控制能力
- 工具执行链多入口并存、可见性与执行权分裂
- workspace 尚未正式进入作用域模型

因此，从本节开始，后续不再把这些问题视为“零散抱怨”，而应视为下一阶段正式实施清单。

换句话说：

> 从现在开始，API 模式主线进入“收口并逐项落地”阶段。
> 目标不再是继续堆抽象计划，而是按 P0 / P1 / P2 节奏，把这些已明确缺口逐项变成真实代码与可验证能力。

