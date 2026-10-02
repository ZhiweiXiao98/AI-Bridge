"""Offline Qt regression for runtime selection, consent and lifecycle routing."""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.ui
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from app.core.api.api_stream_models import StreamChunk, StreamStatus
from app.ui.pages.chat.api_session_list import APISessionList
from app.ui.pages.chat.chat_page_stream import ChatPageStreamManager
from app.ui.pages.chat.page import ChatPage


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app):
    page = ChatPage.__new__(ChatPage)
    QWidget.__init__(page)
    page.worker = SimpleNamespace(api_approve_tool=Mock(), api_cancel=Mock())
    page.header = SimpleNamespace(set_status=Mock())
    page.api_msg_area = SimpleNamespace(clear_runtime_status=Mock(), show_runtime_status=Mock())
    page.api_stop_btn = QPushButton()
    page.api_stop_btn.setEnabled(False)
    page._api_approval_dialog = None
    page._api_pending_approval = None
    page._api_answered_approvals = set()
    page._api_closed_requests = set()
    page._api_round_payload = {}
    page._api_round_state = "idle"
    page._api_all_messages = []
    page._api_active_conv_id = "conv"
    page.current_mode = "api"
    yield page
    page._dismiss_agent_tool_approval()
    page.close()
    page.deleteLater()
    app.processEvents()


def approval(**changes):
    return {"conversation_id": "conv", "request_id": "req", "call_id": "call", "name": "write_file", "arguments": {"path": "file.txt"}, "project_root": "/project", **changes}


def test_snapshot_during_active_stream_is_deferred_without_deleting_bubble(page):
    page._api_stream_manager = SimpleNamespace(_active_stream_id="req")
    page.message_window_service = SimpleNamespace(slice_messages=Mock())
    page._render_api_messages_with_tool_status()
    assert page._api_messages_pending_render
    page.message_window_service.slice_messages.assert_not_called()


def test_stream_start_flushes_old_history_before_inserting_transient(app):
    from app.ui.pages.chat.message_area_stream import MessageAreaStreamManager
    order = []
    area = SimpleNamespace(flush_render=lambda: order.append("flush"))
    manager = MessageAreaStreamManager(area)
    manager._show_typing_indicator = lambda: order.append("indicator")
    manager._create_stream_bubble = lambda: order.append("bubble")
    manager.begin_stream("req")
    assert order == ["flush", "indicator", "bubble"]
    manager.reset_stream_ui()


def round_state(state, **changes):
    return {"conversation_id": "conv", "request_id": "req", "state": state, **changes}


def test_runtime_unavailable_selection_stays_explicit_and_cannot_create(app):
    widget = APISessionList()
    assert not widget.new_btn.isEnabled()
    widget.set_runtime_options({"items": [
        {"id": "pi", "label": "Pi", "available": False, "reason": "Install Pi first"},
        {"id": "legacy", "label": "Legacy API", "available": True},
    ]})
    assert widget.runtime_combo.currentData() == "pi"
    assert widget.selected_runtime() is None
    assert not widget.new_btn.isEnabled()
    assert "Install Pi" in widget.new_btn.toolTip()
    widget._on_new_clicked()
    assert widget._editing_conv_id is None
    widget.runtime_combo.setCurrentIndex(1)
    assert widget.selected_runtime() == "legacy"
    assert widget.new_btn.isEnabled()
    widget.set_runtime_options({"items": [{"id": "pi", "available": True}, {"id": "legacy", "available": True}]})
    assert widget.selected_runtime() == "legacy"
    widget.set_runtime_options({"items": []})
    assert widget.selected_runtime() is None
    assert not widget.new_btn.isEnabled()
    widget.deleteLater()


def test_full_approval_arguments_are_visible_without_blocking(page):
    arguments = {"content": "x" * 9000 + "IMPORTANT SUFFIX <b>literal</b>"}
    page._on_agent_tool_approval(approval(arguments=arguments))
    dialog = page._api_approval_dialog
    assert dialog.isVisible()
    assert not dialog.isModal()
    assert dialog.textFormat() == Qt.TextFormat.PlainText
    assert json.loads(dialog.detailedText()) == arguments
    assert dialog.defaultButton() == dialog.button(QMessageBox.StandardButton.No)
    page._on_agent_tool_approval(approval(arguments=arguments))
    assert page._api_approval_dialog is dialog


