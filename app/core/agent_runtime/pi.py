"""Pi SDK sidecar adapter. Pi alone owns inference, tools loop, retry and compaction."""
from pathlib import Path
import threading
import time

from .contracts import AgentEvent
from .transport import JsonlProcess, ProtocolError
from .tools import normalize_tools
from .paths import node_executable, sidecar_path


SIDECAR = sidecar_path()


class PiRuntime:
    def __init__(self, command=None, *, approval_timeout=240, idle_timeout=600):
        self.command = list(command) if command else [node_executable() or "node", str(sidecar_path())]
        self.approval_timeout = approval_timeout
        self.idle_timeout = idle_timeout
        self._lock = threading.RLock()
        self._running = False
        self._cancelled = threading.Event()
        self._shutdown = threading.Event()
        self._pending_approvals = {}
        self._process = None
        self._identity = None
        self.session_path = ""

    @property
    def is_running(self):
        with self._lock:
            return self._running

    def approve(self, call_id, approved):
        with self._lock:
            slot = self._pending_approvals.get(call_id)
            if slot is None or slot["ready"].is_set() or self._cancelled.is_set():
                return False
            slot["approved"] = bool(approved)
            slot["ready"].set()
            return True

    def cancel(self):
        self._cancelled.set()
        with self._lock:
            for slot in self._pending_approvals.values():
                slot["ready"].set()
            process = self._process
        if process:
            try:
                process.send("abort")
            except ProtocolError:
                process.close()

    def close(self):
        self.shutdown()

    def shutdown(self, timeout=3.0):
        """Close our sidecar without waiting for an abort ACK from a stuck child."""
        self._shutdown.set()
        self._cancelled.set()
        with self._lock:
            for slot in self._pending_approvals.values():
                slot["ready"].set()
            process = self._process
        closed = process.close(timeout=timeout) if process else True
        with self._lock:
            if closed and self._process is process:
                self._process = None
                self._identity = None
        return closed

    def _start(self, request):
        root = Path(request.project_root).resolve(strict=True)
        directory = Path(request.session_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        session_path = request.session_path or (self.session_path if self.session_path and Path(self.session_path).is_file() else "")
        if session_path and request.session_pending and not Path(session_path).exists():
            session_path = ""
        if session_path:
            session_file = Path(session_path).resolve(strict=True)
            if not session_file.is_relative_to(directory):
                raise ProtocolError("Session file is outside this conversation's private session directory")
            session = {"mode": "open", "path": str(session_file)}
        else:
            session = {"mode": "create", "dir": str(directory)}
        identity = (str(root), str(directory), request.conversation_id, request.provider,
                    request.model, request.api, request.base_url, request.api_key,
                    request.system_prompt, repr(request.tools), request.reasoning, request.thinking_level,
                    request.context_window, request.max_tokens)
        if self._process and self._identity == identity:
            return
        if self._process:
            self._process.close()
        process = JsonlProcess(self.command, root, directory / "isolated-home")
        with self._lock:
            if self._cancelled.is_set() or self._shutdown.is_set():
                raise ProtocolError("Agent runtime is shutting down")
            self._process = process
            process.start()
        _, data = process.send(
            "init", provider=request.provider, model=request.model, api=request.api,
            apiKey=request.api_key, baseUrl=request.base_url, systemPrompt=request.system_prompt,
            reasoning=request.reasoning, thinkingLevel=request.thinking_level,
            contextWindow=request.context_window, maxTokens=request.max_tokens,
            cwd=str(root), agentDir=str(directory / "agent"), tools=normalize_tools(request.tools), session=session, toolTimeoutMs=300000,
        )
        self.session_path = str(data.get("sessionFile") or "")
        if self.session_path and not Path(self.session_path).resolve().is_relative_to(directory):
            raise ProtocolError("Agent returned an invalid session path")
        self._identity = identity

    def run(self, request, tool_handler):
        with self._lock:
            if self._running:
                raise RuntimeError("This agent session already has an active request")
            self._running = True
        def event(kind, **payload):
            return AgentEvent(kind, request.conversation_id, request.request_id, payload)
        text, thinking = "", ""
        messages = []
        last_assistant = {}
        observed = {}
        try:
            if self._cancelled.is_set() or self._shutdown.is_set():
                yield event("cancelled", session_path=self.session_path)
                return
            self._start(request)
            yield event("started", session_path=self.session_path, session_pending=not Path(self.session_path).is_file())
            if self._cancelled.is_set():
                yield event("cancelled", session_path=self.session_path)
                return
            if self._cancelled.is_set():
                accepted, command_id = {"disposition": "cancelled"}, None
            else:
                command_id, accepted = self._process.send(
                    "prompt", message=request.message, cancel_if=self._cancelled.is_set)
            if accepted.get("disposition") == "cancelled":
                yield event("cancelled", session_path=self.session_path)
                return
            if accepted.get("disposition") == "handled":
                yield event("completed", text="", thinking="", messages=[], session_path=self.session_path)
                return
            last_event = time.monotonic()
            while True:
                packet = self._process.next_event()
                if packet is None:
                    if time.monotonic() - last_event > self.idle_timeout:
                        raise ProtocolError("Agent run exceeded the inactivity timeout; resume explicitly")
                    continue
                packet_request = packet.get("requestId")
                if packet_request and packet_request != command_id:
                    continue
                last_event = time.monotonic()
                if packet.get("type") == "tool_call":
                    call_id, name = packet.get("callId", ""), packet.get("name", "")
                    arguments = packet.get("arguments")
                    if not call_id or not name or not isinstance(arguments, dict):
                        raise ProtocolError("Invalid tool request")
                    signature = (name, repr(sorted(arguments.items())))
                    if call_id in observed:
                        previous_signature, result = observed[call_id]
                        if previous_signature != signature:
                            raise ProtocolError("Tool call ID was reused with different arguments")
                    else:
                        slot = {"ready": threading.Event(), "approved": False}
                        with self._lock:
                            self._pending_approvals[call_id] = slot
                        yield event("tool_approval", call_id=call_id, name=name, arguments=arguments)
                        slot["ready"].wait(self.approval_timeout)
                        with self._lock:
                            self._pending_approvals.pop(call_id, None)
                        if not slot["approved"] or self._cancelled.is_set():
                            result = {"content": [{"type": "text", "text": "Tool execution denied or cancelled"}], "isError": True}
                        else:
                            yield event("tool_started", call_id=call_id, name=name)
                            try:
                                if self._cancelled.is_set():
                                    result = {"content": [{"type": "text", "text": "Tool cancelled before execution"}], "isError": True}
                                else:
                                    result = tool_handler(name, arguments, call_id)
                            except Exception:
                                result = {"content": [{"type": "text", "text": "Data-Bridge tool execution failed"}], "isError": True}
                        observed[call_id] = (signature, result)
                    yield event("tool_result", call_id=call_id, name=name, result=result)
                    # Aborted SDK tool promises are no longer waiting for a reply.
                    if not self._cancelled.is_set():
                        self._process.send("tool_result", requestId=command_id, callId=call_id,
                                           result={k: v for k, v in result.items() if k != "isError"},
                                           isError=bool(result.get("isError")))
                    continue
                if packet.get("type") == "tool_cancel":
                    continue
                if packet.get("type") != "event":
                    raise ProtocolError("Unknown sidecar event envelope")
                raw = packet.get("event") or {}
                kind = raw.get("type")
                if kind == "run_error":
                    raise ProtocolError(str(raw.get("error") or "Pi run failed"))
                if kind == "message_update":
                    delta = raw.get("assistantMessageEvent") or {}
                    if delta.get("type") == "text_delta":
                        part = str(delta.get("delta", ""))
                        text += part
                        yield event("text_delta", text=part, accumulated=text)
                    elif delta.get("type") == "thinking_delta":
                        part = str(delta.get("delta", ""))
                        thinking += part
                        yield event("thinking_delta", text=part, accumulated=thinking)
                elif kind == "message_end":
                    message = raw.get("message") or {}
                    messages.append(message)
                    if message.get("role") == "assistant":
                        last_assistant = message
                    yield event("message", message=message)
                elif kind == "agent_settled":
                    stop_reason = last_assistant.get("stopReason")
                    terminal = ("cancelled" if self._cancelled.is_set() or stop_reason == "aborted"
                                else "failed" if stop_reason == "error" else "completed")
                    yield event(terminal, error=(str(last_assistant.get("errorMessage") or "Provider failed")
                                                 if terminal == "failed" else ""),
                                text=text, thinking=thinking, messages=messages,
                                session_path=self.session_path)
                    return
                else:
                    yield event("diagnostic", event_type=kind)
        except Exception as error:
            if self._process:
                self._process.close()
                self._process = None
                self._identity = None
            # No request/profile dumps. Known transport messages contain no credentials.
            reason = str(error) if isinstance(error, (ProtocolError, FileNotFoundError)) else "Agent runtime failed"
            if request.api_key:
                reason = reason.replace(request.api_key, "[redacted]")
            yield event("cancelled" if self._cancelled.is_set() else "failed", error=reason,
                        session_path=self.session_path)
        finally:
            with self._lock:
                self._pending_approvals.clear()
                self._running = False
                if not self._shutdown.is_set():
                    self._cancelled.clear()
