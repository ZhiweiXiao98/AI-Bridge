# filename: app/core/api_source.py
"""
API 消息源 - 双消息源架构的API 端

职责：
- 封装 ContextManager + LLMProvider + ConversationStore
- 提供与浏览器消息源对等的接口
- 供 worker.py 在 api 模式下调用
"""

import json
import logging
import os
import asyncio
import hashlib
import time
from typing import Any, Dict, Optional, List, AsyncIterator

import tiktoken

from app.core.context_manager import ContextManager, ContextConfig
from app.core.context_message_models import (
    MESSAGE_KIND_TEXT,
)
from app.core.conversation_store import ConversationStore
from app.core.context_compaction import ContextCompactionOrchestrator
from app.core.llm_provider import create_provider, LLMProvider
from app.core.config import ConfigManager
from app.core.api_mode_config import (
    APIModeConfigManager,
    TOOL_CAPABILITY_PARTIAL,
    TOOL_CAPABILITY_UNSUPPORTED,
    TOOL_PROTOCOL_MARKDOWN,
    TOOL_PROTOCOL_MARKDOWN_ONLY,
    TOOL_PROTOCOL_NATIVE,
)
from app.core.prompt_runtime import build_final_system_prompt
from app.core.journal_index import JournalIndex, extract_search_keywords
from app.core.parsers.markdown_code_block_parser import MarkdownCodeBlockParser
from app.core.tool_runtime.segment_parser import ToolSegmentParser
from app.core.tool_runtime.models import ToolIntent
from app.core.app_constants import APP_ROOT, MIMO_MODELS, DEFAULT_API_BASE_URL, DEFAULT_API_MODEL
from app.core.model_capabilities import provider_reasoning_kwargs
from app.core.provider_errors import classify_provider_error, is_retryable_provider_error
from app.core.logging import get_logger
from app.core.logging.trace_context import get_current_trace, get_trace_extra, new_round
from app.core.debug import probe

logger = get_logger("app.core.api_source", side="worker")

DEFAULT_SYSTEM_PROMPT = """你是一个 AI 编程助手。
- 帮助用户编写、调试、优化代码
- 提供技术建议和最佳实践
- 清晰、简洁地解释概念
"""


def _safe_count_tokens(text: str, model: str = DEFAULT_API_MODEL) -> int:
    if not text:
        return 0
    try:
        try:
            encoder = tiktoken.encoding_for_model(model)
        except KeyError:
            encoder = tiktoken.get_encoding('cl100k_base')
        return len(encoder.encode(text))
    except Exception:
        return max(1, int(len(text) * 0.6))


def _provider_common_payload(profile: dict, provider_kind: str) -> dict:
    profile = profile if isinstance(profile, dict) else {}
    return {
        "provider": provider_kind,
        "api_key": profile.get("api_key", ""),
        "base_url": profile.get("base_url", DEFAULT_API_BASE_URL),
        "model": profile.get("model", DEFAULT_API_MODEL),
        "temperature": profile.get("temperature", 0.7),
        "max_output_tokens": profile.get("max_output_tokens", 4096),
        "timeout": profile.get("timeout", 60),
        "proxy_url": profile.get("proxy_url", ""),
        **provider_reasoning_kwargs(profile),
    }


