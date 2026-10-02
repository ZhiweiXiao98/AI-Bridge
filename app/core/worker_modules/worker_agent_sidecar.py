# filename: app/core/worker_modules/worker_agent_sidecar.py
from __future__ import annotations

import hashlib
import re
import time

from app.core.logging import get_logger
from app.core.utils.error_reporter import ErrorReporter

logger = get_logger("app.core.worker.agent_sidecar", side="worker")


class WorkerAgentSidecarBridge:
    """Agent sidecar auto-fix flow for test failures and repair loops."""

    def __init__(self, worker):
        self.worker = worker

    def request_auto_fix(self, error_report, client_id="Host", **kwargs):
        worker = self.worker
        username = kwargs.get("username", "Unknown")
        mechanic_idx = worker.agent.get_mechanic_index()
        return_idx = worker.current_physical_index

        if mechanic_idx is None:
            worker.safe_emit_status(f"⚠️ 未找到侧车会话，正在自动创建 (User: {username})...")
            worker.scheduler.add_task(client_id, "new_chat_task", **kwargs)
            mechanic_idx = 0
            if return_idx is not None:
                return_idx += 1
        else:
            worker.scheduler.add_task(client_id, "switch_session_task", mechanic_idx, **kwargs)

        worker.safe_emit_status(f"🚑 启动 Agent 模式 -> 会话 {mechanic_idx} [Req: {username}]")

        system_prompt = worker.agent.construct_system_prompt(error_report)
        worker.scheduler.add_task(
            client_id,
            "real_send_text",
            "div.aa-chat-input textarea",
            system_prompt,
            **kwargs,
        )
        worker.scheduler.add_task(
            client_id,
            "task_agent_loop",
            mechanic_idx,
            return_idx,
            10,
            **kwargs,
        )

    def execute_agent_loop_task(self, task):
        worker = self.worker
        if len(task.args) >= 3:
            mechanic_idx = task.args[0]
            return_idx = task.args[1]
            turns_left = task.args[2]
        else:
            mechanic_idx = worker.agent.get_mechanic_index()
            return_idx = task.args[0]
            turns_left = task.args[1]

        if mechanic_idx is not None and worker.current_physical_index != mechanic_idx:
            worker.safe_emit_status(f"🔄 前往侧车会话 #{mechanic_idx} 继续修复...")
            worker.scheduler.add_task(
                task.client_id,
                "switch_session_task",
                mechanic_idx,
                username=worker.current_user,
            )
            self._enqueue_agent_loop(task.client_id, mechanic_idx, return_idx, turns_left)
            return

        if worker.connector.is_busy():
            worker.safe_emit_status("⏳ Agent 思考中...")
            self._enqueue_agent_loop(task.client_id, mechanic_idx, return_idx, turns_left)
            time.sleep(1.0)
            return

        raw_msgs, _ = worker.connector.get_chat_content(worker.target_class, auto_wake=True)
        if not raw_msgs:
            self._enqueue_agent_loop(task.client_id, mechanic_idx, return_idx, turns_left)
            time.sleep(1.0)
            return

        last_msg = raw_msgs[-1]
        full_text = "\n".join(
            [s["content"] for s in last_msg.get("segments", []) if s["type"] == "text"]
        )

        if "```tool_call" in full_text or "```python" in full_text:
            handled = self._handle_executable_agent_reply(
                task,
                last_msg,
                full_text,
                mechanic_idx,
                return_idx,
                turns_left,
            )
            if handled:
                return

        intent, _data = worker.agent.parse_agent_response(full_text)

        if intent == "TOOL":
            worker.safe_emit_status("🔧 [Agent] 检测到工具调用意图，交由 ToolRouter 处理...")
            if turns_left > 0:
                self._enqueue_agent_loop(task.client_id, mechanic_idx, return_idx, turns_left - 1)
            return

        if intent == "CODE":
            self._handle_code_fix_reply(task, last_msg, mechanic_idx, return_idx, turns_left)
            return

        if turns_left > 0:
            self._enqueue_agent_loop(task.client_id, mechanic_idx, return_idx, turns_left - 1)
        else:
            self._enqueue_return_to_main(task.client_id, return_idx)

    def _handle_executable_agent_reply(
        self,
        task,
        last_msg,
        full_text,
        mechanic_idx,
        return_idx,
        turns_left,
    ):
        worker = self.worker
        block_code = full_text.split("```python")[-1].strip()
        if re.match(r"^\s*(#|//|<!--)\s*filename\s*:", block_code, re.IGNORECASE):
            return False

        worker.safe_emit_status("🤖 [Agent] 正在执行代码 (Docker)...")

        msg_id = str(last_msg.get("id", "") or "").strip()
        with worker._processed_lock:
            if msg_id:
                agent_fp = f"{worker.current_chat_id}|mid:{msg_id}"
            else:
                agent_fp = f"{worker.current_chat_id}|fp:{hashlib.md5(full_text.encode('utf-8')).hexdigest()}"
            if agent_fp in worker._processed_tool_fingerprints:
                return True
            worker._processed_tool_fingerprints.add(agent_fp)
            worker._processed_fp_order.append(agent_fp)

        fake_msgs = [
            {
                "role": "AI",
                "index": 9999,
                "segments": [{"type": "text", "content": full_text}],
            }
        ]
        result = worker.tool_router.maybe_handle_tool_from_messages(
            chat_id=worker.current_chat_id,
            messages=fake_msgs,
            allow=True,
        )
        result_text = worker._build_browser_tool_feedback_text(result)

        if not result_text:
            return False

        pending = worker.get_and_clear_pending_message()
        if pending:
            pending_text = str(pending.get("text", "") or "").strip()
            if pending_text:
                result_text = result_text + f"\n\n[USER_MESSAGE_BEGIN]\n{pending_text}\n[USER_MESSAGE_END]"
                worker.safe_emit_status("✅ 已附加用户待发消息")

        worker.connector.send_message(
            "div.aa-chat-input textarea",
            f"{result_text}\n\nNext Step?",
        )
        self._enqueue_agent_loop(task.client_id, mechanic_idx, return_idx, turns_left - 1)
        return True

    def _handle_code_fix_reply(self, task, last_msg, mechanic_idx, return_idx, turns_left):
        worker = self.worker
        worker.safe_emit_status("🛡️ 检测到代码变更，正在安全验证...")
        success, changed_files, log = worker.agent.safe_apply_and_test(
            last_msg.get("segments", [])
        )
        if success:
            worker.safe_emit_status("🎉 修复成功！测试通过！")
            worker.safe_emit_status("🔙 返回主会话...")
            self._enqueue_return_to_main(task.client_id, return_idx)

            needs_restart = any(
                worker.update_service.get_file_category(path) in ["CRITICAL", "CLIENT_ONLY"]
                for path in changed_files
            )
            if needs_restart:
                worker.scheduler.add_task(
                    task.client_id,
                    "task_restart_if_needed",
                    username=worker.current_user,
                )
            return

        if turns_left > 0:
            worker.safe_emit_status("❌ 验证失败(已回滚)，反馈报错...")
            report = ErrorReporter.generate_report(log)
            prompt = (
                "❌ 代码导致测试失败 (环境已回滚)。\n\n"
                f"【New Traceback】\n{report}\n\n请重新分析并修复。"
            )
            worker.connector.send_message("div.aa-chat-input textarea", prompt)
            self._enqueue_agent_loop(task.client_id, mechanic_idx, return_idx, turns_left - 1)
        else:
            worker.safe_emit_status("❌ 次数耗尽，修复中止")
            self._enqueue_return_to_main(task.client_id, return_idx)

    def _enqueue_agent_loop(self, client_id, mechanic_idx, return_idx, turns_left):
        worker = self.worker
        worker.scheduler.add_task(
            client_id,
            "task_agent_loop",
            mechanic_idx,
            return_idx,
            turns_left,
            username=worker.current_user,
        )

    def _enqueue_return_to_main(self, client_id, return_idx):
        worker = self.worker
        worker.scheduler.add_task(
            client_id,
            "switch_session_task",
            return_idx,
            username=worker.current_user,
        )
