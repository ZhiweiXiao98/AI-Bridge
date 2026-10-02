# filename: app/core/worker_modules/worker_browser_commands.py
from __future__ import annotations

import collections
import os
import threading
import time

from app.core.logging import get_logger

logger = get_logger("app.core.worker.browser_commands", side="worker")

BROWSER_TASKS = frozenset({
    "real_send_text", "compound_send_task", "upload_file_task", "switch_session_task",
    "new_chat_task", "task_wake_up", "task_fix_all", "task_manual_toggle",
    "task_batch_end", "task_agent_loop",
})


class WorkerBrowserCommandBridge:
    """UI/RPC browser commands translated into scheduler tasks."""

    def __init__(self, worker):
        self.worker = worker
        self._lock = threading.RLock()
        self._controls = collections.deque()
        self.epoch = 0
        self.cancelled = False
        self.cancel_pending = False
        self.connected = False
        self.ready = False
        self.next_connect_at = 0.0
        self._invalidated_at = 0.0
        self._last_diagnostic = ""
        self._request_ids = set()
        self._completed_requests = set()

    def _status(self, message):
        emit = getattr(self.worker, "safe_emit_status", None)
        if emit:
            emit(message)

    def report_connection(self, message):
        if message != self._last_diagnostic:
            self._last_diagnostic = message
            self._status(message)

    def is_current(self, epoch=None):
        with self._lock:
            return (
                getattr(self.worker, "running", True)
                and not getattr(self.worker, "_shutdown_started", False)
                and getattr(self.worker, "mode", "browser") == "browser"
                and not self.cancelled
                and (epoch is None or epoch == self.epoch)
            )

    def _enqueue(self, client_id, action, *args, **kwargs):
        with self._lock:
            if not getattr(self.worker, "running", True) or getattr(self.worker, "_shutdown_started", False):
                return False
            if getattr(self.worker, "mode", "browser") != "browser":
                self._status("⚠️ 请先切换到浏览器模式；未发送消息。")
                return False
            if self.cancel_pending:
                self._status("⏳ 正在停止上一轮，请等待后重新发送。")
                return False
            if hasattr(self.worker, "running") and not self.ready:
                self._status("⚠️ 浏览器尚未就绪，请先连接浏览器并完成登录后重新发送。")
                return False
            request_id = str(kwargs.get("browser_request_id") or "")
            if request_id and request_id in self._request_ids:
                self._status("⚠️ 同一发送请求已提交，已忽略重复点击。")
                return False
            if request_id:
                self._request_ids.add(request_id)
            self.cancelled = False
            return self.worker.scheduler.add_task(client_id, action, *args, **kwargs)

    def task_is_current(self, task):
        if task.action not in BROWSER_TASKS:
            return True
        with self._lock:
            return self.is_current() and float(getattr(task, "timestamp", 0)) >= self._invalidated_at

    def _invalidate(self):
        self.epoch += 1
        self.cancelled = True
        self._invalidated_at = time.time()
        self.worker.pending_user_message = None
        queue = getattr(self.worker.scheduler, "queue", None)
        if queue is not None:
            with queue.mutex:
                dropped = [task for task in queue.queue if task.action in BROWSER_TASKS]
                kept = [task for task in queue.queue if task.action not in BROWSER_TASKS]
                queue.queue.clear()
                queue.queue.extend(kept)
            for task in dropped:
                self.finish_send(task, False, "发送已取消；内容未自动重发。")

    def finish_send(self, task, ok, message):
        request_id = str(getattr(task, "kwargs", {}).get("browser_request_id") or "")
        if not request_id:
            return
        with self._lock:
            if request_id in self._completed_requests:
                return
            self._completed_requests.add(request_id)
        signal = getattr(self.worker, "browser_send_result_signal", None)
        if signal is not None:
            signal.emit({"request_id": request_id, "ok": bool(ok), "message": str(message)})

    def cancel(self, **kwargs):
        """GUI-safe: invalidate sends now; execute DOM Stop on the worker lane."""
        with self._lock:
            if not getattr(self.worker, "running", True):
                return False
            self._invalidate()
            if not self.cancel_pending:
                self.cancel_pending = True
                self._controls.appendleft(("cancel", False))
        self._status("⏳ 已取消待发消息，正在请求网页停止生成...")
        return True

    def reconnect(self, start_browser=False, **kwargs):
        with self._lock:
            if not getattr(self.worker, "running", True) or getattr(self.worker, "_shutdown_started", False):
                return False
            # Collapse repeated clicks without opening multiple browsers.
            self._invalidate()
            self.ready = False
            existing_start = any(start for name, start in self._controls if name == "reconnect")
            self._controls = collections.deque(item for item in self._controls if item[0] != "reconnect")
            self._controls.append(("reconnect", bool(start_browser or existing_start)))
        self._status("⏳ 已请求重新连接浏览器...")
        return True

    def process_controls(self):
        """Only call from the running worker, including its API-mode loop."""
        from app.core.round_state import RoundStateEvent
        while getattr(self.worker, "running", False):
            with self._lock:
                if not self._controls:
                    return
                action, start = self._controls.popleft()
            if action == "cancel":
                try:
                    stop = getattr(self.worker.connector, "cancel_generation", None)
                    ok, message = stop() if stop else (False, "当前连接器不支持网页停止")
                    self._status(f"{'✅' if ok else '⚠️'} {message}；待发消息已取消。")
                except Exception as exc:
                    self._status(f"⚠️ 网页停止未确认：{exc}；待发消息已取消。")
                finally:
                    with self._lock:
                        self.cancel_pending = False
                    self.worker.was_busy = False
                    self.worker.last_send_time = 0
                    self.worker._pre_send_ai_fingerprint = None
                    self.worker.toggle_queue.clear()
                    self.worker._round_sm.handle_event(RoundStateEvent.FORCE_IDLE)
                    self.worker._update_ai_state("idle")
            elif getattr(self.worker, "mode", "browser") == "browser":
                self.connected = False
                self.ready = False
                self.next_connect_at = 0.0
                self._last_diagnostic = ""
                if os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1":
                    recreate = getattr(self.worker, "_recreate_browser_connector", None)
                    if recreate and not recreate():
                        with self._lock:
                            self._controls.append(("reconnect", start))
                        return
                if start:
                    launch = getattr(self.worker.connector, "start_browser", None)
                    try:
                        ok, message = launch() if launch else (False, "当前连接器不支持启动浏览器")
                        self._status(f"{'✅' if ok else '⚠️'} {message}")
                    except Exception as exc:
                        self._status(f"❌ 启动浏览器失败：{exc}")

    def enqueue_feedback(self, epoch, *args, **kwargs):
        with self._lock:
            if not self.is_current(epoch):
                return False
            return self.worker.scheduler.add_task(*args, **kwargs)

    def handle_compound_send(self, text, file_paths, client_id="Host", **kwargs):
        return self._enqueue(
            client_id,
            "compound_send_task",
            text,
            file_paths,
            **kwargs,
        )

    def send_compound(self, text, file_paths, client_id="Host", **kwargs):
        return self.handle_compound_send(text, file_paths, client_id, **kwargs)

    def upload_file(self, file_path, client_id="Host", **kwargs):
        return self._enqueue(client_id, "upload_file_task", file_path, **kwargs)

    def send_text(self, selector, text, client_id="Host", **kwargs):
        return self._enqueue(client_id, "real_send_text", selector, text, **kwargs)

    def run_remote_script(self, code, client_id="Host", **kwargs):
        prompt = f"请执行/解释以下代码:\n```python\n{code}\n```"
        return self._enqueue(
            client_id,
            "real_send_text",
            "div.aa-chat-input textarea",
            prompt,
            **kwargs,
        )

    def request_switch_session(self, index, client_id="Host", **kwargs):
        return self._enqueue(client_id, "switch_session_task", index, **kwargs)

    def new_chat(self, client_id="Host", **kwargs):
        return self._enqueue(client_id, "new_chat_task", **kwargs)

    def request_wake_up(self, client_id="Host", **kwargs):
        return self._enqueue(client_id, "task_wake_up", **kwargs)

    def request_fix_all(self, client_id="Host", **kwargs):
        return self._enqueue(client_id, "task_fix_all", **kwargs)

    def trigger_manual_toggle(self, msg_index, blk_idx, total, client_id="Host", **kwargs):
        fingerprint = self._get_manual_toggle_fingerprint(msg_index)
        return self._enqueue(
            client_id,
            "task_manual_toggle",
            msg_index,
            blk_idx,
            total,
            fingerprint=fingerprint,
            **kwargs,
        )

    def _get_manual_toggle_fingerprint(self, msg_index):
        worker = self.worker
        try:
            target_msgs = [
                message
                for message in worker.last_messages_snapshot
                if message.get("index") == msg_index
            ]
            if target_msgs:
                full_text = worker.engine.get_msg_text(target_msgs[0])
                return full_text[:30].replace("\n", "").strip()
        except Exception as exc:
            logger.warning("获取指纹失败: %s", exc)
        return None
