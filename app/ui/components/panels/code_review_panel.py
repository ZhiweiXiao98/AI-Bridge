# filename: app/ui/components/panels/code_review_panel.py
"""
代码审查面板
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QListWidget, QListWidgetItem, QFrame, QMenu, QMessageBox)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QBrush, QCursor
from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager
from app.core.config import ConfigManager
import os

class CodeReviewPanel(DockablePanel):
    """代码审查面板"""
    
    # 信号
    request_scan = Signal()
    request_apply = Signal(list)
    request_clear_cache = Signal()
    
    def __init__(self):
        super().__init__("code_review", "代码审查", "🧬")
        self.init_content()
    
    def create_content(self):
        """创建面板内容"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # 按钮行
        btn_layout = QHBoxLayout()
        
        self.btn_scan = QPushButton("扫描")
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.clicked.connect(self.on_scan_clicked)
        
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self.on_clear_clicked)
        
        self.btn_apply = QPushButton("应用变更")
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.on_apply_clicked)
        
        btn_layout.addWidget(self.btn_scan)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        
        layout.addLayout(btn_layout)
        
        # 更新列表
        self.update_list = QListWidget()
        self.update_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.update_list.customContextMenuRequested.connect(self.show_context_menu)
        self.update_list.itemDoubleClicked.connect(self.on_item_dbl_click)
        self.update_list.setFrameShape(QFrame.Shape.NoFrame)
        self.update_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        
        layout.addWidget(self.update_list)
        
        # 应用主题
        theme_manager.theme_changed.connect(self.apply_content_theme)
        self.apply_content_theme()
        
        return widget
    
    def apply_content_theme(self):
        """应用内容主题"""
        p = theme_manager.get_palette()
        
        btn_style = f"""
            QPushButton {{ 
                background-color: #3f3f46; 
                color: #f4f4f5; 
                border: 1px solid #52525b; 
                border-radius: 4px; 
                padding: 6px 12px; 
                font-size: 11px; 
            }}
            QPushButton:hover {{ background-color: #52525b; }}
        """
        self.btn_scan.setStyleSheet(btn_style)
        
        self.btn_clear.setStyleSheet(btn_style.replace("#3f3f46", p.BTN_DANGER).replace("border: 1px solid #52525b", "border: none"))
        
        self.btn_apply.setStyleSheet(f"""
            QPushButton {{ 
                background-color: {p.BTN_SUCCESS}; 
                color: white; 
                border: none; 
                border-radius: 4px; 
                font-weight: bold; 
                font-size: 11px; 
                padding: 6px 12px; 
            }}
            QPushButton:hover {{ background-color: {p.BTN_SUCCESS_HOVER}; }}
            QPushButton:disabled {{ background-color: #3f3f46; color: #71717a; }}
        """)
        
        self.update_list.setStyleSheet(f"""
            QListWidget {{ 
                background: transparent; 
                border: none; 
                outline: none; 
            }}
            QListWidget::item {{ 
                padding: 6px 4px; 
                border-bottom: 1px solid #3f3f46; 
                color: #e4e4e7; 
            }}
            QListWidget::item:selected {{ 
                background-color: {p.ACCENT_PRIMARY}40; 
                border-radius: 4px; 
                color: white; 
            }}
            QListWidget::item:hover {{ 
                background-color: #3f3f46; 
                border-radius: 4px; 
            }}
        """)
    
    def on_scan_clicked(self):
        """扫描按钮点击"""
        self.update_list.clear()
        self.update_list.addItem(QListWidgetItem("⏳ 扫描中..."))
        self.request_scan.emit()
    
    def on_clear_clicked(self):
        """清空按钮点击"""
        reply = QMessageBox.question(
            self, "确认清空", 
            "确定要清空所有代码暂存区吗？\n这将删除 export/code 下的所有未应用文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.request_clear_cache.emit()
    
    def on_apply_clicked(self):
        """应用按钮点击"""
        paths = [
            self.update_list.item(i).data(Qt.ItemDataRole.UserRole) 
            for i in range(self.update_list.count()) 
            if self.update_list.item(i).data(Qt.ItemDataRole.UserRole)
        ]
        if paths:
            self.request_apply.emit(paths)
            self.update_list.clear()
            self.btn_apply.setEnabled(False)
    
    def update_change_list(self, changes):
        """更新变更列表"""
        self.update_list.clear()
        count = 0
        
        for c in changes:
            status = c.get('status', 'unknown')
            path = c.get('rel_path', '???')
            if status == "same":
                continue
            
            count += 1
            item = QListWidgetItem(f"[{status.upper()}] {path}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            
            if status == "new":
                item.setForeground(QBrush(QColor("#34d399")))
            elif status == "overwrite":
                item.setForeground(QBrush(QColor("#fbbf24")))
            
            self.update_list.addItem(item)
        
        self.btn_apply.setEnabled(count > 0)
        self.btn_apply.setText(f"应用 ({count})")
        
        if count == 0:
            item = QListWidgetItem("✨ All clean")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.update_list.addItem(item)
    
    def on_item_dbl_click(self, item):
        """列表项双击"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            main_win = self.window()
            if hasattr(main_win, 'show_preview_dialog'):
                main_win.show_preview_dialog(path)
    
    def show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.update_list.itemAt(pos)
        if not item:
            return
        
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        
        menu = QMenu(self)
        
        # 永久忽略
        act_ignore = menu.addAction("🚫 永久忽略 (加入黑名单)")
        act_ignore.triggered.connect(lambda: self.handle_permanent_ignore(item))
        
        # 删除缓存
        act_delete = menu.addAction("🗑️ 删除缓存 (本次跳过)")
        act_delete.triggered.connect(lambda: self.handle_delete_cache(item))
        
        # 样式
        menu.setStyleSheet("""
            QMenu { 
                background-color: #27272a; 
                border: 1px solid #3f3f46; 
                color: #e4e4e7; 
            }}
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background-color: #3f3f46; }
        """)
        
        menu.exec(QCursor.pos())
    
    def handle_permanent_ignore(self, item):
        """处理永久忽略"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        
        try:
            cfg = ConfigManager.load()
            current_ignored = cfg.get("ignored_files", "")
            ignored_list = [line.strip() for line in current_ignored.split('\n') if line.strip()]
            
            if path not in ignored_list:
                ignored_list.append(path)
                cfg["ignored_files"] = "\n".join(ignored_list)
                ConfigManager.save(cfg)
                print(f"🛡️ 已添加至黑名单: {path}")
                self.handle_delete_cache(item)
            else:
                print(f"ℹ️ 文件已在黑名单中: {path}")
        except Exception as e:
            print(f"❌ 拉黑失败: {e}")
    
    def handle_delete_cache(self, item):
        """处理删除缓存"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            try:
                cfg = ConfigManager.load()
                staging_dir = cfg.get("export_code_path", "export/code")
                full_path = os.path.join(staging_dir, path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                    print(f"🗑️ 已删除缓存文件: {path}")
            except Exception as e:
                print(f"⚠️ 删除文件失败: {e}")
        
        # 视觉移除
        row = self.update_list.row(item)
        self.update_list.takeItem(row)
        self.btn_apply.setEnabled(self.update_list.count() > 0)
