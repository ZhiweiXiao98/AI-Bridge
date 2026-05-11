# filename: app/ui/components/panels/git_control_panel.py
"""
Git 工作台面板（紧凑版）
"""
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QListWidget, QListWidgetItem, QTabWidget, QAbstractItemView,
    QMenu, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor
from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager


class GitControlPanel(DockablePanel):
    """Git 工作台面板（紧凑版）"""

    request_git_backup = Signal(str)
    request_git_refresh = Signal()
    request_git_push_only = Signal()
    request_git_diff_dialog = Signal(str, str)
    request_git_open_config = Signal()
    request_add_to_gitignore = Signal(str)
    request_remove_tracking_and_ignore = Signal(str)
    request_gitignore_save = Signal(str)
    request_gitignore_load = Signal()

    def __init__(self):
        super().__init__("git_control", "Git 工作台", "☁️")
        self.git_busy = False
        self._workbench_payload = None
        self.init_content()
        self._update_repo_summary({})

    def create_content(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.lbl_branch = QLabel("🌿 --")
        self.lbl_branch.setToolTip("当前分支")
        self.lbl_ahead_behind = QLabel("↑0 ↓0")
        self.lbl_ahead_behind.setToolTip("与上游分支的 ahead / behind")
        self.lbl_changed = QLabel("0 changes")
        self.lbl_changed.setToolTip("当前未提交变更数量")
        self.lbl_last_time = QLabel("🕒 --:--")
        self.lbl_last_time.setToolTip("最近一次 Git 操作时间")

        top_row.addWidget(self.lbl_branch)
        top_row.addWidget(self.lbl_ahead_behind)
        top_row.addWidget(self.lbl_changed)
        top_row.addStretch()
        top_row.addWidget(self.lbl_last_time)
        layout.addLayout(top_row)

        self.lbl_repo = QLabel("📁 Repo")
        self.lbl_repo.setToolTip("仓库路径")
        layout.addWidget(self.lbl_repo)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(4)

        self.commit_input = QLineEdit()
        self.commit_input.setPlaceholderText("Commit message...")
        self.commit_input.setFixedHeight(28)
        self.commit_input.returnPressed.connect(self.on_backup_clicked)

        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setFixedSize(28, 28)
        self.btn_refresh.setToolTip("刷新 Git 工作台")
        self.btn_refresh.clicked.connect(self.request_git_refresh.emit)

        self.btn_config = QPushButton("⚙")
        self.btn_config.setFixedSize(28, 28)
        self.btn_config.setToolTip("打开 Git 配置与诊断")
        self.btn_config.clicked.connect(self.request_git_open_config.emit)

        self.btn_gitignore = QPushButton("📝")
        self.btn_gitignore.setFixedSize(28, 28)
        self.btn_gitignore.setToolTip("编辑 .gitignore")
        self.btn_gitignore.clicked.connect(self.on_gitignore_btn_clicked)

        self.btn_push_only = QPushButton("⇪")
        self.btn_push_only.setFixedSize(28, 28)
        self.btn_push_only.setToolTip("仅执行 git push")
        self.btn_push_only.clicked.connect(self.on_push_only_clicked)

        self.btn_backup = QPushButton("✔")
        self.btn_backup.setFixedSize(28, 28)
        self.btn_backup.setToolTip("提交并推送当前修改")
        self.btn_backup.clicked.connect(self.on_backup_clicked)

        action_row.addWidget(self.commit_input, 1)
        action_row.addWidget(self.btn_refresh)
        action_row.addWidget(self.btn_config)
        action_row.addWidget(self.btn_gitignore)
        action_row.addWidget(self.btn_push_only)
        action_row.addWidget(self.btn_backup)
        layout.addLayout(action_row)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setUsesScrollButtons(False)

        self.file_tree = QTreeWidget()
        self.file_tree.setColumnCount(2)
        self.file_tree.setHeaderLabels(["文件", "变更"])
        self.file_tree.setRootIsDecorated(False)
        self.file_tree.setAlternatingRowColors(False)
        self.file_tree.setUniformRowHeights(True)
        self.file_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_tree.itemDoubleClicked.connect(self.on_file_double_clicked)
        self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_tree.header().setStretchLastSection(False)
        self.file_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.file_tree, "变更")

        self.commit_list = QListWidget()
        self.commit_list.setAlternatingRowColors(False)
        self.tabs.addTab(self.commit_list, "历史")

        gitignore_widget = QWidget()
        gitignore_layout = QVBoxLayout(gitignore_widget)
        gitignore_layout.setContentsMargins(0, 0, 0, 0)
        gitignore_layout.setSpacing(4)
        self.gitignore_editor = QPlainTextEdit()
        self.gitignore_editor.setPlaceholderText("加载 .gitignore 内容...")
        self.gitignore_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        gitignore_layout.addWidget(self.gitignore_editor, 1)
        gitignore_btn_row = QHBoxLayout()
        gitignore_btn_row.setSpacing(4)
        self.btn_gitignore_refresh = QPushButton("⟳ 刷新")
        self.btn_gitignore_refresh.setFixedHeight(24)
        self.btn_gitignore_refresh.clicked.connect(self.on_gitignore_refresh_clicked)
        self.btn_gitignore_save = QPushButton("✔ 保存")
        self.btn_gitignore_save.setFixedHeight(24)
        self.btn_gitignore_save.clicked.connect(self.on_gitignore_save_clicked)
        gitignore_btn_row.addStretch()
        gitignore_btn_row.addWidget(self.btn_gitignore_refresh)
        gitignore_btn_row.addWidget(self.btn_gitignore_save)
        gitignore_layout.addLayout(gitignore_btn_row)
        self.tabs.addTab(gitignore_widget, ".gitignore")

        layout.addWidget(self.tabs, 1)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Git / Knowledge 进度日志...")
        self.log_output.setFixedHeight(72)
        layout.addWidget(self.log_output)

        theme_manager.theme_changed.connect(self.apply_content_theme)
        self.apply_content_theme()
        return widget

    def apply_content_theme(self):
        p = theme_manager.get_palette()

        self.commit_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 0 6px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {p.ACCENT_PRIMARY};
            }}
            QLineEdit:disabled {{
                color: #71717a;
            }}
        """)

        icon_btn_style = f"""
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                font-size: 13px;
                font-weight: 600;
                padding: 0;
            }}
            QPushButton:hover {{
                border: 1px solid {p.ACCENT_PRIMARY};
                color: {p.ACCENT_PRIMARY};
            }}
            QPushButton:disabled {{
                background-color: #3f3f46;
                color: #a1a1aa;
            }}
        """
        self.btn_refresh.setStyleSheet(icon_btn_style)
        self.btn_config.setStyleSheet(icon_btn_style)
        self.btn_gitignore.setStyleSheet(icon_btn_style)
        self.btn_push_only.setStyleSheet(icon_btn_style)
        self.btn_backup.setStyleSheet(icon_btn_style)

        compact_editor_style = f"""
            QPlainTextEdit {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 4px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
            }}
        """
        self.log_output.setStyleSheet(compact_editor_style)
        self.gitignore_editor.setStyleSheet(compact_editor_style)

        gitignore_btn_style = f"""
            QPushButton {{
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border: 1px solid {p.ACCENT_PRIMARY};
                color: {p.ACCENT_PRIMARY};
            }}
        """
        self.btn_gitignore_refresh.setStyleSheet(gitignore_btn_style)
        self.btn_gitignore_save.setStyleSheet(gitignore_btn_style)

        list_style = f"""
            QTreeWidget, QListWidget, QTabWidget::pane {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
            }}
            QTreeWidget::item, QListWidget::item {{
                padding: 1px 4px;
                margin: 0;
            }}
            QTreeWidget::item:selected, QListWidget::item:selected {{
                background-color: {p.ACCENT_PRIMARY};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                border: none;
                border-bottom: 1px solid {p.BORDER};
                padding: 3px 4px;
                margin: 0;
            }}
            QTabBar::tab {{
                background: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                padding: 4px 8px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 46px;
            }}
            QTabBar::tab:selected {{
                background: {p.BG_TERTIARY};
                color: {p.ACCENT_PRIMARY};
            }}
        """
        self.file_tree.setStyleSheet(list_style)
        self.commit_list.setStyleSheet(list_style)
        self.tabs.setStyleSheet(list_style)

        label_style = f"color: {p.TEXT_PRIMARY}; font-size: 11px;"
        subtle_style = f"color: {p.TEXT_SECONDARY}; font-size: 11px;"
        self.lbl_branch.setStyleSheet(label_style)
        self.lbl_ahead_behind.setStyleSheet(label_style)
        self.lbl_changed.setStyleSheet(label_style)
        self.lbl_last_time.setStyleSheet(subtle_style)
        self.lbl_repo.setStyleSheet(subtle_style)

    def append_log(self, text):
        if not isinstance(text, str):
            return
        self.log_output.appendPlainText(text)
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_busy(self, busy: bool):
        self.git_busy = busy
        self.btn_backup.setEnabled(not busy)
        self.btn_push_only.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.btn_config.setEnabled(not busy)
        self.btn_gitignore.setEnabled(not busy)

    def on_worker_status(self, text):
        if not isinstance(text, str):
            return
        if "[Git]" in text or "[Knowledge]" in text:
            self.append_log(text)
        if (
            "✅ [Git] 备份成功" in text
            or "❌ [Git] 备份失败" in text
            or "✅ [Git] 推送成功" in text
            or "❌ [Git] 推送失败" in text
        ):
            self.set_busy(False)
            self.lbl_last_time.setText(f"🕒 {datetime.datetime.now().strftime('%H:%M')}")

    def on_backup_clicked(self):
        if self.git_busy:
            self.append_log("⏳ 当前已有 Git 任务在进行中，请稍候...")
            return
        msg = self.commit_input.text().strip()
        if not msg:
            self.append_log("⚠️ 请先输入 Commit Message")
            return
        self.set_busy(True)
        self.request_git_backup.emit(msg)
        self.commit_input.clear()
        self.append_log(f"🚀 已发起 Git 备份: {msg}")

    def on_push_only_clicked(self):
        if self.git_busy:
            self.append_log("⏳ 当前已有 Git 任务在进行中，请稍候...")
            return
        self.set_busy(True)
        self.append_log("🚀 已发起 Git 仅推送")
        self.request_git_push_only.emit()

    def set_workbench_data(self, payload):
        self._workbench_payload = payload or {}
        summary = self._workbench_payload.get('summary', {})
        changes = self._workbench_payload.get('changes', [])
        history = self._workbench_payload.get('history', [])
        self._update_repo_summary(summary)
        self._update_changed_files(changes)
        self._update_commits(history)

    def on_file_double_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        path = data.get('path')
        kind = data.get('kind')
        if path:
            self.request_git_diff_dialog.emit(path, kind or '')

    def _update_repo_summary(self, payload):
        branch = payload.get('branch', '--')
        ahead = payload.get('ahead', 0)
        behind = payload.get('behind', 0)
        change_count = payload.get('change_count', 0)
        status_text = payload.get('status_text', '')
        repo_path = payload.get('repo_path', '.')
        self.lbl_branch.setText(f"🌿 {branch}")
        self.lbl_ahead_behind.setText(f"↑{ahead} ↓{behind}")
        self.lbl_changed.setText(f"{change_count} changes")
        self.lbl_repo.setText("📁 Repo")
        tooltip = repo_path
        if status_text:
            tooltip += f"\n{status_text}"
        self.lbl_repo.setToolTip(tooltip)

    def _update_changed_files(self, changes):
        self.file_tree.clear()
        kind_label_map = {
            'modified': '修改',
            'added': '新增',
            'deleted': '删除',
            'renamed': '重命名',
            'untracked': '未跟踪',
            'unknown': '未知',
        }
        color_map = {
            'modified': '#EAB308',
            'added': '#22C55E',
            'deleted': '#EF4444',
            'renamed': '#A855F7',
            'untracked': '#06B6D4',
            'unknown': '#A1A1AA',
        }
        for item in changes or []:
            path = item.get('path', '')
            filename = path.split('/')[-1] if path else ''
            kind = item.get('kind', '')
            label = kind_label_map.get(kind, kind)
            row = QTreeWidgetItem([filename or path, label])
            row.setData(0, Qt.ItemDataRole.UserRole, item)
            row.setToolTip(0, path)
            row.setToolTip(1, f"类型: {label}")
            row.setForeground(1, QColor(color_map.get(kind, '#A1A1AA')))
            self.file_tree.addTopLevelItem(row)

    def _update_commits(self, commits):
        self.commit_list.clear()
        for item in commits or []:
            sha = item.get('short_hash', '--------')
            subject = item.get('message', '')
            author = item.get('author', '')
            date_text = item.get('date', '')
            text = f"{sha}  {subject}"
            row = QListWidgetItem(text)
            tooltip = '\n'.join([x for x in [item.get('hash', ''), author, date_text] if x])
            if tooltip:
                row.setToolTip(tooltip)
            self.commit_list.addItem(row)

    def show_file_context_menu(self, pos: QPoint):
        item = self.file_tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        path = data.get('path', '')
        kind = data.get('kind', '')
        if not path:
            return

        menu = QMenu(self)
        p = theme_manager.get_palette()
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 4px 0;
            }}
            QMenu::item {{
                padding: 6px 16px;
            }}
            QMenu::item:selected {{
                background-color: {p.ACCENT_PRIMARY};
                color: white;
            }}
        """)

        act_diff = menu.addAction("📄 查看 Diff")
        act_diff.triggered.connect(lambda: self.request_git_diff_dialog.emit(path, kind or ''))
        menu.addSeparator()

        act_ignore_file = menu.addAction("🚫 忽略此文件")
        act_ignore_file.triggered.connect(lambda: self.request_add_to_gitignore.emit(path))

        dir_path = '/'.join(path.split('/')[:-1]) + '/' if '/' in path else None
        if dir_path:
            act_ignore_dir = menu.addAction(f"🚫 忽略此文件夹 ({dir_path})")
            act_ignore_dir.triggered.connect(lambda: self.request_add_to_gitignore.emit(dir_path))

        if kind != 'untracked':
            menu.addSeparator()
            act_untrack = menu.addAction("⛔ 移除跟踪并忽略")
            act_untrack.triggered.connect(lambda: self._confirm_remove_tracking(path))

        menu.exec(self.file_tree.viewport().mapToGlobal(pos))

    def _confirm_remove_tracking(self, path):
        reply = QMessageBox.question(
            self, "确认移除跟踪",
            f"将从 Git 跟踪中移除并忽略:\n\n{path}\n\n"
            "此操作会执行 git rm --cached（不删除本地文件），\n"
            "并将路径加入 .gitignore。\n\n"
            "确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.request_remove_tracking_and_ignore.emit(path)

    def on_gitignore_btn_clicked(self):
        self.tabs.setCurrentIndex(2)
        self.request_gitignore_load.emit()

    def on_gitignore_refresh_clicked(self):
        self.request_gitignore_load.emit()

    def on_gitignore_save_clicked(self):
        content = self.gitignore_editor.toPlainText()
        self.request_gitignore_save.emit(content)

    def set_gitignore_content(self, content):
        self.gitignore_editor.setPlainText(content or "")
