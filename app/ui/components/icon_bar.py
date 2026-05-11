import logging
# filename: app/ui/components/icon_bar.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolTip
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QPainter, QPixmap, QFont, QColor
from app.ui.theme import theme_manager
from app.core.logging import get_logger

logger = get_logger("app.ui.icon_bar", side="ui")

class PanelIconButton(QWidget):
    """面板图标按钮：图标 + 横向文字"""
    
    clicked = Signal()
    
    def __init__(self, panel_name, short_name, icon_pixmap, description="", parent=None):
        super().__init__(parent)
        self.panel_name = panel_name
        self.short_name = short_name
        self.description = description
        self.icon_pixmap = icon_pixmap
        self.is_active = False
        self.is_hovered = False
        
        # 创建布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 8, 5, 8)
        layout.setSpacing(5)
        
        # 图标
        icon_label = QLabel()
        icon_label.setPixmap(icon_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        
        # 文字（横向）
        self.text_label = QLabel(short_name)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self.text_label)
        
        # 设置大小
        self.setFixedWidth(60)
        self.setMinimumHeight(75)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 应用主题
        self.apply_theme()
    
    def mousePressEvent(self, event):
        """鼠标点击"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
    
    def enterEvent(self, event):
        """鼠标进入"""
        self.is_hovered = True
        self.update()
        
        # 显示完整提示
        if self.description:
            tooltip_text = f"{self.panel_name}\n{self.description}"
        else:
            tooltip_text = self.panel_name
        
        QToolTip.showText(
            self.mapToGlobal(QPoint(self.width() + 5, 0)),
            tooltip_text,
            self
        )
    
    def leaveEvent(self, event):
        """鼠标离开"""
        self.is_hovered = False
        self.update()
    
    def paintEvent(self, event):
        """绘制背景"""
        painter = QPainter(self)
        p = theme_manager.get_palette()
        
        if self.is_active:
            painter.fillRect(self.rect(), QColor(p.BG_TERTIARY))
        elif self.is_hovered:
            painter.fillRect(self.rect(), QColor(p.BG_SECONDARY))
    
    def set_active(self, active):
        """设置激活状态"""
        self.is_active = active
        self.update()
    
    def apply_theme(self):
        """应用主题"""
        p = theme_manager.get_palette()
        self.text_label.setStyleSheet(f"font-size: 10px; color: {p.TEXT_PRIMARY};")
        self.update()


class IconBar(QWidget):
    """图标栏：显示折叠的面板图标"""
    
    icon_clicked = Signal(str)  # 发送面板名称
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(60)
        
        # 创建布局
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 8, 0, 8)
        self.layout.setSpacing(5)
        self.layout.addStretch()
        
        # 存储图标按钮
        self.icon_buttons = {}
        
        # 应用主题
        try:
            theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme()
        except Exception as e:
            logger.warning(e)
    
    def add_panel_icon(self, panel_name, short_name, icon_pixmap, description=""):
        """添加面板图标"""
        if panel_name in self.icon_buttons:
            return
        
        btn = PanelIconButton(panel_name, short_name, icon_pixmap, description, self)
        btn.clicked.connect(lambda: self.icon_clicked.emit(panel_name))
        
        self.layout.insertWidget(self.layout.count() - 1, btn)
        self.icon_buttons[panel_name] = btn
        
        self.apply_theme()
    
    def remove_panel_icon(self, panel_name):
        """移除面板图标"""
        if panel_name in self.icon_buttons:
            btn = self.icon_buttons[panel_name]
            self.layout.removeWidget(btn)
            btn.deleteLater()
            del self.icon_buttons[panel_name]
    
    def set_icon_active(self, panel_name, active):
        """设置图标激活状态"""
        if panel_name in self.icon_buttons:
            self.icon_buttons[panel_name].set_active(active)
    
    def apply_theme(self):
        """应用主题"""
        p = theme_manager.get_palette()
        
        self.setStyleSheet(f"""
            IconBar {{
                background-color: {p.BG_SECONDARY};
                border-left: 1px solid {p.BORDER};
            }}
        """)
        
        for btn in self.icon_buttons.values():
            btn.apply_theme()
