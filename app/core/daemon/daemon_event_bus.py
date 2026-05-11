import threading
from typing import Callable, Dict, List, Optional
from uuid import uuid4

from app.core.logging import get_logger

logger = get_logger("app.core.daemon.daemon_event_bus", side="worker")


class DaemonEventBus:
    EVENT_REPLY_COMPLETED = "reply_completed"
    EVENT_ROUND_ENDED = "round_ended"
    EVENT_COMPACT_NEEDED = "compact_needed"
    EVENT_CONVERSATION_CLOSED = "conv_closed"

    def __init__(self):
        self._subscribers: Dict[str, List[dict]] = {}
        self._lock = threading.Lock()

    def emit(self, event_type: str, payload: dict) -> None:
        with self._lock:
            handlers = list(self._subscribers.get(event_type, []))
        logger.info(
            "[DaemonBus] emit: event_type=%s subscribers=%d payload_keys=%s",
            event_type,
            len(handlers),
            list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        )
        if not handlers:
            logger.info("[DaemonBus] emit 无订阅者: %s", event_type)
            return
        for entry in handlers:
            try:
                entry["handler"](payload)
                logger.info("[DaemonBus] handler 已执行: event_type=%s sub_id=%s", event_type, entry["sub_id"])
            except Exception as e:
                logger.warning("[DaemonBus] 事件处理器异常 [%s]: %s", entry["sub_id"], e)

    def subscribe(self, event_type: str, handler: Callable) -> str:
        sub_id = str(uuid4())[:8]
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append({"sub_id": sub_id, "handler": handler})
        logger.info("[DaemonBus] subscribe: event_type=%s sub_id=%s", event_type, sub_id)
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        with self._lock:
            for event_type, entries in self._subscribers.items():
                self._subscribers[event_type] = [
                    e for e in entries if e["sub_id"] != sub_id
                ]
        logger.debug("取消订阅: %s", sub_id)
