from PySide6.QtCore import QObject, Signal

from app.core.subagent.subagent_config import SubagentConfig
from app.core.subagent.subagent_event_bus import SubagentEventBus
from app.core.subagent.subagent_thread import SubagentThread
from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.worker_subagent_bridge", side="worker")


class WorkerSubagentBridge(QObject):
    subagent_suggestion_signal = Signal(object)
    subagent_organize_signal = Signal(object)
    daemon_suggestion_signal = Signal(object)
    daemon_organize_signal = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = SubagentConfig.get()
        logger.info(
            "[SubagentBridge] 初始化: enabled=%s suggest_enabled=%s api_key=%s provider=%s",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            bool(getattr(self._config, 'api_key', '') or ''),
            getattr(self._config, 'provider', ''),
        )
        self.event_bus = SubagentEventBus()
        self.subagent_thread = SubagentThread(self.event_bus, parent=self)
        self.subagent_thread.suggestion_signal.connect(self._on_suggestion)
        self.subagent_thread.organize_signal.connect(self._on_organize)
        logger.info("[SubagentBridge] Subagent 线程对象已创建: running=%s", self.subagent_thread.isRunning())

    def start(self):
        logger.info(
            "[SubagentBridge] start 请求: enabled=%s suggest_enabled=%s running=%s",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            self.subagent_thread.isRunning(),
        )
        if not self._config.enabled:
            logger.info("[SubagentBridge] 已禁用，不启动")
            return
        if not self._config.api_key:
            logger.warning("[SubagentBridge] API key 未配置，不启动Subagent 线程")
            return
        self.subagent_thread.start()
        logger.info("[SubagentBridge] 已启动: running=%s", self.subagent_thread.isRunning())

    def stop(self):
        logger.info("[SubagentBridge] stop 请求: running=%s", self.subagent_thread.isRunning())
        if self.subagent_thread.isRunning():
            self.subagent_thread.stop()
            logger.info("[SubagentBridge] 已停止")

    def reload(self):
        logger.info("[SubagentBridge] 热重载配置...")
        self.stop()
        self._config = SubagentConfig.reload()
        self.start()
        logger.info("[SubagentBridge] 配置已热重载")

    def on_reply_completed(self, reply_text: str, mode: str, chat_id: str = "", recent_context: str = ""):
        logger.info(
            "[SubagentBridge] 收到回复完成: enabled=%s suggest_enabled=%s running=%s mode=%s chat_id=%s reply_len=%d recent_context_len=%d",
            self._config.enabled,
            getattr(self._config, 'suggest', None) and self._config.suggest.enabled,
            self.subagent_thread.isRunning(),
            mode,
            chat_id,
            len(reply_text or ""),
            len(recent_context or ""),
        )
        if not self._config.enabled or not self._config.suggest.enabled:
            logger.info("[SubagentBridge] 跳过建议: Subagent或建议功能已关闭")
            return
        if not self.subagent_thread.isRunning():
            logger.info("[SubagentBridge] 跳过建议: Subagent 线程未运行")
            return
        self.event_bus.emit(SubagentEventBus.EVENT_REPLY_COMPLETED, {
            "reply_text": reply_text,
            "mode": mode,
            "chat_id": chat_id,
            "recent_context": recent_context,
        })
        logger.info("[SubagentBridge] reply_completed 已转发到事件总线")

    def _on_suggestion(self, suggestions):
        try:
            count = len(suggestions or []) if isinstance(suggestions, (list, tuple)) else 1
        except Exception:
            count = -1
        logger.info("[SubagentBridge] 收到建议结果: count=%s", count)
        self.subagent_suggestion_signal.emit(suggestions)
        self.daemon_suggestion_signal.emit(suggestions)

    def request_doc_convert(self, filename: str):
        if not self._config.enabled or not self._config.organize.enabled:
            logger.info("[SubagentBridge] 跳过文档转换: Subagent或整理功能已关闭")
            return
        if not self.subagent_thread.isRunning():
            logger.info("[SubagentBridge] 跳过文档转换: Subagent 线程未运行")
            return
        self.event_bus.emit(SubagentEventBus.EVENT_DOC_CONVERT_REQUESTED, {
            "trigger": "convert",
            "filename": filename,
        })
        logger.info("[SubagentBridge] 文档转换请求已发送: %s", filename)

    def _on_organize(self, result):
        logger.info("[SubagentBridge] 收到资料整理结果: action=%s", result.get("action", "") if isinstance(result, dict) else "")
        self.subagent_organize_signal.emit(result)
        self.daemon_organize_signal.emit(result)

