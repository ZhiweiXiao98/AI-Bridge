# filename: app/core/worker_modules/worker_runtime_monitor.py
from __future__ import annotations

import time

from app.core.logging import get_logger

logger = get_logger("app.core.worker.runtime_monitor", side="worker")


class WorkerRuntimeMonitorBridge:
    """Runtime task queue snapshots and tool execution event bridge."""

    def __init__(self, worker):
        self.worker = worker
        self.runtime_tool_tasks = {}
        self.runtime_task_order = []
        self.tool_runtime_callback_stack = []

    def normalize_runtime_task(self, task: dict | None):
        task = dict(task or {})
        task_id = str(task.get("task_id") or task.get("id") or "").strip()
        if not task_id:
            return None
        task["id"] = task_id
        task["task_id"] = task_id
        if not task.get("status"):
            task["status"] = "running"
        started_at = task.get("started_at", 0) or 0
        elapsed_ms = task.get("elapsed_ms", 0) or 0
        if started_at and not elapsed_ms:
            elapsed_ms = max(0, int((time.time() - float(started_at)) * 1000))
            task["elapsed_ms"] = elapsed_ms
        if elapsed_ms and not task.get("age"):
            task["age"] = elapsed_ms / 1000.0
        return task

    def upsert_runtime_task(self, task: dict | None):
        payload = self.normalize_runtime_task(task)
        if not payload:
            return None
        task_id = payload["task_id"]
        self.runtime_tool_tasks[task_id] = payload
        self.runtime_task_order = [x for x in self.runtime_task_order if x != task_id]
        self.runtime_task_order.append(task_id)
        return payload

    def remove_runtime_task(self, task_id: str | None):
        key = str(task_id or "").strip()
        if not key:
            return
        self.runtime_tool_tasks.pop(key, None)
        self.runtime_task_order = [x for x in self.runtime_task_order if x != key]

    def build_queue_monitor_snapshot(self):
        worker = self.worker
        active_task = None
        queue_list = []
        if hasattr(worker.scheduler, "get_queue_snapshot"):
            active_task, queue_list = worker.scheduler.get_queue_snapshot()
        queue_list = list(queue_list or [])
        runtime_tasks = []
        for task_id in list(self.runtime_task_order):
            payload = self.normalize_runtime_task(self.runtime_tool_tasks.get(task_id))
            if not payload:
                continue
            self.runtime_tool_tasks[task_id] = payload
            runtime_tasks.append(payload)
        if runtime_tasks:
            scheduler_action = str(active_task.get("action", "") if active_task else "")
            if active_task and scheduler_action in ("real_send_text", "compound_send_task"):
                queue_list = [active_task] + queue_list
                active_task = runtime_tasks[0]
                queue_list = runtime_tasks[1:] + queue_list
            elif active_task:
                queue_list = runtime_tasks + queue_list
            else:
                active_task = runtime_tasks[0]
                queue_list = runtime_tasks[1:] + queue_list
        return {
            "active": active_task,
            "queue": queue_list,
            "timestamp": time.time(),
        }

    def emit_queue_monitor_snapshot(self, reason="runtime_event"):
        worker = self.worker
        snapshot = self.build_queue_monitor_snapshot()
        active = snapshot.get("active") or {}
        has_active = bool(active)
        log = logger.info if has_active else logger.debug
        log(
            "[QueueMonitor] emit snapshot | reason=%s has_active=%s task_id=%s tool_name=%s queue=%s",
            reason,
            has_active,
            active.get("task_id", ""),
            active.get("tool_name", ""),
            len(snapshot.get("queue", []) or []),
        )
        worker.queue_monitor_signal.emit(snapshot)
        return snapshot

    def emit_tool_event(
        self,
        event_type,
        tool_call_id,
        tool_name,
        status,
        success=None,
        elapsed_ms=0,
        index=0,
    ):
        worker = self.worker
        seq = worker._seq_gen.next()
        payload = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": status,
            "index": index,
        }
        if success is not None:
            payload["success"] = success
        if elapsed_ms:
            payload["elapsed_ms"] = elapsed_ms

        worker._canonical_store.log_event(
            type(
                "E",
                (),
                {
                    "seq": seq,
                    "conversation_id": worker.current_chat_id,
                    "round_id": "",
                    "event": event_type,
                    "payload": payload,
                    "created_at": time.time(),
                    "to_dict": lambda self_: {
                        "seq": self_.seq,
                        "conversation_id": self_.conversation_id,
                        "round_id": self_.round_id,
                        "event": self_.event,
                        "payload": self_.payload,
                        "created_at": self_.created_at,
                    },
                },
            )()
        )
        worker.ai_state_signal.emit({
            "type": "tool_event",
            "_seq": seq,
            "_event": event_type,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": status,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "index": index,
        })
        logger.info(
            "[工具事件] %s | tool_call_id=%s | tool_name=%s | status=%s | seq=%s",
            event_type,
            str(tool_call_id or "")[:20],
            tool_name,
            status,
            seq,
        )

    def handle_runtime_tool_start(self, intent, index):
        task_id = str(getattr(intent, "tool_call_id", "") or "").strip()
        tool_name = getattr(intent, "name", "") or getattr(intent, "kind", "tool_call")
        task = {
            "id": task_id,
            "task_id": task_id,
            "action": tool_name,
            "status": "running",
            "label": tool_name or getattr(intent, "kind", "工具任务"),
            "category": "Tool",
            "icon": "🛠️" if getattr(intent, "kind", "") == "skill_call" else "🖥️",
            "cancellable": False,
            "client_id": getattr(intent, "conversation_id", "") or "tool_runtime",
            "tool_call_id": task_id,
            "tool_name": tool_name,
            "conversation_id": getattr(intent, "conversation_id", ""),
            "started_at": time.time(),
            "elapsed_ms": 0,
            "age": 0,
            "runtime_source": "tool_runtime",
            "index": index,
            "block_key": getattr(intent, "block_key", ""),
        }
        logger.info(
            "[工具执行] 开始执行工具 | tool_name=%s | tool_call_id=%s | conversation_id=%s | index=%s",
            tool_name,
            task_id,
            getattr(intent, "conversation_id", ""),
            index,
        )
        self.upsert_runtime_task(task)
        self.emit_queue_monitor_snapshot(reason="tool_start")
        self.emit_tool_event("tool.status", task_id, tool_name, "running", index=index)

    def handle_runtime_tool_end(self, intent, result, index):
        task_id = str(getattr(intent, "tool_call_id", "") or "").strip()
        tool_name = getattr(intent, "name", "") or getattr(intent, "kind", "tool_call")
        elapsed_ms = 0
        current_task = self.runtime_tool_tasks.get(task_id) or {}
        started_at = current_task.get("started_at", 0) or 0
        if started_at:
            elapsed_ms = max(0, int((time.time() - float(started_at)) * 1000))
        logger.info(
            "[工具执行] 工具执行结束 | tool_name=%s | tool_call_id=%s | success=%s | elapsed_ms=%s | conversation_id=%s | index=%s",
            tool_name,
            task_id,
            bool(getattr(result, "success", False)),
            elapsed_ms,
            getattr(intent, "conversation_id", ""),
            index,
        )
        self.remove_runtime_task(task_id)
        self.emit_queue_monitor_snapshot(reason="tool_end")
        success = bool(getattr(result, "success", False))
        status = "completed" if success else "failed"
        self.emit_tool_event(
            "tool.result",
            task_id,
            tool_name,
            status,
            success=success,
            elapsed_ms=elapsed_ms,
            index=index,
        )

    def handle_knowledge_task_state_change(self, event):
        worker = self.worker
        event = dict(event or {})
        state = str(event.get("state") or "").strip() or "unknown"
        snap = event.get("snapshot") or {}
        payload = worker.knowledge_task_bridge.build_runtime_task_payload(snap)
        task_id = ""
        if payload:
            task_id = payload.get("task_id", "")
        if not task_id:
            task_id = str((snap or {}).get("task_id", "") or "").strip()
        tool_name = str((snap or {}).get("tool_name", "") or "knowledge_search")
        if state == "running" and payload:
            logger.info(
                "[知识任务] 开始执行知识检索 | task_id=%s | tool_call_id=%s | tool_name=%s | conversation_id=%s | query_preview=%s",
                task_id,
                payload.get("tool_call_id", ""),
                tool_name,
                payload.get("conversation_id", ""),
                payload.get("query_preview", ""),
            )
            self.upsert_runtime_task(payload)
        elif state in ("finished", "idle", "error", "cancelled"):
            elapsed_ms = (snap or {}).get("elapsed_ms", 0) or 0
            logger.info(
                "[知识任务] 知识检索状态变更 | state=%s | task_id=%s | tool_call_id=%s | tool_name=%s | elapsed_ms=%s | conversation_id=%s",
                state,
                task_id,
                (payload or {}).get("tool_call_id", "") if payload else (snap or {}).get("tool_call_id", ""),
                tool_name,
                elapsed_ms,
                (payload or {}).get("conversation_id", "") if payload else (snap or {}).get("conversation_id", ""),
            )
            self.remove_runtime_task(task_id)
        self.emit_queue_monitor_snapshot(reason=f"knowledge_{state}")

    def wrap_tool_runtime_start(self, previous_callback):
        def _wrapped(intent, index):
            try:
                self.handle_runtime_tool_start(intent, index)
            finally:
                if callable(previous_callback):
                    previous_callback(intent, index)

        return _wrapped

    def wrap_tool_runtime_end(self, previous_callback):
        def _wrapped(intent, result, index):
            try:
                self.handle_runtime_tool_end(intent, result, index)
            finally:
                if callable(previous_callback):
                    previous_callback(intent, result, index)

        return _wrapped

    def install_tool_runtime_callbacks(self):
        runtime_executor = getattr(self.worker.tool_router, "runtime_executor", None)
        if not runtime_executor:
            return None
        previous_on_start = getattr(runtime_executor, "on_intent_start", None)
        previous_on_end = getattr(runtime_executor, "on_intent_end", None)
        runtime_executor.on_intent_start = self.wrap_tool_runtime_start(previous_on_start)
        runtime_executor.on_intent_end = self.wrap_tool_runtime_end(previous_on_end)
        token = (runtime_executor, previous_on_start, previous_on_end)
        self.tool_runtime_callback_stack.append(token)
        return token

    def restore_tool_runtime_callbacks(self, token=None):
        runtime_executor = getattr(self.worker.tool_router, "runtime_executor", None)
        if token is None:
            if not self.tool_runtime_callback_stack:
                return
            token = self.tool_runtime_callback_stack.pop()
        else:
            try:
                self.tool_runtime_callback_stack.remove(token)
            except ValueError:
                pass
        executor_obj, previous_on_start, previous_on_end = token
        if runtime_executor is executor_obj:
            runtime_executor.on_intent_start = previous_on_start
            runtime_executor.on_intent_end = previous_on_end
