# filename: app/ui/components/base.py
import requests
import os
from PySide6.QtWidgets import (QLabel, QDialog, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QFileDialog, QApplication, QWidget, QMenu, QFrame,
                               QSizePolicy)
from PySide6.QtCore import Qt, Signal, QThread, QPoint, QRectF, QUrl
from PySide6.QtGui import QImage, QPixmap, QAction, QPainter, QColor, QCursor, QIcon
from app.core.config import ConfigManager
from app.core.app_constants import LOCAL_SERVER_HOST, SERVER_PORT

class ImageLoader(QThread):
    loaded = Signal(QPixmap)
    
    def __init__(self, url, parent=None):
        super().__init__(parent) # [Fix] 绑定父对象，随父对象销毁
        self.url = url
        self.config = ConfigManager.load()
    
    def run(self):
        try:
            final_url = self.url
            # 处理 served:// 伪协议
            if self.url.startswith("served://"):
                filename = self.url.replace("served://", "")
                host = self.config.get("server_ip", LOCAL_SERVER_HOST)
                port = self.config.get("server_port", SERVER_PORT)
                final_url = f"http://{host}:{port}/images/{filename}"
            
            # [Fix] 再次检查协议，防止 requests 处理非 HTTP 链接
            if not final_url.startswith("http"):
                return 

            headers = {"User-Agent": "Mozilla/5.0"}
            # 设置较短超时，防止线程挂死
            resp = requests.get(final_url, headers=headers, timeout=10, proxies={"http": None, "https": None})
            
            if resp.status_code == 200:
                img = QImage()
                # 必须从数据加载，因为 QImage 直接 load 文件名只支持本地
                img.loadFromData(resp.content)
                if not img.isNull():
                    pixmap = QPixmap.fromImage(img)
                    self.loaded.emit(pixmap)
        except Exception as e:
            print(f"Image load failed: {e}")

