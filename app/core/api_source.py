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
from typing import Optional, List, AsyncIterator

import tiktoken

from app.core.context_manager import ContextManager, ContextConfig
from app.core.context_message_models import (
    MESSAGE_KIND_TEXT,
)
from app.core.conversation_store import ConversationStore
from app.core.context_compaction import ContextCompactionOrchestrator
from app.core.llm_provider import create_provider, LLMProvider
from app.core.config import ConfigManager
from app.core.api_mode_config import APIModeConfigManager
from app.core.prompt_runtime import build_final_system_prompt
from app.core.journal_index import JournalIndex, extract_search_keywords
from app.core.parsers.markdown_code_block_parser import MarkdownCodeBlockParser
from app.core.app_constants import APP_ROOT, DEFAULT_API_BASE_URL, DEFAULT_API_MODEL
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

        profile_key = self._resolve_profile_key()
        profile = self.config_dict.get("profiles", {}).get(profile_key, {})
        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            self.current_runtime_profile_key = profile_key
            self._initialized = True
            logger.info("APISource 初始化为 browser_stateless Profile，LLM provider 由浏览器适配器接管")
            return
        provider_kind = profile.get("provider", "openai_compatible")
        provider_common = {
            "api_key": profile.get("api_key", ""),
            "base_url": profile.get("base_url", DEFAULT_API_BASE_URL),
            "model": profile.get("model", DEFAULT_API_MODEL),
            "temperature": profile.get("temperature", 0.7),
            "max_output_tokens": profile.get("max_output_tokens", 4096),
            "timeout": profile.get("timeout", 60),
            "proxy_url": profile.get("proxy_url", ""),
        }
        provider_payload = {
            "provider": provider_kind,
            "api": provider_common,
            "gemini": provider_common,
        }
        self.llm_provider = create_provider(provider_payload)
        self.current_runtime_profile_key = profile_key
        self._initialized = True
        model = profile.get("model", "unknown")
        logger.info(f"APISource 初始化完成 | model={model}")
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
        except Exception as e:
            logger.warning('[APISource] snapshot capture failed: %s', e)

    def _get_snapshot_ref(self, conversation_id: Optional[str] = None) -> Optional[dict]:
        snap = self._last_request_snapshot
        if not snap:
            return None
        if conversation_id and snap.get('conversation_id') != conversation_id:
            return None
        return snap

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
            return True
        except Exception as e:
            logger.warning('[APISource] append snapshot round failed: %s', e)
            return False

    def capture_snapshot_messages(self, phase: str, conversation_id: Optional[str] = None) -> bool:
        try:
            cm = self._get_cm_for(conversation_id)
            messages = cm.build_messages()
            snap = self._get_snapshot_ref(conversation_id)
            if not snap:
                return False
            self.append_snapshot_round(phase, {'messages': messages}, conversation_id=conversation_id)
            snap['final_messages'] = messages
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
            return True
        except Exception as e:
            logger.warning('[APISource] finalize round snapshot failed: %s', e)
            return False

    def get_last_request_snapshot(self, conversation_id: Optional[str] = None) -> Optional[dict]:
        """获取最近一次请求的完整上下文快照。"""
        snap = self._last_request_snapshot
        if snap is None:
            return None
        if conversation_id and snap.get('conversation_id') != conversation_id:
            return None
        return snap

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
            logger.warning(
                "[APISource] context compaction skipped_or_failed | conversation_id=%s | reason=%s | error=%s",
                target_id,
                result.get("reason", "unknown"),
                result.get("error", ""),
            )
        return result

    def trigger_manual_compact(self, conversation_id: Optional[str] = None) -> dict:
        self._ensure_init()
        target_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
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

    def send_message_sync(self, text: str) -> str:
        """同步发送消息，返回完整回复"""
        self._ensure_init()
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

        messages = cm.build_messages()
        self._capture_request_snapshot(messages)
        self.set_round_state('streaming_initial_reply')
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

    async def send_message_stream(self, text: str) -> AsyncIterator[str]:
        """流式发送消息，逐块yield回复"""
        self._ensure_init()
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

        messages = cm.build_messages()
        self._capture_request_snapshot(messages)
        self.set_round_state('streaming_initial_reply')
        full_reply = ""
        try:
            async for chunk in self._chat_with_fallback_stream(messages):
                full_reply += chunk
                yield chunk
            if self._last_request_snapshot:
                self._last_request_snapshot['response'] = full_reply
                self.append_snapshot_round('initial_reply', {'assistant_reply': full_reply})
                self.set_snapshot_final_reply(full_reply)
            cm.add_structured_message("assistant", full_reply, kind=MESSAGE_KIND_TEXT, source_mode="api")
            if self.conv_store and self.conv_store.active_id:
                self.conv_store.touch_last_message_at(self.conv_store.active_id)
            self.conv_store.save_current()
        except Exception as e:
            logger.error(f"流式调用失败: {e}")
            probe("api_source_stream_error", level="error", side="worker", error=str(e))
            if full_reply:
                cm.add_structured_message("assistant", full_reply + f"\n\n[错误中断: {e}]", kind=MESSAGE_KIND_TEXT, source_mode="api")
                self.conv_store.save_current()
            raise

    def _apply_profile_runtime(self, profile_key: str, persist_active: bool = True):
        cfg = APIModeConfigManager.load()
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
        profile = profiles[profile_key]

        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            logger.info(f"APISource 已切换为 browser_stateless Profile | active={profile_key}")
            return

        provider_kind = profile.get("provider", "openai_compatible")
        needs_rebuild = False
        current_provider_name = self.llm_provider.__class__.__name__ if self.llm_provider else ''
        if provider_kind == 'gemini' and current_provider_name != 'GeminiProvider':
            needs_rebuild = True
        if provider_kind in ('api', 'openai_compatible') and current_provider_name != 'APIProvider':
            needs_rebuild = True

        if needs_rebuild:
            provider_payload = {
                "provider": provider_kind,
                "api": {
                    "api_key": profile.get("api_key", ""),
                    "base_url": profile.get("base_url", DEFAULT_API_BASE_URL),
                    "model": profile.get("model", DEFAULT_API_MODEL),
                    "temperature": profile.get("temperature", 0.7),
                    "max_output_tokens": profile.get("max_output_tokens", 4096),
                    "timeout": profile.get("timeout", 60),
                    "proxy_url": profile.get("proxy_url", ""),
                },
                "gemini": {
                    "api_key": profile.get("api_key", ""),
                    "base_url": profile.get("base_url", DEFAULT_API_BASE_URL),
                    "model": profile.get("model", DEFAULT_API_MODEL),
                    "temperature": profile.get("temperature", 0.7),
                    "max_output_tokens": profile.get("max_output_tokens", 4096),
                    "timeout": profile.get("timeout", 60),
                    "proxy_url": profile.get("proxy_url", ""),
                }
            }
            self.llm_provider = create_provider(provider_payload)
        elif self.llm_provider and hasattr(self.llm_provider, "update_config"):
            self.llm_provider.update_config(
                api_key=profile.get("api_key", ""),
                base_url=profile.get("base_url", DEFAULT_API_BASE_URL),
                model=profile.get("model", DEFAULT_API_MODEL),
                temperature=profile.get("temperature", 0.7),
                max_output_tokens=profile.get("max_output_tokens", 4096),
                timeout=profile.get("timeout", 60),
                proxy_url=profile.get("proxy_url", ""),
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
        err_msg = str(e).lower()
        retryable_keywords = ["429", "529", "503", "502", "rate limit", "too many requests", "overloaded"]
        return any(k in err_msg for k in retryable_keywords)

    def _chat_with_fallback_sync(self, messages: list) -> str:
        self._ensure_init()
        cfg = APIModeConfigManager.load()
        active = self._resolve_profile_key()
        attempts = [active] + self._get_fallback_candidates()
        errors = []

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
                        }
                        logger.warning(f"APISource fallback 切换成功，准备重试 | from={previous_profile} | to={profile_key}")
                    return self.llm_provider.chat(messages)
                except Exception as e:
                    import time
                    if attempt < max_retries and hasattr(self, 'is_retryable_error') and self.is_retryable_error(e):
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"[{profile_key}] 同步调用遭遇限流({e}), 等待 {delay}s 后重试 (第{attempt+1}/{max_retries}次)...")
                        time.sleep(delay)
                        continue
                    errors.append(f"{profile_key}: {e}")
                    logger.error(f"APISource 同步调用失败 | profile={profile_key} | error={e}")
                    break

        raise RuntimeError("API 调用失败，且 fallback chain 全部尝试失败: " + " | ".join(errors))

    async def _chat_with_fallback_stream(self, messages: list) -> AsyncIterator[str]:
        self._ensure_init()
        cfg = APIModeConfigManager.load()
        active = self._resolve_profile_key()
        attempts = [active] + self._get_fallback_candidates()
        errors = []

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
                        }
                        logger.warning(f"APISource fallback 切换成功，准备流式重试 | from={previous_profile} | to={profile_key}")
                    
                    async for chunk in self.llm_provider.stream_chat(messages):
                        yield chunk
                    return
                except Exception as e:
                    import asyncio
                    if attempt < max_retries and hasattr(self, 'is_retryable_error') and self.is_retryable_error(e):
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"[{profile_key}] 流式调用遭遇限流({e}), 等待 {delay}s 后重试 (第{attempt+1}/{max_retries}次)...")
                        await asyncio.sleep(delay)
                        continue
                    
                    errors.append(f"{profile_key}: {e}")
                    logger.error(f"APISource 流式调用失败 | profile={profile_key} | error={e}")
                    break

        raise RuntimeError("API 流式调用失败，且 fallback chain 全部尝试失败: " + " | ".join(errors))
    def get_last_reply_as_segments(self, reply_text: str) -> list:
        """
        将 AI 回复转换为与浏览器消息兼容的 segments 格式。
        worker.py 的 messages_signal 和 process_batch 都依赖这个格式。
        """
        return MarkdownCodeBlockParser.parse_segments(reply_text)

    def build_message_for_signal(self, role: str, content: str, index: int = 0, kind: str = "text", meta: Optional[dict] = None, raw_content: str = "", segments: Optional[list] = None) -> dict:
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
            
        final_raw = raw_content if isinstance(raw_content, str) and raw_content else content
        return {
            "role": "AI" if role == "assistant" else "User",
            "index": index,
            "segments": final_segments,
            "id": self.conv_store.active_id or "default",
            "conversation_id": self.conv_store.active_id or "default",
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

    def continue_assistant_reply_sync(self, conversation_id: Optional[str] = None) -> str:
        """基于当前上下文继续生成一条 assistant 回复，不追加新的 user 消息。"""
        self._ensure_init()
        self.last_fallback_event = None
        self._refresh_context_manager_system_prompt(conversation_id=conversation_id)
        cm = self._get_cm_for(conversation_id)
        self._maybe_compact_context(conversation_id=conversation_id)
        cm = self._get_cm_for(conversation_id)
        messages = cm.build_messages()
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

    def create_conversation(self, title: str = "新对话", system_prompt: str = "") -> str:
        """创建新对话，返回对话ID"""
        self._ensure_init()
        prompt = system_prompt or self.config_dict.get("conversation_defaults", {}).get("system", {}).get("user_prompt") or DEFAULT_SYSTEM_PROMPT
        conv_id = self.conv_store.create(title, system_prompt=prompt)
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
        return bool(self.conv_store and self.conv_store.active_id and self.conv_store.context_manager)

    def get_history(self) -> list:
        """获取当前对话的消息历史"""
        self._ensure_init()
        cm = self._get_cm()
        return cm.get_history()

    def get_history_as_messages(self) -> list:
        """
        获取历史并转换为 messages_signal 兼容格式。
        用于切换到API对话时一次性渲染所有历史。
        """
        self._ensure_init()
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
            ))
        return messages

    def get_history_as_messages_for(self, conversation_id: Optional[str] = None) -> list:
        """获取指定对话历史并转换为 messages_signal 兼容格式。"""
        self._ensure_init()
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
                segments=msg.get("segments", [])
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
        profile_key = self._resolve_profile_key()
        self.current_runtime_profile_key = profile_key
        profile = self.config_dict.get("profiles", {}).get(profile_key, {})
        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            logger.info("APISource 运行时配置切换为 browser_stateless Profile")
            return
        if hasattr(self.llm_provider, "update_config"):
            self.llm_provider.update_config(
                api_key=profile.get("api_key", ""),
                base_url=profile.get("base_url", DEFAULT_API_BASE_URL),
                model=profile.get("model", DEFAULT_API_MODEL),
                temperature=profile.get("temperature", 0.7),
                max_output_tokens=profile.get("max_output_tokens", 4096),
                timeout=profile.get("timeout", 60),
            )

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
        profile_key = self._resolve_profile_key()
        profile = self.config_dict.get("profiles", {}).get(profile_key, {})
        if profile.get("kind") == "browser_stateless":
            self.llm_provider = None
            self.current_runtime_profile_key = profile_key
            logger.info("APISource 运行时配置切换为 browser_stateless Profile")
            return
        self.current_runtime_profile_key = profile_key

        if self.llm_provider and hasattr(self.llm_provider, "update_config"):
            self.llm_provider.update_config(
                api_key=profile.get("api_key", ""),
                base_url=profile.get("base_url", DEFAULT_API_BASE_URL),
                model=profile.get("model", DEFAULT_API_MODEL),
                temperature=profile.get("temperature", 0.7),
                max_output_tokens=profile.get("max_output_tokens", 4096),
                timeout=profile.get("timeout", 60),
            )

        model = profile.get("model", "unknown")
        logger.info(f"APISource 运行时配置已热重载 | model={model}")

    # ============================================================
    # 内部方法
    # ============================================================

    def _ensure_init(self):
        if not self._initialized:
            self.initialize()

    def _get_cm(self) -> ContextManager:
        """获取当前活跃的ContextManager"""
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
        profile_key = self._resolve_profile_key(config=cfg)
        profile = dict(cfg.get("profiles", {}).get(profile_key, {}))
        profile.setdefault("name", profile_key)
        profile["_profile_key"] = profile_key
        return profile

    def _resolve_profile_key(self, conversation_id: Optional[str] = None, config: Optional[dict] = None) -> str:
        cfg = config or self.config_dict or APIModeConfigManager.load()
        conv_id = conversation_id or (self.conv_store.active_id if self.conv_store else None)
        usage = self.conv_store.get_model_usage(conv_id) if (self.conv_store and conv_id) else None
        return APIModeConfigManager.get_active_profile_key(cfg, usage_override=usage)

    def build_current_request_messages(self, conversation_id: Optional[str] = None) -> list:
        self._ensure_init()
        cm = self._get_cm_for(conversation_id)
        return cm.build_messages()

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
        if not conversation_id:
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

