from dataclasses import dataclass, field
import time
from typing import Any


UPSTREAM_STARTED = "started"
UPSTREAM_DELTA = "delta"
UPSTREAM_STRUCTURED = "structured"
UPSTREAM_COMPLETED = "completed"
UPSTREAM_FAILED = "failed"
UPSTREAM_DIAGNOSTIC = "diagnostic"

_STREAM_STATUS_BY_EVENT = {
    UPSTREAM_STARTED: "started",
    UPSTREAM_DELTA: "streaming",
    UPSTREAM_STRUCTURED: "streaming",
    UPSTREAM_COMPLETED: "completed",
    UPSTREAM_FAILED: "error",
    UPSTREAM_DIAGNOSTIC: "streaming",
}

_UPSTREAM_EVENT_BY_STREAM_STATUS = {
    "started": UPSTREAM_STARTED,
    "streaming": UPSTREAM_DELTA,
    "completed": UPSTREAM_COMPLETED,
    "error": UPSTREAM_FAILED,
    "cancelled": UPSTREAM_FAILED,
}


@dataclass
class UpstreamEvent:
    """Unified event emitted by an upstream model source.

    API profiles can produce token deltas. Browser profiles can produce
    structured DOM segments. Worker/UI adapters translate this shape into the
    current stream and message signals until the rest of API mode is unified.
    """

    event: str
    conversation_id: str = ""
    request_id: str = ""
    profile_key: str = ""
    stream_id: str = ""
    text_delta: str = ""
    accumulated_text: str = ""
    segments: list[dict[str, Any]] = field(default_factory=list)
    raw_message: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "profile_key": self.profile_key,
            "stream_id": self.stream_id,
            "text_delta": self.text_delta,
            "accumulated_text": self.accumulated_text,
            "segments": list(self.segments or []),
            "raw_message": dict(self.raw_message or {}) if self.raw_message else None,
            "diagnostics": dict(self.diagnostics or {}),
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }

    def to_stream_payload(self) -> dict[str, Any]:
        status = _STREAM_STATUS_BY_EVENT.get(self.event, "streaming")
        return {
            "stream_id": self.stream_id,
            "content": self.text_delta,
            "status": status,
            "accumulated": self.accumulated_text,
            "error_message": self.error_message,
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "profile_key": self.profile_key,
            "upstream_event": self.event,
            "diagnostics": dict(self.diagnostics or {}),
        }

    def to_round_payload(self, state: str, message: str = "") -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "state": state,
            "message": message,
            "profile_key": self.profile_key,
            "request_id": self.request_id,
            "error_code": self.diagnostics.get("error_code", ""),
            "diagnostics": dict(self.diagnostics or {}),
            "upstream_event": self.event,
        }


def make_started_event(**kwargs) -> UpstreamEvent:
    return UpstreamEvent(event=UPSTREAM_STARTED, **kwargs)


def make_structured_event(**kwargs) -> UpstreamEvent:
    return UpstreamEvent(event=UPSTREAM_STRUCTURED, **kwargs)


def make_completed_event(**kwargs) -> UpstreamEvent:
    return UpstreamEvent(event=UPSTREAM_COMPLETED, **kwargs)


def make_failed_event(**kwargs) -> UpstreamEvent:
    return UpstreamEvent(event=UPSTREAM_FAILED, **kwargs)


def upstream_event_from_stream_status(status: Any) -> str:
    try:
        raw = str(status.value).lower()
    except Exception:
        raw = str(status or "").lower()
    return _UPSTREAM_EVENT_BY_STREAM_STATUS.get(raw, UPSTREAM_DIAGNOSTIC)
