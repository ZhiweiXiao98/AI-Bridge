import os
import subprocess
from PySide6.QtCore import QObject, QTimer

from app.core.project_context import ProjectContext
from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.worker_project_switch", side="worker")


class WorkerProjectSwitchBridge(QObject):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._docker_manager = getattr(worker, 'docker_manager', None)
        self._test_process = None

        ctx = ProjectContext.get()
        ctx.about_to_switch.connect(self._on_about_to_switch)
        ctx.project_switched.connect(self._on_project_switched)

    def _on_about_to_switch(self, new_root: str, new_db_path: str):
        logger.info("[项目切换] 阶段2: 资源硬切断开始")
        self._cancel_running_tasks()
        self._force_cleanup_docker()
        logger.info("[项目切换] 阶段2: 资源硬切断完成")

    def _on_project_switched(self, new_root: str, new_db_path: str):
        logger.info("[项目切换] 阶段4: Worker 状态刷新 → %s", new_root)
        if self._docker_manager:
            self._docker_manager.project_root = new_root
        QTimer.singleShot(0, self._refresh_conversation_list)

    def _refresh_conversation_list(self):
        if hasattr(self._worker, 'api_source') and self._worker.api_source:
            try:
                convs = self._worker.api_source.get_conversations()
                self._worker.sessions_signal.emit(convs if convs else [])
                self._worker.get_api_conversations()
                logger.info("[项目切换] 已通知 UI 刷新对话列表 (%d 个对话)", len(convs) if convs else 0)
            except Exception as e:
                logger.warning("[项目切换] 刷新对话列表失败: %s", e)

    def _force_cleanup_docker(self):
        if not self._docker_manager:
            return
        container = getattr(self._docker_manager, '_container', None)
        if not container:
            return
        try:
            container.stop(timeout=3)
            container.remove(force=True)
            logger.info("[Docker] 容器已强制清理")
        except Exception as e:
            logger.warning(f"[Docker] 容器清理异常（可能已不存在）: {e}")
        finally:
            self._docker_manager._container = None

    def _cancel_running_tasks(self):
        proc = self._test_process
        if not proc or not hasattr(proc, 'poll'):
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            logger.info("[Worker] 子进程已终止")
        except Exception as e:
            logger.warning(f"[Worker] 子进程终止异常: {e}")
