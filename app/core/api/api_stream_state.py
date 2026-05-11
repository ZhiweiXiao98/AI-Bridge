import logging
from typing import Optional
from .api_stream_models import StreamStatus, make_stream_id
from app.core.logging import get_logger

logger = get_logger("app.core.api_stream_state", side="worker")

class APIStreamState:
    def __init__(self):
        self._stream_id: Optional[str] = None
        self._conversation_id: Optional[str] = None
        self._status: StreamStatus = StreamStatus.COMPLETED
        self._accumulated_text: str = ""
        self._chunk_count: int = 0

    @property
    def is_streaming(self) -> bool:
        return self._status in (StreamStatus.STARTED, StreamStatus.STREAMING)

    @property
    def stream_id(self) -> Optional[str]:
        return self._stream_id

    @property
    def conversation_id(self) -> Optional[str]:
        return self._conversation_id

    @property
    def accumulated_text(self) -> str:
        return self._accumulated_text

    @property
    def status(self) -> StreamStatus:
        return self._status

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    def start(self, conversation_id: str = "") -> str:
        self._stream_id = make_stream_id()
        self._conversation_id = conversation_id
        self._status = StreamStatus.STARTED
        self._accumulated_text = ""
        self._chunk_count = 0
        logger.debug(f"Stream started: {self._stream_id} | conv={conversation_id}")
        return self._stream_id

    def append(self, text: str):
        self._accumulated_text += text
        self._chunk_count += 1
        if self._status == StreamStatus.STARTED:
            self._status = StreamStatus.STREAMING

    def complete(self):
        self._status = StreamStatus.COMPLETED
        logger.debug(f"Stream completed: {self._stream_id} | chunks={self._chunk_count}")

    def fail(self, error: str = ""):
        self._status = StreamStatus.ERROR
        logger.warning(f"Stream failed: {self._stream_id} | error={error}")

    def cancel(self):
        self._status = StreamStatus.CANCELLED
        logger.debug(f"Stream cancelled: {self._stream_id}")

    def reset(self):
        self._stream_id = None
        self._conversation_id = None
        self._status = StreamStatus.COMPLETED
        self._accumulated_text = ""
        self._chunk_count = 0