class APISource:
    """
    API 消息源，与浏览器消息源对等。
    worker.py 通过此类在 api 模式下收发消息。
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.config_dict: dict = {}
        self.conv_store: Optional[ConversationStore] = None
        self.llm_provider: Optional[LLMProvider] = None
        self.last_fallback_event: Optional[dict] = None
        self.current_runtime_profile_key: Optional[str] = None
        self.provider_init_error: Optional[str] = None
        self._initialized = False
        self._last_request_snapshot: Optional[dict] = None
        self.on_tool_status_event = None

    #============================================================
    # 初始化
    # ============================================================

    def initialize(self):
        """加载配置，初始化所有组件"""
        if self._initialized:
            return

        self.config_dict = APIModeConfigManager.load()
        ctx_conf = ContextConfig(**self.config_dict.get("conversation_defaults", {}).get("context", {}))

        storage_dir = os.path.join(APP_ROOT, "config", "conversations")
        os.makedirs(storage_dir, exist_ok=True)

        self.conv_store = ConversationStore(
            storage_dir=storage_dir,
            config=ctx_conf,
        )

        convs = self.conv_store.list_conversations()
        if convs:
            self.conv_store.switch(convs[0]["id"])

        profile_key, profile, _usage = self._resolve_runtime_profile(config=self.config_dict)
        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            self.current_runtime_profile_key = profile_key
            self._initialized = True
            logger.info("APISource 初始化为 browser_stateless Profile，LLM provider 由浏览器适配器接管")
            return
        provider_kind = profile.get("provider", "openai_compatible")
        provider_common = _provider_common_payload(profile, provider_kind)
        provider_payload = {
            "provider": provider_kind,
            "api": provider_common,
            "gemini": provider_common,
        }
        self.llm_provider = self._create_llm_provider(provider_payload, profile_key=profile_key)
        self.current_runtime_profile_key = profile_key
        self._initialized = True
        model = profile.get("model", "unknown")
        if self.llm_provider:
            logger.info(f"APISource 初始化完成 | model={model}")
        else:
            logger.warning("APISource 初始化完成但 Provider 暂不可用 | profile=%s | model=%s | error=%s", profile_key, model, self.provider_init_error)
    # ============================================================
    # 消息收发
    # ============================================================

    def _compose_system_prompt_payload(self, conversation_id: Optional[str] = None) -> dict:
        self._ensure_init()
        cfg = APIModeConfigManager.load()
        system_cfg = cfg.get("conversation_defaults", {}).get("system", {}) or {}
        conversation_system_prompt = ''
        if self.conv_store:
            target_conv_id = conversation_id or self.conv_store.active_id
            snapshot = self.conv_store.load_conversation_snapshot(target_conv_id) if target_conv_id else None
            if snapshot:
                conversation_system_prompt = (
                    snapshot.get('conversation_system_prompt')
                    or snapshot.get('meta', {}).get('conversation_system_prompt')
                    or ''
                ).strip()
        return build_final_system_prompt(
            conversation_system_prompt=conversation_system_prompt,
            inject_skills_prompt=bool(system_cfg.get("inject_skills_prompt", True)),
            tool_protocol=self._get_tool_protocol(conversation_id=conversation_id, config=cfg),
        )

    def _refresh_context_manager_system_prompt(self, conversation_id: Optional[str] = None):
        payload = self._compose_system_prompt_payload(conversation_id=conversation_id)
        cm = self._get_cm_for(conversation_id)
        cm.set_system_prompt(payload.get("final_system_prompt", ""))
        self._save_cm_for(cm, conversation_id)
        return payload

    _JOURNAL_FRAGMENT_PREFIX = '[AI_JOURNAL 相关记录]\n'

    def _inject_journal_long_term(self, conversation_id: Optional[str] = None):
        """从对话历史提取关键词，搜索 AI_JOURNAL 并注入长期记忆。"""
        try:
            cm = self._get_cm_for(conversation_id)
            history = cm.get_history()
            if not history:
                return

            keywords = extract_search_keywords(history, max_keywords=20)
            if not keywords:
                return

            if not hasattr(self, '_journal_index') or self._journal_index is None:
                self._journal_index = JournalIndex()

            headers = self._journal_index.search_headers(keywords, max_results=8)
            if not headers:
                return

            journal_fragment = self._JOURNAL_FRAGMENT_PREFIX + '\n'.join(headers)

            # 保留非 journal 的已有 fragments
            existing = cm.get_long_term_fragments() if hasattr(cm, 'get_long_term_fragments') else []
            preserved = [f for f in existing if not str(f).startswith(self._JOURNAL_FRAGMENT_PREFIX)]
            preserved.append(journal_fragment)

            cm.inject_long_term(preserved)
            self._save_cm_for(cm, conversation_id)
            logger.debug('[APISource] journal long-term injected | keywords=%d | matched=%d', len(keywords), len(headers))
        except Exception as e:
            logger.warning('[APISource] journal injection failed: %s', e)

    def _capture_request_snapshot(self, messages: list, conversation_id: Optional[str] = None):
        """捕获本次请求的轨迹快照骨架，供调试浮窗使用。"""
        import time as _time
        try:
            cm = self._get_cm_for(conversation_id)
            system_payload = self._compose_system_prompt_payload(conversation_id=conversation_id)
            cid = conversation_id or (self.conv_store.active_id if self.conv_store else None) or ''
            profile_key = self._resolve_profile_key(conversation_id=conversation_id)
            profile = self.config_dict.get('profiles', {}).get(profile_key, {})
            model_name = str(profile.get('model', DEFAULT_API_MODEL))

            long_term = cm.get_long_term_fragments() if hasattr(cm, 'get_long_term_fragments') else []
            working = cm.get_working_memory() if hasattr(cm, 'get_working_memory') else {}
            history_raw = []
            if hasattr(cm, '_history'):
                for msg in cm._history:
                    history_raw.append({
                        'role': msg.role,
                        'kind': getattr(msg, 'kind', 'text'),
                        'content': msg.content[:2000] if len(msg.content) > 2000 else msg.content,
                        'full_length': len(msg.content),
                        'visible': getattr(msg, 'visible_in_context', True),
                        'tokens': getattr(msg, 'token_count', 0),
                    })

            self._last_request_snapshot = {
                'conversation_id': cid,
                'model': model_name,
                'profile_key': profile_key,
                'timestamp': _time.time(),
                'system_blocks': {
                    k: v for k, v in system_payload.items() if k != 'final_system_prompt'
               },
                'final_system_prompt_tokens': _safe_count_tokens(system_payload.get('final_system_prompt', ''), model=model_name),
                'long_term_fragments': long_term,
                'working_memory': working,
                'history': history_raw,
                'initial_request': {
                    'messages': messages,
                },
                'rounds': [],
                'final_reply': None,
                'loop_count': 0,
                'response': None,
                'final_messages': messages,
                'round_state': 'idle',
                'selected_tool_protocol': None,
                'tool_candidates': [],
                'ephemeral_tool_rounds': [],
                'finalized': False,
            }
            self._persist_request_snapshot(conversation_id=cid)
        except Exception as e:
            logger.warning('[APISource] snapshot capture failed: %s', e)

    def _get_snapshot_ref(self, conversation_id: Optional[str] = None) -> Optional[dict]:
        snap = self._last_request_snapshot
        if not snap:
            return None
        if conversation_id and snap.get('conversation_id') != conversation_id:
            return None
        return snap

    def _persist_request_snapshot(self, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap or not self.conv_store:
                return False
            cid = (snap.get('conversation_id') or conversation_id or getattr(self.conv_store, 'active_id', None) or '').strip()
            if not cid:
                return False
            snap['conversation_id'] = cid
            setter = getattr(self.conv_store, 'set_last_request_snapshot', None)
            if callable(setter):
                return bool(setter(cid, snap))
        except Exception as e:
            logger.warning('[APISource] persist snapshot failed: %s', e)
        return False

    def append_snapshot_round(self, phase: str, data: Optional[dict] = None, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            rounds = snap.setdefault('rounds', [])
            entry = {'phase': str(phase or '').strip() or 'unknown'}
            if isinstance(data, dict) and data:
                entry.update(data)
            rounds.append(entry)
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] append snapshot round failed: %s', e)
            return False

    def capture_snapshot_messages(self, phase: str, conversation_id: Optional[str] = None) -> bool:
        try:
            cm = self._get_cm_for(conversation_id)
            messages = self._build_request_messages(cm, conversation_id=conversation_id)
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            self.append_snapshot_round(phase, {'messages': messages}, conversation_id=conversation_id)
            snap['final_messages'] = messages
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] capture snapshot messages failed: %s', e)
            return False

    def set_snapshot_final_reply(self, reply: str, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            snap['final_reply'] = reply
            snap['response'] = reply
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] set snapshot final reply failed: %s', e)
            return False

    def set_snapshot_loop_count(self, loop_count: int, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            snap['loop_count'] = int(loop_count or 0)
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] set snapshot loop count failed: %s', e)
            return False

    def set_round_state(self, state: str, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            snap['round_state'] = str(state or '').strip() or 'idle'
            snap['finalized'] = bool(snap.get('round_state') == 'finalized')
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] set round state failed: %s', e)
            return False

    def set_tool_candidates(self, candidates: list, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            snap['tool_candidates'] = list(candidates or [])
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] set tool candidates failed: %s', e)
            return False

    def set_selected_tool_protocol(self, protocol: str, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            snap['selected_tool_protocol'] = str(protocol or '').strip() or None
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] set selected tool protocol failed: %s', e)
            return False

    def append_ephemeral_tool_round(self, data: Optional[dict] = None, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            rounds = snap.setdefault('ephemeral_tool_rounds', [])
            rounds.append(dict(data or {}) if isinstance(data, dict) else {})
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] append ephemeral tool round failed: %s', e)
            return False

    def finalize_round_snapshot(self, conversation_id: Optional[str] = None) -> bool:
        try:
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            snap['round_state'] = 'finalized'
            snap['finalized'] = True
            self._persist_request_snapshot(conversation_id)
            return True
        except Exception as e:
            logger.warning('[APISource] finalize round snapshot failed: %s', e)
            return False

    def get_last_request_snapshot(self, conversation_id: Optional[str] = None) -> Optional[dict]:
        """获取最近一次请求的完整上下文快照。"""
        snap = self._get_snapshot_ref(conversation_id)
        if snap:
            return snap
        if not self.conv_store:
            return None
        stored = None
        if conversation_id:
            getter = getattr(self.conv_store, 'get_last_request_snapshot', None)
            if callable(getter):
                stored = getter(conversation_id)
        if not stored:
            latest_getter = getattr(self.conv_store, 'get_latest_request_snapshot', None)
            if callable(latest_getter):
                stored = latest_getter()
        if isinstance(stored, dict) and stored:
            self._last_request_snapshot = stored
            return stored
        return None

    def _maybe_compact_context(self, conversation_id: Optional[str] = None, trigger: str = 'pre_request', force: bool = False) -> dict:
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None) or ''
        compact_state = self.conv_store.get_compact_state(target_id) if (self.conv_store and target_id) else {}
        logger.info("[APISource] try context compaction | conversation_id=%s | trigger=%s | force=%s", target_id, trigger, force)
        orchestrator = ContextCompactionOrchestrator(compact_state=compact_state)
        result = orchestrator.maybe_compact(cm, conversation_id=target_id, trigger=trigger, force=force)
        if self.conv_store and target_id:
            self.conv_store.set_compact_state(target_id, result.get("compact_state", compact_state))
        if result.get("compacted"):
            logger.info(
                "[APISource] context compaction success | conversation_id=%s | compacted_count=%s | preserved_count=%s",
                target_id,
                result.get("compacted_count", 0),
                result.get("preserved_count", 0),
            )
            self._save_cm_for(cm, conversation_id)
        else:
            _reason = result.get("reason", "unknown")
            _error = result.get("error", "")
            # threshold_not_reached 是正常行为，不应用 WARNING
            _log_fn = logger.info if (_reason == "threshold_not_reached" and not _error) else logger.warning
            _log_fn(
                "[APISource] context compaction skipped_or_failed | conversation_id=%s | reason=%s | error=%s",
                target_id,
                _reason,
                _error,
            )
        return result

    def trigger_manual_compact(self, conversation_id: Optional[str] = None) -> dict:
        self._ensure_init()
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        if self.get_conversation_runtime(target_id) != "legacy":
            return {"ok": False, "reason": "runtime_owns_context", "conversation_id": target_id,
                    "message": "Pi 会话由运行时管理压缩，不能调用旧版压缩"}
        if not target_id:
            return {
                'ok': False,
                'reason': 'no_active_conversation',
                'compaction': {},
            }
        result = self._maybe_compact_context(conversation_id=target_id, trigger='manual', force=True)
        return {
            'ok': bool(result.get('compacted')),
            'reason': result.get('reason', 'unknown'),
            'compaction': result,
            'conversation_id': target_id,
        }

    def send_message_sync(self, text: str, tool_router=None) -> str:
        """同步发送消息，返回完整回复"""
        self._ensure_init()
        active_conv_id = self.conv_store.active_id if self.conv_store else None
        self.conv_store.require_legacy(active_conv_id)
        self._apply_runtime_for_conversation(active_conv_id)
        self.last_fallback_event = None
        ctx = get_current_trace()
        if ctx:
            new_round()
        logger.info("[APISource] send_message_sync | text_len=%d", len(text), extra=get_trace_extra())
        probe("api_source_send_sync", level="info", side="worker", text_len=len(text))
        self._refresh_context_manager_system_prompt()
        cm = self._get_cm()
        cm.add_structured_message("user", text, kind=MESSAGE_KIND_TEXT, source_mode="api")
        self._maybe_compact_context()
        cm = self._get_cm()
        self._auto_title(text)
        self._inject_journal_long_term()

        messages = self._build_request_messages(cm)
        self._capture_request_snapshot(messages)
        self.set_round_state('streaming_initial_reply')
        native_handled, reply = self._try_chat_with_native_tools(
            messages,
            conversation_id=self.conv_store.active_id if self.conv_store else None,
            tool_router=tool_router,
        )
        if native_handled:
            if self._last_request_snapshot:
                self._last_request_snapshot['response'] = reply
                self.set_snapshot_final_reply(reply)
            if self.conv_store and self.conv_store.active_id:
                self.conv_store.touch_last_message_at(self.conv_store.active_id)
            self.conv_store.save_current()
            return reply

        cm = self._get_cm()
        messages = self._build_request_messages(cm)
        if self._last_request_snapshot:
            self._last_request_snapshot['final_messages'] = messages
            self._persist_request_snapshot()
        reply = self._chat_with_fallback_sync(messages)
        if self._last_request_snapshot:
            self._last_request_snapshot['response'] = reply
            self.append_snapshot_round('initial_reply', {'assistant_reply': reply})
            self.set_snapshot_final_reply(reply)
        cm.add_structured_message("assistant", reply, kind=MESSAGE_KIND_TEXT, source_mode="api")
        if self.conv_store and self.conv_store.active_id:
            self.conv_store.touch_last_message_at(self.conv_store.active_id)
        self.conv_store.save_current()
        return reply

    async def send_message_stream(self, text: str, tool_router=None) -> AsyncIterator[str]:
        """流式发送消息，逐块yield回复"""
        self._ensure_init()
        active_conv_id = self.conv_store.active_id if self.conv_store else None
        self.conv_store.require_legacy(active_conv_id)
        self._apply_runtime_for_conversation(active_conv_id)
        self.last_fallback_event = None
        ctx = get_current_trace()
        if ctx:
            new_round()
        logger.info("[APISource] send_message_stream | text_len=%d", len(text), extra=get_trace_extra())
        probe("api_source_send_stream", level="info", side="worker", text_len=len(text))
        self._refresh_context_manager_system_prompt()
        cm = self._get_cm()
        cm.add_structured_message("user", text, kind=MESSAGE_KIND_TEXT, source_mode="api")
        self._maybe_compact_context()
        cm = self._get_cm()
        self._auto_title(text)
        self._inject_journal_long_term()

        messages = self._build_request_messages(cm)
        self._capture_request_snapshot(messages)
        self.set_round_state('streaming_initial_reply')
        native_stream_method, native_tools = self._get_native_tool_stream_spec(
            conversation_id=self.conv_store.active_id if self.conv_store else None,
            tool_router=tool_router,
        )
        if native_stream_method and native_tools:
            yielded_native = False
            native_partial_parts: List[str] = []
            try:
                async for chunk in self._stream_chat_with_native_tools(
                    messages,
                    native_stream_method,
                    native_tools,
                    conversation_id=self.conv_store.active_id if self.conv_store else None,
                    tool_router=tool_router,
                ):
                    yielded_native = True
                    native_partial_parts.append(chunk)
                    yield chunk
                if self.conv_store and self.conv_store.active_id:
                    self.conv_store.touch_last_message_at(self.conv_store.active_id)
                self.conv_store.save_current()
                return
            except Exception as e:
                self._mark_native_tools_partial(e, conversation_id=self.conv_store.active_id if self.conv_store else None)
                logger.warning("[APISource] native tools stream failed, fallback to markdown/plain stream | error=%s", e)
                self._refresh_context_manager_system_prompt()
                if yielded_native:
                    partial_reply = "".join(native_partial_parts)
                    if partial_reply:
                        cm = self._get_cm()
                        cm.add_structured_message(
                            "assistant",
                            partial_reply + f"\n\n[错误中断: {e}]",
                            kind=MESSAGE_KIND_TEXT,
                            source_mode="api",
                        )
                        self.conv_store.save_current()
                    raise
                cm = self._get_cm()
                messages = self._build_request_messages(cm)
                if self._last_request_snapshot:
                    self._last_request_snapshot['final_messages'] = messages
                    self._persist_request_snapshot()

        full_reply = ""
        full_thinking = ""
        try:
            async for event in self._chat_with_fallback_stream(messages):
                content_delta, thinking_delta = self._split_stream_event(event)
                full_reply += content_delta
                full_thinking += thinking_delta
                yield event
            if self._last_request_snapshot:
                self._last_request_snapshot['response'] = full_reply
                if full_thinking:
                    self._last_request_snapshot['reasoning_content'] = full_thinking
                self.append_snapshot_round(
                    'initial_reply',
                    {
                        'assistant_reply': full_reply,
                        'reasoning_content': full_thinking,
                    } if full_thinking else {'assistant_reply': full_reply},
                )
                self.set_snapshot_final_reply(full_reply)
            cm.add_structured_message(
                "assistant",
                full_reply,
                segments=self._assistant_segments_with_thinking(full_reply, full_thinking),
                kind=MESSAGE_KIND_TEXT,
                raw_content=full_reply,
                meta={"reasoning_content": full_thinking} if full_thinking else {},
                source_mode="api",
            )
            if self.conv_store and self.conv_store.active_id:
                self.conv_store.touch_last_message_at(self.conv_store.active_id)
            self.conv_store.save_current()
        except Exception as e:
            logger.error(f"流式调用失败: {e}")
            probe("api_source_stream_error", level="error", side="worker", error=str(e))
            if full_reply or full_thinking:
                error_reply = (full_reply or "") + f"\n\n[错误中断: {e}]"
                cm.add_structured_message(
                    "assistant",
                    error_reply,
                    segments=self._assistant_segments_with_thinking(error_reply, full_thinking),
                    kind=MESSAGE_KIND_TEXT,
                    raw_content=error_reply,
                    meta={"reasoning_content": full_thinking} if full_thinking else {},
                    source_mode="api",
                )
                self.conv_store.save_current()
            raise

    @staticmethod
    def _split_stream_event(event) -> tuple[str, str]:
        if isinstance(event, dict):
            event_type = str(event.get("type") or event.get("delta_type") or "").strip().lower()
            thinking = str(
                event.get("thinking_content")
                or event.get("reasoning_content")
                or ""
            )
            content = str(
                event.get("content")
                or event.get("text_delta")
                or ""
            )
            if event_type in ("thinking_delta", "reasoning_delta", "thinking"):
                return "", thinking or content
            return content, thinking
        return str(event or ""), ""

    def _assistant_segments_with_thinking(self, reply: str, thinking: str) -> Optional[list]:
        thinking = str(thinking or "")
        if not thinking:
            return None
        segments = [{"type": "thinking", "content": thinking}]
        if reply:
            segments.extend(self.get_last_reply_as_segments(reply))
        return segments

    def _apply_usage_overrides(self, profile: dict, usage: Optional[dict]) -> dict:
        effective = dict(profile or {})
        if not isinstance(usage, dict):
            return effective

        model = str(usage.get("model") or "").strip()
        if model:
            effective["model"] = model

        reasoning = usage.get("reasoning")
        if isinstance(reasoning, dict):
            merged = dict(effective.get("reasoning") or {})
            if "enabled" in reasoning:
                merged["enabled"] = bool(reasoning.get("enabled"))
            effort = str(reasoning.get("effort") or merged.get("effort") or "medium").strip().lower()
            if effort not in ("low", "medium", "high"):
                effort = "medium"
            merged["effort"] = effort
            effective["reasoning"] = merged
        return effective

    def _resolve_runtime_profile(self, conversation_id: Optional[str] = None, config: Optional[dict] = None) -> tuple[str, dict, Optional[dict]]:
        cfg = config or self.config_dict or APIModeConfigManager.load()
        conv_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        usage = self.conv_store.get_model_usage(conv_id) if (self.conv_store and conv_id) else None
        profile_key = APIModeConfigManager.get_active_profile_key(cfg, usage_override=usage)
        profile = dict((cfg.get("profiles", {}) or {}).get(profile_key, {}) or {})
        return profile_key, self._apply_usage_overrides(profile, usage), usage

    def _apply_runtime_for_conversation(self, conversation_id: Optional[str] = None):
        cfg = self.config_dict or APIModeConfigManager.load()
        profile_key, profile, _usage = self._resolve_runtime_profile(conversation_id=conversation_id, config=cfg)
        self._apply_profile_runtime(profile_key, persist_active=False, profile_override=profile, config=cfg)
        return profile_key, profile

    def _apply_profile_runtime(
        self,
        profile_key: str,
        persist_active: bool = True,
        profile_override: Optional[dict] = None,
        config: Optional[dict] = None,
    ):
        cfg = config or APIModeConfigManager.load()
        profiles = cfg.get("profiles", {})
        if profile_key not in profiles:
            raise ValueError(f"Profile 不存在: {profile_key}")

        if persist_active and cfg.get("active_profile") != profile_key:
            cfg["active_profile"] = profile_key
            APIModeConfigManager.save(cfg)
            cfg = APIModeConfigManager.load()
            profiles = cfg.get("profiles", {})

        self.config_dict = cfg
        self.current_runtime_profile_key = profile_key
        profile = dict(profile_override or profiles[profile_key])

        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            logger.info(f"APISource 已切换为 browser_stateless Profile | active={profile_key}")
            return

        provider_kind = profile.get("provider", "openai_compatible")
        if self.llm_provider and not hasattr(self.llm_provider, "update_config"):
            self.current_runtime_profile_key = profile_key
            logger.debug("APISource 保留不可热更新 Provider | active=%s", profile_key)
            return

        needs_rebuild = False
        current_provider_name = self.llm_provider.__class__.__name__ if self.llm_provider else ''
        if provider_kind == 'gemini' and current_provider_name != 'GeminiProvider':
            needs_rebuild = True
        if provider_kind in ('api', 'openai_compatible', 'mimo') and current_provider_name != 'APIProvider':
            needs_rebuild = True

        provider_common = _provider_common_payload(profile, provider_kind)
        if needs_rebuild:
            provider_payload = {
                "provider": provider_kind,
                "api": provider_common,
                "gemini": provider_common,
            }
            self.llm_provider = self._create_llm_provider(provider_payload, profile_key=profile_key)
        elif self.llm_provider and hasattr(self.llm_provider, "update_config"):
            try:
                self.llm_provider.update_config(**provider_common)
                self.provider_init_error = None
            except Exception as e:
                info = self._classify_provider_error(e)
                self.provider_init_error = info.get("user_message") or str(e)
                self.llm_provider = None
                logger.warning(
                    "APISource 更新 Provider 配置失败 | profile=%s | category=%s | retryable=%s | error=%s",
                    profile_key,
                    info.get("category"),
                    info.get("retryable"),
                    e,
                )

        logger.info(f"APISource 已切换运行时 Profile | active={profile_key} | model={profile.get('model', 'unknown')}")

    def _get_fallback_candidates(self) -> list:
        cfg = APIModeConfigManager.load()
        active = cfg.get("active_profile", "default")
        profiles = cfg.get("profiles", {})
        chain = cfg.get("fallback_chain", []) or []

        candidates = []
        seen = set()
        for key in chain:
            key = str(key).strip()
            if not key or key == active or key not in profiles or key in seen:
                continue
            seen.add(key)
            candidates.append(key)
        return candidates

    def _is_retryable_error(self, e: Exception) -> bool:
        return is_retryable_provider_error(e)

    def is_retryable_error(self, e: Exception) -> bool:
        """Public compatibility wrapper used by fallback loops."""
        return self._is_retryable_error(e)

    def _classify_provider_error(self, e: Exception) -> dict:
        return classify_provider_error(e)

    def _chat_with_fallback_sync(self, messages: list) -> str:
        self._ensure_init()
        active_conv_id = self.conv_store.active_id if self.conv_store else None
        self._apply_runtime_for_conversation(active_conv_id)
        cfg = APIModeConfigManager.load()
        active = self._resolve_profile_key()
        attempts = [active] + self._get_fallback_candidates()
        errors = []
        error_infos = []

        for idx, profile_key in enumerate(attempts):
            max_retries = 3
            base_delay = 2.0
            for attempt in range(max_retries + 1):
                try:
                    if idx > 0 and attempt == 0:
                        previous_profile = attempts[idx - 1]
                        previous_error = errors[-1] if errors else "unknown"
                        self._apply_profile_runtime(profile_key, persist_active=True)
                        self.last_fallback_event = {
                            "from": previous_profile,
                            "to": profile_key,
                            "reason": previous_error,
                            "category": (error_infos[-1] if error_infos else {}).get("category", "unknown"),
                            "retryable": (error_infos[-1] if error_infos else {}).get("retryable", False),
                            "user_message": (error_infos[-1] if error_infos else {}).get("user_message", previous_error),
                        }
                        logger.warning(f"APISource fallback 切换成功，准备重试 | from={previous_profile} | to={profile_key}")
                    if not self.llm_provider:
                        if self.current_runtime_profile_key != profile_key:
                            self._apply_profile_runtime(profile_key, persist_active=False)
                        if not self.llm_provider:
                            raise RuntimeError(f"API Provider 暂不可用：请在设置页配置 API Key 并保存应用。{self.provider_init_error or ''}".strip())
                    return self.llm_provider.chat(messages)
                except Exception as e:
                    import time
                    info = self._classify_provider_error(e)
                    if attempt < max_retries and info.get("retryable"):
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "[%s] 同步调用可重试错误 | category=%s | delay=%.1fs | attempt=%d/%d | error=%s",
                            profile_key,
                            info.get("category"),
                            delay,
                            attempt + 1,
                            max_retries,
                            e,
                        )
                        time.sleep(delay)
                        continue
                    errors.append(f"{profile_key}: {info.get('user_message') or e}")
                    error_infos.append(info)
                    logger.error(
                        "APISource 同步调用失败 | profile=%s | category=%s | retryable=%s | error=%s",
                        profile_key,
                        info.get("category"),
                        info.get("retryable"),
                        e,
                    )
                    break

        raise RuntimeError("API 调用失败，且 fallback chain 全部尝试失败: " + " | ".join(errors))

    async def _chat_with_fallback_stream(self, messages: list) -> AsyncIterator[str]:
        self._ensure_init()
        active_conv_id = self.conv_store.active_id if self.conv_store else None
        self._apply_runtime_for_conversation(active_conv_id)
        cfg = APIModeConfigManager.load()
        active = self._resolve_profile_key()
        attempts = [active] + self._get_fallback_candidates()
        errors = []
        error_infos = []

        for idx, profile_key in enumerate(attempts):
            max_retries = 3
            base_delay = 2.0
            for attempt in range(max_retries + 1):
                try:
                    if idx > 0 and attempt == 0:
                        previous_profile = attempts[idx - 1]
                        previous_error = errors[-1] if errors else "unknown"
                        self._apply_profile_runtime(profile_key, persist_active=True)
                        self.last_fallback_event = {
                            "from": previous_profile,
                            "to": profile_key,
                            "reason": previous_error,
                            "category": (error_infos[-1] if error_infos else {}).get("category", "unknown"),
                            "retryable": (error_infos[-1] if error_infos else {}).get("retryable", False),
                            "user_message": (error_infos[-1] if error_infos else {}).get("user_message", previous_error),
                        }
                        logger.warning(f"APISource fallback 切换成功，准备流式重试 | from={previous_profile} | to={profile_key}")
                    if not self.llm_provider:
                        if self.current_runtime_profile_key != profile_key:
                            self._apply_profile_runtime(profile_key, persist_active=False)
                        if not self.llm_provider:
                            raise RuntimeError(f"API Provider 暂不可用：请在设置页配置 API Key 并保存应用。{self.provider_init_error or ''}".strip())
                    stream_events = getattr(self.llm_provider, "stream_chat_events", None)
                    if callable(stream_events):
                        async for event in stream_events(messages):
                            yield event
                    else:
                        async for chunk in self.llm_provider.stream_chat(messages):
                            yield chunk
                    return
                except Exception as e:
                    import asyncio
                    info = self._classify_provider_error(e)
                    if attempt < max_retries and info.get("retryable"):
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "[%s] 流式调用可重试错误 | category=%s | delay=%.1fs | attempt=%d/%d | error=%s",
                            profile_key,
                            info.get("category"),
                            delay,
                            attempt + 1,
                            max_retries,
                            e,
                        )
                        await asyncio.sleep(delay)
                        continue

                    errors.append(f"{profile_key}: {info.get('user_message') or e}")
                    error_infos.append(info)
                    logger.error(
                        "APISource 流式调用失败 | profile=%s | category=%s | retryable=%s | error=%s",
                        profile_key,
                        info.get("category"),
                        info.get("retryable"),
                        e,
                    )
                    break

        raise RuntimeError("API 流式调用失败，且 fallback chain 全部尝试失败: " + " | ".join(errors))

    def _get_native_tool_stream_spec(self, conversation_id: Optional[str] = None, tool_router=None):
        if self._get_tool_protocol(conversation_id=conversation_id) != TOOL_PROTOCOL_NATIVE:
            return None, []
        if not self.llm_provider:
            return None, []
        provider_method = getattr(self.llm_provider, "stream_chat_with_tools", None)
        if not callable(provider_method):
            return None, []
        if getattr(type(self.llm_provider), "stream_chat_with_tools", None) is LLMProvider.stream_chat_with_tools:
            return None, []
        tools = self._get_native_tool_definitions(tool_router)
        if not tools:
            return None, []
        return provider_method, tools

    async def _stream_chat_with_native_tools(
        self,
        messages: list,
        stream_method,
        tools: list,
        conversation_id: Optional[str] = None,
        tool_router=None,
    ) -> AsyncIterator[str]:
        """Run a streaming native tool-calling loop and yield user-visible text deltas."""
        request_messages = [dict(m) for m in (messages or []) if isinstance(m, dict)]
        max_rounds = self._get_native_tool_max_rounds()
        write_conversation_id = self._write_conversation_id(conversation_id)

        self.set_selected_tool_protocol(TOOL_PROTOCOL_NATIVE, conversation_id=conversation_id)
        for round_index in range(1, max_rounds + 1):
            content_parts: List[str] = []
            streamed_content = False
            message_end_seen = False
            content = ""
            tool_calls: List[dict] = []

            stream_iter = stream_method(request_messages, tools)
            try:
                async for event in stream_iter:
                    if not isinstance(event, dict):
                        continue
                    event_type = str(event.get("type", "") or "")
                    if event_type == "content_delta":
                        delta = str(event.get("content", "") or "")
                        if delta:
                            content_parts.append(delta)
                            streamed_content = True
                            yield delta
                    elif event_type == "message_end":
                        message_end_seen = True
                        content = str(event.get("content", "") or "") or "".join(content_parts)
                        tool_calls = list(event.get("tool_calls", []) or [])
                        break
            finally:
                close_stream = getattr(stream_iter, "aclose", None)
                if callable(close_stream):
                    await close_stream()

            if not message_end_seen:
                content = "".join(content_parts)

            if not tool_calls:
                final_reply = content
                if final_reply and not streamed_content:
                    yield final_reply
                self._append_final_native_assistant_reply(final_reply, conversation_id=write_conversation_id)
                if self._last_request_snapshot:
                    self._last_request_snapshot['response'] = final_reply
                    self.set_snapshot_final_reply(final_reply, conversation_id=conversation_id)
                self.append_snapshot_round(
                    "native_stream_assistant_reply",
                    {"assistant_reply": final_reply, "round_index": round_index},
                    conversation_id=conversation_id,
                )
                return

            intents = self._native_tool_calls_to_intents(
                tool_calls,
                conversation_id=conversation_id or (self.conv_store.active_id if self.conv_store else "") or "api_default",
            )
            self._append_native_tool_call_message(content, tool_calls, intents, conversation_id=write_conversation_id)
            request_messages.append(self._build_native_assistant_message(content, tool_calls))

            round_result = self._execute_native_tool_intents(intents, tool_router, conversation_id=conversation_id)
            round_result.source_protocol = TOOL_PROTOCOL_NATIVE
            self.append_snapshot_round(
                "native_stream_tool_calls",
                {
                    "round_index": round_index,
                    "tool_calls": tool_calls,
                    "tool_result": round_result.combined_feedback,
                },
                conversation_id=conversation_id,
            )
            self._append_native_tool_feedback(round_result, round_index, conversation_id=write_conversation_id)
            for result in round_result.results:
                request_messages.append({
                    "role": "tool",
                    "tool_call_id": result.tool_call_id or "",
                    "content": str((result.output if result.success else result.error) or ""),
                })
            self.capture_snapshot_messages("post_native_stream_tool_messages", conversation_id=conversation_id)

        final_reply = f"已达到原生工具最大调用轮数（{max_rounds}），已停止继续自动调用。"
        yield final_reply
        self._append_final_native_assistant_reply(final_reply, conversation_id=write_conversation_id)
        if self._last_request_snapshot:
            self._last_request_snapshot['response'] = final_reply
            self.set_snapshot_final_reply(final_reply, conversation_id=conversation_id)
        self.append_snapshot_round(
            "native_stream_max_rounds_reached",
            {"assistant_reply": final_reply, "max_rounds": max_rounds},
            conversation_id=conversation_id,
        )

    def _try_chat_with_native_tools(self, messages: list, conversation_id: Optional[str] = None, tool_router=None) -> tuple[bool, str]:
        """Run a non-streaming native tool-calling loop when the active profile supports it."""
        if self._get_tool_protocol(conversation_id=conversation_id) != TOOL_PROTOCOL_NATIVE:
            return False, ""
        if not self.llm_provider:
            return False, ""
        provider_method = getattr(self.llm_provider, "chat_with_tools", None)
        if not callable(provider_method):
            return False, ""
        if getattr(type(self.llm_provider), "chat_with_tools", None) is LLMProvider.chat_with_tools:
            return False, ""
        tools = self._get_native_tool_definitions(tool_router)
        if not tools:
            return False, ""

        request_messages = [dict(m) for m in (messages or []) if isinstance(m, dict)]
        max_rounds = self._get_native_tool_max_rounds()
        final_reply = ""
        write_conversation_id = self._write_conversation_id(conversation_id)

        self.set_selected_tool_protocol(TOOL_PROTOCOL_NATIVE, conversation_id=conversation_id)
        try:
            for round_index in range(1, max_rounds + 1):
                response = provider_method(request_messages, tools)
                content = str((response or {}).get("content", "") or "")
                tool_calls = list((response or {}).get("tool_calls", []) or [])

                if not tool_calls:
                    final_reply = content
                    self._append_final_native_assistant_reply(final_reply, conversation_id=write_conversation_id)
                    self.append_snapshot_round(
                        "native_assistant_reply",
                        {"assistant_reply": final_reply, "round_index": round_index},
                        conversation_id=conversation_id,
                    )
                    return True, final_reply

                intents = self._native_tool_calls_to_intents(
                    tool_calls,
                    conversation_id=conversation_id or (self.conv_store.active_id if self.conv_store else "") or "api_default",
                )
                self._append_native_tool_call_message(content, tool_calls, intents, conversation_id=write_conversation_id)
                request_messages.append(self._build_native_assistant_message(content, tool_calls))

                round_result = self._execute_native_tool_intents(intents, tool_router, conversation_id=conversation_id)
                round_result.source_protocol = TOOL_PROTOCOL_NATIVE
                self.append_snapshot_round(
                    "native_tool_calls",
                    {
                        "round_index": round_index,
                        "tool_calls": tool_calls,
                        "tool_result": round_result.combined_feedback,
                    },
                    conversation_id=conversation_id,
                )
                self._append_native_tool_feedback(round_result, round_index, conversation_id=write_conversation_id)
                for result in round_result.results:
                    request_messages.append({
                        "role": "tool",
                        "tool_call_id": result.tool_call_id or "",
                        "content": str((result.output if result.success else result.error) or ""),
                    })
                self.capture_snapshot_messages("post_native_tool_messages", conversation_id=conversation_id)

            final_reply = f"已达到原生工具最大调用轮数（{max_rounds}），已停止继续自动调用。"
            self._append_final_native_assistant_reply(final_reply, conversation_id=write_conversation_id)
            self.append_snapshot_round(
                "native_max_rounds_reached",
                {"assistant_reply": final_reply, "max_rounds": max_rounds},
                conversation_id=conversation_id,
            )
            return True, final_reply
        except Exception as e:
            self._mark_native_tools_partial(e, conversation_id=conversation_id)
            logger.warning("[APISource] native tools failed, fallback to markdown/plain chat | error=%s", e)
            self._refresh_context_manager_system_prompt(conversation_id=conversation_id)
            return False, ""

    def _get_native_tool_definitions(self, tool_router) -> list:
        skills_manager = getattr(tool_router, "skills_manager", None)
        if not skills_manager or not hasattr(skills_manager, "get_all_tool_definitions"):
            return []
        try:
            tools = list(skills_manager.get_all_tool_definitions() or [])
        except Exception as e:
            logger.warning("[APISource] native tools definitions unavailable: %s", e)
            return []
        allow_tools = set(
            str(x).strip()
            for x in (self.config_dict.get("agent", {}).get("allow_tools", []) or [])
            if str(x).strip()
        )
        if allow_tools:
            filtered = []
            for tool in tools:
                fn = tool.get("function", {}) if isinstance(tool, dict) else {}
                name = str(fn.get("name", "") or "")
                if name in allow_tools:
                    filtered.append(tool)
            tools = filtered
        return tools

    def _write_conversation_id(self, conversation_id: Optional[str]) -> Optional[str]:
        if conversation_id and self.conv_store and conversation_id == self.conv_store.active_id:
            return None
        return conversation_id

    def _get_native_tool_max_rounds(self) -> int:
        try:
            raw = int(self.config_dict.get("agent", {}).get("max_steps", 8) or 8)
        except Exception:
            raw = 8
        return max(1, min(raw, 30))

    def _native_tool_calls_to_intents(self, tool_calls: list, conversation_id: str = "") -> List[ToolIntent]:
        intents: List[ToolIntent] = []
        for call in tool_calls or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(fn.get("name", "") or "")
            raw_args = fn.get("arguments", "{}")
            arguments: Dict[str, Any]
            if isinstance(raw_args, dict):
                arguments = dict(raw_args)
            else:
                try:
                    parsed = json.loads(str(raw_args or "{}"))
                    arguments = parsed if isinstance(parsed, dict) else {"_value": parsed}
                except Exception:
                    arguments = {"_raw_arguments": str(raw_args or "")}
            raw_block = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)
            intents.append(ToolIntent(
                kind="skill_call",
                name=name,
                arguments=arguments,
                source=TOOL_PROTOCOL_NATIVE,
                conversation_id=conversation_id,
                raw_block=raw_block,
                tool_call_id=str(call.get("id") or ""),
            ))
        return intents

    def _execute_native_tool_intents(self, intents: List[ToolIntent], tool_router, conversation_id: Optional[str] = None):
        executor = getattr(tool_router, "runtime_executor", None)
        if not executor:
            raise RuntimeError("tool_runtime_executor_unavailable")

        active_conv_id = conversation_id or (self.conv_store.active_id if self.conv_store else "") or "api_default"

        def _on_start(intent, idx):
            if self.on_tool_status_event:
                self.on_tool_status_event({
                    "type": "tool_call",
                    "tool_name": intent.name,
                    "tool_call_id": getattr(intent, "tool_call_id", None),
                    "status": "running",
                    "conversation_id": active_conv_id,
                    "message": f"正在执行 {intent.name}...",
                })

        def _on_end(intent, result, idx):
            if self.on_tool_status_event:
                self.on_tool_status_event({
                    "type": "tool_call",
                    "tool_name": intent.name,
                    "tool_call_id": getattr(result, "tool_call_id", None) or getattr(intent, "tool_call_id", None),
                    "status": "completed" if getattr(result, "success", False) else "failed",
                    "conversation_id": active_conv_id,
                })

        return executor.execute_intents(intents, on_intent_start=_on_start, on_intent_end=_on_end)

    def _append_native_tool_call_message(self, content: str, tool_calls: list, intents: List[ToolIntent], conversation_id: Optional[str] = None):
        names = [intent.name for intent in intents if intent.name]
        display = (content or "").strip() or ("调用工具：" + ", ".join(names) if names else "调用工具")
        segments = []
        for intent in intents:
            segments.append({
                "type": "tool_call",
                "tool_name": intent.name,
                "tool_call_id": intent.tool_call_id,
                "arguments": dict(intent.arguments or {}),
                "content": dict(intent.arguments or {}),
                "raw_content": intent.raw_block,
                "source_protocol": TOOL_PROTOCOL_NATIVE,
            })
        self.append_assistant_message(
            display,
            segments=segments,
            conversation_id=conversation_id,
            kind=MESSAGE_KIND_TEXT,
            raw_content=content or display,
            meta={
                "native_tool_calls": tool_calls,
                "source_protocol": TOOL_PROTOCOL_NATIVE,
            },
            visible_in_context=True,
            compactible=True,
        )

    def _append_native_tool_feedback(self, round_result, round_index: int, conversation_id: Optional[str] = None):
        tool_feedback = round_result.combined_feedback or ""
        full_feedback = f"🔧 [工具执行结果]\n{tool_feedback}" if tool_feedback else "🔧 [工具执行结果]"
        segments = []
        for intent in getattr(round_result, "intents", []) or []:
            segments.append({
                "type": "tool_call",
                "tool_name": intent.name,
                "tool_call_id": getattr(intent, "tool_call_id", None),
                "arguments": dict(getattr(intent, "arguments", {}) or {}),
                "content": dict(getattr(intent, "arguments", {}) or {}),
                "source_protocol": TOOL_PROTOCOL_NATIVE,
            })
        for res in getattr(round_result, "results", []) or []:
            segments.append({
                "type": "tool_result",
                "tool_name": res.name,
                "tool_call_id": getattr(res, "tool_call_id", None),
                "content": res.output or res.error,
                "success": res.success,
                "source_protocol": TOOL_PROTOCOL_NATIVE,
            })
        self.append_tool_feedback_message(
            full_feedback,
            segments=segments,
            conversation_id=conversation_id,
            raw_content=full_feedback,
            meta={
                "tool_name": "tool_router",
                "tool_kind": "tool_feedback",
                "success": True,
                "segments": segments,
                "ephemeral": True,
                "round_stage": "running_tools",
                "source_protocol": TOOL_PROTOCOL_NATIVE,
                "round_index": round_index,
            },
            visible_in_context=True,
            compactible=True,
        )

    def _append_final_native_assistant_reply(self, reply: str, conversation_id: Optional[str] = None):
        self.append_assistant_message(
            reply or "",
            conversation_id=conversation_id,
            kind=MESSAGE_KIND_TEXT,
            raw_content=reply or "",
            meta={"source_protocol": TOOL_PROTOCOL_NATIVE},
            visible_in_context=True,
            compactible=True,
        )

    def _build_native_assistant_message(self, content: str, tool_calls: list) -> dict:
        return {
            "role": "assistant",
            "content": content or None,
            "tool_calls": list(tool_calls or []),
        }

    def _mark_native_tools_partial(self, error: Exception, conversation_id: Optional[str] = None):
        try:
            profile_key = self._resolve_profile_key(conversation_id=conversation_id)
            APIModeConfigManager.update_profile_tool_capability(profile_key, {
                "status": TOOL_CAPABILITY_PARTIAL,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": str(error)[:500],
                "protocol": TOOL_PROTOCOL_MARKDOWN,
            })
            self.config_dict = APIModeConfigManager.load()
        except Exception as update_error:
            logger.warning("[APISource] failed to update native tool capability: %s", update_error)
    def get_last_reply_as_segments(self, reply_text: str) -> list:
        """
        将 AI 回复转换为与浏览器消息兼容的 segments 格式。
        worker.py 的 messages_signal 和 process_batch 都依赖这个格式。
        """
        return MarkdownCodeBlockParser.parse_segments(reply_text)

    def build_message_for_signal(
        self,
        role: str,
        content: str,
        index: int = 0,
        kind: str = "text",
        meta: Optional[dict] = None,
        raw_content: str = "",
        segments: Optional[list] = None,
        timestamp: Optional[float] = None,
        conversation_id: Optional[str] = None,
    ) -> dict:
        """
        构建与浏览器消息格式兼容的消息字典。
        用于通过 messages_signal 发送给 ChatPage 渲染。
        """
        meta_dict = meta if isinstance(meta, dict) else {}
        if not segments and "segments" in meta_dict:
            segments = meta_dict["segments"]

        if segments and isinstance(segments, list):
            final_segments = segments
        elif role == "assistant":
            final_segments = self.get_last_reply_as_segments(content)
        else:
            final_segments = [{"type": "text", "content": content}]
        if role == "assistant" and isinstance(final_segments, list):
            ToolSegmentParser.parse_segments(final_segments, write_back_tool_call_id=True)

        final_raw = raw_content if isinstance(raw_content, str) and raw_content else content
        conversation_id = conversation_id or self.conv_store.active_id or "default"
        if role == "assistant":
            role_label = "AI"
        elif role == "user":
            role_label = "User"
        elif role == "tool_feedback" or kind == "tool_feedback":
            role_label = "Tool"
        else:
            role_label = str(role or "Message")
        stable_ts = timestamp if timestamp is not None else meta_dict.get("timestamp", "")
        explicit_id = (
            meta_dict.get("id")
            or meta_dict.get("message_id")
            or meta_dict.get("uid")
        )
        if explicit_id:
            message_id = str(explicit_id)
        else:
            id_seed = f"{conversation_id}|{index}|{role_label}|{stable_ts}|{kind}"
            id_hash = hashlib.md5(id_seed.encode("utf-8")).hexdigest()[:12]
            message_id = f"{conversation_id}:api:{index}:{role_label}:{id_hash}"
        content_hash_seed = json.dumps({
            "role": role_label,
            "kind": kind,
            "segments": final_segments,
            "raw": final_raw,
        }, ensure_ascii=False, sort_keys=True, default=str)
        content_hash = hashlib.md5(content_hash_seed.encode("utf-8")).hexdigest()[:12]
        return {
            "role": role_label,
            "index": index,
            "ordinal": index,
            "rev": int(meta_dict.get("rev", 1) or 1),
            "content_hash": content_hash,
            "segments": final_segments,
            "id": message_id,
            "conversation_id": conversation_id,
            "raw_len": len(content),
            "raw_content": final_raw,
            "kind": str(kind or "text"),
            "meta": meta_dict,
            "source": "api",
        }

    def append_assistant_message(
        self,
        content: str,
        segments: Optional[list] = None,
        conversation_id: Optional[str] = None,
        kind: str = MESSAGE_KIND_TEXT,
        raw_content: str = '',
        meta: Optional[dict] = None,
        visible_in_context: bool = True,
        compactible: bool = True,
    ) -> bool:
        """向指定 API 对话追加 assistant 消息，并持久化。"""
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        cm.add_structured_message(
            "assistant",
            content,
            segments=segments,
            kind=kind,
            raw_content=raw_content,
            meta=meta or {},
            source_mode="api",
            conversation_id=conversation_id or '',
            visible_in_context=visible_in_context,
            compactible=compactible,
        )
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        if self.conv_store and target_id:
            self.conv_store.touch_last_message_at(target_id)
        self._save_cm_for(cm, conversation_id)
        return True

    def append_tool_feedback_message(
        self,
        content: str,
        segments: Optional[list] = None,
        conversation_id: Optional[str] = None,
        raw_content: str = '',
        meta: Optional[dict] = None,
        visible_in_context: bool = True,
        compactible: bool = True,
    ) -> bool:
        """追加工具回流消息。它是独立 kind，不伪装成 assistant/user。"""
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        cm.add_structured_message(
            "tool_feedback",
            content,
            segments=segments,
            kind="tool_feedback",
            raw_content=raw_content,
            meta=meta or {},
            source_mode="api",
            conversation_id=conversation_id or '',
            visible_in_context=visible_in_context,
            compactible=compactible,
        )
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        if self.conv_store and target_id:
            self.conv_store.touch_last_message_at(target_id)
        self._save_cm_for(cm, conversation_id)
        return True

    def continue_assistant_reply_sync(self, conversation_id: Optional[str] = None) -> str:
        """基于当前上下文继续生成一条 assistant 回复，不追加新的 user 消息。"""
        self._ensure_init()
        self.last_fallback_event = None
        self._refresh_context_manager_system_prompt(conversation_id=conversation_id)
        cm = self._get_cm_for(conversation_id)
        self._maybe_compact_context(conversation_id=conversation_id)
        cm = self._get_cm_for(conversation_id)
        messages = self._build_request_messages(cm, conversation_id=conversation_id)
        reply = self._chat_with_fallback_sync(messages)
        cm.add_structured_message("assistant", reply, kind=MESSAGE_KIND_TEXT, source_mode="api")
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        if self.conv_store and target_id:
            self.conv_store.touch_last_message_at(target_id)
        self._save_cm_for(cm, conversation_id)
        return reply
    # ============================================================
    # 对话管理
    # ============================================================

    def get_conversations(self) -> list:
        """获取对话列表，格式兼容 SessionList"""
        self._ensure_init()
        return self.conv_store.list_conversations()

    def get_api_conversations(self) -> list:
        """获取 API 对话列表，供上下文工作台独立选择目标对话。"""
        return self.get_conversations()

    def create_conversation(self, title: str = "新对话", system_prompt: str = "", runtime: str = "legacy") -> str:
        """创建新对话，返回对话ID"""
        self._ensure_init()
        prompt = system_prompt or self.config_dict.get("conversation_defaults", {}).get("system", {}).get("user_prompt") or DEFAULT_SYSTEM_PROMPT
        conv_id = self.conv_store.create(title, system_prompt=prompt, runtime=runtime)
        return conv_id

    def switch_conversation(self, conv_id: str) -> bool:
        """切换到指定对话，返回是否成功"""
        self._ensure_init()
        return self.conv_store.switch(conv_id)

    def delete_conversation(self, conv_id: str):
        """删除对话"""
        self._ensure_init()
        self.conv_store.delete(conv_id)

    def rename_conversation(self, conv_id: str, title: str) -> bool:
        """重命名对话"""
        self._ensure_init()
        return self.conv_store.rename(conv_id, title)

    def set_conversation_pinned(self, conv_id: str, pinned: bool) -> bool:
        """设置/取消对话置顶"""
        self._ensure_init()
        return self.conv_store.set_pinned(conv_id, pinned)

    def set_conversation_model_usage(self, conv_id: str, usage: Optional[dict]) -> bool:
        """设置指定对话使用的 Profile/Chain；None 表示使用全局默认。"""
        self._ensure_init()
        return bool(self.conv_store and self.conv_store.set_model_usage(conv_id, usage))

    def has_active_conversation(self) -> bool:
        """当前是否存在活跃对话与上下文"""
        self._ensure_init()
        return bool(self.conv_store and self.conv_store.active_id and (self.conv_store.get_runtime() != "legacy" or self.conv_store.context_manager))

    def get_conversation_runtime(self, conversation_id: Optional[str] = None) -> str:
        self._ensure_init()
        return self.conv_store.get_runtime(conversation_id) if self.conv_store else "legacy"

    def _runtime_history(self, conversation_id: Optional[str] = None) -> list:
        target = conversation_id or self.conv_store.active_id
        return self.conv_store.get_display_messages(target)

    def _runtime_messages(self, conversation_id: Optional[str] = None) -> list:
        target = conversation_id or self.conv_store.active_id
        messages = []
        for index, msg in enumerate(self._runtime_history(target)):
            role = {"assistant": "AI", "user": "User", "tool": "Tool", "toolResult": "Tool"}.get(msg.get("role"), "AI")
            content = str(msg.get("content") or "")
            segments = msg.get("segments") or [{"type": "text", "content": content}]
            messages.append({
                "id": msg.get("id") or f"{target}:pi:{index}", "index": index,
                "ordinal": index, "rev": 1, "role": role, "source": "api",
                "runtime": "pi", "conversation_id": target, "raw_content": content,
                "raw_len": len(content), "segments": segments, "kind": msg.get("kind", "text"),
                "meta": {"runtime": "pi", "display_only": True},
                "content_hash": hashlib.sha256(json.dumps(segments, sort_keys=True).encode()).hexdigest()[:12],
            })
        return messages

    def get_history(self) -> list:
        """获取当前对话的消息历史"""
        self._ensure_init()
        if self.get_conversation_runtime(None) != "legacy":
            return self._runtime_history(None)
        cm = self._get_cm()
        return cm.get_history()

    def get_history_as_messages(self) -> list:
        """
        获取历史并转换为 messages_signal 兼容格式。
        用于切换到API对话时一次性渲染所有历史。
        """
        self._ensure_init()
        if self.get_conversation_runtime(None) != "legacy":
            return self._runtime_messages(None)
        cm = self._get_cm()
        history = cm.get_history()
        messages = []
        for i, msg in enumerate(history):
            messages.append(self.build_message_for_signal(
                role=msg["role"],
                content=msg["content"],
                index=i,
                kind=msg.get("kind", "text"),
                meta=msg.get("meta", {}),
                raw_content=msg.get("raw_content", ""),
                segments=msg.get("segments", []),
                timestamp=msg.get("timestamp"),
                conversation_id=self.conv_store.active_id if self.conv_store else None,
            ))
        return messages

    def get_history_as_messages_for(self, conversation_id: Optional[str] = None) -> list:
        """获取指定对话历史并转换为 messages_signal 兼容格式。"""
        self._ensure_init()
        if self.get_conversation_runtime(conversation_id) != "legacy":
            return self._runtime_messages(conversation_id)
        cm = self._get_cm_for(conversation_id)
        history = cm.get_history()
        messages = []
        for i, msg in enumerate(history):
            messages.append(self.build_message_for_signal(
                role=msg["role"],
                content=msg["content"],
                index=i,
                kind=msg.get("kind", "text"),
                meta=msg.get("meta", {}),
                raw_content=msg.get("raw_content", ""),
                segments=msg.get("segments", []),
                timestamp=msg.get("timestamp"),
                conversation_id=conversation_id,
            ))
        return messages

    def clear_context(self):
        """清空当前对话上下文（保留系统层）"""
        self._ensure_init()
        cm = self._get_cm()
        cm.clear()
        self.conv_store.save_current()

    def delete_messages(self, indexes: list[int], conversation_id: Optional[str] = None) -> int:
        """按消息索引删除指定对话中的任意历史消息。"""
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        removed = cm.delete_history_by_indexes(indexes or []) if hasattr(cm, 'delete_history_by_indexes') else 0
        if removed > 0:
            self._save_cm_for(cm, conversation_id)
        return removed
    # ============================================================
    # 上下文状态
    # ============================================================

    def get_context_workspace_payload(self, conversation_id: Optional[str] = None) -> dict:
        self._ensure_init()
        if self.get_conversation_runtime(conversation_id) != "legacy":
            target = conversation_id or self.conv_store.active_id
            meta = self.conv_store.get_meta(target) or {}
            return {
                "mode": "api", "runtime": "pi", "read_only": True,
                "conversation_id": target, "conversation_title": meta.get("title", ""),
                "reason": "Pi 管理上下文；此处为只读显示，不支持旧版历史编辑或压缩",
                "system": {"blocks": [], "conversation_system_prompt": "", "final_system_prompt": "Pi runtime managed", "final_tokens": 0, "system_budget": 0, "over_budget": False},
                "working_memory": {}, "long_term": {"fragments": [], "count": 0},
                "context_config": {}, "compact": {"owner": "pi"},
                "usage": self.get_context_status(target), "history_preview": self._runtime_history(target)[-12:],
            }
        cm = self._get_cm_for(conversation_id)
        cfg = APIModeConfigManager.load()
        system_cfg = cfg.get("conversation_defaults", {}).get("system", {}) or {}
        context_cfg = cfg.get("conversation_defaults", {}).get("context", {}) or {}
        effective_conversation_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        usage = self.get_context_status(conversation_id=effective_conversation_id)
        meta = self.conv_store.get_meta(effective_conversation_id) if (self.conv_store and effective_conversation_id) else None

        system_payload = self._compose_system_prompt_payload(conversation_id=effective_conversation_id)
        conversation_system_prompt = system_payload.get('conversation_system_prompt', '')
        final_system_prompt = system_payload.get('final_system_prompt', '')
        model_name = str(self.config_dict.get('profiles', {}).get(self.config_dict.get('active_profile', 'default'), {}).get('model', DEFAULT_API_MODEL))
        prompt_blocks = [
            {
                'name': 'compat_prompt',
                'label': '兼容提示词',
                'enabled': bool(system_payload.get('compat_prompt', '')),
                'tokens': _safe_count_tokens(system_payload.get('compat_prompt', ''), model=model_name),
                'content': system_payload.get('compat_prompt', ''),
            },
            {
                'name': 'user_pref_prompt',
                'label': '用户偏好',
                'enabled': bool(system_payload.get('user_pref_prompt', '')),
                'tokens': _safe_count_tokens(system_payload.get('user_pref_prompt', ''), model=model_name),
                'content': system_payload.get('user_pref_prompt', ''),
            },
            {
                'name': 'plan_prompt',
                'label': '计划模式提示词',
                'enabled': bool(system_payload.get('plan_prompt', '')),
                'tokens': _safe_count_tokens(system_payload.get('plan_prompt', ''), model=model_name),
                'content': system_payload.get('plan_prompt', ''),
            },
            {
                'name': 'build_prompt',
                'label': '构建模式提示词',
                'enabled': bool(system_payload.get('build_prompt', '')),
                'tokens': _safe_count_tokens(system_payload.get('build_prompt', ''), model=model_name),
                'content': system_payload.get('build_prompt', ''),
            },
            {
                'name': 'skills_prompt',
                'label': 'Skills Prompt',
                'enabled': bool(system_payload.get('skills_prompt', '')),
                'tokens': _safe_count_tokens(system_payload.get('skills_prompt', ''), model=model_name),
                'content': system_payload.get('skills_prompt', ''),
            },
            {
                'name': 'conversation_system_prompt',
                'label': '当前对话系统说明',
                'enabled': bool(conversation_system_prompt),
                'tokens': _safe_count_tokens(conversation_system_prompt, model=model_name),
                'content': conversation_system_prompt,
            },
        ]
        working_memory = cm.get_working_memory() if hasattr(cm, 'get_working_memory') else {}
        long_term = cm.get_long_term_fragments() if hasattr(cm, 'get_long_term_fragments') else []
        compact_state = self.conv_store.get_compact_state(effective_conversation_id) if (self.conv_store and effective_conversation_id) else {}

        return {
            'mode': 'api',
            'conversation_id': effective_conversation_id,
            'conversation_title': (meta or {}).get('title', '未命名对话'),
            'configured_profile_key': usage.get('configured_profile_key'),
            'runtime_profile_key': usage.get('runtime_profile_key'),
            'system': {
                'inject_skills_prompt': bool(system_cfg.get('inject_skills_prompt', True)),
                'conversation_system_prompt': conversation_system_prompt,
                'final_system_prompt': final_system_prompt,
                'final_tokens': _safe_count_tokens(final_system_prompt, model=model_name),
                'system_budget': context_cfg.get('system_budget', 8000),
                'over_budget': _safe_count_tokens(final_system_prompt, model=model_name) > int(context_cfg.get('system_budget', 8000)),
                'blocks': prompt_blocks,
            },
            'working_memory': working_memory,
            'long_term': {
                'fragments': long_term,
                'count': len(long_term),
            },
            'context_config': {
                'max_window_tokens': context_cfg.get('max_window_tokens', 128000),
                'system_budget': context_cfg.get('system_budget', 8000),
                'long_term_budget': context_cfg.get('long_term_budget', 4000),
                'working_budget': context_cfg.get('working_budget', 2000),
                'short_term_budget': context_cfg.get('short_term_budget', 80000),
                'output_reserve': context_cfg.get('output_reserve', 16000),
                'max_history_turns': context_cfg.get('max_history_turns', 50),
            },
            'compact': compact_state,
            'usage': usage,
            'history_preview': cm.get_history()[-12:],
        }

    def update_conversation_system_prompt(self, content: str, conversation_id: Optional[str] = None) -> bool:
        self._ensure_init()
        if not self.conv_store:
            return False
        target_conv_id = conversation_id or self.conv_store.active_id
        if not target_conv_id:
            return False
        ok = self.conv_store.set_conversation_system_prompt(target_conv_id, content)
        if not ok:
            return False
        if target_conv_id == self.conv_store.active_id:
            self._refresh_context_manager_system_prompt(conversation_id=target_conv_id)
        return True

    def get_working_memory(self) -> dict:
        self._ensure_init()
        cm = self._get_cm()
        return cm.get_working_memory() if hasattr(cm, 'get_working_memory') else {}

    def set_working_memory(self, data: dict, conversation_id: Optional[str] = None) -> bool:
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        cm.set_working_memory(data or {})
        self._save_cm_for(cm, conversation_id)
        return True

    def clear_working_memory(self, conversation_id: Optional[str] = None) -> bool:
        return self.set_working_memory({}, conversation_id=conversation_id)

    def get_long_term_fragments(self) -> list:
        self._ensure_init()
        cm = self._get_cm()
        return cm.get_long_term_fragments() if hasattr(cm, 'get_long_term_fragments') else []

    def clear_long_term(self, conversation_id: Optional[str] = None) -> bool:
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        cm.clear_long_term()
        self._save_cm_for(cm, conversation_id)
        return True

    def get_context_status(self, conversation_id: Optional[str] = None) -> dict:
        """
        返回上下文状态，供 context_panel 显示。
        格式: {total, used, layers: {system, long_term, working, short_term, output_reserve}, turns}
        """
        self._ensure_init()
        if self.get_conversation_runtime(conversation_id) != "legacy":
            target = conversation_id or self.conv_store.active_id
            return {"runtime": "pi", "context_owner": "pi", "read_only": True,
                    "conversation_id": target, "turns": len([m for m in self._runtime_history(target) if m.get("role") == "user"]),
                    "conversation_model_usage": self.conv_store.get_model_usage(target)}
        cm = self._get_cm_for(conversation_id)
        usage = cm.get_token_usage()
        history = cm.get_history()
        turns = len([m for m in history if m["role"] == "user"])
        cfg = APIModeConfigManager.load()
        usage["turns"] = turns
        usage["conversation_id"] = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        model_usage = self.conv_store.get_model_usage(usage["conversation_id"]) if (self.conv_store and usage["conversation_id"]) else None
        usage["conversation_model_usage"] = model_usage
        usage["configured_profile_key"] = APIModeConfigManager.get_active_profile_key(cfg, usage_override=model_usage)
        usage["runtime_profile_key"] = self.current_runtime_profile_key or usage["configured_profile_key"]
        return usage

    # ============================================================
    # 配置管理
    # ============================================================

    def update_config(self, updates: dict):
        """更新配置（active profile / context / agent / system）"""
        self._ensure_init()
        if updates.get("profile"):
            APIModeConfigManager.update_active_profile(updates["profile"])
        if updates.get("context"):
            APIModeConfigManager.update_context(updates["context"])
        if updates.get("system"):
            APIModeConfigManager.update_system(updates["system"])
        if updates.get("agent"):
            APIModeConfigManager.update_agent(updates["agent"])

        self.config_dict = APIModeConfigManager.load()
        profile_key, profile, _usage = self._resolve_runtime_profile(config=self.config_dict)
        self.current_runtime_profile_key = profile_key
        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            self.provider_init_error = None
            logger.info("APISource 运行时配置切换为 browser_stateless Profile")
            return
        self._apply_profile_runtime(profile_key, persist_active=False, profile_override=profile, config=self.config_dict)

    def get_config(self) -> dict:
        """获取当前配置（隐藏 api_key）"""
        return APIModeConfigManager.get_safe_config()


    def reload_runtime_config(self):
        """
        从正式配置文件重新加载运行时配置。

        当前阶段（Phase A 最小闭环）只保证：
        - provider / model / api_key / base_url / temperature / max_output_tokens / timeout 热更新
        - 下一次 API 请求按新配置生效

        暂不保证当前活跃对话的 ContextManager 配置（如 max_window_tokens / system 组合提示词）
        完整热应用留待 Phase B 持续补强。
        """
        self._ensure_init()
        self.config_dict = APIModeConfigManager.load()
        profile_key, profile, _usage = self._resolve_runtime_profile(config=self.config_dict)
        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            self.current_runtime_profile_key = profile_key
            self.provider_init_error = None
            logger.info("APISource 运行时配置切换为 browser_stateless Profile")
            return
        self.current_runtime_profile_key = profile_key

        self._apply_profile_runtime(profile_key, persist_active=False, profile_override=profile, config=self.config_dict)

        model = profile.get("model", "unknown")
        logger.info(f"APISource 运行时配置已热重载 | model={model}")

    # ============================================================
    # 内部方法
    # ============================================================

    def _ensure_init(self):
        if not self._initialized:
            self.initialize()

    def _create_llm_provider(self, provider_payload: dict, profile_key: str = ""):
        try:
            provider = create_provider(provider_payload)
            self.provider_init_error = None
            return provider
        except Exception as e:
            info = self._classify_provider_error(e)
            self.provider_init_error = info.get("user_message") or str(e)
            logger.warning(
                "APISource Provider 创建失败，等待用户在设置页补全配置 | profile=%s | category=%s | retryable=%s | error=%s",
                profile_key,
                info.get("category"),
                info.get("retryable"),
                e,
            )
            return None

    def _get_cm(self) -> ContextManager:
        """获取当前活跃的ContextManager"""
        if self.conv_store:
            self.conv_store.require_legacy()
        if not self.conv_store or not self.conv_store.context_manager:
            raise RuntimeError("APISource 未初始化或无活跃对话")
        return self.conv_store.context_manager

    def _get_cm_for(self, conversation_id: Optional[str] = None) -> ContextManager:
        """获取指定对话的 ContextManager；不传时返回当前活跃对话。"""
        if not conversation_id:
            return self._get_cm()
        if not self.conv_store:
            raise RuntimeError("APISource 未初始化")
        cm = self.conv_store.build_context_manager_for(conversation_id)
        if not cm:
            raise RuntimeError(f"未找到指定 API 对话: {conversation_id}")
        return cm

    def get_runtime_profile(self) -> dict:
        self._ensure_init()
        cfg = APIModeConfigManager.load()
        profile_key, profile, usage = self._resolve_runtime_profile(config=cfg)
        profile.setdefault("name", profile_key)
        profile["_profile_key"] = profile_key
        profile["_usage_override"] = usage
        return profile

    def probe_tool_support(self, conversation_id: Optional[str] = None) -> dict:
        """探测当前 HTTP API Profile 是否支持原生 tools，并写回 profile capability。"""
        self._ensure_init()
        cfg = APIModeConfigManager.load()
        profile_key, profile, _usage = self._resolve_runtime_profile(conversation_id=conversation_id, config=cfg)
        if profile.get("kind") == "browser_stateless":
            capability = {
                "status": TOOL_CAPABILITY_UNSUPPORTED,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": "browser_stateless_profile",
                "protocol": TOOL_PROTOCOL_MARKDOWN_ONLY,
            }
            APIModeConfigManager.update_profile_tool_capability(profile_key, capability)
            self.config_dict = APIModeConfigManager.load()
            return {"profile_key": profile_key, **capability}
        self._apply_profile_runtime(profile_key, persist_active=False, profile_override=profile, config=cfg)
        if not self.llm_provider or not hasattr(self.llm_provider, "probe_tool_support"):
            capability = {
                "status": TOOL_CAPABILITY_UNSUPPORTED,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": "provider_unavailable",
                "protocol": "markdown_fallback",
            }
        else:
            capability = dict(self.llm_provider.probe_tool_support() or {})
            capability["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        APIModeConfigManager.update_profile_tool_capability(profile_key, capability)
        self.config_dict = APIModeConfigManager.load()
        logger.info(
            "[APISource] tool capability probe | profile=%s status=%s protocol=%s reason=%s",
            profile_key,
            capability.get("status", ""),
            capability.get("protocol", ""),
            str(capability.get("reason", ""))[:120],
        )
        return {"profile_key": profile_key, **capability}

    def _provider_model_catalog(self, profile: dict) -> dict:
        provider = str(profile.get("provider", "") or "").strip().lower()
        base_url = str(profile.get("base_url", "") or "").strip().lower()
        if provider == "mimo" or "xiaomimimo.com" in base_url:
            return {
                "models": list(MIMO_MODELS),
                "source": "provider_catalog",
                "catalog_name": "xiaomi_mimo_official",
            }
        return {"models": [], "source": "", "catalog_name": ""}

    def _filter_models_for_profile(self, profile: dict, models: list) -> dict:
        normalized = [str(m).strip() for m in (models or []) if str(m).strip()]
        provider = str(profile.get("provider", "") or "").strip().lower()
        base_url = str(profile.get("base_url", "") or "").strip().lower()
        if provider == "mimo" or "xiaomimimo.com" in base_url:
            chat_models = [
                model for model in normalized
                if "-asr" not in model.lower() and "-tts" not in model.lower()
            ]
            order = {model: idx for idx, model in enumerate(MIMO_MODELS)}
            chat_models = sorted(chat_models, key=lambda model: (order.get(model, len(order)), model))
            return {
                "models": chat_models or normalized,
                "filtered": bool(chat_models and len(chat_models) != len(normalized)),
                "raw_count": len(normalized),
            }
        return {
            "models": normalized,
            "filtered": False,
            "raw_count": len(normalized),
        }

    def probe_available_models(self, conversation_id: Optional[str] = None) -> dict:
        """探测当前 API Profile 暴露的模型列表。"""
        self._ensure_init()
        cfg = APIModeConfigManager.load()
        profile_key, profile, _usage = self._resolve_runtime_profile(conversation_id=conversation_id, config=cfg)
        if profile.get("kind") == "browser_stateless":
            return {
                "ok": False,
                "profile_key": profile_key,
                "models": [],
                "reason": "browser_stateless_profile",
            }
        self._apply_profile_runtime(profile_key, persist_active=False, profile_override=profile, config=cfg)
        if not self.llm_provider or not hasattr(self.llm_provider, "list_models"):
            catalog = self._provider_model_catalog(profile)
            if catalog["models"]:
                return {
                    "ok": True,
                    "profile_key": profile_key,
                    "provider": profile.get("provider", "openai_compatible"),
                    "current_model": profile.get("model", ""),
                    "models": catalog["models"],
                    "reason": self.provider_init_error or "provider_unavailable_using_provider_catalog",
                    "source": catalog["source"],
                    "catalog_name": catalog["catalog_name"],
                    "endpoint_ok": False,
                }
            return {
                "ok": False,
                "profile_key": profile_key,
                "models": [],
                "reason": self.provider_init_error or "provider_unavailable",
            }
        result = dict(self.llm_provider.list_models() or {})
        models = [str(m).strip() for m in (result.get("models") or []) if str(m).strip()]
        if models:
            filtered = self._filter_models_for_profile(profile, models)
            result["models"] = filtered["models"]
            if filtered["filtered"]:
                result["source"] = "models_endpoint_filtered"
                result["raw_model_count"] = filtered["raw_count"]
        else:
            catalog = self._provider_model_catalog(profile)
            if catalog["models"]:
                endpoint_reason = str(result.get("reason", "") or "models_endpoint_empty")
                result.update({
                    "ok": True,
                    "models": catalog["models"],
                    "reason": endpoint_reason,
                    "source": catalog["source"],
                    "catalog_name": catalog["catalog_name"],
                    "endpoint_ok": bool(result.get("endpoint_ok")),
                })
        result["profile_key"] = profile_key
        result["provider"] = profile.get("provider", "openai_compatible")
        result["current_model"] = profile.get("model", "")
        logger.info(
            "[APISource] model probe | profile=%s ok=%s count=%d reason=%s",
            profile_key,
            bool(result.get("ok")),
            len(result.get("models") or []),
            str(result.get("reason", ""))[:120],
        )
        return result

    def _resolve_profile_key(self, conversation_id: Optional[str] = None, config: Optional[dict] = None) -> str:
        cfg = config or self.config_dict or APIModeConfigManager.load()
        conv_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        usage = self.conv_store.get_model_usage(conv_id) if (self.conv_store and conv_id) else None
        return APIModeConfigManager.get_active_profile_key(cfg, usage_override=usage)

    def _get_system_prompt_role(self, conversation_id: Optional[str] = None) -> str:
        cfg = self.config_dict or APIModeConfigManager.load()
        profile_key = self._resolve_profile_key(conversation_id=conversation_id, config=cfg)
        profile = cfg.get("profiles", {}).get(profile_key, {}) or {}
        role = str(profile.get("system_prompt_role", "system") or "system").strip().lower()
        return role if role in ("system", "developer") else "system"

    def _get_tool_protocol(self, conversation_id: Optional[str] = None, config: Optional[dict] = None) -> str:
        cfg = config or self.config_dict or APIModeConfigManager.load()
        profile_key = self._resolve_profile_key(conversation_id=conversation_id, config=cfg)
        profile = cfg.get("profiles", {}).get(profile_key, {}) or {}
        return APIModeConfigManager.resolve_tool_protocol(profile)

    def _build_request_messages(self, cm: ContextManager, conversation_id: Optional[str] = None) -> list:
        messages = cm.build_messages(system_prompt_role=self._get_system_prompt_role(conversation_id=conversation_id))
        return self._project_messages_for_chat_api(messages)

    def _project_messages_for_chat_api(self, messages: list) -> list:
        """Project internal message kinds into chat-completions-compatible payloads."""
        projected = []
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "") or "").strip()
            if role == "tool_feedback" or str(msg.get("kind", "") or "").strip() == "tool_feedback":
                projected.append({
                    "role": "system",
                    "content": "[工具回流]\n" + str(msg.get("content", "") or ""),
                })
                continue
            projected.append({
                "role": role or "user",
                "content": str(msg.get("content", "") or ""),
            })
        return projected

    def build_current_request_messages(self, conversation_id: Optional[str] = None) -> list:
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        return self._build_request_messages(cm, conversation_id=conversation_id)

    def prepare_browser_stateless_request_context(self, conversation_id: Optional[str] = None) -> dict:
        """准备浏览器 Profile 请求可用的完整 API 上下文。"""
        self._ensure_init()
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        self._refresh_context_manager_system_prompt(conversation_id=target_id)
        self._inject_journal_long_term(conversation_id=target_id)
        self._maybe_compact_context(conversation_id=target_id)
        return {
            "conversation_id": target_id,
            "messages": self.build_current_request_messages(conversation_id=target_id),
            "context_status": self.get_context_status(conversation_id=target_id),
        }

    def append_user_message(self, content: str, conversation_id: Optional[str] = None) -> bool:
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        cm.add_structured_message("user", content, kind=MESSAGE_KIND_TEXT, source_mode="api")
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        if self.conv_store and target_id:
            self.conv_store.touch_last_message_at(target_id)
        self._save_cm_for(cm, conversation_id)
        return True

    def _save_cm_for(self, cm: ContextManager, conversation_id: Optional[str] = None):
        """保存指定对话的 ContextManager；不传时保存当前活跃对话。"""
        if not self.conv_store:
            return
        self.conv_store.require_legacy(conversation_id)
        if not conversation_id:
            self.conv_store.context_manager = cm
            self.conv_store.save_current()
            return
        if conversation_id == self.conv_store.active_id:
            self.conv_store.context_manager = cm
            self.conv_store.save_current()
            return
        self.conv_store.save_context_manager_for(conversation_id, cm)

    def _auto_title(self, text: str):
        """首条消息自动设置对话标题"""
        if self.conv_store.active_id:
            cm = self._get_cm()
            user_msgs = [m for m in cm.get_history() if m["role"] == "user"]
            if len(user_msgs) <= 1:
                self.conv_store.auto_title(self.conv_store.active_id, text)
