import json
import re
from typing import Optional
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("app.core.services.doc_analyzer_service", side="worker")

ANALYSIS_SYSTEM_PROMPT = """\
你是一个文档分析助手。你的任务是分析一份 Markdown 计划书/方案书，输出结构化的 JSON，用于生成高质量的 HTML 交付展示页。

## 输入
一份 Markdown 文档的原始内容。

## 输出
严格输出以下 JSON 格式，不要输出其他内容：

```json
{
  "title": "文档标题",
  "subtitle": "一句话概括文档的核心目的",
  "badge": {
    "status": "进行中|已完成|已废弃",
    "date": "2026-05-16"
  },
  "phases": [
    {"label": "第一阶段 · xxx", "status": "doing|done|todo"},
    {"label": "第二阶段 · xxx", "status": "todo"}
  ],
  "sections": [
    {
      "id": "background",
      "title": "背景",
      "icon": "📋",
      "summary": "1-2句话概括本节核心内容",
      "key_points": ["要点1", "要点2"],
      "display_hint": "cards|flow|checklist|table|text"
    }
  ],
  "flow_diagrams": [
    {
      "section_id": "techchain",
      "title": "技术链路",
      "nodes": ["节点1", "节点2", "节点3"]
    }
  ],
  "acceptance_criteria": ["标准1", "标准2"],
  "conclusion_highlights": ["更易读", "更易讲解"],
  "risks": ["风险1", "风险2"]
}
```

## 规则
1. `sections` 必须覆盖文档的所有二级标题
2. `icon` 从以下选择：📋🎯📐🔗🏗️⚡🧩⚙️⚠️🚫🗓️✅💡📖🔢📝🧪📊🔍❓🔧🚀
3. `display_hint` 决定渲染方式：
   - `cards`：信息卡片（默认）
   - `flow`：流程/架构图
   - `checklist`：待办/检查清单
   - `table`：对比/数据表格
   - `text`：纯文本段落
4. `flow_diagrams` 只在文档包含流程、链路、架构描述时生成
5. `phases` 从文档中提取实施阶段，没有则留空数组
6. `acceptance_criteria` 和 `conclusion_highlights` 从对应章节提取
7. `summary` 必须精炼，不超过50字
8. `key_points` 每节不超过5个
9. 只输出 JSON，不要输出 Markdown 代码块标记
"""


class DocAnalyzerService:
    def __init__(self, llm_router=None):
        self._llm = llm_router

    def analyze(self, md_text: str, filename: str = "") -> Optional[dict]:
        if not self._llm or not getattr(self._llm, 'available', False):
            logger.warning("DocAnalyzer: LLM 不可用，回退到规则解析")
            return None

        truncated = md_text[:8000]
        user_prompt = f"文件名：{filename}\n\n{truncated}"

        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = self._llm.chat(messages, tier="lite")
            if not raw:
                return None
            return self._parse_response(raw)
        except Exception as e:
            logger.warning("DocAnalyzer: LLM 分析失败: %s", e)
            return None

    def _parse_response(self, raw: str) -> Optional[dict]:
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.warning("DocAnalyzer: JSON 解析失败")
                    return None
            else:
                logger.warning("DocAnalyzer: 响应中未找到 JSON")
                return None

        if not isinstance(data, dict) or "sections" not in data:
            logger.warning("DocAnalyzer: JSON 结构不符合预期")
            return None

        return data
