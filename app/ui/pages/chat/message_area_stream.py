import logging
from typing import Optional
from PySide6.QtCore import QObject, QTimer
from app.core.logging import get_logger

logger = get_logger("app.ui.message_area_stream", side="ui")

class MessageAreaStreamManager(QObject):
    def __init__(self, message_area, parent=None):
        super().__init__(parent)
        self._message_area = message_area
        self._active_bubble = None
        self._active_stream_id = None
        self._typing_label = None
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._auto_scroll)

    def begin_stream(self, stream_id: str, conversation_id: str = ""):
        logger.info(f"[MessageAreaStream] begin_stream | stream_id={stream_id}")
        self._active_stream_id = stream_id
        self._show_typing_indicator()
        self._active_bubble = self._create_stream_bubble()
        logger.info(f"[MessageAreaStream] 创建气泡 | stream_id={stream_id}")
        self._scroll_timer.start()

    def append_text(self, stream_id: str, text: str):
        logger.debug(f"[MessageAreaStream] append_text | stream_id={stream_id} | text_len={len(text)}")
        if stream_id != self._active_stream_id:
            logger.warning(f"[MessageAreaStream] stream_id 不匹配 | expected={self._active_stream_id} | got={stream_id}")
            return
        if self._active_bubble and hasattr(self._active_bubble, 'append_stream_text'):
            logger.debug(f"[MessageAreaStream] 追加文本到气泡 | len={len(text)}")
            self._active_bubble.append_stream_text(text)
        else:
            logger.warning(f"[MessageAreaStream] 气泡不可用或不支持 append_stream_text")

    def end_stream(self, stream_id: str, cancelled: bool = False, error_message: str = ""):
        """结束首轮 assistant 流式临时气泡；这里只表示 initial stream finished，不代表整轮 finalized。"""
        logger.info(f"[MessageAreaStream] end_stream | stream_id={stream_id} | cancelled={cancelled} | error={error_message}")
        if stream_id != self._active_stream_id:
            logger.warning(f"[MessageAreaStream] stream_id 不匹配 | expected={self._active_stream_id} | got={stream_id}")
            return
        self._hide_typing_indicator()
        self._scroll_timer.stop()
        if self._active_bubble:
            if hasattr(self._active_bubble, 'finalize_stream'):
                logger.info(f"[MessageAreaStream] 完成气泡 | stream_id={stream_id}")
                self._active_bubble.finalize_stream(cancelled=cancelled, error_message=error_message)
            
            # 首轮流式结束后移除临时气泡；是否由正式历史接管，交给上层 round_state 决定
            try:
                self._active_bubble.setParent(None)
                self._active_bubble.deleteLater()
            except Exception as e:
                logger.warning(e)
                
        self._active_bubble = None
        self._active_stream_id = None
        self._auto_scroll()
    def _create_stream_bubble(self):
        from app.ui.components.chat_bubble_stream import StreamingChatBubble
        bubble = StreamingChatBubble(role="AI", parent=self._message_area)

        # 优先插入 MessageArea 的真实消息布局（chat_layout）
        if hasattr(self._message_area, 'chat_layout'):
            layout = self._message_area.chat_layout
            insert_idx = max(0, layout.count() - 1)  # 在末尾 stretch 之前
            layout.insertWidget(insert_idx, bubble)
        elif hasattr(self._message_area, 'bubble_layout'):
            self._message_area.bubble_layout.addWidget(bubble)
        elif self._message_area.layout():
            self._message_area.layout().addWidget(bubble)

        return bubble

    def _show_typing_indicator(self):
        if not self._typing_label:
            from PySide6.QtWidgets import QLabel
            from PySide6.QtCore import Qt
            self._typing_label = QLabel("AI 正在输入…")
            self._typing_label.setStyleSheet("color: #888; font-size: 13px; padding: 6px 12px;")
            self._typing_label.setAlignment(Qt.AlignLeft)

        # 优先插入 MessageArea 的真实消息布局（chat_layout）
        if hasattr(self._message_area, 'chat_layout'):
            layout = self._message_area.chat_layout
            insert_idx = max(0, layout.count() - 1)  # 在末尾 stretch 之前
            layout.insertWidget(insert_idx, self._typing_label)
        elif hasattr(self._message_area, 'bubble_layout'):
            self._message_area.bubble_layout.addWidget(self._typing_label)
        elif self._message_area.layout():
            self._message_area.layout().addWidget(self._typing_label)

        self._typing_label.show()

    def _hide_typing_indicator(self):
        if self._typing_label:
            self._typing_label.hide()
            if self._typing_label.parent():
                self._typing_label.setParent(None)

    def reset_stream_ui(self):
        """强制清理流式临时UI（切会话/切模式时调用）。"""
        try:
            self._hide_typing_indicator()
        except Exception as e:
            logger.warning(e)
        try:
            self._scroll_timer.stop()
        except Exception as e:
            logger.warning(e)
        try:
            if self._active_bubble:
                self._active_bubble.setParent(None)
                self._active_bubble.deleteLater()
        except Exception as e:
            logger.warning(e)
        self._active_bubble = None
        self._active_stream_id = None

    def _auto_scroll(self):
        if hasattr(self._message_area, 'force_scroll_bottom'):
            self._message_area.force_scroll_bottom()
