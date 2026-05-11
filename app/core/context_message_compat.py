import time
from typing import Any, Dict

from app.core.context_message_models import (
    ConversationMessage,
    MESSAGE_KIND_TEXT,
)


LEGACY_HISTORY_ROLE_KEY = "role"
LEGACY_HISTORY_CONTENT_KEY = "content"
LEGACY_HISTORY_TOKENS_KEY = "tokens"
LEGACY_HISTORY_TIME_KEY = "time"
PRIMARY_HISTORY_TOKEN_KEY = "token_count"
PRIMARY_HISTORY_TIME_KEY = "timestamp"


def message_from_history_dict(data: Dict[str, Any]) -> ConversationMessage:
    if not isinstance(data, dict):
        return ConversationMessage(role="assistant", content=str(data or ""), timestamp=time.time())

    role = str(data.get("role", "assistant") or "assistant")
    content = str(data.get("content", "") or "")
    segments = list(data.get("segments", []) or [])
    kind = str(data.get("kind", MESSAGE_KIND_TEXT) or MESSAGE_KIND_TEXT)
    raw_content = str(data.get("raw_content", "") or "")
    token_count = int(data.get(PRIMARY_HISTORY_TOKEN_KEY, data.get(LEGACY_HISTORY_TOKENS_KEY, 0)) or 0)
    timestamp = float(data.get(PRIMARY_HISTORY_TIME_KEY, data.get(LEGACY_HISTORY_TIME_KEY, time.time())) or time.time())
    meta = data.get("meta", {}) or {}
    if not isinstance(meta, dict):
        meta = {"value": meta}
    source_mode = str(data.get("source_mode", "api") or "api")
    conversation_id = str(data.get("conversation_id", "") or "")
    visible_in_context = bool(data.get("visible_in_context", True))
    compactible = bool(data.get("compactible", True))

    return ConversationMessage(
        role=role,
        content=content,
        segments=segments,
        kind=kind,
        raw_content=raw_content,
        token_count=token_count,
        timestamp=timestamp,
        meta=meta,
        source_mode=source_mode,
        conversation_id=conversation_id,
        visible_in_context=visible_in_context,
        compactible=compactible,
    )
