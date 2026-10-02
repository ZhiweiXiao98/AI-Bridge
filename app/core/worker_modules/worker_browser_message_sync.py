# filename: app/core/worker_modules/worker_browser_message_sync.py
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger("app.core.worker.browser_message_sync", side="worker")


class WorkerBrowserMessageSyncBridge:
    """Browser-mode message extraction, canonical sync, and UI projection bridge."""

    def __init__(self, worker):
        self.worker = worker

    def emit_browser_messages_snapshot(self, reason="background_sync"):
        worker = self.worker
        if not worker.connector.interact:
            return False
        try:
            old_fps = self._collect_code_fingerprints(worker.last_messages_snapshot, reason)

            raw_msgs, _, _ = worker.connector.get_chat_content_incremental(
                transient_last_ai=False
            )

            if reason == "after_autofix" and old_fps:
                self._log_code_fingerprint_changes(raw_msgs, old_fps, reason)

            self.do_push_extracted_messages(raw_msgs, reason=f"snapshot_{reason}")
            worker.state_service.save_states()
            self.check_and_emit_sync()
            return True
        except Exception as exc:
            logger.warning("浏览器稳定消息同步失败: %s", exc)
            return False

    def _collect_code_fingerprints(self, messages, reason):
        if reason != "after_autofix" or not messages:
            return {}
        old_fps = {}
        for msg in messages:
            msg_id = str(msg.get("id", "") or "")[:12]
            for seg in msg.get("segments") or []:
                if isinstance(seg, dict) and seg.get("type") == "code":
                    fp = str(seg.get("code_fingerprint", "") or "")
                    old_fps[f"{msg_id}:{seg.get('block_index', '?')}"] = fp
        return old_fps

    def _log_code_fingerprint_changes(self, raw_msgs, old_fps, reason):
        new_fps = {}
        for msg in raw_msgs:
            msg_id = str(msg.get("id", "") or "")[:12]
            for seg in msg.get("segments") or []:
                if isinstance(seg, dict) and seg.get("type") == "code":
                    fp = str(seg.get("code_fingerprint", "") or "")
                    new_fps[f"{msg_id}:{seg.get('block_index', '?')}"] = fp
        changed_keys = []
        for key in set(list(old_fps.keys()) + list(new_fps.keys())):
            old_fp = old_fps.get(key, "<无>")
            new_fp = new_fps.get(key, "<无>")
            if old_fp != new_fp:
                changed_keys.append(f"{key}: fp {old_fp[:12]}->{new_fp[:12]}")
        if changed_keys:
            logger.info(
                "[snapshot-诊断] AutoFix后代码内容变化 | reason=%s | 变化数=%s | 详情=%s",
                reason,
                len(changed_keys),
                changed_keys,
            )
        else:
            logger.debug("[snapshot-诊断] AutoFix后代码内容无变化 | reason=%s", reason)

    def trigger_resync(self):
        worker = self.worker
        if worker.last_messages_snapshot:
            self.do_push_extracted_messages(
                worker.last_messages_snapshot,
                reason="resync",
                force_full=True,
            )
        self.check_and_emit_sync(True)

    def check_and_emit_sync(self, force=False):
        worker = self.worker
        needs, snap = worker.state_service.should_emit_sync(
            worker.current_chat_id,
            worker.current_bubble_count,
            force,
        )
        if needs:
            worker.state_sync_signal.emit(worker.current_bubble_count, snap)
            worker.context_health_signal.emit(
                worker.current_bubble_count,
                worker.current_bubble_count - snap,
            )

    def idle_probe_and_maybe_push(self, transient_last_ai=False):
        """Lightweight IDLE probe: emit only when the DOM structure changed."""
        worker = self.worker
        try:
            raw_msgs, _is_at_bottom, has_structural_change = (
                worker.connector.get_chat_content_incremental(
                    transient_last_ai=transient_last_ai
                )
            )
        except Exception as exc:
            logger.warning("[IDLE探测] 增量提取异常: %s", exc)
            return

        if not has_structural_change:
            return

        self.do_push_extracted_messages(raw_msgs, reason="idle_structural_change")

    def do_extract_and_push(self, reason="state_driven", transient_last_ai=False):
        worker = self.worker
        try:
            raw_msgs, _is_at_bottom, _ = worker.connector.get_chat_content_incremental(
                transient_last_ai=transient_last_ai
            )
        except Exception as exc:
            logger.warning("[提取推送] 增量提取异常，降级全量: %s", exc)
            try:
                raw_msgs, _ = worker.connector.get_chat_content(
                    worker.target_class,
                    transient_last_ai=transient_last_ai,
                )
            except Exception as exc2:
                logger.warning("[提取推送] 全量提取也失败: %s", exc2)
                return

        self.do_push_extracted_messages(raw_msgs, reason=reason)

    def do_push_extracted_messages(self, raw_msgs, reason="unknown", force_full=False):
        worker = self.worker
        raw_msgs = worker.file_service.process_images(raw_msgs)
        worker.last_messages_snapshot = raw_msgs

        self.prescan_tool_call_ids(raw_msgs)

        session_data = worker.state_service.get_session(worker.current_chat_id)
        session_data, worker.current_bubble_count, log = worker.engine.deduce_state(
            raw_msgs,
            session_data,
        )
        if log:
            worker.safe_emit_status(log)
        raw_msgs = worker.engine.tag_messages(
            raw_msgs,
            worker.current_bubble_count,
            session_data.snapshot_bubble,
        )

        canonical_msgs, changed_ids, removed_ids = worker._normalizer.normalize_messages(
            raw_msgs,
            conversation_id=worker.current_chat_id,
            round_id="",
            force_full=force_full,
        )
        store_empty = worker._canonical_store.message_count == 0
        if force_full or store_empty:
            seq = worker._seq_gen.next()
            self._emit_snapshot(canonical_msgs, seq, reason)
        elif changed_ids or removed_ids:
            seq = worker._seq_gen.next()
            self._emit_incremental(canonical_msgs, changed_ids, removed_ids, seq, reason)
        else:
            logger.debug(
                "[同步推送] 无变化，跳过推送 | reason=%s | total=%s",
                reason,
                len(canonical_msgs),
            )

        try:
            worker.process_batch(raw_msgs)
        except Exception as exc:
            logger.warning(exc)

    def _emit_snapshot(self, canonical_msgs, seq, reason):
        worker = self.worker
        event_type = "conversation.snapshot"
        worker._canonical_store.apply_snapshot(canonical_msgs, seq, worker.current_chat_id)
        enriched = []
        for cm in canonical_msgs:
            payload = cm.to_dict()
            payload["_seq"] = seq
            payload["_event"] = event_type
            enriched.append(payload)
        change_summary = [
            f"{cm.id[:12]}:rev={cm.rev}:ch={cm.content_hash[:8]}"
            for cm in canonical_msgs
        ]
        logger.info(
            "[同步推送] 全量推送 | reason=%s | seq=%s | messages=%s | 详情=[%s]",
            reason,
            seq,
            len(enriched),
            " | ".join(change_summary),
        )
        worker.messages_signal.emit(enriched)

    def _emit_incremental(self, canonical_msgs, changed_ids, removed_ids, seq, reason):
        worker = self.worker
        event_type = "message.upsert"
        worker._canonical_store.apply_incremental(
            canonical_msgs,
            changed_ids,
            seq,
            worker.current_chat_id,
        )
        changed_set = set(changed_ids)
        enriched = []
        for cm in canonical_msgs:
            if cm.id in changed_set:
                payload = cm.to_dict()
                payload["_seq"] = seq
                payload["_event"] = event_type
                enriched.append(payload)
        for rid in removed_ids:
            enriched.append(
                {
                    "id": rid,
                    "_seq": seq,
                    "_event": "message.remove",
                }
            )
        logger.info(
            "[同步推送] 增量推送 | reason=%s | seq=%s | changed=%s | removed=%s | total=%s",
            reason,
            seq,
            len(enriched) - len(removed_ids),
            len(removed_ids),
            len(canonical_msgs),
        )
        worker.messages_signal.emit(enriched)

    def prescan_tool_call_ids(self, raw_msgs):
        from app.core.tool_runtime.segment_parser import ToolSegmentParser

        worker = self.worker
        assigned = 0
        for msg in raw_msgs or []:
            if str(msg.get("role", "") or "").lower() != "ai":
                continue
            segments = msg.get("segments") or []
            intents = ToolSegmentParser.parse_segments(
                segments,
                conversation_id=worker.current_chat_id,
                source="prescan",
                write_back_tool_call_id=True,
            )
            assigned += len(intents)
        if assigned > 0:
            logger.info(
                "[预扫描] tool_call_id 已回写 | count=%s | chat_id=%s",
                assigned,
                worker.current_chat_id[:12],
            )
