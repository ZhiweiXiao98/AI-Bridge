from PySide6.QtWidgets import QMenu, QFileDialog, QMessageBox
from PySide6.QtGui import QAction
from PySide6.QtCore import QObject

from app.core.project_context import ProjectContext
from app.core.app_constants import APP_ROOT
from app.core.logging import get_logger

logger = get_logger("app.ui.components.panels.project_menu", side="ui")


class ProjectMenu(QObject):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._ctx = ProjectContext.get()
        self._menu = None
        self._recent_menu = None
        self._build_menu()

    def get_menu(self) -> QMenu:
        return self._menu

    def _build_menu(self):
        self._menu = QMenu("📁 项目", self._main_window)

        open_action = QAction("打开项目...", self._main_window)
        open_action.triggered.connect(self._on_open_project)
        self._menu.addAction(open_action)

        self._recent_menu = QMenu("最近项目", self._main_window)
        self._menu.addMenu(self._recent_menu)
        self._refresh_recent_menu()

        self._menu.addSeparator()

        home_action = QAction("返回软件目录", self._main_window)
        home_action.triggered.connect(self._on_return_home)
        self._menu.addAction(home_action)

        self._menu.addSeparator()

        self._current_action = QAction("", self._main_window)
        self._current_action.setEnabled(False)
        self._menu.addAction(self._current_action)
        self._update_current_label()

        self._ctx.project_switched.connect(self._on_project_switched)

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        recent = self._ctx.get_recent_projects()
        if not recent:
            empty_action = QAction("（无）", self._main_window)
            empty_action.setEnabled(False)
            self._recent_menu.addAction(empty_action)
            return
        for item in recent:
            action = QAction(f"{item['name']}  ({item['path']})", self._main_window)
            action.setData(item['path'])
            action.triggered.connect(self._on_recent_project_clicked)
            self._recent_menu.addAction(action)

    def _on_open_project(self):
        current = self._ctx.get_project_root()
        path = QFileDialog.getExistingDirectory(
            self._main_window, "选择项目目录", current
        )
        if not path:
            return
        if not self._validate_path(path):
            return
        self._do_switch(path)

    def _on_recent_project_clicked(self):
        action = self._main_window.sender()
        if not action:
            return
        path = action.data()
        if path and self._validate_path(path):
            self._do_switch(path)

    def _on_return_home(self):
        self._do_switch(APP_ROOT)

    def _do_switch(self, path: str):
        logger.info("[项目菜单] 请求切换到: %s", path)
        ok = self._ctx.switch_to(path)
        if ok:
            logger.info("[项目菜单] 切换成功: %s", path)
        else:
            logger.warning("[项目菜单] 切换失败: %s", path)

    def _validate_path(self, path: str) -> bool:
        import os
        if not os.path.isdir(path):
            QMessageBox.warning(self._main_window, "路径无效", f"目录不存在:\n{path}")
            return False
        return True

    def _on_project_switched(self, new_root: str, new_db_path: str):
        self._update_current_label()
        self._refresh_recent_menu()

    def _update_current_label(self):
        name = self._ctx.project_name
        root = self._ctx.get_project_root()
        self._current_action.setText(f"当前: {name}")
        self._current_action.setToolTip(root)
