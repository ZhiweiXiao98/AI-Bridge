# filename: app/core/browser_sync/projection.py
"""客户端投影状态与 reducer。

按计划书 §8，客户端维护投影状态：
- last_seq: 最新消费的事件 seq
- messages_by_id: 按 message_id 索引的消息投影
- ordered_ids: 按 ordinal 排列的 message_id 列表
- segments_by_id: 按 segment_id 索引的 segment 投影
- round_state: 当前回合状态

reducer 规则（§8.2）：
- seq <= lastSeq → 丢弃
- seq > lastSeq + 1 → 缓冲，请求 resync
- seq == lastSeq + 1 → 应用，更新 lastSeq，排空缓冲
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_PENDING_BUFFER = 50
RESYNC_THRESHOLD = 5


@dataclass
class ChatProjectionState:
    last_seq: int = 0
    conversation_id: str = ""
    messages_by_id: Dict[str, dict] = field(default_factory=dict)
    ordered_ids: List[str] = field(default_factory=list)
    segments_by_id: Dict[str, dict] = field(default_factory=dict)
    round_state: str = "idle"
    pending_events: deque = field(default_factory=lambda: deque(maxlen=MAX_PENDING_BUFFER))


class ChatProjectionReducer:
    """客户端投影 reducer：消费 Worker 推送的消息列表，更新投影状态。"""

    def __init__(self):
        self.state = ChatProjectionState()
        self._on_resync_needed: Optional[Callable] = None
        self._change_callbacks: List[Callable] = []

    def set_resync_callback(self, callback: Callable):
        self._on_resync_needed = callback

    def reset(self):
        self.state = ChatProjectionState()
        logger.info("[ProjectionReducer] 投影状态已重置")

    def on_change(self, callback: Callable):
        self._change_callbacks.append(callback)

    def _notify_change(self, change_type: str, affected_ids: List[str]):
        for cb in self._change_callbacks:
            try:
                cb(change_type, affected_ids)
            except Exception as e:
                logger.warning("[ProjectionReducer] 通知回调异常: %s", e)

    def apply_messages(self, messages: List[dict]) -> dict:
        """应用 Worker 推送的消息列表。

        返回变更摘要：
        {
            'type': 'snapshot' | 'incremental',
            'added': [...],
            'updated': [...],
            'removed': [...],
            'seq': int,
        }
        """
        if not messages:
            return {"type": "empty", "added": [], "updated": [], "removed": [], "seq": 0}

        seq = messages[0].get("_seq", 0)
        event = messages[0].get("_event", "")

        if seq > 0 and seq <= self.state.last_seq:
            logger.debug("[ProjectionReducer] 丢弃旧事件 | seq=%s | last_seq=%s", seq, self.state.last_seq)
            return {"type": "stale", "added": [], "updated": [], "removed": [], "seq": seq}

        is_snapshot = (event == "conversation.snapshot")
        is_fresh_snapshot = (self.state.last_seq == 0) or is_snapshot
        if not is_fresh_snapshot and seq > self.state.last_seq + RESYNC_THRESHOLD:
            logger.warning("[ProjectionReducer] seq 跳跃过大 | seq=%s | last_seq=%s | gap=%s | 降级为全量应用",
                           seq, self.state.last_seq, seq - self.state.last_seq)
            if self._on_resync_needed:
                self._on_resync_needed()
            is_snapshot = True

        added = []
        updated = []
        new_ids = set()
        remove_ids = set()

        for msg in messages:
            if msg.get("_event") == "message.remove":
                remove_ids.add(str(msg.get("id", "") or ""))
                continue

            mid = str(msg.get("id", "") or "")
            if not mid:
                continue
            new_ids.add(mid)

            content_hash = msg.get("content_hash", "")
            ordinal = msg.get("ordinal", 0)

            existing = self.state.messages_by_id.get(mid)
            if existing is None:
                added.append(mid)
                self.state.messages_by_id[mid] = msg
            elif (
                existing.get("content_hash") != content_hash
                or existing.get("rev") != msg.get("rev")
                or existing.get("ordinal") != ordinal
                or existing.get("index") != msg.get("index")
                or existing.get("role") != msg.get("role")
                or existing.get("conversation_id") != msg.get("conversation_id")
            ):
                updated.append(mid)
                self.state.messages_by_id[mid] = msg
                logger.debug("[ProjectionReducer] 消息内容变化 | id=%s | old_ch=%s | new_ch=%s | old_rev=%s | new_rev=%s",
                             mid[:12],
                             existing.get("content_hash", "")[:8], content_hash[:8],
                             existing.get("rev"), msg.get("rev"))
            else:
                pass

            for seg in (msg.get("segments") or []):
                if isinstance(seg, dict):
                    seg_id = seg.get("segment_id", "")
                    if seg_id:
                        self.state.segments_by_id[seg_id] = seg

        removed = []
        if is_snapshot:
            for old_id in list(self.state.ordered_ids):
                if old_id not in new_ids:
                    removed.append(old_id)
                    self.state.messages_by_id.pop(old_id, None)

        for rid in remove_ids:
            if rid in self.state.messages_by_id:
                removed.append(rid)
                self.state.messages_by_id.pop(rid, None)
                if rid in self.state.ordered_ids:
                    self.state.ordered_ids.remove(rid)

        if removed:
            logger.info("[ProjectionReducer] 消息被移除 | ids=[%s]", " | ".join(rid[:12] for rid in removed))

        if is_snapshot:
            self.state.ordered_ids = sorted(
                new_ids,
                key=lambda mid: self.state.messages_by_id.get(mid, {}).get("ordinal", 0)
            )
        else:
            for mid in new_ids:
                if mid not in self.state.ordered_ids:
                    self.state.ordered_ids.append(mid)
            self.state.ordered_ids.sort(
                key=lambda mid: self.state.messages_by_id.get(mid, {}).get("ordinal", 0)
            )

        if seq > 0:
            self.state.last_seq = seq

        change_type = "snapshot" if is_snapshot else "incremental"
        result = {
            "type": change_type,
            "added": added,
            "updated": updated,
            "removed": removed,
            "seq": seq,
        }

        if added or updated or removed:
            self._notify_change(change_type, added + updated + removed)
            logger.info("[ProjectionReducer] 应用完成 | type=%s | added=%s | updated=%s | removed=%s | seq=%s",
                        change_type, len(added), len(updated), len(removed), seq)

        return result

    def get_ordered_messages(self) -> List[dict]:
        return [self.state.messages_by_id[mid] for mid in self.state.ordered_ids
                if mid in self.state.messages_by_id]

    def get_message(self, message_id: str) -> Optional[dict]:
        return self.state.messages_by_id.get(message_id)

    def reset(self):
        self.state = ChatProjectionState()
