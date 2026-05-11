# filename: app/ui/pages/chat/session_list.py
from PySide6.QtWidgets import (QListWidget, QListWidgetItem, QMenu)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QAction
from app.ui.components.session_item import SessionItemWidget
from app.ui.theme import Theme, Palette, theme_manager

class SessionList(QListWidget):
    session_selected = Signal(int)
    role_assigned = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.itemClicked.connect(self.on_item_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        self.last_occupancy_map = {}
        self.session_roles = {} 
        
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"""
            QListWidget {{ background-color: {p.BG_SECONDARY}; border: none; outline:             none; }} 
            QListWidget::item {{ border-bottom: 1px solid {p.BORDER}; padding: 0px; }} 
            QListWidget::item:selected {{ background-color: {p.BG_TERTIARY}; }}
        """)
        # 列表项内的 SessionItemWidget 需要刷新，但因为它们是独立的 Widget，
        # 我们需要在这里触发它们的重绘，或者依靠 SessionItemWidget 自己监听信号（推荐后者，        Batch 2处理）
        # 这里先确保容器背景正确

    def on_item_clicked(self, item):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.session_selected.emit(idx)

    def show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item: return
        idx = item.data(Qt.ItemDataRole.UserRole)
        p = theme_manager.get_palette()
        
        menu = QMenu(self)
        menu.setStyleSheet(f"QMenu {{ background-color: {p.BG_SECONDARY}; color: {p.        TEXT_PRIMARY}; border: 1px solid {p.BORDER}; }} QMenu::item:selected {{         background-color: {p.ACCENT_PRIMARY}; }}")
        
        act_arch = QAction("🧠 设为主会话 (Architect)", self)
        act_mech = QAction("🛠️ 设为侧车会话 (Mechanic)", self)
        act_clear = QAction("❌ 清除标记", self)
        
        act_arch.triggered.connect(lambda: self.set_role(idx, "architect"))
        act_mech.triggered.connect(lambda: self.set_role(idx, "mechanic"))
        act_clear.triggered.connect(lambda: self.set_role(idx, None))
        
        menu.addAction(act_arch)
        menu.addAction(act_mech)
        menu.addSeparator()
        menu.addAction(act_clear)
        
        menu.exec(self.mapToGlobal(pos))

    def set_role(self, idx, role):
        keys_to_remove = [k for k, v in self.session_roles.items() if v == role]
        for k in keys_to_remove:
            if role: del self.session_roles[k]
            
        if role:
            self.session_roles[idx] = role
        else:
            if idx in self.session_roles: del self.session_roles[idx]
            
        self.role_assigned.emit(idx, role)
        self.refresh_ui_roles()

    def refresh_ui_roles(self):
        for i in range(self.count()):
            item = self.item(i)
            idx = item.data(Qt.ItemDataRole.UserRole)
            widget = self.itemWidget(item)
            if widget:
                # 暂时不做前缀处理，等 SessionItemWidget 升级支持
                pass 
        # 触发 Worker 更新会话列表以刷新显示

    def update_list(self, sessions):
        self.clear()
        for s in sessions:
            idx = s.get('index', -1)
            role = self.session_roles.get(idx)
            
            title_prefix = ""
            if role == "architect": title_prefix = "🧠 "
            elif role == "mechanic": title_prefix = "🛠️ "
            
            title = title_prefix + s['title']
            date_str = s.get('date', '')
            icon_char = s.get('icon', '')
            is_active = s.get('active', False)
            
            item = QListWidgetItem(self)
            item.setSizeHint(QSize(200, 60))
            item.setData(Qt.ItemDataRole.UserRole, idx)
            
            widget = SessionItemWidget(title, date_str, icon_char, is_active)
            self.setItemWidget(item, widget)
            
            if is_active:
                item.setSelected(True)
                self.setCurrentItem(item)
        
        if self.last_occupancy_map:
            self.update_occupancy(self.last_occupancy_map)

    def update_occupancy(self, occupancy_map):
        self.last_occupancy_map = occupancy_map 
        clean_map = {}
        for k, v in occupancy_map.items():
            try: clean_map[int(k)] = v
            except: pass

        for i in range(self.count()):
            item = self.item(i)
            idx = item.data(Qt.ItemDataRole.UserRole)
            widget = self.itemWidget(item)
            
            if widget and idx in clean_map:
                users = clean_map[idx]
                widget.set_occupancy(", ".join(users))
            elif widget:
                widget.set_occupancy(None)