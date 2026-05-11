import logging
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("app.core.prompt_runtime.prompt_file_loader", side="worker")

PROMPT_DIR = Path('Prompt')

COMPAT_PROMPT_FILE = '兼容提示词.md'
USER_PREF_FILE = '用户偏好.md'
PLAN_PROMPT_FILE = 'Plan_SystemPrompt.md'
BUILD_PROMPT_FILE = 'Build_SystemPrompt.md'
ASSEMBLED_PROMPT_FILE = '系统提示词.md'
DAEMON_PROMPT_PREFIX = 'Daemon_'


def _load_prompt_file(filename: str) -> str:
    """读取 Prompt/ 下的指定 MD 文件，不存在或失败返回空字符串。"""
    path = PROMPT_DIR / filename
    try:
        if not path.exists():
            logger.warning('Prompt 文件不存在: %s', path)
            return ''
        return path.read_text(encoding='utf-8', errors='replace').strip()
    except Exception as e:
        logger.warning('读取 Prompt 文件失败: %s | %s', path, e)
        return ''


def load_compat_prompt() -> str:
    return _load_prompt_file(COMPAT_PROMPT_FILE)


def load_user_pref_prompt() -> str:
    return _load_prompt_file(USER_PREF_FILE)


def load_plan_prompt() -> str:
    return _load_prompt_file(PLAN_PROMPT_FILE)


def load_build_prompt() -> str:
    return _load_prompt_file(BUILD_PROMPT_FILE)


def load_all_prompt_files() -> dict:
    """加载所有 Prompt 源文件，返回字典。"""
    return {
        'compat_prompt': load_compat_prompt(),
        'user_pref_prompt': load_user_pref_prompt(),
        'plan_prompt': load_plan_prompt(),
        'build_prompt': load_build_prompt(),
    }


def save_assembled_prompt(content: str) -> bool:
    """将组装后的系统提示词写入 Prompt/系统提示词.md（供浏览器模式注入）。"""
    path = PROMPT_DIR / ASSEMBLED_PROMPT_FILE
    try:
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return True
    except Exception as e:
        logger.warning('写入组装提示词失败: %s | %s', path, e)
        return False


def load_daemon_prompt(task_name: str) -> str:
    """加载守护进程提示词。

    task_name 对应 Prompt/Daemon_{task_name}.md
    例如: load_daemon_prompt("suggest") -> Prompt/Daemon_Suggest.md
    """
    filename = f"{DAEMON_PROMPT_PREFIX}{task_name.capitalize()}.md"
    content = _load_prompt_file(filename)
    if not content:
        logger.warning('守护进程提示词为空或不存在: %s', filename)
    return content
