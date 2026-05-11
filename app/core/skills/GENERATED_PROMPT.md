# Available Skills

You have access to the following skills. Use them when appropriate.

## How to Use Skills

To use a skill, output a tool call in the following format:

```
<tool_call>
{
  "name": "skill_name",
  "arguments": {"param1": "value1"}
}
</tool_call>
```

**Important:** Use exact skill names and provide all required parameters.

## Available Skills

## Core Skills (Always Available)

### 代码执行

**Name**: code_execution
**Category**: code
**Scenario**: 需要验证代码逻辑、测试功能、诊断问题时

# 代码执行

## 技能描述

在隔离的 Docker 沙盒环境中执行 Python 代码，用于验证逻辑、测试功能、诊断问题。

## 核心能力

- 安全隔离：代码在 Docker 容器中运行
- 超时控制：默认 60 秒超时
- 资源限制：内存限制 1GB
- 代码验证：执行前进行静态安全检查

## 使用场景

### 1. 验证代码逻辑
测试一段代码是否能正常运行

### 2. 诊断问题
通过插桩打印变量值，定位 bug

### 3. 测试功能
验证函数或模块的行为

### 4. 探索 API
测试第三方库的使用方法

## 工作流程

1. **代码验证**：静态检查危险操作
2. **沙盒执行**：在 Docker 容器中运行
3. **超时控制**：超过时间自动终止
4. **结果返回**：返回输出和退出码

## 安全机制

### 静态检查
- 检测危险函数：os.system, eval, exec
- 检测文件操作：删除、修改系统文件
- 检测网络操作：未授权的网络请求

### 运行时隔离
- Docker 容器隔离
- 资源限制（CPU、内存）
- 网络隔离（可选）
- 文件系统只读（除工作目录）

## 使用原则

1. **最小代码**：只写必要的代码
2. **明确输出**：使用 print() 输出结果
3. **错误处理**：预期可能的异常
4. **超时意识**：避免无限循环
5. **验证结果**：检查输出是否符合预期

## 常见模式

### 模式 1：检查文件是否存在
import os
print(os.path.exists('/workspace/test.py'))

### 模式 2：打印变量值
variable = some_function()
print(f"variable type: {type(variable)}")
print(f"variable value: {variable}")

### 模式 3：测试函数
def test_function(x):
    return x * 2

result = test_function(5)
print(f"Result: {result}")
assert result == 10, "Test failed"
print("Test passed")

### 模式 4：验证导入
try:
    import some_module
    print(f"Module imported: {some_module.__version__}")
except ImportError as e:
    print(f"Import failed: {e}")

## 示例

### 示例 1：简单计算
print(2 + 2)

### 示例 2：文件检查
import os
files = os.listdir('.')
print(f"Found {len(files)} files")

