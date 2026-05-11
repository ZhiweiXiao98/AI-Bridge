# Tavily 搜索适配器（AI 优化，免费 1000 次/月）
import logging
from typing import List
from .base import SearchProvider, SearchResult

logger = logging.getLogger(__name__)


class TavilyProvider(SearchProvider):
    '''Tavily 搜索（AI 优化结果，需 API key）'''

    def is_available(self) -> bool:
        api_key = self.config.get("api_key", "")
        if not api_key:
            return False
        try:
            from tavily import TavilyClient
            return True
        except ImportError:
            return False

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        from tavily import TavilyClient

        api_key = self.config.get("api_key", "")
        if not api_key:
            raise ValueError("Tavily API key 未配置")

        client = TavilyClient(api_key=api_key)
        results = []
        try:
            response = client.search(query, max_results=max_results)
            for r in response.get('results', []):
                results.append(SearchResult(
                    title=r.get('title', ''),
                    url=r.get('url', ''),
                    snippet=r.get('content', '')[:500],
                    content=r.get('content', ''),
                ))
        except Exception as e:
            logger.warning(f"Tavily 搜索失败: {e}")
            raise

        return results
