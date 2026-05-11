# filename: app/core/browser_sync/normalizer.py
"""DOM Normalizer：将浏览器增量提取结果转换为 canonical message。

职责：
1. 给每条消息分配稳定 ordinal
2. 给每个 segment 分配稳定 segment_id
3. 计算 content_hash（消息级 + segment 级）
4. 管理 rev 递增
5. 无 DOM ID 消息的稳定匹配
6. 双 probe 防抖
"""

import hashlib
import json
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

from .models import CanonicalMessage, CanonicalSegment

logger = logging.getLogger(__name__)


def _make_segment_id(message_id: str, seg_type: str, ordinal: int) -> str:
    return f"seg_{message_id}_{seg_type}_{ordinal}"


_STRIP_HTML_RE = re.compile(r"<[^>]+>")


def _strip_html_tags(text: str) -> str:
    """剥离 HTML 标签，保留纯文本内容。"""
    if "<" not in text:
        return text
    text = _STRIP_HTML_RE.sub("", text)
    return text.strip()


def _compute_segment_hash(seg_type: str, content: str) -> str:
    raw = f"{seg_type}:{content}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _compute_message_hash(segments: List[CanonicalSegment]) -> str:
    parts = [f"{s.type}:{s.content_hash}" for s in segments]
    raw = "|".join(parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


class DOMNormalizer:
    """DOM 提取结果 → CanonicalMessage 转换器。

    持有上一轮的 canonical 状态，用于：
    - 判断 rev 是否需要递增
    - 无 DOM ID 消息的稳定匹配
    - content_hash 变化检测
    """

    ACTIVE_TAIL_SIZE = 4

    def __init__(self):
        self._prev_messages_by_id: Dict[str, CanonicalMessage] = {}
        self._fallback_id_map: Dict[str, str] = {}
        self._probe_signature_a: Optional[str] = None
        self._probe_signature_b: Optional[str] = None
        self._raw_cache: Dict[str, str] = {}
        self._processed_cache: Dict[str, CanonicalMessage] = {}

    def clear(self):
        self._prev_messages_by_id.clear()
        self._fallback_id_map.clear()
        self._probe_signature_a = None
        self._probe_signature_b = None
        self._raw_cache.clear()
        self._processed_cache.clear()

    def normalize_messages(
        self,
        raw_messages: List[dict],
        conversation_id: str = "",
        round_id: str = "",
        force_full: bool = False,
    ) -> Tuple[List[CanonicalMessage], List[str], List[str]]:
        """增量 normalize：尾部 N 条原生消息重新处理，其余取缓存。

        返回 (canonical_messages, changed_ids, removed_ids):
          - canonical_messages: 完整的消息列表（含冻结+活跃）
          - changed_ids: 本轮新增或内容变化的消息 id 列表（用于增量推送）
          - removed_ids: 本轮应从客户端移除的消息 id 列表

        force_full=True 时全量处理（重启/切换对话/切换模式）。
        """
        if not raw_messages:
            return [], [], []

        if force_full or not self._processed_cache:
            return self._full_normalize(raw_messages, conversation_id, round_id)

        total = len(raw_messages)
        active_start = max(0, total - self.ACTIVE_TAIL_SIZE)

        frozen_msgs = []
        active_raw = []

        for i, raw in enumerate(raw_messages):
            raw_id = str(raw.get("id", "") or "")
            role = str(raw.get("role", "") or "")
            msg_key = f"{raw_id}:{role}" if raw_id else ""
            if i < active_start and msg_key and msg_key in self._processed_cache:
                frozen_msgs.append(self._processed_cache[msg_key])
            else:
                active_raw.append((i, raw))

        result = list(frozen_msgs)
        newly_processed = []
        for ordinal, raw in active_raw:
            msg = self._normalize_one(raw, ordinal, conversation_id, round_id)
            result.append(msg)
            newly_processed.append(msg)

        result.sort(key=lambda m: m.ordinal)

        self._bind_tool_feedback_to_ai(result, conversation_id, round_id)

        for msg in newly_processed:
            self._processed_cache[msg.id] = msg
            self._raw_cache[msg.id] = msg.content_hash

        newly_bound_ids = set(id(m) for m in newly_processed)
        changed_ids = [msg.id for msg in newly_processed]
        for msg in result:
            if id(msg) in newly_bound_ids:
                continue
            cached = self._processed_cache.get(msg.id)
            if cached and cached.content_hash != msg.content_hash:
                changed_ids.append(msg.id)
                self._processed_cache[msg.id] = msg
                self._raw_cache[msg.id] = msg.content_hash

        _fb_count = sum(1 for m in result if m.id.startswith("msg_fb_"))
        _hidden_count = sum(1 for m in result if m.extra.get("_hidden"))
        _active_count = len(active_raw)
        logger.info(
            "[Normalizer] 增量转换完成 | total=%s | frozen=%s | active=%s | changed=%s | hidden=%s",
            total, len(frozen_msgs), _active_count, len(changed_ids), _hidden_count,
        )

        removed_ids = self._detect_removed_ids(active_raw, newly_processed)
        for rid in removed_ids:
            self._processed_cache.pop(rid, None)
            self._raw_cache.pop(rid, None)

        return result, changed_ids, removed_ids

    def _full_normalize(
        self,
        raw_messages: List[dict],
        conversation_id: str,
        round_id: str,
    ) -> Tuple[List[CanonicalMessage], List[str], List[str]]:
        """全量 normalize：所有消息重新处理，重建缓存。"""
        result = []
        for ordinal, raw in enumerate(raw_messages):
            msg = self._normalize_one(raw, ordinal, conversation_id, round_id)
            result.append(msg)

        self._bind_tool_feedback_to_ai(result, conversation_id, round_id)

        old_ids = set(self._processed_cache.keys())
        self._processed_cache.clear()
        self._raw_cache.clear()
        for msg in result:
            self._processed_cache[msg.id] = msg
            self._raw_cache[msg.id] = msg.content_hash

        new_ids = {m.id for m in result}
        removed_ids = [rid for rid in old_ids if rid not in new_ids]

        _fb_count = sum(1 for m in result if m.id.startswith("msg_fb_"))
        _hidden_count = sum(1 for m in result if m.extra.get("_hidden"))
        _rev_changes = []
        for m in result:
            prev = self._prev_messages_by_id.get(m.id)
            if prev and prev.rev != m.rev:
                _rev_changes.append(f"{m.id[:12]}:{prev.rev}→{m.rev}")
        logger.info(
            "[Normalizer] 全量转换完成 | messages=%s | fallback_id=%s | hidden=%s | removed=%s | rev变化=[%s]",
            len(result), _fb_count, _hidden_count, len(removed_ids), " | ".join(_rev_changes),
        )
        return result, [m.id for m in result], removed_ids

    def _detect_removed_ids(
        self,
        active_raw: List[tuple],
        newly_processed: List[CanonicalMessage],
    ) -> List[str]:
        """检测本轮被替换的消息 ID。

        当 active_raw 区间的消息 ID 与 _processed_cache 中同 ordinal 位置的
        消息 ID 不同时，说明 DOM 发生了整批替换，旧 ID 应标记为移除。
        """
        active_ordinals = {ordinal for ordinal, _ in active_raw}
        new_ids = {m.id for m in newly_processed}
        removed = []
        for msg_id, cached_msg in list(self._processed_cache.items()):
            if cached_msg.ordinal in active_ordinals and msg_id not in new_ids:
                removed.append(msg_id)
        if removed:
            logger.info(
                "[Normalizer] 检测到消息替换 | removed=%s | active_ordinals=%s",
                [rid[:12] for rid in removed],
                sorted(active_ordinals),
            )
        return removed

    def _bind_tool_feedback_to_ai(
        self,
        messages: List[CanonicalMessage],
        conversation_id: str,
        round_id: str,
    ):
        """服务端绑定：将工具回流消息的 tool_result 绑定到 AI 消息的 tool_call segment。

        绑定优先级：
        1. tool_call_id 精确匹配（全局）
        2. block_key 匹配（全局）
        3. 顺序匹配：在紧邻的前一条 AI 消息内，未绑定的 tool_call 数量 == tool_result 数量 → 按序配对
        4. 最终兜底：数量不一致 → 每个 tool_result 拆为独立 AI 消息

        绑定成功 → 工具回流消息标记 _hidden，提取 user_message 为独立消息
        """
        ai_tool_call_map: Dict[str, CanonicalSegment] = {}
        ai_block_key_map: Dict[str, CanonicalSegment] = {}
        bound_seg_set = set()
        for msg in messages:
            if msg.role != "AI":
                continue
            for seg in msg.segments:
                if not self._is_tool_call_anchor(seg):
                    continue
                if seg.tool_call_id:
                    ai_tool_call_map[seg.tool_call_id] = seg
                if seg.block_key:
                    ai_block_key_map[seg.block_key] = seg

        msg_index = {id(m): i for i, m in enumerate(messages)}

        extra_messages = []
        for msg in messages:
            if msg.role != "User":
                continue
            if msg.extra.get("_hidden"):
                continue
            has_tool_result = any(s.type in ("tool_result", "tool_call") for s in msg.segments)
            if not has_tool_result:
                continue

            user_message_segs = [s for s in msg.segments if s.type == "user_message"]
            tool_result_segs = [s for s in msg.segments if s.type == "tool_result"]

            # 第一轮：tool_call_id / block_key 精确匹配
            bound_count = 0
            unmatched_results = []
            for tr_seg in tool_result_segs:
                target_seg = None
                if tr_seg.tool_call_id and tr_seg.tool_call_id in ai_tool_call_map:
                    target_seg = ai_tool_call_map[tr_seg.tool_call_id]
                elif tr_seg.block_key and tr_seg.block_key in ai_block_key_map:
                    target_seg = ai_block_key_map[tr_seg.block_key]

                if target_seg is None:
                    unmatched_results.append(tr_seg)
                    continue

                if "_bound_results" not in target_seg.extra:
                    target_seg.extra["_bound_results"] = []
                target_seg.extra["_bound_results"].append(tr_seg.to_dict())
                bound_seg_set.add(id(target_seg))
                bound_count += 1

            # 第二轮：顺序匹配兜底 — 在紧邻的前一条 AI 消息内配对
            if unmatched_results:
                prev_ai_msg = self._find_preceding_ai_message(
                    messages, msg_index, msg,
                )
                if prev_ai_msg is not None:
                    unbound_in_prev = [
                        s for s in prev_ai_msg.segments
                        if self._is_tool_call_anchor(s)
                        and id(s) not in bound_seg_set
                    ]
                    if len(unbound_in_prev) == len(unmatched_results):
                        for ai_seg, tr_seg in zip(unbound_in_prev, unmatched_results):
                            if "_bound_results" not in ai_seg.extra:
                                ai_seg.extra["_bound_results"] = []
                            ai_seg.extra["_bound_results"].append(tr_seg.to_dict())
                            bound_seg_set.add(id(ai_seg))
                            bound_count += 1
                        unmatched_results = []
                        logger.info(
                            "[Normalizer] 顺序匹配兜底成功 | msg=%s | prev_ai=%s | matched=%s",
                            msg.id[:12], prev_ai_msg.id[:12], len(unbound_in_prev),
                        )
                    else:
                        logger.warning(
                            "[Normalizer] 顺序匹配数量不一致 | msg=%s | prev_ai=%s | unbound_ai=%s | unmatched_results=%s",
                            msg.id[:12], prev_ai_msg.id[:12],
                            len(unbound_in_prev), len(unmatched_results),
                        )

            # 第三轮：最终兜底 — 每个 tool_result 拆为独立 AI 消息
            if unmatched_results:
                for tr_seg in unmatched_results:
                    fallback_msg = self._make_fallback_ai_message(
                        tr_seg, msg.ordinal, conversation_id, round_id,
                    )
                    extra_messages.append(fallback_msg)
                logger.warning(
                    "[Normalizer] 工具回流最终兜底：拆分为独立AI消息 | msg=%s | count=%s",
                    msg.id[:12], len(unmatched_results),
                )

            if bound_count > 0:
                msg.extra["_hidden"] = True
                msg.extra["_tool_feedback"] = True
                logger.info(
                    "[Normalizer] 工具回流绑定成功 | msg=%s | bound=%s | user_segs=%s",
                    msg.id[:12], bound_count, len(user_message_segs),
                )
            else:
                msg.extra["_hidden"] = True
                msg.extra["_tool_feedback"] = True
                msg.extra["_fallback_all_split"] = True
                logger.warning(
                    "[Normalizer] 工具回流全部拆分为独立AI消息 | msg=%s | tool_results=%s",
                    msg.id[:12], len(tool_result_segs),
                )

            if user_message_segs:
                user_content = "\n".join(s.content for s in user_message_segs if s.content)
                if user_content:
                    user_msg = self._make_user_message(
                        user_content, msg.ordinal, conversation_id, round_id,
                    )
                    extra_messages.append(user_msg)

        if extra_messages:
            messages.extend(extra_messages)
            messages.sort(key=lambda m: m.ordinal)

        for msg in messages:
            if msg.role != "AI":
                continue
            bound_segs = [
                s for s in msg.segments
                if "_bound_results" in s.extra and s.extra["_bound_results"]
            ]
            if not bound_segs:
                continue
            for seg in bound_segs:
                seg.content_hash = seg.compute_content_hash()
            old_hash = msg.content_hash
            new_hash = msg.compute_content_hash()
            if new_hash != old_hash:
                msg.content_hash = new_hash
                msg.rev += 1

    @staticmethod
    def _is_tool_call_anchor(seg: CanonicalSegment) -> bool:
        """Return True only for segments that render as executable tool-call cards."""
        if seg is None:
            return False
        if seg.type == "tool_call":
            return True
        language = str(seg.language or "").strip().lower().replace("-", "_")
        if seg.type == "code" and language == "tool_call":
            return True
        if seg.type == "code" and seg.tool_call_id and DOMNormalizer._looks_like_tool_call_json(seg.content):
            return True
        return False

    @staticmethod
    def _looks_like_tool_call_json(text: str) -> bool:
        text = str(text or "").strip()
        if not text:
            return False
        try:
            parsed = json.loads(text)
        except Exception:
            return False
        return isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed

    @staticmethod
    def _find_preceding_ai_message(
        messages: List[CanonicalMessage],
        msg_index: Dict[int, int],
        current_msg: CanonicalMessage,
    ) -> Optional[CanonicalMessage]:
        """从当前消息向前搜索，找到最近的一条 AI 消息。"""
        cur_idx = msg_index.get(id(current_msg))
        if cur_idx is None:
            return None
        for i in range(cur_idx - 1, -1, -1):
            if messages[i].role == "AI":
                return messages[i]
        return None

    @staticmethod
    def _make_user_message(
        content: str,
        ref_ordinal: int,
        conversation_id: str,
        round_id: str,
    ) -> CanonicalMessage:
        """从工具回流消息中提取的用户追加消息，生成独立 CanonicalMessage。"""
        id_source = f"{ref_ordinal}:User:{content}"
        msg_id = f"msg_user_{ref_ordinal}_{hashlib.md5(id_source.encode('utf-8')).hexdigest()[:8]}:User"
        seg = CanonicalSegment(
            id=f"seg_{msg_id}_text_0",
            message_id=msg_id,
            type="text",
            ordinal=0,
            content=content,
            content_hash=hashlib.md5(f"text:{content}".encode("utf-8")).hexdigest()[:12],
        )
        content_hash = hashlib.md5(f"text:{seg.content_hash}".encode("utf-8")).hexdigest()[:12]
        return CanonicalMessage(
            id=msg_id,
            conversation_id=conversation_id,
            round_id=round_id,
            ordinal=ref_ordinal,
            role="User",
            status="final",
            rev=1,
            content_hash=content_hash,
            segments=[seg],
            extra={"_extracted_from_feedback": True},
        )

    @staticmethod
    def _make_fallback_ai_message(
        tr_seg: CanonicalSegment,
        ref_ordinal: int,
        conversation_id: str,
        round_id: str,
    ) -> CanonicalMessage:
        """将未绑定的 tool_result 拆为独立 AI 消息（最终兜底）。

        每个 tool_result 成为一条独立的 AI 消息，包含一个 tool_result segment，
        确保客户端渲染为独立的 AI 端气泡，而非合并成一整块。
        """
        content = str(tr_seg.content or '')
        tool_name = str(tr_seg.extra.get('tool_name') or 'tool_result')
        id_source = (
            f"{ref_ordinal}:{tr_seg.ordinal}:"
            f"{tr_seg.tool_call_id or ''}:{tr_seg.block_key or ''}:{content}"
        )
        msg_id = f"msg_fb_tool_{ref_ordinal}_{tr_seg.ordinal}_{hashlib.md5(id_source.encode('utf-8')).hexdigest()[:8]}:AI"
        seg = CanonicalSegment(
            id=f"seg_{msg_id}_tool_result_0",
            message_id=msg_id,
            type="tool_result",
            ordinal=0,
            content=content,
            content_hash=hashlib.md5(f"tool_result:{content}".encode("utf-8")).hexdigest()[:12],
            tool_call_id=tr_seg.tool_call_id,
            block_key=tr_seg.block_key,
            extra={
                "tool_name": tool_name,
                "success": tr_seg.extra.get("success"),
            },
        )
        content_hash = hashlib.md5(f"tool_result:{seg.content_hash}".encode("utf-8")).hexdigest()[:12]
        return CanonicalMessage(
            id=msg_id,
            conversation_id=conversation_id,
            round_id=round_id,
            ordinal=ref_ordinal,
            role="AI",
            status="final",
            rev=1,
            content_hash=content_hash,
            segments=[seg],
            extra={"_fallback_unbound": True},
        )

    def _normalize_one(
        self,
        raw: dict,
        ordinal: int,
        conversation_id: str,
        round_id: str,
    ) -> CanonicalMessage:
        raw_id = str(raw.get("id", "") or "")
        role = str(raw.get("role", "") or "")
        raw_segments = raw.get("segments") or []
        raw_len = raw.get("raw_len", 0)

        message_id = self._resolve_stable_id(raw_id, role, raw_segments, ordinal)

        segments = []
        code_ordinal = 0
        text_ordinal = 0
        for seg_raw in raw_segments:
            if not isinstance(seg_raw, dict):
                continue
            seg = self._normalize_segment(seg_raw, message_id, code_ordinal, text_ordinal)
            segments.append(seg)
            if seg.type == "code":
                code_ordinal += 1
            else:
                text_ordinal += 1

        content_hash = _compute_message_hash(segments)

        tc_block_map = {}
        for seg in segments:
            if self._is_tool_call_anchor(seg) and seg.tool_call_id and seg.block_key:
                tc_block_map[seg.tool_call_id] = seg.block_key
        for seg in segments:
            if seg.type == "tool_result" and seg.tool_call_id and seg.tool_call_id in tc_block_map:
                seg.block_key = tc_block_map[seg.tool_call_id]

        anchor_segs = [seg for seg in segments if self._is_tool_call_anchor(seg) and seg.block_key]
        tool_result_segs = [seg for seg in segments if seg.type == "tool_result"]
        if anchor_segs and tool_result_segs:
            unmatched_results = [seg for seg in tool_result_segs if not seg.block_key or seg.block_key not in {s.block_key for s in anchor_segs}]
            for i, seg in enumerate(unmatched_results):
                if i < len(anchor_segs):
                    seg.block_key = anchor_segs[i].block_key

        prev_raw_hash = self._raw_cache.get(message_id)
        prev_cached = self._processed_cache.get(message_id)
        if prev_raw_hash == content_hash and prev_cached is not None:
            rev = prev_cached.rev
            msg = prev_cached
            msg.ordinal = ordinal
        else:
            rev = (prev_cached.rev + 1) if prev_cached else 1
            msg = CanonicalMessage(
                id=message_id,
                conversation_id=conversation_id,
                round_id=round_id,
                ordinal=ordinal,
                role=role,
                status="final",
                rev=rev,
                content_hash=content_hash,
                segments=segments,
                raw_len=raw_len,
                index=ordinal + 1,
            )
        return msg

    def _normalize_segment(
        self,
        seg_raw: dict,
        message_id: str,
        code_ordinal: int,
        text_ordinal: int,
    ) -> CanonicalSegment:
        seg_type = str(seg_raw.get("type", "") or "")
        content = str(seg_raw.get("content", "") or "")
        language = str(seg_raw.get("language", "") or "")
        tool_call_id = seg_raw.get("tool_call_id")
        is_transient = seg_raw.get("is_transient_preview", False)
        if seg_type == "code" and language.strip().lower().replace("-", "_") != "tool_call":
            if self._looks_like_tool_call_json(content):
                language = "tool_call"

        if seg_type == "code":
            seg_ordinal = code_ordinal
        else:
            seg_ordinal = text_ordinal

        segment_id = _make_segment_id(message_id, seg_type, seg_ordinal)
        content_hash = _compute_segment_hash(seg_type, content)
        if seg_type == "code":
            block_key = f"{message_id}:{code_ordinal}"
        elif seg_type in ("tool_result", "tool_call"):
            block_key = seg_raw.get("block_key") or None
        else:
            block_key = None
        code_fp = ""
        if seg_type == "code":
            code_fp = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]

        return CanonicalSegment(
            id=segment_id,
            message_id=message_id,
            type=seg_type,
            ordinal=seg_ordinal,
            content=content,
            language=language,
            content_hash=content_hash,
            block_key=block_key,
            block_index=code_ordinal if seg_type == "code" else 0,
            code_fingerprint=code_fp,
            tool_call_id=tool_call_id,
            is_transient_preview=is_transient,
        )

    def _resolve_stable_id(
        self,
        raw_id: str,
        role: str,
        raw_segments: list,
        ordinal: int,
    ) -> str:
        """确定消息的稳定 ID。

        有 DOM ID → 直接用。
        无 DOM ID → 用 role + 内容前缀 hash + 邻近稳定 ID 生成，
        并通过 _fallback_id_map 维护跨轮次映射。
        """
        if raw_id:
            return f"{raw_id}:{role}"

        content_preview = ""
        for seg in (raw_segments or []):
            if isinstance(seg, dict):
                c = str(seg.get("content", "") or "")
                if c:
                    content_preview = c[:80]
                    break

        fallback_source = f"{ordinal}:{role}|{content_preview}"
        fallback_hash = hashlib.md5(fallback_source.encode("utf-8")).hexdigest()[:8]
        cache_key = f"{ordinal}:{fallback_hash}"

        if cache_key in self._fallback_id_map:
            existing_id = self._fallback_id_map[cache_key]
            logger.debug("[Normalizer] fallback ID 命中缓存 | ordinal=%s | id=%s", ordinal, existing_id)
            return existing_id

        stable_id = f"msg_fb_{ordinal}_{fallback_hash}:{role}"
        self._fallback_id_map[cache_key] = stable_id
        logger.info("[Normalizer] fallback ID 新建 | ordinal=%s | id=%s | source=%s[:20]",
                    ordinal, stable_id, fallback_source[:20])
        return stable_id

    def check_probe_stable(self, probe_result: list) -> bool:
        """双 probe 防抖：判断 probe 结果是否稳定。

        用法：
          sig_a = self.probe_signature(probe_result)
          ... fetch DOM ...
          sig_b = self.probe_signature(probe_result_2)
          if sig_a != sig_b → DOM 不稳定，需要重试或降级
        """
        sig = self._compute_probe_signature(probe_result)
        if self._probe_signature_a is None:
            self._probe_signature_a = sig
            return True
        self._probe_signature_b = sig
        stable = (self._probe_signature_a == self._probe_signature_b)
        if not stable:
            logger.info("[Normalizer] 双probe防抖: DOM不稳定 | sig_a=%s | sig_b=%s",
                        self._probe_signature_a, sig)
        self._probe_signature_a = sig
        self._probe_signature_b = None
        return stable

    @staticmethod
    def _compute_probe_signature(probe_result: list) -> str:
        if not probe_result:
            return ""
        parts = []
        for item in probe_result:
            item_id = str(item.get("id", "") or "")
            ai = str(item.get("ai", "") or "")
            html_len = str(item.get("html_len", "") or "")
            parts.append(f"{item_id}:{ai}:{html_len}")
        raw = "|".join(parts)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def should_refetch(self, probe_item: dict, cached_msg: Optional[CanonicalMessage]) -> bool:
        """根据 probe 增强字段判断是否需要重新提取。

        html_len 变化 → DOM 有变化，需要重新提取
        html_len 不变 → 跳过
        """
        if cached_msg is None:
            return True
        html_len = probe_item.get("html_len", 0)
        if html_len and cached_msg.raw_len and html_len != cached_msg.raw_len:
            return True
        return False
