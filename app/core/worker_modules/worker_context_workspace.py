# filename: app/core/worker_modules/worker_context_workspace.py
from __future__ import annotations

from app.core.app_constants import DEFAULT_SYSTEM_BUDGET
from app.core.logging import get_logger

logger = get_logger("app.core.worker.context_workspace", side="worker")


class WorkerContextWorkspaceBridge:
    """Context workspace and API-history operations delegated from WorkerThread."""

    def __init__(self, worker):
        self.worker = worker

    def build_payload(self):
        worker = self.worker
        if worker.mode == "api" and worker.api_source:
            return worker.api_source.get_context_workspace_payload()
        return {
            "mode": worker.mode,
            "conversation_title": "当前模式暂未接入上下文工作台",
            "conversation_id": None,
            "system": {
                "inject_skills_prompt": False,
                "conversation_system_prompt": "",
                "final_system_prompt": "当前仅 API 模式已接入上下文工作台 V1",
                "final_tokens": 0,
                "system_budget": DEFAULT_SYSTEM_BUDGET,
                "over_budget": False,
                "blocks": [],
            },
            "working_memory": {},
            "long_term": {"fragments": [], "count": 0},
            "context_config": {},
            "compact": {},
            "usage": {},
            "history_preview": [],
        }

    def emit_payload(self, client_id=None, user_role=None, conversation_id=None):
        worker = self.worker
        if conversation_id is not None and worker.api_source:
            payload = worker.api_source.get_context_workspace_payload(conversation_id=conversation_id)
        else:
            payload = self.build_payload()
        try:
            worker.context_workspace_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        if client_id:
            remote_payload = dict(payload)
            remote_payload["target_client_id"] = client_id
            remote_payload["target_group"] = "admin" if user_role == "developer" else "user"
            worker.context_workspace_signal.emit(remote_payload)
        return payload

    def get_payload(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.emit_payload(
            client_id=client_id,
            user_role=user_role,
            conversation_id=conversation_id,
        )

    def update_system_prompt(self, content, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        if worker.api_source:
            ok = worker.api_source.update_conversation_system_prompt(content, conversation_id=conversation_id)
            worker.context_status_signal.emit(worker.api_source.get_context_status(conversation_id=conversation_id))
            self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def update_working_memory(self, data, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        if worker.api_source:
            ok = worker.api_source.set_working_memory(data, conversation_id=conversation_id)
            worker.context_status_signal.emit(worker.api_source.get_context_status(conversation_id=conversation_id))
            self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def clear_working_memory(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        if worker.api_source:
            ok = worker.api_source.clear_working_memory(conversation_id=conversation_id)
            worker.context_status_signal.emit(worker.api_source.get_context_status(conversation_id=conversation_id))
            self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def clear_long_term(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        if worker.api_source:
            ok = worker.api_source.clear_long_term(conversation_id=conversation_id)
            worker.context_status_signal.emit(worker.api_source.get_context_status(conversation_id=conversation_id))
            self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self.emit_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def get_last_request_snapshot(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        snap = None
        if not worker.api_source and hasattr(worker, "_init_api_source"):
            try:
                worker._init_api_source()
            except Exception as e:
                logger.warning("[ContextWorkspace] API Source 初始化失败，无法读取请求快照: %s", e)
        if worker.api_source:
            snap = worker.api_source.get_last_request_snapshot(conversation_id=conversation_id)
        payload = snap or {}
        if client_id:
            payload = dict(payload) if payload else {}
            payload["target_client_id"] = client_id
            payload["target_group"] = "admin" if user_role == "developer" else "user"
        try:
            worker.context_snapshot_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return snap

    def trigger_manual_compact(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        group = "admin" if user_role == "developer" else "user"
        if not worker.api_source:
            worker._init_api_source()
        payload = {
            "ok": False,
            "reason": "api_source_unavailable",
            "conversation_id": conversation_id or "",
            "target_client_id": client_id,
            "target_group": group,
        }
        if worker.api_source:
            result = worker.api_source.trigger_manual_compact(conversation_id=conversation_id)
            payload.update(result or {})
            payload["target_client_id"] = client_id
            payload["target_group"] = group
            effective_conv_id = payload.get("conversation_id") or conversation_id or ""
            try:
                worker.context_status_signal.emit(
                    worker.api_source.get_context_status(conversation_id=effective_conv_id or None)
                )
            except Exception as e:
                logger.warning(e)
            try:
                self.emit_payload(
                    client_id=client_id,
                    user_role=user_role,
                    conversation_id=effective_conv_id or None,
                )
            except Exception as e:
                logger.warning(e)
        try:
            worker.api_manual_compact_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return payload

    def get_api_conversations(self, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        group = "admin" if user_role == "developer" else "user"
        if worker.api_source:
            conversations = worker.api_source.get_api_conversations()
            payload = {
                "items": conversations,
                "target_client_id": client_id,
                "target_group": group,
            }
            try:
                worker.api_conversations_signal.emit(payload)
            except Exception as e:
                logger.warning(e)
            return conversations
        payload = {
            "items": [],
            "target_client_id": client_id,
            "target_group": group,
        }
        try:
            worker.api_conversations_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return []

    def delete_api_messages(self, indexes, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        worker = self.worker
        group = "admin" if user_role == "developer" else "user"
        if not worker.api_source:
            worker._init_api_source()
        removed = 0
        payload = {
            "removed": 0,
            "conversation_id": conversation_id or "",
            "indexes": list(indexes or []),
            "target_client_id": client_id,
            "target_group": group,
        }
        if worker.api_source:
            removed = worker.api_source.delete_messages(indexes or [], conversation_id=conversation_id)
            active_id = worker.api_source.conv_store.active_id if worker.api_source.conv_store else ""
            effective_conv_id = conversation_id or active_id
            payload.update({
                "removed": removed,
                "conversation_id": effective_conv_id or "",
            })
            try:
                if conversation_id and effective_conv_id != active_id:
                    msgs = worker.api_source.get_history_as_messages_for(effective_conv_id)
                else:
                    msgs = worker.api_source.get_history_as_messages()
                worker.messages_signal.emit(msgs if msgs else [])
            except Exception as e:
                logger.warning(e)
            try:
                worker.context_status_signal.emit(
                    worker.api_source.get_context_status(conversation_id=effective_conv_id or None)
                )
            except Exception as e:
                logger.warning(e)
            try:
                self.emit_payload(
                    client_id=client_id,
                    user_role=user_role,
                    conversation_id=effective_conv_id or None,
                )
            except Exception as e:
                logger.warning(e)
        try:
            worker.api_messages_deleted_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return removed
