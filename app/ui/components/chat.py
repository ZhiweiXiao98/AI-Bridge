# filename: app/ui/components/chat.py
import re
import json
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QPushButton,
                               QLabel, QApplication, QMenu, QSpinBox, QTextBrowser,
                               QSizePolicy, QCheckBox, QPlainTextEdit, QScrollArea)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QFont, QColor, QCursor, QDesktopServices
from .editor import CodeBox
from .base import ImageBox
from app.ui.theme import Theme, Palette, theme_manager
from app.core.logging import get_logger

logger = get_logger("app.ui.chat", side="ui")


def _format_tool_arguments(arguments) -> str:
    if isinstance(arguments, dict):
        if not arguments:
            return '(无参数)'
        lines = []
        for key, value in arguments.items():
            lines.append(f'- {key}: {value}')
        return '\n'.join(lines)
    text = str(arguments or '').strip()
    return text or '(无参数)'


def _build_bound_tool_box(seg, bound_results):
    tool_name = seg.get('tool_name', 'unknown')
    tool_call_id = str(seg.get('tool_call_id') or '').strip()
    args_text = _format_tool_arguments(seg.get('arguments', seg.get('content', '')))
    runtime_status = seg.get('runtime_status') or {}
    status_text = str(runtime_status.get('message', '') or '').strip()
    runtime_bound_result = seg.get('_bound_runtime_result') if isinstance(seg.get('_bound_runtime_result'), dict) else {}
    if bound_results:
        result_chunks = []
        success_values = []
        for result_seg in bound_results:
            ok = bool(result_seg.get('success', True))
            success_values.append(ok)
            result_title = '✅ 执行结果' if ok else '❌ 执行结果'
            result_chunks.append(f"{result_title}\n{str(result_seg.get('content', '') or '')}")
        merged_result = "\n\n".join(result_chunks)
        overall_success = all(success_values) if success_values else None
        if not status_text:
            status_text = '执行完成' if overall_success else '执行失败'
        return ToolCallCard(tool_name, args_text, result_text=merged_result, status_text=status_text, success=overall_success, tool_call_id=tool_call_id)
    if runtime_bound_result:
        runtime_content = str(runtime_bound_result.get('content', '') or '')
        runtime_success = runtime_bound_result.get('success', None)
        if not status_text:
            if runtime_success is True:
                status_text = '执行完成'
            elif runtime_success is False:
                status_text = '执行失败'
        return ToolCallCard(tool_name, args_text, result_text=runtime_content, status_text=status_text, success=runtime_success, tool_call_id=tool_call_id)
    return ToolCallCard(tool_name, args_text, status_text=status_text, tool_call_id=tool_call_id)


def _try_build_tool_call_box_from_code_seg(seg):
    if not isinstance(seg, dict):
        return None
    if str(seg.get('type', '') or '').strip().lower() != 'code':
        return None
    lang = str(seg.get('language', '') or '').strip().lower()
    tool_call_id = str(seg.get('tool_call_id') or '').strip()
    has_bound_results = isinstance(seg.get('_bound_results'), list) and bool(seg.get('_bound_results'))
    if lang != 'tool_call' and not tool_call_id and not has_bound_results:
        return None
    raw_text = str(seg.get('content', '') or '').strip()
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if 'name' not in parsed or 'arguments' not in parsed:
        return None
    normalized_seg = {
        'type': 'tool_call',
        'tool_name': str(parsed.get('name') or 'unknown'),
        'arguments': parsed.get('arguments', {}) or {},
        'content': raw_text,
        'tool_call_id': tool_call_id,
        'runtime_status': seg.get('runtime_status') or {},
        '_bound_runtime_result': seg.get('_bound_runtime_result') if isinstance(seg.get('_bound_runtime_result'), dict) else {},
    }
    return _build_bound_tool_box(normalized_seg, [])


def _code_seg_should_render_as_tool_call(seg):
    if not isinstance(seg, dict):
        return False
    if str(seg.get('type', '') or '').strip().lower() != 'code':
        return False
    lang = str(seg.get('language', '') or '').strip().lower()
    tool_call_id = str(seg.get('tool_call_id') or '').strip()
    has_bound_results = isinstance(seg.get('_bound_results'), list) and bool(seg.get('_bound_results'))
    if lang != 'tool_call' and not tool_call_id and not has_bound_results:
        return False
    raw_text = str(seg.get('content', '') or '').strip()
    if not raw_text:
        return False
    try:
        parsed = json.loads(raw_text)
    except Exception:
        return False
    return isinstance(parsed, dict) and 'name' in parsed and 'arguments' in parsed

