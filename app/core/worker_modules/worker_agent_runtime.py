"""Agent-owned sessions: UI projection and controls, never the legacy tool loop."""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from app.core.agent_runtime import AgentEvent, AgentRequest, PiRuntime, SafeToolBridge
from app.core.agent_runtime.tools import normalize_tools
from app.core.api_mode_config import APIModeConfigManager
from app.core.project_context import ProjectContext
from app.core.model_capabilities import resolve_model_capability
from app.core.worker_modules.upstream_consumer import UpstreamConsumer
from app.core.worker_modules.upstream_events import UpstreamEvent


class WorkerAgentRuntimeBridge:
    def __init__(self, worker, runtime_factory=PiRuntime):
        self.worker = worker
        self.consumer = UpstreamConsumer(worker)
        self.runtime_factory = runtime_factory
        self._lock = threading.RLock()
        self._thread = None
        self._active = None
        self._pending = None

    @property
    def is_running(self):
        with self._lock:
            return bool(self._active)

    def options(self, **kwargs):
        from app.core.agent_runtime.registry import runtime_options
        payload = {"items": runtime_options(), **self._target(kwargs)}
        self.worker.agent_runtime_options_signal.emit(payload)
        return payload

    @staticmethod
    def _target(kwargs):
        client = kwargs.get("client_id")
        return {"target_client_id": client, "target_username": kwargs.get("username"),
                "target_verified_login": kwargs.get("verified_login") is True,
                "target_group": "admin" if kwargs.get("user_role") == "developer" else "user"} if client else {}

    def _error(self, message, target=None):
        self.worker.safe_emit_status(f"❌ {message}")
        if not self.is_running:
            self.worker._update_ai_state("idle")
            store = getattr(getattr(self.worker, "api_source", None), "conv_store", None)
            self.worker.api_round_state_signal.emit({"state": "failed", "message": message,
                                                       "conversation_id": getattr(store, "active_id", ""),
                                                       "request_id": "", **(target or {})})
        return {"ok": False, "error": message}

    def start(self, text, **kwargs):
        failure = lambda message: self._error(message, self._target(kwargs))
        if kwargs.get("client_id") is not None and kwargs.get("verified_login") is not True:
            return failure("Agent runtime requires a verified account login")
        worker = self.worker
        with self._lock:
            source = worker.api_source
            store = source.conv_store
            conv_id = store.active_id
            if self._active or getattr(worker, "_api_streaming", False):
                return failure("已有请求运行中，请先停止并等待结束")
            if store.get_runtime(conv_id) != "pi":
                return failure("此会话运行时未接入，不会自动回退到旧版")
            from app.core.agent_runtime.registry import runtime_options
            option = next(item for item in runtime_options() if item["id"] == "pi")
            if not option["available"]:
                return failure(option["reason"])
            cfg = APIModeConfigManager.load()
            _profile_key, profile, _usage = source._resolve_runtime_profile(conv_id, cfg)
            if profile.get("kind") == "browser_stateless":
                return failure("Pi 不支持 browser_stateless Profile，请选择 API Profile")
            provider = profile.get("provider", "openai_compatible")
            apis = {"openai_compatible": "openai-completions", "openai": "openai-completions", "api": "openai-completions", "mimo": "openai-completions", "gemini": "google-generative-ai"}
            if provider not in apis:
                return failure(f"Pi 尚未验证此 Provider: {provider}")
            if not profile.get("model"):
                return failure("请先为 Pi 会话选择模型")
            request_id = uuid.uuid4().hex
            project_root = (store.get_meta(conv_id) or {}).get("project_root")
            if not project_root:
                return failure("Pi 会话缺少项目边界，请新建会话")
            context = ProjectContext.get()
            try:
                context.acquire_runtime_lease(project_root, request_id)
            except RuntimeError as exc:
                return failure(str(exc))
            try:
                source.config_dict = cfg
                tools = normalize_tools(source._get_native_tool_definitions(worker.tool_router))
                session = store.get_runtime_session(conv_id)
                directory = str((store.storage_dir / "runtime_sessions" / conv_id).resolve())
                reasoning = profile.get("reasoning") or {}
                supported = resolve_model_capability(profile).get("reasoning", {}).get("supported", False)
                base_url = profile.get("base_url", "")
                if provider == "gemini":
                    if not base_url or base_url.rstrip("/") == "https://api.openai.com/v1":
                        base_url = "https://generativelanguage.googleapis.com/v1beta"
                    elif base_url.rstrip("/") == "https://generativelanguage.googleapis.com":
                        base_url = base_url.rstrip("/") + "/v1beta"
                host = urlsplit(base_url).hostname or ""
                pi_provider = "google" if provider == "gemini" else "xiaomi" if provider == "mimo" or host.endswith(".xiaomimimo.com") else "data-bridge"
                request = AgentRequest(
                    conversation_id=conv_id, request_id=request_id, project_root=project_root,
                    session_dir=directory, session_path=session.get("session_path", ""),
                    session_pending=session.get("pending", False) is True,
                    provider=pi_provider,
                    model=profile["model"], api=apis[provider], message=text,
                    api_key=profile.get("api_key", ""), base_url=base_url,
                    system_prompt=store.get_runtime_system_prompt(conv_id),
                    reasoning=supported,
                    thinking_level=reasoning.get("effort", "medium") if supported and reasoning.get("enabled") else "off",
                    context_window=cfg.get("conversation_defaults", {}).get("context", {}).get("max_window_tokens", 128000),
                    max_tokens=profile.get("max_output_tokens", 4096),
                    tools=tools,
                )
                runtime = self.runtime_factory()
                handler = SafeToolBridge(getattr(worker.tool_router, "runtime_executor", None), tools,
                                        project_root, conv_id, context.get_project_root)
                self._active = {"conversation_id": conv_id, "request_id": request_id, "runtime": runtime,
                                "client_id": kwargs.get("client_id"), "username": kwargs.get("username"),
                                "target": self._target(kwargs), "state": "starting", "project_root": project_root}
                self._pending = None
                worker._api_streaming = True
                worker._update_ai_state("busy")
                self._thread = threading.Thread(target=self._run, args=(request, runtime, handler), daemon=True,
                                                name=f"pi_{conv_id}")
                self._thread.start()
                return {"ok": True, "request_id": request_id, "conversation_id": conv_id}
            except Exception:
                self._active = None
                worker._api_streaming = False
                context.release_runtime_lease(request_id)
                return failure("Pi 启动失败，请检查运行时安装与 Profile 配置")

    def _run(self, request, runtime, handler):
        source = self.worker.api_source
        store = source.conv_store
        conv_id = request.conversation_id
        with self._lock:
            target = dict(self._active["target"])
        terminal = None
        text = thinking = ""
        try:
            projection = store.get_display_messages(conv_id)
            projection.append({"role": "user", "content": request.message, "id": f"{request.request_id}:user"})
            store.save_runtime_projection(conv_id, messages=projection)
            if len(projection) == 1:
                store.auto_title(conv_id, request.message)
            store.touch_last_message_at(conv_id)
            self.consumer.emit_messages(source.get_history_as_messages_for(conv_id))
            for event in runtime.run(request, handler):
                payload = event.payload
                if payload.get("session_path"):
                    store.save_runtime_projection(conv_id, session={"session_path": payload["session_path"], "project_root": request.project_root,
                                                                    "pending": not Path(payload["session_path"]).is_file()})
                if event.kind in {"completed", "cancelled", "failed"}:
                    terminal = event
                    continue
                if event.kind == "message":
                    raw = payload.get("message") or {}
                    # Pi emits the user input; the optimistic UI echo is already present.
                    if raw.get("role") != "user":
                        projected = self._project_message(raw, f"{request.request_id}:{len(projection)}")
                        if projected:
                            projection.append(projected)
                            store.save_runtime_projection(conv_id, messages=projection)
                            self.consumer.emit_messages(source.get_history_as_messages_for(conv_id))
                if event.kind == "text_delta":
                    text = payload.get("accumulated", text + payload.get("text", ""))
                elif event.kind == "thinking_delta":
                    thinking = payload.get("accumulated", thinking + payload.get("text", ""))
                self._emit(event, text, thinking, target=target)
            if terminal is None:
                raise RuntimeError("Agent omitted terminal event")
        except Exception:
            terminal = AgentEvent("failed", conv_id, request.request_id,
                                  {"error": "Pi 运行或历史保存失败；请检查会话存储后重试"})
        finally:
            # A turn owns its process. Resume the pinned session next turn rather than
            # keeping an unbounded cache of idle processes and in-memory credentials.
            try:
                runtime.close()
            finally:
                # Even storage failures and UI signal errors must release the lease.
                ProjectContext.get().release_runtime_lease(request.request_id)
                with self._lock:
                    self._pending = None
                    self._active = None
                    self.worker._api_streaming = False
            self.worker._update_ai_state("idle")
            if terminal:
                self._emit(terminal, text, thinking, target=target)
            try:
                self.consumer.emit_messages(source.get_history_as_messages_for(conv_id))
                self.consumer.emit_context_status(source.get_context_status(conv_id))
                self.worker.sessions_signal.emit(source.get_conversations())
            except Exception:
                self.worker.safe_emit_status("❌ Pi 历史显示刷新失败；请求已停止，项目锁已释放")

    @staticmethod
    def _project_message(raw, message_id):
        role = raw.get("role")
        if role not in {"assistant", "toolResult", "user"}:
            return None
        content = raw.get("content", [])
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        segments = []
        for block in blocks or []:
            kind = block.get("type")
            if kind in {"text", "thinking"}:
                value = str(block.get("text") if kind == "text" else block.get("thinking", ""))
                segments.append({"type": "thinking" if kind == "thinking" else "text", "content": value})
            elif kind == "toolCall":
                segments.append({"type": "text", "content": f"工具: {block.get('name', '')}\n{json.dumps(block.get('arguments', {}), ensure_ascii=False)}"})
        text = "\n".join(segment["content"] for segment in segments)
        if role == "toolResult":
            segments = [{"type": "tool_result", "tool_name": raw.get("toolName", ""), "tool_call_id": raw.get("toolCallId", ""),
                         "content": text, "success": not raw.get("isError", False)}]
        return {"role": "tool" if role == "toolResult" else role, "id": message_id, "content": text, "segments": segments}

    def _emit(self, event, text="", thinking="", target=None):
        payload = event.payload
        with self._lock:
            if target is None:
                target = dict(self._active.get("target", {})) if self._active else {}
        kind = event.kind
        up = UpstreamEvent(event={"started": "started", "completed": "completed", "failed": "failed", "cancelled": "failed"}.get(kind, "delta"),
                           conversation_id=event.conversation_id, request_id=event.request_id, stream_id=event.request_id,
                           text_delta=payload.get("text", "") if kind == "text_delta" else "",
                           thinking_delta=payload.get("text", "") if kind == "thinking_delta" else "",
                           accumulated_text=text, accumulated_thinking=thinking,
                           error_message=payload.get("error", ""), diagnostics={"runtime": "pi", "event_type": payload.get("event_type", kind)})
        if kind in {"started", "text_delta", "thinking_delta", "completed", "cancelled", "failed"}:
            self.consumer.emit_stream(up, extra={**target, **({"status": "cancelled"} if kind == "cancelled" else {})})
        if kind == "tool_approval":
            approval = {**payload, "runtime": "pi", "conversation_id": event.conversation_id, "request_id": event.request_id,
                        "project_root": (self._active or {}).get("project_root", ""), **target}
            with self._lock:
                self._pending = approval
            self.worker.agent_runtime_approval_signal.emit(approval)
        if kind in {"started", "tool_approval", "tool_started", "tool_result", "completed", "cancelled", "failed", "diagnostic"}:
            state = {"started": "streaming_initial_reply", "tool_approval": "awaiting_approval", "tool_started": "running_tools",
                     "tool_result": "waiting_followup", "completed": "finalized", "failed": "failed", "cancelled": "cancelled"}.get(kind, payload.get("event_type", "running"))
            with self._lock:
                if self._active and self._active["request_id"] == event.request_id:
                    self._active["state"] = state
                if kind in {"tool_started", "tool_result"}:
                    self._pending = None
            self.consumer.emit_round(up, state, payload.get("error", ""), extra=target)
        if kind == "failed":
            self.worker.safe_emit_status(f"❌ Pi: {payload.get('error', '运行失败')}")

    @staticmethod
    def _owns_request(active, kwargs):
        # A URL device_id is not an identity. Remote controls need the authenticated
        # account AND device; a local request cannot be claimed by a remote caller.
        return ((not active.get("client_id") or kwargs.get("verified_login") is True)
                and active.get("client_id") == kwargs.get("client_id")
                and active.get("username") == kwargs.get("username"))

    def cancel(self, conversation_id=None, request_id=None, **kwargs):
        with self._lock:
            active = self._active
            if not active or (conversation_id and conversation_id != active["conversation_id"]) or (request_id and request_id != active["request_id"]):
                return {"ok": False, "reason": "stale_request"}
            if not self._owns_request(active, kwargs):
                return {"ok": False, "reason": "request_owner_mismatch"}
            runtime = active["runtime"]
        # Do not hold the bridge lock while waiting for the sidecar's abort ACK.
        runtime.cancel()
        return {"ok": True, "state": "cancelling"}

    def approve(self, conversation_id, request_id, call_id, approved, **kwargs):
        with self._lock:
            active = self._active
            if not active or conversation_id != active["conversation_id"] or request_id != active["request_id"]:
                return {"ok": False, "reason": "stale_request"}
            if not self._owns_request(active, kwargs):
                return {"ok": False, "reason": "request_owner_mismatch"}
            if not isinstance(approved, bool):
                return {"ok": False, "reason": "approval_must_be_boolean"}
            ok = active["runtime"].approve(call_id, approved)
            if ok:
                self._pending = None
            return {"ok": ok}

    def state(self, **kwargs):
        with self._lock:
            active = self._active
            if not active:
                return {"running": False, "state": "idle", "conversation_id": "", "request_id": ""}
            if not self._owns_request(active, kwargs):
                return {"ok": False, "reason": "request_owner_mismatch"}
            snapshot = {"running": True, "state": active["state"],
                        "conversation_id": active["conversation_id"], "request_id": active["request_id"]}
            self.worker.api_round_state_signal.emit({**snapshot, **active["target"]})
            if self._pending:
                self.worker.agent_runtime_approval_signal.emit(self._pending)
            return snapshot
