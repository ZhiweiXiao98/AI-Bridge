from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ToolTaskMeta:
    tool_call_id: str = ''
    tool_name: str = ''
    conversation_id: str = ''

    def to_scheduler_kwargs(self) -> Dict[str, Any]:
        return {
            'tool_call_id': self.tool_call_id,
            'tool_name': self.tool_name,
            'conversation_id': self.conversation_id,
        }


def build_tool_task_meta(tool_call_id: str = '', tool_name: str = '', conversation_id: str = '') -> ToolTaskMeta:
    return ToolTaskMeta(
        tool_call_id=str(tool_call_id or '').strip(),
        tool_name=str(tool_name or '').strip(),
        conversation_id=str(conversation_id or '').strip(),
    )


def build_tool_task_meta_from_intent(intent) -> ToolTaskMeta:
    return ToolTaskMeta(
        tool_call_id=str(getattr(intent, 'tool_call_id', '') or '').strip(),
        tool_name=str(getattr(intent, 'name', '') or '').strip(),
        conversation_id=str(getattr(intent, 'conversation_id', '') or '').strip(),
    )
