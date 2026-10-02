"""本地浏览器设置/停止界面的离线回归，不打开网站。"""
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.ui
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication

from app.ui.components.local_browser_settings import LocalBrowserSettingsDialog, validate_browser_url
from app.ui.pages.chat.page import ChatPage
from boot_local import select_startup_mode


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("url", ["", "about:blank", "https://example.org/chat", "http://127.0.0.1:1234/fixture"])
def test_browser_url_allows_web_and_empty_only(url):
    assert validate_browser_url(url) == (url or "about:blank")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:password@example.org", "not a url"])
def test_browser_url_rejects_non_web_and_embedded_credentials(url):
    from app.core.driver.local_chrome import BrowserSetupError
    with pytest.raises((ValueError, BrowserSetupError)):
        validate_browser_url(url)


def test_settings_save_does_not_launch_or_download(app, monkeypatch):
    from app.ui.components import local_browser_settings as settings
    saved = Mock()
    monkeypatch.setattr(settings.ConfigManager, "load", lambda: {"unrelated": "preserved"})
    monkeypatch.setattr(settings.ConfigManager, "save", saved)
    dialog = LocalBrowserSettingsDialog()
    assert not dialog.download_check.isChecked()
    dialog.url_edit.setText("https://example.org/chat")
    dialog.chrome_edit.setText("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    dialog.driver_edit.setText("/approved/chromedriver")
    dialog.save()
    value = saved.call_args.args[0]
    assert value["unrelated"] == "preserved"
    assert value["browser_start_url"] == "https://example.org/chat"
    assert value["browser_allow_driver_download"] is False
    assert value["browser_source"] == "external_chrome"
    assert dialog.result() == 1
    dialog.deleteLater()


def test_stop_clears_ui_queue_before_worker_can_go_idle():
    order = []
    page = SimpleNamespace(browser_input_area=SimpleNamespace(cancel_queue=lambda: order.append("clear"),
                           cancel_local_browser_submission=lambda: order.append("invalidate")),
                           worker=SimpleNamespace(browser_cancel=lambda: order.append("cancel")),
                           header=SimpleNamespace(set_status=Mock()))
    ChatPage._stop_browser_request(page)
    assert order == ["clear", "invalidate", "cancel"]


def test_reconnect_is_queued_without_touching_driver():
    worker = SimpleNamespace(request_browser_reconnect=Mock())
    page = SimpleNamespace(worker=worker, header=SimpleNamespace(set_status=Mock()))
    ChatPage._reconnect_local_browser(page)
    worker.request_browser_reconnect.assert_called_once_with()


def test_local_settings_do_not_offer_destructive_browser_profile(app, monkeypatch):
    from app.core.api_mode_config import APIModeConfigManager
    from app.ui.components.settings.settings_api import SettingsApiSection
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    config = APIModeConfigManager.load()
    widget = SettingsApiSection(config={}, api_config=config)
    assert not widget.api_browser_profile_add_btn.isEnabled()
    assert not widget.api_provider_combo.model().item(widget.api_provider_combo.findData("web_ai")).isEnabled()
    assert not widget.browser_source_combo.model().item(widget.browser_source_combo.findData("embedded_qt")).isEnabled()
    widget.deleteLater()


@pytest.mark.parametrize("explicit,saved,smoke,expected", [
    (None, "browser", False, "browser"), (None, "api", False, "api"),
    (None, "browser", True, "api"), ("browser", "api", False, "browser"),
    (None, "unsupported", False, "api"),
])
def test_startup_restores_selected_mode_and_isolates_api_smoke(explicit, saved, smoke, expected):
    assert select_startup_mode(explicit, saved, smoke) == expected


@pytest.fixture
def composer(app):
    from app.ui.pages.chat.input_area import InputArea
    widget = InputArea()
    widget.worker = SimpleNamespace()
    widget.input_box.setPlainText("保留测试草稿")
    yield widget
    widget.deleteLater()


def test_disconnected_send_preserves_text_and_attachments(composer):
    composer.pending_attachments = ["/temporary/example.txt"]
    composer.local_browser_submit = Mock(return_value=False)
    composer.on_send()
    assert composer.input_box.toPlainText() == "保留测试草稿"
    assert composer.pending_attachments == ["/temporary/example.txt"]
    assert composer._local_browser_submission is None
    assert composer.send_btn.isEnabled()


def test_accepted_send_waits_for_ack_and_prevents_duplicate(composer):
    composer.local_browser_submit = Mock(return_value=True)
    composer.on_send()
    request_id = composer._local_browser_submission[0]
    assert composer.input_box.toPlainText() == "保留测试草稿"
    assert not composer.send_btn.isEnabled()
    composer.on_send()
    assert composer.local_browser_submit.call_count == 1
    composer.on_browser_send_result({"request_id": request_id, "ok": True})
    assert not composer.input_box.toPlainText()
    assert composer.send_btn.isEnabled()


def test_failed_ack_keeps_draft_and_attachment_retry(composer):
    composer.pending_attachments = ["/temporary/example.txt"]
    composer.local_browser_submit = Mock(return_value=True)
    composer.on_send()
    request_id = composer._local_browser_submission[0]
    composer.on_browser_send_result({"request_id": request_id, "ok": False, "message": "未收到网页回执"})
    assert composer.input_box.toPlainText() == "保留测试草稿"
    assert composer.pending_attachments == ["/temporary/example.txt"]
    assert composer.send_btn.isEnabled()
    composer.on_send()
    assert composer.local_browser_submit.call_count == 2


def test_ack_does_not_clear_newer_edits(composer):
    composer.local_browser_submit = Mock(return_value=True)
    composer.on_send()
    request_id = composer._local_browser_submission[0]
    composer.input_box.setPlainText("更新后的草稿")
    composer.on_browser_send_result({"request_id": request_id, "ok": True})
    assert composer.input_box.toPlainText() == "更新后的草稿"


def test_cancel_invalidates_late_ack_without_losing_draft(composer):
    composer.local_browser_submit = Mock(return_value=True)
    composer.on_send()
    request_id = composer._local_browser_submission[0]
    composer.cancel_local_browser_submission()
    composer.on_browser_send_result({"request_id": request_id, "ok": True})
    assert composer.input_box.toPlainText() == "保留测试草稿"
    assert composer.send_btn.isEnabled()
