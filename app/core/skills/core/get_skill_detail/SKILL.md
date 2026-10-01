---
name: get_skill_detail
display_name: 查看 Skill 完整文档
category: system
description: 按需获取指定 Skill 的完整参数说明、示例和注意事项
scenario: 对某个 skill 的参数或用法不确定时，调用此工具获取完整文档
version: 1.0.0
author: System
dangerous: false
enabled: true
summary: >-
  按需获取指定 skill 的完整文档（参数说明、示例、注意事项）。
  系统提示词默认为摘要版以节省 token，遇到不熟悉的 skill 时调用此工具查看全量文档。
  调用格式：tool_call { "name": "get_skill_detail", "arguments": { "skill_name": "skill名称" } }
---

# 查看 Skill 完整文档

## 技能描述

系统提示词默认使用摘要版以节省 token。当你对某个 skill 的参数、用法或注意事项不确定时，
调用此工具按需获取该 skill 的完整文档，包含所有参数说明、使用示例和注意事项。

## 参数说明

- `skill_name` (str, 必需): 要查询的 skill 名称，与系统提示词中 **Name** 字段完全一致

## 使用示例

```
# 查看 file_operations 完整文档
get_skill_detail(skill_name="file_operations")

# 查看 git_operations 完整文档
get_skill_detail(skill_name="git_operations")
```

## 可查询的 Skill 名称

从系统提示词的 `**Name**: xxx` 字段获取，例如：
`code_execution` / `env_operations` / `file_operations` / `git_operations` / `journal_search` / `knowledge_search` / `web_search`

## 注意事项

- 💡 只需在首次使用某个不熟悉的 skill 前调用一次，后续调用不必重复查询
- 💡 返回内容为该 skill 的 SKILL.md 全量正文
- ⚠️ skill_name 必须与系统提示词中的 Name 字段完全一致，区分大小写

---
