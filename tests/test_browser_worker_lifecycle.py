"""Offline controls, cancellation, reconnect and confirmed browser submission."""
import threading
import time
import collections
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.round_state import BrowserRoundStateMachine, RoundStateEvent
from app.core.services.scheduler_service import SchedulerService
from app.core.worker import WorkerThread
from app.core.worker_modules.worker_browser_commands import WorkerBrowserCommandBridge
from tests.helpers import RecordingSignal


class Harness:
    _execute_task = WorkerThread._execute_task
    _execute_task_sync = WorkerThread._execute_task_sync
    _execute_browser_send = WorkerThread._execute_browser_send
    _browser_detect_state = WorkerThread._browser_detect_state
    _run_browser_loop = WorkerThread._run_browser_loop
    _connect_browser = WorkerThread._connect_browser
    request_browser_reconnect = WorkerThread.request_browser_reconnect
    browser_cancel = WorkerThread.browser_cancel
    _recreate_browser_connector = WorkerThread._recreate_browser_connector

    def __init__(self):
        self.running = True
        self.mode = "browser"
        self._shutdown_started = False
        self._shutdown_lock = threading.Lock()
        self.scheduler = SchedulerService()
        self.statuses = []
        self.safe_emit_status = self.statuses.append
        self.browser_send_result_signal = RecordingSignal()
        self._round_sm = BrowserRoundStateMachine()
        self._update_ai_state = Mock()
        self.pending_user_message = {"text": "stale guide"}
        self.toggle_queue = []
        self.last_send_time = 0
        self.was_busy = False
        self._pre_send_ai_fingerprint = None
        self._get_last_ai_fingerprint = lambda **kw: "old"
        self.connector = SimpleNamespace(
            connect=Mock(return_value=(True, "fixture ready")),
            ready_for_input=Mock(return_value=(True, "ready")),
            send_message=Mock(return_value=(True, "sent")),
            cancel_generation=Mock(return_value=(True, "stopped")),
            start_browser=Mock(return_value=(True, "started")),
            is_busy=Mock(return_value=False),
            get_last_ai_message_id=Mock(return_value="existing-ai"),
            interact=SimpleNamespace(upload_file=Mock(return_value=(True, "uploaded"))),
        )
        self.executor = Mock()
        self._check_and_emit_sync = Mock()
        self._browser_scan_queues = Mock()
        self._browser_process_messages = Mock()
        self._process_toggle_queue = Mock()
        self._background_process_ai_response = Mock()
        self._execute_task_bg = Mock()
        self.last_occupancy_scan = time.time()
        self.occupancy_signal = RecordingSignal()
        self.browser_command_bridge = WorkerBrowserCommandBridge(self)
        self.browser_command_bridge.ready = True
        self.browser_command_bridge.connected = True

    def queue_send(self, request_id="one"):
        accepted = self.browser_command_bridge.send_text("textarea", "hello", browser_request_id=request_id)
        assert accepted
        return self.scheduler.get_next_task()


def test_send_only_signals_success_after_webpage_confirms():
    worker = Harness()
    task = worker.queue_send()
    assert not worker.was_busy
    assert worker._execute_browser_send(task)
    assert worker.was_busy
    assert worker._round_sm.ui_state == "busy"
    assert worker.browser_send_result_signal.items == [
        {"request_id": "one", "ok": True, "message": "网页已确认发送"}
    ]


@pytest.mark.parametrize("failure", [(False, "send_not_committed"), RuntimeError("driver lost")])
def test_submission_failure_resets_busy_and_keeps_draft_receipt(failure):
    worker = Harness()
    task = worker.queue_send()
    if isinstance(failure, Exception):
        worker.connector.send_message.side_effect = failure
    else:
        worker.connector.send_message.return_value = failure
    assert not worker._execute_browser_send(task)
    assert not worker.was_busy and worker.last_send_time == 0
    assert worker._round_sm.ui_state == "idle"
    assert worker.browser_send_result_signal.items[0]["ok"] is False
    worker.connector.send_message.assert_called_once()
    assert "未自动重发" in worker.browser_send_result_signal.items[0]["message"]


def test_cancel_is_gui_safe_clears_queued_messages_and_preserves_other_tasks():
    worker = Harness()
    worker.browser_command_bridge.send_text("textarea", "one", browser_request_id="one")
    worker.browser_command_bridge.send_compound("two", [], browser_request_id="two")
    worker.scheduler.add_task("Host", "run_remote_tests")
    assert worker.browser_cancel()
    worker.connector.cancel_generation.assert_not_called()
    assert worker.pending_user_message is None
    assert [task["action"] for task in worker.scheduler.get_queue_snapshot()[1]] == ["run_remote_tests"]
    assert len(worker.browser_send_result_signal.items) == 2
    assert not any(item["ok"] for item in worker.browser_send_result_signal.items)
    worker.browser_command_bridge.process_controls()
    worker.connector.cancel_generation.assert_called_once()
    assert not worker.browser_command_bridge.cancel_pending


