---
name: file_operations
display_name: 文件操作
category: file
description: 读取、写入、列出文件和目录
scenario: 需要查看文件内容、列出目录结构、检查文件是否存在、写入或编辑文件时
version: 2.2.1
author: System
dangerous: false
enabled: true
---

# 文件操作

## 技能描述

提供文件系统的基础读写与定点编辑能力，适合 AI 协作时读取文件、列目录、直接写文档、追加日志、替换片段、在锚点后插入内容。

## 可用操作

### read_file
读取文件内容，默认返回带行号内容；大文件会截断，但仍保留真实行号，便于后续精确编辑。

**参数**：
- `path` (str, 必需): 文件路径
- `max_lines` (int, 可选): 最大读取行数，默认 1000

### read_lines
按行号读取文件局部内容，并返回带行号的内容，适合大文件中的精确上下文查看与后续行级编辑。

**参数**：
- `path` (str, 必需): 文件路径
- `start_line` (int, 可选): 起始行号（从 1 开始）
- `end_line` (int, 可选): 结束行号（从 1 开始）

### list_files
列出目录下的文件和子目录。

**参数**：
- `path` (str, 可选): 目录路径，默认当前目录

### insert_before
在指定锚点文本前插入内容，适合在某标题、段落、配置块前增加新内容。

**参数**：
- `path` (str, 必需): 目标文件路径
- `anchor_text` (str, 必需): 锚点文本
- `content` (str, 必需): 要插入的内容
- `occurrence` (int, 可选): 第几个锚点，默认 1
- `strict_anchor` (bool, 可选): 多次命中时是否强制要求显式指定 occurrence

### read_file_tail
读取文件最后 N 行，并返回带真实行号的尾部内容，适合验证长文档尾部追加、查看日志最新输出。

**参数**：
- `path` (str, 必需): 文件路径
- `max_lines` (int, 可选): 最大读取尾部行数，默认 100

### file_exists
检查文件或目录是否存在。

**参数**：
- `path` (str, 必需): 目标路径

### stat_file
返回文件或目录的基本信息，不读取全文。

**参数**：
- `path` (str, 必需): 目标路径
- `output_format` (str, 可选): `text` 或 `json`，默认 `text`


---

### search_symbols
搜索指定文件内的所有符号定义（函数、类、方法、Markdown 标题等），返回完整结构化信息，适合实时定位具体实现。

**参数**：
- `path` (str, 必需): 源码文件路径
- `output_format` (str, 可选): 返回格式 `text` 或 `json`，默认 `text`

**支持的文件类型**：
- `.py`：提取类、函数、方法及其行号范围
- `.md`：提取章节标题及其层级和行号
### write_file
写入整个文件，可用于新建文件或覆盖现有文件。

**参数**：
- `path` (str, 必需): 目标文件路径
- `content` (str, 必需): 完整文件内容
- `create_dirs` (bool, 可选): 是否自动创建父目录，默认 true
- `overwrite` (bool, 可选): 是否允许覆盖已有文件，默认 true

### append_file
向文件末尾追加内容，适合追加日志、计划书章节、文档补充段落。

**参数**：
- `path` (str, 必需): 目标文件路径
- `content` (str, 必需): 要追加的文本
- `ensure_newline` (bool, 可选): 追加前是否确保换行，默认 true
- `create_dirs` (bool, 可选): 是否自动创建父目录，默认 true
- `allow_duplicate_append` (bool, 可选): 是否允许追加与文件中已存在的完全相同内容，默认 false

**默认防护**：
- 当待追加的 `content` 已经作为完整文本片段存在于目标文件中时，`append_file` 会默认阻止重复追加。
- 如确实需要重复追加，必须显式传入 `allow_duplicate_append=True`。

### replace_in_file
按文本进行定点替换，适合替换标题、配置段、文档块。

**参数**：
- `path` (str, 必需): 目标文件路径
- `old_text` (str, 必需): 待替换旧文本
- `new_text` (str, 必需): 替换后新文本
- `count` (int, 可选): 最大替换次数，默认 1

### insert_after
在指定锚点文本后插入内容，适合给文档某一标题后追加章节。

**参数**：
- `path` (str, 必需): 目标文件路径
- `anchor_text` (str, 必需): 锚点文本
- `content` (str, 必需): 要插入的内容

### 删除类操作
- `delete_text`: 删除精确文本片段
- `delete_between`: 删除两个锚点之间的内容
- `remove_section`: 按 Markdown 标题删除整节内容

### 区块级编辑
- `replace_between`: 替换两个锚点之间的内容
- `replace_section`: 按 Markdown 标题替换整节内容

### 行级编辑
- `delete_lines`: 删除指定行区间
- `replace_lines`: 替换指定行区间
- `insert_at_line`: 在某一行前或后插入内容

## 使用原则

