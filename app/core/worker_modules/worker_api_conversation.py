from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.worker_api_conversation", side="worker")


class WorkerApiConversationBridge:
    """API 对话级操作桥接。

    WorkerThread 只负责暴露薄入口；具体刷新、状态广播和提示放在这里，
    避免对话配置能力继续膨胀主 Worker。
    """

    def __init__(self, worker):
        self.worker = worker

    def set_model_usage(self, conv_id: str, usage=None) -> bool:
        worker = self.worker
        if not worker.api_source:
            worker._init_api_source()
        if not worker.api_source:
            return False

        ok = worker.api_source.set_conversation_model_usage(conv_id, usage)
        convs = worker.api_source.get_conversations()
        worker.sessions_signal.emit(convs)

        try:
            status = worker.api_source.get_context_status(conversation_id=conv_id)
            worker.context_status_signal.emit(status)
        except Exception as exc:
            logger.warning("刷新 API 对话状态失败: %s", exc)
            worker.context_status_signal.emit({})

        if ok:
            if isinstance(usage, dict):
                worker.safe_emit_status(f"✅ 本对话模型来源已更新: {usage.get('type')} / {usage.get('ref')}")
            else:
                worker.safe_emit_status("✅ 本对话已恢复使用全局默认模型来源")
        else:
            worker.safe_emit_status("⚠️ 本对话模型来源更新失败")
        return bool(ok)
