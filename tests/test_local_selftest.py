"""仅验证自检控制逻辑；不启动应用、模型、浏览器或网络。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.local_selftest import browser_selftest_probe, wait_for


def test_early_runtime_failure_is_not_hidden_as_approval_timeout():
    app = SimpleNamespace(processEvents=Mock())
    predicate = Mock(return_value=False)
    with pytest.raises(RuntimeError, match="sidecar exited"):
        wait_for(app, predicate, "approval", timeout=30, failure_reason=lambda: "sidecar exited")
    app.processEvents.assert_called_once()
    predicate.assert_not_called()


def test_success_without_failure_reason_preserves_existing_behavior():
    app = SimpleNamespace(processEvents=Mock())
    wait_for(app, lambda: True, "ready", failure_reason=lambda: None)
    app.processEvents.assert_called_once()


def test_timeout_keeps_its_safe_stage_diagnostic():
    app = SimpleNamespace(processEvents=Mock())
    with pytest.raises(RuntimeError, match="browser not started"):
        wait_for(app, lambda: False, "browser ready", timeout=0,
                 timeout_detail=lambda: "browser not started")


def test_browser_probe_distinguishes_fixture_cache_and_render_without_content():
    import json
    secret = "private-conversation-and-url"
    page = SimpleNamespace(current_mode="browser", _browser_all_messages=[{"text": secret}],
                           browser_msg_area=SimpleNamespace(bubbles_cache=[SimpleNamespace(current_data={"text": "分块输出已完成"})]),
                           browser_input_area=SimpleNamespace(is_ai_busy=False, queued_payload=(secret, [])))
    worker = SimpleNamespace(mode="browser", last_messages_snapshot=[{}, {}],
                             connector=SimpleNamespace(conn=SimpleNamespace(diagnostic_snapshot=lambda: {"connection_stage": "page_ready"})))
    fixture = SimpleNamespace(snapshot=lambda: {"request_count": 1, "chunk_count": 13, "response_count": 1,
                                                "events": [{"text": secret}], "url": secret})
    probe = browser_selftest_probe(page, worker, fixture, 3)
    assert probe["fixture_counts"]["response_count"] == 1
    assert probe["ui_cached_message_count"] == 1 and probe["rendered_bubble_count"] == 1
    assert probe["final_marker_cached"] is False and probe["final_marker_rendered"] is True
    assert probe["ui_has_queued_message"] is True
    assert secret not in json.dumps(probe, ensure_ascii=False)
    assert "分块输出已完成" not in json.dumps(probe, ensure_ascii=False)
