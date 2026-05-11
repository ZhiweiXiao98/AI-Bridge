from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QWidget, QListWidget, QListWidgetItem
)
from PySide6.QtGui import QFont

from app.ui.theme import theme_manager


class ContextWorkspacePlanBindingDialog(QDialog):
    def __init__(self, plan_data=None, parent=None):
        super().__init__(parent)
        self._plan_data = plan_data or {}
        self._action = None
        self.setWindowTitle('上下文工作台 · 计划书绑定')
        self.resize(960, 760)
        self._build_ui()
        self._render_plan_data()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_lbl = QLabel('计划书绑定')
        title_lbl.setObjectName('ContextWorkspacePlanBindingTitle')
        layout.addWidget(title_lbl)

        self.status_lbl = QLabel('当前未绑定计划书')
        self.status_lbl.setObjectName('ContextWorkspacePlanBindingStatus')
        layout.addWidget(self.status_lbl)

        self.meta_lbl = QLabel('')
        self.meta_lbl.setObjectName('ContextWorkspacePlanBindingMeta')
        self.meta_lbl.setWordWrap(True)
        layout.addWidget(self.meta_lbl)

        checklist_row = QHBoxLayout()
        checklist_row.setContentsMargins(0, 0, 0, 0)
        checklist_row.setSpacing(10)

        pending_col = QWidget()
        pending_layout = QVBoxLayout(pending_col)
        pending_layout.setContentsMargins(0, 0, 0, 0)
        pending_layout.setSpacing(6)
        pending_title = QLabel('待勾选项')
        pending_title.setObjectName('ContextWorkspacePlanBindingSectionTitle')
        self.pending_list = QListWidget()
        self.pending_list.setMinimumHeight(120)
        pending_layout.addWidget(pending_title)
        pending_layout.addWidget(self.pending_list)

        done_col = QWidget()
        done_layout = QVBoxLayout(done_col)
        done_layout.setContentsMargins(0, 0, 0, 0)
        done_layout.setSpacing(6)
        done_title = QLabel('已勾选项')
        done_title.setObjectName('ContextWorkspacePlanBindingSectionTitle')
        self.done_list = QListWidget()
        self.done_list.setMinimumHeight(120)
        done_layout.addWidget(done_title)
        done_layout.addWidget(self.done_list)

        checklist_row.addWidget(pending_col, 1)
        checklist_row.addWidget(done_col, 1)
        layout.addLayout(checklist_row)

        content_title = QLabel('计划书全文')
        content_title.setObjectName('ContextWorkspacePlanBindingSectionTitle')
        layout.addWidget(content_title)

        self.content_view = QPlainTextEdit()
        self.content_view.setReadOnly(True)
        self.content_view.setFont(QFont('Consolas', 10))
        layout.addWidget(self.content_view, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.bind_btn = QPushButton('绑定计划书')
        self.bind_btn.clicked.connect(self._accept_bind)
        btn_row.addWidget(self.bind_btn)

        self.unbind_btn = QPushButton('解绑')
        self.unbind_btn.clicked.connect(self._accept_unbind)
        btn_row.addWidget(self.unbind_btn)

        self.close_btn = QPushButton('关闭')
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    def _render_plan_data(self):
        plan = self._plan_data if isinstance(self._plan_data, dict) else {}
        title = str(plan.get('title', '') or '').strip()
        path = str(plan.get('path', '') or '').strip()
        token_count = int(plan.get('token_count', 0) or 0)
        summary = str(plan.get('summary', '') or '').strip()
        content = str(plan.get('content', '') or '')
        pending = plan.get('checklist_pending', []) or []
        done = plan.get('checklist_done', []) or []

        if title or path:
            self.status_lbl.setText(f'当前已绑定：{title or path}')
        else:
            self.status_lbl.setText('当前未绑定计划书')

        meta_parts = []
        if path:
            meta_parts.append(f'路径：{path}')
        if token_count:
            meta_parts.append(f'Tokens：{token_count}')
        if summary:
            meta_parts.append(f'摘要：{summary}')
        meta_text = '\n'.join(meta_parts) if meta_parts else '尚未绑定计划书。'
        self.meta_lbl.setText(meta_text)
        self.meta_lbl.setToolTip(meta_text)

        self.pending_list.clear()
        for item in pending:
            self.pending_list.addItem(QListWidgetItem(str(item)))
        if not pending:
            self.pending_list.addItem(QListWidgetItem('（无）'))

        self.done_list.clear()
        for item in done:
            self.done_list.addItem(QListWidgetItem(str(item)))
        if not done:
            self.done_list.addItem(QListWidgetItem('（无）'))

        self.content_view.setPlainText(content or '')
        self.unbind_btn.setEnabled(bool(title or path or content))

    def _accept_bind(self):
        self._action = 'bind'
        self.accept()

    def _accept_unbind(self):
        self._action = 'unbind'
        self.accept()

    def selected_action(self):
        return self._action

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f'''
            QDialog {{
                background-color: {p.BG_PRIMARY};
                color: {p.TEXT_PRIMARY};
            }}
            QLabel#ContextWorkspacePlanBindingTitle {{
                color: {p.TEXT_PRIMARY};
                font-size: 18px;
                font-weight: 700;
                padding: 2px 2px 8px 2px;
            }}
            QLabel#ContextWorkspacePlanBindingStatus {{
                color: {p.TEXT_PRIMARY};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#ContextWorkspacePlanBindingMeta{{
                color: {p.TEXT_SECONDARY};
                font-size: 11px;
            }}
            QLabel#ContextWorkspacePlanBindingSectionTitle {{
                color: {p.TEXT_SECONDARY};
                font-size: 12px;
                font-weight: 600;
                padding-top: 4px;
            }}
            QPlainTextEdit, QListWidget {{
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
