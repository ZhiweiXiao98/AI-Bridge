# filename: app/core/logging/noise_control.py
"""
日志噪声控制

职责：
- 管理高频日志的开关配置
- 流式 chunk / RPC 转发 / 同步轮询等日志的降噪
- 提供运行时动态调整能力
- 持久化配置到文件
"""

import json
import os
import logging
from typing import Dict, Optional

_logger = logging.getLogger("noise_control")

DEFAULT_CONFIG = {
    "stream_chunk_enabled": False,
    "stream_chunk_level": "DEBUG",
    "rpc_forward_enabled": False,
    "rpc_forward_level": "DEBUG",
    "sync_poll_enabled": False,
    "sync_poll_level": "DEBUG",
    "heartbeat_enabled": False,
    "heartbeat_level": "DEBUG",
    "tool_loop_detail_enabled": False,
    "tool_loop_detail_level": "DEBUG",
    "panel_noise_filter": True,
    "panel_min_level": "INFO",
}

CONFIG_FILENAME = "log_noise_config.json"


class NoiseControlConfig:
    def __init__(self, config_dir: str = None):
        self._config = dict(DEFAULT_CONFIG)
        from app.core.app_constants import APP_ROOT
        self._config_dir = config_dir or APP_ROOT
        self._load()

    def _config_path(self):
        return os.path.join(self._config_dir, CONFIG_FILENAME)

    def _load(self):
        path = self._config_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._config.update(saved)
            except Exception as e:
                _logger.warning(f"加载噪声控制配置失败: {e}")

    def save(self):
        path = self._config_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            _logger.warning(f"保存噪声控制配置失败: {e}")

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value):
        self._config[key] = value

    def is_enabled(self, category: str) -> bool:
        key = f"{category}_enabled"
        return self._config.get(key, False)

    def get_level(self, category: str) -> str:
        key = f"{category}_level"
        return self._config.get(key, "DEBUG")

    def set_category(self, category: str, enabled: bool, level: str = "DEBUG"):
        self._config[f"{category}_enabled"] = enabled
        self._config[f"{category}_level"] = level
        self.save()

    @property
    def stream_chunk_enabled(self) -> bool:
        return self.is_enabled("stream_chunk")

    @property
    def rpc_forward_enabled(self) -> bool:
        return self.is_enabled("rpc_forward")

    @property
    def sync_poll_enabled(self) -> bool:
        return self.is_enabled("sync_poll")

    @property
    def heartbeat_enabled(self) -> bool:
        return self.is_enabled("heartbeat")

    @property
    def tool_loop_detail_enabled(self) -> bool:
        return self.is_enabled("tool_loop_detail")

    @property
    def panel_noise_filter(self) -> bool:
        return self._config.get("panel_noise_filter", True)

    @property
    def panel_min_level(self) -> str:
        return self._config.get("panel_min_level", "INFO")

    def to_dict(self) -> Dict:
        return dict(self._config)


_instance: Optional[NoiseControlConfig] = None


def get_noise_config() -> NoiseControlConfig:
    global _instance
    if _instance is None:
        _instance = NoiseControlConfig()
    return _instance
