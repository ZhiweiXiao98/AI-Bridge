"""系统提示词组装器。

从 Prompt/ 文件夹加载源文件，按固定顺序拼接最终系统提示词。
拼接顺序:
  1. 兼容提示词
  2. 用户偏好
  3. Plan 模式提示词
  4. Build 模式提示词
  5. Skills Prompt
  6. 当前对话系统说明
"""

import re

from app.core.api_mode_config import TOOL_PROTOCOL_NATIVE
from .prompt_file_loader import load_all_prompt_files, save_assembled_prompt
from .skills_prompt_loader import build_skills_prompt


def _normalized_parts(parts):
    cleaned = []
    for part in parts:
        text = str(part or '').strip()
        if text:
            cleaned.append(text)
    return cleaned


NATIVE_TOOL_POLICY = """# 工具调用协议
当前运行通道支持 API 原生工具调用时，必须优先使用原生 tool calls。
不要主动输出 Markdown `tool_call` 围栏；只有在运行时明确说明原生工具不可用或要求文本兜底时，才使用 Markdown 围栏工具调用。"""


def _strip_markdown_tool_call_sections(files: dict) -> dict:
    adapted = dict(files or {})
    compat = adapted.get('compat_prompt', '')
    compat = re.sub(
        r"\n*##\s*统一工具调用格式（强制、不可违反）[\s\S]*$",
        "",
        compat,
    ).strip()
    adapted['compat_prompt'] = (compat + "\n\n" + NATIVE_TOOL_POLICY).strip() if compat else NATIVE_TOOL_POLICY

    for key in ('plan_prompt', 'build_prompt'):
        text = adapted.get(key, '')
        text = re.sub(
            r"\n*#\s*工具调用格式（强制要求）[\s\S]*?(?=\n#\s*行为准则)",
            "\n",
            text,
        ).strip()
        adapted[key] = text
    return adapted


def build_final_system_prompt(
    conversation_system_prompt: str = '',
    inject_skills_prompt: bool = True,
    save_assembled: bool = False,
    tool_protocol: str = "markdown_fallback",
) -> dict:
    """组装最终系统提示词。

    Args:
        conversation_system_prompt: 当前对话系统说明（面板设置）。
        inject_skills_prompt: 是否注入 Skills Prompt。
        save_assembled: 是否将结果写入 Prompt/系统提示词.md。

    Returns:
        包含各部分内容和 final_system_prompt 的字典。
    """
    files = load_all_prompt_files()
    if str(tool_protocol or '').strip() == TOOL_PROTOCOL_NATIVE:
        files = _strip_markdown_tool_call_sections(files)
    skills_prompt = build_skills_prompt(tool_protocol=tool_protocol) if inject_skills_prompt else ''

    final_parts = _normalized_parts([
        files['compat_prompt'],
        files['user_pref_prompt'],
        files['plan_prompt'],
        files['build_prompt'],
        skills_prompt,
        conversation_system_prompt,
    ])
    final_system_prompt = '\n\n'.join(final_parts)

    if save_assembled and final_system_prompt:
        save_assembled_prompt(final_system_prompt)

    return {
        'compat_prompt': files['compat_prompt'],
        'user_pref_prompt': files['user_pref_prompt'],
        'plan_prompt': files['plan_prompt'],
        'build_prompt': files['build_prompt'],
        'skills_prompt': skills_prompt,
        'conversation_system_prompt': (conversation_system_prompt or '').strip(),
        'final_system_prompt': final_system_prompt,
    }