class ImagePreviewDialog(QDialog):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.original_pixmap = pixmap
        self.scale_factor = 1.0
        self.offset = QPoint(0, 0)
        self.is_dragging = False
        self.last_mouse_pos = QPoint()
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        if parent:
            screen_geo = parent.screen().availableGeometry()
            self.setGeometry(screen_geo)
        else:
            self.resize(1200, 800)

        self.init_ui()
        self.fit_to_screen()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 20)
        
        layout.addStretch()
        
        toolbar = QFrame()
        toolbar.setFixedHeight(50)
        toolbar.setFixedWidth(400)
        toolbar.setStyleSheet("""
            QFrame {
                background-color: rgba(50, 50, 50, 0.8);
                border-radius: 25px;
                border: 1px solid #555;
            }
            QPushButton {
                background: transparent;
                color: white;
                border: none;
                font-weight: bold;
                font-size: 14px;
                padding: 5px 15px;
            }
            QPushButton:hover { color: #6366F1; background-color: rgba(255,255,255,0.1); border-radius: 15px; }
        """)
        
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 5, 10, 5)
        
        btn_fit = QPushButton("适应"); btn_fit.clicked.connect(self.fit_to_screen)
        btn_100 = QPushButton("1:1"); btn_100.clicked.connect(self.reset_scale)
        btn_copy = QPushButton("复制"); btn_copy.clicked.connect(self.copy_image)
        btn_save = QPushButton("下载"); btn_save.clicked.connect(self.save_image)
        btn_close = QPushButton("关闭"); btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet("color: #EF4444;")
        
        tb_layout.addWidget(btn_fit)
        tb_layout.addWidget(btn_100)
        tb_layout.addWidget(btn_copy)
        tb_layout.addWidget(btn_save)
        tb_layout.addWidget(btn_close)
        
        h_layout = QHBoxLayout()
        h_layout.addStretch()
        h_layout.addWidget(toolbar)
        h_layout.addStretch()
        
        layout.addLayout(h_layout)
        
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        painter.fillRect(self.rect(), QColor(0, 0, 0, 230))
        
        if self.original_pixmap.isNull(): return

        scaled_w = self.original_pixmap.width() * self.scale_factor
        scaled_h = self.original_pixmap.height() * self.scale_factor
        
        center_x = self.width() / 2 + self.offset.x()
        center_y = self.height() / 2 + self.offset.y()
        
        draw_rect = QRectF(
            center_x - scaled_w / 2,
            center_y - scaled_h / 2,
            scaled_w,
            scaled_h
        )
        
        painter.drawPixmap(draw_rect.toRect(), self.original_pixmap)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        zoom_speed = 0.1
        if delta > 0:
            self.scale_factor *= (1 + zoom_speed)
        else:
            self.scale_factor *= (1 - zoom_speed)
            if self.scale_factor < 0.1: self.scale_factor = 0.1
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.pos())

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            delta = event.pos() - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        self.fit_to_screen()

    def show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #2D2D30; color: white; border: 1px solid #555; } QMenu::item:selected { background-color: #6366F1; }")
        
        act_copy = QAction("📋 复制图片", self)
        act_copy.triggered.connect(self.copy_image)
        menu.addAction(act_copy)
        
        act_save = QAction("💾 另存为...", self)
        act_save.triggered.connect(self.save_image)
        menu.addAction(act_save)
        
        menu.exec(self.mapToGlobal(pos))

    def fit_to_screen(self):
        ratio_w = self.width() / self.original_pixmap.width()
        ratio_h = self.height() / self.original_pixmap.height()
        self.scale_factor = min(ratio_w, ratio_h) * 0.9 
        self.offset = QPoint(0, 0)
        self.update()

    def reset_scale(self):
        self.scale_factor = 1.0
        self.offset = QPoint(0, 0)
        self.update()

    def save_image(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存图片", "image.png", "Images (*.png *.jpg *.bmp)")
        if path:
            self.original_pixmap.save(path)

    def copy_image(self):
        QApplication.clipboard().setPixmap(self.original_pixmap)

class ImageBox(QLabel):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.setText("Loading Image...")
        self.setStyleSheet("color: #6B7280; font-size: 12px; border: 1px dashed #374151; padding: 20px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(True)
        self.setMaximumSize(400, 400)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.full_pixmap = None 
        self.loader = None

        # [Fix] 优先处理本地文件协议，不再启动线程
        if self.url.startswith("file:///"):
            local_path = self.url.replace("file:///", "")
            # Windows 路径兼容 (file:///Z:/... -> Z:/...)
            if os.name == 'nt' and len(local_path) > 2 and local_path[1] == ':':
                pass # 已经是绝对路径
            elif os.name == 'nt' and local_path.startswith("/"): # file:///C:/...
                local_path = local_path.lstrip("/")
            
            if os.path.exists(local_path):
                self.load_local_image(local_path)
            else:
                self.setText(f"Image Not Found: {os.path.basename(local_path)}")
        else:
            # 只有 HTTP 链接才启动线程
            self.loader = ImageLoader(url, self) # [Fix] 传入 self 作为父对象
            self.loader.loaded.connect(self.on_loaded)
            self.loader.start()

    def load_local_image(self, path):
        img = QImage(path)
        if not img.isNull():
            self.on_loaded(QPixmap.fromImage(img))
        else:
            self.setText("Invalid Image")

    def on_loaded(self, pixmap):
        if not pixmap.isNull():
            self.full_pixmap = pixmap
            
            # 自适应调整大小，但限制最大尺寸
            w = min(pixmap.width(), 400)
            scale = w / pixmap.width()
            h = int(pixmap.height() * scale)
            self.setFixedSize(w, h)
            
            self.setPixmap(pixmap)
            self.setStyleSheet("border: none; padding: 0;")
            self.setText("")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.full_pixmap:
            viewer = ImagePreviewDialog(self.full_pixmap, self.window())
            viewer.exec()
            
    # [Fix] 确保销毁时停止线程
    def closeEvent(self, event):
        if self.loader and self.loader.isRunning():
            self.loader.terminate()
            self.loader.wait()
        super().closeEvent(event)