# filename: app/core/browser_sync/models.py
"""浏览器模式 canonical 数据模型。

服务端维护的规范化消息与 segment，作为客户端投影的唯一事实源。
所有字段设计兼容现有 UI 消费的字段（id, role, segments, block_key 等），
同时新增 ordinal, rev, content_hash 等稳定性字段。
"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CanonicalSegment:
    """规范化 segment：消息内的一个内容单元（text / code / image / tool_result）。"""
    id: str = ""
    message_id: str = ""
    type: str = ""
    ordinal: int = 0
    content: str = ""
    language: str = ""
    content_hash: str = ""
    ui_state: str = ""
    status: str = ""
    rev: int = 0
    tool_call_id: Optional[str] = None
    block_key: Optional[str] = None
    block_index: int = 0
    code_fingerprint: str = ""
    is_transient_preview: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def compute_content_hash(self) -> str:
        raw = f"{self.type}:{self.content}"
        bound = self.extra.get("_bound_results")
        if bound:
            import json as _json
            raw += f":bound:{_json.dumps(bound, sort_keys=True, ensure_ascii=False)}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = {
            "type": self.type,
            "content": self.content,
            "language": self.language,
            "message_id": self.message_id,
            "block_index": self.block_index,
            "block_key": self.block_key,
            "code_fingerprint": self.code_fingerprint,
            "content_hash": self.content_hash,
            "segment_id": self.id,
            "ordinal": self.ordinal,
            "rev": self.rev,
        }
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.ui_state:
            d["ui_state"] = self.ui_state
        if self.status:
            d["status"] = self.status
        if self.is_transient_preview:
            d["is_transient_preview"] = True
        if self.extra:
            d.update(self.extra)
        return d


@dataclass
class CanonicalMessage:
    """规范化消息：服务端维护的一条对话消息。"""
    id: str = ""
    conversation_id: str = ""
    round_id: str = ""
    ordinal: int = 0
    role: str = ""
    status: str = "final"
    rev: int = 0
    content_hash: str = ""
    segments: List[CanonicalSegment] = field(default_factory=list)
    raw_len: int = 0
    index: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def compute_content_hash(self) -> str:
        parts = [f"{s.type}:{s.content_hash}" for s in self.segments]
        raw = "|".join(parts)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "index": self.index,
            "ordinal": self.ordinal,
            "rev": self.rev,
            "status": self.status,
            "content_hash": self.content_hash,
            "conversation_id": self.conversation_id,
            "round_id": self.round_id,
            "segments": [s.to_dict() for s in self.segments],
            "raw_len": self.raw_len,
            **self.extra,
        }


@dataclass
class ConversationEvent:
    """服务端下发的有序事件。"""
    seq: int = 0
    conversation_id: str = ""
    round_id: str = ""
    event: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "conversation_id": self.conversation_id,
            "round_id": self.round_id,
            "event": self.event,
            "payload": self.payload,
            "created_at": self.created_at,
        }
