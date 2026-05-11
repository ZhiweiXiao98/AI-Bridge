重新整合系统提示词组成，系统提示词来源为Prompt文件夹下的兼容提示词（后续升级为用户切换模式，当前由AI决定模式）、用户偏好（后续升级为程序+AI自动整理，后续还有针对模型的模型偏好，比如claude模型需要额外加的提示词、gpt模型需要二外加的提示词）、Build_SystemPrompt.md、Plan_SystemPrompt.md，这些内容为用户直接修改或ai帮忙修改的md文件。注：Prompt\系统提示词.md为整合之后可注入浏览器模式的系统提示词
除此之外加上当前对话系统说明（当前面板已有）
已有的skill列表+已激活的skill提示词+调用的skill提示词（短期存在）
当前任务：可人为绑定计划书，后续升级为AI自动注入并随着任务进度修改。
长期记忆：历史压缩的记忆+AI_JOURNAL.md(AI_JOURNAL.md，仅供检索（需要提供检索方式），不提供具体内容)
短期记忆：未压缩的正常的对话上下文
当前对话：用户最新的提问

┌─ System Prompt Layer ──────────────────────────────┐
│  Prompt/兼容提示词.md        (基础协作流程，始终注入)    │
│  Prompt/用户偏好.md          (用户偏好，始终注入)       │
│  Prompt/Plan_SystemPrompt.md                        │
│    And Prompt/Build_SystemPrompt.md        │
│  Skills Prompt               (工具描述，始终注入)      │
│  当前对话系统说明              (面板已有，per-conversation)│
└────────────────────────────────────────────────────┘
┌─ Current Task Layer ───────────────────────────────┐
│  绑定的计划书内容 (手动绑定 → 后续 AI 自动)            │
│  → 注入 working_memory                              │
└────────────────────────────────────────────────────┘
┌─ Long-term Memory Layer ───────────────────────────┐
│  历史压缩摘要 (compact_summary)                      │
│  AI_JOURNAL.md 检索结果 (仅检索，不注入全文)           │
│  → 注入 long_term_fragments                         │
└────────────────────────────────────────────────────┘
┌─ Short-term Memory ───────────────────────────────┐
│  未压缩的对话上下文 (history)                         │
└────────────────────────────────────────────────────┘
┌─ Current Conversation ─────────────────────────────┐
│  用户最新提问 (history 中最后一条 user message)        │
└────────────────────────────────────────────────────┘

1.当前计划是兼容层+两个模式的提示词始终注入，不进行模式判断。
2.compact_summary 迁移到 long_term：这会改变压缩器的行为，当前它是作为 history 首条消息存在的。迁移后语义更清晰，但需要改 compaction 和 build_messages 两处。我确认要做这个迁移。
3.AI_JOURNAL.md 检索：309KB 的文件，你倾向用关键词匹配还是接入现有的 knowledge_search 语义检索？答：适配AI_JOURNAL.md 的工具索引（机械索引即可没必要上rag）+关键词匹配的
AI_JOURNAL.md的日期标题（方便索引相关内容）
当前
AI_JOURNAL.md的最新段的日志格式为
# filename: AI_JOURNAL.md
# 🚁 AI Bridge 行驶记录仪 (Flight Recorder)
> 记录每一次重要的代码变更、Bug修复与架构决策。

## 格式规范

每次解决完一个问题，请在末尾追加一条标准记录。

## 日期 | 标题 | 状态  

内容...



### 主标题规范
‘## 日期 | 标题 | 状态’  中必须尽量包含以下 3 项：
- 日期
- 本轮标题 / 核心动作
- 当前状态（`✅ 已解决 / 🚧 进行中 / ⚠️ 搁置`）

示例：

## 2026-04-01 | file_operations 恢复验证 + AI_JOURNAL 结构升级 | ✅ 已解决 


### 正文固定九段式
每条记录正文统一使用以下结构：

#### 1. 用户原始诉求
尽量保留用户当时的真实要求、边界条件和偏好，不要只写 AI 转述结论。

#### 2. 背景与上下文
说明本轮任务出现前的系统状态、相关历史、所属主线、前置问题或依赖关系。

#### 3. 目标
明确本轮要达成的结果，最好写成可以验证的完成态。

#### 4. 实施方案
记录采用的解决思路、关键设计决策、修改策略与注意事项。

#### 5. 关键改动文件
列出实际改动、重点检查或重点验证的文件路径。若未改文件，也应说明仅做验证/排查。

#### 6. 验证与证据
记录验证动作、关键日志、执行结果、测试输出、人工核对结论等。

#### 7. 问题与排查
记录过程中遇到的报错、误判、失败尝试、回退动作、定位过程和修正方式。

#### 8. 结果与影响
说明最终结果、影响范围、保留内容、回退内容、兼容性影响与后续约束。

#### 9. 状态与下一步
必须包含：
- **状态**: `✅ 已解决 / 🚧 进行中 / ⚠️ 搁置`
- **下一步**: 若仍有后续动作，明确写出。


### 推荐附加字段
如有必要，可在正文开头补充：

- **标签**: `file_operations` `skills` `journal`

用于提升后续检索、分类与压缩质量。