1. **安全第一**：只能访问项目目录内的文件
2. **优先专用写入**：长文档、Markdown、计划书优先用 `write_file` / `append_file` / `insert_after`，避免走代码执行造成字符串地狱
3. **写后验证**：写入类操作会返回验证结果，帮助 AI 判断是否真的生效
4. **原子写入**：`write_file`、插入、替换默认采用原子写入，减少中途中断把文件写坏的风险
5. **小步编辑**：优先用追加、替换、插入，而不是反复整文件重写
6. **路径重定向**：支持旧路径自动映射到新路径
7. **完整读取，绝不盲判**：  
   - 在做任何覆盖性或结构性修改之前，必须尽可能完整读取目标文件（使用`read_file`或多次`read_lines`分段读取）  
   - 不允许仅凭片段判断或修改推断，须确保上下文完整性与一致性    
   - 如单次无法完整读取，需多次分段组合后确认全局结构  
   - 牢记：“No Full Read, No Write” 是唯一安全底线
8. **先用 `stat_file` 再深入读取**：面对大文件、陌生文件或核心代码文件时，先用 `stat_file` 获取结构摘要，再决定读哪些区段
9. **高风险操作优先显式确认参数**：若操作可能触发大删除、近空结果、内容坍缩风险，应优先改用更小步操作；确属用户明确要求时，再显式传入 `confirm_large_delete=True` / `allow_near_empty_result=True`
10. **不要把 `write_file` 当成默认编辑器**：`write_file` 更适合新建文件、完整重写短文档或你已完整掌握文件全貌的场景；对大代码文件优先用 `read_lines + replace_lines / replace_between`
11. **看到 RequiresConfirmation 要停下来复核**：当返回结果中出现 `RequiresConfirmation=True`、`BlockedBySafetyGuard=True`、`ContentCollapseDetected=True` 等字段时，不应继续盲写，必须先检查用户意图、文件上下文与修改范围
## 常见模式

### 读取文件
- `file_operations(operation="read_file", path="app/core/worker.py")`
- `file_operations(operation="read_lines", path="app/core/worker.py", start_line=80, end_line=120)`


### 搜索文件符号
- `file_operations(operation="search_symbols", path="app/core/worker.py")`
- `file_operations(operation="search_symbols", path="README.md", output_format="json")`
### 列目录
- `file_operations(operation="list_files", path="app/core")`

### 写整个文件
- `file_operations(operation="write_file", path="docs/tmp.md", content="# Title")`

### 给日志追加一节
- `file_operations(operation="append_file", path="AI_JOURNAL.md", content="## new log")`

### 替换某段文本
- `file_operations(operation="replace_in_file", path="docs/x.md", old_text="旧内容", new_text="新内容")`

### 在标题后插入内容
- `file_operations(operation="insert_after", path="docs/x.md", anchor_text="## 标题", content="

### 新段落
内容")`

## 注意事项
- 对 `.py` / `.json` / `.toml` 的插入操作（`insert_after` / `insert_before`）现已接入写盘前语法验证，若修改结果导致语法损坏，将直接阻断并返回错误。
- 对 `.py` 文件的 `insert_after`，若锚点位于 `class/def/if/try/...:` 这类块头，且插入内容首个非空行为无缩进的顶级定义（如 `class` / `def` / `import` / 装饰器），会被判定为高风险结构插入并阻断。
- 对 `.py` 文件命中块头锚点但未达到阻断条件的插入，会返回 `StructuralAnchorRisk=True` 与 `Suggestion`，提示优先考虑 `insert_before`、`replace_between` 或 `insert_at_line`。
- `stat_file` 已不只是基础文件状态检查；对 Python 文件会额外给出顶级函数、类、方法、导入与行号概览，适合先定位再读取。
- 高风险删除、区块替换、整文件覆盖现在可能返回 `RequiresConfirmation=True`、`BlockedBySafetyGuard=True`、`ContentCollapseDetected=True` 等提示字段；这表示当前操作需要复核，而不是说明工具坏了。
- ⚠️ 不能访问项目目录外的文件
- ⚠️ 二进制文件可能显示乱码，不适合本 Skill
- ⚠️ `replace_in_file` 默认只替换 1 次，避免误伤多处相同文本
- 💡 长 Markdown / 文档维护优先使用本 Skill，而不是 `code_execution` 写文件
- 💡 写操作返回 `Verified: True/False`，请继续检查结果而不要盲信
## 安全保护规则
- 删除和大范围替换默认受安全保护，不再默认宽松执行。
- 当删除比例过大、删除行数过多、结果接近空文件，或发生**内容坍缩**（例如大文件被写成极少量内容或近似空白）时，会触发保护。
- 当前高风险路径会优先返回带 `RequiresConfirmation=True` 的结果，用于提示调用方：这是高风险操作，需要人工复核或显式确认参数，而不是继续盲写。
- 如确实需要执行大删除，必须显式传入 `confirm_large_delete=True`。
- 如结果会接近空文件，还必须显式传入 `allow_near_empty_result=True`。
- 删除、区块替换、行级替换默认采用原子写入，防止写入半成品。
- 代码语法校验采用基于抽象语法树（`ast.parse`）和字节编译（`py_compile`）的双重机制，极大降低因缩进错误、BOM 或编码异常引起的误判风险。
- 在校验阶段，会智能捕获并兼容文件系统权限异常，确保文件写入流程的鲁棒性和高可用性。
## 代码验证规则
- 对 `.py`, `.json`, `.toml` 文件，编辑后默认执行语法有效性校验，方可写盘。
- Python 代码语法校验结合静态语法树分析与实际字节码编译检测，有效降低误报误判。
- 校验环节具备异常处理能力，避免权限等系统异常导致伪失败，提升整体稳定性。
- 代码语法验证失败则写入操作被阻断，确保不破坏现有文件内容。
- 可通过参数 `validate_code=False` 显式关闭校验，但不建议关闭，以保证文件安全。

