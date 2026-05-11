from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import uuid


class StreamStatus(Enum):
    STARTED = "started"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class StreamChunk:
    stream_id: str
    content: str
    status: StreamStatus
    accumulated: str = ""
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)
    conversation_id: str = ""


def make_stream_id() -> str:
    return f"stream_{uuid.uuid4().hex[:12]}"