class ResizableTextBrowser(QTextBrowser):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.raw_text = text

        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background-color: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.document().setDocumentMargin(0)
        self.textChanged.connect(self.adjust_height)

        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def apply_theme(self):
        p = theme_manager.get_palette()
        is_light = p.BG_PRIMARY.upper().startswith("#F")

        formatted = self.raw_text.replace("\n", "<br>")
        formatted = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', formatted)

        if is_light:
            formatted = re.sub(r'background-color:\s*#[0-9a-fA-F]{6};?', '', formatted)
            formatted = re.sub(r'background-color:\s*rgb\([^)]+\);?', '', formatted)
            formatted = re.sub(r'color:\s*#d1d5db;?', f'color: {p.TEXT_PRIMARY};', formatted)

        self.setHtml(f"<div style='font-family: Segoe UI Emoji, Apple Color Emoji, Noto Color Emoji, Segoe UI Symbol, Segoe UI, sans-serif; font-size: 13px; line-height: 1.45; color: {p.TEXT_PRIMARY};'>{formatted}</div>")
        self.adjust_height()

    def adjust_height(self):
        doc_height = self.document().size().height()
        self.setFixedHeight(int(doc_height + 10))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_height()

    def wheelEvent(self, event):
        event.ignore()


class ToolCallCard(QFrame):
    def __init__(self, tool_name: str, arguments_text: str, result_text: str = '', status_text: str = '', success: bool | None = None, tool_call_id: str = '', parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.tool_name = tool_name or 'unknown'
        self.arguments_text = arguments_text or '(无参数)'
        self.result_text = result_text or ''
        self.status_text = status_text or ''
        self.success = success
        self.tool_call_id = str(tool_call_id or '').strip()
        self.is_expanded = False
        self._init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QFrame()
        self.header.setMinimumWidth(0)
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 5, 8, 5)
        header_layout.setSpacing(4)

        self.toggle_btn = QPushButton('▶')
        self.toggle_btn.setFixedSize(24, 24)
        self.toggle_btn.setStyleSheet('font-size: 14px;')
        self.toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.toggle_btn.clicked.connect(self.toggle_view)
        header_layout.addWidget(self.toggle_btn)

        self.title_lbl = QLabel(self._build_title())
        self.title_lbl.setMinimumWidth(20)
        self.title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self.title_lbl, 1)

        self.copy_btn = QPushButton('📋')
        self.copy_btn.setFixedSize(24, 24)
        self.copy_btn.setToolTip('复制')
        self.copy_btn.clicked.connect(self.copy_content)
        header_layout.addWidget(self.copy_btn)
        layout.addWidget(self.header)

        self.args_box = QPlainTextEdit()
        self.args_box.setMinimumWidth(0)
        self.args_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.args_box.setReadOnly(True)
        self.args_box.setPlainText(f'参数:\n{self.arguments_text}')
        self.args_box.setVisible(False)
        self.args_box.setMaximumHeight(120)
        layout.addWidget(self.args_box)

        self.status_lbl = QLabel(self.status_text)
        self.status_lbl.setVisible(False)
        layout.addWidget(self.status_lbl)

        self.result_box = QPlainTextEdit()
        self.result_box.setMinimumWidth(0)
        self.result_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.result_box.setReadOnly(True)
        self.result_box.setPlainText(self.result_text)
        self.result_box.setVisible(False)
        self.result_box.setMaximumHeight(220)
        layout.addWidget(self.result_box)

    def _build_title(self):
        # 状态图标
        if self.success is True:
            icon = '✅'
        elif self.success is False:
            icon = '❌'
        else:
            icon = '⏳'
        # 操作摘要：从参数中提取关键信息
        summary = self._extract_summary()
        parts = [f'{icon} {self.tool_name}']
        if summary:
            parts.append(summary)
        if self.status_text:
            parts.append(self.status_text)
        return ' · '.join(parts)

    def _extract_summary(self) -> str:
        """从参数文本中提取简短摘要，让用户一眼看出做了什么"""
        text = self.arguments_text or ''
        if not text or text == '(无参数)':
            return ''
        # 尝试提取 path / operation 等关键字段
        summary_parts = []
        for line in text.split('\n'):
            line = line.strip().lstrip('- ')
            if ':' in line:
                key, _, val = line.partition(':')
                key = key.strip().lower()
                val = val.strip()
                if key == 'operation':
                    summary_parts.insert(0, val)
                elif key == 'path':
                    # 只取文件名部分，避免太长
                    short_path = val.split('/')[-1] if '/' in val else val
                    summary_parts.append(short_path)
                elif key == 'query' and not summary_parts:
                    summary_parts.append(val[:30])
        if summary_parts:
            return ' → '.join(summary_parts[:3])
        # 兜底：取第一行前 40 字符
        first_line = text.split('\n')[0].strip().lstrip('- ')
        return first_line[:40] if first_line else ''

    def _refresh_title(self):
        self.title_lbl.setText(self._build_title())
        self.toggle_btn.setText('▼' if self.is_expanded else '▶')

    def toggle_view(self):
        self.is_expanded = not self.is_expanded
        self.args_box.setVisible(self.is_expanded)
        self.status_lbl.setVisible(self.is_expanded and bool(self.status_text.strip()))
        self.result_box.setVisible(self.is_expanded and bool(self.result_text.strip()))
        self._refresh_title()

    def copy_content(self):
        merged = f'参数:\n{self.arguments_text}'
        if self.status_text:
            merged += f'\n\n状态:\n{self.status_text}'
        if self.result_text:
            merged += f'\n\n结果:\n{self.result_text}'
        QApplication.clipboard().setText(merged)
        self.copy_btn.setText('✅ 已复制')
        QApplication.processEvents()

    def set_status_text(self, text: str):
        self.status_text = str(text or '').strip()
        self.status_lbl.setText(self.status_text)
        self.status_lbl.setVisible(self.is_expanded and bool(self.status_text))
        self._refresh_title()

    def set_result_text(self, text: str):
        self.result_text = str(text or '')
        self.result_box.setPlainText(self.result_text)
        self.result_box.setVisible(self.is_expanded and bool(self.result_text.strip()))
        self._refresh_title()

    def set_success(self, success):
        self.success = success
        self.apply_theme()

    def update_runtime_status(self, payload: dict | None = None):
        payload = payload if isinstance(payload, dict) else {}
        message = str(payload.get('message', '') or '').strip()
        status = str(payload.get('status', '') or '').strip()
        if not message:
            if status == 'completed':
                message = '执行完成'
            elif status == 'failed':
                message = '执行失败'
            elif status == 'running':
                message = f'正在执行 {self.tool_name}...'
        self.set_status_text(message)
        if status == 'completed':
            self.set_success(True)
        elif status == 'failed':
            self.set_success(False)

    def apply_theme(self):
        p = theme_manager.get_palette()
        border_color = p.BORDER
        if self.success is True:
            border_color = p.TEXT_SUCCESS
        elif self.success is False:
            border_color = p.BTN_WARNING
        self.setStyleSheet(
            f'QFrame {{ background-color: {p.BG_SECONDARY}; border: 1px solid {border_color}; border-radius: 8px; }}'
        )
        self.header.setStyleSheet(
            f'background-color: {p.BG_TERTIARY}; border: none; border-top-left-radius: 8px; border-top-right-radius: 8px;'
        )
        self.title_lbl.setStyleSheet(f'color: {p.ACCENT_PRIMARY}; font-weight: bold; border: none;')
        self.toggle_btn.setStyleSheet(
            f'QPushButton {{ border: none; color: {p.ACCENT_PRIMARY}; background: transparent; font-weight: bold; }} '
            f'QPushButton:hover {{ color: {p.TEXT_PRIMARY}; }}'
        )
        self.copy_btn.setStyleSheet(
            f'QPushButton {{ border: none; color: {p.TEXT_SECONDARY}; background: transparent; font-size: 10px; }} '
            f'QPushButton:hover {{ color: {p.TEXT_PRIMARY}; }}'
        )
        self.status_lbl.setStyleSheet(f'color: {p.TEXT_SECONDARY}; padding: 2px 8px; border: none;')
        box_style = (
            f'QPlainTextEdit {{ background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY}; '
            f'border: 1px solid {p.BORDER}; border-radius: 6px; padding: 8px; '
            f'font-family: Segoe UI Emoji, Apple Color Emoji, Noto Color Emoji, Segoe UI Symbol, Segoe UI, sans-serif; }}'
        )
        self.args_box.setStyleSheet(box_style)
        self.result_box.setStyleSheet(box_style)


