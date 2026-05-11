# filename: app/core/browser_sync/store.py
"""浏览器模式 canonical 内存状态存储。

服务端维护的规范化对话状态，作为客户端投影的唯一事实源。
包含：
- messages_by_id: 按 message_id 索引的规范化消息
- ordered_ids: 按 ordinal 排列的 message_id 列表
- segments_by_id: 按 segment_id 索引的规范化 segment
- recent_events: 近期事件日志（用于补偿/回放）
- last_seq: 最新事件的 seq
"""

import logging
import time
from collections import deque
from typing import Dict, List, Optional, Set

from .models import CanonicalMessage, CanonicalSegment, ConversationEvent
from .events import EventType

logger = logging.getLogger(__name__)

MAX_RECENT_EVENTS = 200


class BrowserCanonicalStore:
    """浏览器模式 canonical 对话状态存储。"""

    def __init__(self):
        self.conversation_id: str = ""
        self.round_id: str = ""
        self.messages_by_id: Dict[str, CanonicalMessage] = {}
        self.ordered_ids: List[str] = []
        self.segments_by_id: Dict[str, CanonicalSegment] = {}
        self.recent_events: deque = deque(maxlen=MAX_RECENT_EVENTS)
        self.last_seq: int = 0
        self.last_probe_signature: str = ""

    def clear(self):
        self.conversation_id = ""
        self.round_id = ""
        self.messages_by_id.clear()
        self.ordered_ids.clear()
        self.segments_by_id.clear()
        self.recent_events.clear()
        self.last_seq = 0
        self.last_probe_signature = ""

    def apply_snapshot(self, messages: List[CanonicalMessage], seq: int,
                       conversation_id: str = "", round_id: str = ""):
        """应用完整 snapshot，替换所有状态。"""
        self.conversation_id = conversation_id
        self.round_id = round_id
        self.messages_by_id.clear()
        self.ordered_ids.clear()
        self.segments_by_id.clear()

        for msg in messages:
            self.messages_by_id[msg.id] = msg
            self.ordered_ids.append(msg.id)
            for seg in msg.segments:
                if seg.id:
                    self.segments_by_id[seg.id] = seg

        self.ordered_ids.sort(key=lambda mid: self.messages_by_id[mid].ordinal)
        self.last_seq = seq
        logger.info("[CanonicalStore] snapshot 应用 | seq=%s | msgs=%s | conv=%s | ids=[%s]",
                     seq, len(messages), conversation_id[:12],
                     " | ".join(mid[:12] for mid in self.ordered_ids))

    def apply_incremental(self, messages: List[CanonicalMessage], changed_ids: List[str], seq: int,
                          conversation_id: str = "", round_id: str = ""):
        """增量更新：只 upsert 变化的消息，保留未变化的消息不动。

        messages: 完整的消息列表（含冻结+活跃）
        changed_ids: 本轮变化的消息 id 列表
        """
        if conversation_id:
            self.conversation_id = conversation_id
        if round_id:
            self.round_id = round_id

        changed_set = set(changed_ids)
        upserted = 0
        for msg in messages:
            if msg.id not in changed_set:
                continue
            existing = self.messages_by_id.get(msg.id)
            if existing and existing.content_hash == msg.content_hash and existing.rev >= msg.rev:
                continue
            self.messages_by_id[msg.id] = msg
            if msg.id not in self.ordered_ids:
                self.ordered_ids.append(msg.id)
            for seg in msg.segments:
                if seg.id:
                    self.segments_by_id[seg.id] = seg
            upserted += 1

        if upserted > 0:
            self.ordered_ids.sort(key=lambda mid: self.messages_by_id[mid].ordinal)

        self.last_seq = seq
        logger.info("[CanonicalStore] 增量更新 | seq=%s | changed=%s | upserted=%s | total=%s",
                     seq, len(changed_ids), upserted, len(self.ordered_ids))

    def upsert_message(self, msg: CanonicalMessage, seq: int) -> bool:
        existing = self.messages_by_id.get(msg.id)
        if existing and existing.content_hash == msg.content_hash and existing.rev >= msg.rev:
            logger.debug("[CanonicalStore] upsert 无变化 | id=%s | rev=%s | ch=%s", msg.id[:12], msg.rev, msg.content_hash[:8])
            return False

        self.messages_by_id[msg.id] = msg
        if msg.id not in self.ordered_ids:
            self.ordered_ids.append(msg.id)
            self.ordered_ids.sort(key=lambda mid: self.messages_by_id[mid].ordinal)

        for seg in msg.segments:
            if seg.id:
                self.segments_by_id[seg.id] = seg

        self.last_seq = seq
        logger.info("[CanonicalStore] upsert 有变化 | id=%s | rev=%s | ch=%s | seq=%s",
                    msg.id[:12], msg.rev, msg.content_hash[:8], seq)
        return True

    def delete_message(self, message_id: str, seq: int) -> bool:
        if message_id not in self.messages_by_id:
            return False
        msg = self.messages_by_id.pop(message_id)
        for seg in msg.segments:
            self.segments_by_id.pop(seg.id, None)
        self.ordered_ids.remove(message_id)
        self.last_seq = seq
        logger.info("[CanonicalStore] 删除消息 | id=%s | seq=%s", message_id[:12], seq)
        return True

    def patch_segment(self, segment: CanonicalSegment, seq: int) -> bool:
        existing = self.segments_by_id.get(segment.id)
        if existing and existing.content_hash == segment.content_hash and existing.rev >= segment.rev:
            logger.debug("[CanonicalStore] patch_segment 无变化 | seg_id=%s | rev=%s", segment.id[:16], segment.rev)
            return False
        self.segments_by_id[segment.id] = segment
        if segment.message_id in self.messages_by_id:
            msg = self.messages_by_id[segment.message_id]
            for i, s in enumerate(msg.segments):
                if s.id == segment.id:
                    msg.segments[i] = segment
                    break
            msg.content_hash = msg.compute_content_hash()
        self.last_seq = seq
        logger.info("[CanonicalStore] patch_segment 有变化 | seg_id=%s | rev=%s | msg=%s | seq=%s",
                    segment.id[:16], segment.rev, segment.message_id[:12], seq)
        return True

    def log_event(self, event: ConversationEvent):
        self.recent_events.append(event)

    def get_events_since(self, since_seq: int) -> List[ConversationEvent]:
        return [e for e in self.recent_events if e.seq > since_seq]

    def get_snapshot(self) -> List[dict]:
        return [self.messages_by_id[mid].to_dict() for mid in self.ordered_ids]

    def get_message_by_id(self, message_id: str) -> Optional[CanonicalMessage]:
        return self.messages_by_id.get(message_id)

    @property
    def message_count(self) -> int:
        return len(self.ordered_ids)
