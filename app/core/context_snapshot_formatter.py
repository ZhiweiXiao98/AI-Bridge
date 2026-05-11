"""上下文快照格式化器。

将 APISource._last_request_snapshot 转换为人类可读的调试文本。
"""

import json
import time as _time
from typing import Optional

_SEP = '═' * 72
_SUB = '─' * 60


def _tok_label(n) -> str:
    if n is None:
        return '?tok'
    return f'{n} tok'


def _trunc(text: str, limit: int = 500) -> str:
    """截断过长文本并标注。"""
    if not text:
        return '(空)'
    if len(text) <= limit:
        return text
    return text[:limit] + f'\n... [截断，原文 {len(text)} 字符]'


def format_snapshot(snap: Optional[dict], full: bool = True) -> str:
    """将快照格式化为人类可读文本。

    Args:
        snap: APISource.get_last_request_snapshot() 返回的字典。
        full: True 时展示完整内容，False 时截断长文本。
    """
    if not snap:
        return '(无快照数据)'

    lines = []
    ts = snap.get('timestamp', 0)
    ts_str = _time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime(ts)) if ts else '?'

    lines.append(_SEP)
    lines.append(f'  上下文快照 | {ts_str}')
    lines.append(f'  对话: {snap.get("conversation_id", "?")}')
    lines.append(f'  模型: {snap.get("model", "?")}  |  Profile: {snap.get("profile_key", "?")}')
    lines.append(f'  系统提示词总 tokens: {_tok_label(snap.get("final_system_prompt_tokens"))}')
    lines.append(_SEP)

    # ---- Layer 0: System Prompt Blocks ----
    lines.append('\n[Layer 0: 系统提示词]')
    lines.append(_SUB)
    sys_blocks = snap.get('system_blocks', {})
    block_order = ['compat_prompt', 'user_pref_prompt', 'plan_prompt', 'build_prompt', 'skills_prompt', 'conversation_system_prompt']
    block_labels = {
        'compat_prompt': '兼容提示词',
        'user_pref_prompt': '用户偏好',
        'plan_prompt': 'Plan 模式',
        'build_prompt': 'Build 模式',
        'skills_prompt': 'Skills 提示词',
        'conversation_system_prompt': '对话系统说明',
    }
    for key in block_order:
        content = sys_blocks.get(key, '')
        if not content:
            continue
        label = block_labels.get(key, key)
        tok = sys_blocks.get(f'{key}_tokens', 0)
        lines.append(f'  ▸ {label} ({_tok_label(tok)})')
        text = _trunc(content, 300) if not full else content
        for line in text.split('\n'):
            lines.append(f'    {line}')
        lines.append('')

    # ---- Layer 1: Long-term Memory ----
    lines.append('\n[Layer 1: 长期记忆]')
    lines.append(_SUB)
    lt_frags = snap.get('long_term_fragments', [])
    if not lt_frags:
        lines.append('  (无)')
    else:
        for i, frag in enumerate(lt_frags, 1):
            lines.append(f'  Fragment {i}:')
            text = _trunc(frag, 400) if not full else frag
            for line in text.split('\n'):
                lines.append(f'    {line}')
            lines.append('')

    # ---- Layer 2: Working Memory ----
    lines.append('\n[Layer 2: 工作记忆]')
    lines.append(_SUB)
    wm = snap.get('working_memory', {})
    if not wm:
        lines.append('  (无)')
    else:
        wm_json = json.dumps(wm, ensure_ascii=False, indent=2)
        text = _trunc(wm_json, 500) if not full else wm_json
        for line in text.split('\n'):
            lines.append(f'  {line}')

    # ---- Layer 3: History ----
    lines.append('\n[Layer 3: 对话历史]')
    lines.append(_SUB)
    history = snap.get('history', [])
    if not history:
        lines.append('  (无)')
    else:
        for i, msg in enumerate(history, 1):
            role = msg.get('role', '?')
            kind = msg.get('kind', 'text')
            visible = msg.get('visible', True)
            tokens = msg.get('tokens', 0)
            full_len = msg.get('full_length', 0)
            vis_mark = '✓' if visible else '✗'
            lines.append(f'  [{i}] {role.upper()} ({kind}) [{vis_mark}] {_tok_label(tokens)}')
            content = msg.get('content', '')
            if full_len > len(content):
                content += f'\n... [截断，原文 {full_len} 字符]'
            text = _trunc(content, 300) if not full else content
            for line in text.split('\n'):
                lines.append(f'      {line}')
            lines.append('')

    # ---- Layer 4: Final Messages (sent to LLM) ----
    lines.append('\n[Layer 4: 最终消息数组（发送给 LLM）]')
    lines.append(_SUB)
    final_msgs = snap.get('final_messages', [])
    if not final_msgs:
        lines.append('  (无)')
    else:
        for i, msg in enumerate(final_msgs, 1):
            role = msg.get('role', '?')
            content = msg.get('content', '')
            lines.append(f'  [{i}] role={role}')
            text = _trunc(content, 400) if not full else content
            for line in text.split('\n'):
                lines.append(f'      {line}')
            lines.append('')

    # ---- Response ----
    lines.append('\n[Response: LLM 回复]')
    lines.append(_SUB)
    response = snap.get('response')
    if response is None:
        lines.append('  (未收到回复或仍在流式传输中)')
    else:
        text = _trunc(response, 600) if not full else response
        for line in text.split('\n'):
            lines.append(f'  {line}')

    lines.append('\n' + _SEP)
    return '\n'.join(lines)
