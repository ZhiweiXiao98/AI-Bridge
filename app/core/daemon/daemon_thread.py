from PySide6.QtCore import QThread, Signal

from app.core.daemon.daemon_config import DaemonConfig
from app.core.daemon.daemon_event_bus import DaemonEventBus
from app.core.daemon.daemon_llm import DaemonLLMRouter
from app.core.logging import get_logger

logger = get_logger("app.core.daemon.daemon_thread", side="worker")


class DaemonThread(QThread):
    suggestion_signal = Signal(object)

    def __init__(self, event_bus: DaemonEventBus, parent=None):
        super().__init__(parent)
        self.event_bus = event_bus
        self._config = DaemonConfig.get()
        self._llm: DaemonLLMRouter = None
        self._tasks: dict = {}
        self._running = False

    def run(self):
        logger.info(
            "[DaemonThread] run 进入: enabled=%s suggest_enabled=%s api_key=%s provider=%s",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            bool(getattr(self._config, 'api_key', '') or ''),
            getattr(self._config, 'provider', ''),
        )
        if not self._config.enabled:
            logger.info("[DaemonThread] 守护进程已禁用，跳过启动")
            return

        self._llm = DaemonLLMRouter(self._config)
        logger.info("[DaemonThread] LLM 路由器初始化完成: available=%s", self._llm.available)
        if not self._llm.available:
            logger.warning("[DaemonThread] 守护进程 LLM 不可用（API key 未配置或初始化失败），降级为静默模式")
            self._running = True
            self.exec()
            return

        self._register_tasks()
        self._subscribe_events()

        self._running = True
        logger.info("[DaemonThread] 守护进程已启动 (任务: %s)", list(self._tasks.keys()))
        self.exec()

    def stop(self):
        self._running = False
        self.quit()
        self.wait(3000)
        logger.info("守护进程已停止")

    def _register_tasks(self):
        logger.info("[DaemonThread] 开始注册任务: suggest_enabled=%s", self._config.suggest.enabled)
        if self._config.suggest.enabled:
            from app.core.daemon.tasks.suggest_task import SuggestTask
            self._tasks["suggest"] = SuggestTask(
                config=self._config.suggest,
                llm=self._llm,
            )
            logger.info("[DaemonThread] 任务已注册: suggest")
        else:
            logger.info("[DaemonThread] suggest 任务未启用，跳过注册")

    def _subscribe_events(self):
        logger.info("[DaemonThread] 开始订阅事件: reply_completed")
        self.event_bus.subscribe(
            DaemonEventBus.EVENT_REPLY_COMPLETED,
            self._on_reply_completed,
        )
        logger.info("[DaemonThread] 事件订阅完成: reply_completed")

    def _on_reply_completed(self, payload: dict):
        logger.info(
            "[DaemonThread] 收到 reply_completed: payload_keys=%s reply_len=%d mode=%s chat_id=%s",
            list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
            len(str((payload or {}).get('reply_text', '') or '')) if isinstance(payload, dict) else 0,
            (payload or {}).get('mode', '') if isinstance(payload, dict) else '',
            (payload or {}).get('chat_id', '') if isinstance(payload, dict) else '',
        )
        task = self._tasks.get("suggest")
        if not task:
            logger.info("[DaemonThread] 未找到 suggest 任务，跳过处理")
            return
        try:
            result = task.handle(payload)
            logger.info("[DaemonThread] suggest 处理完成: has_result=%s", bool(result))
            if result:
                self.suggestion_signal.emit(result)
                logger.info("[DaemonThread] 建议信号已发出")
        except Exception as e:
            logger.warning("[DaemonThread] 建议任务异常: %s", e)
