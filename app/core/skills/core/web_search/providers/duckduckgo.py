# DuckDuckGo 搜索适配器（免费，无需 API key）
import logging
from typing import List
from .base import SearchProvider, SearchResult

logger = logging.getLogger(__name__)


class DuckDuckGoProvider(SearchProvider):
    '''DuckDuckGo 搜索（免费，偶尔限流）'''

    def is_available(self) -> bool:
        try:
            from ddgs import DDGS
            return True
        except ImportError:
            return False

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        from ddgs import DDGS

        results = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(SearchResult(
                        title=r.get('title', ''),
                        url=r.get('href', ''),
                        snippet=r.get('body', ''),
                    ))
        except Exception as e:
            logger.warning(f"DuckDuckGo 搜索失败: {e}")
            raise

        return results
