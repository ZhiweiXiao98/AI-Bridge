import os
import json
from dataclasses import dataclass, field
from typing import Optional

from app.core.app_constants import DEFAULT_API_BASE_URL, DEFAULT_API_MODEL, DEFAULT_API_MODEL_LITE
from app.core.logging import get_logger

logger = get_logger("app.core.daemon.daemon_config", side="worker")

_DAEMON_CONFIG_KEY = "daemon"

_DAEMON_CONFIG_KEY = "daemon"

_DEFAULT_DAEMON_CONFIG = {
    "enabled": True,
    "core": {
        "type": "profile",
        "ref": "default"
    },
    "lite": {
        "type": "profile",
        "ref": "default"
    },
    "tasks": {
        "suggest": {
            "enabled": True,
            "trigger": "event",
            "model_tier": "lite",
            "max_suggestions": 3,
            "reply_max_chars": 500,
            "context_max_turns": 3,
        },
    },
}


@dataclass
class ModelTierConfig:
    model: str = DEFAULT_API_MODEL_LITE
    max_output_tokens: int = 1024
    temperature: float = 0.3


@dataclass
class SuggestTaskConfig:
    enabled: bool = True
    trigger: str = "event"
    model_tier: str = "lite"
    max_suggestions: int = 3
    auto_dismiss_seconds: int = 8
    reply_max_chars: int = 500
    context_max_turns: int = 3


@dataclass
class DaemonConfigData:
    enabled: bool = True
    provider: str = "openai_compatible"
    api_key: str = ""
    base_url: str = DEFAULT_API_BASE_URL
    proxy_url: str = ""
    models: dict = field(default_factory=lambda: {
        "lite": ModelTierConfig(),
        "core": ModelTierConfig(model=DEFAULT_API_MODEL, max_output_tokens=2048, temperature=0.5),
    })
    tasks: dict = field(default_factory=dict)


class DaemonConfig:
    _instance: Optional["DaemonConfig"] = None

    def __init__(self):
        self._data = self._load()
        self.suggest = self._parse_suggest()

    @classmethod
    def get(cls) -> "DaemonConfig":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reload(cls) -> "DaemonConfig":
        cls._instance = cls()
        return cls._instance

    @property
    def enabled(self) -> bool:
        return self._data.enabled

    @property
    def provider(self) -> str:
        return self._data.provider

    @property
    def api_key(self) -> str:
        return self._data.api_key

    @property
    def base_url(self) -> str:
        return self._data.base_url

    @property
    def proxy_url(self) -> str:
        return self._data.proxy_url

    def get_model_tier(self, tier: str) -> ModelTierConfig:
        raw = self._data.models.get(tier, {})
        if isinstance(raw, ModelTierConfig):
            return raw
        return ModelTierConfig(
            model=raw.get("model", DEFAULT_API_MODEL_LITE),
            max_output_tokens=raw.get("max_output_tokens", 1024),
            temperature=raw.get("temperature", 0.3),
        )

    def _load(self) -> DaemonConfigData:
        """从 config.json 加载守护进程配置，通过 profile_ref 引用 API 配置"""
        config_path = "config.json"
        if not os.path.exists(config_path):
            return DaemonConfigData()
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                root = json.load(f)
            raw = root.get(_DAEMON_CONFIG_KEY, {})
            if not raw:
                return DaemonConfigData()
            
            # 加载 API 配置
            from app.core.api_mode_config import APIModeConfigManager
            api_config = APIModeConfigManager.load()
            
            # 解析 Core 模型配置
            core_config = raw.get("core", {})
            core_type = core_config.get("type", "profile")
            core_ref = core_config.get("ref", "default")
            core_profile = self._resolve_profile(api_config, core_type, core_ref)
            
            # 解析 Lite 模型配置
            lite_config = raw.get("lite", {})
            lite_type = lite_config.get("type", "profile")
            lite_ref = lite_config.get("ref", "default")
            lite_profile = self._resolve_profile(api_config, lite_type, lite_ref)
            
            if not core_profile or not lite_profile:
                logger.warning("守护进程配置引用的 Profile 不存在，使用默认配置")
                return DaemonConfigData()
            
            # 构建 models 配置
            models = {
                "core": ModelTierConfig(
                    model=core_profile.get("model", DEFAULT_API_MODEL),
                    max_output_tokens=core_profile.get("max_output_tokens", 2048),
                    temperature=core_profile.get("temperature", 0.5),
                ),
                "lite": ModelTierConfig(
                    model=lite_profile.get("model", DEFAULT_API_MODEL_LITE),
                    max_output_tokens=lite_profile.get("max_output_tokens", 1024),
                    temperature=lite_profile.get("temperature", 0.3),
                ),
            }
            
            # 使用 Core 的 API 配置作为主配置
            return DaemonConfigData(
                enabled=raw.get("enabled", True),
                provider=core_profile.get("provider", "openai_compatible"),
                api_key=core_profile.get("api_key", ""),
                base_url=core_profile.get("base_url", DEFAULT_API_BASE_URL),
                proxy_url=core_profile.get("proxy_url", ""),
                models=models,
                tasks=raw.get("tasks", {}),
            )
        except Exception as e:
            logger.warning("守护进程配置加载失败，使用默认值: %s", e)
            return DaemonConfigData()
    
    def _resolve_profile(self, api_config: dict, ref_type: str, ref: str) -> dict:
        """解析 Profile 或 Chain 引用，返回第一个可用的 Profile"""
        if ref_type == "profile":
            return api_config.get("profiles", {}).get(ref, {})
        elif ref_type == "chain":
            chain = api_config.get("fallback_chains", {}).get(ref, [])
            if chain:
                # 返回 Chain 中第一个 Profile
                first_profile_ref = chain[0] if isinstance(chain, list) else None
                if first_profile_ref:
                    return api_config.get("profiles", {}).get(first_profile_ref, {})
        return {}

    def _parse_suggest(self) -> SuggestTaskConfig:
        raw = self._data.tasks.get("suggest", _DEFAULT_DAEMON_CONFIG["tasks"]["suggest"])
        return SuggestTaskConfig(
            enabled=raw.get("enabled", True),
            trigger=raw.get("trigger", "event"),
            model_tier=raw.get("model_tier", "lite"),
            max_suggestions=raw.get("max_suggestions", 3),
            auto_dismiss_seconds=0,  # 已废弃，保留字段以兼容旧代码
            reply_max_chars=raw.get("reply_max_chars", 500),
            context_max_turns=raw.get("context_max_turns", 3),
        )
