# filename: app/core/context_compaction.py
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.context_compaction_state import (
    can_attempt_compact,
    mark_compact_failure,
    mark_compact_success,
    normalize_compact_state,
)
from app.core.context_message_compat import message_from_history_dict
from app.core.context_message_models import ConversationMessage
from app.core.logging import get_logger

COMPACT_SUMMARY_KIND = "compact_summary"
DEFAULT_RECENT_MESSAGE_COUNT = 6
SUMMARY_MAX_ITEMS = 12

logger = get_logger("app.core.context_compaction", side="worker")


class ContextCompactionOrchestrator:
    """Request-time context compaction orchestrator."""

    def __init__(self, compact_state: Optional[Dict[str, Any]] = None):
        self.compact_state = normalize_compact_state(compact_state or {})

    def get_state(self) -> Dict[str, Any]:
        return normalize_compact_state(self.compact_state)

    def should_compact(self, context_manager) -> bool:
        state = self.get_state()

        if not can_attempt_compact(state):
            logger.warning(
                "[ContextCompaction] skip compact: disabled by state | "
                "failure_count=%s | threshold=%s | disabled_until_manual_retry=%s",
                state.get("failure_count", 0),
                state.get("failure_threshold", 0),
                state.get("disabled_until_manual_retry", False),
            )
            return False

        usage = context_manager.get_token_usage()
        max_window_tokens = int(usage.get("total_budget", 0) or 0)
        output_reserve = int(usage.get("output_reserve", 0) or 0)
        total_used = int(usage.get("total_used", 0) or 0)
        compact_buffer = int(state.get("compact_buffer", 24000) or 24000)

        effective_window = max(0, max_window_tokens - output_reserve)
        auto_compact_threshold = max(0, effective_window - compact_buffer)

        if auto_compact_threshold <= 0:
            logger.warning(
                "[ContextCompaction] skip compact: invalid threshold | "
                "total_used=%s | effective_window=%s | compact_buffer=%s | auto_compact_threshold=%s",
                total_used,
                effective_window,
                compact_buffer,
                auto_compact_threshold,
            )
            return False

        should_run = total_used >= auto_compact_threshold
        logger.info(
            "[ContextCompaction] threshold check | total_used=%s | effective_window=%s | "
            "compact_buffer=%s | auto_compact_threshold=%s | should_compact=%s",
            total_used,
            effective_window,
            compact_buffer,
            auto_compact_threshold,
            should_run,
        )
        return should_run

    def split_history(self, history: List[Dict[str, Any]]) -> Dict[str, List[ConversationMessage]]:
        normalized = [message_from_history_dict(item) for item in (history or [])]

        if len(normalized) <= DEFAULT_RECENT_MESSAGE_COUNT:
            return {
                "compact_candidates": [],
                "recent_messages": normalized,
            }

        recent_messages = normalized[-DEFAULT_RECENT_MESSAGE_COUNT:]
        compact_candidates = [
            msg for msg in normalized[:-DEFAULT_RECENT_MESSAGE_COUNT]
            if msg.compactible
        ]

        return {
            "compact_candidates": compact_candidates,
            "recent_messages": recent_messages,
        }

    def build_summary_text(self, messages: List[ConversationMessage]) -> str:
        lines = [
            "[history compaction summary]",
            "Conservative summary of older conversation:",
        ]
        added = 0

        for msg in messages:
            if not msg.visible_in_context:
                continue

            content = (msg.content or "").strip()
            if not content:
                continue

            role_label = msg.role.upper()
            snippet = content.replace("\n", " ").strip()
            if len(snippet) > 120:
                snippet = snippet[:120] + "..."

            lines.append(f"- {role_label}/{msg.kind}: {snippet}")
            added += 1

            if added >= SUMMARY_MAX_ITEMS:
                break

        if added == 0:
            lines.append("- no extractable earlier context")

        return "\n".join(lines)

    def build_summary_message(
        self,
        summary_text: str,
        conversation_id: str = "",
    ) -> ConversationMessage:
        return ConversationMessage(
            role="assistant",
            content=summary_text,
            kind=COMPACT_SUMMARY_KIND,
            raw_content=summary_text,
            token_count=0,
            timestamp=time.time(),
            meta={"summary_type": "rule_based_compaction"},
            source_mode="api",
            conversation_id=conversation_id,
            visible_in_context=True,
            compactible=False,
        )

    def maybe_compact(
        self,
        context_manager,
        conversation_id: str = "",
        trigger: str = "pre_request",
        force: bool = False,
    ) -> Dict[str, Any]:
        logger.info(
            "[ContextCompaction] maybe_compact start | conversation_id=%s | trigger=%s | force=%s",
            conversation_id or "",
            trigger,
            force,
        )

        if not force and not self.should_compact(context_manager):
            logger.info(
                "[ContextCompaction] skip compact | conversation_id=%s | reason=threshold_not_reached | trigger=%s | force=%s",
                conversation_id or "",
                trigger,
                force,
            )
            return {
                "compacted": False,
                "reason": "threshold_not_reached",
                "compact_state": self.get_state(),
                "trigger": trigger,
                "force": force,
            }

        try:
            history = context_manager.get_history()
            split_result = self.split_history(history)
            compact_candidates = split_result.get("compact_candidates", [])
            recent_messages = split_result.get("recent_messages", [])

            logger.info(
                "[ContextCompaction] split history | conversation_id=%s | total_history=%s | "
                "compact_candidates=%s | recent_messages=%s",
                conversation_id or "",
                len(history),
                len(compact_candidates),
                len(recent_messages),
            )

            if not compact_candidates:
                logger.warning(
                    "[ContextCompaction] skip compact | conversation_id=%s | reason=not_enough_history | trigger=%s | force=%s",
                    conversation_id or "",
                    trigger,
                    force,
                )
                return {
                    "compacted": False,
                    "reason": "not_enough_history",
                    "compact_state": self.get_state(),
                    "trigger": trigger,
                    "force": force,
                }

            summary_text = self.build_summary_text(compact_candidates)
            summary_message = self.build_summary_message(
                summary_text,
                conversation_id=conversation_id,
            )
            summary_message.token_count = context_manager.counter.count(summary_message.content)

            new_history = [summary_message] + recent_messages
            context_manager.replace_history(new_history)

            self.compact_state = mark_compact_success(
                self.compact_state,
                summary_preview=summary_text,
                compacted_count=len(compact_candidates),
                preserved_count=len(recent_messages),
                now_ts=time.time(),
            )

            logger.info(
                "[ContextCompaction] compact success | conversation_id=%s | "
                "compacted_count=%s | preserved_count=%s | summary_tokens=%s | trigger=%s | force=%s",
                conversation_id or "",
                len(compact_candidates),
                len(recent_messages),
                summary_message.token_count,
                trigger,
                force,
            )

            return {
                "compacted": True,
                "reason": "success",
                "compact_state": self.get_state(),
                "compacted_count": len(compact_candidates),
                "preserved_count": len(recent_messages),
                "summary_preview": summary_text[:200],
                "trigger": trigger,
                "force": force,
            }

        except Exception as e:
            self.compact_state = mark_compact_failure(self.compact_state, str(e))
            logger.exception(
                "[ContextCompaction] compact failed | conversation_id=%s | failure_count=%s | error=%s | trigger=%s | force=%s",
                conversation_id or "",
                self.compact_state.get("failure_count", 0),
                str(e),
                trigger,
                force,
            )
            return {
                "compacted": False,
                "reason": "failed",
                "error": str(e),
                "compact_state": self.get_state(),
                "trigger": trigger,
                "force": force,
            }