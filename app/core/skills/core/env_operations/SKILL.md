---
name: env_operations
display_name: Python 环境感知与包管理
category: system
scenario: 需要了解当前 Python 环境状态、检查依赖是否安装、安装缺失包时
version: 1.0.0
author: System
dangerous: true
enabled: true
summary: >
  感知当前 Python 运行环境，查看已安装包，对比 requirements.txt，安装缺失依赖。
  支持操作：env_info（环境信息）、list_packages（列出包，支持 search 过滤）、
  check_package（检查单个包版本）、check_requirements（对比 requirements.txt）、
  install_package（安装包，必须传 confirm=true 才执行）。
  调用格式：tool_call { "name": "env_operations", "arguments": { "operation": "操作名", ...参数 } }
---

# env_operations — Python 环境感知与包管理

## 技能描述

感知当前 Python 运行环境，查看已安装包，对比 requirements.txt，以及安装缺失依赖。

## 支持的操作

| operation | 说明 | 是否需要 confirm |
|---|---|---|
| `env_info` | Python 版本、解释器路径、是否虚拟环境、平台 | 否 |
| `list_packages` | 列出已安装的所有包（支持 `search` 关键词过滤） | 否 |
| `check_package` | 检查单个包是否安装及版本 | 否 |
| `check_requirements` | 对比 requirements.txt，列出缺失包 | 否 |
| `install_package` | 安装指定包（需 `confirm=True`） | ✅ 是 |

## 参数说明

- `operation` (str, 必需): 操作类型，见上表
- `package` (str, 可选): 包名，`check_package` / `install_package` 时使用
- `version` (str, 可选): 版本约束，`install_package` 时可选，如 `>=2.0.0` 或 `==1.9.3`
- `search` (str, 可选): 关键词过滤，`list_packages` 时使用
- `req_path` (str, 可选): requirements 文件路径，`check_requirements` 时可选，默认自动查找项目根目录
- `confirm` (bool, 可选): 危险操作二次确认，`install_package` 必须传 `true` 才会执行

## 使用示例

```
# 查看环境基本信息
env_operations(operation="env_info")

# 列出所有已安装包
env_operations(operation="list_packages")

# 按关键词过滤
env_operations(operation="list_packages", search="pyside")

# 检查单个包
env_operations(operation="check_package", package="fastapi")

# 对比 requirements.txt
env_operations(operation="check_requirements")

# 对比指定文件
env_operations(operation="check_requirements", req_path="requirements_client.txt")

# 安装包（不带 confirm，返回确认提示）
env_operations(operation="install_package", package="httpx")

# 安装包（确认执行）
env_operations(operation="install_package", package="httpx", version=">=0.28.0", confirm=True)
```

## 注意事项

- 安装操作使用项目执行环境指定的 Python（`sandbox_local_python` 或 `AI_BRIDGE_PYTHON`）；打包应用自动识别项目 `.venv`，缺少外部 Python 时提示配置，绝不把应用程序本身作为 pip 运行。源码模式未配置时使用当前解释器。
- `check_requirements` 只做对比，不自动安装，由 AI 决定后续动作
- `install_package` 属于危险操作，未传 `confirm=True` 时只返回提示，不执行
