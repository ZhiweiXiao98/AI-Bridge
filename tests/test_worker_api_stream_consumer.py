from app.core.api.api_stream_models import StreamChunk, StreamStatus
from app.core.worker_modules.worker_api_stream import WorkerStreamBridge
from tests.helpers import RecordingSignal


class FakeWorker:
    def __init__(self):
        self.api_stream_chunk_signal = RecordingSignal()
        self.api_stream_status_signal = RecordingSignal()


def test_api_stream_bridge_emits_external_events_through_consumer():
    worker = FakeWorker()
    bridge = WorkerStreamBridge(worker=worker)
    bridge.set_target(client_id="client_1", user_role="developer")

    bridge._on_chunk(StreamChunk(stream_id="s1", content="", status=StreamStatus.STARTED, conversation_id="conv_1"))
    bridge._on_chunk(StreamChunk(stream_id="s1", content="hi", status=StreamStatus.STREAMING, accumulated="hi", conversation_id="conv_1"))
    bridge._on_complete(StreamChunk(stream_id="s1", content="", status=StreamStatus.COMPLETED, accumulated="hi", conversation_id="conv_1"))

    assert bridge.uses_upstream_consumer is True

    assert [p["upstream_event"] for p in worker.api_stream_chunk_signal.payloads] == ["started", "delta"]
    assert worker.api_stream_chunk_signal.payloads[-1]["content"] == "hi"
    assert worker.api_stream_chunk_signal.payloads[-1]["accumulated"] == "hi"
    assert worker.api_stream_chunk_signal.payloads[-1]["target_client_id"] == "client_1"
    assert worker.api_stream_chunk_signal.payloads[-1]["target_group"] == "admin"

    assert [p["upstream_event"] for p in worker.api_stream_status_signal.payloads] == ["completed"]
    assert worker.api_stream_status_signal.payloads[-1]["accumulated"] == "hi"


def test_api_stream_bridge_carries_thinking_delta():
    worker = FakeWorker()
    bridge = WorkerStreamBridge(worker=worker)

    bridge._on_chunk(StreamChunk(
        stream_id="s1",
        content="",
        thinking_content="先分析",
        status=StreamStatus.STREAMING,
        accumulated="",
        accumulated_thinking="先分析",
        delta_type="thinking",
        conversation_id="conv_1",
    ))

    payload = worker.api_stream_chunk_signal.payloads[-1]
    assert payload["thinking_content"] == "先分析"
    assert payload["accumulated_thinking"] == "先分析"
    assert payload["delta_type"] == "thinking"


def test_api_stream_bridge_keeps_internal_status_signal_for_state_machine():
    worker = FakeWorker()
    bridge = WorkerStreamBridge(worker=worker)
    statuses = []
    bridge.stream_status_signal.connect(statuses.append)

    bridge._on_chunk(StreamChunk(stream_id="s1", content="", status=StreamStatus.STARTED))
    bridge._on_error(StreamChunk(stream_id="s1", content="", status=StreamStatus.ERROR, error_message="boom"))

    assert [p["status"] for p in statuses] == ["started", "error"]
    assert [p["upstream_event"] for p in worker.api_stream_status_signal.payloads] == ["failed"]
    assert worker.api_stream_status_signal.payloads[-1]["error_message"] == "boom"
