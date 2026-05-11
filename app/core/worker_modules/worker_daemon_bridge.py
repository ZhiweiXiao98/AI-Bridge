from PySide6.QtCore import QObject, Signal

from app.core.daemon.daemon_config import DaemonConfig
from app.core.daemon.daemon_event_bus import DaemonEventBus
from app.core.daemon.daemon_thread import DaemonThread
from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.worker_daemon_bridge", side="worker")


class WorkerDaemonBridge(QObject):
    daemon_suggestion_signal = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = DaemonConfig.get()
        logger.info(
            "[DaemonBridge] 初始化: enabled=%s suggest_enabled=%s api_key=%s provider=%s",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            bool(getattr(self._config, 'api_key', '') or ''),
            getattr(self._config, 'provider', ''),
        )
        self.event_bus = DaemonEventBus()
        self.daemon_thread = DaemonThread(self.event_bus, parent=self)
        self.daemon_thread.suggestion_signal.connect(self._on_suggestion)
        logger.info("[DaemonBridge] 守护线程对象已创建: running=%s", self.daemon_thread.isRunning())

    def start(self):
        logger.info(
            "[DaemonBridge] start 请求: enabled=%s suggest_enabled=%s running=%s",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            self.daemon_thread.isRunning(),
        )
        if not self._config.enabled:
            logger.info("[DaemonBridge] 已禁用，不启动")
            return
        if not self._config.api_key:
            logger.warning("[DaemonBridge] API key 未配置，不启动守护线程")
            return
        self.daemon_thread.start()
        logger.info("[DaemonBridge] 已启动: running=%s", self.daemon_thread.isRunning())

    def stop(self):
        logger.info("[DaemonBridge] stop 请求: running=%s", self.daemon_thread.isRunning())
        if self.daemon_thread.isRunning():
            self.daemon_thread.stop()
            logger.info("[DaemonBridge] 已停止")

    def reload(self):
        logger.info("[DaemonBridge] 热重载配置...")
        self.stop()
        self._config = DaemonConfig.reload()
        self.start()
        logger.info("[DaemonBridge] 配置已热重载")

    def on_reply_completed(self, reply_text: str, mode: str, chat_id: str = "", recent_context: str = ""):
        logger.info(
            "[DaemonBridge] 收到回复完成: enabled=%s suggest_enabled=%s running=%s mode=%s chat_id=%s reply_len=%d recent_context_len=%d",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            self.daemon_thread.isRunning(),
            mode,
            chat_id,
            len(reply_text or ""),
            len(recent_context or ""),
        )
        if not self._config.enabled or not self._config.suggest.enabled:
            logger.info("[DaemonBridge] 跳过建议: 守护进程或建议功能已关闭")
            return
        if not self.daemon_thread.isRunning():
            logger.info("[DaemonBridge] 跳过建议: 守护线程未运行")
            return
        self.event_bus.emit(DaemonEventBus.EVENT_REPLY_COMPLETED, {
            "reply_text": reply_text,
            "mode": mode,
            "chat_id": chat_id,
            "recent_context": recent_context,
        })
        logger.info("[DaemonBridge] reply_completed 已转发到事件总线")

    def _on_suggestion(self, suggestions):
        try:
            count = len(suggestions or []) if isinstance(suggestions, (list, tuple)) else 1
        except Exception:
            count = -1
        logger.info("[DaemonBridge] 收到建议结果: count=%s", count)
        self.daemon_suggestion_signal.emit(suggestions)
