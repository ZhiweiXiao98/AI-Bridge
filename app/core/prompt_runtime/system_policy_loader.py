from pathlib import Path
import logging

from app.core.logging import get_logger

logger = get_logger("app.core.prompt_runtime.system_policy_loader", side="worker")

API_MODE_SYSTEM_POLICY_PATH = Path('docs/API_MODE_SYSTEM_POLICY.md')


def load_api_mode_system_policy() -> str:
    try:
        if not API_MODE_SYSTEM_POLICY_PATH.exists():
            return ''
        return API_MODE_SYSTEM_POLICY_PATH.read_text(encoding='utf-8', errors='replace').strip()
    except Exception as e:
        logger.warning(f'加载 API 模式系统规范失败: {e}')
        return ''
