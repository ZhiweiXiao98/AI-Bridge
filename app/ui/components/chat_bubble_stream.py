import logging
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy
from PySide6.QtCore import Qt, QTimer
from app.ui.theme import theme_manager
from app.ui.components.chat import ResizableTextBrowser
from app.core.logging import get_logger

logger = get_logger("app.ui.chat_bubble_stream", side="ui")


class StreamingChatBubble(QWidget):
    def __init__(self, role: str = "AI", parent=None):
        super().__init__(parent)
        self._role = role
        self._accumulated_text = ""
        self._is_streaming = True
        self._init_ui()
        theme_manager.theme_changed.connect(self._apply_theme)

    def _init_ui(self):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(15, 8, 15, 8)

        self.container = QFrame()
        self.c_layout = QVBoxLayout(self.container)
        # 与普通气泡视觉对齐（略收紧）
        self.c_layout.setContentsMargins(14, 10, 14, 10)
        self.c_layout.setSpacing(6)
        self.container.setMaximumWidth(1600)
        self.container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        # AI 气泡靠左
        self.layout.addWidget(self.container, 3)
        self.layout.addStretch(1)

        self._text_browser = ResizableTextBrowser("")
        # 对齐常规聊天文本大小
        self._text_browser.setStyleSheet("font-size: 14px; line-height: 1.6;")
        self.c_layout.addWidget(self._text_browser)

        # 闪烁光标
        self._cursor_visible = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(500)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._cursor_timer.start()

        self._apply_theme()

    def append_stream_text(self, text: str):
        self._accumulated_text += text
        self._render_content()

    def finalize_stream(self, cancelled: bool = False, error_message: str = ""):
        self._is_streaming = False
        self._cursor_timer.stop()
        if error_message:
            self._accumulated_text += f"\n\n⚠️ 流式传输异常: {error_message}"
        elif cancelled:
            self._accumulated_text += "\n\n[已中断]"
        self._render_content()

    def get_accumulated_text(self) -> str:
        return self._accumulated_text

    def _render_content(self):
        display = self._accumulated_text
        if self._is_streaming and self._cursor_visible:
            display += "▌"
        self._text_browser.setHtml(display.replace("\n", "<br>"))
        self._text_browser.adjust_height()

    def _toggle_cursor(self):
        self._cursor_visible = not self._cursor_visible
        if self._is_streaming:
            self._render_content()

    def _apply_theme(self):
        try:
            p = theme_manager.get_palette()
            bg = p.BG_SECONDARY
            color = p.TEXT_PRIMARY
            self.container.setStyleSheet(
                f"QFrame {{ background-color: {bg}; color: {color}; border-radius: 12px; }}"
            )
        except Exception as e:
            logger.warning(e)