## 适用建议
- 长文档优先使用 `replace_section`、`delete_between`、`remove_section` 等带边界操作
- 代码文件优先使用行级编辑并保留 `validate_code=True`
- 未读全文件时，不建议做大面积删除或整段重写

---

## 常见修改场景规范指导

### 场景一：大文件修改操作流程

> 推荐先执行：`stat_file -> search_symbols -> read_lines -> 精准编辑 -> 再验证`。
> 
> 对 Python 大文件，`stat_file` 会提示使用 `search_symbols` 获取完整结构：
> - 所有类、函数、方法的精确行号范围
> - 类的继承关系和所有方法列表
> - 无截断、无省略的完整符号索引
> 
> 对 Markdown 文档，`search_symbols` 可以：
> - 提取所有章节标题及其层级
> - 精确定位每个标题所在行号
> - 快速了解文档结构
> 
> 这样 AI 不必在 2000 行文件里从头盲找实现入口。

针对大文件，**尽量避免一上来就用 `read_file` 读取全文**，默认最大读取 1000 行，且大文件会被截断，截断后盲测猜测极易出错。推荐步骤：

1. 预检文件存在性：  
   `file_operations(operation="file_exists", path=...)`

2. 快速定位文件大小或结构：  
   通过 `stat_file` 获得文件大小等辅助信息

3. 按需分段读取关键区域：  
   - 先用 `read_lines` 读取目标区域上下文  
   - 或用 `read_file_tail` 读取文件尾部做定位

4. 精准定位修改点，读取附近上下文确认

5. 采取精准修改操作，如：  
   - 按行替换：`replace_lines`  
   - 按文本区块替换：`replace_between`

6. 操作后再次验证内容正确性，确认 `validate_code=True` 以保证语法正确

### 场景二：追加型文件修改流程

1. 预检文件存在性：`file_exists`  
2. 用 `read_file_tail` 查看文件尾部，避免重复追加  
3. 用 `append_file` 追加，默认防重复，可用 `allow_duplicate_append=True` 强制追加  
4. 追加后用 `read_file_tail` 验证

### 其他常见场景

- 指定文本替换，需先用 `read_lines` 定位旧文本  
- 插入内容用 `insert_after` / `insert_before`，避免插入破坏代码结构  
- 大范围删除需开启安全确认参数

---


**返回示例（Python 文件）**：

```text
📄 File: app/core/worker.py
Type: Python
Total Classes: 1
Total Functions: 3
Total Methods: 15

Functions:
  - main (lines 12-40)
  - helper_func (lines 50-70) [async]

Classes:
  - WorkerThread (lines 42-3040), bases: QThread
    Methods:
      * __init__ (lines 44-80)
      * run (lines 81-120)
      * _execute_task (lines 425-552)
```

**返回示例（Markdown 文件）**：

```text
📄 File: README.md
Type: Markdown
Total Headings: 25

Headings:
- # 项目标题 (line 1)
  - ## 功能介绍 (line 8)
    - ### 核心特性 (line 12)
  - ## 使用说明 (line 40)
```

**使用场景**：
- 需要快速了解文件内所有函数和类的定义位置
- 需要定位 Markdown 文档的章节结构
- 替代 `knowledge_search` 进行实时、准确的文件内符号搜索
- 配合 `stat_file` 使用：先用 `stat_file` 判断文件大小，再用 `search_symbols` 获取完整结构

**与其他工具的配合**：
- `stat_file` → `search_symbols` → `read_lines`：推荐的大文件探索链路
- `search_symbols` 返回实时文件内容，不依赖历史索引
- 对于超过 500 行的文件，`stat_file` 会建议使用 `search_symbols` 获取完整结构
