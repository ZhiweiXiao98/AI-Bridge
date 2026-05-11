import threading
import time
import traceback

from app.core.api.api_stream_models import StreamStatus
from app.core.logging import get_logger, get_trace_extra, new_trace, new_round
from app.core.logging.trace_context import get_current_trace
from app.core.debug import probe
from app.core.project_context import ProjectContext

logger = get_logger("app.core.worker_modules.worker_api_mode", side="worker")


class WorkerApiModeBridge:
    """API mode bridge for WorkerThread.

    The bridge deliberately delegates unknown attributes and writes back state to
    WorkerThread so the moved methods keep their original behavior while the
    worker stays as the public RPC facade.
    """

    def __init__(self, worker):
        object.__setattr__(self, "worker", worker)

    def __getattr__(self, name):
        return getattr(self.worker, name)

    def __setattr__(self, name, value):
        if name == "worker":
            object.__setattr__(self, name, value)
        else:
            setattr(self.worker, name, value)

    #============================================================
    # API模式
    # ============================================================

    def switch_mode(self, mode: str, **kwargs):
        """
        切换消息源模式。
        由 UI 层（Tab切换）调用，同一时刻只有一个模式活跃。
        """
        if mode == self.mode:
            return
        old_mode = self.mode
        self.mode = mode
        self._normalizer.clear()
        self.safe_emit_status(f"🔄 切换模式: {old_mode} → {mode}")
        self.mode_changed_signal.emit(mode)

        if mode == "api":
            self._init_api_source()
            convs = self.api_source.get_conversations()
            self.sessions_signal.emit(convs)
            if hasattr(self.api_source, "has_active_conversation") and self.api_source.has_active_conversation():
                msgs = self.api_source.get_history_as_messages()
                self.messages_signal.emit(msgs if msgs else [])
                status = self.api_source.get_context_status()
                self.context_status_signal.emit(status)
            else:
                self.messages_signal.emit([])
                self.context_status_signal.emit({})
                self.safe_emit_status("🤖 API 模式暂无对话")
        else:
            try:
                if self.connector.interact:
                    self.connector.interact.switch_to_chat_tab()
                s_list = self.connector.get_session_list()
                if s_list:
                    self.sessions_signal.emit(s_list)
                raw_msgs, _ = self.connector.get_chat_content(self.target_class, auto_wake=False)
                raw_msgs = self.file_service.process_images(raw_msgs)
                if raw_msgs:
                    self._do_push_extracted_messages(raw_msgs, reason='mode_switch', force_full=True)
                else:
                    self.messages_signal.emit([])
            except Exception as e:
                self.safe_emit_status(f"⚠️ Browser 模式数据补推失败: {e}")
            self.context_status_signal.emit({})
    def _init_api_source(self):
        """延迟初始化 APISource"""
        if self.api_source is not None:
            return
        try:
            from app.core.api_source import APISource
            self.api_source = APISource()
            self.api_source.initialize()
            if hasattr(self.api_source, 'conv_store') and self.api_source.conv_store:
                ProjectContext.get().project_switched.connect(self.api_source.conv_store.on_project_switched)
            # 绑定工具状态回调
            if hasattr(self, 'api_stream_status_signal'):
                def _forward_tool_status_event(event):
                    self.api_stream_status_signal.emit(event)
                    try:
                        if isinstance(event, dict) and event.get('type') == 'tool_call':
                            ctx = get_current_trace()
                            self.api_round_state_signal.emit({
                                'conversation_id': event.get('conversation_id', ''),
                                'state': 'running_tools' if event.get('status') == 'running' else 'detecting_tools',
                                'tool_name': event.get('tool_name', ''),
                                'message': event.get('message', ''),
                                'trace_id': ctx.trace_id if ctx else "",
                                'round_id': ctx.round_id if ctx else "",
                            })
                            probe("api_tool_status", level="info", side="worker",
                                  tool_name=event.get('tool_name', ''),
                                  status=event.get('status', ''))
                    except Exception as e:
                        logger.warning(e)
                self.api_source.on_tool_status_event = _forward_tool_status_event
            original_set_round_state = getattr(self.api_source, 'set_round_state', None)
            if callable(original_set_round_state):
                def _wrapped_set_round_state(state, conversation_id=None):
                    ok = original_set_round_state(state, conversation_id=conversation_id)
                    try:
                        trace_id = ""
                        ctx = get_current_trace()
                        if ctx:
                            trace_id = ctx.trace_id
                        round_id = ctx.round_id if ctx else ""
                        self.api_round_state_signal.emit({
                            'conversation_id': conversation_id or (self.api_source.conv_store.active_id if self.api_source and self.api_source.conv_store else ''),
                            'state': str(state or '').strip() or 'idle',
                            'trace_id': trace_id,
                            'round_id': round_id,
                        })
                    except Exception as e:
                        logger.warning(e)
                    return ok
                self.api_source.set_round_state = _wrapped_set_round_state
            self.safe_emit_status("✅ API 消息源初始化完成")
            logger.info("[API] 消息源初始化完成，准备注入桥接")

            # 完成初始化后注入流式桥接
            self.init_api_stream_bridge()
            logger.info("[API] 流式桥接注入完成")

        except Exception as e:
            self.safe_emit_status(f"❌ API 初始化失败: {e}")
            self.mode = "browser"
    def api_send(self, text: str, **kwargs):
        """API模式发送消息（由UI层调用）"""
        conv_id = ""
        if self.api_source and self.api_source.conv_store:
            conv_id = self.api_source.conv_store.active_id or ""
        ctx = new_trace(conversation_id=conv_id, side="worker")
        new_round()
        self._current_trace_ctx = ctx
        logger.info(f"[API] api_send 被调用 | stream={kwargs.get('stream', False)} | text_len={len(text)}", extra=get_trace_extra())
        probe("api_send_entry", level="info", side="worker", stream=kwargs.get('stream', False), text_len=len(text))
        if self.mode != "api" or not self.api_source:
           logger.warning(f"[API] 模式检查失败 | mode={self.mode} | has_api_source={bool(self.api_source)}")
           self.safe_emit_status("⚠️ 当前不在API模式")
           return
        if hasattr(self.api_source, "has_active_conversation") and not self.api_source.has_active_conversation():
           logger.warning("[API] 没有活跃对话")
           self.safe_emit_status("⚠️ 当前没有可用的 API 对话，请先新建对话")
           return
        try:
            profile = self.api_source.get_runtime_profile() if hasattr(self.api_source, "get_runtime_profile") else {}
            if profile.get("kind") == "browser_stateless":
                kwargs["stream"] = False
        except Exception as e:
            logger.warning(e)
        if kwargs.get('stream', False):
            logger.info("[API] 启动流式发送")
            # 为远程链路注入目标路由信息
            try:
                if self.stream_bridge and hasattr(self.stream_bridge, 'set_target'):
                    self.stream_bridge.set_target(kwargs.get('client_id'), kwargs.get('user_role'))
                    logger.info("[API] 流式桥接 target 已设置")
            except Exception as e:
                logger.warning(e)
            # 流式发送（用户消息入库后会在 _handle_api_send_stream 内立即回显）
            self._api_pending_text = None
            self._handle_api_send_stream(text)
        else:
            logger.info("[API] 启动同步发送")
            # 同步发送
            self._api_pending_text = text
            logger.info("[API] 已缓存待发送内容，等待循环处理")
    def _run_api_loop(self):
        """API模式主循环"""
        self._init_api_source()
        if not self.api_source:
            self.safe_emit_status("❌ API源不可用，回退到浏览器模式")
            self.mode = "browser"
            self._run_browser_loop()
            return
     
        self.safe_emit_status("🤖 API 模式已启动")
        # 发送初始对话列表和历史
        convs = self.api_source.get_conversations()
        self.sessions_signal.emit(convs if convs else [])
        if hasattr(self.api_source, "has_active_conversation") and self.api_source.has_active_conversation():
            msgs = self.api_source.get_history_as_messages()
            self.messages_signal.emit(msgs if msgs else [])
            status = self.api_source.get_context_status()
            self.context_status_signal.emit(status)
        else:
            self.messages_signal.emit([])
            self.context_status_signal.emit({})

        while self.running:
            try:
                # 模式被切走了，退出循环
                if self.mode != "api":
                    self.safe_emit_status("🔄 退出API循环，切换到浏览器模式")
                    self._run_browser_loop()
                    return

                # 检查是否有待发送消息
                text = self._api_pending_text
                if text:
                    self._api_pending_text = None
                    self._handle_api_send(text)

            except Exception as e:
                logger.error("API循环异常: %s", e, extra=get_trace_extra())
                import traceback
                traceback.print_exc()
                self.safe_emit_status(f"❌ API循环错误: {e}")
                time.sleep(2.0)

            time.sleep(0.3)

    def _continue_api_round_after_stream(self):
        """首轮流式完成后，继续推进工具检测/工具执行/followup/finalized。"""
        active_conv_id = "api_default"
        loop_result = {
            'round_finalized': False,
            'loop_count': 0,
            'selected_protocols': [],
            'msgs': [],
        }

        try:
            if not self.api_source:
                return

            active_conv_id = (
                self.api_source.conv_store.active_id
                if self.api_source and self.api_source.conv_store and self.api_source.conv_store.active_id
                else "api_default"
            )

            logger.info("API: 流式完成，进入回合后半段检测", extra=get_trace_extra())


            runtime_callback_token = self._install_tool_runtime_callbacks()
            def _debug_api_msgs(label, msgs):
                try:
                    count = len(msgs or [])
                    last = (msgs or [])[-1] if count else {}
                    role = str(last.get('role', '') or '') if isinstance(last, dict) else ''
                    kind = str(last.get('kind', '') or last.get('type', '') or '') if isinstance(last, dict) else ''
                    content_len = 0
                    if isinstance(last, dict):
                        segments = last.get('segments', [])
                        if isinstance(segments, list):
                            for seg in segments:
                                if isinstance(seg, dict):
                                    content_len += len(str(seg.get('content', '') or ''))
                        if content_len == 0:
                            content_len = len(str(last.get('content', '') or last.get('text', '') or ''))
                    probe("api_stream_after", level="debug", side="worker",
                          label=label, count=count, role=role, kind=kind, content_len=content_len)
                except Exception as e:
                    logger.debug("api_stream_after debug failed: %s", e)

            # 1. 先把首轮 assistant 文本正式推给 UI 缓存，避免 finalized 时没有最新数据。
            try:
                current_msgs = self.api_source.get_history_as_messages()
                _debug_api_msgs("initial_history", current_msgs)
                self.messages_signal.emit(current_msgs if current_msgs else [])
            except Exception as e:
                logger.warning(e)
                current_msgs = []

            # 2. 进入工具检测态。
            try:
                if hasattr(self.api_source, 'set_round_state'):
                    self.api_source.set_round_state('detecting_tools', conversation_id=active_conv_id)
                self.api_round_state_signal.emit({
                    'conversation_id': active_conv_id,
                    'state': 'detecting_tools',
                    'message': '🧠 正在分析工具调用...',
                    'trace_id': (get_current_trace().trace_id if get_current_trace() else ""),
                    'round_id': (get_current_trace().round_id if get_current_trace() else ""),
                })
                probe("api_detecting_tools", level="info", side="worker", conv_id=active_conv_id)
            except Exception as e:
                logger.warning(e)

            # 3. 预采样候选仅用于调试/快照，不再作为是否进入 tool loop 的阻断条件。
            candidates = []
            try:
                candidate_input = (current_msgs or [])[-1:]
                _debug_api_msgs("candidate_input", candidate_input)
                if self.tool_router and hasattr(self.tool_router, 'collect_tool_candidates'):
                    candidates = self.tool_router.collect_tool_candidates(active_conv_id, candidate_input) or []
                probe("api_candidates", level="debug", side="worker",
                      count=len(candidates or []))
                if hasattr(self.api_source, 'set_tool_candidates'):
                    self.api_source.set_tool_candidates(candidates, conversation_id=active_conv_id)
            except Exception as e:
                logger.warning(e)
                candidates = []

            from app.core.tool_runtime.conversation_loop import ToolConversationLoop
            loop_runner = ToolConversationLoop(
                api_source=self.api_source,
                tool_router=self.tool_router,
            )
            loop_result = loop_runner.run_api_loop(conversation_id=active_conv_id) or loop_result
            probe("api_loop_result", level="info", side="worker",
                  executed=loop_result.get('executed'),
                  loop_count=loop_result.get('loop_count'),
                  stopped_reason=loop_result.get('stopped_reason'),
                  protocols=loop_result.get('selected_protocols'))

            try:
                final_msgs = loop_result.get('msgs') or self.api_source.get_history_as_messages()
                self.messages_signal.emit(final_msgs if final_msgs else [])
            except Exception as e:
                logger.warning(e)

            loop_count = int(loop_result.get('loop_count', 0) or 0)
            stopped_reason = str(loop_result.get('stopped_reason', '') or '')
            if loop_count > 0:
                if stopped_reason == 'max_rounds_reached':
                    self.safe_emit_status(f"⛔ 已达到最大自动续答轮数，停止继续调用（{loop_count} 轮）")
                else:
                    self.safe_emit_status(f"🤖 工具闭环完成，共自动续答 {loop_count} 轮")

            try:
                final_msgs = loop_result.get('msgs') or self.api_source.get_history_as_messages()
                self.process_batch(final_msgs if final_msgs else [])
            except Exception as e:
                logger.warning(e)

            try:
                status = self.api_source.get_context_status()
                self.context_status_signal.emit(status)
            except Exception as e:
                logger.warning(e)

        except Exception as e:
            logger.error("API: 流式后工具闭环失败: %s", e, extra=get_trace_extra())
            traceback.print_exc()
            self.safe_emit_status(f"❌ 流式后工具闭环失败: {e}")

        finally:
            try:
                self._restore_tool_runtime_callbacks(locals().get('runtime_callback_token'))
            except Exception as e:
                logger.warning(e)

            try:
                if self.api_source:
                    if hasattr(self.api_source, 'finalize_round_snapshot'):
                        self.api_source.finalize_round_snapshot(conversation_id=active_conv_id)
                    elif hasattr(self.api_source, 'set_round_state'):
                        self.api_source.set_round_state('finalized', conversation_id=active_conv_id)
            except Exception as e:
                logger.warning(e)

            try:
                final_msgs = self.api_source.get_history_as_messages() if self.api_source else []
                _debug_api_msgs("finally_final_history", final_msgs)
                self.messages_signal.emit(final_msgs if final_msgs else [])
            except Exception as e:
                logger.warning(e)

            try:
                self.api_round_state_signal.emit({
                    'conversation_id': active_conv_id,
                    'state': 'finalized',
                    'loop_count': int(loop_result.get('loop_count', 0) or 0) if isinstance(loop_result, dict) else 0,
                    'selected_protocols': list(loop_result.get('selected_protocols') or []) if isinstance(loop_result, dict) else [],
                    'trace_id': (get_current_trace().trace_id if get_current_trace() else ""),
                    'round_id': (get_current_trace().round_id if get_current_trace() else ""),
                })
                probe("api_finalized", level="info", side="worker", conv_id=active_conv_id,
                      loop_count=int(loop_result.get('loop_count', 0) or 0) if isinstance(loop_result, dict) else 0)
            except Exception as e:
                logger.warning(e)

            self._api_streaming = False
            self._update_ai_state("idle")
            self._notify_daemon_reply_completed("api", chat_id=active_conv_id)

    def _handle_api_send_stream(self, text: str):
        """异步流式发送入口"""
        if self._api_streaming:
            self.safe_emit_status("⚠️ 流式发送中，请稍候")
            return

        # 检查流式桥接是否已初始化
        if not self.stream_bridge or not self.stream_bridge._handler:
            self.safe_emit_status("⚠️ 流式处理器未初始化，请稍候")
            return

        def on_status(chunk):
            # 兼容 StreamChunk 对象与 dict payload（远程链路）
            if isinstance(chunk, dict):
                status_raw = str(chunk.get("status", "") or "").lower()
            else:
                status_obj = getattr(chunk, "status", "")
                try:
                    status_raw = str(status_obj.value).lower()
                except Exception:
                    status_raw = str(status_obj).lower()

            completed_statuses = {
                str(StreamStatus.COMPLETED.value).lower(),
                "completed",
            }
            terminal_error_statuses = {
                str(StreamStatus.CANCELLED.value).lower(),
                str(StreamStatus.ERROR.value).lower(),
                "cancelled",
                "error",
            }

            if status_raw in completed_statuses or status_raw in terminal_error_statuses:
                try:
                    self.stream_bridge.stream_status_signal.disconnect(on_status)
                except RuntimeError:
                    pass
                except Exception as e:
                    logger.warning(e)

                if status_raw in completed_statuses:
                    try:
                        if self.api_source and hasattr(self.api_source, 'set_round_state'):
                            self.api_source.set_round_state('detecting_tools')
                    except Exception as e:
                        logger.warning(e)

                    try:
                        threading.Thread(target=self._continue_api_round_after_stream, daemon=True).start()
                    except Exception as e:
                        logger.warning(e)
                        self._api_streaming = False
                        self._update_ai_state("idle")
                    return

                self._api_streaming = False
                self._update_ai_state("idle")

        self._update_ai_state("busy")
        self._api_streaming = True
        try:
            self.stream_bridge.stream_status_signal.connect(on_status, type=0)  # AutoConnection
            self.stream_bridge.start_stream(text)

            # 轻微延迟后回显：由 api_source.send_message_stream 负责写入 user，避免重复入库
            try:
                if self.api_source:
                    time.sleep(0.08)
                    msgs_pre = self.api_source.get_history_as_messages()
                    self.messages_signal.emit(msgs_pre if msgs_pre else [])
            except Exception as e:
                logger.warning(e)
        except Exception as e:
            self._api_streaming = False
            self._update_ai_state("idle")
            self.safe_emit_status(f"❌ 流式发送启动失败: {e}")

    def _handle_api_send(self, text: str):
        """处理API模式的消息发送（同步，在worker线程中执行）"""
        if hasattr(self.api_source, "has_active_conversation") and not self.api_source.has_active_conversation():
            self.safe_emit_status("⚠️ 当前没有可用的 API 对话，请先新建对话")
            self.messages_signal.emit([])
            self.context_status_signal.emit({})
            return

        self._update_ai_state("busy")
        self._api_streaming = True

        try:
            # 同步调用，获取完整回复
            profile = self.api_source.get_runtime_profile() if hasattr(self.api_source, "get_runtime_profile") else {}
            if profile.get("kind") == "browser_stateless":
                self.browser_stateless_bridge.handle_send(text, profile)
                return

            reply = self.api_source.send_message_sync(text)

            # 如果本次发生了 fallback 自动切换，给用户一个直觉提示
            fallback_event = getattr(self.api_source, "last_fallback_event", None)
            if fallback_event:
                from_name = self._get_api_profile_display_name(fallback_event.get("from", ""))
                to_name = self._get_api_profile_display_name(fallback_event.get("to", ""))
                self.safe_emit_status(f"⚠️ 当前模型调用失败，已自动切换备用模型：{from_name} → {to_name}")

            # 构建消息列表并发送给UI渲染
            msgs = self.api_source.get_history_as_messages()
            self.messages_signal.emit(msgs)

            # 工具闭环（由独立 conversation_loop 控制，worker 仅做桥接）
            from app.core.tool_runtime.conversation_loop import ToolConversationLoop
            loop_runner = ToolConversationLoop(
                api_source=self.api_source,
                tool_router=self.tool_router,
            )
            loop_result = loop_runner.run_api_loop(
                conversation_id=self.api_source.conv_store.active_id or "api_default"
            )

            msgs = loop_result.get('msgs') or self.api_source.get_history_as_messages()
            self.messages_signal.emit(msgs if msgs else [])
            try:
                self.api_round_state_signal.emit({
                    'conversation_id': self.api_source.conv_store.active_id if self.api_source and self.api_source.conv_store else 'api_default',
                    'state': 'finalized' if loop_result.get('round_finalized') else str((getattr(self.api_source, '_last_request_snapshot', {}) or {}).get('round_state', 'idle')),
                    'loop_count': int(loop_result.get('loop_count', 0) or 0),
                    'selected_protocols': list(loop_result.get('selected_protocols') or []),
                    'trace_id': (get_current_trace().trace_id if get_current_trace() else ""),
                    'round_id': (get_current_trace().round_id if get_current_trace() else ""),
                })
                probe("api_sync_finalized", level="info", side="worker",
                      loop_count=int(loop_result.get('loop_count', 0) or 0))
            except Exception as e:
                logger.warning(e)

            loop_count = int(loop_result.get('loop_count', 0) or 0)
            stopped_reason = str(loop_result.get('stopped_reason', '') or '')
            if loop_count > 0:
                if stopped_reason == 'max_rounds_reached':
                    self.safe_emit_status(f"⛔ 已达到最大自动续答轮数，停止继续调用（{loop_count} 轮）")
                else:
                    self.safe_emit_status(f"🤖 工具闭环完成，共自动续答 {loop_count} 轮")

            # 兼容旧 filename 协议代码块的暂存导出；不属于当前 tool/skill 主闭环
            try:
                self.process_batch(msgs)
            except Exception as e:
                logger.warning(e)

            # 发送上下文状态
            status = self.api_source.get_context_status()
            self.context_status_signal.emit(status)

        except Exception as e:
            self.safe_emit_status(f"❌ API调用失败: {e}")
        finally:
            self._api_streaming = False
            self._update_ai_state("idle")
            active_conv_id = (
                self.api_source.conv_store.active_id
                if self.api_source and self.api_source.conv_store and self.api_source.conv_store.active_id
                else ""
            )
            self._notify_daemon_reply_completed("api", chat_id=active_conv_id)

    def api_switch_conversation(self, conv_id: str, **kwargs):
        """API模式切换对话"""
        if not self.api_source:
            self._init_api_source()
        if not self.api_source:
            return

        ok = self.api_source.switch_conversation(conv_id)
        convs = self.api_source.get_conversations()
        self.sessions_signal.emit(convs)

        if ok:
            msgs = self.api_source.get_history_as_messages()
            self.messages_signal.emit(msgs if msgs else [])
            status = self.api_source.get_context_status()
            self.context_status_signal.emit(status)
            self.safe_emit_status(f"📂 切换到对话: {conv_id[:8]}")
            return

        # 切换失败：可能是点到了已删除/残留的对话项，进入兜底刷新
        if convs:
            try:
                msgs = self.api_source.get_history_as_messages()
                self.messages_signal.emit(msgs if msgs else [])
                status = self.api_source.get_context_status()
                self.context_status_signal.emit(status)
            except Exception:
                self.messages_signal.emit([])
                self.context_status_signal.emit({})
        else:
            self.messages_signal.emit([])
            self.context_status_signal.emit({})

        self.safe_emit_status("⚠️ 对话不存在或已删除，已刷新列表")

    def api_new_conversation(self, title: str = "新对话", **kwargs):
        """API模式新建对话"""
        if not self.api_source:
            self._init_api_source()
        if not self.api_source:
            return
        conv_id = self.api_source.create_conversation(title)
        convs = self.api_source.get_conversations()
        self.sessions_signal.emit(convs)
        msgs = self.api_source.get_history_as_messages()
        self.messages_signal.emit(msgs if msgs else [])
        status = self.api_source.get_context_status()
        self.context_status_signal.emit(status)
        self.safe_emit_status(f"✨ 新建对话: {title}")

    def api_delete_conversation(self, conv_id: str, **kwargs):
        """API模式删除对话"""
        if not self.api_source:
            self._init_api_source()
        if not self.api_source:
            return
        self.api_source.delete_conversation(conv_id)
        convs = self.api_source.get_conversations()
        self.sessions_signal.emit(convs)
        if convs:
            msgs = self.api_source.get_history_as_messages()
            self.messages_signal.emit(msgs if msgs else [])
            status = self.api_source.get_context_status()
            self.context_status_signal.emit(status)
        else:
            self.messages_signal.emit([])
            self.context_status_signal.emit({})
        self.safe_emit_status(f"🗑️ 已删除对话: {conv_id[:8]}")


    def api_rename_conversation(self, conv_id: str, title: str, **kwargs):
        """API模式重命名对话"""
        if not self.api_source:
            self._init_api_source()
        if not self.api_source:
            return

        ok = self.api_source.rename_conversation(conv_id, title)
        convs = self.api_source.get_conversations()
        self.sessions_signal.emit(convs)

        if hasattr(self.api_source, "has_active_conversation") and self.api_source.has_active_conversation():
            msgs = self.api_source.get_history_as_messages()
            self.messages_signal.emit(msgs if msgs else [])
            status = self.api_source.get_context_status()
            self.context_status_signal.emit(status)
        else:
            self.messages_signal.emit([])
            self.context_status_signal.emit({})

        if ok:
            self.safe_emit_status(f"✏️ 已重命名对话: {title}")
        else:
            self.safe_emit_status("⚠️ 重命名失败：对话不存在")


    def api_pin_conversation(self, conv_id: str, **kwargs):
        """API模式置顶对话"""
        if not self.api_source:
            self._init_api_source()
        if not self.api_source:
            return
        ok = self.api_source.set_conversation_pinned(conv_id, True)
        convs = self.api_source.get_conversations()
        self.sessions_signal.emit(convs)
        if ok:
            self.safe_emit_status("📌 已置顶对话")
        else:
            self.safe_emit_status("⚠️ 置顶失败：对话不存在")

    def api_unpin_conversation(self, conv_id: str, **kwargs):
        """API模式取消置顶对话"""
        if not self.api_source:
            self._init_api_source()
        if not self.api_source:
            return
        ok = self.api_source.set_conversation_pinned(conv_id, False)
        convs = self.api_source.get_conversations()
        self.sessions_signal.emit(convs)
        if ok:
            self.safe_emit_status("📍 已取消置顶")
        else:
            self.safe_emit_status("⚠️ 取消置顶失败：对话不存在")


    def api_set_conversation_model_usage(self, conv_id: str, usage=None, **kwargs):
        """设置单个 API 对话使用的 Profile/Chain；usage=None 表示使用全局默认。"""
        return self.api_conversation_bridge.set_model_usage(conv_id, usage)

