from PySide6.QtCore import QThread, Signal

from app.core.subagent.subagent_config import SubagentConfig
from app.core.subagent.subagent_event_bus import SubagentEventBus
from app.core.subagent.subagent_llm import SubagentLLMRouter
from app.core.logging import get_logger

logger = get_logger("app.core.subagent.subagent_thread", side="worker")


class SubagentThread(QThread):
    suggestion_signal = Signal(object)
    organize_signal = Signal(object)

    def __init__(self, event_bus: SubagentEventBus, parent=None):
        super().__init__(parent)
        self.event_bus = event_bus
        self._config = SubagentConfig.get()
        self._llm: SubagentLLMRouter = None
        self._tasks: dict = {}
        self._running = False
        self._organize_timer = None

    def run(self):
        logger.info(
            "[SubagentThread] run 进入: enabled=%s suggest_enabled=%s api_key=%s provider=%s",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            bool(getattr(self._config, 'api_key', '') or ''),
            getattr(self._config, 'provider', ''),
        )
        if not self._config.enabled:
            logger.info("[SubagentThread] Subagent已禁用，跳过启动")
            return

        self._llm = SubagentLLMRouter(self._config)
        logger.info("[SubagentThread] LLM 路由器初始化完成: available=%s", self._llm.available)
        if not self._llm.available:
            logger.warning("[SubagentThread] Subagent LLM 不可用（API key 未配置或初始化失败），降级为静默模式")
            self._running = True
            self.exec()
            return

        self._register_tasks()
        self._subscribe_events()

        self._running = True
        logger.info("[SubagentThread] Subagent已启动 (任务: %s)", list(self._tasks.keys()))
        self.exec()

    def stop(self):
        self._running = False
        self.quit()
        self.wait(3000)
        logger.info("Subagent已停止")

    def _register_tasks(self):
        logger.info("[SubagentThread] 开始注册任务: suggest_enabled=%s organize_enabled=%s", self._config.suggest.enabled, self._config.organize.enabled)
        if self._config.suggest.enabled:
            from app.core.subagent.tasks.suggest_task import SuggestTask
            self._tasks["suggest"] = SuggestTask(
                config=self._config.suggest,
                llm=self._llm,
            )
            logger.info("[SubagentThread] 任务已注册: suggest")
        else:
            logger.info("[SubagentThread] suggest 任务未启用，跳过注册")

        if self._config.organize.enabled:
            from app.core.subagent.tasks.organize_task import OrganizeTask
            self._tasks["organize"] = OrganizeTask(
                config=self._config.organize,
                llm=self._llm,
            )
            logger.info("[SubagentThread] 任务已注册: organize")
        else:
            logger.info("[SubagentThread] organize 任务未启用，跳过注册")

    def _subscribe_events(self):
        logger.info("[SubagentThread] 开始订阅事件: reply_completed")
        self.event_bus.subscribe(
            SubagentEventBus.EVENT_REPLY_COMPLETED,
            self._on_reply_completed,
        )
        self.event_bus.subscribe(
            SubagentEventBus.EVENT_DOC_CONVERT_REQUESTED,
            self._on_doc_convert_requested,
        )
        logger.info("[SubagentThread] 事件订阅完成: reply_completed, doc_convert_requested")

        if self._config.organize.enabled and self._config.organize.trigger == "polling":
            from PySide6.QtCore import QTimer
            self._organize_timer = QTimer()
            self._organize_timer.timeout.connect(self._on_organize_tick)
            self._organize_timer.start(self._config.organize.interval_seconds * 1000)
            logger.info("[SubagentThread] organize 定时器已启动: interval=%ds", self._config.organize.interval_seconds)

    def _on_reply_completed(self, payload: dict):
        logger.info(
            "[SubagentThread] 收到 reply_completed: payload_keys=%s reply_len=%d mode=%s chat_id=%s",
            list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
            len(str((payload or {}).get('reply_text', '') or '')) if isinstance(payload, dict) else 0,
            (payload or {}).get('mode', '') if isinstance(payload, dict) else '',
            (payload or {}).get('chat_id', '') if isinstance(payload, dict) else '',
        )
        task = self._tasks.get("suggest")
        if not task:
            logger.info("[SubagentThread] 未找到 suggest 任务，跳过处理")
            return
        try:
            result = task.handle(payload)
            logger.info("[SubagentThread] suggest 处理完成: has_result=%s", bool(result))
            if result:
                self.suggestion_signal.emit(result)
                logger.info("[SubagentThread] 建议信号已发出")
        except Exception as e:
            logger.warning("[SubagentThread] 建议任务异常: %s", e)

    def _on_doc_convert_requested(self, payload: dict):
        task = self._tasks.get("organize")
        if not task:
            logger.info("[SubagentThread] 未找到 organize 任务，跳过文档转换")
            return
        try:
            result = task.handle(payload)
            if result:
                self.organize_signal.emit(result)
                logger.info("[SubagentThread] 文档转换结果已发出: %s", result.get("action", ""))
        except Exception as e:
            logger.warning("[SubagentThread] 文档转换任务异常: %s", e)

    def _on_organize_tick(self):
        task = self._tasks.get("organize")
        if not task:
            return
        try:
            result = task.handle()
            if result:
                self.organize_signal.emit(result)
                logger.info("[SubagentThread] 定时整理结果已发出: converted=%s", result.get("converted_count", 0))
        except Exception as e:
            logger.warning("[SubagentThread] 定时整理任务异常: %s", e)
