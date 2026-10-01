import os
import sys

import pytest

pytestmark = pytest.mark.ui

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", reason="PySide6 unavailable", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from app.ui.pages.chat.api_skill_references import (
    ApiSkillReferenceHandler,
    SkillReference,
)
from app.ui.pages.chat.input_area import InputArea


def _app():
    return QApplication.instance() or QApplication(sys.argv)


SKILLS = (
    SkillReference("file_operations", "文件读写编辑"),
    SkillReference("knowledge_search", "知识库检索"),
    SkillReference("journal_search", "查询行驶记录"),
)


class FakeHeader:
    def __init__(self):
        self.status = ""

    def set_status(self, text):
        self.status = text


class FakeInputArea:
    def __init__(self):
        self.suggestions = []
        self.input_box = None
        self.suggestion_bar = None

    def show_suggestions(self, suggestions):
        self.suggestions = list(suggestions)


class FakePage:
    def __init__(self):
        self.header = FakeHeader()
        self.api_input_area = FakeInputArea()


class FakeCursor:
    def __init__(self, position):
        self._position = position

    def position(self):
        return self._position


class FakeInputBox:
    def __init__(self, text):
        self.text = text

    def toPlainText(self):
        return self.text

    def textCursor(self):
        return FakeCursor(len(self.text))


def _handler(page=None):
    return ApiSkillReferenceHandler(page or FakePage(), skills_provider=lambda: SKILLS)


class SignalStub:
    def connect(self, *_args, **_kwargs):
        return None


class WorkerStub:
    def __init__(self):
        self.status_signal = SignalStub()
        self.sessions_signal = SignalStub()
        self.batch_complete_signal = SignalStub()
        self.occupancy_signal = SignalStub()
        self.messages_signal = SignalStub()
        self.input_area = None

    def set_exec_mode(self, *_args, **_kwargs):
        return None


def test_slash_without_query_shows_skill_mentions():
    page = FakePage()
    handled, send_text = _handler(page).handle("/")

    assert handled is True
    assert send_text is None
    assert "$file_operations" in page.api_input_area.suggestions
    assert page.header.status == "选择一个 Skill 引用"


def test_slash_prefix_filters_skill_mentions():
    page = FakePage()
    handled, send_text = _handler(page).handle("/know")

    assert handled is True
    assert send_text is None
    assert page.api_input_area.suggestions == ["$knowledge_search"]


def test_realtime_slash_token_updates_skill_suggestions():
    page = FakePage()
    page.api_input_area.input_box = FakeInputBox("/jo")

    _handler(page).update_suggestions_for_input()

    assert page.api_input_area.suggestions == ["$journal_search"]


def test_exact_slash_skill_reference_normalizes_to_codex_style_mention():
    handled, send_text = _handler().handle("/file_operations 读取 app/core/api_source.py")

    assert handled is False
    assert send_text == "$file_operations 读取 app/core/api_source.py"


def test_normal_text_is_not_handled():
    handled, send_text = _handler().handle("正常发送")

    assert handled is False
    assert send_text == "正常发送"


def test_input_area_replaces_current_slash_token_when_adopting_skill_reference():
    _app()
    area = InputArea()
    area.input_box.setPlainText("/file")
    cursor = area.input_box.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    area.input_box.setTextCursor(cursor)

    area._adopt_suggestion("$file_operations")

    assert area.input_box.toPlainText() == "$file_operations "


def test_chat_page_initializes_skill_references_before_signal_wiring():
    _app()
    from app.ui.pages.chat.page import ChatPage

    page = ChatPage(WorkerStub())
    try:
        assert page.api_skill_references is not None
    finally:
        page.deleteLater()
