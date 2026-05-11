import uuid

from app.core.logging.trace_context import get_current_trace
from app.core.logging import get_logger
from app.core.worker_modules.browser_stateless_profile import (
    ModelRequest,
    StatelessBrowserProfileAdapter,
)
from app.core.worker_modules.upstream_events import (
    make_completed_event,
    make_failed_event,
    make_started_event,
    make_structured_event,
)

logger = get_logger("app.core.worker_modules.worker_browser_stateless", side="worker")


class WorkerBrowserStatelessBridge:
    def __init__(self, worker):
        self.worker = worker

    def _emit_stream_event(self, event):
        payload = event.to_stream_payload()
        if payload.get("status") == "started":
            self.worker.api_stream_chunk_signal.emit(payload)
        elif payload.get("status") in ("completed", "error", "cancelled"):
            self.worker.api_stream_status_signal.emit(payload)
        else:
            self.worker.api_stream_chunk_signal.emit(payload)

    def _emit_transient_reply(self, api_source, active_conv_id: str, progress_info: dict, request_id: str):
        if not isinstance(progress_info, dict):
            return
        structured_message = progress_info.get("message")
        if not isinstance(structured_message, dict):
            return
        raw_text = str(progress_info.get("raw_text") or "").strip()
        segments = structured_message.get("segments") if isinstance(structured_message.get("segments"), list) else []
        if not raw_text and not segments:
            return

        content_key = str(structured_message.get("id", "")) + ":" + str(progress_info.get("raw_len", "")) + ":" + raw_text[-120:]
        if getattr(self, "_last_transient_key", "") == content_key:
            return
        self._last_transient_key = content_key

        event = make_structured_event(
            conversation_id=active_conv_id,
            request_id=request_id,
            profile_key=getattr(self, "_active_profile_key", ""),
            stream_id=getattr(self, "_active_stream_id", ""),
            accumulated_text=raw_text,
            segments=segments,
            raw_message=structured_message,
            diagnostics={"raw_len": progress_info.get("raw_len", 0)},
        )
        self._emit_stream_event(event)

        base_msgs = api_source.get_history_as_messages_for(active_conv_id)
        transient_msg = api_source.build_message_for_signal(
            role="assistant",
            content=raw_text,
            index=len(base_msgs),
            kind="text",
            meta={
                "profile_kind": "browser_stateless",
                "request_id": request_id,
                "transient": True,
            },
            raw_content=raw_text,
            segments=segments,
        )
        transient_msg["id"] = f"{active_conv_id}:browser_stateless_transient"
        transient_msg["conversation_id"] = active_conv_id
        transient_msg["status"] = "streaming"
        self.worker.messages_signal.emit([*base_msgs, transient_msg])
        logger.debug(
            "[BrowserStatelessBridge] transient reply emitted | conv_id=%s request_id=%s segments=%d raw_len=%d",
            active_conv_id,
            request_id,
            len(segments or []),
            len(raw_text),
        )

    def handle_send(self, text: str, profile: dict):
        worker = self.worker
        api_source = worker.api_source
        active_conv_id = (
            api_source.conv_store.active_id
            if api_source and api_source.conv_store and api_source.conv_store.active_id
            else "api_default"
        )
        profile_key = str(profile.get("_profile_key") or profile.get("key") or profile.get("name") or profile.get("provider") or "browser_web_primary")
        conversation_url = str(profile.get("conversation_url") or "").strip()
        conversation_name = str(profile.get("conversation_name") or "").strip()
        legacy_browser_profile = str(profile.get("browser_profile") or "").strip()
        if not conversation_name and legacy_browser_profile and legacy_browser_profile != "current_debug_session":
            conversation_name = legacy_browser_profile
        logger.info(
            "[BrowserStatelessBridge] handle_send | conv_id=%s profile_key=%s kind=%s provider=%s conversation_url=%s conversation_name=%s text_len=%d",
            active_conv_id,
            profile_key,
            profile.get("kind"),
            profile.get("provider"),
            conversation_url or "(empty)",
            conversation_name or "(empty)",
            len(text or ""),
        )
        if not conversation_url and not conversation_name:
            logger.warning(
                "[BrowserStatelessBridge] selected browser Profile has empty conversation target | conv_id=%s profile=%s",
                active_conv_id,
                profile,
            )
            worker.safe_emit_status("⚠️ 当前浏览器 Profile 没有配置目标对话名称或 URL")
        stream_id = f"browser_stateless_{uuid.uuid4().hex[:12]}"
        self._active_stream_id = stream_id
        self._active_profile_key = profile_key
        started_event = make_started_event(
            conversation_id=active_conv_id,
            request_id="",
            profile_key=profile_key,
            stream_id=stream_id,
            diagnostics={
                "conversation_url": conversation_url,
                "conversation_name": conversation_name,
            },
        )
        self._emit_stream_event(started_event)
        round_payload = started_event.to_round_payload(
            state="browser_stateless",
            message="正在操作 WebAI 网页...",
        )
        round_payload.update({
            "conversation_url": conversation_url,
            "conversation_name": conversation_name,
            "trace_id": (get_current_trace().trace_id if get_current_trace() else ""),
            "round_id": (get_current_trace().round_id if get_current_trace() else ""),
        })
        worker.api_round_state_signal.emit(round_payload)

        api_source.append_user_message(text, conversation_id=active_conv_id)
        prepared_context = api_source.prepare_browser_stateless_request_context(conversation_id=active_conv_id)
        request = ModelRequest(
            task_type="chat",
            messages=prepared_context.get("messages", []),
            context_bundle={
                "conversation_id": prepared_context.get("conversation_id") or active_conv_id,
                "profile": {
                    "kind": profile.get("kind"),
                    "provider": profile.get("provider"),
                    "role": profile.get("role"),
                },
                "context_status": prepared_context.get("context_status", {}),
            },
        )
        self._last_transient_key = ""

        def on_browser_progress(progress_info):
            self._emit_transient_reply(api_source, active_conv_id, progress_info, request.request_id)

        adapter = StatelessBrowserProfileAdapter(
            connector=worker.connector,
            profile_id=profile_key,
            conversation_url=conversation_url,
            conversation_name=conversation_name,
            timeout_seconds=int(profile.get("timeout_seconds", profile.get("timeout", 180)) or 180),
            progress_callback=on_browser_progress,
        )
        response = adapter.invoke(request)
        logger.info(
            "[BrowserStatelessBridge] response | conv_id=%s request_id=%s finish=%s error=%s states=%s diagnostics=%s",
            active_conv_id,
            response.request_id,
            response.finish_reason,
            response.diagnostics.get("error_code", ""),
            response.diagnostics.get("states"),
            response.diagnostics,
        )
        if response.finish_reason == "succeeded":
            assistant_text = response.raw_text
            structured_message = response.structured_message if isinstance(response.structured_message, dict) else {}
            assistant_segments = structured_message.get("segments") if isinstance(structured_message.get("segments"), list) else None
            assistant_raw_content = assistant_text
        else:
            assistant_segments = None
            assistant_raw_content = ""
            error_code = response.diagnostics.get("error_code", "unknown_error")
            if error_code in ("conversation_url_required", "conversation_target_required"):
                assistant_text = (
                    "浏览器无上下文 Profile 调用失败: 当前浏览器 Profile 没有保存目标对话名称或 URL。\n\n"
                    "请到设置页打开该浏览器 Profile，填写“目标对话名称”后再试。"
                )
            else:
                assistant_text = f"浏览器无上下文 Profile 调用失败: {error_code}"

        api_source.append_assistant_message(
            assistant_text,
            segments=assistant_segments,
            conversation_id=active_conv_id,
            raw_content=assistant_raw_content,
            meta={
                "profile_kind": "browser_stateless",
                "request_id": response.request_id,
                "diagnostics": response.diagnostics,
            },
        )
        msgs = api_source.get_history_as_messages_for(active_conv_id)
        terminal_event_factory = make_completed_event if response.finish_reason == "succeeded" else make_failed_event
        terminal_event = terminal_event_factory(
            conversation_id=active_conv_id,
            request_id=response.request_id,
            profile_key=profile_key,
            stream_id=stream_id,
            accumulated_text=assistant_text if response.finish_reason == "succeeded" else "",
            segments=assistant_segments or [],
            raw_message=response.structured_message if isinstance(response.structured_message, dict) else None,
            diagnostics=response.diagnostics,
            error_message="" if response.finish_reason == "succeeded" else response.diagnostics.get("error_code", "unknown_error"),
        )
        self._emit_stream_event(terminal_event)
        worker.messages_signal.emit(msgs if msgs else [])
        worker.context_status_signal.emit(api_source.get_context_status(conversation_id=active_conv_id))
        final_payload = terminal_event.to_round_payload(state="finalized")
        final_payload.update({
            "profile_kind": "browser_stateless",
            "conversation_url": conversation_url,
            "conversation_name": conversation_name,
            "trace_id": (get_current_trace().trace_id if get_current_trace() else ""),
            "round_id": (get_current_trace().round_id if get_current_trace() else ""),
        })
        worker.api_round_state_signal.emit(final_payload)
        if response.finish_reason == "succeeded":
            worker.safe_emit_status("✅ 无上下文浏览器 Profile 调用完成")
        else:
            worker.safe_emit_status("❌ 无上下文浏览器 Profile 调用失败")
        return response
