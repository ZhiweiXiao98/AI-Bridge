# filename: app/core/worker.py
import os
import time
import hashlib
import sys
import subprocess
import re
import json
import threading
import collections
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QThread, Signal, QMutex

from app.core.driver import ChromeConnector
from app.core.config import ConfigManager
from app.core.project_context import ProjectContext
from app.core.services.file_service import FileService
from app.core.services.scheduler_service import SchedulerService
from app.core.services.update_service import UpdateService
from app.core.services.state_service import StateService
from app.core.engine.conversation_engine import ConversationEngine
from app.core.agent_manager import AgentManager
from app.core.docker_manager import DockerManager
from app.core.services.knowledge_service import KnowledgeService
from app.core.utils.error_reporter import ErrorReporter
from app.core.services.context_pack_service import ContextPackService
from app.core.app_constants import CHROME_PORT, MAX_WORKERS, DEFAULT_SYSTEM_BUDGET
from app.core.services.tool_router_service import ToolRouterService
from app.core.tool_runtime.models import ToolRoundResult
from app.core.round_state import BrowserRoundStateMachine, RoundStateEvent, BrowserRoundState
from app.core.logging import get_logger, get_trace_extra
from app.core.debug import probe

logger = get_logger("app.core.worker", side="worker")


class WorkerThread(QThread):
    # === 信号定义 ===
    status_signal = Signal(str)
    messages_signal = Signal(list)
    context_health_signal = Signal(int, int)
    sessions_signal = Signal(list)
    state_sync_signal = Signal(int, int)
    restart_needed_signal = Signal(bool)
    snapshot_ready_signal = Signal(str)
    batch_complete_signal = Signal()
    update_list_signal = Signal(list)
    ota_sync_signal = Signal(object)
    git_detail_signal = Signal(str)
    git_workbench_signal = Signal(object)
    git_diff_preview_signal = Signal(object)
    git_config_signal = Signal(object)
    server_log_signal = Signal(str)
    ai_state_signal = Signal(object)
    occupancy_signal = Signal(object)
    file_preview_signal = Signal(object)
    test_result_signal = Signal(object)
    queue_monitor_signal = Signal(object) # 任务队列监控
    skills_data_signal = Signal(object)  # Skills 数据
    system_prompt_signal = Signal(object)  # 系统提示词
    context_status_signal = Signal(object)  # API模式: 上下文状态
    context_workspace_signal = Signal(object)  # 上下文工作台完整负载
    api_conversations_signal = Signal(object)  # API 对话列表
    api_messages_deleted_signal = Signal(object)  # API 历史消息删除结果
    api_manual_compact_signal = Signal(object)  # API 手动压缩结果
    context_snapshot_signal = Signal(object)  # 上下文快照（调试浮窗）
    mode_changed_signal = Signal(str)       # 模式切换通知
    code_execution_completed = Signal()     # 代码执行完成

    api_stream_chunk_signal = Signal(object)  # 流式文本块信号
    api_stream_status_signal = Signal(object)  # 流式状态信号
    api_round_state_signal = Signal(object)  # API 单回合状态信号
    knowledge_health_signal = Signal(object)  # 知识检索健康状态
    daemon_suggestion_signal = Signal(object)  # 守护进程回复建议

    def __init__(self):
        super().__init__()
        self.config = ConfigManager.load()
        self.connector = ChromeConnector(port=self.config.get("chrome_port", CHROME_PORT))
        self.file_service = FileService(self.config)
        self.scheduler = SchedulerService()
        self.update_service = UpdateService(self.config, self.file_service)
        self.state_service = StateService()
        self.engine = ConversationEngine()

        # 初始化 Docker 管理器
        self.docker_manager = DockerManager()
        
        # 初始化知识服务
        self.knowledge_service = KnowledgeService()

        v2 = getattr(self.knowledge_service, '_v2', None)
        if v2:
            v2._on_health_change = lambda h: self.knowledge_health_signal.emit(h)

        # 初始化 Agent（传递依赖）
        self.agent = AgentManager(
            self.file_service,
            docker_manager=self.docker_manager,
            knowledge_service=self.knowledge_service
        )
        self.context_pack_service = ContextPackService()
        self.tool_router = ToolRouterService(self.agent)

        # 初始化流式桥接器
        from app.core.worker_modules.worker_api_stream import WorkerStreamBridge
        from app.core.worker_modules.worker_knowledge_tasks import WorkerKnowledgeTaskBridge
        from app.core.worker_modules.worker_daemon_bridge import WorkerDaemonBridge
        from app.core.worker_modules.worker_project_switch import WorkerProjectSwitchBridge
        from app.core.worker_modules.worker_browser_stateless import WorkerBrowserStatelessBridge
        from app.core.worker_modules.worker_api_conversation import WorkerApiConversationBridge
        from app.core.worker_modules.worker_api_mode import WorkerApiModeBridge
        from app.core.worker_modules.worker_git_bridge import WorkerGitBridge
        self.stream_bridge = WorkerStreamBridge()
        self.knowledge_task_bridge = WorkerKnowledgeTaskBridge(self.knowledge_service)
        self.api_conversation_bridge = WorkerApiConversationBridge(self)
        self.api_mode_bridge = WorkerApiModeBridge(self)
        self.browser_stateless_bridge = WorkerBrowserStatelessBridge(self)
        self.git_bridge = WorkerGitBridge(self)
        self.daemon_bridge = WorkerDaemonBridge()
        self.daemon_bridge.daemon_suggestion_signal.connect(self.daemon_suggestion_signal.emit)
        self.daemon_bridge.start()
        self.project_switch_bridge = WorkerProjectSwitchBridge(self)

        ctx = ProjectContext.get()
        ctx.about_to_switch.connect(self.docker_manager.on_about_to_switch)
        ctx.project_switched.connect(self.docker_manager.on_project_switched)
        ctx.project_switched.connect(self.knowledge_service.on_project_switched)
        ctx.project_switched.connect(self.file_service.on_project_switched)
        self._runtime_tool_tasks = {}
        self._runtime_task_order = []
        self._tool_runtime_callback_stack = []

        executor_v2 = getattr(self.knowledge_service, '_v2', None)
        executor_obj = getattr(executor_v2, '_executor', None) if executor_v2 else None
        if executor_obj and hasattr(executor_obj, '_on_task_state_change'):
            executor_obj._on_task_state_change = self._handle_knowledge_task_state_change

        self.last_send_time = 0
        self._pre_send_ai_fingerprint = None
        self.rpc_lock = QMutex()

        self.path_redirects = {
            "app/ui/worker.py": "app/core/worker.py",
            "app/ui/error_reporter.py": "app/core/utils/error_reporter.py"
        }

        # === 双消息源 ===
        self.mode = "browser"  # "browser" | "api"
        self.api_source = None  # 延迟初始化
        self._api_pending_text = None
        self._api_streaming = False
        # === 运行时状态 ===
        self.running = True
        self.current_chat_id = "default"
        self.current_bubble_count = 0
        self.current_physical_index = 0
        self.current_user = "System"
        self.was_busy = False
        self.last_messages_snapshot = []
        self.last_session_scan = 0
        self.last_queue_scan = 0
        self.last_occupancy_scan = 0
        self.toggle_queue = []
        self._processed_tool_fingerprints = set()
        self._processed_fp_order = collections.deque(maxlen=500)  # FIFO 淘汰队列
        self._last_processed_ai_msg_id = None  # 已处理的最后一条 AI 消息 ID
        self._last_fixed_ai_msg_id = None  # 最近一次执行 AutoFix 的 AI 消息 ID
        self._last_fixed_at = 0.0  # 最近一次 AutoFix 时间戳
        self._last_tool_trigger_ai_msg_id = None  # 最近一次事件驱动触发工具执行的 AI 消息 ID
        self._processed_lock = threading.RLock()  # 去重操作线程安全
        # 浏览器模式 canonical 同步层
        from app.core.browser_sync import SeqGenerator, DOMNormalizer, BrowserCanonicalStore
        self._seq_gen = SeqGenerator()
        self._normalizer = DOMNormalizer()
        self._canonical_store = BrowserCanonicalStore()
        # 浏览器模式回合状态机（替代原 _browser_round_state 字符串直接赋值）
        self._round_sm = BrowserRoundStateMachine()
        self._round_sm.on_state_change(self._on_round_state_change)
        self.target_class = "aa-chat-message"
        self.pending_user_message = None
        self.input_area = None
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

        logger.info("Worker 线程已就绪 (Monitor V2.0)")

    def init_api_stream_bridge(self):
        """在 _init_api_source 完成后调用，注入流式桥接"""
        if self.api_source and self.stream_bridge:
            self.stream_bridge.init_handler(self.api_source)

            # 将桥接信号转发到 WorkerThread 级别信号，供 server.SignalBridge 分发
            try:
                self.stream_bridge.stream_chunk_signal.disconnect(self.api_stream_chunk_signal.emit)
            except Exception as e:
                logger.warning(e)
            try:
                self.stream_bridge.stream_status_signal.disconnect(self.api_stream_status_signal.emit)
            except Exception as e:
                logger.warning(e)

            self.stream_bridge.stream_chunk_signal.connect(self.api_stream_chunk_signal.emit)
            self.stream_bridge.stream_status_signal.connect(self.api_stream_status_signal.emit)

        self.daemon_bridge.daemon_suggestion_signal.connect(self.daemon_suggestion_signal.emit)
        self.daemon_bridge.start()
    def _build_context_workspace_payload(self):
        if self.mode == "api" and self.api_source:
            return self.api_source.get_context_workspace_payload()
        return {
            "mode": self.mode,
            "conversation_title": "当前模式暂未接入上下文工作台",
            "conversation_id": None,
            "system": {
                "inject_skills_prompt": False,
                "conversation_system_prompt": "",
                "final_system_prompt": "当前仅 API 模式已接入上下文工作台 V1",
                "final_tokens": 0,
                "system_budget": DEFAULT_SYSTEM_BUDGET,
                "over_budget": False,
                "blocks": []
            },
            "working_memory": {},
            "long_term": {"fragments": [], "count": 0},
            "context_config": {},
            "compact": {},
            "usage": {},
            "history_preview": []
        }

    def _emit_context_workspace_payload(self, client_id=None, user_role=None, conversation_id=None):
        if conversation_id is not None and self.api_source:
            payload = self.api_source.get_context_workspace_payload(conversation_id=conversation_id)
        else:
            payload = self._build_context_workspace_payload()
        try:
            self.context_workspace_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        if client_id:
            remote_payload = dict(payload)
            remote_payload["target_client_id"] = client_id
            remote_payload["target_group"] = "admin" if user_role == "developer" else "user"
            self.context_workspace_signal.emit(remote_payload)
        return payload

    def get_context_workspace_payload(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)

    def update_context_workspace_system_prompt(self, content, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        if self.api_source:
            ok = self.api_source.update_conversation_system_prompt(content, conversation_id=conversation_id)
            self.context_status_signal.emit(self.api_source.get_context_status(conversation_id=conversation_id))
            self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def update_context_workspace_working_memory(self, data, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        if self.api_source:
            ok = self.api_source.set_working_memory(data, conversation_id=conversation_id)
            self.context_status_signal.emit(self.api_source.get_context_status(conversation_id=conversation_id))
            self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def clear_context_workspace_working_memory(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        if self.api_source:
            ok = self.api_source.clear_working_memory(conversation_id=conversation_id)
            self.context_status_signal.emit(self.api_source.get_context_status(conversation_id=conversation_id))
            self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def clear_context_workspace_long_term(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        if self.api_source:
            ok = self.api_source.clear_long_term(conversation_id=conversation_id)
            self.context_status_signal.emit(self.api_source.get_context_status(conversation_id=conversation_id))
            self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
            return ok
        self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=conversation_id)
        return False

    def get_last_request_snapshot(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        """获取最近一次请求的完整上下文快照（用于调试浮窗）。"""
        snap = None
        if self.api_source:
            snap = self.api_source.get_last_request_snapshot(conversation_id=conversation_id)
        payload = snap or {}
        if client_id:
            payload = dict(payload) if payload else {}
            payload['target_client_id'] = client_id
            payload['target_group'] = 'admin' if user_role == 'developer' else 'user'
        try:
            self.context_snapshot_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return snap

    def trigger_api_manual_compact(self, conversation_id=None, client_id='Host', user_role=None, **kwargs):
        group = 'admin' if user_role == 'developer' else 'user'
        if not self.api_source:
            self._init_api_source()
        payload = {
            'ok': False,
            'reason': 'api_source_unavailable',
            'conversation_id': conversation_id or '',
            'target_client_id': client_id,
            'target_group': group,
        }
        if self.api_source:
            result = self.api_source.trigger_manual_compact(conversation_id=conversation_id)
            payload.update(result or {})
            payload['target_client_id'] = client_id
            payload['target_group'] = group
            effective_conv_id = payload.get('conversation_id') or conversation_id or ''
            try:
                self.context_status_signal.emit(self.api_source.get_context_status(conversation_id=effective_conv_id or None))
            except Exception as e:
                logger.warning(e)
            try:
                self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=effective_conv_id or None)
            except Exception as e:
                logger.warning(e)
        try:
            self.api_manual_compact_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return payload

    def get_api_conversations(self, client_id="Host", user_role=None, **kwargs):
        group = "admin" if user_role == "developer" else "user"
        if self.api_source:
            conversations = self.api_source.get_api_conversations()
            payload = {
                "items": conversations,
                "target_client_id": client_id,
                "target_group": group,
            }
            try:
                self.api_conversations_signal.emit(payload)
            except Exception as e:
                logger.warning(e)
            return conversations
        payload = {
            "items": [],
            "target_client_id": client_id,
            "target_group": group,
        }
        try:
            self.api_conversations_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return []

    def delete_api_messages(self, indexes, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        group = "admin" if user_role == "developer" else "user"
        if not self.api_source:
            self._init_api_source()
        removed = 0
        payload = {
            "removed": 0,
            "conversation_id": conversation_id or '',
            "indexes": list(indexes or []),
            "target_client_id": client_id,
            "target_group": group,
        }
        if self.api_source:
            removed = self.api_source.delete_messages(indexes or [], conversation_id=conversation_id)
            effective_conv_id = conversation_id or (self.api_source.conv_store.active_id if self.api_source and self.api_source.conv_store else '')
            payload.update({
                "removed": removed,
                "conversation_id": effective_conv_id or '',
            })
            try:
                if conversation_id and effective_conv_id != (self.api_source.conv_store.active_id if self.api_source and self.api_source.conv_store else None):
                    msgs = self.api_source.get_history_as_messages_for(effective_conv_id)
                else:
                    msgs = self.api_source.get_history_as_messages()
                self.messages_signal.emit(msgs if msgs else [])
            except Exception as e:
                logger.warning(e)
            try:
                self.context_status_signal.emit(self.api_source.get_context_status(conversation_id=effective_conv_id or None))
            except Exception as e:
                logger.warning(e)
            try:
                self._emit_context_workspace_payload(client_id=client_id, user_role=user_role, conversation_id=effective_conv_id or None)
            except Exception as e:
                logger.warning(e)
        try:
            self.api_messages_deleted_signal.emit(payload)
        except Exception as e:
            logger.warning(e)
        return removed

    def set_session_role(self, index, role, **kwargs):
        self.agent.set_role(index, role)
        tag = f"[{role.upper()}]" if role else "标记已清除"
        self.safe_emit_status(f"🏷️ 会话 {index} {tag}")

    def cancel_task(self, task_id, client_id="Host", **kwargs):
        task_id = str(task_id or '').strip()
        if not task_id:
            return

        # 1. 检查是否为运行中的 runtime tool task
        runtime_task = self._runtime_tool_tasks.get(task_id)
        if runtime_task:
            runtime_task['status'] = 'cancel_requested'
            logger.info("[任务取消] 已标记运行中工具任务为 cancel_requested | task_id=%s | tool_name=%s",
                        task_id, runtime_task.get('tool_name', ''))
            self.safe_emit_status(f"⏳ 已请求取消任务 (ID: {task_id})，等待执行器响应...")
            self._emit_queue_monitor_snapshot(reason='cancel_requested')
            return

        # 2. 尝试从 scheduler 排队队列中取消
        if hasattr(self.scheduler, 'cancel_task'):
            success = self.scheduler.cancel_task(task_id)
            if success:
                logger.info("[任务取消] 排队任务已取消 | task_id=%s", task_id)
                self.safe_emit_status(f"🚫 任务已取消 (ID: {task_id})")
                self._emit_queue_monitor_snapshot(reason='cancel_done')
            else:
                self.safe_emit_status(f"⚠️ 无法取消: 任务可能已开始或不可撤销")

    def request_auto_fix(self, error_report, client_id="Host", **kwargs):
        username = kwargs.get('username', 'Unknown')
        mechanic_idx = self.agent.get_mechanic_index()
        return_idx = self.current_physical_index

        if mechanic_idx is None:
            self.safe_emit_status(f"⚠️ 未找到侧车会话，正在自动创建 (User: {username})...")
            self.scheduler.add_task(client_id, "new_chat_task", **kwargs)
            mechanic_idx = 0
            if return_idx is not None:
                return_idx += 1
        else:
            self.scheduler.add_task(client_id, "switch_session_task", mechanic_idx, **kwargs)

        self.safe_emit_status(f"🚑 启动 Agent 模式 -> 会话 {mechanic_idx} [Req: {username}]")
        
        system_prompt = self.agent.construct_system_prompt(error_report)
        self.scheduler.add_task(client_id, "real_send_text", "div.aa-chat-input textarea", system_prompt, **kwargs)
        self.scheduler.add_task(client_id, "task_agent_loop", return_idx, 10, **kwargs)

    def _execute_task(self, task):
        try:
            user = getattr(task, 'username', 'System')
            self.current_user = user

            if task.action == "task_agent_loop":
                self._execute_agent_loop_task(task)
                return

            if task.action in ["do_server_backup", "run_remote_tests"]:
                self.executor.submit(self._execute_task_bg, task)
            else:
                self._execute_task_sync(task)

        except Exception as e:
            logger.error("调度器异常: %s", e, extra=get_trace_extra())
            traceback.print_exc()
            self.safe_emit_status(f"🔥 任务出错: {e}")

    def _execute_agent_loop_task(self, task):
        return_idx = task.args[0]
        turns_left = task.args[1]

        if self.connector.is_busy():
            self.safe_emit_status("⏳ Agent 思考中...")
            self.scheduler.add_task(task.client_id, "task_agent_loop", return_idx, turns_left, username=self.current_user)
            time.sleep(1.0)
            return

        raw_msgs, _ = self.connector.get_chat_content(self.target_class, auto_wake=True)
        if not raw_msgs:
            self.scheduler.add_task(task.client_id, "task_agent_loop", return_idx, turns_left, username=self.current_user)
            time.sleep(1.0)
            return

        last_msg = raw_msgs[-1]
        full_text = "\n".join(
            [s['content'] for s in last_msg.get('segments', []) if s['type'] == 'text']
        )

        if "```tool_call" in full_text or "```python" in full_text:
            block_code = full_text.split("```python")[-1].strip()
            if not re.match(r"^\s*(#|//|<!--)\s*filename\s*:", block_code, re.IGNORECASE):
                self.safe_emit_status("🤖 [Agent] 正在执行代码 (Docker)...")

                # 统一去重：优先用 message_id，fallback 到内容指纹
                msg_id = str(last_msg.get('id', '') or '').strip()
                with self._processed_lock:
                    if msg_id:
                        _agent_fp = f"{self.current_chat_id}|mid:{msg_id}"
                    else:
                        _agent_fp = f"{self.current_chat_id}|fp:{hashlib.md5(full_text.encode('utf-8')).hexdigest()}"
                    if _agent_fp in self._processed_tool_fingerprints:
                        return  # 已处理过，跳过
                    self._processed_tool_fingerprints.add(_agent_fp)
                    self._processed_fp_order.append(_agent_fp)

                fake_msgs = [{"role": "AI", "index": 9999, "segments": [{"type": "text", "content": full_text}]}]

                result = self.tool_router.maybe_handle_tool_from_messages(
                    chat_id=self.current_chat_id,
                    messages=fake_msgs,
                    allow=True
                )
                result_text = self._build_browser_tool_feedback_text(result)

                if result_text:
                    pending = self.get_and_clear_pending_message()
                    if pending:
                        pending_text = str(pending.get("text", "") or "").strip()
                        if pending_text:
                            result_text = result_text + f"\n\n[USER_MESSAGE_BEGIN]\n{pending_text}\n[USER_MESSAGE_END]"
                            self.safe_emit_status("✅ 已附加用户待发消息")

                    self.connector.send_message(
                        "div.aa-chat-input textarea",
                        f"{result_text}\n\nNext Step?"
                    )
                    self.scheduler.add_task(task.client_id, "task_agent_loop", return_idx, turns_left - 1, username=self.current_user)
                    return

        intent, data = self.agent.parse_agent_response(full_text)

        if intent == "TOOL":
            self.safe_emit_status("🔧 [Agent] 检测到工具调用意图，交由 ToolRouter 处理...")
            if turns_left > 0:
                self.scheduler.add_task(task.client_id, "task_agent_loop", return_idx, turns_left - 1, username=self.current_user)
            return

        elif intent == "CODE":
            self.safe_emit_status("🛡️ 检测到代码变更，正在安全验证...")
            success, changed_files, log = self.agent.safe_apply_and_test(
                last_msg.get('segments', [])
            )
            if success:
                self.safe_emit_status("🎉 修复成功！测试通过！")
                self.safe_emit_status("🔙 返回主会话...")
                self.scheduler.add_task(task.client_id, "switch_session_task", return_idx, username=self.current_user)
                
                needs_restart = any(
                    self.update_service.get_file_category(f) in ["CRITICAL", "CLIENT_ONLY"]
                    for f in changed_files
                )
                if needs_restart:
                    self.scheduler.add_task(task.client_id, "task_restart_if_needed", username=self.current_user)
                return
            else:
                if turns_left > 0:
                    self.safe_emit_status("❌ 验证失败(已回滚)，反馈报错...")
                    report = ErrorReporter.generate_report(log)
                    prompt = (
                        "❌ 代码导致测试失败 (环境已回滚)。\n\n"
                        f"【New Traceback】\n{report}\n\n请重新分析并修复。"
                    )
                    self.connector.send_message("div.aa-chat-input textarea", prompt)
                    self.scheduler.add_task(task.client_id, "task_agent_loop", return_idx, turns_left - 1, username=self.current_user)
                    return
                else:
                    self.safe_emit_status("❌ 次数耗尽，修复中止")
                    self.scheduler.add_task(task.client_id, "switch_session_task", return_idx, username=self.current_user)
                    return

        if turns_left > 0:
            self.scheduler.add_task(task.client_id, "task_agent_loop", return_idx, turns_left - 1, username=self.current_user)
        else:
            self.scheduler.add_task(task.client_id, "switch_session_task", return_idx, username=self.current_user)

    def _execute_task_sync(self, task):
        self.safe_emit_status(f"🟢 执行: {task.action} (User: {getattr(task, 'username', 'Unknown')})")

        if task.action == "task_restart_if_needed":
            self.restart_needed_signal.emit(True)

        elif task.action == "switch_session_task":
            self._update_ai_state("switching")
            idx = task.args[0]
            if self.connector.switch_session(idx):
                self.current_physical_index = idx
                detected_title_id = self.connector.get_chat_title_id()
                if detected_title_id:
                    self.current_chat_id = detected_title_id
                else:
                    self.current_chat_id = f"session_{idx}_{id(self)}"
                self._normalizer.clear()
                self.safe_emit_status("✅ 会话切换成功")
                time.sleep(1.0)
                raw_msgs, _ = self.connector.get_chat_content(self.target_class, auto_wake=False)
                if raw_msgs:
                    self._do_push_extracted_messages(
                        self.file_service.process_images(raw_msgs),
                        reason='switch_session',
                        force_full=True,
                    )
                self._check_and_emit_sync(True)
                if self.connector.interact:
                    self.safe_emit_status("📜 内容已上屏，开始执行全页唤醒...")
                    self.connector.force_scroll(
                        interrupt_callback=lambda: not self.scheduler.queue.empty()
                    )
            else:
                self.safe_emit_status("❌ 会话切换失败")

        elif task.action == "new_chat_task":
            self._update_ai_state("switching")
            self.safe_emit_status("⚠️ 创建新会话...")
            ok, msg = self.connector.new_chat()
            if ok:
                detected_title_id = self.connector.get_chat_title_id()
                if detected_title_id:
                    self.current_chat_id = detected_title_id
                else:
                    self.current_chat_id = f"new_chat_{id(self)}"
                self._normalizer.clear()
                self.safe_emit_status("✨ 新会话已创建")
            self.agent.shift_roles_for_new_chat()

        elif task.action == "real_send_text":
            self._pre_send_ai_fingerprint = self._get_last_ai_fingerprint()
            self.connector.send_message(task.args[0], task.args[1])
            time.sleep(0.5)  # 等待消息上屏
            if self.connector.interact:
                self.connector.interact.scroll_to_bottom()  # 滚动到底部

        elif task.action == "compound_send_task":
            self._pre_send_ai_fingerprint = self._get_last_ai_fingerprint()
            text, file_paths = task.args
            if file_paths and self.connector.interact:
                self.connector.interact.upload_file(file_paths)
                time.sleep(1.5)
            if text:
                self.connector.send_message("div.aa-chat-input textarea", text)

        elif task.action == "upload_file_task":
            self.connector.interact.upload_file(task.args[0])

        elif task.action == "task_fix_all":
            self._batch_fix_all()

        elif task.action == "task_batch_end":
            self.toggle_queue.append("BATCH_END")

        elif task.action == "task_manual_toggle":
            msg_index, blk_idx, total = task.args[0], task.args[1], task.args[2]
            fingerprint = task.kwargs.get("fingerprint")
            self.toggle_queue.append((msg_index, blk_idx, total, fingerprint))

        elif task.action == "task_ignore_block":
            filename, content = task.args
            ok, msg = self.file_service.add_ignored_content(filename, content)
            self.safe_emit_status(f"🗑️ {msg}")

        elif task.action == "task_wake_up":
            self.connector.force_scroll()

    def _execute_task_bg(self, task):
        try:
            if task.action == "do_server_backup":
                self.do_server_backup(task.args[0])
            elif task.action == "run_remote_tests":
                self.run_remote_tests(task.client_id)
        except Exception as e:
            logger.error("后台任务失败 %s: %s", task.action, e)
            traceback.print_exc()

    def ignore_block_content(self, filename, content, client_id="Host", **kwargs):
        threading.Thread(target=self._do_ignore_block, args=(filename, content)).start()

    def _do_ignore_block(self, filename, content):
        ok, msg = self.file_service.add_ignored_content(filename, content)
        self.safe_emit_status(f"🗑️ {msg}")

    def unignore_block_content(self, filename, content, client_id="Host", **kwargs):
        threading.Thread(target=self._do_unignore_block, args=(filename, content)).start()

    def _do_unignore_block(self, filename, content):
        if hasattr(self.file_service, 'remove_ignored_content'):
            ok, msg = self.file_service.remove_ignored_content(content)
            self.safe_emit_status(f"♻️ {msg}")
            
            if ok:
                self.safe_emit_status("🔄 正在回溯并重新扫描代码...")
                try:
                    self.process_batch(self.last_messages_snapshot)
                    self.do_server_scan()
                except Exception as e:
                    self.safe_emit_status(f"⚠️ 回溯扫描失败: {e}")
        else:
            self.safe_emit_status("❌ FileService 不支持撤销操作")

    def run_remote_tests(self, client_id="Host", **kwargs):
        self.safe_emit_status(f"🧪 [测试] 正在后台运行 pytest...")
        self._run_tests_bg(client_id)

    def _run_tests_bg(self, client_id):
        cwd = ProjectContext.get().get_project_root()
        cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                cwd=cwd,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            full_log = []
            logger.info("TestRunner: 开始执行 pytest...")
            
            for line in process.stdout:
                line = line.strip()
                if not line: continue
                logger.debug("测试日志: %s", line)
                full_log.append(line)
            
            process.wait()
            
            full_text = "\n".join(full_log)
            passed = full_text.count("PASSED")
            failed = full_text.count("FAILED")
            error = full_text.count("ERROR")
            
            duration = "0"
            m = re.search(r"in ([\d\.]+)s", full_text.splitlines()[-1] if full_log else "")
            if m: duration = m.group(1)
            
            result_payload = {
                "target_client_id": client_id,
                "passed": passed,
                "failed": failed + error,
                "duration": duration,
                "full_log": full_text
            }
            
            self.test_result_signal.emit(result_payload)
            self.safe_emit_status(f"✅ [测试完成] Pass: {passed}, Fail: {failed}")

        except Exception as e:
            err_msg = f"测试启动失败: {e}"
            logger.error(err_msg)
            self.test_result_signal.emit({
                "target_client_id": client_id,
                "passed": 0,
                "failed": 1,
                "duration": "0",
                "full_log": err_msg
            })

    def _notify_daemon_reply_completed(self, mode: str, chat_id: str = ""):
        try:
            logger.info(
                "[DaemonWorker] 进入回复完成通知: mode=%s chat_id=%s has_connector=%s has_api_source=%s has_daemon_bridge=%s",
                mode,
                chat_id,
                bool(getattr(self, 'connector', None)),
                bool(getattr(self, 'api_source', None)),
                bool(getattr(self, 'daemon_bridge', None)),
            )

            reply_text = ""
            recent_context = ""
            history_count = 0
            assistant_count = 0

            def _extract_text(msg):
                if not isinstance(msg, dict):
                    return ""
                if mode == "browser":
                    text_parts = []
                    for seg in (msg.get("segments") or []):
                        if not isinstance(seg, dict):
                            continue
                        content = str(seg.get("content", "") or "")
                        if not content.strip():
                            continue
                        if seg.get("type") == "code":
                            lang = str(seg.get("language", "") or "text").strip() or "text"
                            if content.strip().startswith("```"):
                                text_parts.append(content)
                            else:
                                text_parts.append(f"```{lang}\n{content}\n```")
                        else:
                            text_parts.append(content)
                    if not text_parts:
                        fallback_text = str(msg.get("content", "") or msg.get("text", "") or "")
                        if fallback_text.strip():
                            text_parts.append(fallback_text)
                    return "\n\n".join(text_parts).strip()
                text = str(
                    msg.get("content", "")
                    or msg.get("text", "")
                    or msg.get("raw_content", "")
                    or ""
                ).strip()
                if text:
                    return text
                text_parts = []
                for seg in (msg.get("segments") or []):
                    if not isinstance(seg, dict):
                        continue
                    content = str(seg.get("content", "") or "")
                    if content.strip():
                        text_parts.append(content)
                return "\n\n".join(text_parts).strip()

            def _normalize_role(msg):
                if not isinstance(msg, dict):
                    return ""
                role = str(msg.get("role", "") or "").strip().lower()
                if role == "ai":
                    return "assistant"
                return role

            def _build_recent_context(entries, reply_index):
                if reply_index is None or reply_index <= 0:
                    return ""
                start_index = max(0, reply_index - 5)
                context_lines = []
                for item in entries[start_index:reply_index]:
                    role = item.get("role", "")
                    text = str(item.get("text", "") or "").strip()
                    if not text:
                        continue
                    label = "用户" if role == "user" else "AI" if role in ("assistant", "ai") else role or "未知"
                    context_lines.append(f"{label}：{text}")
                return "\n".join(context_lines).strip()

            message_entries = []
            if mode == "api" and self.api_source:
                logger.info("[DaemonWorker] API 准备读取历史消息")
                history = self.api_source.get_history_as_messages() or []
                history_count = len(history)
                logger.info("[DaemonWorker] API 历史消息读取完成: count=%d", history_count)
                for msg in history:
                    if not isinstance(msg, dict):
                        continue
                    role = _normalize_role(msg)
                    text = _extract_text(msg)
                    if not text:
                        continue
                    message_entries.append({"role": role, "text": text})
            elif mode == "browser" and self.connector:
                logger.info("[DaemonWorker] Browser 准备读取结构化消息")
                if hasattr(self.connector, "get_chat_content"):
                    raw_msgs, _is_at_bottom = self.connector.get_chat_content(auto_wake=False)
                else:
                    logger.warning("[DaemonWorker] Browser connector 不支持 get_chat_content，无法读取回复文本")
                    raw_msgs = []
                raw_msgs = raw_msgs or []
                history_count = len(raw_msgs)
                logger.info("[DaemonWorker] Browser 消息读取完成: count=%d type=%s", history_count, type(raw_msgs).__name__)
                for msg in raw_msgs:
                    if not isinstance(msg, dict):
                        continue
                    role = _normalize_role(msg)
                    text = _extract_text(msg)
                    if not text:
                        continue
                    message_entries.append({"role": role, "text": text})
            else:
                logger.warning(
                    "[DaemonWorker] 回复完成通知缺少可用消息源: mode=%s has_connector=%s has_api_source=%s",
                    mode,
                    bool(getattr(self, 'connector', None)),
                    bool(getattr(self, 'api_source', None)),
                )

            reply_index = None
            for idx in range(len(message_entries) - 1, -1, -1):
                role = message_entries[idx].get("role", "")
                if role in ("assistant", "ai"):
                    reply_index = idx
                    reply_text = str(message_entries[idx].get("text", "") or "").strip()
                    assistant_count += 1
                    logger.info("[DaemonWorker] 命中 assistant 消息: reverse_idx=%d reply_len=%d", len(message_entries) - idx, len(reply_text or ""))
                    break

            recent_context = _build_recent_context(message_entries, reply_index)

            logger.info(
                "[DaemonWorker] 回复完成检查: mode=%s chat_id=%s history_count=%d assistant_count=%d reply_len=%d recent_context_len=%d has_daemon_bridge=%s",
                mode,
                chat_id,
                history_count,
                assistant_count,
                len(reply_text or ""),
                len(recent_context or ""),
                bool(getattr(self, 'daemon_bridge', None)),
            )
            if reply_text:
                logger.info("[DaemonWorker] 触发守护通知: mode=%s chat_id=%s", mode, chat_id)
                self.daemon_bridge.on_reply_completed(reply_text, mode, chat_id, recent_context=recent_context)
            else:
                logger.info("[DaemonWorker] 未获取到 assistant 回复文本，跳过守护通知")
        except Exception as e:
            logger.warning("[DaemonWorker] 守护进程通知异常: %s", e)
            traceback.print_exc()

    def _background_process_ai_response(self):
        try:
            self._round_sm.handle_event(RoundStateEvent.PIPELINE_START)
            logger.info("流水线: 开始处理 AI 回复...")
            time.sleep(2.0)

            # [message_id 去重] 用 DOM 的 data-message-id 判断是否已处理
            # 不依赖内容指纹（text[:150] 不稳定，AutoFix 可能改任意位置）
            ai_msg_id = self.connector.get_last_ai_message_id() if self.connector else ''
            if not ai_msg_id:
                logger.info("[流水线] 未获取到 AI 消息 ID，跳过")
                self._round_sm.handle_event(RoundStateEvent.PIPELINE_END)
                return
            with self._processed_lock:
                if ai_msg_id == self._last_processed_ai_msg_id:
                    logger.debug("[流水线] 消息已处理 | ai_msg_id=%s，跳过", ai_msg_id)
                    self._round_sm.handle_event(RoundStateEvent.PIPELINE_END)
                    return

            # [AutoFix] 展开代码块 + 遍历渲染
            if self.connector.interact:
                self.connector.interact.scan_and_fix_last_message()
                self._last_fixed_ai_msg_id = ai_msg_id
                self._last_fixed_at = time.time()
                time.sleep(0.2)

            # [snapshot 推送] AutoFix 完成后立即推送修复后的内容
            # 必须在 _check_and_handle_tool() 之前推送，原因：
            # - 工具结果回流是新的一轮对话（新 message-id）
            # - 如果跳过此 snapshot，后续流水线处理新消息，原消息修复状态永远不会推到客户端
            # - 此时 DOM 是安全的：工具结果还在 scheduler 队列中，浏览器尚未开始输入
            # 关键：必须先失效缓存，否则增量提取器会命中旧缓存（修复前的折叠状态）
            if ai_msg_id and hasattr(self.connector, '_incremental'):
                self.connector._incremental.cache.invalidate_message(ai_msg_id)
            self.executor.submit(self._emit_browser_messages_snapshot, reason='after_autofix')

            # [工具识别与执行] AutoFix 完成后立即进入，不依赖外部事件
            self._check_and_handle_tool()
            self._last_processed_ai_msg_id = ai_msg_id
            self._pre_send_ai_fingerprint = None

            # 显式收尾：只有仍处于 FIXING（无工具触发）才回 IDLE
            # TOOL_EXECUTING / SYSTEM_SENDING 由后续流转自行处理，绝不在此处回 IDLE
            if self._round_sm.state == BrowserRoundState.FIXING:
                self._round_sm.handle_event(RoundStateEvent.PIPELINE_END)
                logger.info("[流水线] 无工具调用，回合结束 | ai_msg_id=%s", ai_msg_id)
            else:
                logger.info("[流水线] 处理完成 | ai_msg_id=%s | state=%s（等待后续流转）", ai_msg_id, self._round_sm.state_value)
        except Exception as e:
            logger.error("流水线崩溃: %s", e)
            traceback.print_exc()
            self._round_sm.handle_event(RoundStateEvent.ERROR_RESET)

    def _background_process_ai_response_direct(self):
        """超时兜底 / 修复按钮专用：跳过指纹对比，直接执行流水线"""
        try:
            logger.info("兜底流水线: 直接执行...")

            ai_msg_id = ''
            try:
                tool_input = self._extract_browser_tool_input()
                ai_msg_id = str(tool_input.get('last_ai_msg_id', '') or '').strip()
            except Exception:
                pass

            should_skip_fix = False
            if ai_msg_id and self._last_fixed_ai_msg_id == ai_msg_id:
                if (time.time() - float(self._last_fixed_at or 0)) < 15:
                    should_skip_fix = True
                    logger.info("[AutoFix] 跳过重复兜底修复 | ai_msg_id=%s", ai_msg_id)

            if self.connector.interact and not should_skip_fix:
                self.connector.interact.scan_and_fix_last_message()
                if ai_msg_id:
                    self._last_fixed_ai_msg_id = ai_msg_id
                    self._last_fixed_at = time.time()
                time.sleep(0.2)

            # [snapshot 推送] 同主流水线：AutoFix 后、工具执行前推送
            # 同样需要先失效缓存，强制重新提取修复后的内容
            if ai_msg_id and hasattr(self.connector, '_incremental'):
                self.connector._incremental.cache.invalidate_message(ai_msg_id)
            self.executor.submit(self._emit_browser_messages_snapshot, reason='after_autofix_direct')

            self._pre_send_ai_fingerprint = None
            self._check_and_handle_tool()

            # 显式收尾：同主流水线，只有 FIXING 才回 IDLE
            if self._round_sm.state == BrowserRoundState.FIXING:
                self._round_sm.handle_event(RoundStateEvent.PIPELINE_END)
                logger.info("[兜底流水线] 无工具调用，回合结束 | ai_msg_id=%s", ai_msg_id)
            else:
                logger.info("[兜底流水线] 处理完成 | ai_msg_id=%s | state=%s（等待后续流转）", ai_msg_id, self._round_sm.state_value)
        except Exception as e:
            logger.error("兜底流水线: %s", e)
            traceback.print_exc()
            self._round_sm.handle_event(RoundStateEvent.ERROR_RESET)

    def _emit_browser_messages_snapshot(self, reason='background_sync'):
        """浏览器模式：主动抓取当前稳定消息并推送给 UI，避免修复完成后仍停留旧视图。
        使用增量提取器，由状态机事件驱动缓存失效。"""
        if not self.connector.interact:
            return False
        try:
            # [诊断] 记录推送前的 code_fingerprint 快照
            old_fps = {}
            if reason == 'after_autofix' and self.last_messages_snapshot:
                for msg in self.last_messages_snapshot:
                    msg_id = str(msg.get('id', '') or '')[:12]
                    for seg in (msg.get('segments') or []):
                        if isinstance(seg, dict) and seg.get('type') == 'code':
                            fp = str(seg.get('code_fingerprint', '') or '')
                            old_fps[f"{msg_id}:{seg.get('block_index', '?')}"] = fp

            raw_msgs, _, _ = self.connector.get_chat_content_incremental(
                transient_last_ai=False
            )

            # [诊断] 对比 AutoFix 前后 code_fingerprint 变化
            if reason == 'after_autofix' and old_fps:
                new_fps = {}
                for msg in raw_msgs:
                    msg_id = str(msg.get('id', '') or '')[:12]
                    for seg in (msg.get('segments') or []):
                        if isinstance(seg, dict) and seg.get('type') == 'code':
                            fp = str(seg.get('code_fingerprint', '') or '')
                            new_fps[f"{msg_id}:{seg.get('block_index', '?')}"] = fp
                changed_keys = []
                for k in set(list(old_fps.keys()) + list(new_fps.keys())):
                    old_fp = old_fps.get(k, '<无>')
                    new_fp = new_fps.get(k, '<无>')
                    if old_fp != new_fp:
                        changed_keys.append(f"{k}: fp {old_fp[:12]}→{new_fp[:12]}")
                if changed_keys:
                    logger.info("[snapshot-诊断] AutoFix后代码内容变化 | reason=%s | 变化数=%s | 详情=%s",
                                reason, len(changed_keys), changed_keys)
                else:
                    logger.debug("[snapshot-诊断] AutoFix后代码内容无变化 | reason=%s", reason)

            self._do_push_extracted_messages(raw_msgs, reason=f'snapshot_{reason}')
            self.state_service.save_states()
            self._check_and_emit_sync()
            return True
        except Exception as e:
            logger.warning(f"浏览器稳定消息同步失败: {e}")
            return False

    def _get_last_ai_fingerprint(self, live=False):
        """获取最后一条 AI 消息的指纹。live=True 时从浏览器实时获取"""
        try:
            if live:
                text = self.connector.check_last_ai_message_for_tool() or ''
                return hashlib.md5(text[:150].encode()).hexdigest() if text else None
            if self.last_messages_snapshot:
                last = self.last_messages_snapshot[-1]
                text = ''.join(
                    s.get('content', '')[:50]
                    for s in last.get('segments', [])[:3]
                )
                return hashlib.md5(text.encode()).hexdigest() if text else None
        except Exception as e:
            logger.warning(f"获取工具指纹失败: {e}")
        return None

    def _check_and_handle_tool(self):
        try:
            if not self.connector.interact:
                return

            tool_input = self._extract_browser_tool_input()
            candidate_messages = list(tool_input.get('messages') or [])
            fingerprint_source = str(tool_input.get('fingerprint_source', '') or '')
            fallback_text = str(tool_input.get('fallback_text', '') or '')
            used_structured = bool(tool_input.get('used_structured'))
            ai_msg_id = str(tool_input.get('last_ai_msg_id', '') or '').strip()

            if not candidate_messages:
                logger.info("[工具路由] 无候选消息，跳过工具检测 | ai_msg_id=%s", ai_msg_id)
                return

            probe("tool_router_input", level="debug", side="worker",
                  mode="structured" if used_structured else "fallback",
                  msg_count=len(candidate_messages),
                  fingerprint_len=len(fingerprint_source),
                  ai_msg_id=ai_msg_id)
            probe("tool_router_msg_preview", level="debug", side="worker",
                  preview=fallback_text[:300] if fallback_text else None)

            tool_input_kind = self._classify_browser_tool_input(
                candidate_messages,
                fallback_text=fallback_text,
                used_structured=used_structured,
            )

            # [重试] 首次分类为 'none' 时，DOM 可能尚未稳定（AutoFix 刚改过），等 1s 重试
            if tool_input_kind == 'none':
                time.sleep(1.0)
                tool_input = self._extract_browser_tool_input()
                candidate_messages = list(tool_input.get('messages') or [])
                fingerprint_source = str(tool_input.get('fingerprint_source', '') or '')
                fallback_text = str(tool_input.get('fallback_text', '') or '')
                used_structured = bool(tool_input.get('used_structured'))
                ai_msg_id = str(tool_input.get('last_ai_msg_id', '') or '').strip()
                if candidate_messages:
                    tool_input_kind = self._classify_browser_tool_input(
                        candidate_messages,
                        fallback_text=fallback_text,
                        used_structured=used_structured,
                    )

            if tool_input_kind == 'none':
                probe("tool_router_skip", level="debug", side="worker",
                      reason="classified_none",
                      mode="structured" if used_structured else "fallback")
                logger.info("[工具路由] 未检测到工具调用，流水线正常结束 | ai_msg_id=%s", ai_msg_id)
                return

            # === 统一去重：message_id 主键 + fallback 复合键 ===
            with self._processed_lock:
                if ai_msg_id:
                    dedup_key = f"{self.current_chat_id}|mid:{ai_msg_id}"
                else:
                    dedup_key = f"{self.current_chat_id}|fp:{hashlib.md5(fingerprint_source.encode('utf-8')).hexdigest()}"

                if dedup_key in self._processed_tool_fingerprints:
                    logger.debug("[去重] 跳过已处理消息 | dedup_key=%s | chat_id=%s", dedup_key[:40], self.current_chat_id)
                    return

                # FIFO 淘汰：超上限时移除最旧的 300 条
                if len(self._processed_tool_fingerprints) >= 500:
                    evicted = 0
                    while self._processed_fp_order and evicted < 300:
                        old_key = self._processed_fp_order.popleft()
                        self._processed_tool_fingerprints.discard(old_key)
                        evicted += 1
                    logger.info("[去重] FIFO 淘汰 %d 条旧指纹", evicted)

                self._processed_tool_fingerprints.add(dedup_key)
                self._processed_fp_order.append(dedup_key)

            if tool_input_kind == 'tool_feedback':
                logger.info("[工具路由] 浏览器模式识别为 tool_feedback，跳过执行链 | mode=%s | chat_id=%s",
                            "structured" if used_structured else "fallback",
                            self.current_chat_id)
                probe("tool_router_feedback_skip", level="info", side="worker",
                      mode="structured" if used_structured else "fallback")
                return

            probe("tool_router_new_message", level="info", side="worker",
                  mode="structured" if used_structured else "fallback",
                  ai_msg_id=ai_msg_id)

            self._round_sm.handle_event(RoundStateEvent.TOOL_EXECUTION_START)

            logger.info("[工具路由] 开始工具识别与执行 | ai_msg_id=%s | 消息数=%s",
                        ai_msg_id, len(candidate_messages))
            _t0 = time.time()
            response = self.tool_router.maybe_handle_tool_from_messages(
                chat_id=self.current_chat_id,
                messages=candidate_messages,
                allow=True,
                on_intent_start=self._handle_runtime_tool_start,
                on_intent_end=self._handle_runtime_tool_end,
            )
            logger.info("[工具路由] 工具识别与执行完成 | 耗时=%.1fs | ai_msg_id=%s",
                        time.time() - _t0, ai_msg_id)

            response_text = self._build_browser_tool_feedback_text(response)

            probe("tool_router_response", level="debug", side="worker",
                  resp_type=type(response).__name__,
                  resp_len=len(response_text) if response_text else 0,
                  preview=response_text[:200] if response_text else None)

            if response_text:
                # 记录已处理的 message_id，防止同消息重复进链
                if ai_msg_id:
                    self._last_processed_ai_msg_id = ai_msg_id

                probe("tool_router_result", level="info", side="worker",
                      mode="structured" if used_structured else "fallback")
                self.safe_emit_status("📤 工具执行完成，正在回传结果...")

                # 提取 tool_call_id 用于 send 去重和 UI 展示
                tc_ids = []
                if response and hasattr(response, 'results'):
                    tc_ids = [r.tool_call_id for r in response.results if r.tool_call_id]
                primary_tc_id = tc_ids[0] if tc_ids else ''

                # Send 去重：chat_id|send:{msg_id}:{tcid} 防止同一结果重复入队
                with self._processed_lock:
                    send_key = f"{self.current_chat_id}|send:{ai_msg_id}:{primary_tc_id}"
                    if send_key in self._processed_tool_fingerprints:
                        logger.debug("[去重] 跳过重复发送 | send_key=%s", send_key[:50])
                        return
                    self._processed_tool_fingerprints.add(send_key)
                    self._processed_fp_order.append(send_key)

                # 用户待发消息拼接到工具结果末尾，浏览器一问一答限制下必须同轮发出
                pending = self.get_and_clear_pending_message()
                if pending:
                    pending_text = str(pending.get("text", "") or "").strip()
                    if pending_text:
                        response_text = response_text + f"\n\n[USER_MESSAGE_BEGIN]\n{pending_text}\n[USER_MESSAGE_END]"
                        self.safe_emit_status("✅ 已附加用户待发消息")
                        logger.info("[工具路由] 用户待发消息已附加到工具结果")

                self._round_sm.handle_event(RoundStateEvent.TOOL_RESULT_READY)
                self.scheduler.add_task(
                    "Host",
                    "real_send_text",
                    "div.aa-chat-input textarea",
                    response_text,
                    username="System",
                    tool_call_id=primary_tc_id,
                    tool_name="tool_feedback",
                )
                logger.info("[工具路由] 工具结果已入队 scheduler | ai_msg_id=%s | tool_call_id=%s", ai_msg_id, primary_tc_id)

        except Exception as e:
            logger.error("工具路由异常: %s", e)
            traceback.print_exc()
        finally:
            # 正常路径：工具成功/失败都有 response_text → TOOL_RESULT_READY → SYSTEM_SENDING
            # 异常路径：maybe_handle_tool_from_messages 抛异常 → state 仍在 TOOL_EXECUTING
            # 此处只处理异常路径，正常路径 state 已经是 SYSTEM_SENDING，不动
            self._round_sm.try_tool_failed()

    def send_context_pack(self, pack_key, session_index, goal_text="", client_id="Host", **kwargs):
        try:
            idx = int(session_index)
        except Exception:
            idx = 0

        try:
            pack_text = self.context_pack_service.build_pack_text(
                str(pack_key),
                goal_text=str(goal_text or ""),
                include_ai_readme=True,
                include_project_structure=True,
            )
        except Exception as e:
            self.safe_emit_status(f"❌ Context Pack Error: {e}")
            return

        self.safe_emit_status(f"📦 Context Pack 入队: {pack_key} -> 会话 {idx}")
        self.scheduler.add_task(client_id, "switch_session_task", idx, **kwargs)
        self.scheduler.add_task(
            client_id,
            "real_send_text",
            "div.aa-chat-input textarea",
            pack_text,
            **kwargs
        )

    def get_staging_file_content(self, rel_path, client_id="Host", **kwargs):
        staging_dir = self.config.get("export_code_path", "export/code")
        new_path = os.path.join(staging_dir, rel_path)
        new_content = "File not found"
        try:
            if os.path.exists(new_path):
                with open(new_path, 'r', encoding='utf-8') as f:
                    new_content = f.read()
        except Exception as e:
            new_content = f"Error reading staging: {e}"
        project_root = ProjectContext.get().get_project_root()
        old_path = os.path.join(project_root, rel_path)
        old_content = None
        try:
            if os.path.exists(old_path):
                with open(old_path, 'r', encoding='utf-8') as f:
                    old_content = f.read()
        except Exception as e:
            logger.warning(f"读取旧文件内容失败: {e}")
        self.file_preview_signal.emit({
            "target_client_id": client_id,
            "rel_path": rel_path,
            "content": new_content,
            "old_content": old_content
        })

    def handle_sync_request(self, client_id="Host", **kwargs):
        self.safe_emit_status(f"🔄 [Sync] {client_id} 请求同步...")
        sync_data = self.update_service.pack_client_code()
        self.ota_sync_signal.emit(sync_data)

    def handle_compound_send(self, text, file_paths, client_id="Host", **kwargs):
        self.scheduler.add_task(client_id, "compound_send_task", text, file_paths, **kwargs)

    def send_compound(self, text, file_paths, client_id="Host", **kwargs):
        self.handle_compound_send(text, file_paths, client_id, **kwargs)

    def upload_file(self, file_path, client_id="Host", **kwargs):
        self.scheduler.add_task(client_id, "upload_file_task", file_path, **kwargs)

    def _build_browser_tool_feedback_text(self, payload) -> str:
        import json
        import re

        def _clean_body_text(text: str) -> str:
            body = str(text or '').strip()
            if not body:
                return ''
            body = re.sub(r'^🔧\s*\[工具调用\s*\d+\]\s*[^\n]*\n?', '', body, count=1, flags=re.MULTILINE).strip()
            return body

        if not isinstance(payload, ToolRoundResult):
            return str(payload or '').strip()

        results = list(payload.results or [])
        if not results:
            return str(payload.combined_feedback or '').strip()

        blocks = ['[TOOL_RESULTS_BEGIN version=2]']
        for idx, result in enumerate(results, start=1):
            tool_name = str(
                getattr(result, 'name', '')
                or getattr(result, 'tool_name', '')
                or getattr(result, 'kind', '')
                or 'tool_result'
            ).strip() or 'tool_result'
            success = getattr(result, 'success', None)
            tool_call_id = getattr(result, 'tool_call_id', None)
            block_key = getattr(result, 'block_key', None)
            task_id = getattr(result, 'task_id', None) or tool_call_id

            content_text = ''
            for attr_name in ('display_text', 'content', 'output', 'error'):
                value = getattr(result, attr_name, None)
                if value:
                    content_text = str(value).strip()
                    if content_text:
                        break
            if not content_text:
                content_text = str(result or '').strip()
            content_text = _clean_body_text(content_text)

            call_meta = {
                'protocol': 'tool_call_v1',
                'tool_call_id': tool_call_id,
                'block_key': block_key,
                'tool_name': tool_name,
            }
            blocks.append(f'[TOOL_CALL_META] {json.dumps(call_meta, ensure_ascii=False, sort_keys=True)}')
            meta = {
                'protocol': 'tool_result_v2',
                'seq': idx,
                'tool_name': tool_name,
                'tool_call_id': tool_call_id,
                'block_key': block_key,
                'task_id': task_id,
                'success': success,
                'result_format': 'text',
            }
            blocks.append(f'[TOOL_RESULT_META] {json.dumps(meta, ensure_ascii=False, sort_keys=True)}')
            blocks.append('[TOOL_RESULT_BODY]')
            if content_text:
                blocks.append(content_text)
            blocks.append('[TOOL_RESULT_END]')
            blocks.append('')

        if blocks and blocks[-1] == '':
            blocks.pop()
        blocks.append('[TOOL_RESULTS_END]')
        return '\n'.join(blocks)

    def send_text(self, selector, text, client_id="Host", **kwargs):
        self.scheduler.add_task(client_id, "real_send_text", selector, text, **kwargs)

    def run_remote_script(self, code, client_id="Host", **kwargs):
        prompt = f"请执行/解释以下代码:\n```python\n{code}\n```"
        self.scheduler.add_task(
            client_id,
            "real_send_text",
            "div.aa-chat-input textarea",
            prompt,
            **kwargs
        )

    def request_switch_session(self, index, client_id="Host", **kwargs):
        self.scheduler.add_task(client_id, "switch_session_task", index, **kwargs)

    def new_chat(self, client_id="Host", **kwargs):
        self.scheduler.add_task(client_id, "new_chat_task", **kwargs)

    def request_wake_up(self, client_id="Host", **kwargs):
        self.scheduler.add_task(client_id, "task_wake_up", **kwargs)

    def request_fix_all(self, client_id="Host", **kwargs):
        self.scheduler.add_task(client_id, "task_fix_all", **kwargs)

    def trigger_manual_toggle(self, msg_index, blk_idx, total, client_id="Host", **kwargs):
        fingerprint = None
        try:
            target_msgs = [m for m in self.last_messages_snapshot if m.get('index') == msg_index]
            if target_msgs:
                msg_obj = target_msgs[0]
                full_text = self.engine.get_msg_text(msg_obj)
                fingerprint = full_text[:30].replace("\n", "").strip()
        except Exception as e:
            logger.warning(f"获取指纹失败: {e}")
        self.scheduler.add_task(
            client_id,
            "task_manual_toggle",
            msg_index,
            blk_idx,
            total,
            fingerprint=fingerprint,
            **kwargs
        )

    def do_server_scan(self, **kwargs):
        if not self.rpc_lock.tryLock():
            return
        try:
            changes = self.update_service.scan()
            self.update_list_signal.emit(changes)
        finally:
            self.rpc_lock.unlock()

    def do_server_apply(self, paths, **kwargs):
        if not self.rpc_lock.tryLock():
            return
        try:
            self.update_service.process_updates(
                paths,
                self.safe_emit_status,
                self.ota_sync_signal.emit
            )
        finally:
            self.rpc_lock.unlock()

    def get_git_workbench_state(self, limit=30, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.get_workbench_state(limit=limit, client_id=client_id, user_role=user_role)
    def get_git_file_diff(self, path, kind=None, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.get_file_diff(path, kind=kind, client_id=client_id, user_role=user_role)
    def get_git_config_snapshot(self, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.get_config_snapshot(client_id=client_id, user_role=user_role)
    def _emit_git_status(self, detail_text, status_text=None):
        return self.git_bridge.emit_status(detail_text, status_text=status_text)
    def _emit_git_log_lines(self, log):
        return self.git_bridge.emit_log_lines(log)
    def _execute_git_action(self, git_func, start_msg, start_detail, success_msg, fail_msg, post_actions=None, client_id="Host", user_role=None):
        return self.git_bridge.execute_action(
            git_func=git_func,
            start_msg=start_msg,
            start_detail=start_detail,
            success_msg=success_msg,
            fail_msg=fail_msg,
            post_actions=post_actions,
        )
    def do_server_git_init(self, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.init_repo(client_id=client_id, user_role=user_role)
    def do_server_git_set_user(self, name, email, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.set_user(name, email, client_id=client_id, user_role=user_role)
    def do_server_git_set_remote(self, name, url, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.set_remote(name, url, client_id=client_id, user_role=user_role)
    def do_server_set_upstream(self, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.set_upstream(client_id=client_id, user_role=user_role)
    def run_git_connectivity_checks(self, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.run_connectivity_checks(client_id=client_id, user_role=user_role)
    def do_server_push_only(self, client_id="Host", user_role=None, **kwargs):
        return self.git_bridge.push_only()
    def do_server_backup(self, msg, **kwargs):
        return self.git_bridge.backup(msg)
    def _run_knowledge_reindex_after_git_push(self, changed_files=None):
        return self.git_bridge.run_knowledge_reindex_after_git_push(changed_files)
    def _on_knowledge_reindex_progress(self, info):
        return self.git_bridge.on_knowledge_reindex_progress(info)
    def request_generate_snapshot(self, *args, **kwargs):
        self.safe_emit_status("⏳ 正在生成项目快照...")
        try:
            result = subprocess.run(
                [sys.executable, "dump_code.py"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if result.returncode == 0:
                if os.path.exists("FULL_PROJECT_CONTEXT.txt"):
                    with open("FULL_PROJECT_CONTEXT.txt", "r", encoding="utf-8") as f:
                        content = f.read()
                    self.snapshot_ready_signal.emit(content)
                    self.safe_emit_status("✅ 快照生成完毕")
                else:
                    self.safe_emit_status("❌ 错误: 未找到快照文件")
            else:
                self.safe_emit_status(f"❌ 生成失败: {result.stderr}")
        except Exception as e:
            self.safe_emit_status(f"❌ 执行异常: {e}")

    def do_server_clear_cache(self, **kwargs):
        staging_dir = self.config.get("export_code_path", "export/code")
        if not os.path.exists(staging_dir):
            self.safe_emit_status("⚠️ 服务端暂存区已为空")
            return

        try:
            count = 0
            for filename in os.listdir(staging_dir):
                file_path = os.path.join(staging_dir, filename)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                    count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    count += 1

            self.safe_emit_status(f"🗑️ 服务端暂存区已清空 ({count} items)")
            self.do_server_scan()
        except Exception as e:
            self.safe_emit_status(f"❌ 服务端清空失败: {e}")

    def update_config(self, cfg, **kwargs):
        self.config = cfg
        self.file_service.config = cfg
        self.update_service.config = cfg
        if hasattr(self, 'daemon_bridge') and self.daemon_bridge:
            try:
                self.daemon_bridge.reload()
            except Exception as e:
                logger.debug("守护进程配置热重载异常: %s", e)


    def reload_api_runtime_config(self, **kwargs):
        """
        API 模式运行时配置热重载薄桥。
        - Worker 只做桥接，不承担 API 配置逻辑中心职责
        - 真正热更新逻辑由 APISource 自己负责
        """
        if not self.api_source:
            return False
        try:
            self.api_source.reload_runtime_config()
            self.safe_emit_status("✅ API 运行时配置已热应用（下一次请求生效）")
            return True
        except Exception as e:
            self.safe_emit_status(f"⚠️ API 配置热应用失败: {e}")
            return False

    def manual_save(self, f, c, **kwargs):
        self.file_service.save_code(f, c)

    def navigate(self, u, **kwargs):
        self.connector.navigate(u)

    def trigger_paste(self, s="textarea", auto_send=False, **kwargs):
        self.connector.paste_to_input(s, auto_send=auto_send)

    def touch_file(self, path, **kwargs):
        if os.path.exists(path):
            os.utime(path, None)

    def set_manual_turn(self, num, **kwargs):
        self.state_service.set_manual_bubble_count(self.current_chat_id, num)
        self._check_and_emit_sync(True)

    def set_manual_snapshot(self, num, **kwargs):
        self.state_service.set_snapshot(self.current_chat_id, num)
        self._check_and_emit_sync(True)

    def trigger_resync(self):
        if self.last_messages_snapshot:
            self._do_push_extracted_messages(
                self.last_messages_snapshot,
                reason='resync',
                force_full=True,
            )
        self._check_and_emit_sync(True)


    def _check_and_emit_sync(self, force=False):
        needs, snap = self.state_service.should_emit_sync(
            self.current_chat_id,
            self.current_bubble_count,
            force
        )
        if needs:
            self.state_sync_signal.emit(self.current_bubble_count, snap)
            self.context_health_signal.emit(
                self.current_bubble_count,
                self.current_bubble_count - snap
            )

    def _update_ai_state(self, state):
        extra = {}
        if self.mode == "browser":
            extra["browser_round"] = self._round_sm.state_value
            extra["state"] = self._round_sm.ui_state
        self.ai_state_signal.emit(extra)
    def _on_round_state_change(self, old_state: BrowserRoundState, new_state: BrowserRoundState, event: RoundStateEvent):
        """状态机变更回调：自动同步 UI 侧状态信号 + 状态机驱动缓存失效。"""
        self._update_ai_state(self._round_sm.ui_state)

        # 状态机驱动缓存失效：PIPELINE_END 时失效最后一条 AI 消息缓存
        # 原因：AI 流式输出期间缓存的是 transient 版本，
        #        PIPELINE_END 后需要强制重新提取稳定版本
        if event == RoundStateEvent.PIPELINE_END:
            try:
                last_ai_msg_id = self.connector.get_last_ai_message_id() if self.connector else ''
                if last_ai_msg_id and hasattr(self.connector, '_incremental'):
                    self.connector._incremental.cache.invalidate_message(last_ai_msg_id)
                    logger.debug(
                        "[状态机缓存失效] PIPELINE_END | message_id=%s", last_ai_msg_id
                    )
            except Exception as e:
                logger.debug("[状态机缓存失效] 失败（非致命）: %s", e)

        # 守护进程触发：仅浏览器回复流水线 fixing → idle 后生成建议。
        # 会话切换、异常恢复、工具失败兜底等回到 idle 的路径不应误触发建议。
        if (
            old_state == BrowserRoundState.FIXING
            and new_state == BrowserRoundState.IDLE
            and event == RoundStateEvent.PIPELINE_END
        ):
            try:
                self._notify_daemon_reply_completed("browser", self.current_chat_id)
            except Exception as e:
                logger.debug("[守护进程] 浏览器模式通知失败（非致命）: %s", e)

    @property
    def _browser_round_state(self) -> str:
        """兼容属性：旧代码中读取 _browser_round_state 的地方继续工作。"""
        return self._round_sm.state_value

    @property
    def browser_round_state(self) -> str:
        """公开属性：UI 层通过此属性获取状态机当前状态，无需 __dict__ 穿透。"""
        return self._round_sm.state_value

    def _normalize_runtime_task(self, task: dict | None):
        task = dict(task or {})
        task_id = str(task.get('task_id') or task.get('id') or '').strip()
        if not task_id:
            return None
        task['id'] = task_id
        task['task_id'] = task_id
        if not task.get('status'):
            task['status'] = 'running'
        started_at = task.get('started_at', 0) or 0
        elapsed_ms = task.get('elapsed_ms', 0) or 0
        if started_at and not elapsed_ms:
            elapsed_ms = max(0, int((time.time() - float(started_at)) * 1000))
            task['elapsed_ms'] = elapsed_ms
        if elapsed_ms and not task.get('age'):
            task['age'] = elapsed_ms / 1000.0
        return task

    def _upsert_runtime_task(self, task: dict | None):
        payload = self._normalize_runtime_task(task)
        if not payload:
            return None
        task_id = payload['task_id']
        self._runtime_tool_tasks[task_id] = payload
        self._runtime_task_order = [x for x in self._runtime_task_order if x != task_id]
        self._runtime_task_order.append(task_id)
        return payload

    def _remove_runtime_task(self, task_id: str | None):
        key = str(task_id or '').strip()
        if not key:
            return
        self._runtime_tool_tasks.pop(key, None)
        self._runtime_task_order = [x for x in self._runtime_task_order if x != key]

    def _build_queue_monitor_snapshot(self):
        active_task = None
        queue_list = []
        if hasattr(self.scheduler, 'get_queue_snapshot'):
            active_task, queue_list = self.scheduler.get_queue_snapshot()
        queue_list = list(queue_list or [])
        runtime_tasks = []
        for task_id in list(self._runtime_task_order):
            payload = self._normalize_runtime_task(self._runtime_tool_tasks.get(task_id))
            if not payload:
                continue
            self._runtime_tool_tasks[task_id] = payload
            runtime_tasks.append(payload)
        if runtime_tasks:
            # Runtime tool task 优先于 scheduler 的 system send 任务占据 active 位
            scheduler_action = str(active_task.get('action', '') if active_task else '')
            if active_task and scheduler_action in ('real_send_text', 'compound_send_task'):
                # scheduler 的发送任务让位给 runtime tool task
                queue_list = [active_task] + queue_list
                active_task = runtime_tasks[0]
                queue_list = runtime_tasks[1:] + queue_list
            elif active_task:
                queue_list = runtime_tasks + queue_list
            else:
                active_task = runtime_tasks[0]
                queue_list = runtime_tasks[1:] + queue_list
        return {
            'active': active_task,
            'queue': queue_list,
            'timestamp': time.time(),
        }

    def _emit_queue_monitor_snapshot(self, reason='runtime_event'):
        snapshot = self._build_queue_monitor_snapshot()
        active = snapshot.get('active') or {}
        _has_active = bool(active)
        _log = logger.info if _has_active else logger.debug
        _log(
            "[QueueMonitor] emit snapshot | reason=%s has_active=%s task_id=%s tool_name=%s queue=%s",
            reason,
            _has_active,
            active.get('task_id', ''),
            active.get('tool_name', ''),
            len(snapshot.get('queue', []) or []),
        )
        self.queue_monitor_signal.emit(snapshot)
        return snapshot

    def _emit_tool_event(self, event_type, tool_call_id, tool_name, status,
                         success=None, elapsed_ms=0, index=0):
        """工具状态/结果事件推送，走 canonical 同步层。"""
        from app.core.browser_sync.events import EventType
        seq = self._seq_gen.next()
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

        self._canonical_store.log_event(
            type("E", (), {
                "seq": seq,
                "conversation_id": self.current_chat_id,
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
            })()
        )
        self.ai_state_signal.emit({
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
        logger.info("[工具事件] %s | tool_call_id=%s | tool_name=%s | status=%s | seq=%s",
                    event_type, tool_call_id[:20], tool_name, status, seq)

    def _handle_runtime_tool_start(self, intent, index):
        task_id = str(getattr(intent, 'tool_call_id', '') or '').strip()
        tool_name = getattr(intent, 'name', '') or getattr(intent, 'kind', 'tool_call')
        task = {
            'id': task_id,
            'task_id': task_id,
            'action': tool_name,
            'status': 'running',
            'label': tool_name or getattr(intent, 'kind', '工具任务'),
            'category': 'Tool',
            'icon': '🛠️' if getattr(intent, 'kind', '') == 'skill_call' else '🖥️',
            'cancellable': False,
            'client_id': getattr(intent, 'conversation_id', '') or 'tool_runtime',
            'tool_call_id': task_id,
            'tool_name': tool_name,
            'conversation_id': getattr(intent, 'conversation_id', ''),
            'started_at': time.time(),
            'elapsed_ms': 0,
            'age': 0,
            'runtime_source': 'tool_runtime',
            'index': index,
            'block_key': getattr(intent, 'block_key', ''),
        }
        logger.info(
            "[工具执行] 开始执行工具 | tool_name=%s | tool_call_id=%s | conversation_id=%s | index=%s",
            tool_name,
            task_id,
            getattr(intent, 'conversation_id', ''),
            index,
        )
        self._upsert_runtime_task(task)
        self._emit_queue_monitor_snapshot(reason='tool_start')
        self._emit_tool_event("tool.status", task_id, tool_name, "running", index=index)

    def _handle_runtime_tool_end(self, intent, result, index):
        task_id = str(getattr(intent, 'tool_call_id', '') or '').strip()
        tool_name = getattr(intent, 'name', '') or getattr(intent, 'kind', 'tool_call')
        elapsed_ms = 0
        current_task = self._runtime_tool_tasks.get(task_id) or {}
        started_at = current_task.get('started_at', 0) or 0
        if started_at:
            elapsed_ms = max(0, int((time.time() - float(started_at)) * 1000))
        logger.info(
            "[工具执行] 工具执行结束 | tool_name=%s | tool_call_id=%s | success=%s | elapsed_ms=%s | conversation_id=%s | index=%s",
            tool_name,
            task_id,
            bool(getattr(result, 'success', False)),
            elapsed_ms,
            getattr(intent, 'conversation_id', ''),
            index,
        )
        self._remove_runtime_task(task_id)
        self._emit_queue_monitor_snapshot(reason='tool_end')
        success = bool(getattr(result, 'success', False))
        status = "completed" if success else "failed"
        self._emit_tool_event("tool.result", task_id, tool_name, status,
                              success=success, elapsed_ms=elapsed_ms, index=index)

    def _handle_knowledge_task_state_change(self, event):
        event = dict(event or {})
        state = str(event.get('state') or '').strip() or 'unknown'
        snap = event.get('snapshot') or {}
        payload = self.knowledge_task_bridge.build_runtime_task_payload(snap)
        task_id = ''
        if payload:
            task_id = payload.get('task_id', '')
        if not task_id:
            task_id = str((snap or {}).get('task_id', '') or '').strip()
        tool_name = str((snap or {}).get('tool_name', '') or 'knowledge_search')
        if state == 'running' and payload:
            logger.info(
                "[知识任务] 开始执行知识检索 | task_id=%s | tool_call_id=%s | tool_name=%s | conversation_id=%s | query_preview=%s",
                task_id,
                payload.get('tool_call_id', ''),
                tool_name,
                payload.get('conversation_id', ''),
                payload.get('query_preview', ''),
            )
            self._upsert_runtime_task(payload)
        elif state in ('finished', 'idle', 'error', 'cancelled'):
            elapsed_ms = (snap or {}).get('elapsed_ms', 0) or 0
            logger.info(
                "[知识任务] 知识检索状态变更 | state=%s | task_id=%s | tool_call_id=%s | tool_name=%s | elapsed_ms=%s | conversation_id=%s",
                state,
                task_id,
                (payload or {}).get('tool_call_id', '') if payload else (snap or {}).get('tool_call_id', ''),
                tool_name,
                elapsed_ms,
                (payload or {}).get('conversation_id', '') if payload else (snap or {}).get('conversation_id', ''),
            )
            self._remove_runtime_task(task_id)
        self._emit_queue_monitor_snapshot(reason=f'knowledge_{state}')


    def _wrap_tool_runtime_start(self, previous_callback):
        def _wrapped(intent, index):
            try:
                self._handle_runtime_tool_start(intent, index)
            finally:
                if callable(previous_callback):
                    previous_callback(intent, index)
        return _wrapped

    def _wrap_tool_runtime_end(self, previous_callback):
        def _wrapped(intent, result, index):
            try:
                self._handle_runtime_tool_end(intent, result, index)
            finally:
                if callable(previous_callback):
                    previous_callback(intent, result, index)
        return _wrapped

    def _install_tool_runtime_callbacks(self):
        runtime_executor = getattr(self.tool_router, 'runtime_executor', None)
        if not runtime_executor:
            return None
        previous_on_start = getattr(runtime_executor, 'on_intent_start', None)
        previous_on_end = getattr(runtime_executor, 'on_intent_end', None)
        runtime_executor.on_intent_start = self._wrap_tool_runtime_start(previous_on_start)
        runtime_executor.on_intent_end = self._wrap_tool_runtime_end(previous_on_end)
        token = (runtime_executor, previous_on_start, previous_on_end)
        self._tool_runtime_callback_stack.append(token)
        return token

    def _restore_tool_runtime_callbacks(self, token=None):
        runtime_executor = getattr(self.tool_router, 'runtime_executor', None)
        if token is None:
            if not self._tool_runtime_callback_stack:
                return
            token = self._tool_runtime_callback_stack.pop()
        else:
            try:
                self._tool_runtime_callback_stack.remove(token)
            except ValueError:
                pass
        executor_obj, previous_on_start, previous_on_end = token
        if runtime_executor is executor_obj:
            runtime_executor.on_intent_start = previous_on_start
            runtime_executor.on_intent_end = previous_on_end

    def _get_api_profile_display_name(self, profile_key: str) -> str:
        try:
            from app.core.api_mode_config import APIModeConfigManager
            cfg = APIModeConfigManager.load()
            profile = cfg.get("profiles", {}).get(profile_key, {})
            return str(profile.get("name") or profile_key)
        except Exception:
            return str(profile_key)

    def safe_emit_status(self, text):
        try:
            self.status_signal.emit(text)
        except Exception as e:
            logger.warning(f"状态信号发送失败: {e}")

    def process_batch(self, msgs):
        if not self.config.get("auto_export", True):
            return []
        changed = []
        ignore = [
            x.strip()
            for x in self.config.get("ignored_files", "").split('\n')
            if x.strip()
        ]

        for msg in msgs:
            for seg in msg.get('segments', []):
                if seg['type'] == 'code':
                    try:
                        name = None
                        for line in seg['content'].split('\n')[:5]:
                            line = line.strip()
                            m = re.search(r"^#\s*filename\s*:\s*(.+)$", line, re.IGNORECASE)
                            if not m:
                                m = re.search(r"^//\s*filename\s*:\s*(.+)$", line, re.IGNORECASE)
                            if not m:
                                m = re.search(
                                    r"^<!--\s*filename\s*:\s*(.+?)\s*-->$",
                                    line,
                                    re.IGNORECASE
                                )
                            if m:
                                name = m.group(1).strip()
                                break

                        if name:
                            clean_name = name.replace('\\', '/')
                            if clean_name in self.path_redirects:
                                clean_name = self.path_redirects[clean_name]

                            if clean_name.endswith("worker.py") and "app/core" not in clean_name:
                                clean_name = "app/core/worker.py"

                            if any(i in clean_name for i in ignore):
                                continue

                            saved, _ = self.file_service.save_code(clean_name, seg['content'])
                            if saved:
                                changed.append(clean_name)

                    except Exception as code_err:
                        self.safe_emit_status(f"⚠️ 代码保存失败: {name}")

        return changed

    def _extract_browser_tool_input(self):
        """优先从最后一条结构化 AI 消息提取工具识别输入；全文文本仅作兜底。"""
        try:
            raw_msgs, _ = self.connector.get_chat_content(self.target_class, auto_wake=False)
            raw_msgs = self.file_service.process_images(raw_msgs)
        except Exception as e:
            logger.warning(f"浏览器模式结构化消息获取失败: {e}")
            raw_msgs = []

        if raw_msgs:
            try:
                self.last_messages_snapshot = raw_msgs
            except Exception:
                pass

            last_ai_msg = None
            for msg in reversed(raw_msgs):
                if str(msg.get('role', '')).lower() == 'ai':
                    last_ai_msg = msg
                    break

            if last_ai_msg:
                segments = list(last_ai_msg.get('segments') or [])
                structured_summary = []
                for seg in segments:
                    seg_type = seg.get('type')
                    if seg_type == 'code':
                        structured_summary.append({
                            'type': 'code',
                            'content': seg.get('content', ''),
                            'language': seg.get('language'),
                            'message_id': seg.get('message_id'),
                            'block_index': seg.get('block_index'),
                            'code_fingerprint': seg.get('code_fingerprint'),
                            'block_key': seg.get('block_key'),
                        })
                    elif seg_type in ('text', 'tool_call', 'tool_result', 'thinking'):
                        structured_summary.append({
                            'type': seg_type,
                            'content': seg.get('content', ''),
                        })

                logger.info(
                    "[工具路由] 浏览器模式命中结构化 AI 消息 | segments=%s | codes=%s | message_id=%s",
                    len(segments),
                    sum(1 for seg in segments if seg.get('type') == 'code'),
                    last_ai_msg.get('id', ''),
                )
                return {
                    'messages': [{
                        'role': 'AI',
                        'id': last_ai_msg.get('id', ''),
                        'segments': segments,
                    }],
                    'fingerprint_source': json.dumps(structured_summary, ensure_ascii=False, sort_keys=True),
                    'fallback_text': self.connector.check_last_ai_message_for_tool() or '',
                    'used_structured': True,
                    'last_ai_msg_id': last_ai_msg.get('id', ''),
                }

        fallback_text = self.connector.check_last_ai_message_for_tool() or ''
        if fallback_text:
            logger.warning("[工具路由] 浏览器模式未获取到结构化 AI 消息，回退到全文文本识别")
        return {
            'messages': [{
                'role': 'AI',
                'index': 9999,
                'segments': [{'type': 'text', 'content': fallback_text}],
            }] if fallback_text else [],
            'fingerprint_source': fallback_text,
            'fallback_text': fallback_text,
            'used_structured': False,
            'last_ai_msg_id': '',
        }

    def _looks_like_browser_tool_feedback_text(self, text: str) -> bool:
        text = str(text or '').strip()
        if not text:
            return False
        normalized = text.lstrip()
        return normalized.startswith('🔧 [工具执行结果]') or normalized.startswith('[工具执行结果]') or normalized.startswith('工具执行结果')

    def _classify_browser_tool_input(self, candidate_messages, fallback_text: str = '', used_structured: bool = False) -> str:
        fallback_text = str(fallback_text or '')
        messages = list(candidate_messages or [])
        if not messages:
            return 'none'

        last_msg = messages[-1] if messages else {}
        segments = list(last_msg.get('segments') or []) if isinstance(last_msg, dict) else []

        if used_structured and segments:
            has_tool_result = any(str(seg.get('type', '') or '').strip().lower() == 'tool_result' for seg in segments if isinstance(seg, dict))
            if has_tool_result:
                logger.info("[工具分类] 结果=工具回显 | 段数=%s | 含 tool_result 段", len(segments))
                return 'tool_feedback'

            # [诊断] 记录每段 type/language/是否最后段/代码block_key
            seg_details = []
            for i, seg in enumerate(segments):
                if not isinstance(seg, dict):
                    continue
                _t = str(seg.get('type', '') or '').strip().lower()
                _l = str(seg.get('language', '') or '').strip().lower()
                _is_last = (i == len(segments) - 1)
                _bk = str(seg.get('block_key', '') or '').strip()[:20] if _t == 'code' else ''
                _c_len = len(str(seg.get('content', '') or ''))
                seg_details.append(f'{_t}:{_l}:len={_c_len}:last={_is_last}{":bk="+_bk if _bk else ""}')

            text_chunks = []
            has_tool_call = False
            has_tool_call_code = False
            has_code = False

            for seg in segments:
                if not isinstance(seg, dict):
                    continue

                seg_type = str(seg.get('type', '') or '').strip().lower()

                if seg_type == 'tool_call':
                    has_tool_call = True

                elif seg_type == 'code':
                    has_code = True
                    language = str(seg.get('language', '') or '').strip().lower()
                    if language == 'tool_call':
                        has_tool_call_code = True

                elif seg_type == 'text':
                    text_chunks.append(str(seg.get('content', '') or ''))

            merged_text = '\n'.join([chunk for chunk in text_chunks if chunk.strip()])
            if self._looks_like_browser_tool_feedback_text(merged_text):
                logger.info("[工具分类] 结果=工具回显 | 段数=%s | 文本匹配反馈模式", len(segments))
                return 'tool_feedback'

            if has_tool_call or has_tool_call_code:
                logger.info(
                    "[工具分类] 结果=工具调用 | 段数=%s | 含显式 tool_call 段=%s | 含 tool_call 代码块=%s | 段详情=%s",
                    len(segments),
                    has_tool_call,
                    has_tool_call_code,
                    seg_details,
                )
                return 'tool_call'

            if has_code:
                logger.info(
                    "[工具分类] 结果=无工具 | 段数=%s | 仅普通代码块，不进入工具路由 | 段详情=%s",
                    len(segments),
                    seg_details,
                )
                return 'none'

            logger.info(
                "[工具分类] 结果=无工具 | 段数=%s | 无工具调用/代码块/回显 | 段详情=%s",
                len(segments),
                seg_details,
            )
            return 'none'

        if self._looks_like_browser_tool_feedback_text(fallback_text):
            return 'tool_feedback'
        if fallback_text.strip():
            return 'tool_call'
        return 'none'

    def _batch_fix_all(self, limit=None):
        count = 0
        msgs = self.last_messages_snapshot
        fix_count = limit if limit is not None else self.config.get("fix_limit", 5)
        target_msgs = msgs[-fix_count:] if len(msgs) > fix_count else msgs
        for m in target_msgs:
            msg_index = 0
            total_code = 0
            for seg in m.get('segments', []):
                if seg['type'] == 'code':
                    total_code += 1
            if total_code > 0:
                for blk_idx in range(total_code):
                    self.trigger_manual_toggle(msg_index, blk_idx, total_code)
                    count += 1
        if count > 0:
            self.scheduler.add_task("Host", "task_batch_end")
            self.safe_emit_status(f"🛠️ 已加入 {count} 个任务，开始执行...")
        else:
            if limit is None:
                self.safe_emit_status("⚠️ 范围内无代码块")

    def _initial_expand_bg(self):
        time.sleep(2.0)
        if self.connector.interact:
            self.connector.interact.fast_expand_all()

    def _browser_try_trigger_tool_execution(self, reason='message_update'):
        """浏览器模式事件驱动工具触发：消息一旦稳定命中结构化工具块，尽快执行。"""
        if self.mode != 'browser':
            return False
        if not self.connector.interact:
            return False
        if self.connector.is_busy():
            return False
        if self._round_sm.is_tool_phase():
            return False

        tool_input = self._extract_browser_tool_input()
        candidate_messages = list(tool_input.get('messages') or [])
        fallback_text = str(tool_input.get('fallback_text', '') or '')
        used_structured = bool(tool_input.get('used_structured'))
        ai_msg_id = str(tool_input.get('last_ai_msg_id', '') or '').strip()

        tool_input_kind = self._classify_browser_tool_input(
            candidate_messages,
            fallback_text=fallback_text,
            used_structured=used_structured,
        )

        if tool_input_kind != 'tool_call':
            return False
        if ai_msg_id and ai_msg_id == self._last_tool_trigger_ai_msg_id:
            return False

        self._last_tool_trigger_ai_msg_id = ai_msg_id or None
        logger.info(
            "[工具路由] 事件驱动触发工具执行 | reason=%s | ai_msg_id=%s | mode=%s",
            reason,
            ai_msg_id,
            'structured' if used_structured else 'fallback',
        )
        self._check_and_handle_tool()
        return True


    def get_skills_list(self, client_id="Host", **kwargs):
        """获取 Skills 列表（RPC 方法）"""
        try:
            skills_list = self.agent.skills_manager.list_all_skills()
            
            # 通过信号返回数据
            if hasattr(self, 'skills_data_signal'):
                self.skills_data_signal.emit({
                    'target_client_id': client_id,
                    'skills': skills_list
                })
            
            self.safe_emit_status(f"📋 已获取 {len(skills_list)} 个 Skills")
        except Exception as e:
            self.safe_emit_status(f"❌ 获取 Skills 列表失败: {e}")
    
    def toggle_skill(self, skill_name, enabled, client_id="Host", **kwargs):
        """启用/禁用 Skill（RPC 方法）"""
        try:
            if not self.tool_router or not self.tool_router.skills_manager:
                self.safe_emit_status(f"❌ SkillsManager 未初始化，无法切换 Skill")
                return False

            success = self.tool_router.skills_manager.toggle_skill(skill_name, enabled)
            if success:
                status = "启用" if enabled else "禁用"
                self.safe_emit_status(f"✅ 已{status} Skill: {skill_name}")
            else:
                self.safe_emit_status(f"❌ Skill '{skill_name}' 不存在")

            self.get_skills_list(client_id=client_id)
            return success
        except Exception as e:
            self.safe_emit_status(f"❌ 切换 Skill 状态失败: {e}")
            return False

    def reload_skill(self, skill_name, client_id="Host", **kwargs):
        """重载单个 Skill（RPC 方法）"""
        try:
            success, message = self.agent.reload_skill(skill_name)
            if success:
                self.safe_emit_status(f"🔄 {message}")
            else:
                self.safe_emit_status(f"❌ {message}")
            self.get_skills_list(client_id=client_id)
        except Exception as e:
            self.safe_emit_status(f"❌ 重载 Skill 失败: {e}")
    
    def get_system_prompt(self, client_id="Host", **kwargs):
        """获取系统提示词（RPC 方法）"""
        try:
            prompt = self.agent.skills_manager.generate_system_prompt()
            
            # 通过信号返回数据
            if hasattr(self, 'system_prompt_signal'):
                self.system_prompt_signal.emit({
                    'target_client_id': client_id,
                    'prompt': prompt
                })
            
            self.safe_emit_status(f"📝 已生成系统提示词 (~{len(prompt) // 4} tokens)")
        except Exception as e:
            self.safe_emit_status(f"❌ 生成系统提示词失败: {e}")

    def run(self):
        """主循环入口：根据 mode 分发"""
        if self.mode == "api":
            self._run_api_loop()
        else:
            self._run_browser_loop()

    def _run_browser_loop(self):
        """浏览器模式主循环"""
        self._check_and_emit_sync(True)
        if not self._connect_browser():
            return

        while self.running:
            try:
                if self.mode != "browser":
                    self.safe_emit_status("🔄 退出Browser循环，切换到API模式")
                    self._run_api_loop()
                    return

                self._browser_scan_queues()

                current_busy, next_state = self._browser_detect_state()

                self.was_busy = current_busy
                self._update_ai_state(next_state)

                self._browser_process_messages()

                self._process_toggle_queue()

                if time.time() - self.last_occupancy_scan > 2:
                    occ = self.scheduler.get_occupancy_map()
                    self.occupancy_signal.emit(occ)
                    self.last_occupancy_scan = time.time()

            except Exception as e:
                logger.error("Worker主循环异常: %s", e)
                traceback.print_exc()
                self.safe_emit_status(f"❌ 主循环错误: {e}")
                time.sleep(2.0)

            time.sleep(0.3)

    def _connect_browser(self):
        connected = False
        for i in range(5):
            if not self.running:
                return False
            self.safe_emit_status(f"正在连接浏览器 ({i+1})...")
            ok, msg = self.connector.connect()
            if ok:
                self.safe_emit_status(f"✅ 浏览器连接成功: {msg}")
                connected = True
                if self.connector.interact:
                    time.sleep(1.0)
                    self.executor.submit(self._initial_expand_bg)
                # 启动时标记当前已有消息为"已处理"，防止旧消息被当成新工具调用
                try:
                    startup_msg_id = self.connector.get_last_ai_message_id()
                    if startup_msg_id:
                        self._last_processed_ai_msg_id = startup_msg_id
                        logger.info("[启动] 记录初始 AI 消息 ID | ai_msg_id=%s", startup_msg_id)
                except Exception:
                    pass
                break
            time.sleep(2)
        if not connected:
            self.safe_emit_status("❌ 无法连接到浏览器，请检查端口")
        return connected

    def _browser_scan_queues(self):
        if time.time() - self.last_queue_scan > 1.5:
            snapshot = None
            if hasattr(self, 'knowledge_task_bridge') and self.knowledge_task_bridge:
                snapshot = self.knowledge_task_bridge.get_panel_snapshot(self.scheduler)
            elif hasattr(self.scheduler, 'get_queue_snapshot'):
                active_task, queue_list = self.scheduler.get_queue_snapshot()
                snapshot = {
                    "active": active_task,
                    "queue": queue_list,
                    "timestamp": time.time()
                }
            if snapshot:
                active = snapshot.get('active') or {}
                _has_active = bool(active)
                _log_level = logger.info if _has_active else logger.debug
                _log_level("[QueueMonitor] emit snapshot | has_active=%s task_id=%s tool_name=%s queue=%d",
                           _has_active, active.get('task_id', ''), active.get('tool_name', ''), len(snapshot.get('queue', []) or []))
                self.queue_monitor_signal.emit(snapshot)
            else:
                logger.debug("[QueueMonitor] snapshot empty")
            self.last_queue_scan = time.time()

        if time.time() - self.last_session_scan > 2:
            if self.connector.interact:
                self.connector.interact.switch_to_chat_tab()
            s_list = self.connector.get_session_list()
            if s_list:
                self.sessions_signal.emit(s_list)
            self.last_session_scan = time.time()

    def _browser_detect_state(self):
        current_busy = self.connector.is_busy()
        is_fixing_queue = len(self.toggle_queue) > 0
        next_state = "idle"

        if current_busy:
            next_state = "busy"
            self._round_sm.handle_event(RoundStateEvent.BUSY_DETECTED)
            self.last_send_time = 0
        elif self.was_busy and not current_busy:
            next_state = "fixing"
            self._round_sm.handle_event(RoundStateEvent.BUSY_TO_IDLE)
            self.safe_emit_status("✅ 生成结束，处理输出...")
            self.executor.submit(self._background_process_ai_response)
            self.last_send_time = 0

        elif is_fixing_queue:
            next_state = "fixing"
        else:
            if self.last_send_time > 0 and time.time() - self.last_send_time > 10:
                current_fp = self._get_last_ai_fingerprint(live=True)
                pre_send_fp = getattr(self, '_pre_send_ai_fingerprint', None)
                self.last_send_time = 0

                if current_fp != pre_send_fp and current_fp:
                    self.safe_emit_status("⏰ 延迟检测到新回复，执行流水线...")
                    self._pre_send_ai_fingerprint = None
                    self.executor.submit(self._background_process_ai_response_direct)
                else:
                    self.safe_emit_status("⚠️ 10s 后仍无新回复，等待手动修复")

            task = self.scheduler.get_next_task()
            if task:
                if task.action == "switch_session_task":
                    next_state = "switching"
                elif "task_agent_loop" in task.action:
                    next_state = "fixing"
                else:
                    next_state = "busy"
                # 异步执行任务，不阻塞轮询循环
                self._update_ai_state(next_state)
                if task.action in ["real_send_text", "compound_send_task"]:
                    # 发送类任务：标记 busy 后异步执行，轮询下一轮自然检测 busy
                    current_busy = True
                    self.was_busy = current_busy
                    self.executor.submit(self._execute_task, task)
                else:
                    # 非发送类任务：异步执行，短暂让出 CPU
                    self.executor.submit(self._execute_task, task)
                    self.was_busy = current_busy
                time.sleep(0.1)
                return current_busy, next_state

        return current_busy, next_state

    def _browser_process_messages(self):
        detected_title_id = self.connector.get_chat_title_id()
        if detected_title_id != self.current_chat_id:
            self.safe_emit_status(f"🔄 识别会话变更: {detected_title_id[:6]}")
            self.current_chat_id = detected_title_id
            self._check_and_emit_sync(True)

        # 状态机驱动推送决策
        transient_mode = bool(self.was_busy or len(self.toggle_queue) > 0)

        if self._round_sm.is_idle():
            # IDLE：用增量提取器做轻量探测，只看结构变化
            self._idle_probe_and_maybe_push(transient_mode)
            self.state_service.save_states()
            self._check_and_emit_sync()
            return

        # 非 IDLE 状态（状态机说有事发生，总是推送）
        self._do_extract_and_push(
            reason=f'state={self._round_sm.state_value}',
            transient_last_ai=transient_mode,
        )
        self.state_service.save_states()
        self._check_and_emit_sync()

    def _process_toggle_queue(self):
        while self.toggle_queue:
            task = self.toggle_queue.pop(0)
            if task == "BATCH_END":
                self.safe_emit_status("✅ 修复完成")
                self.batch_complete_signal.emit()
                logger.info("[修复队列] 批量修复完成，队列已清空")
                continue
            msg_idx, blk_idx, total, fingerprint = task
            self.connector.manual_toggle_block(
                0, blk_idx, total, fingerprint
            )

    def _idle_probe_and_maybe_push(self, transient_last_ai=False):
        """IDLE 状态下轻量探测：只看结构变化，无变化则静默跳过。"""
        try:
            raw_msgs, is_at_bottom, has_structural_change = \
                self.connector.get_chat_content_incremental(
                    transient_last_ai=transient_last_ai
                )
        except Exception as e:
            logger.warning("[IDLE探测] 增量提取异常: %s", e)
            return

        if not has_structural_change:
            return  # 结构无变化 → 静默跳过，零推送

        # 结构有变化（如平台插入了系统消息）→ 推送
        self._do_push_extracted_messages(raw_msgs, reason='idle_structural_change')

    def _do_extract_and_push(self, reason='state_driven', transient_last_ai=False):
        """非 IDLE 状态下的提取+推送，使用增量提取器。"""
        try:
            raw_msgs, is_at_bottom, _ = self.connector.get_chat_content_incremental(
                transient_last_ai=transient_last_ai
            )
        except Exception as e:
            logger.warning("[提取推送] 增量提取异常，降级全量: %s", e)
            try:
                raw_msgs, _ = self.connector.get_chat_content(
                    self.target_class,
                    transient_last_ai=transient_last_ai,
                )
            except Exception as e2:
                logger.warning("[提取推送] 全量提取也失败: %s", e2)
                return

        self._do_push_extracted_messages(raw_msgs, reason=reason)

    def _do_push_extracted_messages(self, raw_msgs, reason='unknown', force_full=False):
        """公共推送逻辑：预扫描tool_call_id → process_images → deduce_state → tag_messages → normalizer → store → emit。

        force_full=True 时全量推送（重启/切换对话/切换模式）。
        默认增量推送：只发变化的消息。
        """
        raw_msgs = self.file_service.process_images(raw_msgs)
        self.last_messages_snapshot = raw_msgs

        self._prescan_tool_call_ids(raw_msgs)

        session_data = self.state_service.get_session(self.current_chat_id)
        session_data, self.current_bubble_count, log = self.engine.deduce_state(
            raw_msgs, session_data
        )
        if log:
            self.safe_emit_status(log)
        raw_msgs = self.engine.tag_messages(
            raw_msgs,
            self.current_bubble_count,
            session_data.snapshot_bubble
        )

        # === canonical 同步层 ===
        canonical_msgs, changed_ids, removed_ids = self._normalizer.normalize_messages(
            raw_msgs,
            conversation_id=self.current_chat_id,
            round_id="",
            force_full=force_full,
        )
        seq = self._seq_gen.next()

        store_empty = (self._canonical_store.message_count == 0)
        if force_full or store_empty or not changed_ids:
            event_type = "conversation.snapshot"
            self._canonical_store.apply_snapshot(canonical_msgs, seq, self.current_chat_id)
            enriched = []
            for cm in canonical_msgs:
                d = cm.to_dict()
                d["_seq"] = seq
                d["_event"] = event_type
                enriched.append(d)
            _ch_summary = []
            for cm in canonical_msgs:
                _ch_summary.append(f"{cm.id[:12]}:rev={cm.rev}:ch={cm.content_hash[:8]}")
            logger.info(
                "[同步推送] 全量推送 | reason=%s | seq=%s | messages=%s | 详情=[%s]",
                reason, seq, len(enriched), " | ".join(_ch_summary),
            )
            self.messages_signal.emit(enriched)
        else:
            event_type = "message.upsert"
            self._canonical_store.apply_incremental(canonical_msgs, changed_ids, seq, self.current_chat_id)
            changed_set = set(changed_ids)
            enriched = []
            for cm in canonical_msgs:
                if cm.id in changed_set:
                    d = cm.to_dict()
                    d["_seq"] = seq
                    d["_event"] = event_type
                    enriched.append(d)
            for rid in removed_ids:
                enriched.append({
                    "id": rid,
                    "_seq": seq,
                    "_event": "message.remove",
                })
            logger.info(
                "[同步推送] 增量推送 | reason=%s | seq=%s | changed=%s | removed=%s | total=%s",
                reason, seq, len(enriched) - len(removed_ids), len(removed_ids), len(canonical_msgs),
            )
            self.messages_signal.emit(enriched)

        try:
            self.process_batch(raw_msgs)
        except Exception as e:
            logger.warning(e)

    def _prescan_tool_call_ids(self, raw_msgs):
        """预扫描 AI 消息的 tool_call segment，提前生成 tool_call_id 并回写到 segment dict。

        时序要求：必须在 normalizer 推送之前完成，这样客户端第一次渲染时
        ToolCallCard 就能通过 tool_call_id 注册到 _tool_cards_by_id，
        后续工具执行结果通过 _emit_tool_event 推送时可直接绑定。
        """
        from app.core.tool_runtime.segment_parser import ToolSegmentParser
        assigned = 0
        for msg in raw_msgs or []:
            if str(msg.get('role', '') or '').lower() != 'ai':
                continue
            segments = msg.get('segments') or []
            intents = ToolSegmentParser.parse_segments(
                segments,
                conversation_id=self.current_chat_id,
                source='prescan',
                write_back_tool_call_id=True,
            )
            assigned += len(intents)
        if assigned > 0:
            logger.info("[预扫描] tool_call_id 已回写 | count=%s | chat_id=%s",
                        assigned, self.current_chat_id[:12])

    #============================================================
    # API???
    # ============================================================

    def switch_mode(self, mode: str, **kwargs):
        return self.api_mode_bridge.switch_mode(mode, **kwargs)

    def _init_api_source(self):
        return self.api_mode_bridge._init_api_source()

    def api_send(self, text: str, **kwargs):
        return self.api_mode_bridge.api_send(text, **kwargs)

    def _run_api_loop(self):
        return self.api_mode_bridge._run_api_loop()

    def _continue_api_round_after_stream(self):
        return self.api_mode_bridge._continue_api_round_after_stream()

    def _handle_api_send_stream(self, text: str):
        return self.api_mode_bridge._handle_api_send_stream(text)

    def _handle_api_send(self, text: str):
        return self.api_mode_bridge._handle_api_send(text)

    def api_switch_conversation(self, conv_id: str, **kwargs):
        return self.api_mode_bridge.api_switch_conversation(conv_id, **kwargs)

    def api_new_conversation(self, title: str = "\u65b0\u5bf9\u8bdd", **kwargs):
        return self.api_mode_bridge.api_new_conversation(title, **kwargs)

    def api_delete_conversation(self, conv_id: str, **kwargs):
        return self.api_mode_bridge.api_delete_conversation(conv_id, **kwargs)

    def api_rename_conversation(self, conv_id: str, title: str, **kwargs):
        return self.api_mode_bridge.api_rename_conversation(conv_id, title, **kwargs)

    def api_pin_conversation(self, conv_id: str, **kwargs):
        return self.api_mode_bridge.api_pin_conversation(conv_id, **kwargs)

    def api_unpin_conversation(self, conv_id: str, **kwargs):
        return self.api_mode_bridge.api_unpin_conversation(conv_id, **kwargs)

    def api_set_conversation_model_usage(self, conv_id: str, usage=None, **kwargs):
        return self.api_conversation_bridge.set_model_usage(conv_id, usage)


    def set_pending_message(self, text, attachments=None, **kwargs):
        """设置待发消息"""
        self.pending_user_message = {"text": text, "attachments": attachments or []}

    def get_and_clear_pending_message(self):
        """获取并清除待发消息"""
        msg = self.pending_user_message
        self.pending_user_message = None
        return msg
