import logging
import json
import os
from copy import deepcopy

from app.core.config import ConfigManager
from app.core.app_constants import APP_ROOT, DEFAULT_API_BASE_URL, DEFAULT_API_MODEL
from app.core.logging import get_logger

logger = get_logger("app.core.api_mode_config", side="worker")

API_MODE_CONFIG_PATH = os.path.join(APP_ROOT, "config", "api_mode.json")
LEGACY_EXPERIMENTAL_PATH = os.path.join(APP_ROOT, "experimental", "config.json")


class APIModeConfigManager:
    @staticmethod
    def _default_config():
        return {
            "version": 1,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "name": "Default",
                    "kind": "api",
                    "provider": "openai_compatible",
                    "api_key": "",
                    "base_url": DEFAULT_API_BASE_URL,
                    "model": DEFAULT_API_MODEL,
                    "temperature": 0.7,
                    "max_output_tokens": 4096,
                    "timeout": 60,
                    "proxy_url": "",
                    "supports_stream": True,
                    "supports_tools": False,
                    "supports_reasoning": False,
                    "reasoning": {
                        "enabled": False,
                        "effort": "medium"
                    }
                }
            },
            "fallback_chains": {},
            "fallback_chain": [],
            "api_mode_usage": {
                "type": "profile",
                "ref": "default"
            },
            "conversation_defaults": {
                "context": {
                    "max_window_tokens": 128000,
                    "system_budget": 8000,
                    "long_term_budget": 4000,
                    "working_budget": 2000,
                    "short_term_budget": 80000,
                    "output_reserve": 16000,
                    "max_history_turns": 50
                },
                "system": {
                    "user_prompt": "",
                    "inject_skills_prompt": True,
                    "inject_system_policy": False
                }
            },
            "agent": {
                "enabled": True,
                "max_steps": 8,
                "auto_execute_tools": True,
                "tool_summary_mode": "compact",
                "allow_tools": [
                    "file_operations",
                    "code_execution",
                    "knowledge_search",
                    "web_search"
                ],
                "retry_count": 1
            }
        }

    @staticmethod
    def _ensure_dirs():
        os.makedirs(os.path.dirname(API_MODE_CONFIG_PATH), exist_ok=True)

    @staticmethod
    def _deep_merge(base, incoming):
        if not isinstance(base, dict) or not isinstance(incoming, dict):
            return incoming
        result = deepcopy(base)
        for k, v in incoming.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = APIModeConfigManager._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    @staticmethod
    def _normalize(config):
        cfg = APIModeConfigManager._deep_merge(APIModeConfigManager._default_config(), config or {})
        profiles = cfg.get("profiles") or {}
        if not profiles:
            cfg["profiles"] = deepcopy(APIModeConfigManager._default_config()["profiles"])
            profiles = cfg["profiles"]
        active = cfg.get("active_profile") or "default"
        if active not in profiles:
            cfg["active_profile"] = next(iter(profiles.keys()))
        for profile in cfg["profiles"].values():
            profile.setdefault("kind", "api")
            profile.setdefault("reasoning", {"enabled": False, "effort": "medium"})
            profile["temperature"] = float(profile.get("temperature", 0.7))
            profile["max_output_tokens"] = int(profile.get("max_output_tokens", 4096))
            profile["timeout"] = int(profile.get("timeout", 60))
        return cfg

    @staticmethod
    def get_active_profile_key(config=None, usage_override=None):
        """Resolve the effective API-mode Profile key.

        usage_override is used for per-conversation model selection. When absent,
        the global api_mode_usage remains the fallback/default source.
        """
        cfg = APIModeConfigManager._normalize(config or APIModeConfigManager.load())
        profiles = cfg.get("profiles", {})
        usage = usage_override if isinstance(usage_override, dict) else (cfg.get("api_mode_usage") or {})
        usage_type = usage.get("type", "profile")
        usage_ref = usage.get("ref", cfg.get("active_profile", "default"))

        if usage_type == "profile" and usage_ref in profiles:
            return usage_ref

        if usage_type == "chain":
            chain = cfg.get("fallback_chains", {}).get(usage_ref, [])
            if isinstance(chain, dict):
                chain = chain.get("profiles", [])
            if isinstance(chain, list):
                for profile_key in chain:
                    if profile_key in profiles:
                        return profile_key

        active = cfg.get("active_profile", "default")
        return active if active in profiles else next(iter(profiles.keys()))

    @staticmethod
    def _load_json(path):
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _build_from_legacy():
        cfg = APIModeConfigManager._default_config()
        legacy = APIModeConfigManager._load_json(LEGACY_EXPERIMENTAL_PATH) or {}
        profile = cfg["profiles"][cfg["active_profile"]]

        legacy_api = legacy.get("api", {}) if isinstance(legacy, dict) else {}
        if legacy_api:
            profile.update({
                "api_key": legacy_api.get("api_key", profile["api_key"]),
                "base_url": legacy_api.get("base_url", profile["base_url"]),
                "model": legacy_api.get("model", profile["model"]),
                "temperature": float(legacy_api.get("temperature", profile["temperature"])),
                "max_output_tokens": int(legacy_api.get("max_output_tokens", profile["max_output_tokens"])),
            })
        legacy_ctx = legacy.get("context", {}) if isinstance(legacy, dict) else {}
        if legacy_ctx:
            cfg["conversation_defaults"]["context"].update(legacy_ctx)

        main_cfg = ConfigManager.load()
        if main_cfg.get("api_key"):
            profile["api_key"] = main_cfg["api_key"]
        if main_cfg.get("api_base_url"):
            profile["base_url"] = main_cfg["api_base_url"]
        if main_cfg.get("api_model"):
            profile["model"] = main_cfg["api_model"]
        if main_cfg.get("api_temperature") is not None:
            profile["temperature"] = float(main_cfg["api_temperature"]) / 10.0
        if main_cfg.get("api_max_output_tokens"):
            profile["max_output_tokens"] = int(main_cfg["api_max_output_tokens"])
        if main_cfg.get("api_max_context"):
            cfg["conversation_defaults"]["context"]["max_window_tokens"] = int(main_cfg["api_max_context"])

        return APIModeConfigManager._normalize(cfg)

    @staticmethod
    def load():
        APIModeConfigManager._ensure_dirs()
        data = APIModeConfigManager._load_json(API_MODE_CONFIG_PATH)
        if data is None:
            data = APIModeConfigManager._build_from_legacy()
            APIModeConfigManager.save(data)
            return data
        normalized = APIModeConfigManager._normalize(data)
        if normalized != data:
            APIModeConfigManager.save(normalized)
        return normalized

    @staticmethod
    def save(config):
        APIModeConfigManager._ensure_dirs()
        normalized = APIModeConfigManager._normalize(config)
        with open(API_MODE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=4, ensure_ascii=False)

    @staticmethod
    def get_active_profile(config=None):
        """获取 API 模式对话使用的活跃 Profile
        
        优先从 api_mode_usage 配置读取，支持 Profile 和 Chain 两种引用方式。
        如果 api_mode_usage 不存在或引用无效，回退到 active_profile。
        """
        cfg = APIModeConfigManager._normalize(config or APIModeConfigManager.load())
        return cfg["profiles"][APIModeConfigManager.get_active_profile_key(cfg)]

    @staticmethod
    def get_editing_profile(config=None):
        """获取设置页正在编辑的 Profile，不受 api_mode_usage 影响。"""
        cfg = APIModeConfigManager._normalize(config or APIModeConfigManager.load())
        profiles = cfg.get("profiles", {})
        active = cfg.get("active_profile", "default")
        if active not in profiles:
            active = next(iter(profiles.keys()))
        return profiles[active]

    @staticmethod
    def update_active_profile(updates):
        cfg = APIModeConfigManager.load()
        active = cfg["active_profile"]
        cfg["profiles"][active] = APIModeConfigManager._deep_merge(cfg["profiles"][active], updates or {})
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def update_context(updates):
        cfg = APIModeConfigManager.load()
        cfg["conversation_defaults"]["context"] = APIModeConfigManager._deep_merge(
            cfg["conversation_defaults"]["context"], updates or {}
        )
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def update_system(updates):
        cfg = APIModeConfigManager.load()
        cfg["conversation_defaults"]["system"] = APIModeConfigManager._deep_merge(
            cfg["conversation_defaults"]["system"], updates or {}
        )
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def update_agent(updates):
        cfg = APIModeConfigManager.load()
        cfg["agent"] = APIModeConfigManager._deep_merge(cfg["agent"], updates or {})
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def set_active_profile(profile_key):
        cfg = APIModeConfigManager.load()
        profiles = cfg.get("profiles", {})
        if profile_key not in profiles:
            raise ValueError(f"Profile 不存在: {profile_key}")
        cfg["active_profile"] = profile_key
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def create_profile(profile_key, profile_data=None):
        key = (profile_key or "").strip()
        if not key:
            raise ValueError("Profile 名称不能为空")
        cfg = APIModeConfigManager.load()
        profiles = cfg.setdefault("profiles", {})
        if key in profiles:
            raise ValueError(f"Profile 已存在: {key}")
        active = cfg.get("active_profile", "default")
        template = deepcopy(profiles.get(active) or APIModeConfigManager._default_config()["profiles"]["default"])
        incoming = profile_data or {}
        new_profile = APIModeConfigManager._deep_merge(template, incoming)
        new_profile.setdefault("name", key)
        profiles[key] = new_profile
        cfg["active_profile"] = key
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def create_browser_stateless_profile(profile_key, profile_data=None):
        data = {
            "name": profile_key,
            "kind": "browser_stateless",
            "provider": "web_ai",
            "conversation_name": "",
            "conversation_url": "",
            "browser_profile": "current_debug_session",
            "supports_parallel": False,
            "cost_level": "low",
            "role": "primary_reasoning",
            "reliability_level": "medium",
            "timeout_seconds": 180,
            "max_queue_size": 1,
        }
        data = APIModeConfigManager._deep_merge(data, profile_data or {})
        return APIModeConfigManager.create_profile(profile_key, data)

    @staticmethod
    def delete_profile(profile_key):
        cfg = APIModeConfigManager.load()
        profiles = cfg.get("profiles", {})
        if profile_key not in profiles:
            raise ValueError(f"Profile 不存在: {profile_key}")
        if len(profiles) <= 1:
            raise ValueError("至少保留一个 Profile")
        del profiles[profile_key]
        if cfg.get("active_profile") == profile_key:
            cfg["active_profile"] = next(iter(profiles.keys()))
        usage = cfg.get("api_mode_usage") or {}
        if usage.get("type") == "profile" and usage.get("ref") == profile_key:
            cfg["api_mode_usage"] = {
                "type": "profile",
                "ref": cfg["active_profile"],
            }
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def rename_profile(old_key, new_key):
        old_key = (old_key or "").strip()
        new_key = (new_key or "").strip()
        if not old_key or not new_key:
            raise ValueError("Profile 名称不能为空")
        cfg = APIModeConfigManager.load()
        profiles = cfg.get("profiles", {})
        if old_key not in profiles:
            raise ValueError(f"Profile 不存在: {old_key}")
        if old_key != new_key and new_key in profiles:
            raise ValueError(f"Profile 已存在: {new_key}")
        profile = deepcopy(profiles[old_key])
        profile["name"] = new_key
        if old_key == new_key:
            profiles[old_key] = profile
        else:
            new_profiles = {}
            for k, v in profiles.items():
                if k == old_key:
                    new_profiles[new_key] = profile
                else:
                    new_profiles[k] = v
            cfg["profiles"] = new_profiles
            if cfg.get("active_profile") == old_key:
                cfg["active_profile"] = new_key
            usage = cfg.get("api_mode_usage") or {}
            if usage.get("type") == "profile" and usage.get("ref") == old_key:
                cfg["api_mode_usage"] = {
                    "type": "profile",
                    "ref": new_key,
                }
            cfg["fallback_chain"] = [new_key if x == old_key else x for x in (cfg.get("fallback_chain", []) or [])]
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def get_safe_config():
        cfg = APIModeConfigManager.load()
        safe = json.loads(json.dumps(cfg))
        for profile in safe.get("profiles", {}).values():
            key = profile.get("api_key", "")
            if key and len(key) > 8:
                profile["api_key"] = key[:4] + "****" + key[-4:]

        return safe

    @staticmethod
    def create_fallback_chain(chain_name: str, profile_refs: list):
        """创建一个新的 Fallback Chain"""
        cfg = APIModeConfigManager.load()
        chains = cfg.setdefault("fallback_chains", {})
        if chain_name in chains:
            raise ValueError(f"Fallback Chain '{chain_name}' 已存在")
        chains[chain_name] = profile_refs
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def update_fallback_chain(chain_name: str, profile_refs: list):
        """更新 Fallback Chain"""
        cfg = APIModeConfigManager.load()
        chains = cfg.setdefault("fallback_chains", {})
        if chain_name not in chains:
            raise ValueError(f"Fallback Chain '{chain_name}' 不存在")
        chains[chain_name] = profile_refs
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def delete_fallback_chain(chain_name: str):
        """删除 Fallback Chain"""
        cfg = APIModeConfigManager.load()
        chains = cfg.get("fallback_chains", {})
        if chain_name not in chains:
            raise ValueError(f"Fallback Chain '{chain_name}' 不存在")
        del chains[chain_name]
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()

    @staticmethod
    def rename_fallback_chain(old_name: str, new_name: str):
        """重命名 Fallback Chain"""
        cfg = APIModeConfigManager.load()
        chains = cfg.get("fallback_chains", {})
        if old_name not in chains:
            raise ValueError(f"Fallback Chain '{old_name}' 不存在")
        if new_name in chains:
            raise ValueError(f"Fallback Chain '{new_name}' 已存在")
        chains[new_name] = chains.pop(old_name)
        APIModeConfigManager.save(cfg)
        return APIModeConfigManager.load()
        return safe
