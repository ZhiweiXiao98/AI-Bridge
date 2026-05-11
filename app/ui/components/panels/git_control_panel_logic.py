import logging
# filename: app/ui/components/panels/git_control_panel_logic.py

from app.ui.components.panels.git_control_panel_presenter import GitControlPanelPresenter
from app.ui.components.panels.git_config_dialog import GitConfigDialog
from app.core.logging import get_logger

logger = get_logger("app.ui.git_control_panel_logic", side="ui")


class GitControlPanelLogic:
    def __init__(self, panel=None, worker=None, runtime_log_panel=None, refresh_workbench_callback=None, parent=None):
        self.panel = panel
        self.worker = worker
        self.runtime_log_panel = runtime_log_panel
        self.refresh_workbench_callback = refresh_workbench_callback
        self.parent = parent
        self.dialog = None
        self._last_snapshot_vm = {}
        self._last_checks_payload = {}

    def bind(self):
        if self.panel is not None and hasattr(self.panel, 'request_git_open_config'):
            self.panel.request_git_open_config.connect(self.open_dialog)
        if self.worker is not None and hasattr(self.worker, 'git_config_signal'):
            self.worker.git_config_signal.connect(self.handle_payload)

    def open_dialog(self):
        dialog = self._ensure_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.refresh_snapshot()

    def _ensure_dialog(self):
        if self.dialog is None:
            self.dialog = GitConfigDialog(self.parent)
            self.dialog.request_refresh.connect(self.refresh_snapshot)
            self.dialog.request_run_checks.connect(self.run_checks)
            self.dialog.request_init_repo.connect(self.init_repo)
            self.dialog.request_save_user.connect(self.save_user)
            self.dialog.request_set_remote.connect(self.set_remote)
            self.dialog.request_set_upstream.connect(self.set_upstream)
            self.dialog.request_recommended_action.connect(self.handle_recommended_action)
        return self.dialog

    def _log(self, text):
        if self.runtime_log_panel is not None and hasattr(self.runtime_log_panel, 'append_log'):
            self.runtime_log_panel.append_log(text)

    def _is_remote(self):
        return hasattr(self.worker, '_request_send')

    def refresh_snapshot(self):
        dialog = self._ensure_dialog()
        dialog.set_busy_state('snapshot', True)
        if self._is_remote():
            try:
                if hasattr(self.worker, 'get_git_config_snapshot'):
                    self.worker.get_git_config_snapshot()
                else:
                    self._log('❌ [Git] 当前远程 Worker 版本不支持 Git 配置快照')
                    dialog.set_busy_state('snapshot', False)
            except Exception as e:
                self._log(f'❌ [Git] 读取配置失败: {e}')
                dialog.set_busy_state('snapshot', False)
            return
        try:
            from app.core.git_manager import GitManager
            payload = GitManager().get_git_config_snapshot()
            payload['payload_kind'] = 'snapshot'
            self.handle_payload(payload)
        except Exception as e:
            self._log(f'❌ [Git] 读取配置失败: {e}')
            dialog.set_busy_state('snapshot', False)

    def run_checks(self):
        dialog = self._ensure_dialog()
        dialog.set_busy_state('checks', True)
        if self._is_remote():
            try:
                if hasattr(self.worker, 'run_git_connectivity_checks'):
                    self.worker.run_git_connectivity_checks()
                else:
                    self._log('❌ [Git] 当前远程 Worker 版本不支持 Git 检测')
                    dialog.set_busy_state('checks', False)
            except Exception as e:
                self._log(f'❌ [Git] 检测失败: {e}')
                dialog.set_busy_state('checks', False)
            return
        try:
            from app.core.git_manager import GitManager
            payload = GitManager().run_connectivity_checks()
            payload['payload_kind'] = 'checks'
            self.handle_payload(payload)
        except Exception as e:
            self._log(f'❌ [Git] 检测失败: {e}')
            dialog.set_busy_state('checks', False)

    def init_repo(self):
        dialog = self._ensure_dialog()
        dialog.set_busy_state('action', True)
        if self._is_remote():
            try:
                if hasattr(self.worker, 'do_server_git_init'):
                    self.worker.do_server_git_init()
                else:
                    self._log('❌ [Git] 当前远程 Worker 版本不支持初始化仓库')
                    dialog.set_busy_state('action', False)
            except Exception as e:
                self._log(f'❌ [Git] 初始化仓库失败: {e}')
                dialog.set_busy_state('action', False)
            return
        self._run_local_action(self._local_git_init)

    def save_user(self, name, email):
        dialog = self._ensure_dialog()
        dialog.set_busy_state('action', True)
        if self._is_remote():
            try:
                if hasattr(self.worker, 'do_server_git_set_user'):
                    self.worker.do_server_git_set_user(name, email)
                else:
                    self._log('❌ [Git] 当前远程 Worker 版本不支持保存 Git 用户信息')
                    dialog.set_busy_state('action', False)
            except Exception as e:
                self._log(f'❌ [Git] 保存用户信息失败: {e}')
                dialog.set_busy_state('action', False)
            return
        self._run_local_action(lambda: self._local_git_set_user(name, email))

    def set_remote(self, name, url):
        dialog = self._ensure_dialog()
        dialog.set_busy_state('action', True)
        if self._is_remote():
            try:
                if hasattr(self.worker, 'do_server_git_set_remote'):
                    self.worker.do_server_git_set_remote(name, url)
                else:
                    self._log('❌ [Git] 当前远程 Worker 版本不支持设置远程仓库')
                    dialog.set_busy_state('action', False)
            except Exception as e:
                self._log(f'❌ [Git] 设置远程仓库失败: {e}')
                dialog.set_busy_state('action', False)
            return
        self._run_local_action(lambda: self._local_git_set_remote(name, url))

    def set_upstream(self):
        dialog = self._ensure_dialog()
        dialog.set_busy_state('action', True)
        if self._is_remote():
            try:
                if hasattr(self.worker, 'do_server_set_upstream'):
                    self.worker.do_server_set_upstream()
                else:
                    self._log('❌ [Git] 当前远程 Worker 版本不支持绑定 upstream')
                    dialog.set_busy_state('action', False)
            except Exception as e:
                self._log(f'❌ [Git] 绑定 upstream 失败: {e}')
                dialog.set_busy_state('action', False)
            return
        self._run_local_action(self._local_git_set_upstream)

    def _run_local_action(self, func):
        import threading
        threading.Thread(target=func, daemon=True).start()


    def handle_recommended_action(self, action: str):
        action = str(action or '').strip()
        if action == 'init_repo':
            self.init_repo()
        elif action == 'save_user':
            self.save_user(
                self.dialog.input_user_name.text().strip() if self.dialog else '',
                self.dialog.input_user_email.text().strip() if self.dialog else '',
            )
        elif action == 'set_remote':
            self.set_remote('origin', self.dialog.input_origin_url.text().strip() if self.dialog else '')
        elif action == 'set_upstream':
            self.set_upstream()
        elif action == 'refresh':
            self.refresh_snapshot()
        else:
            self.run_checks()
    def _after_local_action(self, trigger_checks=False):
        dialog = self._ensure_dialog()
        dialog.set_busy_state('action', False)
        self.refresh_snapshot()
        if trigger_checks:
            self.run_checks()
        if callable(self.refresh_workbench_callback):
            try:
                self.refresh_workbench_callback()
            except Exception as e:
                logger.warning(e)

    def _local_git_init(self):
        try:
            from app.core.git_manager import GitManager
            ok, log = GitManager().init_repo()
            self._emit_log_lines(log)
            self._log('✅ [Git] 仓库初始化成功' if ok else '❌ [Git] 仓库初始化失败')
        except Exception as e:
            self._log(f'❌ [Git] 初始化仓库异常: {e}')
        finally:
            self._after_local_action(trigger_checks=False)

    def _local_git_set_user(self, name, email):
        try:
            from app.core.git_manager import GitManager
            ok, log = GitManager().set_user_config(name, email)
            self._emit_log_lines(log)
            self._log('✅ [Git] 用户信息保存成功' if ok else '❌ [Git] 用户信息保存失败')
        except Exception as e:
            self._log(f'❌ [Git] 保存用户信息异常: {e}')
        finally:
            self._after_local_action(trigger_checks=False)

    def _local_git_set_remote(self, name, url):
        try:
            from app.core.git_manager import GitManager
            ok, log = GitManager().set_remote(name, url)
            self._emit_log_lines(log)
            self._log('✅ [Git] 远程仓库设置成功' if ok else '❌ [Git] 远程仓库设置失败')
        except Exception as e:
            self._log(f'❌ [Git] 设置远程仓库异常: {e}')
        finally:
            self._after_local_action(trigger_checks=True)

    def _local_git_set_upstream(self):
        try:
            from app.core.git_manager import GitManager
            ok, log = GitManager().set_upstream_to_origin_current_branch()
            self._emit_log_lines(log)
            self._log('✅ [Git] 上游分支绑定成功' if ok else '❌ [Git] 上游分支绑定失败')
        except Exception as e:
            self._log(f'❌ [Git] 绑定 upstream 异常: {e}')
        finally:
            self._after_local_action(trigger_checks=True)

    def _emit_log_lines(self, log):
        if not log:
            return
        for line in str(log).splitlines():
            if line.strip():
                self._log(line)

    def handle_payload(self, payload):
        dialog = self._ensure_dialog()
        data = payload or {}
        kind = data.get('payload_kind')
        if not kind:
            kind = 'checks' if 'checks' in data else 'snapshot'
        if kind == 'checks':
            self._last_checks_payload = data
            dialog.set_checks_text(GitControlPanelPresenter.build_checks_text(data))
            dialog.set_guidance(
                GitControlPanelPresenter.build_setup_guidance(self._last_snapshot_vm, self._last_checks_payload)
            )
            dialog.set_busy_state('checks', False)
            dialog.set_busy_state('action', False)
            return
        vm = GitControlPanelPresenter.build_snapshot_view_model(data)
        self._last_snapshot_vm = vm
        dialog.set_snapshot_view_model(vm)
        dialog.set_guidance(
            GitControlPanelPresenter.build_setup_guidance(self._last_snapshot_vm, self._last_checks_payload)
        )
        dialog.set_busy_state('snapshot', False)
        dialog.set_busy_state('action', False)
