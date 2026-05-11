import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.browser_stateless_profile", side="worker")


@dataclass
class ModelRequest:
    request_id: str = ""
    task_type: str = "general"
    messages: list[dict[str, Any]] = field(default_factory=list)
    context_bundle: dict[str, Any] = field(default_factory=dict)
    output_schema: Optional[dict[str, Any]] = None
    priority: int = 0


@dataclass
class ModelResponse:
    request_id: str
    profile_id: str
    raw_text: str
    structured_message: Optional[dict[str, Any]] = None
    parsed: Optional[dict[str, Any]] = None
    usage: Optional[dict[str, Any]] = None
    finish_reason: str = "succeeded"
    diagnostics: dict[str, Any] = field(default_factory=dict)


class ContextCompiler:
    def compile(self, request: ModelRequest) -> str:
        context_bundle = request.context_bundle if isinstance(request.context_bundle, dict) else {}
        profile = context_bundle.get("profile", {}) if isinstance(context_bundle.get("profile"), dict) else {}
        usage = context_bundle.get("context_status", {}) if isinstance(context_bundle.get("context_status"), dict) else {}

        sections = [
            "你是 Data-Bridge 的近似无上下文浏览器推理后端。",
            "本次请求只能依赖下面输入完成任务，不要依赖任何网页历史对话。",
            "",
            "<request_meta>",
            f"task_type: {request.task_type}",
            f"conversation_id: {context_bundle.get('conversation_id', '')}",
            f"profile_kind: {profile.get('kind', '')}",
            f"profile_provider: {profile.get('provider', '')}",
            f"context_utilization: {usage.get('utilization', '')}%",
            f"context_tokens: {usage.get('total_used', '')}/{usage.get('total_budget', '')}",
            "</request_meta>",
            "",
            "<compiled_context>",
            self._format_messages(request.messages),
            "</compiled_context>",
        ]
        if request.output_schema:
            sections.extend([
                "",
                "<output_contract>",
                "本任务需要结构化结果时，请把 JSON 放入 ```json fenced block，并回显完全相同的 request_id。",
                json.dumps(request.output_schema, ensure_ascii=False, indent=2),
                "</output_contract>",
            ])
        else:
            sections.extend([
                "",
                "<output_contract>",
                "请用自然语言或 Markdown 回复。需要代码时使用 fenced code block。",
                "不要为了迎合系统而强行输出 JSON；只有任务明确需要结构化数据时才输出 JSON。",
                "请在回复中尽量回显 request_id，并给出本次任务的最终结果。",
                "</output_contract>",
            ])
        return "\n".join(sections)

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for i, msg in enumerate(messages or [], 1):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "user").strip() or "user"
            content = msg.get("content", "")
            if isinstance(content, (dict, list)):
                content_text = json.dumps(content, ensure_ascii=False, indent=2)
            else:
                content_text = str(content or "").strip()
            if not content_text:
                continue
            lines.extend([
                f"### Message {i} · {role}",
                "",
                content_text,
                "",
            ])
        return "\n".join(lines).strip() or "(empty)"


class BrowserPromptEnvelope:
    def build(self, request: ModelRequest, compiled_prompt: str) -> str:
        request_id = request.request_id or f"req_{uuid.uuid4().hex[:12]}"
        request.request_id = request_id
        return "\n".join([
            "[Data-Bridge Stateless Browser Request]",
            f"request_id: {request_id}",
            f"task_type: {request.task_type}",
            "",
            compiled_prompt,
            "",
            "<hard_requirements>",
            f"必须回显 request_id: {request_id}",
            "不要引用或延续网页历史消息。",
            "</hard_requirements>",
        ])


