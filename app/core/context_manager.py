"""
上下文管理引擎 (Context Manager)

职责：分层记忆管理、Token 计数、消息组装、滑动窗口
设计原则：独立于传输通道（API/Browser），只负责"组装什么内容"

参考: docs/context_system_plan.md
"""

import time
import json
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

import tiktoken

from app.core.app_constants import DEFAULT_API_MODEL
from app.core.context_message_models import (
    ConversationMessage,
    MESSAGE_KIND_TEXT,
)
from app.core.context_message_compat import message_from_history_dict
from app.core.logging import get_logger

logger = get_logger("app.core.context_manager", side="worker")


# ============================================================
# 配置
# ============================================================

@dataclass
class ContextConfig:
    """上下文配置"""
    max_window_tokens: int = 128000
    system_budget: int = 8000
    long_term_budget: int = 4000
    working_budget: int = 2000
    short_term_budget: int = 80000
    output_reserve: int = 16000
    max_history_turns: int = 50
    model: str = DEFAULT_API_MODEL

    @property
    def safety_margin(self) -> int:
        used = (self.system_budget + self.long_term_budget +
                self.working_budget + self.short_term_budget +
                self.output_reserve)
        return max(0, self.max_window_tokens - used)




# ============================================================
# Token 计数器
# ============================================================

class TokenCounter:
    """Token 计数，tiktoken 精确计数+ 降级估算"""

    def __init__(self, model: str = DEFAULT_API_MODEL):
        self._encoder = None
        self._model = model
        try:
            self._encoder = tiktoken.encoding_for_model(model)
        except KeyError:
            try:
                self._encoder = tiktoken.get_encoding("cl100k_base")
            except Exception:
                logger.warning("tiktoken 不可用，使用估算模式")

    def count(self, text: str) -> int:
        """计算文本的 token 数"""
        if not text:
            return 0
        if self._encoder:
            return len(self._encoder.encode(text))
        # 降级：中文约 1.5 token/字，英文约 0.25 token/词
        return max(1, int(len(text) * 0.6))

    def count_messages(self, messages: List[dict]) -> int:
        """计算 messages 列表的总 token 数（含格式开销）"""
        total = 0
        for msg in messages:
            total += 4  # 每条消息的格式开销
            total += self.count(msg.get("role", ""))
            total += self.count(msg.get("content", ""))
        total += 2  # 回复前缀开销
        return total

# ============================================================
# 上下文管理器
# ============================================================

class ContextManager:
    """
    上下文管理引擎

    分层记忆模型:
      - system_layer: 系统提示词（固定）
      - long_term: 长期记忆（RAG 检索结果）
      - working_memory: 工作记忆（当前任务状态）
      - history: 对话历史（滑动窗口）
    """

    def __init__(self, config: Optional[ContextConfig] = None):
        self.config = config or ContextConfig()
        self.counter = TokenCounter(self.config.model)

        # 系统层
        self._system_content: str = ""
        self._system_tokens: int = 0

        # 长期记忆（RAG 片段）
        self._long_term_fragments: List[str] = []
        self._long_term_tokens: int = 0

        # 工作记忆（结构化状态）
        self._working_memory: Dict[str, Any] = {}
        self._working_tokens: int = 0

        # 对话历史
        self._history: List[ConversationMessage] = []
        self._history_tokens: int = 0

    # ----------------------------------------------------------
    # 系统层
    # ----------------------------------------------------------

    def set_system_prompt(self, content: str) -> None:
        """设置系统提示词"""
        tokens = self.counter.count(content)
        if tokens > self.config.system_budget:
            logger.warning(
                f"系统提示词 ({tokens} tokens) 超出预算 ({self.config.system_budget})，将被截断"
            )
        self._system_content = content
        self._system_tokens = tokens

    # ----------------------------------------------------------
    # 长期记忆
    # ----------------------------------------------------------

    def inject_long_term(self, fragments: List[str]) -> None:
        """注入长期记忆片段（来自 RAG 检索）"""
        self._long_term_fragments = []
        self._long_term_tokens = 0
        budget = self.config.long_term_budget

        for frag in fragments:
            frag_tokens = self.counter.count(frag)
            if self._long_term_tokens + frag_tokens > budget:
                logger.info(f"长期记忆预算已满，丢弃剩余 {len(fragments) - len(self._long_term_fragments)} 片段")
                break
            self._long_term_fragments.append(frag)
            self._long_term_tokens += frag_tokens

    def clear_long_term(self) -> None:
        """清空长期记忆"""
        self._long_term_fragments = []
        self._long_term_tokens = 0

    # ----------------------------------------------------------
    # 工作记忆
    # ----------------------------------------------------------

    def update_working_memory(self, key: str, value: Any) -> None:
        """更新工作记忆的某个字段"""
        self._working_memory[key] = value
        self._rebuild_working_tokens()

    def set_working_memory(self, data: Dict[str, Any]) -> None:
        """整体替换工作记忆"""
        self._working_memory = data
        self._rebuild_working_tokens()

    def _rebuild_working_tokens(self) -> None:
        if self._working_memory:
            text = json.dumps(self._working_memory, ensure_ascii=False)
            self._working_tokens = self.counter.count(text)
        else:
            self._working_tokens = 0
