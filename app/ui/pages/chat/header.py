# filename: app/ui/pages/chat/header.py
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QComboBox, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from app.ui.theme import Theme, theme_manager

class ChatHeader(QFrame):
    request_wake = Signal()
    request_fix = Signal()
    license_changed = Signal(str)
    resume_sync_clicked = Signal()
    mode_switch_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatHeader")
        self.setFixedHeight(40)
        self.init_ui()

        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        self.title_label = QLabel("AI Bridge")
        self.title_label.setObjectName("HeaderTitle")
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.sync_btn = QPushButton("🔴 视图冻结 (点击同步)")
        self.sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_btn.clicked.connect(self.resume_sync_clicked)
        self.sync_btn.hide()

        self.license_combo = QComboBox()
        self.license_combo.addItems(["admin", "vip_001", "vip_002", "trial_user"])
        self.license_combo.setToolTip("切换当前控制的客户环境")
        self.license_combo.currentTextChanged.connect(self.license_changed)
        self.license_combo.setMinimumWidth(70)
        self.license_combo.setMaximumWidth(88)
        self.license_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.license_combo.setMinimumContentsLength(4)

        self.wake_btn = QPushButton("↻")
        self.wake_btn.setToolTip("唤醒 + 全量同步")
        self.wake_btn.clicked.connect(self.request_wake)
        self.fix_all_btn = QPushButton("⚒")
        self.fix_all_btn.setToolTip("修复")
        self.fix_all_btn.clicked.connect(self.request_fix)

        self.status_label = QLabel("监听中...")
        self.status_label.setMinimumWidth(0)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.latency_label = QLabel("--ms")
        self.latency_label.setMinimumWidth(0)
        self.latency_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        layout.addWidget(self.title_label)
        layout.addWidget(self.sync_btn)
        self.target_label = QLabel("Target:")
        self.target_label.hide()
        layout.addWidget(self.target_label)
        layout.addWidget(self.license_combo)

        self.mode_btn = QPushButton("浏览器")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.setToolTip("切换消息源: 浏览器 / API")
        self.mode_btn.clicked.connect(self._toggle_mode)
        self._current_mode = "browser"
        layout.addWidget(self.mode_btn)
        layout.addWidget(self.status_label, 1)

        layout.addWidget(self.wake_btn)
        layout.addWidget(self.fix_all_btn)
        layout.addWidget(self.latency_label)
        self._apply_compressible_width_policy()

    def _apply_compressible_width_policy(self):
        widgets = [
            self.title_label,
            self.target_label,
            self.license_combo,
            self.mode_btn,
            self.wake_btn,
            self.fix_all_btn,
            self.status_label,
            self.latency_label,
        ]
        for widget in widgets:
            widget.setMinimumWidth(0)
        for widget in (self.title_label, self.target_label):
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        for widget in (self.mode_btn, self.wake_btn, self.fix_all_btn, self.latency_label):
            widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.mode_btn.setMaximumWidth(54)
        self.wake_btn.setMaximumWidth(34)
        self.fix_all_btn.setMaximumWidth(34)

    def apply_theme(self):
        p = theme_manager.get_palette()

        self.setStyleSheet(f"#ChatHeader {{ background-color: {p.BG_PRIMARY}; border-bottom: 1px solid {p.BORDER}; }}")
        self.title_label.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")

        self.sync_btn.setStyleSheet(Theme.button_danger())
        self.license_combo.setStyleSheet(Theme.combo_box())

        btn_style = f"""
            QPushButton {{ background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 4px; padding: 2px 6px; }}
            QPushButton:hover {{ background-color: {p.ACCENT_PRIMARY}; color: white; border: 1px solid {p.ACCENT_PRIMARY}; }}
        """
        self.wake_btn.setStyleSheet(btn_style)
        self.fix_all_btn.setStyleSheet(btn_style)

        self.status_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 11px;")
        self.latency_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 10px;")

    def set_sync_visible(self, visible):
        if visible: self.sync_btn.show()
        else: self.sync_btn.hide()

    def set_status(self, text):
        self.status_label.setText(text)

    def set_fix_btn_state(self, enabled, text):
        self.fix_all_btn.setEnabled(enabled)
        self.fix_all_btn.setText(text)

    def update_latency(self, ms):
        p = theme_manager.get_palette()
        if ms < 0: ms = 0

        color = p.TEXT_SUCCESS
        text = f"{ms}ms"

        if ms > 1000:
            sec = ms / 1000
            color = p.TEXT_DANGER
            text = f"{sec:.1f}s"
        elif ms > 300:
            color = p.BTN_WARNING
        elif ms > 100:
            color = p.TEXT_SECONDARY

        self.latency_label.setText(text)
        self.latency_label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")

    def _toggle_mode(self):
        if self._current_mode == "browser":
            self.set_mode("api")
            self.mode_switch_clicked.emit("api")
        else:
            self.set_mode("browser")
            self.mode_switch_clicked.emit("browser")

    def set_mode(self, mode):
        self._current_mode = mode
        p = theme_manager.get_palette()
        if mode == "api":
            self.mode_btn.setText("API")
            self.mode_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {p.ACCENT_PRIMARY}; color: white; border-radius: 4px; padding: 2px 6px; font-weight: bold; }}
                QPushButton:hover {{ background-color: {p.ACCENT_SECONDARY}; }}
            """)
        else:
            self.mode_btn.setText("浏览器")
            self.mode_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 4px; padding: 2px 6px; }}
                QPushButton:hover {{ background-color: {p.ACCENT_PRIMARY}; color: white; }}
            """)
