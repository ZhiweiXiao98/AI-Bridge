# filename: app/core/worker_modules/worker_browser_tool_input.py
from __future__ import annotations

import json

from app.core.logging import get_logger

logger = get_logger("app.core.worker.browser_tool_input", side="worker")


class WorkerBrowserToolInputBridge:
    """Extract and classify browser-mode tool-router input."""

    def __init__(self, worker):
        self.worker = worker

    def extract_browser_tool_input(self):
        """Prefer the last structured AI message; use full text only as fallback."""
        worker = self.worker
        try:
            raw_msgs, _ = worker.connector.get_chat_content(worker.target_class, auto_wake=False)
            raw_msgs = worker.file_service.process_images(raw_msgs)
        except Exception as exc:
            logger.warning("Browser tool structured message fetch failed: %s", exc)
            raw_msgs = []

        if raw_msgs:
            try:
                worker.last_messages_snapshot = raw_msgs
            except Exception:
                pass

            last_ai_msg = None
            for msg in reversed(raw_msgs):
                if str(msg.get("role", "")).lower() == "ai":
                    last_ai_msg = msg
                    break

            if last_ai_msg:
                segments = list(last_ai_msg.get("segments") or [])
                structured_summary = self._build_structured_summary(segments)
                logger.info(
                    "[工具路由] 浏览器模式命中结构化 AI 消息 | segments=%s | codes=%s | message_id=%s",
                    len(segments),
                    sum(1 for seg in segments if isinstance(seg, dict) and seg.get("type") == "code"),
                    last_ai_msg.get("id", ""),
                )
                return {
                    "messages": [
                        {
                            "role": "AI",
                            "id": last_ai_msg.get("id", ""),
                            "segments": segments,
                        }
                    ],
                    "fingerprint_source": json.dumps(
                        structured_summary,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "fallback_text": worker.connector.check_last_ai_message_for_tool() or "",
                    "used_structured": True,
                    "last_ai_msg_id": last_ai_msg.get("id", ""),
                }

        fallback_text = worker.connector.check_last_ai_message_for_tool() or ""
        if fallback_text:
            logger.warning("[工具路由] 浏览器模式未获取到结构化 AI 消息，回退到全文文本识别")
        return {
            "messages": [
                {
                    "role": "AI",
                    "index": 9999,
                    "segments": [{"type": "text", "content": fallback_text}],
                }
            ]
            if fallback_text
            else [],
            "fingerprint_source": fallback_text,
            "fallback_text": fallback_text,
            "used_structured": False,
            "last_ai_msg_id": "",
        }

    def _build_structured_summary(self, segments):
        structured_summary = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            seg_type = seg.get("type")
            if seg_type == "code":
                structured_summary.append(
                    {
                        "type": "code",
                        "content": seg.get("content", ""),
                        "language": seg.get("language"),
                        "message_id": seg.get("message_id"),
                        "block_index": seg.get("block_index"),
                        "code_fingerprint": seg.get("code_fingerprint"),
                        "block_key": seg.get("block_key"),
                    }
                )
            elif seg_type in ("text", "tool_call", "tool_result", "thinking"):
                structured_summary.append(
                    {
                        "type": seg_type,
                        "content": seg.get("content", ""),
                    }
                )
        return structured_summary

    def looks_like_browser_tool_feedback_text(self, text: str) -> bool:
        text = str(text or "").strip()
        if not text:
            return False
        normalized = text.lstrip()
        return (
            normalized.startswith("🔧 [工具执行结果]")
            or normalized.startswith("[工具执行结果]")
            or normalized.startswith("工具执行结果")
        )

    def classify_browser_tool_input(
        self,
        candidate_messages,
        fallback_text: str = "",
        used_structured: bool = False,
    ) -> str:
        fallback_text = str(fallback_text or "")
        messages = list(candidate_messages or [])
        if not messages:
            return "none"

        last_msg = messages[-1] if messages else {}
        segments = list(last_msg.get("segments") or []) if isinstance(last_msg, dict) else []

        if used_structured and segments:
            return self._classify_structured_segments(segments)

        if self.looks_like_browser_tool_feedback_text(fallback_text):
            return "tool_feedback"
        if fallback_text.strip():
            return "tool_call"
        return "none"

    def _classify_structured_segments(self, segments) -> str:
        has_tool_result = any(
            str(seg.get("type", "") or "").strip().lower() == "tool_result"
            for seg in segments
            if isinstance(seg, dict)
        )
        if has_tool_result:
            logger.info("[工具分类] 结果=工具回显 | 段数=%s | 含 tool_result 段", len(segments))
            return "tool_feedback"

        seg_details = []
        text_chunks = []
        has_tool_call = False
        has_tool_call_code = False
        has_code = False

        for index, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type", "") or "").strip().lower()
            language = str(seg.get("language", "") or "").strip().lower()
            is_last = index == len(segments) - 1
            block_key = str(seg.get("block_key", "") or "").strip()[:20] if seg_type == "code" else ""
            content_len = len(str(seg.get("content", "") or ""))
            seg_details.append(
                f"{seg_type}:{language}:len={content_len}:last={is_last}"
                f'{":bk=" + block_key if block_key else ""}'
            )

            if seg_type == "tool_call":
                has_tool_call = True
            elif seg_type == "code":
                has_code = True
                if language == "tool_call":
                    has_tool_call_code = True
            elif seg_type == "text":
                text_chunks.append(str(seg.get("content", "") or ""))

        merged_text = "\n".join([chunk for chunk in text_chunks if chunk.strip()])
        if self.looks_like_browser_tool_feedback_text(merged_text):
            logger.info("[工具分类] 结果=工具回显 | 段数=%s | 文本匹配反馈模式", len(segments))
            return "tool_feedback"

        if has_tool_call or has_tool_call_code:
            logger.info(
                "[工具分类] 结果=工具调用 | 段数=%s | 含显式 tool_call 段=%s | 含 tool_call 代码块=%s | 段详情=%s",
                len(segments),
                has_tool_call,
                has_tool_call_code,
                seg_details,
            )
            return "tool_call"

        if has_code:
            logger.info(
                "[工具分类] 结果=无工具 | 段数=%s | 仅普通代码块，不进入工具路由 | 段详情=%s",
                len(segments),
                seg_details,
            )
            return "none"

        logger.info(
            "[工具分类] 结果=无工具 | 段数=%s | 无工具调用/代码块/回显 | 段详情=%s",
            len(segments),
            seg_details,
        )
        return "none"
