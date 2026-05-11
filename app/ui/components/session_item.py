# filename: app/ui/components/session_item.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from app.ui.theme import Theme, Palette, theme_manager

class SessionItemWidget(QWidget):
    def __init__(self, title, date, icon_char, is_active, parent=None, source="browser"):
        super().__init__(parent)
        self.is_active = is_active
        self.source = source
        self.title_text = title
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        
        # 1. 头像
        self.avatar = QLabel(icon_char[0] if icon_char else title[0].upper())
        self.avatar.setFixedSize(36, 36)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.avatar)
        
        # 2. 文本区域
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        
        self.lbl_title = QLabel(title)
        text_layout.addWidget(self.lbl_title)
        
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        
        self.lbl_date = QLabel(date)
        meta_row.addWidget(self.lbl_date)
        
        self.lbl_tag = QLabel("") 
        self.lbl_tag.hide()
        meta_row.addWidget(self.lbl_tag)
        
        # 来源标识
        if source == "api":
            self.lbl_source = QLabel("API")
            self.lbl_source.setFixedWidth(30)
        else:
            self.lbl_source = QLabel("")
            self.lbl_source.hide()
        meta_row.addWidget(self.lbl_source)
        
        meta_row.addStretch()
        text_layout.addLayout(meta_row)
        layout.addLayout(text_layout)
        
        theme_manager.theme_changed.connect(self.update_style)
        self.update_style()

    def update_style(self):
        p = theme_manager.get_palette()
        
        bg_color = p.ACCENT_PRIMARY if self.is_active else p.BG_TERTIARY
        fg_color = "white" if self.is_active else p.TEXT_PRIMARY
        
        self.avatar.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: {fg_color};
                border-radius: 18px;
                font-weight: bold;
                font-size: 16px;
            }}
        """)
        
        title_weight = "bold" if self.is_active else "normal"
        title_color = p.TEXT_PRIMARY if self.is_active else p.TEXT_SECONDARY
        self.lbl_title.setStyleSheet(f"font-weight: {title_weight}; font-size: 13px; color: {title_color}; background: transparent;")
        
        self.lbl_date.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        
        if hasattr(self, 'lbl_source') and self.source == "api":
            self.lbl_source.setStyleSheet(f"color: {p.ACCENT_PRIMARY}; font-size: 9px; font-weight: bold; background: transparent;")
        
    def set_occupancy(self, username):
        p = theme_manager.get_palette()
        if username and username != "Unknown":
            self.lbl_tag.setText(f"👁️ {username}")
            self.lbl_tag.setStyleSheet(f"""
                color: {p.BTN_WARNING}; 
                font-size: 10px; 
                font-weight: bold;
                background: transparent;
            """)
            self.lbl_tag.show()
        else:
            self.lbl_tag.hide()