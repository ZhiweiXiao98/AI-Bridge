import logging
from app.core.skills import SkillsManager
from app.core.logging import get_logger

logger = get_logger("app.core.prompt_runtime.skills_prompt_loader", side="worker")


def build_skills_prompt(tool_protocol: str = "markdown_fallback") -> str:
    try:
        manager = SkillsManager()
        manager.scan_all_skills()
        return manager.generate_system_prompt(tool_protocol=tool_protocol, summary_only=True).strip()
    except Exception as e:
        logger.warning(f'生成 Skills Prompt 失败: {e}')
        return ''
