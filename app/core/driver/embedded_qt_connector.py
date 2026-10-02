# filename: app/core/driver/embedded_qt_connector.py
from __future__ import annotations

from typing import Any

from app.core.driver.parser import DOMParser
from app.core.logging import get_logger

logger = get_logger("app.core.driver.embedded_qt", side="worker")


class EmbeddedQtBrowserConnector:
    """
    Connector shell for the in-process Qt WebEngine browser source.

    Qt WebEngine views must live on the Qt UI thread. The worker can select this
    connector today without breaking external Chrome, while the UI-side service
    later attaches a thread-safe executor that runs navigation, JavaScript and
    DOM materialization on hidden WebEngine pages.
    """

    source = "embedded_qt"

    def __init__(self, config: dict[str, Any] | None = None, executor=None):
        self.config = config if isinstance(config, dict) else {}
        self.executor = executor
        self.parser = DOMParser()
        self.interact = None
        self.last_chat_id = None

    @property
    def driver(self):
        return self.executor

    def attach_executor(self, executor) -> None:
        self.executor = executor
        self.interact = executor

    def _not_attached(self, stage: str = "connecting"):
        return False, {
            "stage": stage,
            "error_code": "embedded_browser_executor_not_attached",
            "message": "内置 Qt WebEngine 浏览器源尚未绑定 UI 线程执行器",
        }

    def connect(self):
        if self.executor is None:
            return self._not_attached("connecting")
        if hasattr(self.executor, "connect"):
            return self.executor.connect()
        return True, "内置浏览器执行器已绑定"

    def is_busy(self):
        if self.executor and hasattr(self.executor, "is_busy"):
            return bool(self.executor.is_busy())
        return False

    def send_message(self, selector, text):
        if self.executor and hasattr(self.executor, "send_message"):
            return self.executor.send_message(selector, text)
        return False, "embedded_browser_executor_not_attached"

    def open_conversation_target(self, conversation_url="", conversation_name="", timeout=20):
        if self.executor and hasattr(self.executor, "open_conversation_target"):
            return self.executor.open_conversation_target(
                conversation_url=conversation_url,
                conversation_name=conversation_name,
                timeout=timeout,
            )
        return self._not_attached("switching_conversation")

    def clear_conversation(self, timeout=10):
        if self.executor and hasattr(self.executor, "clear_conversation"):
            return self.executor.clear_conversation(timeout=timeout)
        return self._not_attached("resetting")

    def wait_until_idle(self, timeout=180, stable_seconds=1.0, progress_callback=None, progress_interval=0.8):
        if self.executor and hasattr(self.executor, "wait_until_idle"):
            return self.executor.wait_until_idle(
                timeout=timeout,
                stable_seconds=stable_seconds,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )
        return self._not_attached("waiting")

    def extract_latest_ai_response(self, request_id=None, transient=False, require_request_id=True):
        if self.executor and hasattr(self.executor, "extract_latest_ai_response"):
            return self.executor.extract_latest_ai_response(
                request_id=request_id,
                transient=transient,
                require_request_id=require_request_id,
            )
        return self._not_attached("extracting")

    def materialize_chat_dom(self, transient_last_ai=False, max_passes=240):
        if self.executor and hasattr(self.executor, "materialize_chat_dom"):
            return self.executor.materialize_chat_dom(
                transient_last_ai=transient_last_ai,
                max_passes=max_passes,
            )
        return [], False, False

    def get_chat_content(self, target_class="chat-text", auto_wake=True, transient_last_ai=False):
        if self.executor and hasattr(self.executor, "get_chat_content"):
            return self.executor.get_chat_content(
                target_class=target_class,
                auto_wake=auto_wake,
                transient_last_ai=transient_last_ai,
            )
        return [], False

    def get_chat_content_incremental(self, transient_last_ai=False):
        if self.executor and hasattr(self.executor, "get_chat_content_incremental"):
            return self.executor.get_chat_content_incremental(transient_last_ai=transient_last_ai)
        return [], False, False

    def force_scroll(self, interrupt_callback=None):
        if self.executor and hasattr(self.executor, "force_scroll"):
            return self.executor.force_scroll(interrupt_callback=interrupt_callback)
        return None

    def get_session_list(self):
        if self.executor and hasattr(self.executor, "get_session_list"):
            return self.executor.get_session_list()
        return []

    def get_chat_title_id(self):
        if self.executor and hasattr(self.executor, "get_chat_title_id"):
            return self.executor.get_chat_title_id()
        return "embedded_qt_default"

    def get_active_session_text(self):
        if self.executor and hasattr(self.executor, "get_active_session_text"):
            return self.executor.get_active_session_text()
        return None

    def switch_session(self, index):
        if self.executor and hasattr(self.executor, "switch_session"):
            return self.executor.switch_session(index)
        return False

    def get_last_ai_message_id(self):
        if self.executor and hasattr(self.executor, "get_last_ai_message_id"):
            return self.executor.get_last_ai_message_id()
        return ""

    def check_last_ai_message_for_tool(self):
        if self.executor and hasattr(self.executor, "check_last_ai_message_for_tool"):
            return self.executor.check_last_ai_message_for_tool()
        return None

    def clear_message_cache(self):
        if self.executor and hasattr(self.executor, "clear_message_cache"):
            return self.executor.clear_message_cache()
        return None

    def click_ai_message_action(self, action, message_id=None, confirm_delete=False, timeout=5):
        if self.executor and hasattr(self.executor, "click_ai_message_action"):
            return self.executor.click_ai_message_action(
                action,
                message_id=message_id,
                confirm_delete=confirm_delete,
                timeout=timeout,
            )
        return False, "embedded_browser_executor_not_attached"

    def paste_to_input(self, selector="textarea", auto_send=False):
        if self.executor and hasattr(self.executor, "paste_to_input"):
            return self.executor.paste_to_input(selector=selector, auto_send=auto_send)
        return False, "embedded_browser_executor_not_attached"

    def navigate(self, url):
        if self.executor and hasattr(self.executor, "navigate"):
            return self.executor.navigate(url)
        return False

    def new_chat(self):
        if self.executor and hasattr(self.executor, "new_chat"):
            return self.executor.new_chat()
        return False, "embedded_browser_executor_not_attached"

    def manual_toggle_block(self, offset, block_idx, total_blocks, fingerprint=None):
        if self.executor and hasattr(self.executor, "manual_toggle_block"):
            return self.executor.manual_toggle_block(offset, block_idx, total_blocks, fingerprint=fingerprint)
        return None

