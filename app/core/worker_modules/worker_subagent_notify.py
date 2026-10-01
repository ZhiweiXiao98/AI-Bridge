# filename: app/core/worker_modules/worker_subagent_notify.py
from __future__ import annotations

import traceback

from app.core.logging import get_logger

logger = get_logger("app.core.worker.subagent_notify", side="worker")


class WorkerSubagentNotifyBridge:
    """Build reply-completed payloads from Browser/API history and notify subagent."""

    def __init__(self, worker):
        self.worker = worker

    def notify_reply_completed(self, mode: str, chat_id: str = ""):
        worker = self.worker
        try:
            logger.info(
                "[SubagentWorker] 进入回复完成通知: mode=%s chat_id=%s has_connector=%s has_api_source=%s has_subagent_bridge=%s",
                mode,
                chat_id,
                bool(getattr(worker, "connector", None)),
                bool(getattr(worker, "api_source", None)),
                bool(getattr(worker, "subagent_bridge", None)),
            )

            message_entries, history_count = self._collect_message_entries(mode)
            reply_text, reply_index, assistant_count = self._find_latest_assistant_reply(
                message_entries
            )
            recent_context = self._build_recent_context(message_entries, reply_index)

            logger.info(
                "[SubagentWorker] 回复完成检查: mode=%s chat_id=%s history_count=%d assistant_count=%d reply_len=%d recent_context_len=%d has_subagent_bridge=%s",
                mode,
                chat_id,
                history_count,
                assistant_count,
                len(reply_text or ""),
                len(recent_context or ""),
                bool(getattr(worker, "subagent_bridge", None)),
            )
            if reply_text:
                logger.info("[SubagentWorker] 触发Subagent 通知: mode=%s chat_id=%s", mode, chat_id)
                worker.subagent_bridge.on_reply_completed(
                    reply_text,
                    mode,
                    chat_id,
                    recent_context=recent_context,
                )
            else:
                logger.info("[SubagentWorker] 未获取到 assistant 回复文本，跳过Subagent 通知")
        except Exception as exc:
            logger.warning("[SubagentWorker] Subagent通知异常: %s", exc)
            traceback.print_exc()

    def _collect_message_entries(self, mode: str):
        worker = self.worker
        message_entries = []
        history_count = 0
        if mode == "api" and worker.api_source:
            logger.info("[SubagentWorker] API 准备读取历史消息")
            history = worker.api_source.get_history_as_messages() or []
            history_count = len(history)
            logger.info("[SubagentWorker] API 历史消息读取完成: count=%d", history_count)
            source_messages = history
        elif mode == "browser" and worker.connector:
            logger.info("[SubagentWorker] Browser 准备读取结构化消息")
            if hasattr(worker.connector, "get_chat_content"):
                raw_msgs, _is_at_bottom = worker.connector.get_chat_content(auto_wake=False)
            else:
                logger.warning("[SubagentWorker] Browser connector 不支持 get_chat_content，无法读取回复文本")
                raw_msgs = []
            source_messages = raw_msgs or []
            history_count = len(source_messages)
            logger.info(
                "[SubagentWorker] Browser 消息读取完成: count=%d type=%s",
                history_count,
                type(source_messages).__name__,
            )
        else:
            logger.warning(
                "[SubagentWorker] 回复完成通知缺少可用消息源: mode=%s has_connector=%s has_api_source=%s",
                mode,
                bool(getattr(worker, "connector", None)),
                bool(getattr(worker, "api_source", None)),
            )
            source_messages = []

        for msg in source_messages:
            if not isinstance(msg, dict):
                continue
            role = self._normalize_role(msg)
            text = self._extract_text(msg, mode)
            if not text:
                continue
            message_entries.append({"role": role, "text": text})
        return message_entries, history_count

    def _find_latest_assistant_reply(self, message_entries):
        assistant_count = 0
        for idx in range(len(message_entries) - 1, -1, -1):
            role = message_entries[idx].get("role", "")
            if role in ("assistant", "ai"):
                reply_text = str(message_entries[idx].get("text", "") or "").strip()
                assistant_count += 1
                logger.info(
                    "[SubagentWorker] 命中 assistant 消息: reverse_idx=%d reply_len=%d",
                    len(message_entries) - idx,
                    len(reply_text or ""),
                )
                return reply_text, idx, assistant_count
        return "", None, assistant_count

    def _extract_text(self, msg, mode: str):
        if not isinstance(msg, dict):
            return ""
        if mode == "browser":
            return self._extract_browser_text(msg)
        text = str(
            msg.get("content", "")
            or msg.get("text", "")
            or msg.get("raw_content", "")
            or ""
        ).strip()
        if text:
            return text
        return self._join_segment_text(msg)

    def _extract_browser_text(self, msg):
        text_parts = []
        for seg in msg.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            content = str(seg.get("content", "") or "")
            if not content.strip():
                continue
            if seg.get("type") == "code":
                lang = str(seg.get("language", "") or "text").strip() or "text"
                if content.strip().startswith("```"):
                    text_parts.append(content)
                else:
                    text_parts.append(f"```{lang}\n{content}\n```")
            else:
                text_parts.append(content)
        if not text_parts:
            fallback_text = str(msg.get("content", "") or msg.get("text", "") or "")
            if fallback_text.strip():
                text_parts.append(fallback_text)
        return "\n\n".join(text_parts).strip()

    def _join_segment_text(self, msg):
        text_parts = []
        for seg in msg.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            content = str(seg.get("content", "") or "")
            if content.strip():
                text_parts.append(content)
        return "\n\n".join(text_parts).strip()

    def _normalize_role(self, msg):
        if not isinstance(msg, dict):
            return ""
        role = str(msg.get("role", "") or "").strip().lower()
        if role == "ai":
            return "assistant"
        return role

    def _build_recent_context(self, entries, reply_index):
        if reply_index is None or reply_index <= 0:
            return ""
        start_index = max(0, reply_index - 5)
        context_lines = []
        for item in entries[start_index:reply_index]:
            role = item.get("role", "")
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            label = "用户" if role == "user" else "AI" if role in ("assistant", "ai") else role or "未知"
            context_lines.append(f"{label}：{text}")
        return "\n".join(context_lines).strip()
