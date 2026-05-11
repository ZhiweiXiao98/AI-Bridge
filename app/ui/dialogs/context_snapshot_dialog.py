"""上下文快照调试浮窗。"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from app.core.context_snapshot_formatter import format_snapshot


class ContextSnapshotDialog(QDialog):
    """显示最近一次请求的完整上下文快照。"""

    def __init__(self, snapshot: dict, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.setWindowTitle('📋 上下文快照 - 调试')
        self.setGeometry(100, 100, 1000, 750)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 标题行
        header = QHBoxLayout()
        conv_id = self.snapshot.get('conversation_id', '?')
        model = self.snapshot.get('model', '?')
        import time as _time
        ts = self.snapshot.get('timestamp', 0)
        ts_str = _time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime(ts)) if ts else '?'
        
        title_lbl = QLabel(f'对话: {conv_id}  |  模型: {model}  |  时间: {ts_str}')
        title_lbl.setStyleSheet('font-weight: bold; color: #1f2937;')
        header.addWidget(title_lbl)
        header.addStretch()
        layout.addLayout(header)

        # 内容区
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont('Courier', 9))
        self.text_edit.setPlainText(format_snapshot(self.snapshot, full=True))
        layout.addWidget(self.text_edit, 1)

        # 按钮行
        buttons = QHBoxLayout()
        buttons.addStretch()

        copy_btn = QPushButton('📋 复制全部')
        copy_btn.setFixedWidth(120)
        copy_btn.clicked.connect(self._copy_all)
        copy_btn.setStyleSheet('''
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        ''')
        buttons.addWidget(copy_btn)

        close_btn = QPushButton('关闭')
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet('''
            QPushButton {
                background-color: #6b7280;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        ''')
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _copy_all(self):
        """复制全部内容到剪贴板。"""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_edit.toPlainText())
