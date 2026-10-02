import time
from typing import Optional
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy
from PySide6.QtCore import Qt, QTimer
from app.ui.theme import theme_manager
from app.ui.components.chat import ResizableTextBrowser, ToolResultBox
from app.ui.components.editor import CodeBox
from app.core.parsers.markdown_code_block_parser import MarkdownCodeBlockParser
from app.core.logging import get_logger

logger = get_logger("app.ui.chat_bubble_stream", side="ui")


class StreamingChatBubble(QWidget):
    """流式输出气泡，支持实时代码块解析与增量更新。
    
    设计原则：
    - 流式中途就用和最终态一致的组件（CodeBox + ResizableTextBrowser）
    - 未闭合代码块正常渲染，光标只在末尾文本段显示
    - 增量更新：segment 结构不变时只更新最后一段内容，避免重建
    - 节流 100ms，finalize 时强制刷新
    """

    def __init__(self, role: str = "AI", parent=None):
        super().__init__(parent)
        self._role = role
        self._accumulated_text = ""
        self._accumulated_thinking = ""
        self._is_streaming = True
        
        # segment 渲染状态
        self._current_segments = []  # 当前已解析的 segment 列表
        self._segment_widgets = []   # 对应的 widget 列表
        self._last_text_widget: Optional[ResizableTextBrowser] = None  # 最后一个文本段引用（用于显示光标）
        
        # 光标状态
        self._cursor_visible = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(500)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._cursor_timer.start()
        
        # 节流状态
        self._last_render_time = 0.0
        self._pending_render = False
        
        self._init_ui()
        theme_manager.theme_changed.connect(self._apply_theme)

    def _init_ui(self):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)

        self.container = QFrame()
        self.c_layout = QVBoxLayout(self.container)
        self.c_layout.setContentsMargins(10, 8, 10, 8)
        self.c_layout.setSpacing(5)
        self.container.setMaximumWidth(1600)
        self.container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        # AI 气泡靠左
        self.layout.addWidget(self.container, 3)
        self.layout.addStretch(1)

        self._apply_theme()

    def append_stream_text(self, text: str):
        """追加流式文本，触发增量渲染（带节流）。"""
        logger.info("[StreamBubble] append_stream_text | text_len=%d | total_len=%d", len(text), len(self._accumulated_text) + len(text))
        self._accumulated_text += text
        self._schedule_render()

    def append_stream_thinking(self, text: str):
        """追加流式思考过程，触发增量渲染（带节流）。"""
        logger.info(
            "[StreamBubble] append_stream_thinking | text_len=%d | total_len=%d",
            len(text),
            len(self._accumulated_thinking) + len(text),
        )
        self._accumulated_thinking += text
        self._schedule_render()

    def _schedule_render(self):
        self._pending_render = True
        
        now = time.monotonic()
        if now - self._last_render_time >= 0.1:  # 100ms 节流
            self._render_segments()
            self._last_render_time = now
            self._pending_render = False

    def finalize_stream(self, cancelled: bool = False, error_message: str = ""):
        """结束流式，停止光标，刷新最终状态。"""
        self._is_streaming = False
        self._cursor_timer.stop()
        
        if error_message:
            self._accumulated_text += f"\n\n⚠️ 流式传输异常: {error_message}"
        elif cancelled:
            self._accumulated_text += "\n\n[已中断]"
        
        # 强制刷新，确保最终状态完整
        if self._pending_render:
            self._render_segments()
            self._pending_render = False
        
        # 移除光标
        if self._last_text_widget and hasattr(self._last_text_widget, 'raw_text'):
            self._last_text_widget.raw_text = self._last_text_widget.raw_text.rstrip('▌')
            self._last_text_widget.apply_theme()

    def get_accumulated_text(self) -> str:
        return self._accumulated_text

    def get_accumulated_thinking(self) -> str:
        return self._accumulated_thinking

    def _render_segments(self):
        """解析累积文本为 segments，增量更新 UI。"""
        logger.info(
            "[StreamBubble] _render_segments called | text_len=%d | thinking_len=%d",
            len(self._accumulated_text),
            len(self._accumulated_thinking),
        )
        new_segments = []
        if self._accumulated_thinking:
            new_segments.append({"type": "thinking", "content": self._accumulated_thinking})
        new_segments.extend(MarkdownCodeBlockParser.parse_segments(self._accumulated_text))
        
        # 计算结构签名：segment 类型序列
        new_sig = tuple(seg.get('type', '') for seg in new_segments)
        old_sig = tuple(seg.get('type', '') for seg in self._current_segments)
        
        if new_sig == old_sig and len(new_segments) == len(self._segment_widgets):
            # 结构不变，逐段更新内容；thinking 在正文前面时也能继续流式刷新。
            self._update_all_segments(new_segments)
        else:
            # 结构变化，重建所有 widget
            self._rebuild_all_segments(new_segments)
        
        self._current_segments = new_segments

    def _update_all_segments(self, segments: list):
        """结构不变时逐段更新内容。"""
        self._last_text_widget = None
        for i, seg in enumerate(segments):
            if i >= len(self._segment_widgets):
                return
            self._update_segment_widget(self._segment_widgets[i], seg, i == len(segments) - 1)

    def _update_segment_widget(self, widget, seg: dict, is_last: bool):
        """增量更新单个 segment widget。"""
        seg_type = seg.get('type', '')
        content = str(seg.get('content', '') or '')
        
        if seg_type == 'text':
            if isinstance(widget, ResizableTextBrowser):
                # 文本段：更新内容 + 可能显示光标
                display_text = content
                if is_last and self._is_streaming and self._cursor_visible:
                    display_text += '▌'
                widget.raw_text = display_text
                widget.apply_theme()
                if is_last:
                    self._last_text_widget = widget
        
        elif seg_type == 'code':
            if isinstance(widget, CodeBox):
                # 代码段：更新编辑器内容
                widget.editor.setPlainText(content)
                widget.content = content
                # 刷新标题（行数/字符数可能变了）
                widget._refresh_toggle_title()
            # 代码段不显示光标
            if is_last:
                self._last_text_widget = None

        elif seg_type == 'thinking':
            if isinstance(widget, ToolResultBox):
                widget.content = content
                widget.body.setPlainText(content)
            if is_last:
                self._last_text_widget = None

    def _rebuild_all_segments(self, segments: list):
        """重建所有 segment widget（结构变化时调用）。"""
        # 清空现有 widget
        while self.c_layout.count() > 0:
            item = self.c_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self._segment_widgets.clear()
        self._last_text_widget = None
        
        # 重建
        for i, seg in enumerate(segments):
            seg_type = seg.get('type', '')
            content = str(seg.get('content', '') or '')
            
            if seg_type == 'text':
                if not content.strip():
                    continue
                
                # 最后一个文本段可能显示光标
                display_text = content
                is_last = (i == len(segments) - 1)
                if is_last and self._is_streaming and self._cursor_visible:
                    display_text += '▌'
                
                widget = ResizableTextBrowser(display_text)
                self.c_layout.addWidget(widget)
                self._segment_widgets.append(widget)
                
                if is_last:
                    self._last_text_widget = widget
            
            elif seg_type == 'code':
                language = str(seg.get('language', '') or 'code')
                closed = seg.get('closed', True)
                
                # 未闭合代码块用 language + " (输出中)" 标识
                display_lang = language if closed else f"{language} (输出中)"
                
                widget = CodeBox(
                    content=content,
                    language=display_lang,
                    is_ignored=False,
                    is_placeholder=False  # 不是占位符，是正在输出的真实代码
                )
                # 流式中代码块默认展开
                if not widget.is_expanded:
                    widget.toggle_view()
                
                self.c_layout.addWidget(widget)
                self._segment_widgets.append(widget)
                
                # 代码段后，光标归零
                self._last_text_widget = None

            elif seg_type == 'thinking':
                widget = ToolResultBox("🤔 思考过程", content)
                if not widget.expanded:
                    widget.toggle_view()
                self.c_layout.addWidget(widget)
                self._segment_widgets.append(widget)
                self._last_text_widget = None

    def _toggle_cursor(self):
        """切换光标可见性，只影响最后一个文本段。"""
        if not self._is_streaming:
            return
        
        self._cursor_visible = not self._cursor_visible
        
        # 只更新最后一个文本段
        if self._last_text_widget and isinstance(self._last_text_widget, ResizableTextBrowser):
            raw = self._last_text_widget.raw_text.rstrip('▌')
            if self._cursor_visible:
                raw += '▌'
            self._last_text_widget.raw_text = raw
            self._last_text_widget.apply_theme()

    def _apply_theme(self):
        try:
            p = theme_manager.get_palette()
            bg = p.BG_SECONDARY
            color = p.TEXT_PRIMARY
            self.container.setStyleSheet(
                f"QFrame {{ background-color: {bg}; color: {color}; border-radius: 8px; }}"
            )
        except Exception as e:
            logger.warning(e)
