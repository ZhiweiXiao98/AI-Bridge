# filename: app/ui/main_window.py
import sys
import os
import shutil
import threading
import logging

from app.core.logging import init_logging, get_logger, register_panel_handler, unregister_panel_handler
from app.ui.logging import QtPanelLogHandler, LogPanelBridge

logger = get_logger("app.ui.main_window")
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QFrame, QMenuBar, QMenu, QStackedWidget, QToolButton, QApplication, QDockWidget, QMessageBox, QSplitter, QLabel, QInputDialog, QTabWidget, QTabBar)
from PySide6.QtCore import Qt, QSize, QTimer, QSettings, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import QIcon, QAction

from app.ui.pages.chat import ChatPage
from app.ui.pages.console_page import ConsolePage
from app.ui.settings_page import SettingsPage
from app.ui.modeling_page import ModelingPage
from app.ui.pages.context_page import ContextPage
from app.ui.theme import theme_manager
from app.ui.components.preview_dialog import CodePreviewDialog
from app.ui.components.overlay import OverlayWidget
from app.core.config import ConfigManager
from app.core.app_constants import UPDATE_EXIT_CODE, RESTART_EXIT_CODE, UI_COLORS, UI_SIZES, APP_ROOT
from app.core.utils.text_utils import is_test_log

# 🆕 面板管理系统导入
from app.ui.managers.panel_manager import PanelManager
from app.ui.managers.workspace_manager import WorkspaceManager
from app.ui.components.panels import (
    TaskSchedulePanel,
    CodeReviewPanel,
    GitControlPanel,
    RuntimeLogPanel,
    SandboxMonitorPanel,
    ContextWorkspacePanel
)
from app.ui.components.panels.context_workspace_panel_logic import ContextWorkspacePanelLogic
from app.ui.components.panels.git_control_panel_logic import GitControlPanelLogic
# SkillsManager 由插件使用

# 🔌 插件系统导入
from app.ui.plugins.panel_plugin_loader import PanelPluginLoader
from app.ui.panels.plugin_manager_panel import PluginManagerPanel

UPDATE_CODE = UPDATE_EXIT_CODE

