# web_search skill - 网络搜索能力
import logging
from typing import Any
from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter

logger = logging.getLogger(__name__)


class WebSearchSkill(BaseSkill):
    '''网络搜索 Skill（自动降级链）'''

    def __init__(self):
        super().__init__()
        self._chain = None

    @property
    def chain(self):
        '''懒加载搜索链'''
        if self._chain is None:
            from .config import SearchChain
            self._chain = SearchChain()
        return self._chain

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="web_search",
            display_name="网络搜索",
            category="network",
            description="在互联网上搜索信息，获取最新资料",
            scenario="需要查找最新信息、技术文档、API 用法、错误解决方案时",
            version="1.0.0",
            author="System",
            parameters=[
                SkillParameter(
                    name="query",
                    type="str",
                    required=True,
                    description="搜索关键词"
                ),
                SkillParameter(
                    name="max_results",
                    type="int",
                    required=False,
                    description="最大结果数",
                    default=5
                )
            ],
            examples=[
                'web_search(query="Python asyncio tutorial")',
                'web_search(query="FastAPI WebSocket 断线重连", max_results=3)',
            ],
            dangerous=False
        )

    def _get_parameters_schema(self) -> dict:
        return {
            "query": {
                "type": "string",
                "description": "搜索关键词"
            },
            "max_results": {
                "type": "integer",
                "description": "最大结果数，默认 5",
                "default": 5
            }
        }

    def _get_required_parameters(self) -> list:
        return ["query"]

    def execute(self, query: str, max_results: int = 5, **kwargs) -> Any:
        '''执行网络搜索'''
        if not self.chain.providers:
            return (
                "❌ 无可用搜索提供商。请安装搜索依赖:\n"
                "  pip install duckduckgo-search  (免费，推荐)\n"
                "  pip install tavily-python       (需 API key)\n"
                "或在 config/search_config.json 中配置 SearXNG 地址"
            )

        results = self.chain.search(query, max_results)

        if not results:
            return f"未找到与 '{query}' 相关的结果"

        # 格式化输出
        lines = [f"🌐 搜索结果: {query}", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r.title}")
            lines.append(f"🔗 {r.url}")
            lines.append(f"{r.snippet}")
            lines.append("")

        return "\n".join(lines)


__skill__ = WebSearchSkill
