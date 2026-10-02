"""Offline Qt coverage of the full browser cache and its visible projection."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.ui
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication

from app.core.browser_sync import ChatProjectionReducer
from app.ui.pages.chat.message_area import MessageArea
from app.ui.pages.chat.page import ChatPage
from app.ui.pages.chat.services.message_window_service import MessageWindowService


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app):
    area = MessageArea()
    projection = ChatProjectionReducer()
    resync = Mock()
    projection.set_resync_callback(resync)
    value = SimpleNamespace(
        worker=SimpleNamespace(current_chat_id="chat-1"), current_mode="browser",
        _browser_all_messages=[], _browser_round_state="idle",
        _browser_message_projection=projection,
        message_window_service=MessageWindowService(default_turns=1, step_turns=1),
        browser_msg_area=area, _request_browser_resync=resync,
    )
    yield value
    area.render_timer.stop()
    area.deleteLater()
    app.processEvents()


def message(mid, text, seq=1, event="conversation.snapshot", ordinal=0, role="AI", conversation="chat-1"):
    return {"id": mid, "role": role, "index": ordinal + 1, "ordinal": ordinal,
            "conversation_id": conversation, "source": "browser", "rev": seq,
            "content_hash": text, "segments": [{"type": "text", "content": text}],
            "_seq": seq, "_event": event}


def deliver(page, messages):
    ChatPage._on_mode_messages(page, messages)
    page.browser_msg_area.flush_render()


def test_streaming_updates_full_cache_and_actual_bubble(page):
    user = message("turn:User", "中文问题", role="User")
    partial = message("turn:AI", "本地浏览器测试回复", ordinal=1)
    deliver(page, [user, partial])
    for seq, text in [(2, "本地浏览器测试回复，分块输出"), (3, "本地浏览器测试回复，分块输出已完成")]:
        final = message("turn:AI", text, seq, "message.upsert", ordinal=1)
        deliver(page, [final])
        assert page._browser_all_messages == [user, final]
        assert page.browser_msg_area._projection.get_ordered_messages() == [user, final]
        assert page.browser_msg_area._bubbles_by_id["turn:AI"].current_data == final
        assert page.browser_msg_area._bubbles_by_id["turn:User"].is_user
        assert not page.browser_msg_area._bubbles_by_id["turn:AI"].is_user


def test_delete_only_event_keeps_other_history(page):
    first, second = message("first:AI", "keep"), message("second:AI", "remove", ordinal=1)
    deliver(page, [first, second])
    deliver(page, [{"id": "second:AI", "_seq": 2, "_event": "message.remove"}])
    assert page._browser_all_messages == [first]
    assert list(page.browser_msg_area._bubbles_by_id) == ["first:AI"]


def test_old_event_cannot_roll_back_cache_or_bubble(page):
    deliver(page, [message("turn:AI", "partial")])
    final = message("turn:AI", "complete", 2, "message.upsert")
    deliver(page, [final])
    deliver(page, [message("turn:AI", "old", 1, "message.upsert")])
    assert page._browser_all_messages == [final]
    assert page.browser_msg_area._bubbles_by_id["turn:AI"].current_data == final


def test_conversation_snapshot_replaces_cache_and_rendered_history(page):
    deliver(page, [message("old:AI", "old conversation")])
    page.worker.current_chat_id = "chat-2"
    new = message("new:AI", "new conversation", 2, conversation="chat-2")
    deliver(page, [new])
    assert page._browser_all_messages == [new]
    assert list(page.browser_msg_area._bubbles_by_id) == ["new:AI"]


def test_new_conversation_incremental_requires_snapshot(page):
    old = message("old:AI", "old conversation")
    deliver(page, [old])
    page.worker.current_chat_id = "chat-2"
    deliver(page, [message("new:AI", "new conversation", 2, "message.upsert", conversation="chat-2")])
    page._request_browser_resync.assert_called_once()
    assert page._browser_all_messages == [old]
    assert list(page.browser_msg_area._bubbles_by_id) == ["old:AI"]


def test_load_more_retains_hidden_history_and_latest_stream_text(page):
    initial = [message(f"{i}:AI", f"message {i}", ordinal=i) for i in range(4)]
    deliver(page, initial)
    assert len(page._browser_all_messages) == 4
    assert len(page.browser_msg_area._bubbles_by_id) == 2
    final = message("3:AI", "分块输出已完成", 2, "message.upsert", ordinal=3)
    deliver(page, [final])
    assert page._browser_all_messages == initial[:3] + [final]
    ChatPage._load_more_for_mode(page, "browser")
    page.browser_msg_area.flush_render()
    assert set(page.browser_msg_area._bubbles_by_id) == {f"{i}:AI" for i in range(4)}
    assert page.browser_msg_area._bubbles_by_id["3:AI"].current_data["segments"] == final["segments"]


def test_reconnect_snapshot_restores_cleared_same_conversation_view(page):
    page.message_window_service = MessageWindowService(default_turns=10)
    initial = [message(f"{i}:AI", f"restored {i}", ordinal=i) for i in range(4)]
    deliver(page, initial)
    # The native acceptance gate deliberately clears only what the user can see;
    # reconnect must repopulate it even when every DOM message is unchanged.
    page._browser_all_messages = []
    page.browser_msg_area.render_messages([], "")
    assert not page.browser_msg_area._bubbles_by_id
    deliver(page, [dict(item, _seq=2) for item in initial])
    assert len(page._browser_all_messages) == 4
    assert set(page.browser_msg_area._bubbles_by_id) == {f"{i}:AI" for i in range(4)}
    assert "restored 0" in str(page.browser_msg_area._bubbles_by_id["0:AI"].current_data)


def test_reconnect_snapshot_updates_visible_tail_with_unchanged_first_message(page):
    user = message("turn:User", "question", role="User")
    partial = message("turn:AI", "partial", ordinal=1)
    deliver(page, [user, partial])
    final = message("turn:AI", "restored final", seq=2, ordinal=1)
    deliver(page, [dict(user, _seq=2), final])
    assert page._browser_all_messages[-1] == final
    assert page.browser_msg_area._bubbles_by_id["turn:AI"].current_data["segments"] == final["segments"]


def test_reconnect_to_empty_page_clears_full_cache_and_bubbles(page):
    deliver(page, [message("old:AI", "old browser history")])
    deliver(page, [])
    assert page._browser_all_messages == []
    assert page._browser_message_projection.get_ordered_messages() == []
    assert page.browser_msg_area._bubbles_by_id == {}
