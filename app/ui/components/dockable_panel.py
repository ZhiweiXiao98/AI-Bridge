import logging
# filename: app/ui/components/dockable_panel.py
from PySide6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont
from app.ui.theme import theme_manager
from app.core.logging import get_logger

logger = get_logger("app.ui.dockable_panel", side="ui")

class DockablePanel(QDockWidget):
    """可停靠面板基类"""
    
    minimize_requested = Signal(str)
    docked = Signal(str)
    closed = Signal(str)
    
    def __init__(self, panel_id, title, icon_name="", parent=None):
        super().__init__(title, parent)
        
        self.panel_id = panel_id
        self.setObjectName(panel_id)  # Qt 状态恢复需要 objectName
        self.panel_title = title
        self.icon_name = icon_name or title[:2]
        self.is_floating_mode = False
        self.was_floating = False
        self.drag_position = None
        
        self.setMinimumWidth(250)
        self.resize(300, 400)
        
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea |
            Qt.DockWidgetArea.TopDockWidgetArea |
            Qt.DockWidgetArea.BottomDockWidgetArea
        )
        
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        
        self.topLevelChanged.connect(self.on_top_level_changed)
        self.create_title_bar()
        self.create_simple_title_bar()
        
        try:
            theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme()
        except Exception as e:
            logger.warning(e)
    
    def create_title_bar(self):
        """创建自定义标题栏"""
        title_widget = QWidget()
        title_widget.setObjectName("titleBar")
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(12, 8, 12, 8)
        title_layout.setSpacing(8)
        
        drag_handle = QLabel("⋮⋮")
        drag_handle.setStyleSheet("color: #6B7280; font-size: 14px;")
        title_layout.addWidget(drag_handle)
        
        self.title_label = QLabel(self.panel_title)
        title_font = QFont()
        title_font.setPixelSize(12)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        title_layout.addWidget(self.title_label)
        
        title_layout.addStretch()
        
        self.minimize_btn = QPushButton("−")
        self.minimize_btn.setObjectName("titleBarButton")
        self.minimize_btn.setFixedSize(24, 24)
        self.minimize_btn.setToolTip("最小化到图标栏")
        self.minimize_btn.clicked.connect(self.on_minimize_clicked)
        title_layout.addWidget(self.minimize_btn)
        
        # 关闭/隐藏按钮
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("titleBarButton")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setToolTip("隐藏面板")
        self.close_btn.clicked.connect(self.on_close_clicked)
        title_layout.addWidget(self.close_btn)
        
        self.title_bar_widget = title_widget
        self.setTitleBarWidget(title_widget)
    
    def create_simple_title_bar(self):
        """创建简化标题栏（仅显示按钮，用于 Tab 化时）"""
        simple_widget = QWidget()
        simple_widget.setObjectName("simpleTitleBar")
        simple_layout = QHBoxLayout(simple_widget)
        simple_layout.setContentsMargins(4, 2, 4, 2)
        simple_layout.setSpacing(4)
        
        # 最小化按钮
        self.simple_minimize_btn = QPushButton("−")
        self.simple_minimize_btn.setObjectName("titleBarButton")
        self.simple_minimize_btn.setFixedSize(20, 20)
        self.simple_minimize_btn.setToolTip("最小化到图标栏")
        self.simple_minimize_btn.clicked.connect(self.on_minimize_clicked)
        simple_layout.addWidget(self.simple_minimize_btn)
        
        # 关闭按钮
        self.simple_close_btn = QPushButton("×")
        self.simple_close_btn.setObjectName("titleBarButton")
        self.simple_close_btn.setFixedSize(20, 20)
        self.simple_close_btn.setToolTip("隐藏面板")
        self.simple_close_btn.clicked.connect(self.on_close_clicked)
        simple_layout.addWidget(self.simple_close_btn)
        
        simple_layout.addStretch()
        
        self.simple_title_bar_widget = simple_widget

    
    def create_content(self):
        """创建面板内容（子类重写）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.addWidget(QLabel(f"{self.panel_title} 内容"))
        return widget
    
    def init_content(self):
        """初始化内容"""
        container = QFrame()
        container.setObjectName("panelContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        content = self.create_content()
        container_layout.addWidget(content)
        
        self.setWidget(container)
        
        # 设置 widget 的外边距，创造卡片感
        container.setContentsMargins(4, 4, 4, 4)
    
    def on_minimize_clicked(self):
        self.minimize_requested.emit(self.panel_id)
    
    def on_top_level_changed(self, is_floating):
        if self.was_floating and not is_floating:
            self.docked.emit(self.panel_id)
        
        self.was_floating = is_floating
        
        # 检查是否在标签页中
        parent = self.parent()
        is_tabbed = False
        
        if parent and not is_floating:
            from PySide6.QtWidgets import QMainWindow
            if isinstance(parent, QMainWindow):
                area = parent.dockWidgetArea(self)
                if area != 0:
                    tabified = parent.tabifiedDockWidgets(self)
                    is_tabbed = len(tabified) > 0
        
        # 根据状态选择标题栏
        if is_tabbed:
            # Tab 化模式：显示简化标题栏
            if hasattr(self, 'simple_title_bar_widget'):
                self.setTitleBarWidget(self.simple_title_bar_widget)
        else:
            # 单独停靠和悬浮都使用完整标题栏
            if hasattr(self, 'title_bar_widget'):
                self.setTitleBarWidget(self.title_bar_widget)
        
        # 悬浮时设置无边框
        if is_floating:
            from PySide6.QtCore import Qt
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        else:
            from PySide6.QtCore import Qt
            flags = self.windowFlags()
            if flags & Qt.WindowType.FramelessWindowHint:
                self.setWindowFlags(flags & ~Qt.WindowType.FramelessWindowHint)
        
        self.apply_theme()
    def closeEvent(self, event):
        self.closed.emit(self.panel_id)
        event.accept()
    
    def show_floating(self, pos):
        self.is_floating_mode = True
        self.was_floating = True
        self.setFloating(True)
        self.move(pos)
        self.show()
    
    def get_state(self):
        return {
            "id": self.panel_id,
            "title": self.panel_title,
            "visible": self.isVisible(),
            "floating": self.isFloating(),
            "geometry": {
                "x": self.x(),
                "y": self.y(),
                "width": self.width(),
                "height": self.height()
            }
        }
    
    def restore_state(self, state):
        if "geometry" in state:
            geo = state["geometry"]
            self.setGeometry(geo["x"], geo["y"], geo["width"], geo["height"])
        
        if state.get("floating", False):
            self.setFloating(True)
        
        if state.get("visible", True):
            self.show()
        else:
            self.hide()
    
    def apply_theme(self):
        p = theme_manager.get_palette()
        is_floating = self.isFloating()
        
        if is_floating:
            border_style = f"border: 1px solid {p.BORDER}; border-radius: 8px;"
        else:
            border_style = f"border: 1px solid {p.BORDER}; border-radius: 6px;"
        
        self.setStyleSheet(f"""
            QDockWidget {{
                background-color: transparent;
            }}
            QDockWidget::title {{
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                padding: 3px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border-bottom: 1px solid {p.BORDER};
            }}
            QWidget#titleBar {{
                background-color: {p.BG_SECONDARY};
            }}
            QLabel {{
                color: {p.TEXT_PRIMARY};
                background-color: transparent;
            }}
            QFrame#panelContainer {{
                background-color: {p.BG_PRIMARY};
                {border_style}
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
            }}
            QPushButton {{
                background-color: transparent;
                color: {p.TEXT_SECONDARY};
                border: none;
                border-radius: 4px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: {p.ACCENT_PRIMARY};
            }}
            QPushButton#titleBarButton {{
                background-color: transparent;
                color: {p.TEXT_PRIMARY};
                border: none;
                padding: 4px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton#titleBarButton:hover {{
                color: {p.ACCENT_PRIMARY};
                background-color: {p.BG_TERTIARY};
                border-radius: 4px;
            }}
            QPushButton#titleBarButton:pressed {{
                color: {p.ACCENT_PRIMARY};
                background-color: {p.BG_SECONDARY};
            }}
            
            
            """)
        
        # 确保内容区域也使用主题背景色（修复悬浮时变白的问题）
        if self.widget():
            self.widget().setStyleSheet(f"background-color: {p.BG_PRIMARY};")


    def mousePressEvent(self, event):
        """处理鼠标按下事件，用于拖拽悬浮窗口"""
        from PySide6.QtCore import Qt
        if event.button() == Qt.MouseButton.LeftButton and self.isFloating():
            # 检查是否点击在标题栏区域
            if hasattr(self, 'title_bar_widget') and self.title_bar_widget:
                title_bar_rect = self.title_bar_widget.geometry()
                if title_bar_rect.contains(event.pos()):
                    self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    event.accept()
                    return
        super().mousePressEvent(event)


    def mouseMoveEvent(self, event):
        """处理鼠标移动事件，拖拽悬浮窗口"""
        from PySide6.QtCore import Qt
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position and self.isFloating():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件"""
        self.drag_position = None
        super().mouseReleaseEvent(event)





    def on_close_clicked(self):
        """关闭按钮被点击"""
        self.closed.emit(self.panel_id)
        self.hide()
