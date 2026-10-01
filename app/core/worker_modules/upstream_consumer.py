from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.upstream_consumer", side="worker")


class UpstreamConsumer:
    """Translate unified upstream events into current worker/UI signals.

    This is intentionally thin. It keeps today's external signals stable while
    moving source-specific emission logic out of browser/API bridges.
    """

    def __init__(self, worker):
        self.worker = worker

    def emit_stream(self, event, extra: dict | None = None):
        payload = event.to_stream_payload()
        if extra:
            payload.update(extra)
        status = payload.get("status")
        if status == "started":
            self.worker.api_stream_chunk_signal.emit(payload)
        elif status in ("completed", "error", "cancelled"):
            self.worker.api_stream_status_signal.emit(payload)
        else:
            self.worker.api_stream_chunk_signal.emit(payload)
        return payload

    def emit_round(self, event, state: str, message: str = "", extra: dict | None = None):
        payload = event.to_round_payload(state=state, message=message)
        if extra:
            payload.update(extra)
        self.worker.api_round_state_signal.emit(payload)
        return payload

    def emit_messages(self, messages):
        self.worker.messages_signal.emit(messages if messages else [])

    def emit_context_status(self, context_status):
        self.worker.context_status_signal.emit(context_status or {})

    def emit_transient_reply(self, api_source, event):
        """Show a browser transient structured reply without persisting it."""
        raw_text = str(event.accumulated_text or "").strip()
        segments = list(event.segments or [])
        if not raw_text and not segments:
            return False

        self.emit_stream(event)

        base_msgs = api_source.get_history_as_messages_for(event.conversation_id)
        transient_msg = api_source.build_message_for_signal(
            role="assistant",
            content=raw_text,
            index=len(base_msgs),
            kind="text",
            meta={
                "profile_kind": "browser_stateless",
                "request_id": event.request_id,
                "transient": True,
            },
            raw_content=raw_text,
            segments=segments,
        )
        transient_msg["id"] = f"{event.conversation_id}:browser_stateless_transient"
        transient_msg["conversation_id"] = event.conversation_id
        transient_msg["status"] = "streaming"
        self.emit_messages([*base_msgs, transient_msg])
        logger.debug(
            "[UpstreamConsumer] transient reply emitted | conv_id=%s request_id=%s segments=%d raw_len=%d",
            event.conversation_id,
            event.request_id,
            len(segments),
            len(raw_text),
        )
        return True
