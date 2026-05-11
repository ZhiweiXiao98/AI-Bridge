---
name: web_search
display_name: 网络搜索
category: network
description: 在互联网上搜索信息，获取最新资料
scenario: 需要查找最新信息、技术文档、API 用法、错误解决方案时
version: 1.0.0
author: System
dangerous: false
enabled: true
---

# 网络搜索

## 技能描述

在互联网上搜索信息，获取最新技术文档、API 用法、错误解决方案等。

## 核心能力

- 多源搜索：支持 DuckDuckGo、Tavily、SearXNG 等多个搜索引擎
- 自动降级：某个引擎不可用时自动切换到下一个
- 结果优化：自动截断过长内容，适配 AI 上下文窗口
- 零配置启动：安装 duckduckgo-search 即可使用

## 使用场景

### 1. 查找技术文档
搜索某个库或框架的最新用法

### 2. 错误排查
搜索报错信息，找到解决方案

### 3. 获取最新信息
查找最新版本、更新日志、安全公告等

### 4. API 用法
搜索第三方 API 的调用方式和参数说明

## 搜索提供商

| 提供商 | 费用 | 配置 | 特点 |
| :--- | :--- | :--- | :--- |
| DuckDuckGo | 免费 | `pip install duckduckgo-search` | 零配置，偶尔限流 |
| Tavily | 免费 1000次/月 | 需 API key | AI 优化结果，质量最好 |
| SearXNG | 免费（自建） | 需部署 Docker 实例 | 无限额度，多源聚合 |

## 降级策略

按 `config/search_config.json` 中的 `provider_chain` 顺序尝试：
1. 优先使用排在前面的提供商
2. 如果失败（限流/网络错误/额度用完），自动切换下一个
3. 所有提供商都失败时返回错误提示

## 配置说明

编辑 `config/search_config.json`：

```json
{
  "provider_chain": ["tavily", "duckduckgo", "searxng"],
  "max_results": 5,
  "max_snippet_length": 500,
  "providers": {
    "tavily": {"api_key": "tvly-xxxxx"},
    "duckduckgo": {},
    "searxng": {"base_url": "http://localhost:8888"}
  }
}
```

## 示例

### 示例 1：搜索技术文档
web_search(query="Python asyncio tutorial")

### 示例 2：搜索错误解决方案
web_search(query="ChromaDB PySide6 shibokensupport conflict")

### 示例 3：限制结果数
web_search(query="FastAPI WebSocket reconnect", max_results=3)

## 注意事项

- 💡 首次使用需安装至少一个搜索依赖
- 💡 Tavily 需要在 tavily.com 注册获取 API key
- 💡 SearXNG 需要自行部署 Docker 实例
- ⚠️ 搜索结果来自互联网，需要验证准确性
- ⚠️ 注意搜索频率，避免被限流
