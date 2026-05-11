---
name: code_execution
display_name: 代码执行
category: code
description: 在 Docker 沙盒中安全执行 Python 代码
scenario: 需要验证代码逻辑、测试功能、诊断问题时
version: 1.0.0
author: System
dangerous: true
enabled: true
---

# 代码执行

## ⚠️ 重要：必须添加 # EXEC 标记

**代码默认不会执行！** 必须在代码块开头添加 `# EXEC` 标记才会执行：

```python
# EXEC
print("这段代码会被执行")
```

不加标记的代码只会被当作示例展示：

```python
print("这段代码不会被执行")
```

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
