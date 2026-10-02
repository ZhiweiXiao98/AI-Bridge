"""Reconnect and new-chat navigation restore snapshots without re-exporting code."""
import copy
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

from app.core.browser_sync import BrowserCanonicalStore, DOMNormalizer, SeqGenerator
from app.core.worker import WorkerThread
from app.core.worker_modules.worker_browser_message_sync import WorkerBrowserMessageSyncBridge
from tests.helpers import RecordingSignal


def make_worker():
    raw = [
        {"id": "user-1", "role": "User", "segments": [{"type": "text", "content": "first"}]},
        {"id": "ai-2", "role": "AI", "segments": [{"type": "text", "content": "final"}]},
        {"id": "user-3", "role": "User", "segments": [{"type": "text", "content": "second"}]},
        {"id": "ai-4", "role": "AI", "segments": [
            {"type": "code", "language": "python", "content": "# filename: must_not_export.py\nprint('history')"}]},
    ]
    session = SimpleNamespace(snapshot_bubble=0)
    worker = SimpleNamespace(
        running=True, mode="browser", current_chat_id="same-chat", current_bubble_count=4,
        was_busy=False, toggle_queue=[], last_messages_snapshot=copy.deepcopy(raw),
        safe_emit_status=Mock(), _update_ai_state=Mock(),
        browser_command_bridge=SimpleNamespace(report_connection=Mock()),
        connector=SimpleNamespace(
            connect=Mock(return_value=(True, "ready")), interact=object(),
            get_last_ai_message_id=Mock(return_value="ai-4"),
            get_chat_title_id=Mock(return_value="same-chat"),
            get_chat_content_incremental=Mock(side_effect=lambda **_: (copy.deepcopy(raw), True, False))),
        _normalizer=DOMNormalizer(), _canonical_store=BrowserCanonicalStore(), _seq_gen=SeqGenerator(),
        _round_sm=SimpleNamespace(is_idle=lambda: True),
        file_service=SimpleNamespace(process_images=lambda messages: messages),
        state_service=SimpleNamespace(get_session=lambda _: session, save_states=Mock(),
                                      should_emit_sync=lambda *_: (False, 0)),
        engine=SimpleNamespace(deduce_state=lambda messages, state: (state, len(messages), ""),
                               tag_messages=lambda messages, *_: messages),
        messages_signal=RecordingSignal(), process_batch=Mock(),
        _check_and_emit_sync=Mock(), executor=Mock(), tool_router=Mock(),
    )
    canonical, _, _ = worker._normalizer.normalize_messages(raw, conversation_id=worker.current_chat_id)
    worker._canonical_store.apply_snapshot(canonical, worker._seq_gen.next(), worker.current_chat_id)
    worker.browser_message_sync_bridge = WorkerBrowserMessageSyncBridge(worker)
    worker._idle_probe_and_maybe_push = worker.browser_message_sync_bridge.idle_probe_and_maybe_push
    worker._connect_browser = MethodType(WorkerThread._connect_browser, worker)
    worker._browser_process_messages = MethodType(WorkerThread._browser_process_messages, worker)
    return worker


def test_local_reconnect_emits_fresh_full_snapshot_when_identical_history_was_deduped(monkeypatch):
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    worker = make_worker()
    previous_seq = worker._canonical_store.last_seq
    assert worker._connect_browser()
    worker._browser_process_messages()
    assert len(worker.messages_signal.items) == 1
    restored = worker.messages_signal.items[0]
    assert len(restored) == 4
    assert {item["_event"] for item in restored} == {"conversation.snapshot"}
    assert {item["_seq"] for item in restored} == {previous_seq + 1}
    assert worker._last_processed_ai_msg_id == "ai-4"
    worker._browser_process_messages()
    assert len(worker.messages_signal.items) == 1  # only one forced snapshot per connection
    worker.process_batch.assert_not_called()
    worker.executor.submit.assert_not_called()
    assert not worker.tool_router.mock_calls