# ----------------------------------------------------------
    # 对话历史
    # ----------------------------------------------------------

    def add_message(self, role: str, content: str) -> None:
        """记录新消息（兼容旧接口）"""
        self.add_structured_message(role=role, content=content, kind=MESSAGE_KIND_TEXT)

    def add_structured_message(
        self,
        role: str,
        content: str,
        segments: Optional[list] = None,
        kind: str = MESSAGE_KIND_TEXT,
        raw_content: str = '',
        meta: Optional[Dict[str, Any]] = None,
        source_mode: str = 'api',
        conversation_id: str = '',
        visible_in_context: bool = True,
        compactible: bool = True,
        timestamp: Optional[float] = None,
    ) -> None:
        """记录结构化消息"""
        tokens = self.counter.count(content)
        msg = ConversationMessage(
            role=role,
            content=content,
            segments=segments or [],
            kind=kind,
            raw_content=raw_content,
            token_count=tokens,
            timestamp=timestamp or time.time(),
            meta=dict(meta or {}),
            source_mode=source_mode,
            conversation_id=conversation_id,
            visible_in_context=visible_in_context,
            compactible=compactible,
        )
        self.add_history_message(msg)

    def add_history_message(self, message: ConversationMessage) -> None:
        """直接写入结构化历史消息。"""
        self._history.append(message)
        if message.visible_in_context:
            self._history_tokens += message.token_count
        self._trim_history()

    def load_history_message(self, data: Dict[str, Any]) -> None:
        """从持久化 dict 恢复消息，兼容旧格式。"""
        message = message_from_history_dict(data)
        self.add_history_message(message)

    def _trim_history(self) -> None:
        """滑动窗口：裁剪超出预算的早期对话"""
        budget = self.config.short_term_budget
        max_turns = self.config.max_history_turns

        while len(self._history) > max_turns * 2:
            removed = self._history.pop(0)
            if removed.visible_in_context:
                self._history_tokens = max(0, self._history_tokens - removed.token_count)

        while self._history_tokens > budget and len(self._history) > 2:
            removed = self._history.pop(0)
            if removed.visible_in_context:
                self._history_tokens = max(0, self._history_tokens - removed.token_count)

    # ----------------------------------------------------------
    # 消息组装（核心方法）
    # ----------------------------------------------------------

    def build_messages(self) -> List[dict]:
        """
        组装发送给 LLM 的 messages 列表

        顺序:
          1. system（系统提示词）
          2. system（长期记忆，如有）
          3. system（工作记忆，如有）
          4. 对话历史（滑动窗口）
        """
        messages = []

        # 1. 系统层
        if self._system_content:
            messages.append({
                "role": "system",
                "content": self._system_content
            })

        # 2. 长期记忆
        if self._long_term_fragments:
            lt_content = "[长期记忆]" + chr(10) + chr(10).join(self._long_term_fragments)
            messages.append({
                "role": "system",
                "content": lt_content
            })

        # 3. 工作记忆
        if self._working_memory:
            wm_text = json.dumps(self._working_memory, ensure_ascii=False, indent=2)
            wm_content = f"[工作记忆]当前任务状态:{chr(10)}{wm_text}"
            messages.append({
                "role": "system",
                "content": wm_content
            })

        # 4. 对话历史
        for msg in self._history:
            if not msg.visible_in_context:
                continue
            if msg.kind == 'meta':
                continue
            if msg.kind in ('tool_feedback', 'compact_summary', 'text'):
                messages.append({"role": msg.role, "content": msg.content})
                continue
            messages.append(msg.to_chat_dict())

        return messages

    # ----------------------------------------------------------
    # 状态查询
    # ----------------------------------------------------------

    def get_system_prompt(self) -> str:
        return self._system_content or ""

    def get_long_term_fragments(self) -> List[str]:
        return list(self._long_term_fragments)

    def get_working_memory(self) -> Dict[str, Any]:
        return dict(self._working_memory)

    def get_token_usage(self) -> Dict[str, Any]:
        """返回各层token 用量"""
        total_used = (
            self._system_tokens +
            self._long_term_tokens +
            self._working_tokens +
            self._history_tokens
        )
        return {
            "system": {"used": self._system_tokens, "budget": self.config.system_budget},
            "long_term": {"used": self._long_term_tokens, "budget": self.config.long_term_budget},
            "working": {"used": self._working_tokens, "budget": self.config.working_budget},
            "short_term": {"used": self._history_tokens, "budget": self.config.short_term_budget},
            "output_reserve": self.config.output_reserve,
            "total_used": total_used,
            "total_budget": self.config.max_window_tokens,
            "utilization": round(total_used / self.config.max_window_tokens * 100, 1),
            "history_turns": len(self._history) // 2,
            "history_messages": len(self._history),
        }

    def get_history(self) -> List[dict]:
        """返回对话历史（结构化格式）"""
        return [m.to_history_dict() for m in self._history]

    def replace_history(self, messages: List[ConversationMessage]) -> None:
        """整体替换 history，并重算上下文 token。"""
        self._history = list(messages or [])
        self._history_tokens = sum(m.token_count for m in self._history if m.visible_in_context)

    def delete_history_by_indexes(self, indexes: List[int]) -> int:
        """按索引删除任意历史消息，返回实际删除条数。"""
        if not indexes:
            return 0
        valid_indexes = sorted({int(i) for i in indexes if 0 <= int(i) < len(self._history)}, reverse=True)
        removed = 0
        for idx in valid_indexes:
            msg = self._history.pop(idx)
            if msg.visible_in_context:
                self._history_tokens = max(0, self._history_tokens - msg.token_count)
            removed += 1
        return removed

    # ----------------------------------------------------------
    # 清空
    # ----------------------------------------------------------

    def clear(self) -> None:
        """清空所有上下文（保留系统层）"""
        self._long_term_fragments = []
        self._long_term_tokens = 0
        self._working_memory = {}
        self._working_tokens = 0
        self._history = []
        self._history_tokens = 0
        logger.info("上下文已清空（系统层保留）")