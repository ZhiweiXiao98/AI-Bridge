# web_search 配置与降级链
import os
import json
import logging
from typing import List, Optional
from .providers.base import SearchProvider, SearchResult

logger = logging.getLogger(__name__)

# 默认配置路径
DEFAULT_CONFIG_PATH = "config/search_config.json"

# 默认配置
DEFAULT_CONFIG = {
    "provider_chain": ["tavily", "duckduckgo", "searxng"],
    "max_results": 5,
    "max_snippet_length": 500,
    "providers": {
        "tavily": {"api_key": ""},
        "duckduckgo": {},
        "searxng": {"base_url": ""}
    }
}


def load_search_config() -> dict:
    '''加载搜索配置，不存在则创建默认配置'''
    if os.path.exists(DEFAULT_CONFIG_PATH):
        try:
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载搜索配置失败: {e}，使用默认配置")
    return DEFAULT_CONFIG.copy()


def save_default_config():
    '''保存默认配置文件（首次使用时）'''
    os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH), exist_ok=True)
    if not os.path.exists(DEFAULT_CONFIG_PATH):
        with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        logger.info(f"已创建默认搜索配置: {DEFAULT_CONFIG_PATH}")


def create_provider(name: str, config: dict) -> Optional[SearchProvider]:
    '''根据名称创建 provider 实例'''
    try:
        if name == "duckduckgo":
            from .providers.duckduckgo import DuckDuckGoProvider
            return DuckDuckGoProvider(config)
        elif name == "tavily":
            from .providers.tavily import TavilyProvider
            return TavilyProvider(config)
        elif name == "searxng":
            from .providers.searxng import SearXNGProvider
            return SearXNGProvider(config)
        else:
            logger.warning(f"未知的搜索提供商: {name}")
            return None
    except Exception as e:
        logger.warning(f"创建 {name} provider 失败: {e}")
        return None


class SearchChain:
    '''搜索降级链：按优先级尝试，失败自动切换下一个'''

    def __init__(self):
        self.config = load_search_config()
        self.providers: List[SearchProvider] = []
        self._init_chain()

    def _init_chain(self):
        '''按配置的优先级初始化 provider 链'''
        chain = self.config.get("provider_chain", ["duckduckgo"])
        providers_config = self.config.get("providers", {})

        for name in chain:
            provider_conf = providers_config.get(name, {})
            provider = create_provider(name, provider_conf)
            if provider and provider.is_available():
                self.providers.append(provider)
                logger.info(f"[SearchChain] ✅ {name} 已就绪")
            else:
                reason = "未安装依赖" if provider and not provider.is_available() else "创建失败"
                if provider and name == "tavily" and not providers_config.get(name, {}).get("api_key"):
                    reason = "未配置 API key"
                elif provider and name == "searxng" and not providers_config.get(name, {}).get("base_url"):
                    reason = "未配置 base_url"
                logger.info(f"[SearchChain] ⏭️ {name} 跳过（{reason}）")

        if not self.providers:
            logger.warning("[SearchChain] ⚠️ 无可用搜索提供商")

    def search(self, query: str, max_results: int = None) -> List[SearchResult]:
        '''执行搜索，自动降级'''
        if max_results is None:
            max_results = self.config.get("max_results", 5)

        max_snippet = self.config.get("max_snippet_length", 500)

        for provider in self.providers:
            try:
                logger.debug(f"[SearchChain] 尝试 {provider.name}...")
                results = provider.search(query, max_results)
                # 截断 snippet
                for r in results:
                    if r.snippet and len(r.snippet) > max_snippet:
                        r.snippet = r.snippet[:max_snippet] + "..."
                logger.info(f"[SearchChain] {provider.name} 返回 {len(results)} 条结果")
                return results
            except Exception as e:
                logger.warning(f"[SearchChain] {provider.name} 失败: {e}，尝试下一个")
                continue

        return []

    def get_status(self) -> str:
        '''获取所有 provider 状态'''
        if not self.providers:
            return "⚠️ 无可用搜索提供商，请安装 duckduckgo-search 或配置其他 provider"
        lines = [f"✅ {p.name}" for p in self.providers]
        return "可用提供商: " + ", ".join(lines)