def test_reconnect_snapshot_uses_newly_detected_session_and_retries_failed_read(monkeypatch):
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    worker = make_worker()
    assert worker._connect_browser()
    worker.connector.get_chat_title_id.return_value = "new-chat"
    extract = worker.connector.get_chat_content_incremental.side_effect
    worker.connector.get_chat_content_incremental.side_effect = RuntimeError("temporary DOM failure")
    worker._browser_process_messages()
    assert not worker.messages_signal.items
    worker.connector.get_chat_content_incremental.side_effect = extract
    worker._browser_process_messages()
    assert len(worker.messages_signal.items) == 1
    assert {item["conversation_id"] for item in worker.messages_signal.items[0]} == {"new-chat"}
    assert worker._canonical_store.conversation_id == "new-chat"
    worker.process_batch.assert_not_called()


def test_remote_connect_preserves_existing_projection_behavior(monkeypatch):
    monkeypatch.delenv("AI_BRIDGE_LOCAL_MODE", raising=False)
    worker = make_worker()
    assert worker._connect_browser()
    worker._browser_process_messages()
    assert not worker.messages_signal.items


def test_reconnect_to_empty_page_clears_old_canonical_history(monkeypatch):
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    worker = make_worker()
    previous_seq = worker._canonical_store.last_seq
    assert worker._connect_browser()
    worker.connector.get_chat_title_id.return_value = "empty-chat"
    worker.connector.get_chat_content_incremental.side_effect = lambda **_: ([], True, False)
    worker._browser_process_messages()
    assert worker.messages_signal.items == [[]]
    assert worker.last_messages_snapshot == []
    assert worker._canonical_store.message_count == 0
    assert worker._canonical_store.conversation_id == "empty-chat"
    assert worker._canonical_store.last_seq == previous_seq + 1
    worker.process_batch.assert_not_called()


def test_new_chat_to_empty_page_clears_old_history_once_without_tool_replay():
    worker = make_worker()
    previous_seq = worker._canonical_store.last_seq
    worker.agent = SimpleNamespace(shift_roles_for_new_chat=Mock())
    worker.connector.new_chat = Mock(return_value=(True, "created"))
    worker.connector.get_chat_title_id.return_value = "empty-new-chat"
    worker.connector.get_chat_content_incremental.side_effect = lambda **_: ([], True, False)

    WorkerThread._execute_task_sync(worker, SimpleNamespace(action="new_chat_task"))
    assert worker._browser_snapshot_pending is True
    worker._browser_process_messages()

    assert worker.messages_signal.items == [[]]
    assert worker.last_messages_snapshot == []
    assert worker._canonical_store.message_count == 0
    assert worker._canonical_store.conversation_id == "empty-new-chat"
    assert worker._canonical_store.last_seq == previous_seq + 1
    assert worker._browser_snapshot_pending is False
    worker._browser_process_messages()
    assert worker.messages_signal.items == [[]]
    worker.process_batch.assert_not_called()
    worker.executor.submit.assert_not_called()
    assert not worker.tool_router.mock_calls


def test_new_chat_snapshot_retries_transient_read_failure():
    worker = make_worker()
    worker.agent = SimpleNamespace(shift_roles_for_new_chat=Mock())
    worker.connector.new_chat = Mock(return_value=(True, "created"))
    worker.connector.get_chat_title_id.return_value = "empty-new-chat"
    worker.connector.get_chat_content_incremental.side_effect = RuntimeError("temporary DOM failure")
    WorkerThread._execute_task_sync(worker, SimpleNamespace(action="new_chat_task"))
    worker._browser_process_messages()
    assert worker._browser_snapshot_pending is True
    assert worker._canonical_store.message_count == 4 and not worker.messages_signal.items
    worker.connector.get_chat_content_incremental.side_effect = lambda **_: ([], True, False)
    worker._browser_process_messages()
    assert worker.messages_signal.items == [[]]
    assert worker._browser_snapshot_pending is False
    worker.process_batch.assert_not_called()


def test_failed_new_chat_does_not_request_a_new_snapshot_or_change_history():
    worker = make_worker()
    worker.agent = SimpleNamespace(shift_roles_for_new_chat=Mock())
    worker.connector.new_chat = Mock(return_value=(False, "not found"))
    WorkerThread._execute_task_sync(worker, SimpleNamespace(action="new_chat_task"))
    assert not getattr(worker, "_browser_snapshot_pending", False)
    assert worker.current_chat_id == "same-chat"
    assert worker._canonical_store.message_count == 4 and not worker.messages_signal.items
