---
name: journal_search
display_name: 行驶记录查询
category: system
description: 按需查询 AI_JOURNAL 行驶记录和完整历史归档，返回标题、片段或指定条目
scenario: 需要追溯项目历史决策、Bug 修复记录、用户约束、长期记忆证据时
version: 1.0.0
author: System
dangerous: false
enabled: true
summary: >
  查询 AI_JOURNAL 行驶记录，不再要求 AI 直接读取超大日志文件。
  支持 search/latest/index/entry/stats 五种模式，可按关键词、日期、标题定位历史记录。
  默认限制返回长度，避免把完整归档一次性灌入上下文。
  调用格式：tool_call { "name": "journal_search", "arguments": { "mode": "search", "query": "项目切换" } }
---

# 行驶记录查询

## 技能描述

`journal_search` 用于查询项目权威行驶记录：

- 当前轻量入口：`AI_JOURNAL.md`
- 完整历史归档：`docs/归档/AI行驶记录完整归档_2026-06-20.md`
- 归档索引：`docs/归档/AI行驶记录完整归档索引_2026-06-20.md`

它的目标是让 AI 按需调用日志信息，而不是直接读取超大 Markdown 文件。

## 参数说明

- `mode` (str, 可选): 查询模式，默认 `search`
  - `search`: 关键词搜索，返回命中片段
  - `latest`: 返回最近的记录标题
  - `index`: 返回标题索引，可配合日期范围和关键词过滤
  - `entry`: 返回指定标题或日期附近的一整条记录片段
  - `stats`: 返回 journal 文件体量和记录数量
- `query` (str, 可选): 搜索关键词；`search` 模式建议必填
- `date_from` (str, 可选): 起始日期，格式 `YYYY-MM-DD`
- `date_to` (str, 可选): 结束日期，格式 `YYYY-MM-DD`
- `limit` (int, 可选): 返回条数，默认 8，最大 30
- `source` (str, 可选): 数据源，默认 `all`
  - `current`: 只查当前轻量 `AI_JOURNAL.md`
  - `archive`: 只查完整历史归档
  - `all`: 当前入口和完整归档都查
- `max_chars` (int, 可选): 单次返回最大字符数，默认 8000，最大 20000

## 使用示例

```text
journal_search(mode="search", query="项目切换")
journal_search(mode="latest", limit=10)
journal_search(mode="index", date_from="2026-05-01", date_to="2026-05-31", query="浏览器")
journal_search(mode="entry", query="UI 热切换项目")
journal_search(mode="stats")
```

## 使用原则

1. 先用 `search` 或 `index` 定位，再用 `entry` 拉取具体记录。
2. 不要一次性要求返回完整归档。
3. 查当前项目事实优先读 `docs/当前项目状态.md`；查历史证据再用本工具。
