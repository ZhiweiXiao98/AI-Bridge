import logging
from PySide6.QtCore import QObject
from app.core.api.api_stream_models import StreamStatus
from app.core.logging import get_logger

logger = get_logger("app.ui.chat_page_stream", side="ui")


class ChatPageStreamManager(QObject):
    def __init__(self, message_area, parent=None):
        super().__init__(parent)
        self._message_area = message_area
        self._stream_manager = None
        self._active_conv_hook = None

    def set_active_conv_hook(self, hook):
        self._active_conv_hook = hook

    def _is_valid_conv(self, conv_id):
        if not getattr(self, '_active_conv_hook', None):
            return True
        active = self._active_conv_hook()
        if not active or not conv_id:
            return True
        return str(active) == str(conv_id)

    def set_stream_manager(self, stream_manager):
        self._stream_manager = stream_manager

    def connect_worker_signals(self, stream_bridge):
        stream_bridge.stream_chunk_signal.connect(self._on_stream_chunk)
        stream_bridge.stream_status_signal.connect(self._on_stream_status)

    def disconnect_worker_signals(self, stream_bridge):
        try:
            stream_bridge.stream_chunk_signal.disconnect(self._on_stream_chunk)
            stream_bridge.stream_status_signal.disconnect(self._on_stream_status)
        except RuntimeError:
            pass

    def _normalize(self, chunk):
        if isinstance(chunk, dict):
            status = str(chunk.get("status", "") or "").lower()
            return {
                "stream_id": chunk.get("stream_id", "") or "",
                "content": chunk.get("content", "") or "",
                "status": status,
                "error_message": chunk.get("error_message", "") or "",
                "conversation_id": chunk.get("conversation_id", "") or "",
            }

        status_obj = getattr(chunk, "status", "")
        try:
            status = str(status_obj.value).lower()
        except Exception:
            status = str(status_obj).lower()
        return {
            "stream_id": getattr(chunk, "stream_id", "") or "",
            "content": getattr(chunk, "content", "") or "",
            "status": status,
            "error_message": getattr(chunk, "error_message", "") or "",
            "conversation_id": getattr(chunk, "conversation_id", "") or "",
        }

    def _on_stream_chunk(self, chunk):
        data = self._normalize(chunk)
        if not self._is_valid_conv(data.get('conversation_id')):
            logger.debug(f"[ChatPageStream] 丢弃跨对话包 | conv_id={data.get('conversation_id')}")
            return
        print(f"[DBG][ChatPageStream] on_chunk status={data['status']} len={len(data['content'])} stream_id={data['stream_id']}")
        logger.info(f"[ChatPageStream] _on_stream_chunk 收到信号 | status={data['status']} | content_len={len(data['content'])}")
        if not self._stream_manager:
            print("[DBG][ChatPageStream] stream_manager missing")
            logger.warning("[ChatPageStream] stream_manager 未初始化")
            return

        if data["status"] in (StreamStatus.STARTED.value, "started"):
            logger.info(f"[ChatPageStream] 流式开始 | stream_id={data['stream_id']}")
            self._stream_manager.begin_stream(data["stream_id"], data["conversation_id"])
        elif data["status"] in (StreamStatus.STREAMING.value, "streaming"):
            logger.debug(f"[ChatPageStream] 接收流式数据 | stream_id={data['stream_id']} | len={len(data['content'])}")
            self._stream_manager.append_text(data["stream_id"], data["content"])
        elif data["status"] in (StreamStatus.CANCELLED.value, "cancelled"):
            logger.info(f"[ChatPageStream] 流式被取消 | stream_id={data['stream_id']}")
            self._stream_manager.end_stream(data["stream_id"], cancelled=True)

    def _on_stream_status(self, chunk):
        data = self._normalize(chunk)
        if not self._is_valid_conv(data.get('conversation_id')):
            logger.debug(f"[ChatPageStream] 丢弃跨对话状态 | conv_id={data.get('conversation_id')}")
            return
        print(f"[DBG][ChatPageStream] on_status status={data['status']} stream_id={data['stream_id']}")
        logger.info(f"[ChatPageStream] _on_stream_status 收到信号 | status={data['status']}")
        if not self._stream_manager:
            print("[DBG][ChatPageStream] stream_manager missing")
            logger.warning("[ChatPageStream] stream_manager 未初始化")
            return

        if data["status"] in (StreamStatus.COMPLETED.value, "completed"):
            logger.info(f"[ChatPageStream] 流式完成 | stream_id={data['stream_id']}")
            self._stream_manager.end_stream(data["stream_id"])
        elif data["status"] in (StreamStatus.ERROR.value, "error"):
            logger.error(f"[ChatPageStream] 流式错误 | stream_id={data['stream_id']} | error={data['error_message']}")
            self._stream_manager.end_stream(data["stream_id"], error_message=data["error_message"])