def test_repeated_cancel_does_not_double_stop_or_double_signal():
    worker = Harness()
    worker.browser_command_bridge.send_text("textarea", "hello", browser_request_id="one")
    worker.browser_cancel()
    worker.browser_cancel()
    worker.browser_command_bridge.process_controls()
    worker.connector.cancel_generation.assert_called_once()
    assert len(worker.browser_send_result_signal.items) == 1


def test_cancel_of_task_already_taken_out_of_queue_prevents_send():
    worker = Harness()
    task = worker.queue_send()
    worker.browser_cancel()
    assert not worker._execute_browser_send(task)
    worker.connector.send_message.assert_not_called()
    assert worker.browser_send_result_signal.items[0]["ok"] is False


def test_cancel_before_actual_dom_submit_prevents_send_without_gui_block():
    worker = Harness()
    task = worker.queue_send()
    before_submit = threading.Event()
    resume = threading.Event()
    submitted = []

    def send(selector, text, cancel_check=None):
        before_submit.set()
        assert resume.wait(2)
        if cancel_check and cancel_check():
            return False, "cancelled before submit"
        submitted.append(text)
        return True, "sent"

    worker.connector.send_message = send
    thread = threading.Thread(target=worker._execute_browser_send, args=(task,))
    thread.start()
    assert before_submit.wait(2)
    assert worker.browser_cancel()
    resume.set()
    thread.join(2)
    assert not thread.is_alive()
    assert submitted == []
    assert worker.browser_send_result_signal.items[0]["ok"] is False


def test_cancelled_tool_result_cannot_enqueue_after_new_user_round():
    worker = Harness()
    browser = worker.browser_command_bridge
    old_epoch = browser.epoch
    worker.browser_cancel()
    browser.process_controls()
    assert browser.send_text("textarea", "new user request")
    assert not browser.enqueue_feedback(old_epoch, "Host", "real_send_text", "textarea", "old result")
    assert [task.args[1] for task in list(worker.scheduler.queue.queue)] == ["new user request"]


def test_reconnect_invalidates_old_sends_and_collapses_repeated_clicks(monkeypatch):
    monkeypatch.delenv("AI_BRIDGE_LOCAL_MODE", raising=False)
    worker = Harness()
    task = worker.queue_send()
    worker.request_browser_reconnect(start_browser=True)
    worker.request_browser_reconnect()
    worker.connector.start_browser.assert_not_called()
    worker.browser_command_bridge.process_controls()
    worker.connector.start_browser.assert_called_once()
    assert not worker._execute_browser_send(task)
    worker.connector.send_message.assert_not_called()


def test_same_request_id_is_never_queued_twice():
    worker = Harness()
    browser = worker.browser_command_bridge
    assert browser.send_text("textarea", "hello", browser_request_id="one")
    assert not browser.send_text("textarea", "hello", browser_request_id="one")
    assert worker.scheduler.queue.qsize() == 1


def test_unready_or_stopping_worker_rejects_send_without_driver_calls():
    worker = Harness()
    worker.browser_command_bridge.ready = False
    assert not worker.browser_command_bridge.send_text("textarea", "hello")
    worker.running = False
    assert not worker.request_browser_reconnect()
    assert not worker.browser_cancel()
    worker.connector.send_message.assert_not_called()
    worker.connector.ready_for_input.assert_not_called()


def test_not_logged_in_rejects_send_and_emits_failure():
    worker = Harness()
    task = worker.queue_send()
    worker.connector.ready_for_input.return_value = False, "请先登录网页"
    assert not worker._execute_browser_send(task)
    worker.connector.send_message.assert_not_called()
    assert "登录" in worker.browser_send_result_signal.items[0]["message"]


def test_browser_loop_survives_failure_and_reconnects_without_new_worker(monkeypatch):
    from app.core import worker as module
    worker = Harness()
    worker.browser_command_bridge.connected = False
    worker.browser_command_bridge.ready = False
    worker.connector.connect.side_effect = [(False, "Chrome missing"), (True, "ready")]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 1:
            worker.request_browser_reconnect()
        if len(waits) > 20:
            pytest.fail("loop failed to recover")

    monkeypatch.delenv("AI_BRIDGE_LOCAL_MODE", raising=False)
    monkeypatch.setattr(module.time, "sleep", sleep)
    worker._browser_process_messages.side_effect = lambda: setattr(worker, "running", False)
    worker._run_browser_loop()
    assert worker.connector.connect.call_count == 2
    assert worker._browser_process_messages.called
    assert any("Chrome missing" in message for message in worker.statuses)


def test_failed_send_is_dispatched_serially_and_not_marked_busy():
    worker = Harness()
    worker.browser_command_bridge.send_text("textarea", "one", browser_request_id="one")
    worker.connector.send_message.return_value = False, "failed"
    busy, state = worker._browser_detect_state()
    assert not busy and state == "idle"
    worker.executor.submit.assert_not_called()
    worker.connector.send_message.assert_called_once()
    assert worker.scheduler.current_task is None


