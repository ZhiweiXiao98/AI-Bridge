import json
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QSizePolicy
from PySide6.QtCore import Qt
from app.ui.theme import theme_manager

class ToolCallCard(QFrame):
    """
    工具调用展示卡片，支持流式显示参数和执行结果。
    """
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.tool_name = data.get('tool_name') or data.get('name') or "Unknown Tool"
        self.arguments = data.get('arguments', {})
        self.status_text = "等待执行..."
        self.result_text = ""
        self.is_success = None
        
        self.init_ui()
        self.apply_theme()

    def init_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 8, 10, 8)
        self.layout.setSpacing(6)

        # 标题行
        self.header_layout = QHBoxLayout()
        self.icon_lbl = QLabel("🔧")
        self.name_lbl = QLabel(self.tool_name)
        self.name_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.status_lbl = QLabel(self.status_text)
        self.status_lbl.setStyleSheet("font-size: 11px; opacity: 0.7;")
        
        self.header_layout.addWidget(self.icon_lbl)
        self.header_layout.addWidget(self.name_lbl)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.status_lbl)
        self.layout.addLayout(self.header_layout)

        # 参数预览 (如果是 dict 则转为 JSON)
        arg_str = self.arguments if isinstance(self.arguments, str) else json.dumps(self.arguments, indent=2, ensure_ascii=False)
        self.arg_view = QLabel(arg_str)
        self.arg_view.setWordWrap(True)
        self.arg_view.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px; padding: 4px;")
        self.layout.addWidget(self.arg_view)

        # 结果区域 (默认隐藏)
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setVisible(False)
        self.result_view.setMaximumHeight(150)
        self.layout.addWidget(self.result_view)

    def apply_theme(self):
        p = theme_manager.get_palette()
        status_color = p.TEXT_SECONDARY
        border_color = p.BORDER
        bg_color = p.BG_TERTIARY

        if self.is_success is True:
            status_color = "#4CAF50" # Success Green
            border_color = "#4CAF50"
        elif self.is_success is False:
            status_color = "#F44336" # Error Red
            border_color = "#F44336"

        self.setStyleSheet(f"""
            ToolCallCard {{ 
                background-color: {bg_color}; 
                border: 1px solid {border_color}; 
                border-radius: 8px; 
            }}
        """)
        self.name_lbl.setStyleSheet(f"color: {p.ACCENT_PRIMARY}; font-weight: bold;")
        self.status_lbl.setStyleSheet(f"color: {status_color}; font-size: 11px;")
        self.arg_view.setStyleSheet(f"color: {p.TEXT_SECONDARY}; background: {p.BG_PRIMARY}; border-radius: 4px; padding: 5px;")
        self.result_view.setStyleSheet(f"background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; font-family: 'Consolas';")

    def update_runtime_status(self, payload):
        """更新运行时状态（流式阶段）"""
        if 'status' in payload:
            self.status_text = payload['status']
            self.status_lbl.setText(self.status_text)
        
    def set_result_text(self, text):
        self.result_text = text
        self.result_view.setPlainText(text)
        self.result_view.setVisible(bool(text))

    def set_success(self, success):
        self.is_success = success
        self.apply_theme()

    def set_status_text(self, text):
        self.status_text = text
        self.status_lbl.setText(text)
