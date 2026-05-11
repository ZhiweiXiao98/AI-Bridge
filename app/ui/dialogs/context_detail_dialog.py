from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QWidget
)
from PySide6.QtGui import QFont

from app.ui.theme import theme_manager


class ContextDetailDialog(QDialog):
    def __init__(
        self,
        title: str,
        text: str = '',
        parent=None,
        editable: bool = False,
        action_text: str = '保存',
        on_accept=None,
        auxiliary_sections=None,
        sections=None,
        save_button_text: str | None = None,
        initial_text: str | None = None,
        content: str | None = None,
    ):
        super().__init__(parent)
        self._title = str(title or '详情')
        self._editable = bool(editable)
        self._on_accept = on_accept

        normalized_sections = []
        for section in list(sections or []) + list(auxiliary_sections or []):
            if not isinstance(section, dict):
                continue
            sec_title = str(section.get('title', '') or '').strip()
            sec_text = str(section.get('content', section.get('text', '')) or '')
            if sec_title:
                normalized_sections.append({'title': sec_title, 'text': sec_text})
        self._auxiliary_sections = normalized_sections

        base_text = initial_text if initial_text is not None else content if content is not None else text
        button_text = save_button_text if save_button_text is not None else action_text

        self.setWindowTitle(self._title)
        self.resize(920, 720)
        self._build_ui(str(base_text or ''), str(button_text or '保存'))
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def _build_ui(self, text: str, action_text: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_lbl = QLabel(self._title)
        title_lbl.setObjectName('ContextDetailTitle')
        layout.addWidget(title_lbl)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(text)
        self.editor.setReadOnly(not self._editable)
        self.editor.setFont(QFont('Consolas', 10))
        layout.addWidget(self.editor, 1)

        self.section_host = QWidget()
        self.section_layout = QVBoxLayout(self.section_host)
        self.section_layout.setContentsMargins(0, 0, 0, 0)
        self.section_layout.setSpacing(8)
        layout.addWidget(self.section_host)

        self._section_widgets = []
        for section in self._auxiliary_sections:
            sec_title = str((section or {}).get('title', '') or '').strip()
            sec_text = str((section or {}).get('text', '') or '')
            if not sec_title:
                continue
            block = QWidget()
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(4)

            lbl = QLabel(sec_title)
            lbl.setObjectName('ContextDetailSectionTitle')
            block_layout.addWidget(lbl)

            view = QPlainTextEdit()
            view.setReadOnly(True)
            view.setPlainText(sec_text)
            view.setMinimumHeight(120)
            view.setFont(QFont('Consolas', 9))
            block_layout.addWidget(view)
            self.section_layout.addWidget(block)
            self._section_widgets.append(view)

        self.section_host.setVisible(bool(self._section_widgets))

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        copy_btn = QPushButton('复制')
        copy_btn.clicked.connect(self._copy_text)
        btn_row.addWidget(copy_btn)
        self.copy_btn = copy_btn

        if self._editable:
            save_btn = QPushButton(action_text)
            save_btn.clicked.connect(self._handle_accept)
            btn_row.addWidget(save_btn)
            self.save_btn = save_btn
        else:
            self.save_btn = None

        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        self.close_btn = close_btn

        layout.addLayout(btn_row)

    def _copy_text(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.editor.toPlainText())

    def _handle_accept(self):
        if callable(self._on_accept):
            self._on_accept(self.editor.toPlainText())
        self.accept()

    def get_result_text(self) -> str:
        return self.editor.toPlainText()

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f'''
            QDialog {{
                background-color: {p.BG_PRIMARY};
                color: {p.TEXT_PRIMARY};
            }}
            QLabel#ContextDetailTitle {{
                color: {p.TEXT_PRIMARY};
                font-size: 18px;
                font-weight: 700;
                padding: 2px 2px 8px 2px;
            }}
            QLabel#ContextDetailSectionTitle {{
                color: {p.TEXT_SECONDARY};
                font-size: 12px;
                font-weight: 600;
                padding-top: 4px;
            }}
            QPlainTextEdit {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
                padding: 8px;
                selection-background-color: {p.ACCENT_PRIMARY};
            }}
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                min-height: 28px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {p.BORDER};
            }}
        ''')
