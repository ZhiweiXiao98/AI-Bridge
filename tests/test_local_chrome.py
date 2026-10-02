"""No-network browser startup and DOM authorization regression tests."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import pytest

from app.core.driver.local_chrome import BrowserSetupError, LocalChromeSession, browser_url, origin, validate_browser_url


@pytest.mark.parametrize("url", ["", "about:blank", "https://web-ai.example.com"])
def test_unconfigured_browser_opens_only_blank(url):
    assert validate_browser_url(url) == "about:blank"


def test_explicit_blank_url_does_not_restore_inherited_site(monkeypatch):
    monkeypatch.setenv("UPSTREAM_AI_URL", "https://old-private.example/chat")
    assert browser_url({"browser_start_url": ""}) == "about:blank"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://alice:secret@example.com", "https://example.com:wrong", "http://[bad"])
def test_browser_url_rejects_unsafe_or_invalid_destinations(url):
    with pytest.raises(BrowserSetupError):
        validate_browser_url(url)


def test_origin_includes_scheme_and_port():
    assert origin("https://EXAMPLE.com/chat#one") == ("https", "example.com", 443)
    assert origin("http://127.0.0.1:1234/path") != origin("http://127.0.0.1:4321/path")
    assert origin("http://example.com") != origin("https://example.com")


def test_local_driver_has_no_cwd_or_path_implicit_fallback(tmp_path, monkeypatch):
    from app.core.driver.connection import ConnectionManager, TrustedDriverService
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chromedriver").write_text("untrusted")
    monkeypatch.setenv("SE_CHROMEDRIVER", str(tmp_path / "chromedriver"))
    conn = ConnectionManager(9527, config={})
    assert str(tmp_path / "chromedriver") not in conn._candidate_driver_paths()
    service = TrustedDriverService("/explicit/driver", port=12345)
    assert service.path == "/explicit/driver" and service.env_path() is None


@pytest.mark.parametrize("allowed", [False, True])
def test_manager_download_requires_explicit_opt_in_and_never_downloads_chrome(tmp_path, monkeypatch, allowed):
    from app.core.driver import local_chrome as module
    monkeypatch.setattr(module, "local_home", lambda: tmp_path)
    monkeypatch.setenv("SE_DRIVER_MIRROR_URL", "https://untrusted.invalid/")
    process = Mock(returncode=1)
    process.communicate.return_value = ('{"result":{"code":65}}', "")
    process.poll.return_value = 1
    launch = Mock(return_value=process)
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    session = LocalChromeSession({"browser_allow_driver_download": allowed})
    session.binary = "/known/chrome"
    with pytest.raises(BrowserSetupError):
        session._manager_driver()
    command = launch.call_args.args[0]
    assert ("--offline" in command) is not allowed
    assert "--avoid-browser-download" in command
    assert "--skip-driver-in-path" in command and "--avoid-stats" in command
    assert "SE_DRIVER_MIRROR_URL" not in launch.call_args.kwargs["env"]
    assert session.shutdown(0.2)


def test_partial_start_retries_existing_owned_process_and_uses_debugger_version(tmp_path, monkeypatch):
    from app.core.driver import local_chrome as module
    monkeypatch.setattr(module, "local_home", lambda: tmp_path)
    session = LocalChromeSession({"browser_start_url": "about:blank"})
    session.profile.mkdir()
    (session.profile / "DevToolsActivePort").write_text("45678\n/devtools/browser/test-id\n")
    session.process = Mock()
    session.process.poll.return_value = None
    monkeypatch.setattr(module, "find_chrome", Mock(side_effect=AssertionError("must reuse live process")))
    monkeypatch.setattr(module, "executable_version", Mock(side_effect=AssertionError("GUI Chrome --version is not required")))
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"Browser": "Chrome/154.0.8037.57", "webSocketDebuggerUrl": "ws://127.0.0.1:45678/devtools/browser/test-id"})
    monkeypatch.setattr(module, "build_opener", lambda *_: SimpleNamespace(open=lambda *a, **kw: response))
    assert session.start(timeout=0.5) == 45678
    assert session.version == "154.0.8037.57"


def test_chrome_binary_must_be_present_and_explicit_path_is_authoritative(tmp_path, monkeypatch):
    from app.core.driver.local_chrome import find_chrome
    with pytest.raises(BrowserSetupError):
        find_chrome({"chrome_binary": str(tmp_path / "missing")})


def _connector(monkeypatch, current_url="http://127.0.0.1:1234/chat", enabled=True):
    from app.core.driver import ChromeConnector
    from app.core.driver.interaction import InteractionManager
    from app.core.driver.config import SELECTORS
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    connector = ChromeConnector(config={"browser_start_url": "http://127.0.0.1:1234/chat"})
    driver = MagicMock()
    driver.current_url = current_url
    driver.window_handles = ["target"]
    driver.current_window_handle = "target"
    input_element = Mock()
    input_element.is_displayed.return_value = True
    input_element.is_enabled.return_value = enabled
    driver.find_elements.side_effect = lambda by, selector: [input_element] if selector == SELECTORS["input_area"] else []
    connector.conn.driver = driver
    connector.interact = InteractionManager(driver, allowed_origin=origin("http://127.0.0.1:1234/chat"), strict_origin=True)
    return connector, driver, input_element


def test_same_dom_on_foreign_origin_cannot_receive_messages(monkeypatch):
    connector, driver, element = _connector(monkeypatch, current_url="http://127.0.0.1:5678/chat")
    assert not connector.ready_for_input()[0]
    assert not connector.send_message("", "must not send")[0]
    element.send_keys.assert_not_called()
    driver.execute_script.assert_not_called()


def test_disabled_composer_still_allows_stopping_generation(monkeypatch):
    connector, driver, _ = _connector(monkeypatch, enabled=False)
    connector.interact.is_busy = Mock(side_effect=[True, False])
    stop = Mock()
    stop.is_displayed.return_value = stop.is_enabled.return_value = True
    find = driver.find_elements.side_effect
    driver.find_elements.side_effect = lambda by, selector: [stop] if by == "xpath" else find(by, selector)
    assert connector.cancel_generation()[0]
    stop.click.assert_called_once()


def test_single_remaining_tab_is_selected_after_previous_tab_closed(monkeypatch):
    connector, driver, _ = _connector(monkeypatch)
    connector.interact.target_handle = "closed"
    driver.current_window_handle = "closed"
    assert connector.interact.switch_to_chat_tab()
    driver.switch_to.window.assert_called_once_with("target")


@pytest.mark.parametrize("text", ["hello", "取消中文发送"])
def test_cancel_between_input_and_submit_does_not_commit(text):
    from app.core.driver.interaction import InteractionManager
    manager = InteractionManager(MagicMock())
    element, button = Mock(), Mock()
    button.is_displayed.return_value = True
    manager.find_element = Mock(return_value=element)
    manager._chat_submit_state = Mock(return_value={"user_count": 0})
    manager.driver.find_elements.return_value = [button]
    checks = iter([False, False, True])
    ok, message = manager.send_message(text, cancel_check=lambda: next(checks))
    assert not ok and "取消" in message
    button.click.assert_not_called()
    assert all(call.args != ("arguments[0].click();", button) for call in manager.driver.execute_script.call_args_list)
    assert not any("\ue007" in str(call) for call in element.send_keys.call_args_list)


@pytest.mark.parametrize("alias", ["normalize-space(.)='创建新对话'", "@aria-label='创建新对话'"])
def test_new_chat_accepts_exact_create_conversation_button_alias(alias):
    from app.core.driver.interaction import InteractionManager
    driver = MagicMock()
    driver.current_url = "https://example.invalid/chat#old"
    button = Mock()
    button.is_displayed.return_value = button.is_enabled.return_value = True
    button.click.side_effect = lambda: setattr(driver, "current_url", "https://example.invalid/chat#new")
    def find(by, selector):
        if by == "xpath":
            assert alias in selector
            assert "contains(normalize-space(.)" not in selector
            return [button]
        return []
    driver.find_elements.side_effect = find
    assert InteractionManager(driver).new_chat() == (True, "已新建网页会话")
    button.click.assert_called_once()


@pytest.mark.parametrize("false_selector", ["div[class*='session']", "div[class*='chat-item']"])
def test_local_empty_session_list_never_uses_wrappers_or_message_bubbles(monkeypatch, false_selector):
    from app.core.driver.config import SELECTORS
    connector, driver, _ = _connector(monkeypatch)
    connector._ensure_live_window = lambda: True
    driver.execute_script.return_value = "complete"
    wrapper = Mock(text="")
    wrapper.get_attribute.return_value = "chat-sessions" if "session" in false_selector else "chat-item"
    driver.find_elements.side_effect = lambda by, selector: [wrapper] if selector == false_selector else []
    assert connector.get_session_list() == []
    driver.find_elements.assert_called_once_with("css selector", SELECTORS["session_item"])


def test_local_session_list_keeps_exact_real_items(monkeypatch):
    from app.core.driver.config import SELECTORS
    connector, driver, _ = _connector(monkeypatch)
    connector._ensure_live_window = lambda: True
    driver.execute_script.return_value = "complete"
    item = Mock(text="实际会话标题\n今天")
    item.get_attribute.return_value = "aa-sidebar-list-item active"
    driver.find_elements.side_effect = lambda by, selector: [item] if selector == SELECTORS["session_item"] else []
    assert connector.get_session_list() == [{"index": 0, "title": "实际会话标题", "date": "今天", "icon": "", "active": True}]


def test_remote_session_list_preserves_legacy_fallback(monkeypatch):
    connector, driver, _ = _connector(monkeypatch)
    connector.conn.local_desktop = False
    connector._ensure_live_window = lambda: True
    driver.execute_script.return_value = "complete"
    item = Mock(text="旧版远程会话")
    item.get_attribute.return_value = "legacy-session"
    driver.find_elements.side_effect = lambda by, selector: [item] if selector == "div[class*='session']" else []
    result = connector.get_session_list()
    assert len(result) == 1 and result[0]["title"] == "旧版远程会话"
    assert any(call.args == ("css selector", "div[class*='session']") for call in driver.find_elements.call_args_list)
