import logging
import json
import hashlib
from typing import List

from app.core.tool_runtime.models import ToolIntent
from app.core.logging import get_logger

logger = get_logger("app.core.tool_runtime.segment_parser", side="worker")


class ToolSegmentParser:
    @staticmethod
    def parse_messages(messages: list, conversation_id: str = '', source: str = '') -> List[ToolIntent]:
        intents: List[ToolIntent] = []
        for msg in reversed(messages or []):
            if msg.get('role') != 'AI':
                continue
            segments = msg.get('segments', []) or []
            intents.extend(ToolSegmentParser.parse_segments(segments, conversation_id=conversation_id, source=source))
            if intents:
                break
        return intents

    @staticmethod
    def parse_segments(segments: list, conversation_id: str = '', source: str = '',
                       write_back_tool_call_id: bool = False) -> List[ToolIntent]:
        intents: List[ToolIntent] = []
        for seg in segments or []:
            seg_type = seg.get('type')
            if seg_type not in ('code', 'tool_call'):
                continue

            lang = str(seg.get('language', '') or '').strip().lower()
            code = str(seg.get('code', seg.get('content', '')) or '')
            raw_block = str(seg.get('raw_content', seg.get('content', '')) or '')
            tool_meta = seg.get('tool_meta') or {}
            block_key = seg.get('block_key')

            parsed = None
            if seg_type == 'tool_call' or lang == 'tool_call':
                parsed = ToolSegmentParser._parse_tool_call_json(code)
            elif seg_type == 'code':
                parsed = ToolSegmentParser._parse_tool_call_json(code)
                if parsed and isinstance(seg, dict):
                    seg['language'] = 'tool_call'
                    lang = 'tool_call'

            if parsed:
                tool_call_id = str(seg.get('tool_call_id') or '').strip()
                if not tool_call_id:
                    tool_call_id = ToolSegmentParser._make_tool_call_id(block_key, code)
                    if write_back_tool_call_id and isinstance(seg, dict):
                        seg['tool_call_id'] = tool_call_id
                intents.append(ToolIntent(
                    kind='skill_call',
                    name=str(parsed.get('name', '') or ''),
                    arguments=parsed.get('arguments', {}) or {},
                    code=code,
                    lang=lang or 'tool_call',
                    source=source,
                    conversation_id=conversation_id,
                    raw_block=raw_block,
                    block_key=block_key,
                    tool_call_id=tool_call_id,
                ))
                continue

            first_line = ''
            for line in code.split('\n'):
                s = line.strip()
                if s:
                    first_line = s.upper()
                    break
            if seg_type == 'code' and lang in ('python', 'py') and any(marker in first_line for marker in ['# EXEC', '# RUN', '# EXECUTE']):
                clean_code = '\n'.join(code.split('\n')[1:]).strip()
                if clean_code:
                    tool_call_id = str(seg.get('tool_call_id') or '').strip()
                    if not tool_call_id:
                        tool_call_id = ToolSegmentParser._make_tool_call_id(block_key, clean_code)
                        if write_back_tool_call_id and isinstance(seg, dict):
                            seg['tool_call_id'] = tool_call_id
                    intents.append(ToolIntent(
                        kind='exec_code',
                        name=tool_meta.get('tool_name', 'code_execution') or 'code_execution',
                        arguments={},
                        code=clean_code,
                        lang=lang,
                        source=source,
                        conversation_id=conversation_id,
                        raw_block=raw_block,
                        block_key=block_key,
                        tool_call_id=tool_call_id,
                    ))
        return intents

    @staticmethod
    def _parse_tool_call_json(code: str):
        text = (code or '').strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        if 'name' not in parsed or 'arguments' not in parsed:
            return None
        return parsed

    @staticmethod
    def _make_tool_call_id(block_key: str, code: str) -> str:
        seed = f"{block_key or ''}|{code or ''}"
        return f"toolcall_{hashlib.md5(seed.encode('utf-8')).hexdigest()[:8]}"
