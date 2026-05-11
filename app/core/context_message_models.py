from dataclasses import dataclass, field
from typing import Any, Dict


MESSAGE_KIND_TEXT = "text"
MESSAGE_KIND_TOOL_FEEDBACK = "tool_feedback"
MESSAGE_KIND_COMPACT_SUMMARY = "compact_summary"
MESSAGE_KIND_META= "meta"


@dataclass
class ConversationMessage:
    role: str
    content: str = ""
    segments: list = field(default_factory=list)
    kind: str = MESSAGE_KIND_TEXT
    raw_content: str = ""
    token_count: int = 0
    timestamp: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)
    source_mode: str = "api"
    conversation_id: str = ""
    visible_in_context: bool = True
    compactible: bool = True

    def to_chat_dict(self) -> dict:
        return {"role": self.role, "content": self.content}

    def to_history_dict(self) -> dict:
        return {
            "role": self.role,
            "kind": self.kind,
            "content": self.content,
            "segments": list(self.segments or []),
            "raw_content": self.raw_content,
            "token_count": self.token_count,
            "timestamp": self.timestamp,
            "meta": dict(self.meta or {}),
            "source_mode": self.source_mode,
            "conversation_id": self.conversation_id,
            "visible_in_context": self.visible_in_context,
            "compactible": self.compactible,
        }
