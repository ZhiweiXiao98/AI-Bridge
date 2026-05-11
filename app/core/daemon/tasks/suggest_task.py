import re
from typing import List, Optional

from app.core.daemon.daemon_config import SuggestTaskConfig
from app.core.daemon.daemon_llm import DaemonLLMRouter
from app.core.logging import get_logger
from app.core.prompt_runtime.prompt_file_loader import load_daemon_prompt

logger = get_logger("app.core.daemon.tasks.suggest_task", side="worker")


class SuggestTask:
    def __init__(self, config: SuggestTaskConfig, llm: DaemonLLMRouter):
        self._config = config
        self._llm = llm
        self._system_prompt = ""

    def _load_system_prompt(self) -> str:
        content = load_daemon_prompt("suggest")
        if content:
            self._system_prompt = content
        return self._system_prompt

    def _build_user_prompt(self, reply_summary: str, context_summary: str, intent: str, mode: str) -> str:
        parts = [
            f"对话模式：{mode or 'unknown'}",
            f"AI 最新回复：\n{reply_summary}",
            f"本轮模仿意图：{intent}",
        ]
        if context_summary.strip():
            parts.append(f"最近对话上下文：\n{context_summary}")
        parts.append("你现在扮演对话里的用户本人，直接说出下一句自然口语。只输出一句纯文本，不要解释，不要编号，不要列表，不要 JSON，不要 Markdown。")
        return "\n\n".join(parts)

    def _normalize_suggestion_text(self, raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""

        text = text.replace("```", "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        first_line = lines[0]
        first_line = re.sub(r"^[\-\*\d\.\)\s]+", "", first_line).strip()
        first_line = first_line.strip('"“”\'')
        return first_line.strip()

    def handle(self, payload: dict) -> Optional[List[str]]:
        reply_text = str(payload.get("reply_text", "") or "")
        recent_context = str(payload.get("recent_context", "") or "")
        mode = payload.get("mode", "")
        if not reply_text.strip():
            return None

        system_prompt = self._load_system_prompt()
        if not system_prompt:
            logger.warning("守护进程建议任务: 提示词为空，跳过")
            return None

        reply_summary = reply_text[: self._config.reply_max_chars]
        context_summary = recent_context[: self._config.reply_max_chars] if recent_context else ""
        intents = ["追问细节", "确认执行", "补充信息"]
        suggestions: List[str] = []

        for idx, intent in enumerate(intents, start=1):
            user_prompt = self._build_user_prompt(reply_summary, context_summary, intent, mode)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            raw = self._llm.chat(messages, tier=self._config.model_tier)
            if not raw:
                logger.info("守护进程建议任务: 第 %d 次生成无结果 (意图: %s)", idx, intent)
                continue

            raw_text = str(raw)
            raw_preview = raw_text.strip().replace("\n", "\\n")
            logger.info(
                "守护进程建议任务: 第 %d 次原始输出长度=%d preview=%s",
                idx,
                len(raw_text),
                raw_preview[:500],
            )

            suggestion = self._normalize_suggestion_text(raw_text)
            if not suggestion:
                logger.info("守护进程建议任务: 第 %d 次输出为空，已丢弃", idx)
                continue
            if suggestion in suggestions:
                logger.info("守护进程建议任务: 第 %d 次输出重复，已丢弃: %s", idx, suggestion)
                continue

            suggestions.append(suggestion)
            if len(suggestions) >= self._config.max_suggestions:
                break

        if not suggestions:
            logger.debug("守护进程建议任务: 3 次生成均未得到有效建议")
            return None

        suggestions = suggestions[: self._config.max_suggestions]
        logger.info("守护进程建议生成: %s (模式: %s)", suggestions, mode)
        return suggestions
