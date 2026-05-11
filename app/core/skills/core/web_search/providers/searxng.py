# SearXNG 搜索适配器（自建实例，无限额度）
import logging
import urllib.request
import urllib.parse
import json
from typing import List
from .base import SearchProvider, SearchResult

logger = logging.getLogger(__name__)


class SearXNGProvider(SearchProvider):
    '''SearXNG 自建搜索（需部署 SearXNG Docker 实例）'''

    def is_available(self) -> bool:
        base_url = self.config.get("base_url", "")
        if not base_url:
            return False
        try:
            req = urllib.request.Request(base_url, method="HEAD")
            urllib.request.urlopen(req, timeout=3)
            return True
        except Exception:
            return False

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        base_url = self.config.get("base_url", "").rstrip("/")
        if not base_url:
            raise ValueError("SearXNG base_url 未配置")

        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "categories": "general",
            "language": "auto",
        })
        url = f"{base_url}/search?{params}"

        results = []
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for r in data.get("results", [])[:max_results]:
                results.append(SearchResult(
                    title=r.get('title', ''),
                    url=r.get('url', ''),
                    snippet=r.get('content', ''),
                ))
        except Exception as e:
            logger.warning(f"SearXNG 搜索失败: {e}")
            raise

        return results