@pytest.mark.parametrize("button", [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
def test_approval_answers_once_and_does_not_reopen(page, button):
    page._on_agent_tool_approval(approval())
    page._api_approval_dialog.button(button).click()
    page.worker.api_approve_tool.assert_called_once_with("conv", "req", "call", button == QMessageBox.StandardButton.Yes)
    page._on_agent_tool_approval(approval())
    assert page._api_approval_dialog is None


def test_window_close_denies_approval(page):
    page._on_agent_tool_approval(approval())
    page._api_approval_dialog.close()
    page.worker.api_approve_tool.assert_called_once_with("conv", "req", "call", False)


@pytest.mark.parametrize("state", ["waiting_followup", "running_tools", "cancelled", "failed", "finalized"])
def test_resolved_or_terminal_state_closes_stale_approval_without_answer(page, state):
    page._on_api_round_state_changed(round_state("streaming_initial_reply"))
    page._on_agent_tool_approval(approval())
    page._on_api_round_state_changed(round_state("awaiting_approval"))
    page._on_api_round_state_changed(round_state(state))
    assert page._api_approval_dialog is None
    page.worker.api_approve_tool.assert_not_called()
    assert page.api_stop_btn.isEnabled() == (state in {"waiting_followup", "running_tools"})


def test_wrong_conversation_and_old_request_cannot_end_new_turn(page):
    page._on_api_round_state_changed(round_state("streaming_initial_reply", request_id="new"))
    page._on_api_round_state_changed(round_state("failed", conversation_id="other", request_id="new"))
    page._on_api_round_state_changed(round_state("failed"))
    page._on_agent_tool_approval(approval())
    assert page._api_round_payload["request_id"] == "new"
    assert page.api_stop_btn.isEnabled()
    assert page._api_approval_dialog is None
    page._on_api_round_state_changed(round_state("cancelled", request_id="new"))
    page._on_agent_tool_approval(approval(request_id="new"))
    assert page._api_approval_dialog is None
    assert not page.api_stop_btn.isEnabled()


def test_stop_is_scoped_and_dismisses_approval_without_sending_denial(page):
    page._on_api_round_state_changed(round_state("awaiting_approval"))
    page._on_agent_tool_approval(approval())
    page._stop_api_request()
    page._stop_api_request()
    page.worker.api_cancel.assert_called_once_with(conversation_id="conv", request_id="req")
    page.worker.api_approve_tool.assert_not_called()
    assert not page.api_stop_btn.isEnabled()
    assert page._api_approval_dialog is None


class StreamSink:
    def __init__(self):
        self.events = []
        self._active_stream_id = None

    def begin_stream(self, stream_id, conversation_id):
        self._active_stream_id = stream_id
        self.events.append(("begin", stream_id, conversation_id))

    def append_text(self, stream_id, content):
        self.events.append(("text", stream_id, content))

    def append_thinking(self, stream_id, content):
        self.events.append(("thinking", stream_id, content))

    def end_stream(self, stream_id, **kwargs):
        self._active_stream_id = None
        self.events.append(("end", stream_id, kwargs))


@pytest.mark.parametrize("status,kwargs", [("completed", {}), ("cancelled", {"cancelled": True}), ("error", {"error_message": "failed"})])
def test_stream_dict_and_legacy_object_routing_close_exactly_once(app, status, kwargs):
    handler = ChatPageStreamManager(None)
    sink = StreamSink()
    handler.set_stream_manager(sink)
    handler.set_active_conv_hook(lambda: "conv")
    started = {"stream_id": "s", "conversation_id": "conv", "status": "started"}
    handler._on_stream_chunk({**started, "conversation_id": "other"})
    assert sink.events == []
    handler._on_stream_chunk(started)
    handler._on_stream_chunk(started)
    handler._on_stream_chunk(StreamChunk("s", "text", StreamStatus.STREAMING, thinking_content="thought", conversation_id="conv"))
    terminal = {**started, "status": status, "error_message": "failed"}
    handler._on_stream_status(terminal)
    handler._on_stream_chunk(terminal)
    handler._on_stream_chunk(started)
    assert sink.events == [("begin", "s", "conv"), ("thinking", "s", "thought"), ("text", "s", "text"), ("end", "s", kwargs)]


def test_pi_navigation_keeps_active_session_and_approval_until_request_finishes(page):
    page._api_conversations_by_id = {"conv": {"id": "conv", "runtime": "pi", "active": True}}
    page.api_session_list = SimpleNamespace(update_sessions=Mock())
    page.session_tabs = SimpleNamespace(blockSignals=Mock(), setCurrentIndex=Mock())
    page._on_api_round_state_changed(round_state("awaiting_approval"))
    page._on_agent_tool_approval(approval())
    dialog = page._api_approval_dialog
    page.on_api_session_clicked("other")
    page.on_mode_switch("browser")
    page._on_api_new_conversation("new")
    assert page._api_active_conv_id == "conv"
    assert page.current_mode == "api"
    assert page._api_approval_dialog is dialog
    page.session_tabs.setCurrentIndex.assert_called_once_with(1)
    page.worker.api_approve_tool.assert_not_called()


def test_timed_out_approval_cannot_reappear_in_same_request(page):
    page._on_agent_tool_approval(approval())
    page._on_api_round_state_changed(round_state("waiting_followup"))
    page._on_agent_tool_approval(approval())
    assert page._api_approval_dialog is None


def test_reconnect_snapshot_reveals_running_api_view_without_switching_backend(page):
    page.current_mode = "browser"
    page._api_conversations_by_id = {"conv": {"runtime": "pi"}}
    page.inner_stack = SimpleNamespace(setCurrentIndex=Mock())
    page.session_tabs = SimpleNamespace(blockSignals=Mock(), setCurrentIndex=Mock())
    page.header.set_mode = Mock()
    page._on_api_round_state_changed(round_state("running_tools", running=True))
    assert page.current_mode == "api"
    page.inner_stack.setCurrentIndex.assert_called_once_with(1)
    page.header.set_mode.assert_called_once_with("api")
    assert page.api_stop_btn.isEnabled()
