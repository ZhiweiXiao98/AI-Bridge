from app.core.worker_modules.upstream_events import (
    make_completed_event,
    make_failed_event,
    make_started_event,
    make_structured_event,
    upstream_event_from_stream_status,
)


def test_started_event_maps_to_stream_started_payload():
    event = make_started_event(
        conversation_id="conv_1",
        request_id="req_1",
        profile_key="browser_web",
        stream_id="stream_1",
    )

    payload = event.to_stream_payload()

    assert payload["status"] == "started"
    assert payload["conversation_id"] == "conv_1"
    assert payload["request_id"] == "req_1"
    assert payload["profile_key"] == "browser_web"
    assert payload["upstream_event"] == "started"


def test_structured_event_carries_segments_and_streaming_status():
    event = make_structured_event(
        conversation_id="conv_1",
        request_id="req_1",
        profile_key="browser_web",
        stream_id="stream_1",
        accumulated_text="hello",
        segments=[{"type": "text", "content": "hello"}],
        raw_message={"id": "ai_1"},
    )

    payload = event.to_stream_payload()
    raw = event.to_dict()

    assert payload["status"] == "streaming"
    assert payload["accumulated"] == "hello"
    assert raw["segments"][0]["content"] == "hello"
    assert raw["raw_message"]["id"] == "ai_1"


def test_terminal_events_map_to_completed_and_error():
    completed = make_completed_event(
        conversation_id="conv_1",
        request_id="req_ok",
        stream_id="stream_ok",
    )
    failed = make_failed_event(
        conversation_id="conv_1",
        request_id="req_fail",
        stream_id="stream_fail",
        error_message="send_failed",
        diagnostics={"error_code": "send_failed"},
    )

    assert completed.to_stream_payload()["status"] == "completed"
    failed_payload = failed.to_stream_payload()
    assert failed_payload["status"] == "error"
    assert failed_payload["error_message"] == "send_failed"
    assert failed.to_round_payload("finalized")["error_code"] == "send_failed"


def test_api_stream_status_maps_to_upstream_events():
    assert upstream_event_from_stream_status("started") == "started"
    assert upstream_event_from_stream_status("streaming") == "delta"
    assert upstream_event_from_stream_status("completed") == "completed"
    assert upstream_event_from_stream_status("error") == "failed"