class ToolResultBox(QFrame):
    def __init__(self, summary: str, content: str, parent=None):
        super().__init__(parent)
        self.summary = summary or '🔧 工具执行结果'
        self.content = content or ''
        self.expanded = False
        self._init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QFrame()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 6, 10, 6)

        self.toggle_btn = QPushButton(f'▶ {self.summary}')
        self.toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.toggle_btn.clicked.connect(self.toggle_view)
        header_layout.addWidget(self.toggle_btn)
        header_layout.addStretch()

        self.copy_btn = QPushButton('📋 复制')
        self.copy_btn.clicked.connect(self.copy_content)
        header_layout.addWidget(self.copy_btn)

        layout.addWidget(self.header)

        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setPlainText(self.content)
        self.body.setVisible(False)
        self.body.setMaximumHeight(220)
        layout.addWidget(self.body)

    def toggle_view(self):
        self.expanded = not self.expanded
        self.body.setVisible(self.expanded)
        arrow = '▼' if self.expanded else '▶'
        self.toggle_btn.setText(f'{arrow} {self.summary}')

    def copy_content(self):
        QApplication.clipboard().setText(self.content)
        self.copy_btn.setText('✅ 已复制')
        QApplication.processEvents()

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.header.setStyleSheet(
            f'background-color: {p.BG_TERTIARY}; border: 1px solid {p.BORDER}; '
            f'border-top-left-radius: 6px; border-top-right-radius: 6px;'
        )
        self.toggle_btn.setStyleSheet(
            f'QPushButton {{ border: none; color: {p.BTN_WARNING}; font-weight: bold; text-align: left; }} '
            f'QPushButton:hover {{ color: {p.ACCENT_PRIMARY}; }}'
        )
        self.copy_btn.setStyleSheet(
            f'QPushButton {{ border: none; color: {p.TEXT_SECONDARY}; }} '
            f'QPushButton:hover {{ color: {p.TEXT_PRIMARY}; }}'
        )
        self.body.setStyleSheet(
            f'QPlainTextEdit {{ background-color: {p.BG_SECONDARY}; color: {p.TEXT_PRIMARY}; '
            f'border: 1px solid {p.BORDER}; border-top: none; '
            f'border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; padding: 8px; '
            f'font-family: Segoe UI Emoji, Apple Color Emoji, Noto Color Emoji, Segoe UI Symbol, Segoe UI, sans-serif; }}'
        )