def test_cancelled_generation_does_not_restart_tool_pipeline():
    worker = Harness()
    worker._round_sm.handle_event(RoundStateEvent.BUSY_DETECTED)
    worker.was_busy = True
    worker.browser_cancel()
    worker.browser_command_bridge.process_controls()
    assert worker._browser_detect_state() == (False, "idle")
    worker.executor.submit.assert_not_called()


def test_local_reconnect_uses_saved_settings_only_after_old_shutdown(monkeypatch):
    from app.core import worker as module
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    worker = Harness()
    worker.connector.shutdown = Mock(side_effect=[False, True])
    old = worker.connector
    fresh = SimpleNamespace()
    create = Mock(return_value=fresh)
    monkeypatch.setattr(module.ConfigManager, "load", lambda: {"browser_start_url": "http://fixture/new"})
    monkeypatch.setattr(module, "create_browser_connector", create)
    worker.request_browser_reconnect()
    worker.browser_command_bridge.process_controls()
    create.assert_not_called()
    assert worker.connector is old
    worker.browser_command_bridge.process_controls()
    create.assert_called_once_with({"browser_start_url": "http://fixture/new"})
    assert worker.connector is fresh


def test_switching_to_browser_never_calls_driver_from_gui():
    from app.core.worker_modules.worker_api_mode import WorkerApiModeBridge
    worker = Harness()
    worker.mode = "api"
    worker.agent_runtime_bridge = None
    worker._normalizer = Mock()
    worker.mode_changed_signal = RecordingSignal()
    worker.messages_signal = RecordingSignal()
    worker.context_status_signal = RecordingSignal()
    WorkerApiModeBridge(worker).switch_mode("browser")
    assert worker.mode == "browser"
    worker.connector.connect.assert_not_called()
    worker.connector.send_message.assert_not_called()
    assert worker.browser_command_bridge._controls


def test_local_stateless_profile_is_blocked_before_any_browser_action(monkeypatch):
    from app.core.worker_modules.worker_browser_stateless import WorkerBrowserStatelessBridge
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    worker = SimpleNamespace(safe_emit_status=Mock(), connector=Mock(), api_source=Mock())
    assert WorkerBrowserStatelessBridge(worker).handle_send("hello", {"kind": "browser_stateless"}) is False
    assert not worker.connector.mock_calls
    assert not worker.api_source.mock_calls
    assert "浏览器标签页" in worker.safe_emit_status.call_args.args[0]


def test_worker_checks_cancellation_before_each_tool_dispatch():
    worker = Harness()
    worker._processed_lock = threading.RLock()
    worker._processed_tool_fingerprints = set()
    worker._processed_fp_order = collections.deque(maxlen=500)
    worker.current_chat_id = "chat"
    worker._extract_browser_tool_input = lambda: {
        "messages": [{"role": "AI", "segments": []}], "last_ai_msg_id": "new-ai",
        "fingerprint_source": "tool", "fallback_text": "tool", "used_structured": True,
    }
    worker._classify_browser_tool_input = lambda *a, **kw: "tool_call"
    worker._handle_runtime_tool_start = Mock()
    worker._handle_runtime_tool_end = Mock()
    worker._build_browser_tool_feedback_text = lambda response: "result"
    dispatched = []

    def tool_round(**kwargs):
        kwargs["on_intent_start"]("first", 1)
        dispatched.append("first")
        worker.browser_cancel()
        kwargs["on_intent_start"]("second", 2)
        dispatched.append("second")

    worker.tool_router = SimpleNamespace(maybe_handle_tool_from_messages=tool_round)
    WorkerThread._check_and_handle_tool(worker)
    assert dispatched == ["first"]
    assert worker.scheduler.queue.empty()


@pytest.mark.parametrize("fallback", ["function", "code"])
def test_legacy_tool_fallback_preserves_cancellation_callbacks(fallback):
    from app.core.services.tool_router_service import ToolRouterService
    from app.core.tool_runtime.executor import ToolRuntimeExecutor
    from app.core.tool_runtime.models import ToolExecutionResult
    router = ToolRouterService.__new__(ToolRouterService)
    router.runtime_executor = ToolRuntimeExecutor()
    router.runtime_executor.execute_intent = Mock(return_value=ToolExecutionResult(
        success=True, kind="skill_call", name="fixture", display_text="done"
    ))
    router._seen_set = set()
    router.agent = SimpleNamespace()

    def start(intent, index):
        if index == 2:
            raise CancelledError("stop before next tool")

    end = Mock()
    with pytest.raises(CancelledError):
        if fallback == "function":
            text = 'tool_call\n```json\n{"name":"one","arguments":{}}\n```\ntool_call\n```json\n{"name":"two","arguments":{}}\n```'
            router._handle_function_calling("chat", text, start, end)
        else:
            router._extract_all_code_blocks = lambda messages: ["print('one')", "print('two')"]
            router._handle_code_blocks("chat", [], start, end)
    router.runtime_executor.execute_intent.assert_called_once()
    end.assert_called_once()