class ResponseNormalizer:
    def normalize(
        self,
        request: ModelRequest,
        profile_id: str,
        raw_text: str,
        diagnostics: dict[str, Any],
        structured_message: Optional[dict[str, Any]] = None,
    ) -> ModelResponse:
        parsed = self._extract_json(raw_text)
        return ModelResponse(
            request_id=request.request_id,
            profile_id=profile_id,
            raw_text=raw_text,
            structured_message=structured_message,
            parsed=parsed,
            usage=None,
            finish_reason="succeeded",
            diagnostics=diagnostics,
        )

    def _extract_json(self, text: str) -> Optional[dict[str, Any]]:
        text = str(text or "").strip()
        if not text:
            return None
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        candidates = [fenced.group(1)] if fenced else []
        candidates.append(text)
        obj_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if obj_match:
            candidates.append(obj_match.group(1))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None


class StatelessBrowserProfileAdapter:
    def __init__(
        self,
        connector,
        profile_id: str = "browser_web_primary",
        conversation_url: str = "",
        conversation_name: str = "",
        timeout_seconds: int = 180,
        compiler: Optional[ContextCompiler] = None,
        envelope: Optional[BrowserPromptEnvelope] = None,
        normalizer: Optional[ResponseNormalizer] = None,
        progress_callback=None,
    ):
        self.connector = connector
        self.profile_id = profile_id
        self.conversation_url = str(conversation_url or "").strip()
        self.conversation_name = str(conversation_name or "").strip()
        self.timeout_seconds = int(timeout_seconds or 180)
        self.compiler = compiler or ContextCompiler()
        self.envelope = envelope or BrowserPromptEnvelope()
        self.normalizer = normalizer or ResponseNormalizer()
        self.progress_callback = progress_callback
        self._lock = threading.Lock()

    def invoke(self, request: ModelRequest) -> ModelResponse:
        started = time.time()
        request.request_id = request.request_id or f"req_{uuid.uuid4().hex[:12]}"
        diagnostics: dict[str, Any] = {
            "states": ["queued"],
            "profile_id": self.profile_id,
            "conversation_url": self.conversation_url,
            "conversation_name": self.conversation_name,
        }
        with self._lock:
            diagnostics["states"].append("acquiring_lock")
            compiled = self.compiler.compile(request)
            prompt = self.envelope.build(request, compiled)
            diagnostics["prompt_chars"] = len(prompt)
            logger.info(
                "[BrowserStateless] invoke start | request_id=%s profile_id=%s conversation_url=%s conversation_name=%s prompt_chars=%d timeout=%s",
                request.request_id,
                self.profile_id,
                self.conversation_url or "(empty)",
                self.conversation_name or "(empty)",
                len(prompt),
                self.timeout_seconds,
            )

            if not self.conversation_url and not self.conversation_name:
                diagnostics["states"].append("failed")
                diagnostics["error_code"] = "conversation_target_required"
                diagnostics["detail"] = {
                    "error": "browser_stateless Profile 缺少目标对话 URL 或名称，已停止以避免清空当前浏览器对话",
                }
                logger.warning(
                    "[BrowserStateless] missing conversation target, abort before clear | request_id=%s profile_id=%s",
                    request.request_id,
                    self.profile_id,
                )
                return ModelResponse(
                    request_id=request.request_id,
                    profile_id=self.profile_id,
                    raw_text="",
                    finish_reason="failed",
                    diagnostics=diagnostics,
                )

            if self.conversation_url or self.conversation_name:
                diagnostics["states"].append("switching_conversation")
                logger.info(
                    "[BrowserStateless] switching conversation | request_id=%s url=%s name=%s",
                    request.request_id,
                    self.conversation_url or "(empty)",
                    self.conversation_name or "(empty)",
                )
                switch_ok, switch_info = self.connector.open_conversation_target(
                    conversation_url=self.conversation_url,
                    conversation_name=self.conversation_name,
                    timeout=min(20, self.timeout_seconds),
                )
                diagnostics["switch_conversation"] = switch_info
                logger.info(
                    "[BrowserStateless] switch result | request_id=%s ok=%s info=%s",
                    request.request_id,
                    switch_ok,
                    switch_info,
                )
                if not switch_ok:
                    diagnostics["states"].append("failed")
                    diagnostics.update(switch_info if isinstance(switch_info, dict) else {})
                    diagnostics.setdefault("error_code", "conversation_switch_failed")
                    return ModelResponse(
                        request_id=request.request_id,
                        profile_id=self.profile_id,
                        raw_text="",
                        finish_reason="failed",
                        diagnostics=diagnostics,
                    )

            diagnostics["states"].append("resetting")
            logger.info("[BrowserStateless] clearing target conversation | request_id=%s", request.request_id)
            reset_ok, reset_info = self.connector.clear_conversation(timeout=min(15, self.timeout_seconds))
            diagnostics["reset"] = reset_info
            logger.info(
                "[BrowserStateless] clear result | request_id=%s ok=%s info=%s",
                request.request_id,
                reset_ok,
                reset_info,
            )
            if not reset_ok:
                return self._failed(request, "reset_failed", diagnostics, reset_info)

            diagnostics["states"].append("sending")
            logger.info("[BrowserStateless] sending prompt | request_id=%s prompt_chars=%d", request.request_id, len(prompt))
            send_ok, send_msg = self.connector.send_message("div.aa-chat-input textarea", prompt)
            diagnostics["send"] = {"ok": send_ok, "message": send_msg}
            logger.info(
                "[BrowserStateless] send result | request_id=%s ok=%s message=%s",
                request.request_id,
                send_ok,
                send_msg,
            )
            if not send_ok:
                return self._failed(request, "send_failed", diagnostics, {"error": send_msg})

            diagnostics["states"].append("waiting")
            logger.info("[BrowserStateless] waiting response | request_id=%s timeout=%s", request.request_id, self.timeout_seconds)
            try:
                wait_ok, wait_info = self.connector.wait_until_idle(
                    timeout=self.timeout_seconds,
                    progress_callback=self.progress_callback,
                )
            except TypeError:
                wait_ok, wait_info = self.connector.wait_until_idle(timeout=self.timeout_seconds)
            diagnostics["wait"] = wait_info
            logger.info(
                "[BrowserStateless] wait result | request_id=%s ok=%s info=%s",
                request.request_id,
                wait_ok,
                wait_info,
            )
            if not wait_ok:
                return self._failed(request, "response_timeout", diagnostics, wait_info)

            diagnostics["states"].append("extracting")
            logger.info("[BrowserStateless] extracting latest AI response via browser parser | request_id=%s", request.request_id)
            extract_ok, extract_info = self.connector.extract_latest_ai_response(request_id=request.request_id)
            diagnostics["extract"] = {k: v for k, v in extract_info.items() if k != "raw_text"}
            logger.info(
                "[BrowserStateless] extract result | request_id=%s ok=%s info=%s",
                request.request_id,
                extract_ok,
                diagnostics["extract"],
            )
            if not extract_ok:
                return self._failed(request, extract_info.get("error_code", "extract_failed"), diagnostics, extract_info)

            diagnostics["states"].append("normalizing")
            diagnostics["elapsed_ms"] = int((time.time() - started) * 1000)
            response = self.normalizer.normalize(
                request=request,
                profile_id=self.profile_id,
                raw_text=extract_info.get("raw_text", ""),
                diagnostics=diagnostics,
                structured_message=extract_info.get("message") if isinstance(extract_info.get("message"), dict) else None,
            )
            response.diagnostics["states"].append("succeeded")
            logger.info("[BrowserStateless] invoke succeeded | request_id=%s elapsed_ms=%s", request.request_id, diagnostics["elapsed_ms"])
            return response

    def _failed(self, request: ModelRequest, reason: str, diagnostics: dict[str, Any], detail: Any) -> ModelResponse:
        diagnostics["states"].append("failed")
        diagnostics["error_code"] = reason
        diagnostics["detail"] = detail
        logger.warning(
            "[BrowserStateless] invoke failed | request_id=%s reason=%s states=%s detail=%s",
            request.request_id,
            reason,
            diagnostics.get("states"),
            detail,
        )
        return ModelResponse(
            request_id=request.request_id,
            profile_id=self.profile_id,
            raw_text="",
            parsed=None,
            usage=None,
            finish_reason="failed",
            diagnostics=diagnostics,
        )
