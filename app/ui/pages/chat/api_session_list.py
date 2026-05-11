# filename: app/ui/pages/chat/api_session_list.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QMenu, QLabel, QLineEdit, QApplication
)
from PySide6.QtCore import Qt, QSize, Signal, QEvent, QPoint
from PySide6.QtGui import QAction
from app.ui.components.session_item import SessionItemWidget
from app.ui.theme import theme_manager


class APISessionList(QWidget):
    """API 对话列表组件（独立 Tab）"""
    session_selected = Signal(str)       # conv_id
    new_conversation = Signal(str)       # title
    delete_conversation = Signal(str)    # conv_id
    rename_conversation = Signal(str, str)  # conv_id, new_title
    pin_conversation = Signal(str)
    unpin_conversation = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._conversations = []  # 缓存当前对话列表
        self._editing_conv_id = None
        self._editing_original_title = ""
        self._pending_new_item = None
        self.init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        #顶部：新建对话按钮
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(8, 6, 8, 6)
        self.new_btn = QPushButton("+ 新建对话")
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(self._on_new_clicked)
        top_bar.addWidget(self.new_btn)
        layout.addLayout(top_bar)

        # 对话列表
        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)

        # 底部状态
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_SECONDARY};")
        self.new_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.ACCENT_PRIMARY}; color: #fff;
                border: none; border-radius: 4px; padding: 6px 12px;
                font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {p.ACCENT_HOVER}; }}
        """)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{ background-color: {p.BG_SECONDARY}; border: none; outline: none; }}
            QListWidget::item {{ border-bottom: 1px solid {p.BORDER}; padding: 0px; }}
            QListWidget::item:selected {{ background-color: {p.BG_TERTIARY}; }}
        """)
        self.status_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 11px; padding: 4px;")

    def update_sessions(self, conversations: list):
        """更新 API 对话列表"""
        self._conversations = conversations
        self.list_widget.clear()

        if not conversations:
            self.status_label.setText("暂无对话，点击上方按钮新建")
            self.list_widget.clearSelection()
            self.list_widget.setCurrentItem(None)
            self.list_widget.setCurrentRow(-1)
            self.list_widget.viewport().update()
        else:
            self.status_label.setText(f"{len(conversations)} 个对话")

        for conv in conversations:
            title = conv.get("title", "未命名")
            date_str = conv.get("date", "")
            is_active = conv.get("active", False)
            conv_id = conv.get("id", "")
            turns = conv.get("turns", 0)
            icon = conv.get("icon", "🤖")

            item = QListWidgetItem(self.list_widget)
            item.setSizeHint(QSize(200, 60))
            item.setData(Qt.ItemDataRole.UserRole, conv_id)

            pinned = conv.get("pinned", False)
            display_title = f"📍 {title}" if pinned else f"{title}"
            if turns > 0:
                display_title += f" ({turns}轮)"

            widget = SessionItemWidget(display_title, date_str, icon, is_active, source="api")
            self.list_widget.setItemWidget(item, widget)

            if is_active:
                item.setSelected(True)
                self.list_widget.setCurrentItem(item)

    def _on_item_clicked(self, item):
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if conv_id:
            self.session_selected.emit(conv_id)

    def _on_new_clicked(self):
        if self._editing_conv_id is not None:
            return
        self._start_inline_new()

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        p = theme_manager.get_palette()

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {p.BG_SECONDARY}; color: {p.TEXT_PRIMARY};
                     border: 1px solid {p.BORDER}; }}
            QMenu::item:selected {{ background-color: {p.ACCENT_PRIMARY}; }}
        """)

        conv = next((c for c in self._conversations if c.get("id") == conv_id), {})
        is_pinned = bool(conv.get("pinned", False))

        act_rename = QAction("✏️ 重命名", self)
        act_delete = QAction("🗑️ 删除", self)
        act_pin = QAction("📌 置顶", self)
        act_unpin = QAction("📍 取消置顶", self)

        act_rename.triggered.connect(lambda: self._start_inline_rename(conv_id))
        act_delete.triggered.connect(lambda: self.delete_conversation.emit(conv_id))
        act_pin.triggered.connect(lambda: self.pin_conversation.emit(conv_id))
        act_unpin.triggered.connect(lambda: self.unpin_conversation.emit(conv_id))

        menu.addAction(act_rename)
        menu.addSeparator()
        if is_pinned:
            menu.addAction(act_unpin)
        else:
            menu.addAction(act_pin)
        menu.addSeparator()
        menu.addAction(act_delete)
        menu.exec(self.list_widget.mapToGlobal(pos))

    def _start_inline_rename(self, conv_id):
        self._editing_conv_id = conv_id
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) != conv_id:
                continue
            current_title = ""
            for c in self._conversations:
                if c.get("id") == conv_id:
                    current_title = c.get("title", "")
                    break
            self._editing_original_title = current_title
            editor = QLineEdit(current_title, self.list_widget)
            editor.selectAll()
            editor.installEventFilter(self)
            QApplication.instance().installEventFilter(self)
            editor.returnPressed.connect(lambda cid=conv_id, e=editor: self._commit_inline_rename(cid, e))
            self.list_widget.setItemWidget(item, editor)
            editor.setFocus()
            break

    def _start_inline_new(self):
        self._editing_conv_id = "__new__"
        self._editing_original_title = "新对话"
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(200, 60))
        item.setData(Qt.ItemDataRole.UserRole, "__new__")
        self.list_widget.insertItem(0, item)
        self._pending_new_item = item

        editor = QLineEdit(self._editing_original_title, self.list_widget)
        editor.selectAll()
        editor.installEventFilter(self)
        QApplication.instance().installEventFilter(self)
        editor.returnPressed.connect(lambda e=editor: self._commit_inline_new(e))
        self.list_widget.setItemWidget(item, editor)
        self.list_widget.setCurrentItem(item)
        editor.setFocus()

    def _commit_inline_rename(self, conv_id, editor):
        if self._editing_conv_id != conv_id:
            return
        QApplication.instance().removeEventFilter(self)
        self._editing_conv_id = None
        new_title = editor.text().strip()
        if new_title:
            self.rename_conversation.emit(conv_id, new_title)
        else:
            self.update_sessions(self._conversations)

    def _commit_inline_new(self, editor):
        if self._editing_conv_id != "__new__":
            return
        QApplication.instance().removeEventFilter(self)
        self._editing_conv_id = None
        new_title = editor.text().strip()
        item = self._pending_new_item
        self._pending_new_item = None
        if item is not None:
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)
        if new_title:
            self.new_conversation.emit(new_title)
        else:
            self.update_sessions(self._conversations)

    def _cancel_inline_edit(self):
        QApplication.instance().removeEventFilter(self)
        if self._editing_conv_id == "__new__":
            self._editing_conv_id = None
            item = self._pending_new_item
            self._pending_new_item = None
            if item is not None:
                row = self.list_widget.row(item)
                self.list_widget.takeItem(row)
            self.update_sessions(self._conversations)
            return

        if self._editing_conv_id:
            self._editing_conv_id = None
            self.update_sessions(self._conversations)

    def eventFilter(self, obj, event):
        if isinstance(obj, QLineEdit) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_inline_edit()
                return True

        if self._editing_conv_id is not None and event.type() == QEvent.Type.MouseButtonPress:
            editor = self.focusWidget()
            if isinstance(editor, QLineEdit):
                if obj is editor:
                    return super().eventFilter(obj, event)

                global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                local_pos = editor.mapFromGlobal(global_pos)
                if editor.rect().contains(local_pos):
                    return super().eventFilter(obj, event)

                if event.button() == Qt.MouseButton.LeftButton:
                    if self._editing_conv_id == "__new__":
                       self._commit_inline_new(editor)
                    else:
                        self._commit_inline_rename(self._editing_conv_id, editor)
                    return True

                if event.button() == Qt.MouseButton.RightButton:
                    self._cancel_inline_edit()
                    return True

        return super().eventFilter(obj, event)