### 记录原则
1. 尽量保留用户关键原话与约束，不要过度摘要。
2. 优先记录事实、决策、文件、证据，不写空泛总结。
3. 如果本轮有错误尝试、回退或误判，必须写入“问题与排查”。
4. 如果只是验证、审计或定位问题，没有真正改代码，也要如实记录。
5. 每条记录应尽量做到“只看主标题和九段标题即可快速理解全貌”。
6. 标题尽量具体，避免只写“修复问题”“优化逻辑”这类模糊表述。

### 推荐模板

## YYYY-MM-DD | 标题 | ✅ 已解决

- **标签**: `tag1` `tag2`

#### 1. 用户原始诉求
...

#### 2. 背景与上下文
...

#### 3. 目标
...

#### 4. 实施方案
...

#### 5. 关键改动文件
- `path/to/file`

#### 6. 验证与证据
- ...

#### 7. 问题与排查
...

#### 8. 结果与影响
...

#### 9. 状态与下一步
- **状态**: ✅ 已解决
- **下一步**: ...



---
其中是包含**标签**的，可以利用标签先检索相关的主标题（含日期、标题、状态）放入长期记忆。
后续ai想调用，利用专门的记忆调用工具调用读取相关日志信息。





**修正后的完整方案：**

**Layer 1: 系统提示词（system message）**
```
Prompt/兼容提示词.md          ← 始终注入
Prompt/用户偏好.md            ← 始终注入
Prompt/Plan_SystemPrompt.md  ← 始终注入（不做模式判断）
Prompt/Build_SystemPrompt.md ← 始终注入（不做模式判断）
Skills Prompt                ← 自动生成，始终注入
当前对话系统说明              ← per-conversation，面板已有
```

**Layer 2: 当前任务（working memory）**
- 人为绑定的计划书内容，后续升级为 AI 自动注入

**Layer 3: 长期记忆（long-term fragments）**
- 历史压缩摘要（compact_summary）
- AI_JOURNAL.md 标签索引命中的主标题列表（日期 | 标题 | 状态）

**Layer 4: 短期记忆**
- 未压缩的对话历史

**Layer 5: 当前对话**
- 用户最新提问

---

**AI_JOURNAL.md 索引方案：**

1. 解析所有 `## YYYY-MM-DD | 标题 | 状态` 主标题行
2. 提取每条记录的 `**标签**: \`tag1\` \`tag2\`` 
3. 构建轻量索引：`{tag: [(date, title, status, line_start, line_end), ...]}`
4. 组装长期记忆时，按当前对话关键词/标签匹配，命中的主标题列表注入 long-term
5. AI 需要详情时，通过专用记忆检索工具按日期/标题读取对应段落全文

---

**需要新增的文件：**
- `app/core/prompt_runtime/prompt_file_loader.py` — 从 Prompt/ 文件夹读取 MD 文件
- `app/core/journal_index.py` — AI_JOURNAL.md 解析、索引、检索

**需要改动的文件：**
- `app/core/prompt_runtime/prompt_assembler.py` — 重写为文件驱动拼接
- `app/core/prompt_runtime/__init__.py` — 更新导出
- `app/core/api_source.py` — `_compose_system_prompt_payload()` 和 `get_context_workspace_payload()` 适配新结构
- Skills 定义中新增一个 journal 检索 skill（供 AI 按需读取日志详情）

**不动的部分：**
- `ContextManager` 分层结构不变（system / long_term / working / history）
- `context_compaction.py` 不变
- `conversation_store.py` 不变

---

方案：上下文快照调试浮窗

数据捕获 (api_source.py)
在  send_message_sync  /  send_message_stream  中， build_messages()  之后、调用 LLM 之前，捕获完整快照存入  _last_request_snapshot ：
 system_blocks : 6 个 prompt block 各自内容与 token 数
 long_term_fragments : 长期记忆片段列表
 working_memory : 工作记忆 dict
 history : 未压缩的对话历史（含 role/kind/content）
 final_messages : 实际发给 LLM 的 messages 数组
 response : LLM 返回的完整回复（请求完成后回填）
 timestamp ,  conversation_id ,  model 
暴露  get_last_request_snapshot(conversation_id=None)  方法
格式化层 (context_snapshot_formatter.py)
接收 snapshot dict，输出人类可读的结构化文本
按层分节： [Layer 0: System Prompt]  → 每个 block 独立展示（标题 + token + 内容）→  [Layer 1: Long-term]  →  [Layer 2: Working Memory]  →  [Layer 3: History] （每条消息标注 role/kind/tokens）→  [Layer 4: Final Messages] （实际发送的完整数组）→  [Response] 
每层有分隔线、token 小计、条目计数
浮窗 UI (context_snapshot_dialog.py)
QDialog，约 900×700
顶部：对话标题 + 时间戳 + model
主体：只读 QPlainTextEdit（等宽字体，方便阅读 JSON 和代码）
底部：「复制全部」按钮 + 「关闭」按钮
面板入口 (context_workspace_panel.py)
toolbar 区域加一个「📋 最近请求」按钮
双击打开浮窗
通过 worker → api_source.get_last_request_snapshot() 获取数据
