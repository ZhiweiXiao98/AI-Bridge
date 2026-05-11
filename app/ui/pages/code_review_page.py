import logging
# filename: app/ui/pages/code_review_page.py
import os
import shutil
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QListWidget, QListWidgetItem, QLabel, QGroupBox,
                               QMessageBox)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QBrush
from app.core.project_context import ProjectContext
from app.core.config import ConfigManager
from app.core.app_constants import RESTART_EXIT_CODE
from app.core.self_update import SelfUpdateManager
from app.ui.components.preview_dialog import CodePreviewDialog
from app.ui.theme import Theme, theme_manager
from app.ui.pages.console_page import UIHelper
from app.core.logging import get_logger

logger = get_logger("app.ui.code_review_page", side="ui")

RESTART_CODE = RESTART_EXIT_CODE

class CodeReviewPage(QWidget):
    request_scan = Signal()

    def _is_remote(self):
        return hasattr(self.worker, '_request_send')

    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.config = ConfigManager.load()
        self.update_mgr = SelfUpdateManager()

        self.current_preview_dlg = None

        self.init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

        # 延迟绑定信号
        QTimer.singleShot(1000, self.bind_worker_signals)

    def bind_worker_signals(self):
        if not self.worker:
            return

        # 绑定远程预览信号
        if hasattr(self.worker, 'file_preview_signal'):
            try:
                self.worker.file_preview_signal.disconnect(self.on_remote_preview_received)
            except Exception as e:
                logger.warning(e)
            self.worker.file_preview_signal.connect(self.on_remote_preview_received)

        # 绑定扫描结果信号
        if hasattr(self.worker, 'update_list_signal'):
            try:
                self.worker.update_list_signal.disconnect(self.on_remote_list_received)
            except Exception as e:
                logger.warning(e)
            self.worker.update_list_signal.connect(self.on_remote_list_received)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header_layout = QHBoxLayout()
        self.title_lbl = QLabel("🧬 代码审查 (Code Review)")
        self.title_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(self.title_lbl)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        self.dev_group = QGroupBox("🚀 待应用变更 (Staging Area)")
        dev_layout = QVBoxLayout(self.dev_group)
        dev_layout.setContentsMargins(10, 20, 10, 10)

        toolbar = QHBoxLayout()
        self.scan_btn = QPushButton("🔍 扫描变更")
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.clicked.connect(self.scan_updates)

        self.clear_cache_btn = QPushButton("🗑️ 清空暂存")
        self.clear_cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_cache_btn.clicked.connect(self.clear_staging_area)

        self.apply_btn = QPushButton("✅ 应用选中变更")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_updates)

        toolbar.addWidget(self.scan_btn)
        toolbar.addWidget(self.clear_cache_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.apply_btn)
        dev_layout.addLayout(toolbar)

        self.update_list = QListWidget()
        self.update_list.setAlternatingRowColors(True)
        self.update_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.update_list.customContextMenuRequested.connect(self.show_list_context_menu)
        self.update_list.itemDoubleClicked.connect(self.preview_update_file)
        dev_layout.addWidget(self.update_list)

        layout.addWidget(self.dev_group)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY};")
        self.title_lbl.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-weight: bold;")

        group_style = Theme.group_box()
        self.dev_group.setStyleSheet(group_style)

        self.update_list.setStyleSheet(Theme.table_widget())
        self.scan_btn.setStyleSheet(Theme.button_primary())
        self.clear_cache_btn.setStyleSheet(Theme.button_danger())
        self.apply_btn.setStyleSheet(Theme.button_success_small())

    def scan_updates(self):
        is_remote = self._is_remote()
        if is_remote:
            self.update_list.clear()
            self.update_list.addItem(QListWidgetItem("⏳ 正在请求云端扫描..."))
            self.scan_btn.setEnabled(False)
            self.worker.do_server_scan()
        else:
            self.update_list.clear()
            candidates = self.update_mgr.scan()
            self._fill_list(candidates)

    def on_remote_list_received(self, candidates):
        self.scan_btn.setEnabled(True)
        self._fill_list(candidates)

    def _fill_list(self, candidates):
        self.update_list.clear()
        has_updates = False
        for c in candidates:
            status = c.get('status', 'unknown')
            path = c.get('rel_path', '???')
            if status == "same":
                continue

            has_updates = True
            item = QListWidgetItem(f"[{status.upper()}] {path}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            if status == "new":
                item.setForeground(QBrush(QColor("#34D399")))
            elif status == "overwrite":
                item.setForeground(QBrush(QColor("#FBBF24")))
            self.update_list.addItem(item)

        self._update_apply_btn_state()
        if not has_updates:
            self.update_list.addItem(QListWidgetItem("✅ 暂无待处理变更"))

    def _update_apply_btn_state(self):
        count = self.update_list.count()
        first_item = self.update_list.item(0)
        has_items = count > 0 and first_item and first_item.data(Qt.ItemDataRole.UserRole) is not None
        self.apply_btn.setEnabled(has_items)
        self.apply_btn.setText(f"✅ 应用 {count} 个更新" if has_items else "无可用更新")

    def preview_update_file(self, item):
        rel_path = item.data(Qt.ItemDataRole.UserRole)
        if not rel_path:
            return

        self.current_preview_dlg = CodePreviewDialog(rel_path, self)
        self.current_preview_dlg.set_loading(True)

        is_remote = self._is_remote()
        if is_remote:
            if hasattr(self.worker, 'get_staging_file_content'):
                self.worker.get_staging_file_content(rel_path)
            else:
                self.current_preview_dlg.update_content("❌ Worker 版本过低")
        else:
            self._load_local_preview(rel_path)

        self.current_preview_dlg.exec()

    def _load_local_preview(self, rel_path):
        staging_dir = self.config.get("export_code_path", "export/code")
        staging_path = os.path.join(staging_dir, rel_path)
        project_root = ProjectContext.get().get_project_root()
        current_path = os.path.join(project_root, rel_path)

        new_content = ""
        old_content = None

        if os.path.exists(staging_path):
            with open(staging_path, 'r', encoding='utf-8') as f:
                new_content = f.read()
        if os.path.exists(current_path):
            with open(current_path, 'r', encoding='utf-8') as f:
                old_content = f.read()

        self.current_preview_dlg.set_loading(False)
        self.current_preview_dlg.update_content(new_content, old_content)

    def on_remote_preview_received(self, data):
        if not self.current_preview_dlg or not self.current_preview_dlg.isVisible():
            return
        self.current_preview_dlg.set_loading(False)
        self.current_preview_dlg.update_content(data.get("content"), data.get("old_content"))

    def apply_updates(self):
        paths = [
            self.update_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.update_list.count())
            if self.update_list.item(i).data(Qt.ItemDataRole.UserRole)
        ]
        if not paths:
            return

        is_remote = self._is_remote()
        target_str = "[服务端]" if is_remote else "[本地]"

        if QMessageBox.question(
            self,
            "确认部署",
            f"在 {target_str} 应用 {len(paths)} 个更新？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            if is_remote:
                self.worker.do_server_apply(paths)
                UIHelper.info(self, "指令已发送", "已通知服务端执行更新。")
                self.update_list.clear()
            else:
                self.update_mgr.apply(rel_paths=paths)
                UIHelper.info(self, "更新完成", "文件已更新，无需重启。")
                self.scan_updates()

    def clear_staging_area(self):
        is_remote = self._is_remote()
        if not UIHelper.confirm(self, "确认清空", "确定要清空暂存区吗？此操作不可逆！"):
            return

        if is_remote:
            if hasattr(self.worker, 'do_server_clear_cache'):
                self.worker.do_server_clear_cache()
                self.update_list.clear()
            else:
                UIHelper.warning(self, "错误", "服务端不支持此操作")
        else:
            staging_dir = self.config.get("export_code_path", "export/code")
            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir)
                os.makedirs(staging_dir)
            self.update_list.clear()
            UIHelper.info(self, "完成", "本地暂存区已清空")

    def show_list_context_menu(self, pos):
        item = self.update_list.itemAt(pos)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        rel_path = item.data(Qt.ItemDataRole.UserRole)

        p = theme_manager.get_palette()
        menu = QMessageBox()  # placeholder to keep imports stable if context menu path changes
        del menu
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.setStyleSheet(
            f"QMenu {{ background-color: {p.BG_SECONDARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; }} "
            f"QMenu::item:selected {{ background-color: {p.ACCENT_PRIMARY}; }}"
        )

        action_discard = menu.addAction("🗑️ 仅本次跳过 (删除缓存)")
        action = menu.exec(self.update_list.mapToGlobal(pos))

        if action == action_discard:
            try:
                full_path = os.path.join(self.config.get("export_code_path", "export/code"), rel_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                self.update_list.takeItem(self.update_list.row(item))
                self._update_apply_btn_state()
            except Exception as e:
                QMessageBox.critical(self, "错误", str(e))