class ChatBubble(QWidget):
    request_remote_action = Signal(int, int, int)
    request_code_apply = Signal(str, str)
    request_discard_relay = Signal(str, str)
    request_undiscard_relay = Signal(str, str)
    request_multi_select_mode = Signal(int)
    selection_changed = Signal(int, bool)

    def __init__(self, message_data, is_user=True, index=0, parent=None):
        super().__init__(parent)
        self.index = index
        self.is_user = is_user
        self.message_id = str(message_data.get('id', '')) if isinstance(message_data, dict) else ''
        self.selection_mode = False
        self.selected = False
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.layout = QHBoxLayout(self); self.layout.setContentsMargins(10, 5, 10, 5)
        self.current_data = None
        self._tool_cards_by_id = {}
        self.container = QFrame()
        self.container.setMinimumWidth(0)
        self.container.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.c_layout = QVBoxLayout(self.container); self.c_layout.setContentsMargins(10, 8, 10, 8); self.c_layout.setSpacing(5)
        self.container.setMaximumWidth(1600)
        self.container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.meta_box = QWidget()
        self.meta_box.setMinimumWidth(0)
        self.meta_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        meta_layout = QHBoxLayout(self.meta_box); meta_layout.setContentsMargins(0,0,0,0); meta_layout.setSpacing(5)

        self.turn_box = QSpinBox()
        self.turn_box.setMinimumWidth(32)
        self.turn_box.setMaximumWidth(48)
        self.turn_box.setRange(0, 999999)
        self.turn_box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.turn_box.setPrefix("Turn ")
        self.turn_box.setReadOnly(True)
        self.turn_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.select_box = QCheckBox()
        self.select_box.setVisible(False)
        self.select_box.toggled.connect(self._on_selection_toggled)

        self._content_scroll = None
        self._expand_btn = None
        self._copy_btn = None
        self._is_expanded = False
        self._COLLAPSE_HEIGHT = 900

        if is_user:
            # 用户气泡：用 QScrollArea 包裹 container，支持长消息折叠滚动
            self._content_scroll = QScrollArea()
            self._content_scroll.setWidget(self.container)
            self._content_scroll.setWidgetResizable(True)
            self._content_scroll.setFrameShape(QFrame.Shape.NoFrame)
            self._content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._content_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._content_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

            # 底部操作栏：展开 + 复制
            self._expand_btn = QPushButton("展开 ▼")
            self._expand_btn.setFixedHeight(24)
            self._expand_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._expand_btn.clicked.connect(self._toggle_expand)
            self._expand_btn.setVisible(False)

            self._copy_btn = QPushButton("复制")
            self._copy_btn.setFixedHeight(24)
            self._copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._copy_btn.clicked.connect(self._copy_user_message)
            self._copy_btn.setVisible(False)

            action_row = QWidget()
            action_row_layout = QHBoxLayout(action_row)
            action_row_layout.setContentsMargins(0, 0, 0, 0)
            action_row_layout.setSpacing(6)
            action_row_layout.addWidget(self._expand_btn)
            action_row_layout.addWidget(self._copy_btn)
            action_row_layout.addStretch()
            self._action_row = action_row

            wrapper = QWidget()
            wrapper.setMinimumWidth(0)
            wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            wrapper_layout = QVBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(2)
            # meta_box 放在滚动区外面，不跟随滚动
            wrapper_layout.addWidget(self.meta_box)
            wrapper_layout.addWidget(self._content_scroll)
            wrapper_layout.addWidget(action_row)

            self.layout.addStretch(1)
            self.layout.addWidget(wrapper, 3)
            meta_layout.addStretch(); meta_layout.addWidget(self.select_box); meta_layout.addWidget(self.turn_box)
        else:
            self.layout.addWidget(self.container, 3)
            self.layout.addStretch(1)
            meta_layout.addWidget(self.turn_box); meta_layout.addWidget(self.select_box); meta_layout.addStretch()
            self.c_layout.addWidget(self.meta_box)

        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

        self.update_content(message_data, index)

    def apply_theme(self):
        p = theme_manager.get_palette()

        if self.is_user:
            bg = p.ACCENT_PRIMARY
            color = "white"
            self.turn_box.setStyleSheet(f"background: transparent; border: none; font-weight: bold; font-family: Consolas; font-size: 10px; color: {p.ACCENT_PRIMARY};")
        else:
            bg = p.BG_SECONDARY
            color = p.TEXT_PRIMARY
            self.turn_box.setStyleSheet(f"background: transparent; border: none; font-weight: bold; font-family: Consolas; font-size: 10px; color: {p.TEXT_SECONDARY};")

        border = p.ACCENT_PRIMARY if self.selected else 'transparent'
        self.container.setStyleSheet(f"QFrame {{ background-color: {bg}; color: {color}; border-radius: 8px; border: 1px solid {border}; }}")

        if self._expand_btn or self._copy_btn:
            _action_btn_style = f"QPushButton {{ background: {p.BG_TERTIARY}; border: 1px solid {p.BORDER}; border-radius: 4px; color: {p.TEXT_SECONDARY}; font-size: 11px; padding: 2px 10px; }} QPushButton:hover {{ background: {p.BORDER}; color: {p.TEXT_PRIMARY}; }}"
            if self._expand_btn:
                self._expand_btn.setStyleSheet(_action_btn_style)
            if self._copy_btn:
                self._copy_btn.setStyleSheet(_action_btn_style)

    def _toggle_expand(self):
        """切换用户消息的展开/折叠状态。"""
        if not self._content_scroll:
            return
        self._is_expanded = not self._is_expanded
        if self._is_expanded:
            # 展开：取消固定高度，让内容完全显示
            self._content_scroll.setMinimumHeight(0)
            self._content_scroll.setMaximumHeight(16777215)
            content_h = self.c_layout.sizeHint().height()
            margins = self.c_layout.contentsMargins()
            content_h += margins.top() + margins.bottom()
            self._content_scroll.setFixedHeight(content_h)
            self._expand_btn.setText("收起 ▲")
        else:
            self._content_scroll.setFixedHeight(self._COLLAPSE_HEIGHT)
            self._expand_btn.setText("展开 ▼")

    def _copy_user_message(self):
        """复制用户消息全文到剪贴板。"""
        text = self._extract_full_message_text(self.current_data)
        if text:
            QApplication.clipboard().setText(text)

    def _check_collapse(self):
        """检查用户消息内容高度，超过阈值则启用折叠。"""
        if not self._content_scroll or not self.is_user:
            return
        # 延迟执行，等布局完成
        QTimer.singleShot(100, self._do_check_collapse)

    def _do_check_collapse(self):
        """实际执行折叠检查，基于内容实际高度。"""
        if not self._content_scroll:
            return
        # 获取内容自然高度
        content_h = self.c_layout.sizeHint().height()
        margins = self.c_layout.contentsMargins()
        content_h += margins.top() + margins.bottom()
        seg_count = self.c_layout.count()

        needs_collapse = content_h > self._COLLAPSE_HEIGHT
        if needs_collapse:
            if not self._is_expanded:
                self._content_scroll.setFixedHeight(self._COLLAPSE_HEIGHT)
            self._expand_btn.setVisible(True)
            self._copy_btn.setVisible(True)
        else:
            # 不需要折叠：让 scroll area 完全展开到内容高度
            self._content_scroll.setFixedHeight(max(content_h, 30))
            self._expand_btn.setVisible(False)
            self._copy_btn.setVisible(seg_count > 0)

    def _on_selection_toggled(self, checked):
        self.selected = bool(checked)
        self.apply_theme()
        self.selection_changed.emit(self.index, bool(checked))

    def set_selection_mode(self, enabled: bool, checked: bool = False):
        self.selection_mode = bool(enabled)
        self.select_box.setVisible(self.selection_mode)
        self.select_box.blockSignals(True)
        self.select_box.setChecked(bool(checked) if self.selection_mode else False)
        self.select_box.blockSignals(False)
        self.selected = bool(checked) if self.selection_mode else False
        self.apply_theme()

    def _extract_full_message_text(self, message_data):
        if isinstance(message_data, str):
            return message_data
        if not isinstance(message_data, dict):
            return ""
        raw_content = message_data.get('raw_content')
        if isinstance(raw_content, str) and raw_content:
            return raw_content
        parts = []
        for seg in message_data.get('segments', []) or []:
            seg_type = seg.get('type')
            if seg_type == 'text':
                parts.append(seg.get('content', ''))
            elif seg_type == 'code':
                code = seg.get('content', '')
                lang = seg.get('language', '')
                if lang:
                    parts.append(f"```{lang}{chr(10)}{code}{chr(10)}```")
                else:
                    parts.append(f"```{chr(10)}{code}{chr(10)}```")
            elif seg_type == 'code_placeholder':
                placeholder = str(seg.get('placeholder_text', '') or '检测到代码块，正在整理完整内容...').strip()
                if placeholder:
                    parts.append(placeholder)
        return chr(10).join([p for p in parts if p])

    def _try_incremental_update(self, new_segments):
        """尝试增量更新：如果 segment 结构没变，只更新内容，不销毁重建。

        返回 True 表示增量更新成功，False 表示需要全量重建。
        """
        old_segments = (self.current_data.get('segments') or []) if isinstance(self.current_data, dict) else []
        if not old_segments or not new_segments:
            return False

        if len(old_segments) != len(new_segments):
            return False

        for old_seg, new_seg in zip(old_segments, new_segments):
            if not isinstance(old_seg, dict) or not isinstance(new_seg, dict):
                return False
            if old_seg.get('type') != new_seg.get('type'):
                return False

        widgets = []
        for i in range(self.c_layout.count()):
            item = self.c_layout.itemAt(i)
            if item and item.widget():
                widgets.append(item.widget())

        content_widgets = widgets[1:]

        if len(content_widgets) != len(new_segments):
            return False

        for widget, new_seg in zip(content_widgets, new_segments):
            seg_type = new_seg.get('type', '')
            content = str(new_seg.get('content', '') or '')

            if seg_type == 'text':
                if hasattr(widget, 'setHtml'):
                    old_text = widget.toPlainText() if hasattr(widget, 'toPlainText') else ''
                    new_plain = re.sub(r'<[^>]+>', '', content)
                    if old_text != new_plain:
                        widget.raw_text = content
                        widget.setHtml(content)
                else:
                    return False
            elif seg_type == 'code':
                if isinstance(widget, CodeBox):
                    if _code_seg_should_render_as_tool_call(new_seg):
                        return False
                    old_content = widget.editor.toPlainText() if hasattr(widget, 'editor') else ''
                    if old_content != content:
                        widget.content = content
                        widget.editor.setPlainText(content)
                        line_count = content.count('\n') + 1
                        height = min(400, max(60, line_count * 21 + 20))
                        widget.editor.setFixedHeight(int(height))
                    new_lang = str(new_seg.get('language', '') or 'Code')
                    tool_meta = new_seg.get('tool_meta') or {}
                    display_title = tool_meta.get('summary') or new_lang
                    widget.language = display_title
                    if hasattr(widget, '_refresh_toggle_title'):
                        widget._refresh_toggle_title()
                elif isinstance(widget, ToolCallCard):
                    prev_seg = getattr(widget, '_seg_data', {}) if isinstance(getattr(widget, '_seg_data', {}), dict) else {}
                    if (
                        _code_seg_should_render_as_tool_call(new_seg)
                        and str(prev_seg.get('content', '') or '') != content
                    ):
                        return False
                    server_bound = new_seg.get('_bound_results') if isinstance(new_seg.get('_bound_results'), list) else []
                    if server_bound:
                        for result in server_bound:
                            result_content = str(result.get('content', '') or '')
                            success = result.get('success')
                            if hasattr(widget, 'set_result_text') and result_content:
                                widget.set_result_text(result_content)
                            if hasattr(widget, 'set_success') and success is not None:
                                widget.set_success(bool(success))
                    tool_call_id = str(new_seg.get('tool_call_id') or '').strip()
                    block_key = str(new_seg.get('block_key') or '').strip()
                    if block_key:
                        self._tool_cards_by_id[block_key] = widget
                    if tool_call_id:
                        self._tool_cards_by_id[tool_call_id] = widget
                    widget._seg_data = new_seg
                else:
                    return False
            elif seg_type == 'tool_call':
                tool_call_id = str(new_seg.get('tool_call_id') or '').strip()
                server_bound = new_seg.get('_bound_results') if isinstance(new_seg.get('_bound_results'), list) else []
                if isinstance(widget, ToolCallCard):
                    if server_bound:
                        for result in server_bound:
                            result_content = str(result.get('content', '') or '')
                            success = result.get('success')
                            if hasattr(widget, 'set_result_text') and result_content:
                                widget.set_result_text(result_content)
                            if hasattr(widget, 'set_success') and success is not None:
                                widget.set_success(bool(success))
                    if tool_call_id:
                        self._tool_cards_by_id[tool_call_id] = widget
                    widget._seg_data = new_seg
            elif seg_type == 'thinking':
                if isinstance(widget, ToolResultBox):
                    widget.content = content
                    widget.body.setPlainText(content)
                else:
                    return False

        return True

    def _try_build_tool_result_box(self, message_data):
        # 结构化优先：kind/meta 驱动
        if isinstance(message_data, dict):
            kind = str(message_data.get('kind', '') or '').strip().lower()
            meta = message_data.get('meta', {}) if isinstance(message_data.get('meta', {}), dict) else {}
            tool_kind = str(meta.get('tool_kind', '') or '').strip().lower()
            if kind == 'tool_feedback' or tool_kind == 'tool_feedback':
                raw = message_data.get('raw_content', '')
                content = raw if isinstance(raw, str) and raw else self._extract_full_message_text(message_data)
                summary = meta.get('tool_name') or '🔧 工具执行结果'
                return ToolResultBox(str(summary), str(content or ''))

        # 旧数据兜底：marker 识别
        full_text = self._extract_full_message_text(message_data)
        if not isinstance(full_text, str):
            return None
        normalized = re.sub(r'^(?:\s*<[^>]+>\s*)+', '', full_text)
        normalized = normalized.lstrip()
        marker = '🔧 [工具执行结果]'
        if not normalized.startswith(marker):
            return None
        lines = normalized.splitlines()
        summary = marker
        for line in lines[1:]:
            stripped = line.strip()
            if stripped:
                summary = stripped
                break
        return ToolResultBox(summary, normalized)

    def update_content(self, message_data, index=None):
        self.select_box.blockSignals(True)
        self.select_box.setChecked(self.selected if self.selection_mode else False)
        self.select_box.blockSignals(False)
        self.select_box.setVisible(self.selection_mode)
        if index is not None:
            self.index = index
            self.turn_box.setValue(index)

        if self.current_data == message_data:
            return
        self.current_data = message_data
        self.message_id = str(message_data.get('id', '')) if isinstance(message_data, dict) else ''

        new_segments = message_data.get('segments', []) if not isinstance(message_data, str) else [{'type': 'text', 'content': message_data}]

        if self._try_incremental_update(new_segments):
            return

        while self.c_layout.count() > 1:
            item = self.c_layout.takeAt(1)
            if item.widget(): item.widget().deleteLater()
        self._tool_cards_by_id = {}
        self._tool_result_boxes_by_id = {}

        segments = new_segments
        has_native_blocks = any(isinstance(seg, dict) and seg.get('type') in ['tool_result', 'tool_call', 'thinking'] for seg in segments)

        if not has_native_blocks:
            tool_box = self._try_build_tool_result_box(message_data)
            if tool_box is not None:
                self.c_layout.addWidget(tool_box)
                return
        if not segments: segments = [{'type': 'text', 'content': "..."}]

        total_code_blocks = sum(1 for s in segments if s['type'] == 'code')
        code_count = 0

        bound_tool_results = {}
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            if seg.get('type') == 'tool_result':
                tool_call_id = str(seg.get('tool_call_id') or '').strip()
                if tool_call_id:
                    bound_tool_results.setdefault(tool_call_id, []).append(seg)

        rendered_tool_result_ids = set()

        for seg in segments:
            if seg['type'] == 'text':
                text_content = str(seg.get('content', '') or '').strip()
                if not text_content:
                    continue
                tb = ResizableTextBrowser(seg['content'])
                self.c_layout.addWidget(tb)
            elif seg['type'] == 'code':
                code_content = str(seg.get('content', '') or '').strip()
                code_lang = str(seg.get('language', '') or '').strip().lower()
                if not code_content:
                    if code_lang == 'tool_call':
                        tool_call_id = str(seg.get('tool_call_id') or '').strip()
                        block_key = str(seg.get('block_key') or '').strip()
                        box = ToolCallCard('', '', tool_call_id=tool_call_id)
                        if block_key:
                            self._tool_cards_by_id[block_key] = box
                        if tool_call_id:
                            self._tool_cards_by_id[tool_call_id] = box
                        box._seg_data = seg
                        self.c_layout.addWidget(box)
                        code_count += 1
                    else:
                        box = CodeBox('代码块内容加载中，稍后展示完整内容。', language=code_lang or 'code', is_ignored=False, is_placeholder=True)
                        self.c_layout.addWidget(box)
                    continue
                tool_call_box = _try_build_tool_call_box_from_code_seg(seg)
                if tool_call_box is not None:
                    if isinstance(tool_call_box, ToolCallCard):
                        tool_call_id = str(seg.get('tool_call_id') or '').strip()
                        block_key = str(seg.get('block_key') or '').strip()
                        if block_key:
                            self._tool_cards_by_id[block_key] = tool_call_box
                        if tool_call_id:
                            self._tool_cards_by_id[tool_call_id] = tool_call_box
                        tool_call_box._seg_data = seg
                        server_bound = seg.get('_bound_results') if isinstance(seg.get('_bound_results'), list) else []
                        if server_bound:
                            for result in server_bound:
                                content = str(result.get('content', '') or '')
                                success = result.get('success')
                                if hasattr(tool_call_box, 'set_result_text') and content:
                                    tool_call_box.set_result_text(content)
                                if hasattr(tool_call_box, 'set_success') and success is not None:
                                    tool_call_box.set_success(bool(success))
                        logger.info("[ChatBubble-诊断] ToolCallCard注册 | tool_call_id=%s | block_key=%s | msg_idx=%s | lang=%s",
                                    tool_call_id[:25], block_key[:25], self.index,
                                    str(seg.get('language', '') or '')[:15])
                    self.c_layout.addWidget(tool_call_box)
                    code_count += 1
                    continue
                is_ignored = seg.get('is_ignored', False)
                tool_meta = seg.get('tool_meta') or {}
                display_title = tool_meta.get('summary') or seg.get('language', 'Code')
                box = CodeBox(seg['content'], language=display_title, is_ignored=is_ignored)
                current_block_idx = code_count

                box.request_remote_toggle.connect(lambda idx=current_block_idx: self.request_remote_action.emit(self.index, idx, total_code_blocks))
                box.request_apply.connect(self.request_code_apply.emit)
                box.request_discard.connect(self.request_discard_relay.emit)
                box.request_undiscard.connect(self.request_undiscard_relay.emit)

                self.c_layout.addWidget(box)
                code_count += 1
            elif seg['type'] == 'image':
                self.c_layout.addWidget(ImageBox(seg['content']))
            elif seg['type'] == 'code_placeholder':
                placeholder_text = str(seg.get('placeholder_text', '') or 'AI 正在生成代码块，稍后展示完整内容。')
                placeholder_lang = str(seg.get('language', '') or 'code')
                box = CodeBox(placeholder_text, language=placeholder_lang, is_ignored=False, is_placeholder=True)
                self.c_layout.addWidget(box)
            elif seg['type'] == 'tool_call':
                tool_call_id = str(seg.get('tool_call_id') or '').strip()
                bound_results = bound_tool_results.get(tool_call_id, []) if tool_call_id else []
                server_bound = seg.get('_bound_results') if isinstance(seg.get('_bound_results'), list) else []
                if server_bound and not bound_results:
                    bound_results = server_bound
                if bound_results and tool_call_id:
                    rendered_tool_result_ids.add(tool_call_id)
                box = _build_bound_tool_box(seg, bound_results)
                if isinstance(box, ToolCallCard):
                    if tool_call_id:
                        self._tool_cards_by_id[tool_call_id] = box
                        box._seg_data = seg
                    _bk = str(seg.get('block_key') or '').strip()
                    if _bk:
                        self._tool_cards_by_id[_bk] = box
                self.c_layout.addWidget(box)
            elif seg['type'] == 'thinking':
                box = ToolResultBox("🤔 思考过程", str(seg.get('content', '')))
                self.c_layout.addWidget(box)
            elif seg['type'] == 'user_message':
                text_content = str(seg.get('content', '') or '').strip()
                if text_content:
                    tb = ResizableTextBrowser(seg['content'])
                    self.c_layout.addWidget(tb)
            elif seg['type'] == 'tool_result':
                tool_call_id = str(seg.get('tool_call_id') or '').strip()
                if tool_call_id and tool_call_id in rendered_tool_result_ids:
                    continue
                title = seg.get('tool_name') or '🔧 工具执行结果'
                if not seg.get('success', True):
                    title = f'❌ {title} (失败)'
                else:
                    title = f'✅ {title}'
                box = ToolResultBox(title, str(seg.get('content', '')))
                if tool_call_id:
                    self._tool_result_boxes_by_id[tool_call_id] = {
                        'widget': box,
                        'seg': seg,
                    }
                self.c_layout.addWidget(box)

        # 所有 segments 渲染完毕后，如果没有任何内容，隐藏气泡
        # 用户气泡的 meta_box 在 wrapper_layout 中，不在 c_layout 里，阈值为 0
        # AI 气泡的 meta_box 在 c_layout 中，阈值为 1
        _cc = self.c_layout.count()
        _role = 'User' if self.is_user else 'AI'
        _empty_threshold = 0 if self.is_user else 1
        if _cc <= _empty_threshold:
            logger.debug("[诊断] 隐藏空气泡 | idx=%s | role=%s | c_layout_count=%s | seg_count=%s", self.index, _role, _cc, len(segments))
            self.setVisible(False)
        else:
            self.setVisible(True)

        # 用户消息折叠检查
        self._check_collapse()


    def find_tool_card(self, tool_call_id: str):
        key = str(tool_call_id or '').strip()
        if not key:
            return None
        return self._tool_cards_by_id.get(key)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        multi_delete_action = menu.addAction('🗑️ 进入多选删除模式')
        chosen = menu.exec(event.globalPos())
        if chosen == multi_delete_action:
            self.request_multi_select_mode.emit(self.index)