class MainWindow(QMainWindow):
    git_log_signal = Signal(str)
    git_busy_signal = Signal(bool)

    def _is_remote(self):
        return hasattr(self.worker, '_request_send')


    def _is_test_log(self, text):
        return is_test_log(text)

    def _append_main_log_filtered(self, text):
        if self._is_test_log(text):
            return
        if hasattr(self, 'runtime_log_panel'):
            self.runtime_log_panel.append_log(text)
        elif hasattr(self, 'log_panel'):
            self.log_panel.append_log(text)

    def __init__(self, worker_core=None, user_profile=None, **kwargs):
        init_logging(side="ui")
        self._docker_manager = None
        super().__init__(**kwargs)
        if worker_core:
            for sig in ['status_signal', 'restart_needed_signal', 'snapshot_ready_signal', 'system_prompt_signal', 'file_preview_signal']:
                has_it = hasattr(worker_core, sig)
                val = getattr(worker_core, sig, None) if has_it else None
        self.is_loading = True
        self.is_admin = "--admin" in sys.argv
        self.worker = worker_core
        self.user_profile = user_profile or {"role": "developer", "username": "Admin"}
        
        ini_path = os.path.join(APP_ROOT, "layout.ini")
        self.settings = QSettings(ini_path, QSettings.Format.IniFormat)
        
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)
        self.save_timer.timeout.connect(self.save_layout)
        
        self.is_startup_protected = True

        role_name = self.user_profile.get("role", "user").upper()
        self._update_window_title()
        self.resize(*UI_SIZES["default_window"])
        
        from app.core.project_context import ProjectContext
        ProjectContext.get().project_switched.connect(lambda r, d: self._update_window_title())
        
        theme_manager.theme_changed.connect(self.apply_theme)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.root_layout = QVBoxLayout(central_widget)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.splitterMoved.connect(lambda: self.save_timer.start())
        self.main_splitter.setHandleWidth(1)
        self.root_layout.addWidget(self.main_splitter)

        # 1. Left Sidebar
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(UI_SIZES["sidebar_width"])
        self.sidebar_layout = QVBoxLayout(self.sidebar_frame)
        self.sidebar_layout.setContentsMargins(5, 20, 5, 20)
        self.sidebar_layout.setSpacing(15)
        self.sidebar_btns = []
        self.init_sidebar()
        self.main_splitter.addWidget(self.sidebar_frame)

        # 2. Content Stack
        self.content_stack = QStackedWidget()
        self.init_pages()
        self.main_splitter.addWidget(self.content_stack)

        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setCollapsible(0, False)

        self.overlay = OverlayWidget(self)
        if self.worker and hasattr(self.worker, 'status_signal') and self.worker.status_signal:
            self.worker.status_signal.connect(self.handle_status_update)
        else:
            print(f"⚠️ status_signal 不可用: worker={self.worker}, hasattr={hasattr(self.worker, 'status_signal') if self.worker else False}")

        if self.worker and hasattr(self.worker, 'restart_needed_signal') and self.worker.restart_needed_signal:
            self.worker.restart_needed_signal.connect(self.handle_restart_request)
        else:
            print(f"⚠️ restart_needed_signal 不可用")
        if self.worker and hasattr(self.worker, 'snapshot_ready_signal') and self.worker.snapshot_ready_signal:
            self.worker.snapshot_ready_signal.connect(self.copy_snapshot_to_clipboard)
        else:
            print(f"⚠️ snapshot_ready_signal 不可用")

        # Skills 面板信号

        # system_prompt_signal 现在由 SkillsPanel 插件处理
        if self.worker and hasattr(self.worker, 'file_preview_signal') and self.worker.file_preview_signal:
            self.worker.file_preview_signal.connect(self.on_remote_preview_received)
        else:
            print(f"⚠️ file_preview_signal 不可用")

        if self.worker and hasattr(self.worker, 'queue_monitor_signal') and self.worker.queue_monitor_signal:
            self.worker.queue_monitor_signal.connect(self.handle_queue_update)
        else:
            print(f"⚠️ queue_monitor_signal 不可用")

        if hasattr(self.worker, 'isRunning') and not self.worker.isRunning():
            self.worker.start()
        
        # Skills 管理器现在由插件处理

        
        # 🆕 初始化面板管理系统（必须在菜单之前，因为菜单需要 plugin_loader）
        try:
            self.init_panel_system()
        except Exception as e:
            print(f"❌ 面板系统初始化失败: {e}")
        
        # 🆕 初始化菜单栏（现在可以安全使用 plugin_loader）
        self.init_menu_bar()
        
        self.git_log_signal.connect(self._append_git_panel_log)
        self.git_busy_signal.connect(self._set_git_panel_busy)
        if self.worker and hasattr(self.worker, 'git_detail_signal') and self.worker.git_detail_signal:
            self.worker.git_detail_signal.connect(self._append_git_panel_log)
        if self.worker and hasattr(self.worker, 'git_workbench_signal') and self.worker.git_workbench_signal:
            self.worker.git_workbench_signal.connect(self._on_git_workbench_received)
        if self.worker and hasattr(self.worker, 'git_diff_preview_signal') and self.worker.git_diff_preview_signal:
            self.worker.git_diff_preview_signal.connect(self._on_git_diff_preview_received)
        self._pending_git_diff_dialog_path = None
        self.git_config_logic = GitControlPanelLogic(
            panel=getattr(self, 'git_control_panel', None),
            worker=self.worker,
            runtime_log_panel=getattr(self, 'runtime_log_panel', None),
            refresh_workbench_callback=self.handle_git_refresh_request,
            parent=self,
        )
        self.git_config_logic.bind()

        self.apply_theme()
        QTimer.singleShot(0, self.delayed_restore)

    def handle_clear_cache_request(self):
        is_remote = self._is_remote()
        if is_remote:
            if hasattr(self.worker, 'do_server_clear_cache'):
                self.worker.do_server_clear_cache()
                if hasattr(self, 'runtime_log_panel'):
                    self.runtime_log_panel.append_log("🗑️ 已请求服务端清空缓存...")
                if hasattr(self, 'code_review_panel'):
                    self.code_review_panel.update_list.clear()
        else:
            try:
                cfg = ConfigManager.load()
                staging_dir = cfg.get("export_code_path", "export/code")
                if os.path.exists(staging_dir):
                    shutil.rmtree(staging_dir)
                    os.makedirs(staging_dir)
                    if hasattr(self, 'runtime_log_panel'):
                        self.runtime_log_panel.append_log("🗑️ 本地暂存区已清空")
                    if hasattr(self, 'code_review_panel'):
                        self.code_review_panel.update_list.clear()
            except Exception as e:
                if hasattr(self, 'runtime_log_panel'):
                    self.runtime_log_panel.append_log(f"❌ 本地清空失败: {e}")

    def handle_queue_update(self, data):
        my_id = getattr(self.worker, 'client_id', 'Host')
        active = (data or {}).get('active') or {}
        queue = list((data or {}).get('queue', []) or [])
        active_task_id = str(active.get('task_id', '') or '')
        active_tool_name = str(active.get('tool_name', '') or '')
        snapshot_key = (bool(active), active_task_id, active_tool_name, len(queue))
        previous_key = getattr(self, '_task_panel_log_snapshot_key', None)
        if snapshot_key != previous_key:
            self._task_panel_log_snapshot_key = snapshot_key
            if active:
                logger.info(
                    "[任务面板] 状态变化：出现运行中任务 | task_id=%s | tool_name=%s | queue=%d",
                    active_task_id,
                    active_tool_name,
                    len(queue),
                )
            elif queue:
                logger.info(
                    "[任务面板] 状态变化：当前无运行中任务，但存在排队任务 | queue=%d",
                    len(queue),
                )
            else:
                logger.info("[任务面板] 状态变化：进入空闲状态")
        else:
            logger.debug(
                "[任务面板] 轮询快照（无变化） | has_active=%s | task_id=%s | tool_name=%s | queue=%d",
                bool(active),
                active_task_id,
                active_tool_name,
                len(queue),
            )
        if hasattr(self, 'task_schedule_panel'):
            self.task_schedule_panel.update_task_queue(data, client_id=my_id)

    def handle_scan_request(self):
        is_remote = self._is_remote()
        if is_remote:
            self.worker.do_server_scan()
        else:
            if hasattr(self, 'log_panel'):
                self.log_panel.update_change_list(self.log_panel.update_mgr.scan())

    def handle_apply_request(self, paths):
        is_remote = self._is_remote()
        if is_remote:
            self.worker.do_server_apply(paths)
        else:
            if hasattr(self, 'runtime_log_panel'):
                self.runtime_log_panel.append_log(f"✅ 正在应用 {len(paths)} 个文件的更改...")


    def handle_git_request(self, msg):
        is_remote = self._is_remote()
        self.git_log_signal.emit(f"🚀 开始 Git 备份: {msg}")
        if is_remote:
            self.worker.do_server_backup(msg)
        else:
            threading.Thread(target=self._local_git_backup, args=(msg,), daemon=True).start()

    def handle_git_refresh_request(self):
        is_remote = self._is_remote()
        if is_remote:
            if hasattr(self.worker, 'get_git_workbench_state'):
                self.worker.get_git_workbench_state(30)
        else:
            try:
                from app.core.git_manager import GitManager
                gm = GitManager()
                payload = gm.get_workbench_state(limit=30)
                self._on_git_workbench_received(payload)
            except Exception as e:
                self.git_log_signal.emit(f"❌ [Git] 刷新失败: {e}")

    def handle_git_push_only_request(self):
        is_remote = self._is_remote()
        self.git_log_signal.emit("🚀 开始 Git 仅推送")
        if is_remote:
            if hasattr(self.worker, 'do_server_push_only'):
                self.worker.do_server_push_only()
            else:
                self.git_log_signal.emit("❌ [Git] 当前远程 Worker 版本不支持仅推送")
                self.git_busy_signal.emit(False)
        else:
            threading.Thread(target=self._local_git_push_only, daemon=True).start()

    def handle_git_diff_request(self, path, kind=""):
        is_remote = self._is_remote()
        if is_remote:
            if hasattr(self.worker, 'get_git_file_diff'):
                self.worker.get_git_file_diff(path, kind or None)
        else:
            try:
                from app.core.git_manager import GitManager
                gm = GitManager()
                payload = gm.get_file_diff_content(path, kind=kind or None)
                self._on_git_diff_preview_received(payload)
            except Exception as e:
                self.git_log_signal.emit(f"❌ [Git] Diff 读取失败: {e}")

    def handle_git_diff_dialog_request(self, path, kind=""):
        self._pending_git_diff_dialog_path = path
        self.current_preview_dlg = CodePreviewDialog(path, self)
        self.current_preview_dlg.set_loading(True)
        self.current_preview_dlg.show()
        self.current_preview_dlg.raise_()
        self.current_preview_dlg.activateWindow()
        self.handle_git_diff_request(path, kind)

    def handle_add_to_gitignore(self, pattern):
        try:
            from app.core.git_manager import GitManager
            gm = GitManager()
            ok, msg = gm.add_to_gitignore(pattern)
            self.git_log_signal.emit(f"{'✅' if ok else 'ℹ️'} [Git] {msg}")
            if ok:
                self.handle_git_refresh_request()
        except Exception as e:
            self.git_log_signal.emit(f"❌ [Git] 添加 .gitignore 规则失败: {e}")

    def handle_remove_tracking_and_ignore(self, path):
        try:
            from app.core.git_manager import GitManager
            gm = GitManager()
            ok, msg = gm.remove_from_tracking(path)
            self.git_log_signal.emit(f"{'✅' if ok else '❌'} [Git] {msg}")
            if ok:
                ok2, msg2 = gm.add_to_gitignore(path)
                self.git_log_signal.emit(f"{'✅' if ok2 else 'ℹ️'} [Git] {msg2}")
                self.handle_git_refresh_request()
        except Exception as e:
            self.git_log_signal.emit(f"❌ [Git] 移除跟踪并忽略失败: {e}")

    def handle_gitignore_save(self, content):
        try:
            from app.core.git_manager import GitManager
            gm = GitManager()
            ok, msg = gm.write_gitignore(content)
            self.git_log_signal.emit(f"{'✅' if ok else '❌'} [Git] {msg}")
            if ok:
                self.handle_git_refresh_request()
        except Exception as e:
            self.git_log_signal.emit(f"❌ [Git] 保存 .gitignore 失败: {e}")

    def handle_gitignore_load(self):
        try:
            from app.core.git_manager import GitManager
            gm = GitManager()
            content = gm.read_gitignore()
            if hasattr(self, 'git_control_panel'):
                self.git_control_panel.set_gitignore_content(content)
        except Exception as e:
            self.git_log_signal.emit(f"❌ [Git] 读取 .gitignore 失败: {e}")

    def _local_git_backup(self, msg):
        if not hasattr(self, 'git_control_panel'):
            print("⚠️ Git 控制面板未初始化")
            return

        try:
            self.git_log_signal.emit(">>> 开始本地备份...")
            from app.core.git_manager import GitManager
            gm = GitManager()
            ok, log, changed_files = gm.backup(msg)
            if log:
                for line in str(log).splitlines():
                    if line.strip():
                        self.git_log_signal.emit(line)

            if ok:
                self.git_log_signal.emit("✅ [Git] 备份成功")
                config = ConfigManager.load()
                if config.get("knowledge_reindex_after_git_push", True):
                    file_count = len(changed_files or [])
                    self.git_log_signal.emit(f"🧠 [Knowledge] 已加入后台增量更新队列，本次变更文件 {file_count} 个")
                    threading.Thread(
                        target=self._run_local_knowledge_reindex_after_git,
                        args=(changed_files or [],),
                        daemon=True,
                    ).start()
                else:
                    self.git_log_signal.emit("⏭️ [Knowledge] 已跳过：未开启 Git Push 后自动重建")
            else:
                self.git_log_signal.emit("❌ [Git] 备份失败")
        except Exception as e:
            self.git_log_signal.emit(f"❌ [Git] 本地备份异常: {e}")
            self.git_log_signal.emit("❌ [Git] 备份失败")
        finally:
            self.git_busy_signal.emit(False)
            self.handle_git_refresh_request()

    def _append_git_panel_log(self, text):
        if hasattr(self, 'git_control_panel'):
            self.git_control_panel.append_log(text)
        if isinstance(text, str) and (
            '✅ [Git] 备份成功' in text
            or '❌ [Git] 备份失败' in text
            or '✅ [Git] 推送成功' in text
            or '❌ [Git] 推送失败' in text
        ):
            self.git_busy_signal.emit(False)

    def _set_git_panel_busy(self, busy):
        if hasattr(self, 'git_control_panel'):
            self.git_control_panel.set_busy(busy)

    def _on_git_workbench_received(self, payload):
        if hasattr(self, 'git_control_panel'):
            self.git_control_panel.set_workbench_data(payload or {})

    def _on_git_diff_preview_received(self, payload):
        path = (payload or {}).get('path')
        old_text = (payload or {}).get('old_text')
        new_text = (payload or {}).get('new_text', '') or ''
        if (
            path
            and getattr(self, '_pending_git_diff_dialog_path', None) == path
            and hasattr(self, 'current_preview_dlg')
            and self.current_preview_dlg
            and self.current_preview_dlg.isVisible()
        ):
            self.current_preview_dlg.set_loading(False)
            self.current_preview_dlg.update_content(new_text, old_text)
            self._pending_git_diff_dialog_path = None


    def _run_local_knowledge_reindex_after_git(self, changed_files=None):
        normalized = [str(x).strip() for x in (changed_files or []) if str(x).strip()]
        file_count = len(normalized)
        use_incremental = file_count > 0
        if use_incremental:
            self.git_log_signal.emit(f"🧠 [Knowledge] 开始按本次变更增量更新知识库（{file_count} 个文件）...")
        else:
            self.git_log_signal.emit("🧠 [Knowledge] 未获得本次变更文件，开始按规则扫描项目并更新知识库...")
        try:
            if use_incremental:
                from app.core.knowledge.reindex_runner import reindex_changed_files
                summary = reindex_changed_files(normalized, progress_callback=self._on_local_knowledge_reindex_progress)
                success_text = (
                    f"✅ [Knowledge] 增量更新完成: ok={summary['ok']} fail={summary['fail']} skip={summary['skip']} deleted={summary['deleted']} keep={summary['keep']}"
                )
            else:
                from app.core.knowledge.reindex_runner import reindex_project
                summary = reindex_project(progress_callback=self._on_local_knowledge_reindex_progress)
                success_text = (
                    f"✅ [Knowledge] 规则扫描更新完成: ok={summary['ok']} fail={summary['fail']} skip={summary['skip']} deleted={summary['deleted']} keep={summary['keep']}"
                )
            if summary.get('enabled', True):
                self.git_log_signal.emit(success_text)
            else:
                self.git_log_signal.emit("⏭️ [Knowledge] 已跳过：规则过滤未启用")
        except Exception as e:
            self.git_log_signal.emit(f"⚠️ [Knowledge] 知识库构建失败: {e}")

    def _on_local_knowledge_reindex_progress(self, info):
        stage = info.get('stage')
        detail_text = None

        if stage == 'disabled':
            detail_text = '⏭️ [Knowledge] 已跳过：规则过滤未启用'
        elif stage == 'prepare':
            detail_text = '🧠 [Knowledge] 扫描准备开始...'
        elif stage == 'scan_start':
            detail_text = '🧠 [Knowledge] 开始扫描项目文件...'
        elif stage == 'scan_done':
            detail_text = f"🧠 [Knowledge] 扫描完成，共 {info.get('total', 0)} 个候选文件"
        elif stage == 'delete_start':
            detail_text = f"🧠 [Knowledge] 开始清理 stale 索引，共 {info.get('total', 0)} 项"
        elif stage == 'delete_done':
            detail_text = f"🧠 [Knowledge] stale 索引清理完成，已删除 {info.get('deleted', 0)} 项"
        elif stage == 'index_start':
            detail_text = f"🧠 [Knowledge] 开始写入索引，共 {info.get('total', 0)} 个文件"
        elif stage == 'index_progress':
            current = info.get('current', 0)
            total = info.get('total', 0)
            file = info.get('file', '')
            status = info.get('status', 'ok')
            detail_text = f"🧠 [Knowledge] 索引进度 {current}/{total} [{status}] {file}"

        if detail_text:
            self.git_log_signal.emit(detail_text)
    def _local_git_push_only(self):
        try:
            self.git_log_signal.emit(">>> 开始本地仅推送...")
            from app.core.git_manager import GitManager
            gm = GitManager()
            ok, log = gm.push_only()
            if log:
                for line in str(log).splitlines():
                    if line.strip():
                        self.git_log_signal.emit(line)
            if ok:
                self.git_log_signal.emit("✅ [Git] 推送成功")
                config = ConfigManager.load()
                if config.get("knowledge_reindex_after_git_push", True):
                    self.git_log_signal.emit("🧠 [Knowledge] 未获得本次变更文件，已回退为按规则扫描项目...")
                    threading.Thread(
                        target=self._run_local_knowledge_reindex_after_git,
                        args=(None,),
                        daemon=True,
                    ).start()
                else:
                    self.git_log_signal.emit("⏭️ [Knowledge] 已跳过：未开启 Git Push 后自动重建")
            else:
                self.git_log_signal.emit("❌ [Git] 推送失败")
        except Exception as e:
            self.git_log_signal.emit(f"❌ [Git] 本地推送异常: {e}")
            self.git_log_signal.emit("❌ [Git] 推送失败")
        finally:
            self.git_busy_signal.emit(False)
            self.handle_git_refresh_request()

    def show_preview_dialog(self, rel_path):
        self.current_preview_dlg = CodePreviewDialog(rel_path, self)
        self.current_preview_dlg.set_loading(True)
        is_remote = self._is_remote()
        if is_remote:
            if hasattr(self.worker, 'get_staging_file_content'):
                self.worker.get_staging_file_content(rel_path)
            else:
                self.current_preview_dlg.update_content("Worker version too old")
        self.current_preview_dlg.exec()

    def on_remote_preview_received(self, data):
        if hasattr(self, 'current_preview_dlg') and self.current_preview_dlg.isVisible():
            self.current_preview_dlg.set_loading(False)
            self.current_preview_dlg.update_content(data.get("content"), data.get("old_content"))

    def apply_theme(self):
        """应用主题样式"""
        self.setStyleSheet(theme_manager.get_stylesheet())

    def handle_status_update(self, text):
        if "🚑" in text:
            self.overlay.show_message("🚑", "正在前往侧车维修站...", "AI 正在接管控制权，请勿操作")
        elif "⏳" in text and "侧车" in text:
            self.overlay.show_message("🤖", "AI 正在诊断代码...", "可能需要 10-30 秒，请耐心等待")
        elif "🔙" in text:
            self.overlay.show_message("🔙", "修复完成，正在返航...", "即将回到主会话")
        elif "✅" in text and "会话已切换" in text:
            if self.overlay.isVisible() and "User" in text:
                pass
    def resizeEvent(self, event):
        if hasattr(self, 'overlay') and self.overlay.isVisible():
            self.overlay.resize(self.size())
        is_fixed = (self.minimumSize() == self.maximumSize() and self.minimumSize().width() > 0)
        if not is_fixed:
            self.save_timer.start()
        super().resizeEvent(event)

    def delayed_restore(self):
        try:
            w = self.settings.value("win_w", type=int)
            h = self.settings.value("win_h", type=int)
            x = self.settings.value("win_x", type=int)
            y = self.settings.value("win_y", type=int)
            if w and h and w > 100 and h > 100:
                self.setFixedSize(w, h)
                QTimer.singleShot(1000, self.unlock_window)
            if x is not None and y is not None:
                self.move(x, y)
            saved_sizes = self.settings.value("splitter_sizes")
            if saved_sizes:
                sizes = [int(s) for s in saved_sizes if s]
                if len(sizes) >= 3:
                    self.main_splitter.setSizes(sizes)
            chat_input_sizes = self.settings.value("chat_input_sizes")
            if chat_input_sizes and hasattr(self, 'chat_page'):
                sizes = [int(s) for s in chat_input_sizes if s]
                if len(sizes) >= 2 and sizes[0] > 0 and sizes[1] > 0:
                    self.chat_page.set_input_height_state(sizes)
        except Exception as e:
            logger.warning(e)

    def unlock_window(self):
        self.setMinimumSize(0, 0)
        
        # 设置停靠面板的标签页位置为顶部
        from PySide6.QtCore import Qt
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        
        # 启用标签拖拽（左右调整顺序）
        # 注意：这是 QMainWindow 的方法，用于 DockWidget 标签
        # Qt 会自动处理标签的左右拖拽，我们的事件过滤器处理上下拖拽
        
        # 安装事件过滤器，用于智能标签拖拽
        
        # 初始化标签栏：启用拖拽并安装事件过滤器
        QApplication.instance().processEvents()
        for tabbar in self.findChildren(QTabBar):
            tabbar.setMovable(True)
            tabbar.installEventFilter(self)
        
        # 设置停靠区域间距，创造卡片感
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks |
            QMainWindow.DockOption.AllowNestedDocks |
            QMainWindow.DockOption.AllowTabbedDocks
        )
        
        # 设置中央区域的 margin，为停靠面板创造间距
        if hasattr(self, 'centralWidget') and self.centralWidget():
            central_layout = self.centralWidget().layout()
            if central_layout:
                central_layout.setContentsMargins(4, 4, 4, 4)
                central_layout.setSpacing(4)
        self.setMaximumSize(16777215, 16777215)

    def moveEvent(self, event):
        self.save_timer.start()
        super().moveEvent(event)

    def init_sidebar(self):
        self.add_sidebar_btn("对话", "chat.png", 0, None, True)
        self.add_sidebar_btn("建模", "draw.png", 1, None)
        self.add_sidebar_btn("图像", "video.png", 2, None)
        self.add_sidebar_btn("游戏", "music.png", 3, None)
        self.add_sidebar_btn("Context", "layers.png", 6, None)
        self.sidebar_layout.addStretch()
        self.add_sidebar_btn("设置", "settings.png", 4, None)
        self.add_sidebar_btn("用户", "console.png", 5, None)

    def add_sidebar_btn(self, text, icon_name, page_idx, url=None, active=False):
        btn = QToolButton()
        btn.setText(text)
        btn.setObjectName("SidebarBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(True)
        btn.setChecked(active)
        btn.setFixedSize(*UI_SIZES["sidebar_button"])
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        icon_path = os.path.join(APP_ROOT, "assets", "icons", icon_name)
        if not os.path.exists(icon_path) and icon_name == "console.png":
            btn.setText("User")
        elif not os.path.exists(icon_path) and icon_name == "layers.png":
            btn.setText("Context")
        elif os.path.exists(icon_path):
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(*UI_SIZES["sidebar_icon"]))
        btn.clicked.connect(lambda: self.handle_sidebar_click(btn, page_idx, url))
        self.sidebar_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.sidebar_btns.append(btn)

    def init_pages(self):
        self.chat_page = ChatPage(self.worker)
        self.chat_page.splitter.splitterMoved.connect(lambda: self.save_timer.start())
        self.chat_page.v_splitter.splitterMoved.connect(lambda: self.save_timer.start())
        self.chat_page.request_focus.connect(lambda: self.switch_to_page(0))
        self.content_stack.addWidget(self.chat_page)
        self.modeling_page = ModelingPage()
        self.modeling_page.request_inject_prompt.connect(self.chat_page.activate_staging_area)
        self.modeling_page.request_run_script.connect(self.handle_remote_run)
        self.content_stack.addWidget(self.modeling_page)
        self.content_stack.addWidget(self.create_placeholder_page("ComfyUI / SD 模式", "等待接入..."))
        self.content_stack.addWidget(self.create_placeholder_page("UE5 / Blender 模式", "等待接入..."))
        self.settings_page = SettingsPage()
        self.settings_page.config_saved.connect(self.on_config_updated)
        if hasattr(self.worker, 'request_generate_snapshot'):
            self.settings_page.request_snapshot.connect(self.worker.request_generate_snapshot)
        self.content_stack.addWidget(self.settings_page)
        self.console_page = ConsolePage(self.worker)
        self.content_stack.addWidget(self.console_page)
        self.context_page = ContextPage(self.worker)
        self.context_page.request_push_pack.connect(self.handle_context_push)
        self.content_stack.addWidget(self.context_page)
        self.apply_permissions(self.user_profile.get("role", "user"))

    def handle_context_push(self, content, goal):
        for btn in self.sidebar_btns:
            if btn.text() == "对话":
                self.handle_sidebar_click(btn, 0, None)
                break
        header_text = f"Goal: {goal}\n\n" if goal else ""
        final_text = header_text + content
        QTimer.singleShot(200, lambda: self.chat_page.activate_staging_area(final_text))
        self.chat_page.log_status("📦 上下文快照已装载至暂存区")

    def on_config_updated(self, config):
        if hasattr(self.worker, 'update_config'):
            self.worker.update_config(config)
        theme_manager.reload_from_config()
        
    def apply_permissions(self, role):
        permissions = {
            "developer": [0, 1, 2, 3, 4, 5, 6],
            "vip": [0, 1, 2, 3, 4, 6],
            "user": [0],
            "guest": [0]
        }
        allowed_indices = permissions.get(role, [0])
        for i, btn in enumerate(self.sidebar_btns):
            if i in allowed_indices:
                btn.show()
            else:
                btn.hide()
        if self.content_stack.currentIndex() not in allowed_indices:
            self.switch_to_page(0)

    def handle_sidebar_click(self, clicked_btn, page_idx, url):
        for btn in self.sidebar_btns:
            btn.setChecked(False)
        clicked_btn.setChecked(True)
        self.switch_to_page(page_idx)
        if url:
            if hasattr(self.worker, 'navigate'):
                self.worker.navigate(url)
        if page_idx == 1 and hasattr(self, 'modeling_page'):
            self.modeling_page.scan_projects()

    def switch_to_page(self, idx):
        self.content_stack.setCurrentIndex(idx)

    def save_layout(self):
        if getattr(self, 'is_startup_protected', False):
            return
        s = self.size()
        p = self.pos()
        sizes = self.main_splitter.sizes()
        if len(sizes) > 1 and sizes[1] == 0:
            return
        self.settings.setValue("win_w", s.width())
        self.settings.setValue("win_h", s.height())
        self.settings.setValue("win_x", p.x())
        self.settings.setValue("win_y", p.y())
        self.settings.setValue("splitter_sizes", sizes)
        if hasattr(self, 'chat_page'):
            chat_sizes = self.chat_page.get_input_height_state()
            if len(chat_sizes) > 1:
                self.settings.setValue("chat_input_sizes", chat_sizes)
        if hasattr(self, 'panel_manager'):
            try:
                self.panel_manager.save_layout()
            except Exception as e:
                print(f"⚠️ 保存面板布局失败: {e}")
        self.settings.sync()

    def handle_restart_request(self, is_update=False):
        self.save_layout()
        if is_update:
            reply = QMessageBox.question(
                self, "应用更新",
                "检测到核心组件更新，需要重启客户端生效。\n是否立即重启？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.chat_page.log_status("⚡ 正在执行升级重启...")
                QTimer.singleShot(500, lambda: os._exit(UPDATE_CODE))
            else:
                self.chat_page.log_status("⚠️ 更新已暂存")
        else:
            self.chat_page.log_status("♻️ 请求普通重启...")
            QTimer.singleShot(1000, lambda: os._exit(RESTART_EXIT_CODE))

    def handle_remote_run(self, path):
        if not os.path.exists(path):
            return
        if hasattr(self.worker, 'touch_file'):
            self.worker.touch_file(path)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                code = f.read()
            if hasattr(self.worker, 'run_remote_script'):
                self.worker.run_remote_script(code)
                self.chat_page.log_status(f"🚀 [RPC] 远程投送: {os.path.basename(path)}")
            else:
                self.chat_page.log_status(f"⚠️ Worker 不支持远程执行")
        except Exception as e:
            self.chat_page.log_status(f"❌ 发送失败: {e}")

    def copy_snapshot_to_clipboard(self, content):
        QApplication.clipboard().setText(content)
        QMessageBox.information(self, "快照就绪", "✅ 项目快照已生成并复制到剪贴板！")

    def init_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件(&F)")
        save_layout_action = file_menu.addAction("保存布局")
        save_layout_action.triggered.connect(self.save_layout)
        reset_layout_action = file_menu.addAction("重置布局")
        reset_layout_action.triggered.connect(
            lambda: self.panel_manager.reset_layout() if hasattr(self, 'panel_manager') else None
        )
        file_menu.addSeparator()
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)
        self.panel_menu = menubar.addMenu("面板(&P)")
        workspace_menu = self.panel_menu.addMenu("工作区")
        save_workspace_action = workspace_menu.addAction("保存当前工作区...")
        save_workspace_action.triggered.connect(self.save_workspace_dialog)
        load_workspace_action = workspace_menu.addAction("加载工作区...")
        load_workspace_action.triggered.connect(self.load_workspace_dialog)
        self.panel_menu.addSeparator()
        # Skills 面板菜单由插件系统管理
        self.refresh_panel_menu()
        view_menu = menubar.addMenu("视图(&V)")
        fullscreen_action = view_menu.addAction("全屏")
        fullscreen_action.setCheckable(True)
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        
        # 插件菜单
        self.plugin_menu = menubar.addMenu("插件(&L)")
        
        # 插件管理器
        plugin_manager_action = self.plugin_menu.addAction("🔌 插件管理器")
        plugin_manager_action.triggered.connect(self.show_plugin_manager)
        
        self.plugin_menu.addSeparator()
        
        # 动态插件列表（将在 refresh_plugin_menu 中填充）
        self.refresh_plugin_menu()
        
        help_menu = menubar.addMenu("帮助(&H)")
        about_action = help_menu.addAction("关于")
        about_action.triggered.connect(self.show_about)
    
        from app.ui.components.panels.project_menu import ProjectMenu
        self._project_menu = ProjectMenu(self)
        menubar.insertMenu(view_menu.menuAction(), self._project_menu.get_menu())
    
    def init_panel_system(self):
        self.panel_manager = PanelManager(self)
        config_dir = os.path.join(APP_ROOT, ".config")
        self.workspace_manager = WorkspaceManager(config_dir)
        self.workspace_manager.panel_manager = self.panel_manager
        self.panel_manager.panel_registered.connect(self.update_panel_menu)
        self.panel_manager.panel_shown.connect(lambda: self.refresh_panel_menu())
        self.panel_manager.panel_hidden.connect(lambda: self.refresh_panel_menu())

        # 🔌 初始化插件系统，并先扫描启用插件数量，避免 expected_panels_count 过早触发
        self.plugin_loader = PanelPluginLoader([
            "plugins/panels",  # 用户插件目录
        ])
        plugin_infos = self.plugin_loader.scan_plugins()
        enabled_plugin_count = sum(1 for p in plugin_infos if getattr(p, "enabled", False))

        self.create_devops_panels()

        # 扫描并加载插件
        self.load_panel_plugins()

        # 所有内置面板和插件面板都处理完后，统一做启动收尾
        self.finalize_panel_startup()

        print(f"📊 已完成内置面板与插件面板注册 (插件: {enabled_plugin_count})")

    def finalize_panel_startup(self):
        """面板系统启动收尾：统一恢复布局、刷新菜单、解除启动保护。"""
        print("🎉 面板注册流程完成，开始恢复布局...")

        layout_file = os.path.join(APP_ROOT, ".config", "panel_layout.json")
        if os.path.exists(layout_file):
            try:
                import json
                with open(layout_file, 'r', encoding='utf-8') as f:
                    layout = json.load(f)
                self.panel_manager.restore_layout(layout)
                print("✅ 已自动加载上次的面板布局")
            except Exception as e:
                print(f"⚠️ 加载面板布局失败: {e}")

        # Qt 恢复布局后再刷新菜单勾选状态，避免启动早期状态不准
        QTimer.singleShot(300, self.refresh_panel_menu)
        QTimer.singleShot(500, self.refresh_panel_menu)

        self.is_loading = False
        self.is_startup_protected = False
        print("✅ 启动完成，布局记忆已启用")
    
    def create_devops_panels(self):
        """🆕 创建 DevOps 面板"""
        self.task_schedule_panel = TaskSchedulePanel()
        self.panel_manager.register_panel(self.task_schedule_panel, {
            "id": "task_schedule",
            "title": "任务调度",
            "default_area": Qt.DockWidgetArea.RightDockWidgetArea
        })
        # 连接取消信号到 worker
        if self.worker and hasattr(self.worker, 'cancel_task'):
            self.task_schedule_panel.cancel_signal.connect(
                lambda task_id: self.worker.cancel_task(task_id)
            )
        self.code_review_panel = CodeReviewPanel()
        self.panel_manager.register_panel(self.code_review_panel, {
            "id": "code_review",
            "title": "代码审查",
            "default_area": Qt.DockWidgetArea.RightDockWidgetArea
        })
        self.code_review_panel.request_scan.connect(self.handle_scan_request)
        self.code_review_panel.request_apply.connect(self.handle_apply_request)
        self.code_review_panel.request_clear_cache.connect(self.handle_clear_cache_request)
        self.git_control_panel = GitControlPanel()
        self.panel_manager.register_panel(self.git_control_panel, {
            "id": "git_control",
            "title": "Git 版本控制",
            "default_area": Qt.DockWidgetArea.RightDockWidgetArea
        })
        self.git_control_panel.request_git_backup.connect(self.handle_git_request)
        self.git_control_panel.request_git_refresh.connect(self.handle_git_refresh_request)
        self.git_control_panel.request_git_push_only.connect(self.handle_git_push_only_request)
        self.git_control_panel.request_git_diff_dialog.connect(self.handle_git_diff_dialog_request)
        self.git_control_panel.request_add_to_gitignore.connect(self.handle_add_to_gitignore)
        self.git_control_panel.request_remove_tracking_and_ignore.connect(self.handle_remove_tracking_and_ignore)
        self.git_control_panel.request_gitignore_save.connect(self.handle_gitignore_save)
        self.git_control_panel.request_gitignore_load.connect(self.handle_gitignore_load)
        QTimer.singleShot(300, self.handle_git_refresh_request)
        self.runtime_log_panel = RuntimeLogPanel()
        self.panel_manager.register_panel(self.runtime_log_panel, {
            "id": "runtime_log",
            "title": "运行日志",
            "default_area": Qt.DockWidgetArea.BottomDockWidgetArea
        })

        self._log_panel_bridge = LogPanelBridge(self)
        self._qt_log_handler = QtPanelLogHandler(
            bridge=self._log_panel_bridge,
            level=logging.INFO,
            filter_noise=True,
        )
        self._log_panel_bridge.log_signal.connect(self.runtime_log_panel.append_log)
        register_panel_handler(self._qt_log_handler)
        logger.info("运行日志面板已连接统一日志系统")
        
        # 沙盒监控面板
        try:
            self.sandbox_monitor_panel = SandboxMonitorPanel()
            self.panel_manager.register_panel(self.sandbox_monitor_panel, {
                "id": "sandbox_monitor",
                "title": "沙盒监控",
                "default_area": Qt.DockWidgetArea.RightDockWidgetArea
            })
            
            # 连接沙盒监控信号
            self.sandbox_monitor_panel.refresh_requested.connect(self._refresh_sandbox_info)
            self.sandbox_monitor_panel.clear_history_requested.connect(self._clear_sandbox_history)
            
            # 监听代码执行完成信号
            if self.worker and hasattr(self.worker, 'code_execution_completed'):
                self.worker.code_execution_completed.connect(self._refresh_sandbox_info)
            
            # 初始加载沙盒信息
            self._refresh_sandbox_info()
            print("✅ 沙盒监控面板已注册")
        except Exception as e:
            print(f"❌ 沙盒监控面板注册失败: {e}")
            import traceback
            traceback.print_exc()

        self.context_workspace_panel = ContextWorkspacePanel()
        self.panel_manager.register_panel(self.context_workspace_panel, {
            "id": "context_workspace",
            "title": "上下文工作台",
            "default_area": Qt.DockWidgetArea.RightDockWidgetArea
        })
        self.context_workspace_panel_logic = ContextWorkspacePanelLogic(
            panel=self.context_workspace_panel,
            worker=self.worker,
            runtime_log_panel=getattr(self, 'runtime_log_panel', None),
            staging_injector=getattr(self.chat_page, 'activate_staging_area', None),
        )
        self.context_workspace_panel_logic.bind()

        self.plugin_manager_panel = PluginManagerPanel(
            plugin_loader=self.plugin_loader,
            parent=self
        )
        self.panel_manager.register_panel(self.plugin_manager_panel, {
            "id": "plugin_manager",
            "title": "插件管理器",
            "default_area": Qt.DockWidgetArea.RightDockWidgetArea
        })
        self.plugin_manager_panel.plugin_detail_requested.connect(self.show_plugin_detail)
        self.plugin_manager_panel.hide()

        # 刷新面板菜单状态
        self.refresh_panel_menu()

        try:
            self.context_workspace_panel_logic.initialize()
        except Exception as e:
            print(f"上下文工作台初始化请求失败: {e}")
        
        # 🔧 连接 worker 信号到面板
        if self.worker:
            try:
                # 运行日志面板
                if hasattr(self.worker, 'server_log_signal') and self.worker.server_log_signal:
                    self.worker.server_log_signal.connect(self.runtime_log_panel.append_log)
                else:
                    print(f"⚠️ server_log_signal 不可用")
                print("✅ 已连接 server_log_signal 到运行日志面板")
                
                # 任务调度面板
                if hasattr(self.worker, "queue_monitor_signal"):
                    self.worker.queue_monitor_signal.connect(
                        lambda data: self.task_schedule_panel.update_task_queue(
                            data, 
                            client_id=getattr(self.worker, "client_id", "Host")
                        )
                    )
                    print("✅ 已连接 queue_monitor_signal 到任务调度面板")
                
                # 代码审查面板
                if hasattr(self.worker, "update_list_signal"):
                    self.worker.update_list_signal.connect(self.code_review_panel.update_change_list)
                    print("✅ 已连接 update_list_signal 到代码审查面板")

            except Exception as e:
                print(f"⚠️ 连接 worker 信号失败: {e}")
        else:
            print("⚠️ Worker 未初始化，跳过信号连接")
    def load_panel_plugins(self):
        """🔌 加载面板插件"""
        try:
            # 扫描插件
            plugin_infos = self.plugin_loader.scan_plugins()
            print(f"[PluginSystem] 发现 {len(plugin_infos)} 个插件")
            
            # 加载启用的插件
            loaded_count = 0
            for plugin_info in plugin_infos:
                if not plugin_info.enabled:
                    print(f"[PluginSystem] 跳过禁用的插件: {plugin_info.name}")
                    continue
                
                try:
                    # 加载插件
                    plugin = self.plugin_loader.load_plugin(plugin_info.id)
                    if not plugin:
                        continue
                    
                    # 创建面板
                    panel = plugin.create_panel()
                    if not panel:
                        print(f"[PluginSystem] 插件 {plugin_info.name} 创建面板失败")
                        continue
                    
                    # 标记为插件面板
                    panel._plugin_id = plugin_info.id
                    
                    # 注册面板
                    self.panel_manager.register_panel(panel, {
                        "id": plugin_info.id,
                        "title": plugin_info.name,
                        "default_area": self._get_dock_area(plugin_info.default_area)
                    })
                    
                    # 调用插件钩子
                    plugin.on_panel_created(panel)
                    
                    # 特殊处理：为 SkillsPanel 设置 skill_data
                    if plugin_info.id == 'skills_panel':
                        try:
                            # 获取 skill_data（从某个地方）
                            if hasattr(self, 'skill_data'):
                                plugin.set_skill_data(self.skill_data)
                        except Exception as e:
                            logger.warning(f"设置 SkillsPanel 数据失败: {e}")
                    plugin._set_panel_instance(panel)
                    
                    # 连接面板关闭信号
                    panel.closed.connect(lambda pid=plugin_info.id: self._on_plugin_panel_closed(pid))
                    panel.visibilityChanged.connect(lambda visible, pid=plugin_info.id: self._on_plugin_visibility_changed(pid, visible))
                    
                    loaded_count += 1
                    print(f"[PluginSystem] ✅ 插件加载成功: {plugin_info.name} v{plugin_info.version}")
                    
                except Exception as e:
                    print(f"[PluginSystem] ❌ 加载插件失败 {plugin_info.name}: {e}")
                    import traceback
                    traceback.print_exc()
            
            print(f"[PluginSystem] 插件加载完成: {loaded_count}/{len(plugin_infos)}")
            
            # 刷新插件菜单
            self.refresh_plugin_menu()
            
        except Exception as e:
            print(f"[PluginSystem] ❌ 插件系统初始化失败: {e}")
            import traceback
            traceback.print_exc()
        plugin_count = len(self.plugin_loader.plugins) if hasattr(self, 'plugin_loader') else 0
        print(f"📊 插件面板加载完成: {plugin_count}")
    
    def _get_dock_area(self, area_str: str) -> Qt.DockWidgetArea:
        """将字符串转换为 Qt.DockWidgetArea"""
        area_map = {
            "left": Qt.DockWidgetArea.LeftDockWidgetArea,
            "right": Qt.DockWidgetArea.RightDockWidgetArea,
            "top": Qt.DockWidgetArea.TopDockWidgetArea,
            "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
        }
        return area_map.get(area_str.lower(), Qt.DockWidgetArea.RightDockWidgetArea)
    
    def _on_plugin_panel_closed(self, plugin_id: str):
        """插件面板关闭时的回调"""
        try:
            plugin = self.plugin_loader.get_plugin(plugin_id)
            if plugin and plugin.panel_instance:
                plugin.on_panel_closed(plugin.panel_instance)
                plugin._set_panel_instance(None)
            
            # 刷新插件菜单勾选状态
            self._update_plugin_menu_check_state()
            
        except Exception as e:
            print(f"[PluginSystem] 处理面板关闭事件失败: {e}")

    def _on_plugin_visibility_changed(self, plugin_id: str, visible: bool):
        """插件面板可见性变化时的回调"""
        self._update_plugin_menu_check_state()

    def _update_plugin_menu_check_state(self):
        """更新插件菜单的勾选状态（根据面板实际可见性）"""
        try:
            if not hasattr(self, 'plugin_menu'):
                return
            
            actions = self.plugin_menu.actions()
            # 跳过前两个（管理器 + 分隔符）
            for action in actions[2:]:
                if action.isCheckable():
                    # 从 action text 中提取插件信息，查找对应面板
                    plugin_id = action.data()
                    if plugin_id:
                        plugin = self.plugin_loader.get_plugin(plugin_id)
                        if plugin and plugin.panel_instance:
                            action.setChecked(plugin.panel_instance.isVisible())
                        else:
                            action.setChecked(False)
        except Exception as e:
            logger.error(f"更新插件菜单状态失败: {e}")

    def update_panel_menu(self, panel_id):
        """🆕 更新面板菜单"""
        self.refresh_panel_menu()
    



    def _update_panel_menu_state(self, panel_id, is_visible):
        """更新菜单项的勾选状态"""
        try:
            panel = self.panel_manager.get_panel(panel_id)
            if not panel or not hasattr(self, 'panel_menu'):
                return
            
            for action in self.panel_menu.actions():
                if action.text() == panel.panel_title:
                    action.setChecked(is_visible)
                    break
        except Exception as e:
            print(f"[DEBUG] 更新菜单状态失败: {e}")

    def refresh_panel_menu(self):
        """刷新面板菜单"""
        # 连接所有面板的可见性改变信号
        try:
            panels = self.panel_manager.get_all_panels()
            for panel_id, panel in panels.items():
                # 连接现有的三个信号来更新菜单
                try:
                    panel.minimize_requested.disconnect()
                    panel.docked.disconnect()
                    panel.closed.disconnect()
                except Exception as e:
                    logger.warning(e)
                
                panel.minimize_requested.connect(lambda pid=panel_id: self._update_panel_menu_state(pid, False))
                panel.docked.connect(lambda pid=panel_id: self._update_panel_menu_state(pid, True))
                panel.closed.connect(lambda pid=panel_id: self._update_panel_menu_state(pid, False))
        except Exception as e:
            print(f"[DEBUG] 连接信号失败: {e}")
        try:
            if not hasattr(self, 'panel_menu'):
                return
            
            # 清除现有的动态菜单项（保留工作区菜单和分隔符）
            actions = self.panel_menu.actions()
            # 保留前两项（工作区菜单和分隔符），删除后面的
            if len(actions) > 2:
                for action in actions[2:]:
                    self.panel_menu.removeAction(action)
            
            # 获取所有面板
            panels = self.panel_manager.get_all_panels()
            
            # 为每个面板添加菜单项
            for panel_id, panel in panels.items():
                panel_title = panel.panel_title if hasattr(panel, 'panel_title') else panel_id
                action = self.panel_menu.addAction(panel_title)
                action.setCheckable(True)
                action.setChecked(panel.isVisible())
                action.triggered.connect(lambda checked, pid=panel_id: self.panel_manager.toggle_panel(pid))
        except Exception as e:
            print(f"[ERROR] refresh_panel_menu 失败: {e}")

    def _get_sandbox_docker_manager(self):
        """获取沙盒 DockerManager。

        优先使用真实执行侧实例；若当前是 RemoteWorker 等不暴露 agent 的场景，
        则回退到主窗口缓存的本地 DockerManager，避免面板永久显示 unavailable。
        """
        try:
            if self.worker and hasattr(self.worker, 'agent'):
                agent = getattr(self.worker, 'agent', None)
                docker_manager = getattr(agent, 'docker_manager', None) if agent else None
                if docker_manager:
                    self._docker_manager = docker_manager
                    return docker_manager
        except Exception as e:
            print(f"⚠️ 获取 worker.agent.docker_manager 失败: {e}")

        try:
            if self._docker_manager is not None:
                return self._docker_manager

            from app.core.docker_manager import DockerManager
            self._docker_manager = DockerManager()
            return self._docker_manager
        except Exception as e:
            print(f"⚠️ 初始化本地 DockerManager 失败: {e}")
            return None

    def _refresh_sandbox_info(self):
        """刷新沙盒信息"""
        try:
            docker_manager = self._get_sandbox_docker_manager()
            if not docker_manager:
                if hasattr(self, "sandbox_monitor_panel"):
                    self.sandbox_monitor_panel.update_container_status("unavailable")
                return

            stats = docker_manager.get_execution_statistics()
            if hasattr(self, "sandbox_monitor_panel"):
                self.sandbox_monitor_panel.update_statistics(stats)

            if docker_manager.available and docker_manager.container:
                docker_manager.container.reload()
                status = docker_manager.container.status
                container_id = docker_manager.container.short_id
                if hasattr(self, "sandbox_monitor_panel"):
                    self.sandbox_monitor_panel.update_container_status(status, container_id)
            else:
                if hasattr(self, "sandbox_monitor_panel"):
                    self.sandbox_monitor_panel.update_container_status("unavailable")

            history = docker_manager.get_execution_history(count=10)
            if hasattr(self, "sandbox_monitor_panel"):
                self.sandbox_monitor_panel.update_history(history)
        except Exception as e:
            print(f"⚠️ 刷新沙盒信息失败: {e}")
            import traceback
            traceback.print_exc()
            if hasattr(self, "sandbox_monitor_panel"):
                self.sandbox_monitor_panel.update_container_status("unavailable")

    def _clear_sandbox_history(self):
        """清空沙盒历史"""
        try:
            from PySide6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "确认清空",
                "确定要清空所有沙盒执行历史吗？\n此操作不可恢复。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                docker_manager = self._get_sandbox_docker_manager()
                if docker_manager:
                    docker_manager.clear_execution_history()
                    self._refresh_sandbox_info()
                    QMessageBox.information(self, "成功", "沙盒历史已清空")
                else:
                    QMessageBox.warning(self, "错误", "docker_manager 不可用")
        except Exception as e:
            print(f"⚠️ 清空历史失败: {e}")

    def show_plugin_manager(self):
        """显示插件管理器面板"""
        try:
            if not hasattr(self, "plugin_manager_panel") or self.plugin_manager_panel is None:
                raise RuntimeError("插件管理器面板未在启动时注册")

            self.plugin_manager_panel.show()
            self.plugin_manager_panel.raise_()

            if hasattr(self, "panel_manager"):
                self.panel_manager.panel_states["plugin_manager"] = "docked"

            self.refresh_panel_menu()
            logger.info("插件管理器面板已打开")
        except Exception as e:
            logger.error(f"打开插件管理器失败: {e}")
            QMessageBox.critical(
                self,
                "错误",
                f"打开插件管理器失败：{str(e)}"
            )

    def show_plugin_detail(self, plugin_id: str):
        """显示插件详情对话框"""
        try:
            plugin_info = None
            for info in self.plugin_loader.scan_plugins():
                if info.id == plugin_id:
                    plugin_info = info
                    break

            if not plugin_info:
                QMessageBox.warning(
                    self,
                    "警告",
                    f"未找到插件: {plugin_id}"
                )
                return

            from app.ui.dialogs.plugin_detail_dialog import PluginDetailDialog
            dialog = PluginDetailDialog(
                plugin_info=plugin_info,
                plugin_loader=self.plugin_loader,
                parent=self
            )
            dialog.exec()
        except Exception as e:
            logger.error(f"显示插件详情失败: {e}")
            QMessageBox.critical(
                self,
                "错误",
                f"显示插件详情失败：{str(e)}"
            )

    def refresh_plugin_menu(self):
        """刷新插件菜单"""
        try:
            print("[DEBUG] refresh_plugin_menu 被调用")
            
            if not hasattr(self, 'plugin_menu'):
                print("[DEBUG] plugin_menu 不存在")
                return
            
            print(f"[DEBUG] plugin_menu 存在，当前有 {len(self.plugin_menu.actions())} 个菜单项")
            
            # 清除现有的动态菜单项（保留管理器和分隔符）
            actions = self.plugin_menu.actions()
            if len(actions) > 2:  # 管理器 + 分隔符
                for action in actions[2:]:
                    self.plugin_menu.removeAction(action)
            
            # 获取所有插件
            plugins = self.plugin_loader.scan_plugins()
            print(f"[DEBUG] 扫描到 {len(plugins)} 个插件")
            for p in plugins:
                print(f"[DEBUG]   - {p.id}: {p.name} (enabled={p.enabled})")
            
            if not plugins:
                no_plugins_action = self.plugin_menu.addAction("(无可用插件)")
                no_plugins_action.setEnabled(False)
                return
            
            # 添加插件菜单项
            for plugin_info in plugins:
                plugin_id = plugin_info.id
                plugin_name = plugin_info.name
                plugin_icon = plugin_info.icon
                is_enabled = plugin_info.enabled
                
                # 创建菜单项
                action_text = f"{plugin_icon} {plugin_name}"
                if is_enabled:
                    action_text += " ✓"
                
                action = self.plugin_menu.addAction(action_text)
                print(f"[DEBUG] 添加菜单项: {action_text}")
                action.setCheckable(True)
                # 根据面板实际可见性设置勾选状态
                plugin = self.plugin_loader.get_plugin(plugin_id)
                if plugin and plugin.panel_instance:
                    action.setChecked(plugin.panel_instance.isVisible())
                else:
                    action.setChecked(is_enabled)
                action.setData(plugin_id)
                
                # 连接信号（使用 lambda 捕获当前值）
                action.triggered.connect(
                    lambda checked, pid=plugin_id: self.toggle_plugin_from_menu(pid, checked)
                )
            
            logger.debug(f"刷新插件菜单: {len(plugins)} 个插件")
            
        except Exception as e:
            logger.error(f"刷新插件菜单失败: {e}")
    
    def toggle_plugin_from_menu(self, plugin_id: str, checked: bool):
        """从菜单切换插件面板的显示/隐藏"""
        try:
            plugin = self.plugin_loader.get_plugin(plugin_id)
            
            if checked:
                # 显示面板
                if plugin and plugin.panel_instance:
                    # 面板已存在，直接显示
                    plugin.panel_instance.show()
                    plugin.panel_instance.raise_()
                else:
                    # 面板不存在，需要重新加载插件并创建面板
                    if not plugin:
                        plugin = self.plugin_loader.load_plugin(plugin_id)
                    if plugin:
                        panel = plugin.create_panel()
                        if panel:
                            panel._plugin_id = plugin_id  # 标记为插件面板
                            plugin_info = self.plugin_loader.get_plugin_info(plugin_id)
                            area = self._get_dock_area(
                                plugin_info.default_area if plugin_info else 'right'
                            )
                            self.addDockWidget(area, panel)
                            if hasattr(self, 'panel_manager'):
                                self.panel_manager.register_panel(panel, {
                                    "id": plugin_id,
                                    "title": plugin_info.name if plugin_info else plugin_id,
                                    "default_area": area
                                })
                            plugin.on_panel_created(panel)
                            plugin._set_panel_instance(panel)
                            panel.closed.connect(lambda pid=plugin_id: self._on_plugin_panel_closed(pid))
                            panel.visibilityChanged.connect(lambda visible, pid=plugin_id: self._on_plugin_visibility_changed(pid, visible))
                            panel.show()
            else:
                # 隐藏面板
                if plugin and plugin.panel_instance:
                    plugin.panel_instance.hide()
                    
        except Exception as e:
            logger.error(f"切换插件面板失败: {e}")
            import traceback
            traceback.print_exc()
    def get_skills_panel(self):
        """获取 SkillsPanel 实例（通过插件系统）"""
        try:
            plugin = self.plugin_loader.get_plugin('skills_panel')
            if plugin and plugin.panel_instance:
                return plugin.panel_instance
        except Exception as e:
            logger.warning(f"获取 SkillsPanel 失败: {e}")
        return None
    def setup_dock_widgets(self):
        """配置所有 DockWidget 的拖拽功能"""
        from PySide6.QtWidgets import QDockWidget

        for dock in self.findChildren(QDockWidget):
            dock.setFeatures(
                QDockWidget.DockWidgetMovable |
                QDockWidget.DockWidgetFloatable |
                QDockWidget.DockWidgetClosable
            )
            # Qt 会自动处理标签页拖拽、浮窗等

    def create_placeholder_page(self, title, desc):
        p = QWidget()
        l = QVBoxLayout(p)
        t = QLabel(title)
        d = QLabel(desc)
        l.addStretch(); l.addWidget(t); l.addWidget(d); l.addStretch()
        def _safe_apply_placeholder_theme():
            try:
                self.apply_placeholder_theme(p, t, d)
            except RuntimeError:
                pass

        theme_manager.theme_changed.connect(_safe_apply_placeholder_theme)
        self.apply_placeholder_theme(p, t, d)
        return p

    def apply_placeholder_theme(self, p_widget, t_label, d_label):
        p = theme_manager.get_palette()
        p_widget.setStyleSheet(f"background-color: {p.BG_PRIMARY};")
        t_label.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-size: 24px;")
        t_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d_label.setStyleSheet(f"color: {p.TEXT_SECONDARY};")
        d_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def save_workspace_dialog(self):
        """🆕 保存工作区对话框"""
        name, ok = QInputDialog.getText(self, "保存工作区", "请输入工作区名称:")
        if ok and name:
            if hasattr(self, "workspace_manager") and hasattr(self, "panel_manager"):
                layout = self.panel_manager.get_layout()
                self.workspace_manager.save_preset(name, layout)
                QMessageBox.information(self, "成功", f"工作区 '{name}' 已保存")

    def load_workspace_dialog(self):
        """🆕 加载工作区对话框"""
        if hasattr(self, "workspace_manager") and hasattr(self, "panel_manager"):
            presets = self.workspace_manager.list_presets()
            if not presets:
                QMessageBox.information(self, "提示", "没有保存的工作区")
                return

            if presets and isinstance(presets[0], dict):
                preset_names = [p["name"] for p in presets]
            else:
                preset_names = presets

            name, ok = QInputDialog.getItem(self, "加载工作区", "选择工作区:", preset_names, 0, False)
            if ok and name:
                preset_data = self.workspace_manager.load_preset(name)
                if preset_data:
                    if isinstance(preset_data, dict) and "layout" in preset_data:
                        layout = preset_data["layout"]
                    else:
                        layout = preset_data

                    self.panel_manager.restore_layout(layout)
                    QMessageBox.information(self, "成功", f"工作区 '{name}' 已加载")
                else:
                    QMessageBox.warning(self, "错误", f"加载工作区 '{name}' 失败")

    def toggle_fullscreen(self, checked):
        """🆕 切换全屏"""
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _update_window_title(self):
        from app.core.project_context import ProjectContext
        ctx = ProjectContext.get()
        role_name = self.user_profile.get("role", "user").upper()
        project = ctx.project_name
        self.setWindowTitle(f"AI Bridge - {project} - {self.user_profile.get('username')} [{role_name}]")

    def show_about(self):
        """🆕 显示关于对话框"""
        QMessageBox.about(self, "关于 AI Bridge",
                         "AI Bridge Client\n\n"
                         "版本: 1.0.0\n"
                         "一个智能的 AI 辅助开发工具")

    def closeEvent(self, event):
        try:
            theme_manager.theme_changed.disconnect(self.apply_theme)
        except Exception as e:
            logger.warning(e)
        self.save_layout()
        if hasattr(self.worker, "stop_worker"):
            self.worker.stop_worker()
        elif hasattr(self.worker, "isRunning") and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        super().closeEvent(event)

