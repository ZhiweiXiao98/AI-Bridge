from typing import List, Optional

from app.core.llm_provider import APIProvider, GeminiProvider, ProviderConfig
from app.core.daemon.daemon_config import DaemonConfig, ModelTierConfig
from app.core.logging import get_logger

logger = get_logger("app.core.daemon.daemon_llm", side="worker")


class DaemonLLMRouter:
    _providers: dict

    def __init__(self, config: Optional[DaemonConfig] = None):
        self._config = config or DaemonConfig.get()
        self._providers = {}
        logger.info(
            "[DaemonLLM] 初始化: provider=%s base_url=%s api_key=%s lite_model=%s core_model=%s",
            getattr(self._config, 'provider', ''),
            getattr(self._config, 'base_url', ''),
            bool(getattr(self._config, 'api_key', '') or ''),
            getattr(self._config.get_model_tier('lite'), 'model', '') if hasattr(self._config, 'get_model_tier') else '',
            getattr(self._config.get_model_tier('core'), 'model', '') if hasattr(self._config, 'get_model_tier') else '',
        )
        self._init_providers()
        logger.info("[DaemonLLM] 初始化完成: available=%s providers=%s", self.available, list(self._providers.keys()))

    def _create_provider(self, tier_cfg: ModelTierConfig):
        provider_cfg = ProviderConfig(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            model=tier_cfg.model,
            max_output_tokens=tier_cfg.max_output_tokens,
            temperature=tier_cfg.temperature,
            proxy_url=self._config.proxy_url,
            timeout=30,
        )
        logger.info(
            "[DaemonLLM] 创建 provider: provider=%s model=%s max_output_tokens=%s temperature=%s",
            self._config.provider,
            tier_cfg.model,
            tier_cfg.max_output_tokens,
            tier_cfg.temperature,
        )
        if self._config.provider == "gemini":
            return GeminiProvider(provider_cfg)
        return APIProvider(provider_cfg)

    def _init_providers(self):
        if not self._config.api_key:
            logger.warning("[DaemonLLM] API key 未配置，LLM 路由器不可用")
            return
        for tier_name in ("lite", "core"):
            tier_cfg = self._config.get_model_tier(tier_name)
            try:
                self._providers[tier_name] = self._create_provider(tier_cfg)
                logger.info(
                    "[DaemonLLM] provider 初始化成功: tier=%s model=%s base_url=%s provider=%s",
                    tier_name, tier_cfg.model, self._config.base_url, self._config.provider,
                )
            except Exception as e:
                logger.warning("[DaemonLLM] provider 初始化失败: tier=%s error=%s", tier_name, e)

    @property
    def available(self) -> bool:
        available = bool(self._providers)
        logger.info("[DaemonLLM] available 检查: %s", available)
        return available

    def chat(self, messages: List[dict], tier: str = "lite") -> Optional[str]:
        logger.info("[DaemonLLM] chat 请求: tier=%s messages=%d", tier, len(messages or []))
        provider = self._providers.get(tier)
        if not provider:
            fallback = self._providers.get("lite") or self._providers.get("core")
            if not fallback:
                logger.warning("[DaemonLLM] 无可用 provider")
                return None
            provider = fallback
            logger.info("[DaemonLLM] 降级 provider: %s -> fallback", tier)
        try:
            result = provider.chat(messages)
            logger.info("[DaemonLLM] chat 完成: tier=%s result_len=%d", tier, len(result or ""))
            return result
        except Exception as e:
            logger.warning("[DaemonLLM] 调用失败: tier=%s error=%s", tier, e)
            return None
