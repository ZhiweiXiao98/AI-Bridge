# filename: app/core/browser_sync/events.py
"""事件类型常量定义。

对应计划书 §4.2 主要事件类型。
当前阶段只定义常量，后续阶段逐步在 Worker 侧使用。
"""

from enum import Enum


class EventType(str, Enum):
    CONVERSATION_SNAPSHOT = "conversation.snapshot"
    MESSAGE_UPSERT = "message.upsert"
    MESSAGE_PATCH = "message.patch"
    MESSAGE_DELETE = "message.delete"
    SEGMENT_UPSERT = "segment.upsert"
    SEGMENT_PATCH = "segment.patch"
    SEGMENT_DELETE = "segment.delete"
    TOOL_STATUS = "tool.status"
    TOOL_RESULT = "tool.result"
    ROUND_STATE = "round.state"
    STREAM_DONE = "stream.done"
    SYNC_RESET = "sync.reset"