### 示例 3：错误诊断
try:
    result = risky_operation()
    print(f"Success: {result}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

## 注意事项

- ⚠️ 这是危险操作，代码会被实际执行
- ⚠️ 避免无限循环和长时间运行
- ⚠️ 不要执行破坏性操作
- 💡 使用 # EXEC 标记才会执行
- 💡 执行结果会返回给你
- 💡 超时后容器会自动重启


---

### 文件操作

**Name**: file_operations
**Category**: file
**Scenario**: 需要查看文件内容、列出目录结构、检查文件是否存在时

# 文件操作

## 技能描述

提供文件系统的基本操作能力，包括读取文件内容、列出目录文件。

## 可用操作

### read_file
读取文件内容，支持大文件截断。

**参数**：
- `path` (str, 必需): 文件路径
- `max_lines` (int, 可选): 最大读取行数，默认 1000

**返回**：
- 文件内容（字符串）
- 如果文件过大，会截断并提示

### list_files
列出目录下的文件和子目录。

**参数**：
- `directory` (str, 可选): 目录路径，默认当前目录

**返回**：
- 目录内容列表（格式化字符串）

## 工作流程

### 读取文件
1. 检查文件是否存在
2. 检查是否有访问权限
3. 读取内容
4. 如果超过 max_lines，截断并提示
5. 返回内容

### 列出目录
1. 检查目录是否存在
2. 扫描目录内容
3. 分类：目录 vs 文件
4. 排序并格式化输出
5. 过滤特殊目录（.git, __pycache__ 等）

## 使用原则

1. **安全第一**：只能访问项目目录内的文件
2. **验证路径**：使用前检查文件/目录是否存在
3. **处理错误**：优雅处理权限错误、编码错误
4. **大文件处理**：自动截断，避免内存溢出
5. **路径重定向**：支持旧路径自动映射到新路径

## 常见模式

### 检查文件是否存在
在读取前先检查：
- 使用 `list_files` 查看目录
- 或直接尝试 `read_file`，会返回错误信息

### 探索项目结构
从根目录开始：
1. `list_files(".")` 查看根目录
2. `list_files("app/core")` 深入子目录
3. `read_file("app/core/worker.py")` 查看具体文件

### 大文件处理
如果文件很大：
- 会自动截断到 max_lines
- 提示总行数
- 建议读取特定部分

## 示例

### 示例 1：读取配置文件
read_file(path="config.json")

### 示例 2：查看项目结构
list_files(directory="app/core")

### 示例 3：读取大文件（限制行数）
read_file(path="logs/app.log", max_lines=100)

## 注意事项

- ⚠️ 不能访问项目目录外的文件
- ⚠️ 二进制文件可能显示乱码
- ⚠️ 大文件会被自动截断
- 💡 支持相对路径和绝对路径
- 💡 自动处理路径分隔符（Windows/Linux）


---

### 知识检索

**Name**: knowledge_search
**Category**: system
**Scenario**: 需要查找相关代码、理解模块关系、定位功能实现时

# 知识检索

## 技能描述

在 2 万行代码库中进行语义搜索，快速定位相关代码和功能实现。

## 核心能力

- 语义理解：不只是关键词匹配，理解查询意图
- 智能排序：按相关度排序结果
- 上下文提供：返回代码片段和位置信息
- 快速定位：从海量代码中找到关键部分

## 使用场景

### 1. 查找功能实现
"文件上传功能在哪里实现的？"

### 2. 理解模块关系
"Worker 和 Agent 是如何交互的？"

### 3. 定位错误处理
"错误报告是如何生成的？"

### 4. 探索未知代码
"这个项目有哪些 Skills？"

## 工作流程

1. **理解查询**：分析用户的搜索意图
2. **语义匹配**：在代码库中搜索相关内容
3. **排序结果**：按相关度排序
4. **返回上下文**：提供代码片段和位置
5. **建议下一步**：推荐进一步探索的方向

## 使用原则

1. **具体查询**：描述清楚要找什么
2. **关键词准确**：使用代码中可能出现的术语
3. **迭代搜索**：根据结果调整查询
4. **结合阅读**：搜索后用 read_file 查看完整代码
5. **验证理解**：确认找到的代码是否符合预期

## 常见模式

### 模式 1：查找功能
查询："文件保存功能"
结果：FileService.save_code 方法

### 模式 2：理解流程
查询："消息处理流程"
结果：WorkerThread.run → process_batch → save_code

### 模式 3：定位问题
查询："Docker 执行超时"
结果：DockerManager.execute_code 的超时处理

### 模式 4：探索架构
查询："Skills 系统架构"
结果：SkillsManager, BaseSkill, SkillLoader

## 查询技巧

### 技巧 1：使用功能描述
好："处理 AI 回复的代码"
差："代码"

### 技巧 2：使用类名或方法名
好："AgentManager 的工具方法"
差："工具"

### 技巧 3：使用场景描述
好："当用户点击修复按钮时"
差："修复"

### 技巧 4：组合关键词
好："Docker 沙盒 超时控制"
差："Docker"

## 示例

### 示例 1：查找类
knowledge_search(query="SkillsManager 类的实现")

### 示例 2：查找功能
knowledge_search(query="如何执行 Python 代码")

### 示例 3：理解流程
knowledge_search(query="从用户输入到 AI 回复的完整流程")

### 示例 4：定位问题
knowledge_search(query="文件保存失败的错误处理")

## 注意事项

- 💡 搜索结果默认返回 Top 5
- 💡 结果包含文件路径和代码片段
- 💡 可以多次搜索，逐步缩小范围
- 💡 搜索后建议用 read_file 查看完整代码
- ⚠️ 搜索不到可能是关键词不准确
- ⚠️ 代码库需要先建立索引


---

