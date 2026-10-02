import logging
from PySide6.QtCore import QObject, Signal
from app.core.api.api_stream_models import StreamChunk, StreamStatus
from app.core.api.api_stream_handler import APIStreamHandler
from app.core.logging import get_logger
from app.core.worker_modules.upstream_consumer import UpstreamConsumer
from app.core.worker_modules.upstream_events import UpstreamEvent, upstream_event_from_stream_status

logger = get_logger("app.core.worker_api_stream", side="worker")


class WorkerStreamBridge(QObject):
    stream_chunk_signal = Signal(object)
    stream_status_signal = Signal(object)

    def __init__(self, worker=None, parent=None):
        super().__init__(parent)
        self._handler: APIStreamHandler = None
        self._consumer = UpstreamConsumer(worker) if worker else None
        self._closed = False

    def init_handler(self, api_source, tool_router=None):
        if self._closed:
            return
        self._handler = APIStreamHandler(api_source, tool_router=tool_router)
        self._target_client_id = None
        self._target_group = "admin"
        print(f"[DBG][WorkerStreamBridge] init_handler api_source={bool(api_source)}")

    def set_target(self, client_id=None, user_role=None):
        self._target_client_id = client_id
        self._target_group = "admin" if user_role == "developer" else "user"

    @property
    def is_streaming(self) -> bool:
        return self._handler.is_streaming if self._handler else False

    @property
    def uses_upstream_consumer(self) -> bool:
        return self._consumer is not None

    def _chunk_to_payload(self, chunk: StreamChunk) -> dict:
        status = getattr(chunk, "status", "")
        try:
            status_val = status.value
        except Exception:
            status_val = str(status)

        payload = {
            "stream_id": getattr(chunk, "stream_id", "") or "",
            "content": getattr(chunk, "content", "") or "",
            "thinking_content": getattr(chunk, "thinking_content", "") or "",
            "status": status_val,
            "accumulated": getattr(chunk, "accumulated", "") or "",
            "accumulated_thinking": getattr(chunk, "accumulated_thinking", "") or "",
            "delta_type": getattr(chunk, "delta_type", "") or "content",
            "error_message": getattr(chunk, "error_message", "") or "",
            "conversation_id": getattr(chunk, "conversation_id", "") or "",
            "upstream_event": upstream_event_from_stream_status(status_val),
        }
        if getattr(self, "_target_client_id", None):
            payload["target_client_id"] = self._target_client_id
            payload["target_group"] = getattr(self, "_target_group", "admin")
        return payload

    def _payload_to_event(self, payload: dict) -> UpstreamEvent:
        status = str(payload.get("status", "") or "").lower()
        return UpstreamEvent(
            event=upstream_event_from_stream_status(status),
            conversation_id=payload.get("conversation_id", "") or "",
            stream_id=payload.get("stream_id", "") or "",
            text_delta=payload.get("content", "") or "",
            thinking_delta=payload.get("thinking_content", "") or "",
            accumulated_text=payload.get("accumulated", "") or "",
            accumulated_thinking=payload.get("accumulated_thinking", "") or "",
            error_message=payload.get("error_message", "") or "",
            diagnostics={
                "source": "api_stream",
                "status": status,
                "delta_type": payload.get("delta_type", "content"),
            },
        )

    def _consumer_extra(self, payload: dict) -> dict:
        extra = {}
        if payload.get("target_client_id"):
            extra["target_client_id"] = payload.get("target_client_id")
            extra["target_group"] = payload.get("target_group", "admin")
        return extra

    def _emit_external_stream(self, payload: dict):
        if not self._consumer:
            return
        self._consumer.emit_stream(self._payload_to_event(payload), extra=self._consumer_extra(payload))

    def start_stream(self, text: str, tool_router=None):
        if self._closed:
            return
        logger.info(f"[WorkerStreamBridge] start_stream 被调用 | text_len={len(text)}")
        print(f"[DBG][WorkerStreamBridge] start_stream handler={bool(self._handler)} text_len={len(text)}")
        if not self._handler:
            logger.error("[WorkerStreamBridge] Stream handler 未初始化")
            logger.warning("Stream handler not initialized")
            return

        logger.info("[WorkerStreamBridge] 调用 handler.start_stream")
        self._handler.start_stream(
            text=text,
            on_chunk=self._on_chunk,
            on_complete=self._on_complete,
            on_error=self._on_error,
            tool_router=tool_router,
        )
        logger.info("[WorkerStreamBridge] handler.start_stream 已调用")

    def cancel_stream(self):
        if self._handler:
            self._handler.cancel()

    def shutdown(self, timeout=3.0):
        self._closed = True
        if self._handler:
            return self._handler.shutdown(timeout=timeout)
        return True

    def _on_chunk(self, chunk: StreamChunk):
        payload = self._chunk_to_payload(chunk)
        status = payload.get('status')
        if status not in (StreamStatus.STREAMING.value, 'streaming', StreamStatus.STARTED.value, 'started'):
            print(f"[DBG][WorkerStreamBridge] on_chunk status={status} len={len(payload.get('content', ''))}")
        self._emit_external_stream(payload)
        self.stream_chunk_signal.emit(payload)
        if payload.get("status") in (StreamStatus.STARTED.value, "started"):
            self.stream_status_signal.emit(payload)

    def _on_complete(self, chunk: StreamChunk):
        payload = self._chunk_to_payload(chunk)
        self._emit_external_stream(payload)
        self.stream_status_signal.emit(payload)

    def _on_error(self, chunk: StreamChunk):
        payload = self._chunk_to_payload(chunk)
        self._emit_external_stream(payload)
        self.stream_status_signal.emit(payload)
