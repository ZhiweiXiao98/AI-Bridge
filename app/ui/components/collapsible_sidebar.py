# filename: app/ui/components/collapsible_sidebar.py
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QPainter, QPen
from app.ui.theme import theme_manager

class ToggleHandle(QPushButton):
    """通用悬浮手柄"""
    def __init__(self, direction='left', parent=None):
        super().__init__(parent)
        self.direction = direction # 'left' (for left sidebar) or 'right' (for right sidebar)
        self.setFixedSize(14, 60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(True)
        self.hovered = False
        self.setStyleSheet("background: transparent; border: none;")
        
    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        p = theme_manager.get_palette()
        is_dark = p.BG_PRIMARY.startswith("#1") or p.BG_PRIMARY.startswith("#0")
        
        if self.hovered:
            bg_color = QColor(p.ACCENT_PRIMARY)
            bg_color.setAlpha(200)
            icon_color = QColor("white")
        else:
            bg_color = QColor(p.BG_TERTIARY)
            bg_color.setAlpha(150) if is_dark else bg_color.setAlpha(180)
            icon_color = QColor(p.TEXT_SECONDARY)

        rect = self.rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        
        # 绘制圆角矩形
        painter.drawRoundedRect(rect, 4, 4)
        
        # 绘制箭头
        painter.setPen(QPen(icon_color, 2))
        cx, cy = rect.width() / 2, rect.height() / 2
        off = 3
        
        # 根据方向和状态决定箭头指向
        # isChecked=True 表示展开状态
        is_expanded = self.isChecked()
        
        show_left_arrow = False
        
        if self.direction == 'left':
            # 左侧栏：展开时显示 < (收起)，折叠时显示 > (展开)
            show_left_arrow = is_expanded
        else:
            # 右侧栏：展开时显示 > (收起)，折叠时显示 < (展开)
            show_left_arrow = not is_expanded

        if show_left_arrow: 
            # <
            pts = [QPoint(int(cx+off), int(cy-off)), QPoint(int(cx-off/2), int(cy)), QPoint(int(cx+off), int(cy+off))]
        else: 
            # >
            pts = [QPoint(int(cx-off), int(cy-off)), QPoint(int(cx+off/2), int(cy)), QPoint(int(cx-off), int(cy+off))]
            
        painter.drawPolyline(pts)

class CollapsibleSideBar(QFrame):
    request_toggle = Signal()

    def __init__(self, content_widget, direction='left', parent=None):
        super().__init__(parent)
        self.direction = direction
        self.content = content_widget
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.addWidget(self.content)
        
        self.handle = ToggleHandle(direction, self)
        self.handle.clicked.connect(self.request_toggle.emit)
        
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(0) 

    def resizeEvent(self, event):
        h_w, h_h = self.handle.width(), self.handle.height()
        
        if self.direction == 'left':
            # 左侧栏：手柄在右边缘
            x = self.width() - h_w
        else:
            # 右侧栏：手柄在左边缘
            x = 0
            
        y = (self.height() - h_h) // 2
        self.handle.move(x, y)
        self.handle.raise_()
        super().resizeEvent(event)

    def set_content_visible(self, visible):
        self.content.setVisible(visible)
        self.handle.setChecked(visible)