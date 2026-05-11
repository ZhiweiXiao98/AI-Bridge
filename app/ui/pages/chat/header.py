# filename: app/ui/pages/chat/header.py
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, 
                               QComboBox, QSpinBox) 
from PySide6.QtCore import Qt, Signal
from app.ui.theme import Theme, Palette, theme_manager

class ChatHeader(QFrame):
    request_wake = Signal()
    request_fix = Signal()
    license_changed = Signal(str)
    resume_sync_clicked = Signal()
    mode_switch_clicked = Signal(str)  # 模式切换: "browser" | "api"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatHeader")
        self.setFixedHeight(50)
        self.init_ui()
        
        # [Theme] 绑定信号并应用
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        
        self.title_label = QLabel("AI Bridge SaaS Console")
        self.title_label.setObjectName("HeaderTitle")
        
        self.sync_btn = QPushButton("🔴 视图冻结 (点击同步)")
        self.sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_btn.clicked.connect(self.resume_sync_clicked)
        self.sync_btn.hide()

        self.license_combo = QComboBox()
        self.license_combo.addItems(["admin", "vip_001", "vip_002", "trial_user"])
        self.license_combo.setToolTip("切换当前控制的客户环境")
        self.license_combo.currentTextChanged.connect(self.license_changed)
        
        self.state_box = QFrame()
        sb_layout = QHBoxLayout(self.state_box); sb_layout.setContentsMargins(10,2,10,2)
        
        self.lbl_turn = QLabel("Turn:")
        
        self.turn_spinbox = QSpinBox()
        self.turn_spinbox.setRange(0, 99999)
        self.turn_spinbox.setReadOnly(True)
        self.turn_spinbox.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        
        self.lbl_snap = QLabel("Snap:")
        self.snap_spinbox = QSpinBox(); self.snap_spinbox.setRange(0, 99999); self.        snap_spinbox.setReadOnly(True); self.snap_spinbox.setButtonSymbols(QSpinBox.        ButtonSymbols.NoButtons)
        self.snap_spinbox.setToolTip("当前快照点 (点击气泡上的 ⛳ 设置)")
        
        self.separator = QLabel("|")
        
        sb_layout.addWidget(self.lbl_turn); sb_layout.addWidget(self.turn_spinbox)
        sb_layout.addWidget(self.separator); sb_layout.addWidget(self.lbl_snap); sb_layout.        addWidget(self.snap_spinbox)
        
        self.wake_btn = QPushButton("🔄 唤醒"); self.wake_btn.clicked.connect(self.        request_wake)
        self.fix_all_btn = QPushButton("🛠️ 修复"); self.fix_all_btn.clicked.connect(self.        request_fix)
        
        self.health_label = QLabel("未备份: 0")
        self.status_label = QLabel("监听中...")
        self.latency_label = QLabel("📶 --ms")
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.sync_btn)
        layout.addWidget(QLabel("   Target:"))
        layout.addWidget(self.license_combo)
        
        # 模式切换按钮
        self.mode_btn = QPushButton("🌐 浏览器")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.setToolTip("切换消息源: 浏览器 / API")
        self.mode_btn.clicked.connect(self._toggle_mode)
        self._current_mode = "browser"
        layout.addWidget(self.mode_btn)
        
        layout.addStretch()
        layout.addWidget(self.wake_btn)
        layout.addWidget(self.fix_all_btn)
        layout.addWidget(self.state_box)
        layout.addWidget(self.health_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.latency_label)

    def apply_theme(self):
        p = theme_manager.get_palette()
        
        # 容器背景
        self.setStyleSheet(f"#ChatHeader {{ background-color: {p.BG_PRIMARY}; border-bottom:         1px solid {p.BORDER}; }}")
        self.title_label.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-size: 18px;         font-weight: bold;")
        
        self.sync_btn.setStyleSheet(Theme.button_danger())
        self.license_combo.setStyleSheet(Theme.combo_box())
        
        # 状态盒子
        self.state_box.setStyleSheet(f"background-color: {p.BG_TERTIARY}; border-radius: 4px;        ")
        self.lbl_turn.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-weight: bold;")
        self.lbl_snap.setStyleSheet(f"color: {p.ACCENT_PRIMARY}; font-weight: bold;")
        self.separator.setStyleSheet(f"color: {p.BORDER};")
        
        spin_style = f"background: transparent; color: {p.TEXT_PRIMARY}; border: none;         font-weight: bold;"
        self.turn_spinbox.setStyleSheet(spin_style)
        self.snap_spinbox.setStyleSheet(f"background: transparent; color: {p.ACCENT_PRIMARY};         border: none; font-weight: bold;")
        
        # 按钮
        btn_style = f"""
            QPushButton {{ background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY};             border: 1px solid {p.BORDER}; border-radius: 4px; padding: 5px 10px; }}
            QPushButton:hover {{ background-color: {p.ACCENT_PRIMARY}; color: white; border:             1px solid {p.ACCENT_PRIMARY}; }}
        """
        self.wake_btn.setStyleSheet(btn_style)
        self.fix_all_btn.setStyleSheet(btn_style)
        
        self.status_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        self.latency_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 10px;")

    def set_sync_visible(self, visible):
        if visible: self.sync_btn.show()
        else: self.sync_btn.hide()

    def update_stats(self, current, snapshot):
        self.turn_spinbox.blockSignals(True)
        self.turn_spinbox.setValue(current)
        self.turn_spinbox.blockSignals(False)
        self.snap_spinbox.blockSignals(True)
        self.snap_spinbox.setValue(snapshot)
        self.snap_spinbox.blockSignals(False)
        
        gap = current - snapshot
        self.update_health(gap)

    def update_health(self, gap):
        p = theme_manager.get_palette()
        # 动态计算健康度颜色 (这里简单硬编码逻辑，也可以放入 Theme)
        color, bg = p.TEXT_SUCCESS, p.BG_TERTIARY
        if gap > 35: color, bg = p.TEXT_DANGER, p.BG_TERTIARY # 实际上应该用更醒目的警告色，        暂时用 Tertiary
        elif gap > 25: color, bg = p.BTN_WARNING, p.BG_TERTIARY
        
        self.health_label.setText(f"未备份: {gap}")
        self.health_label.setStyleSheet(f"color: {color}; font-weight: bold; padding: 2px         5px; border-radius: 4px; background-color: {bg}; margin-right: 5px;")

    def set_status(self, text):
        self.status_label.setText(text)
    
    def set_fix_btn_state(self, enabled, text):
        self.fix_all_btn.setEnabled(enabled)
        self.fix_all_btn.setText(text)

    def update_latency(self, ms):
        p = theme_manager.get_palette()
        if ms < 0: ms = 0
        
        color = p.TEXT_SUCCESS
        text = f"📶 {ms}ms"
        
        if ms > 1000:
            sec = ms / 1000
            color = p.TEXT_DANGER
            text = f"📶 {sec:.1f}s (拥堵)"
        elif ms > 300:
            color = p.BTN_WARNING
        elif ms > 100:
            color = p.TEXT_SECONDARY 
            
        self.latency_label.setText(text)
        self.latency_label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;        ")

    def _toggle_mode(self):
        if self._current_mode == "browser":
            self.set_mode("api")
            self.mode_switch_clicked.emit("api")
        else:
            self.set_mode("browser")
            self.mode_switch_clicked.emit("browser")

    def set_mode(self, mode):
        """更新按钮显示状态"""
        self._current_mode = mode
        p = theme_manager.get_palette()
        if mode == "api":
            self.mode_btn.setText("🤖 API")
            self.mode_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {p.ACCENT_PRIMARY}; color: white; border-radius: 4px; padding: 5px 10px; font-weight: bold; }}
                QPushButton:hover {{ background-color: {p.ACCENT_SECONDARY}; }}
            """)
        else:
            self.mode_btn.setText("🌐 浏览器")
            self.mode_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 4px; padding: 5px 10px; }}
                QPushButton:hover {{ background-color: {p.ACCENT_PRIMARY}; color: white; }}
            """)
