# filename: app/core/worker_modules/worker_browser_commands.py
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger("app.core.worker.browser_commands", side="worker")


class WorkerBrowserCommandBridge:
    """UI/RPC browser commands translated into scheduler tasks."""

    def __init__(self, worker):
        self.worker = worker

    def handle_compound_send(self, text, file_paths, client_id="Host", **kwargs):
        self.worker.scheduler.add_task(
            client_id,
            "compound_send_task",
            text,
            file_paths,
            **kwargs,
        )

    def send_compound(self, text, file_paths, client_id="Host", **kwargs):
        return self.handle_compound_send(text, file_paths, client_id, **kwargs)

    def upload_file(self, file_path, client_id="Host", **kwargs):
        self.worker.scheduler.add_task(client_id, "upload_file_task", file_path, **kwargs)

    def send_text(self, selector, text, client_id="Host", **kwargs):
        self.worker.scheduler.add_task(client_id, "real_send_text", selector, text, **kwargs)

    def run_remote_script(self, code, client_id="Host", **kwargs):
        prompt = f"请执行/解释以下代码:\n```python\n{code}\n```"
        self.worker.scheduler.add_task(
            client_id,
            "real_send_text",
            "div.aa-chat-input textarea",
            prompt,
            **kwargs,
        )

    def request_switch_session(self, index, client_id="Host", **kwargs):
        self.worker.scheduler.add_task(client_id, "switch_session_task", index, **kwargs)

    def new_chat(self, client_id="Host", **kwargs):
        self.worker.scheduler.add_task(client_id, "new_chat_task", **kwargs)

    def request_wake_up(self, client_id="Host", **kwargs):
        self.worker.scheduler.add_task(client_id, "task_wake_up", **kwargs)

    def request_fix_all(self, client_id="Host", **kwargs):
        self.worker.scheduler.add_task(client_id, "task_fix_all", **kwargs)

    def trigger_manual_toggle(self, msg_index, blk_idx, total, client_id="Host", **kwargs):
        fingerprint = self._get_manual_toggle_fingerprint(msg_index)
        self.worker.scheduler.add_task(
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
