# filename: app/core/skills/core/knowledge_search/skill.py
import time
from typing import Any
from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter
from app.core.logging import get_logger

logger = get_logger("app.core.skills.knowledge_search", side="worker")

class KnowledgeSearchSkill(BaseSkill):
    '''知识检索 Skill'''

    def __init__(self, knowledge_engine=None):
        super().__init__()
        self.knowledge_engine = knowledge_engine

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="knowledge_search",
            display_name="知识检索",
            category="system",
            description="在项目代码库中进行语义搜索",
            scenario="需要查找相关代码、理解模块关系、定位功能实现时",
            version="1.1.0",
            author="System",
            parameters=[
                SkillParameter(
                    name="query",
                    type="str",
                    required=True,
                    description="搜索查询（描述要找的内容）"
                ),
                SkillParameter(
                    name="top_k",
                    type="int",
                    required=False,
                    description="返回结果数量",
                    default=5
                )
            ],
            examples=[
                "knowledge_search(query='文件保存功能的实现')",
                "knowledge_search(query='Docker 执行代码的流程', top_k=3)"
            ],
            dangerous=False
        )

    def _get_parameters_schema(self) -> dict:
        return {
            "query": {
                "type": "string",
                "description": "搜索查询，描述要查找的内容"
            },
            "top_k": {
                "type": "integer",
                "description": "返回结果数量，默认 5",
                "default": 5
            }
        }

    def _get_required_parameters(self) -> list:
        return ["query"]

    def _do_search(self, query: str, top_k: int, task_meta=None) -> str:
        return self.knowledge_engine.search_context(query, top_k=top_k, task_meta=task_meta)

    def execute(self, query: str, top_k: int = 5, **kwargs) -> Any:
        '''执行知识检索（统一走 KnowledgeExecutor，可观测，不做 skill 层硬超时）'''
        _tool_task_meta = kwargs.get('_tool_task_meta')
        if not self.knowledge_engine:
            return "❌ Error: 知识引擎不可用"

        v2 = getattr(self.knowledge_engine, '_v2', None)
        if v2:
            health = v2.get_health()
            if health.get("state") == "failed":
                logger.warning("知识检索处于 failed 状态，尝试恢复: path=%s last_error=%s",
                             health.get("active_path"), health.get("last_error", "")[:80])
                recovery = v2.try_recover_main_path()
                if recovery.get("recovered"):
                    logger.info("知识检索路径已恢复: %s -> %s", recovery["old_path"], recovery["new_path"])

        if _tool_task_meta:
            logger.debug(
                "knowledge_search 收到任务上下文 tool_call_id=%s conversation_id=%s",
                getattr(_tool_task_meta, 'tool_call_id', ''),
                getattr(_tool_task_meta, 'conversation_id', ''),
            )

        t0 = time.time()
        try:
            result = self._do_search(query, top_k, _tool_task_meta)
            elapsed = time.time() - t0
            logger.info("knowledge_search 完成 (%.1fms) query_len=%d", elapsed * 1000, len(query))
            return result
        except Exception as e:
            elapsed = time.time() - t0
            logger.error("knowledge_search 异常: %s (%.1fms)", e, elapsed * 1000)
            return f"❌ 搜索失败: {str(e)}"


__skill__ = KnowledgeSearchSkill
