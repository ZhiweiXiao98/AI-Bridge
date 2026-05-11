# filename: app/ui/components/editor.py
import re
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
                               QPushButton, QPlainTextEdit, QApplication,
                               QMessageBox)
from PySide6.QtCore import Qt, QSize, Signal, QRect, QTimer
from PySide6.QtGui import (QColor, QTextCharFormat, QFont, QSyntaxHighlighter, 
                           QTextCursor, QPainter)
from app.ui.theme import Theme, Palette, theme_manager

class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.highlighting_rules = []
        self.update_rules()

    def update_rules(self):
        self.highlighting_rules = []
        p = theme_manager.get_palette()
        
        is_light = p.BG_PRIMARY.upper().startswith("#F") or p.BG_PRIMARY.upper().startswith("#E")

        c_keyword = "#C678DD" if not is_light else "#A626A4"
        c_string = "#98C379" if not is_light else "#50A14F"
        c_comment = "#5C6370" if not is_light else "#A0A1A7"
        c_decorator = "#E5C07B" if not is_light else "#986801"
        c_func = "#61AFEF" if not is_light else "#4078F2"

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor(c_keyword)) 
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "def", "class", "if", "else", "elif", "while", "for", "in", "return",
            "import", "from", "try", "except", "finally", "with", "as", "pass",
            "break", "continue", "lambda", "global", "nonlocal", "True", "False", "None"
        ]
        for word in keywords:
            pattern = re.compile(rf"\b{word}\b")
            self.highlighting_rules.append((pattern, keyword_format))

        string_format = QTextCharFormat()
        string_format.setForeground(QColor(c_string)) 
        self.highlighting_rules.append((re.compile(r"\".*\""), string_format))
        self.highlighting_rules.append((re.compile(r"\'.*\'"), string_format))

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor(c_comment))
        self.highlighting_rules.append((re.compile(r"#[^\n]*"), comment_format))
        
        decorator_format = QTextCharFormat()
        decorator_format.setForeground(QColor(c_decorator))
        self.highlighting_rules.append((re.compile(r"@[^\n]*"), decorator_format))

        func_format = QTextCharFormat()
        func_format.setForeground(QColor(c_func))
        self.highlighting_rules.append((re.compile(r"\b[A-Za-z0-9_]+(?=\()"), func_format))
        
        self.rehighlight()

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.codeEditor = editor

    def sizeHint(self):
        return QSize(self.codeEditor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.codeEditor.lineNumberAreaPaintEvent(event)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.highlighter = PythonHighlighter(self.document())
        
        self.lineNumberArea = LineNumberArea(self)
        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.updateLineNumberAreaWidth(0)
        
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def apply_theme(self):
        p = theme_manager.get_palette()
        is_light = p.BG_PRIMARY.upper().startswith("#F") or p.BG_PRIMARY.upper().startswith("#E")
        bg_color = "#282C34" if not is_light else "#FAFAFA"
        fg_color = "#ABB2BF" if not is_light else "#383A42"
        
        sel_bg = "#3E4451" if not is_light else "#ADD6FF"
        sel_fg = "#FFFFFF" if not is_light else "#000000"
        
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {bg_color};
                color: {fg_color};
                border: none;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                selection-background-color: {sel_bg};
                selection-color: {sel_fg};
            }}
        """)
        self.highlighter.update_rules()
        self.lineNumberArea.update()

    def lineNumberAreaWidth(self):
        digits = 1
        max_val = max(1, self.blockCount())
        while max_val >= 10:
            max_val /= 10
            digits += 1
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(0, rect.y(), self.lineNumberArea.width(), rect.height())
        
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.lineNumberArea.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        p = theme_manager.get_palette()
        is_light = p.BG_PRIMARY.upper().startswith("#F") or p.BG_PRIMARY.upper().startswith("#E")
        bg_color = QColor("#21252B") if not is_light else QColor("#F0F0F0")
        fg_color = QColor("#5C6370") if not is_light else QColor("#9CA3AF")

        painter = QPainter(self.lineNumberArea)
        painter.fillRect(event.rect(), bg_color)

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(blockNumber + 1)
                painter.setPen(fg_color)
                painter.setFont(self.font())
                painter.drawText(0, int(top), self.lineNumberArea.width() - 5, self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            blockNumber += 1

class CodeBox(QFrame):
    request_ignore = Signal(str) 
    request_discard = Signal(str, str) 
    request_undiscard = Signal(str, str) 
    request_save = Signal(str, str)
    request_remote_toggle = Signal()
    request_apply = Signal(str, str)

    def __init__(self, content, filename="code", language="Code", is_ignored=False, is_placeholder=False):
        super().__init__()
        self.content = content
        self.language = language
        self.is_ignored_state = is_ignored # 初始化状态
        self.is_placeholder = bool(is_placeholder)
        self._loading_dots = 0
        self._loading_timer = None
        
        if filename == "code":
            self.filename = self._extract_filename(content) or "code"
        else:
            self.filename = filename
            
        self.is_expanded = True
        self.init_ui()
        
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()
        if self.is_placeholder:
            self._loading_timer = QTimer(self)
            self._loading_timer.setInterval(450)
            self._loading_timer.timeout.connect(self._advance_loading_indicator)
            self._loading_timer.start()

    def _extract_filename(self, code):
        for line in code.split('\n')[:5]:
            match = re.search(r"(?:filename)\s*[:=]\s*([^\s]+)", line, re.IGNORECASE)
            if match:
                fname = match.group(1).strip()
                return fname.replace("-->", "")
        return None

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.header = QFrame()
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(10, 5, 10, 5)
        
        display_name = self._build_display_name()
        
        self.toggle_btn = QPushButton(f"▼ {display_name}")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle_view)
        h_layout.addWidget(self.toggle_btn)
        
        h_layout.addStretch()
        
        self.discard_btn = None
        self.remote_btn = None
        self.apply_btn = None
        self.copy_btn = None

        if not self.is_placeholder:
            btn_text = "♻️ 撤销" if self.is_ignored_state else "🗑️"
            self.discard_btn = QPushButton(btn_text)
            self.discard_btn.setToolTip("拉黑/取消拉黑：防止此版本代码再次被识别为更新")
            self.discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.discard_btn.clicked.connect(self.on_discard_toggle)
            h_layout.addWidget(self.discard_btn)

            self.remote_btn = QPushButton("🔧")
            self.remote_btn.setToolTip("远程点穴")
            self.remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.remote_btn.clicked.connect(lambda: self.request_remote_toggle.emit())
            h_layout.addWidget(self.remote_btn)

            self.apply_btn = QPushButton("⚡ 应用")
            self.apply_btn.setToolTip("应用代码")
            self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.apply_btn.clicked.connect(self.quick_apply)
            h_layout.addWidget(self.apply_btn)

            self.copy_btn = QPushButton("📋 复制")
            self.copy_btn.setToolTip("复制")
            self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.copy_btn.clicked.connect(self.copy_to_clipboard)
            h_layout.addWidget(self.copy_btn)
        
        layout.addWidget(self.header)
        
        self.editor = CodeEditor()
        self.editor.setPlainText(self.content)
        
        doc_height = self.editor.document().size().height()
        line_count = self.content.count('\n') + 1
        height = min(400, max(60, line_count * 21 + 20))
        self.editor.setFixedHeight(int(height))
        
        layout.addWidget(self.editor)


    def _build_display_name(self):
        base = f"💻 {self.language}"
        if self.is_placeholder:
            dots = '.' * ((self._loading_dots % 3) + 1)
            return f"{base} · 生成中{dots}"
        if self.filename and self.filename != "code":
            base += f" | 📄 {self.filename}"
        return base

    def _refresh_toggle_title(self):
        arrow = "▼" if self.is_expanded else "▶"
        self.toggle_btn.setText(f"{arrow} {self._build_display_name()}")

    def _advance_loading_indicator(self):
        if not self.is_placeholder:
            return
        self._loading_dots = (self._loading_dots + 1) % 3
        self._refresh_toggle_title()
    def apply_theme(self):
        p = theme_manager.get_palette()
        is_light = p.BG_PRIMARY.upper().startswith("#F")
        bg_header = "#21252B" if not is_light else "#E5E5E5"
        border_color = "#181A1F" if not is_light else "#D1D5DB"
        text_color = "#ABB2BF" if not is_light else "#383A42"
        
        self.header.setStyleSheet(f"background-color: {bg_header}; border-top-left-radius: 6px; border-top-right-radius: 6px; border: 1px solid {border_color}; border-bottom: none;")
        
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{ border: none; color: {text_color}; font-weight: bold; text-align: left; }}
            QPushButton:hover {{ color: {p.ACCENT_PRIMARY}; }}
        """)
        
        if self.discard_btn is not None:
            discard_color = p.TEXT_SUCCESS if self.is_ignored_state else p.TEXT_DANGER
            self.discard_btn.setStyleSheet(f"border: none; color: {discard_color}; font-size: 14px; margin-right: 10px; font-weight: bold;")
        if self.remote_btn is not None:
            self.remote_btn.setStyleSheet(f"border: none; color: {p.BTN_WARNING}; font-weight: bold; font-size: 14px; margin-right: 10px;")
        if self.apply_btn is not None:
            self.apply_btn.setStyleSheet(f"border: none; color: {p.TEXT_SUCCESS}; font-weight: bold; font-size: 11px; margin-right: 10px;")
        if self.copy_btn is not None:
            self.copy_btn.setStyleSheet(f"border: none; color: {p.TEXT_SECONDARY}; font-size: 11px;")
        
        self.editor.setStyleSheet(self.editor.styleSheet() + f"border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; border: 1px solid {border_color}; border-top: none;")

    def copy_to_clipboard(self):
        QApplication.clipboard().setText(self.content)
        if self.copy_btn is not None:
            self.copy_btn.setText(f"✅ 已复制")
        QApplication.processEvents()

    def toggle_view(self):
        self.is_expanded = not self.is_expanded
        self.editor.setVisible(self.is_expanded)
        self._refresh_toggle_title()

    def quick_apply(self):
        if self.filename == "code":
            self.filename = self._extract_filename(self.content) or "code"
        self.request_apply.emit(self.filename, self.content)
    
    def on_discard_toggle(self):
        if self.filename == "code":
            self.filename = self._extract_filename(self.content) or "code"
            
        p = theme_manager.get_palette()
        
        if not self.is_ignored_state:
            # 状态翻转：执行拉黑
            self.is_ignored_state = True
            self.request_discard.emit(self.filename, self.content)
            
            # 即时 UI 反馈
            self.discard_btn.setText("♻️ 撤销")
            self.discard_btn.setStyleSheet(f"border: none; color: {p.TEXT_SUCCESS}; font-size: 11px; margin-right: 10px; font-weight: bold;")
        else:
            # 状态翻转：执行撤销
            self.is_ignored_state = False
            self.request_undiscard.emit(self.filename, self.content)
            
            # 即时 UI 反馈
            self.discard_btn.setText("🗑️")
            self.discard_btn.setStyleSheet(f"border: none; color: {p.TEXT_DANGER}; font-size: 14px; margin-right: 10px;")