# filename: app/core/worker.py
import os
import time
import hashlib
import re
import json
import threading
import collections
import traceback
import warnings
import inspect
from concurrent.futures import CancelledError, ThreadPoolExecutor
from PySide6.QtCore import QThread, Signal, QMutex

from app.core.driver.factory import create_browser_connector
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
from app.core.services.context_pack_service import ContextPackService
from app.core.app_constants import MAX_WORKERS
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

    agent_runtime_options_signal = Signal(object)
    agent_runtime_approval_signal = Signal(object)
    api_stream_chunk_signal = Signal(object)  # 流式文本块信号
    api_stream_status_signal = Signal(object)  # 流式状态信号
    api_round_state_signal = Signal(object)  # API 单回合状态信号
    knowledge_health_signal = Signal(object)  # 知识检索健康状态
    subagent_suggestion_signal = Signal(object)  # Subagent回复建议
    daemon_suggestion_signal = Signal(object)
    pending_message_consumed_signal = Signal()  # 待发消息被消费（工具回流或idle发送）
    browser_send_result_signal = Signal(object)  # 网页确认后才能清除本地输入草稿

    def __init__(self, startup_mode=None):
        super().__init__()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_complete = False
        self.config = ConfigManager.load()
        self.connector = create_browser_connector(self.config)
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
        from app.core.worker_modules.worker_subagent_bridge import WorkerSubagentBridge
        from app.core.worker_modules.worker_project_switch import WorkerProjectSwitchBridge
        from app.core.worker_modules.worker_browser_stateless import WorkerBrowserStatelessBridge
        from app.core.worker_modules.worker_api_conversation import WorkerApiConversationBridge
        from app.core.worker_modules.worker_api_mode import WorkerApiModeBridge
        from app.core.worker_modules.worker_agent_runtime import WorkerAgentRuntimeBridge
        from app.core.worker_modules.worker_git_bridge import WorkerGitBridge
        from app.core.worker_modules.worker_context_workspace import WorkerContextWorkspaceBridge
        from app.core.worker_modules.worker_runtime_monitor import WorkerRuntimeMonitorBridge
        from app.core.worker_modules.worker_browser_tool_input import WorkerBrowserToolInputBridge
        from app.core.worker_modules.worker_browser_message_sync import WorkerBrowserMessageSyncBridge
        from app.core.worker_modules.worker_agent_sidecar import WorkerAgentSidecarBridge
        from app.core.worker_modules.worker_test_runner import WorkerTestRunnerBridge
        from app.core.worker_modules.worker_browser_commands import WorkerBrowserCommandBridge
        from app.core.worker_modules.worker_code_workspace import WorkerCodeWorkspaceBridge
        from app.core.worker_modules.worker_skills import WorkerSkillsBridge
        from app.core.worker_modules.worker_subagent_notify import WorkerSubagentNotifyBridge
        self.stream_bridge = WorkerStreamBridge(worker=self)
        self.knowledge_task_bridge = WorkerKnowledgeTaskBridge(self.knowledge_service)
        self.api_conversation_bridge = WorkerApiConversationBridge(self)
        self.api_mode_bridge = WorkerApiModeBridge(self)
        self.agent_runtime_bridge = WorkerAgentRuntimeBridge(self)
        self.browser_stateless_bridge = WorkerBrowserStatelessBridge(self)
        self.git_bridge = WorkerGitBridge(self)
        self.context_workspace_bridge = WorkerContextWorkspaceBridge(self)
        self.runtime_monitor_bridge = WorkerRuntimeMonitorBridge(self)
        self.browser_tool_input_bridge = WorkerBrowserToolInputBridge(self)
        self.browser_message_sync_bridge = WorkerBrowserMessageSyncBridge(self)
        self.agent_sidecar_bridge = WorkerAgentSidecarBridge(self)
        self.test_runner_bridge = WorkerTestRunnerBridge(self)
        self.browser_command_bridge = WorkerBrowserCommandBridge(self)
        self.code_workspace_bridge = WorkerCodeWorkspaceBridge(self)
        self.skills_bridge = WorkerSkillsBridge(self)
        self.subagent_notify_bridge = WorkerSubagentNotifyBridge(self)
        self.subagent_bridge = WorkerSubagentBridge()
        self.subagent_bridge.subagent_suggestion_signal.connect(self.subagent_suggestion_signal.emit)
        self.subagent_bridge.subagent_suggestion_signal.connect(self.daemon_suggestion_signal.emit)
        self.daemon_notify_bridge = self.subagent_notify_bridge
        self.daemon_bridge = self.subagent_bridge
        self.subagent_bridge.start()
        self.project_switch_bridge = WorkerProjectSwitchBridge(self)

        ctx = ProjectContext.get()
        ctx.about_to_switch.connect(self.docker_manager.on_about_to_switch)
        ctx.project_switched.connect(self.docker_manager.on_project_switched)
        ctx.project_switched.connect(self.knowledge_service.on_project_switched)
        ctx.project_switched.connect(self.file_service.on_project_switched)
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
        configured_mode = startup_mode or self.config.get("startup_mode", "browser")
        configured_mode = str(configured_mode or "browser").strip().lower()
        self.mode = configured_mode if configured_mode in {"browser", "api"} else "browser"
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

    def shutdown(self, timeout=5.0):
        """Request cooperative cancellation and wait within one shared deadline.

        A False result means a Python/native tool is still unwinding. Keep the
        worker alive and retry; never terminate a QThread or discard a live one.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        if not self._shutdown_lock.acquire(timeout=max(0.0, timeout)):
            return False
        try:
            if self._shutdown_complete:
                return True
            browser = getattr(self, "browser_command_bridge", None)
            if browser:
                with browser._lock:
                    browser._invalidate()
            self.running = False
            self.requestInterruption()
            self.quit()
            from app.core.services.knowledge_service import knowledge_engine
            components = [getattr(self, name, None) for name in
                          ("agent_runtime_bridge", "stream_bridge", "subagent_bridge", "knowledge_service", "test_runner_bridge")]
            if knowledge_engine not in components:
                components.append(knowledge_engine)
            components.append(getattr(self, "docker_manager", None))
            connector = getattr(self, "connector", None)
            if callable(getattr(type(connector), "shutdown", None)):
                components.append(connector)
            components = [item for item in components if item is not None]
            if not self._shutdown_started:
                self._shutdown_started = True
                # Signal every component before spending the waiting budget on
                # any one of them. ThreadPoolExecutor cancels only queued work.
                for component in components:
                    try:
                        component.shutdown(timeout=0)
                    except Exception:
                        logger.exception("关闭组件时发生异常: %s", type(component).__name__)
                executor = getattr(self, "executor", None)
                if executor:
                    executor.shutdown(wait=False, cancel_futures=True)
            complete = True
            for component in components:
                try:
                    stopped = component.shutdown(timeout=max(0.0, deadline - time.monotonic()))
                    complete = bool(stopped) and complete
                except Exception:
                    logger.exception("等待组件停止失败: %s", type(component).__name__)
                    complete = False
            executor = getattr(self, "executor", None)
            for thread in list(getattr(executor, "_threads", ())):
                if thread is not threading.current_thread():
                    thread.join(timeout=max(0.0, deadline - time.monotonic()))
                complete = not thread.is_alive() and complete
            if QThread.currentThread() is not self:
                self.wait(max(0, int((deadline - time.monotonic()) * 1000)))
            complete = not self.isRunning() and complete
            self._shutdown_complete = complete
            return complete
        finally:
            self._shutdown_lock.release()

    def stop_worker(self, timeout=5.0):
        return self.shutdown(timeout=timeout)

    def init_api_stream_bridge(self):
        """在 _init_api_source 完成后调用，注入流式桥接"""
        if self.api_source and self.stream_bridge:
            self.stream_bridge.init_handler(self.api_source, tool_router=getattr(self, "tool_router", None))

            # 将桥接信号转发到 WorkerThread 级别信号，供 server.SignalBridge 分发
            # 仅在已连接过的情况下才 disconnect，避免 PySide6 C++ 层 RuntimeWarning
            if getattr(self, '_stream_signals_connected', False):
                try:
                    self.stream_bridge.stream_chunk_signal.disconnect(self.api_stream_chunk_signal.emit)
                except (RuntimeError, TypeError):
                    pass
                try:
                    self.stream_bridge.stream_status_signal.disconnect(self.api_stream_status_signal.emit)
                except (RuntimeError, TypeError):
                    pass

            if not getattr(self.stream_bridge, "uses_upstream_consumer", False):
                self.stream_bridge.stream_chunk_signal.connect(self.api_stream_chunk_signal.emit)
                self.stream_bridge.stream_status_signal.connect(self.api_stream_status_signal.emit)
                self._stream_signals_connected = True

        if not self.subagent_bridge.subagent_thread.isRunning():
            self.subagent_bridge.start()
    def _build_context_workspace_payload(self):
        return self.context_workspace_bridge.build_payload()

    def _emit_context_workspace_payload(self, client_id=None, user_role=None, conversation_id=None):
        return self.context_workspace_bridge.emit_payload(
            client_id=client_id,
            user_role=user_role,
            conversation_id=conversation_id,
        )

    def get_context_workspace_payload(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.get_payload(
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def update_context_workspace_system_prompt(self, content, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.update_system_prompt(
            content,
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def update_context_workspace_working_memory(self, data, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.update_working_memory(
            data,
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def clear_context_workspace_working_memory(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.clear_working_memory(
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def clear_context_workspace_long_term(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.clear_long_term(
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def get_last_request_snapshot(self, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.get_last_request_snapshot(
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def trigger_api_manual_compact(self, conversation_id=None, client_id='Host', user_role=None, **kwargs):
        return self.context_workspace_bridge.trigger_manual_compact(
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def get_api_conversations(self, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.get_api_conversations(
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def delete_api_messages(self, indexes, conversation_id=None, client_id="Host", user_role=None, **kwargs):
        return self.context_workspace_bridge.delete_api_messages(
            indexes,
            conversation_id=conversation_id,
            client_id=client_id,
            user_role=user_role,
            **kwargs,
        )

    def set_session_role(self, index, role, **kwargs):
        self.agent.set_role(index, role)
        tag = f"[{role.upper()}]" if role else "标记已清除"
        self.safe_emit_status(f"🏷️ 会话 {index} {tag}")

    def cancel_task(self, task_id, client_id="Host", **kwargs):
        task_id = str(task_id or '').strip()
        if not task_id:
            return

        # 1. 检查是否为运行中的 runtime tool task
        runtime_task = self.runtime_monitor_bridge.runtime_tool_tasks.get(task_id)
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
        return self.agent_sidecar_bridge.request_auto_fix(error_report, client_id=client_id, **kwargs)

    def _execute_task(self, task):
        try:
            browser = getattr(self, "browser_command_bridge", None)
            if browser and not browser.task_is_current(task):
                browser.finish_send(task, False, "发送已取消；未自动重发。")
                return
            user = getattr(task, 'username', 'System')
            self.current_user = user

            if task.action == "task_agent_loop":
                self._execute_agent_loop_task(task)
                return

            if task.action in ["do_server_backup", "run_remote_tests"]:
                return self.executor.submit(self._execute_task_bg, task)
            else:
                return self._execute_task_sync(task)

        except Exception as e:
            logger.error("调度器异常: %s", e, extra=get_trace_extra())
            traceback.print_exc()
            self.safe_emit_status(f"🔥 任务出错: {e}")

    def _execute_agent_loop_task(self, task):
        return self.agent_sidecar_bridge.execute_agent_loop_task(task)

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

        elif task.action in {"real_send_text", "compound_send_task"}:
            return self._execute_browser_send(task)

        elif task.action == "upload_file_task":
            if self.connector.interact:
                return self.connector.interact.upload_file(task.args[0])
            self.safe_emit_status("❌ 浏览器未连接，未上传文件。")

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
            if self.mode == "browser":
                self.browser_message_sync_bridge.emit_browser_messages_snapshot(
                    reason="wake_up"
                )

    def _execute_browser_send(self, task):
        """A send becomes busy only after the webpage confirms submission."""
        bridge = self.browser_command_bridge
        epoch = bridge.epoch
        if not bridge.task_is_current(task):
            bridge.finish_send(task, False, "发送已取消；未自动重发。")
            return False
        confirmed = False
        result_message = "发送已取消；未自动重发。"
        try:
            ready = getattr(self.connector, "ready_for_input", None)
            ok, message = ready() if ready else (bool(self.connector.interact), "浏览器未连接")
            if not ok:
                raise RuntimeError(message)
            selector, text = task.args[:2] if task.action == "real_send_text" else ("div.aa-chat-input textarea", task.args[0])
            file_paths = task.args[1] if task.action == "compound_send_task" else []
            if file_paths:
                if not bridge.is_current(epoch):
                    return False
                result = self.connector.interact.upload_file(file_paths)
                if isinstance(result, tuple) and not result[0]:
                    raise RuntimeError(result[1])
                if result is False:
                    raise RuntimeError("附件上传失败")
            if not text:
                result_message = "附件已上传；请输入消息后发送。" if file_paths else "消息为空，未发送。"
                return False
            if not bridge.is_current(epoch):
                return False
            self._pre_send_ai_fingerprint = self._get_last_ai_fingerprint()
            # A cancellation can arrive while Selenium is awaiting its result;
            # never retry this send, and suppress all follow-up work afterwards.
            send = self.connector.send_message
            parameters = inspect.signature(send).parameters
            cancellable = "cancel_check" in parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
            )
            if not bridge.is_current(epoch):
                return False
            result = send(selector, text, cancel_check=lambda: not bridge.is_current(epoch)) if cancellable else send(selector, text)
            ok, message = result if isinstance(result, tuple) else (bool(result), "网页未确认发送成功")
            if not bridge.is_current(epoch):
                return False
            if not ok:
                raise RuntimeError(message)
            self.last_send_time = time.time()
            self.was_busy = True
            self._round_sm.handle_event(RoundStateEvent.BUSY_DETECTED)
            self._update_ai_state("busy")
            self.safe_emit_status("✅ 网页已确认发送")
            confirmed = True
            result_message = "网页已确认发送"
            return True
        except Exception as exc:
            result_message = f"发送失败：{exc}。未自动重发，请确认网页后手动重试。"
            self.last_send_time = 0
            self.was_busy = False
            self._pre_send_ai_fingerprint = None
            self._round_sm.handle_event(RoundStateEvent.ERROR_RESET)
            self._update_ai_state("idle")
            self.safe_emit_status(f"❌ {result_message}")
            return False
        finally:
            bridge.finish_send(task, confirmed, result_message)

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
        return self.code_workspace_bridge.ignore_block_content(
            filename,
            content,
            client_id=client_id,
            **kwargs,
        )

    def _do_ignore_block(self, filename, content):
        return self.code_workspace_bridge.do_ignore_block(filename, content)

    def unignore_block_content(self, filename, content, client_id="Host", **kwargs):
        return self.code_workspace_bridge.unignore_block_content(
            filename,
            content,
            client_id=client_id,
            **kwargs,
        )

    def _do_unignore_block(self, filename, content):
        return self.code_workspace_bridge.do_unignore_block(filename, content)

    def run_remote_tests(self, client_id="Host", **kwargs):
        return self.test_runner_bridge.run_remote_tests(client_id=client_id, **kwargs)

    def _run_tests_bg(self, client_id):
        return self.test_runner_bridge.run_tests_bg(client_id)

    def _notify_subagent_reply_completed(self, mode: str, chat_id: str = ""):
        return self.subagent_notify_bridge.notify_reply_completed(mode, chat_id)

    def _background_process_ai_response(self, browser_epoch=None):
        bridge = getattr(self, "browser_command_bridge", None)
        browser_epoch = bridge.epoch if bridge and browser_epoch is None else browser_epoch
        if bridge and not bridge.is_current(browser_epoch):
            return
        try:
            self._round_sm.handle_event(RoundStateEvent.PIPELINE_START)
            logger.info("流水线: 开始处理 AI 回复...")
            time.sleep(2.0)
            if bridge and not bridge.is_current(browser_epoch):
                return

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
            self._check_and_handle_tool(browser_epoch=browser_epoch)
            if bridge and not bridge.is_current(browser_epoch):
                return
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

    def _background_process_ai_response_direct(self, browser_epoch=None):
        """超时兜底 / 修复按钮专用：跳过指纹对比，直接执行流水线"""
        bridge = getattr(self, "browser_command_bridge", None)
        browser_epoch = bridge.epoch if bridge and browser_epoch is None else browser_epoch
        if bridge and not bridge.is_current(browser_epoch):
            return
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
            self._check_and_handle_tool(browser_epoch=browser_epoch)
            if bridge and not bridge.is_current(browser_epoch):
                return

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
        return self.browser_message_sync_bridge.emit_browser_messages_snapshot(reason)

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

    def _check_and_handle_tool(self, browser_epoch=None):
        browser = getattr(self, "browser_command_bridge", None)
        browser_epoch = browser.epoch if browser and browser_epoch is None else browser_epoch
        if browser and not browser.is_current(browser_epoch):
            return
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

            if browser and not browser.is_current(browser_epoch):
                return
            self._round_sm.handle_event(RoundStateEvent.TOOL_EXECUTION_START)

            logger.info("[工具路由] 开始工具识别与执行 | ai_msg_id=%s | 消息数=%s",
                        ai_msg_id, len(candidate_messages))
            _t0 = time.time()
            def on_browser_intent_start(intent, index):
                if browser and not browser.is_current(browser_epoch):
                    raise CancelledError("浏览器请求已取消，未启动后续工具")
                self._handle_runtime_tool_start(intent, index)
                if browser and not browser.is_current(browser_epoch):
                    raise CancelledError("浏览器请求已取消，未启动后续工具")

            response = self.tool_router.maybe_handle_tool_from_messages(
                chat_id=self.current_chat_id,
                messages=candidate_messages,
                allow=True,
                on_intent_start=on_browser_intent_start,
                on_intent_end=self._handle_runtime_tool_end,
            )
            logger.info("[工具路由] 工具识别与执行完成 | 耗时=%.1fs | ai_msg_id=%s",
                        time.time() - _t0, ai_msg_id)

            response_text = self._build_browser_tool_feedback_text(response)
            if browser and not browser.is_current(browser_epoch):
                return

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
                # 只有用户主动点击「随工具发送」后 pending_user_message 才会被设置
                # idle 自动发送路径不经过此处，两条路径互斥，不会重复发送
                pending = self.get_and_clear_pending_message()
                logger.info("[工具路由] get_and_clear_pending_message 结果: %s", pending)
                if pending:
                    pending_text = str(pending.get("text", "") or "").strip()
                    logger.info("[工具路由] pending_text 长度: %d", len(pending_text))
                    if pending_text:
                        response_text = response_text + f"\n\n[USER_MESSAGE_BEGIN]\n{pending_text}\n[USER_MESSAGE_END]"
                        self.safe_emit_status("✅ 已附加用户待发消息")
                        logger.info("[工具路由] 用户待发消息已附加到工具结果，通知 UI 清除排队")
                        self.pending_message_consumed_signal.emit()
                else:
                    logger.info("[工具路由] 无待发消息，跳过 pending 附加")

                self._round_sm.handle_event(RoundStateEvent.TOOL_RESULT_READY)
                enqueue = (lambda *a, **kw: browser.enqueue_feedback(browser_epoch, *a, **kw)) if browser else self.scheduler.add_task
                enqueue(
                    "Host",
                    "real_send_text",
                    "div.aa-chat-input textarea",
                    response_text,
                    username="System",
                    tool_call_id=primary_tc_id,
                    tool_name="tool_feedback",
                )
                logger.info("[工具路由] 工具结果已入队 scheduler | ai_msg_id=%s | tool_call_id=%s", ai_msg_id, primary_tc_id)

        except CancelledError:
            logger.info("浏览器请求已取消，后续工具与回传已停止")
        except Exception as e:
            logger.error("工具路由异常: %s", e)
            traceback.print_exc()
        finally:
            # 正常路径：工具成功/失败都有 response_text → TOOL_RESULT_READY → SYSTEM_SENDING
            # 异常路径：maybe_handle_tool_from_messages 抛异常 → state 仍在 TOOL_EXECUTING
            # 此处只处理异常路径，正常路径 state 已经是 SYSTEM_SENDING，不动
            if not browser or browser.is_current(browser_epoch):
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
        return self.code_workspace_bridge.get_staging_file_content(
            rel_path,
            client_id=client_id,
            **kwargs,
        )

    def handle_sync_request(self, client_id="Host", **kwargs):
        return self.code_workspace_bridge.handle_sync_request(client_id=client_id, **kwargs)

    def handle_compound_send(self, text, file_paths, client_id="Host", **kwargs):
        return self.browser_command_bridge.handle_compound_send(
            text,
            file_paths,
            client_id=client_id,
            **kwargs,
        )

    def send_compound(self, text, file_paths, client_id="Host", **kwargs):
        return self.browser_command_bridge.send_compound(
            text,
            file_paths,
            client_id=client_id,
            **kwargs,
        )

    def upload_file(self, file_path, client_id="Host", **kwargs):
        return self.browser_command_bridge.upload_file(file_path, client_id=client_id, **kwargs)

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
        return self.browser_command_bridge.send_text(selector, text, client_id=client_id, **kwargs)

    def run_remote_script(self, code, client_id="Host", **kwargs):
        return self.browser_command_bridge.run_remote_script(code, client_id=client_id, **kwargs)

    def request_switch_session(self, index, client_id="Host", **kwargs):
        return self.browser_command_bridge.request_switch_session(index, client_id=client_id, **kwargs)

    def new_chat(self, client_id="Host", **kwargs):
        return self.browser_command_bridge.new_chat(client_id=client_id, **kwargs)

    def request_wake_up(self, client_id="Host", **kwargs):
        return self.browser_command_bridge.request_wake_up(client_id=client_id, **kwargs)

    def request_fix_all(self, client_id="Host", **kwargs):
        return self.browser_command_bridge.request_fix_all(client_id=client_id, **kwargs)

    def trigger_manual_toggle(self, msg_index, blk_idx, total, client_id="Host", **kwargs):
        return self.browser_command_bridge.trigger_manual_toggle(
            msg_index,
            blk_idx,
            total,
            client_id=client_id,
            **kwargs,
        )

    def do_server_scan(self, **kwargs):
        return self.code_workspace_bridge.do_server_scan(**kwargs)

    def do_server_apply(self, paths, **kwargs):
        return self.code_workspace_bridge.do_server_apply(paths, **kwargs)

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
        return self.code_workspace_bridge.request_generate_snapshot(*args, **kwargs)

    def do_server_clear_cache(self, **kwargs):
        return self.code_workspace_bridge.do_server_clear_cache(**kwargs)

    def set_exec_mode(self, mode: str, local_python: str = "", **kwargs):
        """代理方法：将执行环境切换请求转发给 docker_manager。供 RPC 调用。"""
        if self.docker_manager:
            self.docker_manager.set_exec_mode(mode, local_python)
        else:
            logger.warning("[set_exec_mode] docker_manager 未初始化，忽略切换请求")

    def update_config(self, cfg, **kwargs):
        self.config = cfg
        self.file_service.config = cfg
        self.update_service.config = cfg
        if hasattr(self, 'subagent_bridge') and self.subagent_bridge:
            try:
                self.subagent_bridge.reload()
            except Exception as e:
                logger.debug("Subagent配置热重载异常: %s", e)


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

    def api_probe_tool_support(self, **kwargs):
        return self.api_mode_bridge.api_probe_tool_support(**kwargs)

    def api_probe_models(self, **kwargs):
        return self.api_mode_bridge.api_probe_models(**kwargs)

    def manual_save(self, f, c, **kwargs):
        return self.code_workspace_bridge.manual_save(f, c, **kwargs)

    def navigate(self, u, **kwargs):
        self.connector.navigate(u)

    def trigger_paste(self, s="textarea", auto_send=False, **kwargs):
        self.connector.paste_to_input(s, auto_send=auto_send)

    def touch_file(self, path, **kwargs):
        return self.code_workspace_bridge.touch_file(path, **kwargs)

    def set_manual_turn(self, num, **kwargs):
        self.state_service.set_manual_bubble_count(self.current_chat_id, num)
        self._check_and_emit_sync(True)

    def set_manual_snapshot(self, num, **kwargs):
        self.state_service.set_snapshot(self.current_chat_id, num)
        self._check_and_emit_sync(True)

    def trigger_resync(self):
        return self.browser_message_sync_bridge.trigger_resync()


    def _check_and_emit_sync(self, force=False):
        return self.browser_message_sync_bridge.check_and_emit_sync(force)

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

        # Subagent触发：仅浏览器回复流水线 fixing → idle 后生成建议。
        # 会话切换、异常恢复、工具失败兜底等回到 idle 的路径不应误触发建议。
        if (
            old_state == BrowserRoundState.FIXING
            and new_state == BrowserRoundState.IDLE
            and event == RoundStateEvent.PIPELINE_END
        ):
            try:
                self._notify_subagent_reply_completed("browser", self.current_chat_id)
            except Exception as e:
                logger.debug("[Subagent] 浏览器模式通知失败（非致命）: %s", e)

    @property
    def _browser_round_state(self) -> str:
        """兼容属性：旧代码中读取 _browser_round_state 的地方继续工作。"""
        return self._round_sm.state_value

    @property
    def browser_round_state(self) -> str:
        """公开属性：UI 层通过此属性获取状态机当前状态，无需 __dict__ 穿透。"""
        return self._round_sm.state_value

    def _normalize_runtime_task(self, task: dict | None):
        return self.runtime_monitor_bridge.normalize_runtime_task(task)

    def _upsert_runtime_task(self, task: dict | None):
        return self.runtime_monitor_bridge.upsert_runtime_task(task)

    def _remove_runtime_task(self, task_id: str | None):
        return self.runtime_monitor_bridge.remove_runtime_task(task_id)

    def _build_queue_monitor_snapshot(self):
        return self.runtime_monitor_bridge.build_queue_monitor_snapshot()

    def _emit_queue_monitor_snapshot(self, reason='runtime_event'):
        return self.runtime_monitor_bridge.emit_queue_monitor_snapshot(reason)

    def _emit_tool_event(self, event_type, tool_call_id, tool_name, status,
                         success=None, elapsed_ms=0, index=0):
        return self.runtime_monitor_bridge.emit_tool_event(
            event_type,
            tool_call_id,
            tool_name,
            status,
            success=success,
            elapsed_ms=elapsed_ms,
            index=index,
        )

    def _handle_runtime_tool_start(self, intent, index):
        return self.runtime_monitor_bridge.handle_runtime_tool_start(intent, index)

    def _handle_runtime_tool_end(self, intent, result, index):
        return self.runtime_monitor_bridge.handle_runtime_tool_end(intent, result, index)

    def _handle_knowledge_task_state_change(self, event):
        return self.runtime_monitor_bridge.handle_knowledge_task_state_change(event)

    def _wrap_tool_runtime_start(self, previous_callback):
        return self.runtime_monitor_bridge.wrap_tool_runtime_start(previous_callback)

    def _wrap_tool_runtime_end(self, previous_callback):
        return self.runtime_monitor_bridge.wrap_tool_runtime_end(previous_callback)

    def _install_tool_runtime_callbacks(self):
        return self.runtime_monitor_bridge.install_tool_runtime_callbacks()

    def _restore_tool_runtime_callbacks(self, token=None):
        return self.runtime_monitor_bridge.restore_tool_runtime_callbacks(token)

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
        return self.browser_tool_input_bridge.extract_browser_tool_input()

    def _looks_like_browser_tool_feedback_text(self, text: str) -> bool:
        return self.browser_tool_input_bridge.looks_like_browser_tool_feedback_text(text)

    def _classify_browser_tool_input(self, candidate_messages, fallback_text: str = '', used_structured: bool = False) -> str:
        return self.browser_tool_input_bridge.classify_browser_tool_input(
            candidate_messages,
            fallback_text=fallback_text,
            used_structured=used_structured,
        )

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
        browser = getattr(self, "browser_command_bridge", None)
        if browser and not browser.is_current():
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
        return self.skills_bridge.get_skills_list(client_id=client_id, **kwargs)

    def toggle_skill(self, skill_name, enabled, client_id="Host", **kwargs):
        return self.skills_bridge.toggle_skill(
            skill_name,
            enabled,
            client_id=client_id,
            **kwargs,
        )

    def reload_skill(self, skill_name, client_id="Host", **kwargs):
        return self.skills_bridge.reload_skill(skill_name, client_id=client_id, **kwargs)

    def get_system_prompt(self, client_id="Host", **kwargs):
        return self.skills_bridge.get_system_prompt(client_id=client_id, **kwargs)

    def request_browser_reconnect(self, start_browser=False, **kwargs):
        return self.browser_command_bridge.reconnect(start_browser=start_browser, **kwargs)

    def browser_cancel(self, **kwargs):
        return self.browser_command_bridge.cancel(**kwargs)

    def _recreate_browser_connector(self):
        """Apply saved local settings without touching a server's shared Chrome."""
        with self._shutdown_lock:
            if not self.running or self._shutdown_started:
                return False
            close = getattr(self.connector, "shutdown", None)
            if close and close(timeout=1.0) is False:
                return False
            self.config = ConfigManager.load()
            self.connector = create_browser_connector(self.config)
            return True

    def run(self):
        """Keep the worker alive across unavailable services and mode changes."""
        while self.running:
            try:
                if self.mode == "api":
                    self._run_api_loop()
                else:
                    self._run_browser_loop()
            except Exception as exc:
                logger.exception("Worker 模式循环异常")
                self.safe_emit_status(f"⚠️ 当前模式暂不可用：{exc}；可修改设置后重连。")
            if self.running:
                time.sleep(0.3)

    def _run_browser_loop(self):
        """An unavailable Chrome/driver/login page is recoverable, not terminal."""
        bridge = self.browser_command_bridge
        self._check_and_emit_sync(True)
        while self.running and self.mode == "browser":
            try:
                bridge.process_controls()
                if not self.running or self.mode != "browser":
                    return
                if not bridge.connected:
                    if time.monotonic() >= bridge.next_connect_at:
                        bridge.connected = self._connect_browser()
                        bridge.ready = bridge.connected
                        bridge.next_connect_at = time.monotonic() + 3.0
                    if not bridge.connected:
                        time.sleep(0.3)
                        continue

                self._browser_scan_queues()
                current_busy, next_state = self._browser_detect_state()
                self.was_busy = current_busy
                self._update_ai_state(next_state)
                if not bridge.connected:
                    continue
                self._browser_process_messages()
                if bridge.is_current():
                    self._process_toggle_queue()
                if time.time() - self.last_occupancy_scan > 2:
                    self.occupancy_signal.emit(self.scheduler.get_occupancy_map())
                    self.last_occupancy_scan = time.time()
            except Exception as exc:
                logger.warning("浏览器暂不可用: %s", exc)
                bridge.connected = False
                bridge.ready = False
                bridge.next_connect_at = time.monotonic() + 3.0
                self.was_busy = False
                self.last_send_time = 0
                self._round_sm.handle_event(RoundStateEvent.ERROR_RESET)
                bridge.report_connection(f"⚠️ 浏览器暂不可用：{exc}；正在等待重连。")
            time.sleep(0.3)

    def _connect_browser(self):
        if not self.running or self.mode != "browser":
            return False
        bridge = self.browser_command_bridge
        try:
            ok, message = self.connector.connect()
        except Exception as exc:
            ok, message = False, str(exc)
        if not self.running or self.mode != "browser":
            return False
        if not ok:
            self._round_sm.handle_event(RoundStateEvent.ERROR_RESET)
            self._update_ai_state("idle")
            bridge.report_connection(f"⚠️ {message}；请检查浏览器设置或完成网页登录，可点击重连。")
            return False
        bridge.report_connection(f"✅ 浏览器已就绪：{message}")
        # Mark pre-existing content handled so reconnect does not replay tools.
        try:
            initial_id = self.connector.get_last_ai_message_id()
            if initial_id:
                self._last_processed_ai_msg_id = initial_id
        except Exception:
            pass
        self.last_session_scan = 0
        return True

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
        bridge = self.browser_command_bridge
        current_busy = self.connector.is_busy()
        if not current_busy:
            ready = getattr(self.connector, "ready_for_input", None)
            ok, message = ready() if ready else (bool(self.connector.interact), "浏览器未连接")
            bridge.ready = bool(ok)
            if not ok:
                with bridge._lock:
                    bridge._invalidate()
                bridge.connected = False
                bridge.next_connect_at = time.monotonic() + 3.0
                self.was_busy = False
                self.last_send_time = 0
                self._round_sm.handle_event(RoundStateEvent.ERROR_RESET)
                bridge.report_connection(f"⚠️ {message}；未发送待发内容，请检查网页后重试。")
                return False, "idle"
        if bridge.cancelled:
            # Stop may fail on an unsupported site. Do not restart a cancelled
            # tool pipeline or send queued content when the site later idles.
            self.last_send_time = 0
            self._round_sm.handle_event(RoundStateEvent.FORCE_IDLE)
            task = self.scheduler.get_next_task()
            if task:
                try:
                    self._execute_task(task)  # its guard rejects stale browser actions
                finally:
                    self.scheduler.mark_task_complete()
            return False, "idle"
        if current_busy:
            self._round_sm.handle_event(RoundStateEvent.BUSY_DETECTED)
            self.last_send_time = 0
            return True, "busy"
        if self.was_busy:
            # Allow a just-committed request time to reveal its Stop indicator.
            if self.last_send_time and time.time() - self.last_send_time < 1.0:
                return True, "busy"
            if self.last_send_time:
                current_fp = self._get_last_ai_fingerprint(live=True)
                if not current_fp or current_fp == self._pre_send_ai_fingerprint:
                    if time.time() - self.last_send_time < 10:
                        return True, "busy"
                    self.last_send_time = 0
                    self._round_sm.handle_event(RoundStateEvent.ERROR_RESET)
                    self.safe_emit_status("⚠️ 网页已确认提交，但尚未检测到新回复。请查看网页；不会自动重发。")
                    return False, "idle"
            self._round_sm.handle_event(RoundStateEvent.BUSY_TO_IDLE)
            self.safe_emit_status("✅ 生成结束，处理输出...")
            self.executor.submit(self._background_process_ai_response, bridge.epoch)
            self.last_send_time = 0
            return False, "fixing"
        if self.toggle_queue:
            return False, "fixing"
        if self._round_sm.ui_state in {"fixing", "tool_executing"}:
            return False, self._round_sm.ui_state

        task = self.scheduler.get_next_task()
        if task:
            try:
                if not bridge.task_is_current(task):
                    bridge.finish_send(task, False, "发送已取消；未自动重发。")
                    return False, "idle"
                # Selenium sends and UI navigation are serialized on the worker
                # lane. Never fire overlapping sends in the shared executor.
                result = self._execute_task(task)
                if task.action in {"real_send_text", "compound_send_task"}:
                    return bool(result), "busy" if result else "idle"
            finally:
                complete = getattr(self.scheduler, "mark_task_complete", None)
                if complete:
                    complete()
        return False, self._round_sm.ui_state

    def _browser_process_messages(self):
        detected_title_id = self.connector.get_chat_title_id()
        if detected_title_id and detected_title_id != self.current_chat_id:
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
                self._background_process_ai_response_direct()
                continue
            msg_idx, blk_idx, total, fingerprint = task
            self.connector.manual_toggle_block(
                0, blk_idx, total, fingerprint
            )

    def _idle_probe_and_maybe_push(self, transient_last_ai=False):
        return self.browser_message_sync_bridge.idle_probe_and_maybe_push(transient_last_ai)

    def _do_extract_and_push(self, reason='state_driven', transient_last_ai=False):
        return self.browser_message_sync_bridge.do_extract_and_push(reason, transient_last_ai)

    def _do_push_extracted_messages(self, raw_msgs, reason='unknown', force_full=False):
        return self.browser_message_sync_bridge.do_push_extracted_messages(raw_msgs, reason, force_full)

    def _prescan_tool_call_ids(self, raw_msgs):
        return self.browser_message_sync_bridge.prescan_tool_call_ids(raw_msgs)


    #============================================================
    # API???
    # ============================================================

    def switch_mode(self, mode: str, **kwargs):
        return self.api_mode_bridge.switch_mode(mode, **kwargs)

    def _init_api_source(self):
        return self.api_mode_bridge._init_api_source()

    def get_agent_runtime_options(self, **kwargs):
        return self.agent_runtime_bridge.options(**kwargs)

    def get_agent_runtime_state(self, **kwargs):
        return self.agent_runtime_bridge.state(**kwargs)

    def api_cancel(self, conversation_id=None, request_id=None, **kwargs):
        if self.agent_runtime_bridge.is_running:
            return self.agent_runtime_bridge.cancel(conversation_id, request_id, **kwargs)
        if self.stream_bridge:
            self.stream_bridge.cancel_stream()
        self._api_pending_text = None
        return {"ok": True}

    def api_approve_tool(self, conversation_id, request_id, call_id, approved, **kwargs):
        return self.agent_runtime_bridge.approve(conversation_id, request_id, call_id, approved, **kwargs)

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
