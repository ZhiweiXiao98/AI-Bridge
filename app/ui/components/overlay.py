# filename: app/ui/components/overlay.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame, QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtGui import QColor, QPainter
from app.ui.theme import theme_manager

class OverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.container = QFrame()
        self.container.setFixedSize(400, 200)
        
        shadow = QGraphicsOpacityEffect(self)
        shadow.setOpacity(0) 
        self.setGraphicsEffect(shadow)
        self.anim = QPropertyAnimation(shadow, b"opacity")
        self.anim.setDuration(300)
        
        c_layout = QVBoxLayout(self.container)
        
        self.icon_lbl = QLabel("🚑")
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_lbl.setStyleSheet("font-size: 48px; background: transparent; border: none;")
        
        self.text_lbl = QLabel("正在前往侧车维修站...")
        self.text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.sub_lbl = QLabel("AI 正在接管控制权，请勿操作")
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        c_layout.addStretch()
        c_layout.addWidget(self.icon_lbl)
        c_layout.addWidget(self.text_lbl)
        c_layout.addWidget(self.sub_lbl)
        c_layout.addStretch()
        
        layout.addWidget(self.container)
        
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {p.BG_SECONDARY};
                border: 1px solid {p.BORDER};
                border-radius: 16px;
            }}
        """)
        self.text_lbl.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-size: 18px; font-weight: bold; background: transparent; border: none; margin-top: 10px;")
        self.sub_lbl.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;")

    def show_message(self, icon, text, subtext=""):
        self.icon_lbl.setText(icon)
        self.text_lbl.setText(text)
        self.sub_lbl.setText(subtext)
        if self.parent():
            self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.anim.setStartValue(0); self.anim.setEndValue(1); self.anim.start()

    def hide_message(self):
        self.anim.setStartValue(1); self.anim.setEndValue(0); self.anim.finished.connect(self.hide); self.anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))