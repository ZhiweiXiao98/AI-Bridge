from app.core.worker_modules.upstream_consumer import UpstreamConsumer
from app.core.worker_modules.upstream_events import (
    make_completed_event,
    make_failed_event,
    make_started_event,
    make_structured_event,
)
from tests.helpers import RecordingSignal


class FakeWorker:
    def __init__(self):
        self.api_stream_chunk_signal = RecordingSignal()
        self.api_stream_status_signal = RecordingSignal()
        self.api_round_state_signal = RecordingSignal()
        self.messages_signal = RecordingSignal()
        self.context_status_signal = RecordingSignal()


def test_consumer_routes_stream_events_to_existing_signals():
    worker = FakeWorker()
    consumer = UpstreamConsumer(worker)

    started = make_started_event(conversation_id="conv_1", stream_id="s1")
    structured = make_structured_event(conversation_id="conv_1", stream_id="s1", segments=[{"type": "text", "content": "x"}])
    completed = make_completed_event(conversation_id="conv_1", stream_id="s1")
    failed = make_failed_event(conversation_id="conv_1", stream_id="s2", error_message="boom")

    consumer.emit_stream(started)
    consumer.emit_stream(structured)
    consumer.emit_stream(completed)
    consumer.emit_stream(failed)

    assert worker.api_stream_chunk_signal.payloads[0]["upstream_event"] == "started"
    assert worker.api_stream_chunk_signal.payloads[1]["upstream_event"] == "structured"
    assert worker.api_stream_status_signal.payloads[0]["upstream_event"] == "completed"
    assert worker.api_stream_status_signal.payloads[1]["upstream_event"] == "failed"


def test_consumer_emits_round_and_context_status():
    worker = FakeWorker()
    consumer = UpstreamConsumer(worker)
    event = make_started_event(conversation_id="conv_1", profile_key="browser_web")

    consumer.emit_round(event, state="browser_stateless", message="working", extra={"trace_id": "T1"})
    consumer.emit_context_status({"conversation_id": "conv_1", "total_used": 10})

    round_payload = worker.api_round_state_signal.payloads[-1]
    assert round_payload["state"] == "browser_stateless"
    assert round_payload["message"] == "working"
    assert round_payload["trace_id"] == "T1"
    assert worker.context_status_signal.payloads[-1]["total_used"] == 10


def test_consumer_emits_transient_reply_without_persisting():
    class FakeApiSource:
        def __init__(self):
            self.persisted = []

        def get_history_as_messages_for(self, conv_id):
            return [{"id": "user_1", "conversation_id": conv_id, "role": "User", "segments": [{"type": "text", "content": "hi"}]}]

        def build_message_for_signal(self, role, content, index=0, kind="text", meta=None, raw_content="", segments=None):
            return {
                "id": "built",
                "conversation_id": "conv_1",
                "role": "AI" if role == "assistant" else "User",
                "index": index,
                "segments": segments or [{"type": "text", "content": content}],
                "raw_content": raw_content or content,
                "meta": meta or {},
                "source": "api",
            }

        def append_assistant_message(self, *args, **kwargs):
            self.persisted.append((args, kwargs))

    worker = FakeWorker()
    consumer = UpstreamConsumer(worker)
    api_source = FakeApiSource()
    event = make_structured_event(
        conversation_id="conv_1",
        request_id="req_1",
        stream_id="s1",
        accumulated_text="生成中",
        segments=[{"type": "text", "content": "生成中"}],
    )

    ok = consumer.emit_transient_reply(api_source, event)

    assert ok is True
    assert not api_source.persisted
    assert worker.api_stream_chunk_signal.payloads[-1]["upstream_event"] == "structured"
    transient = worker.messages_signal.payloads[-1][-1]
    assert transient["id"] == "conv_1:browser_stateless_transient"
    assert transient["status"] == "streaming"
    assert transient["meta"]["transient"] is True
