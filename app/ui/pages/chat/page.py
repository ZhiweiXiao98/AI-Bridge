# filename: app/ui/pages/chat/page.py
import time
import os
import json

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QSplitter, QMessageBox, QApplication, QStackedWidget, QPushButton, QHBoxLayout, QFrame, QTabWidget, QGraphicsOpacityEffect, QLabel, QSizePolicy)
from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve, QPoint, QRect, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QPainter, QBrush, QPen

from .header import ChatHeader
from .session_list import SessionList
from .api_session_list import APISessionList
from .input_area import InputArea
from .message_area import MessageArea
from .status_bar import ApiModelUsageBar, BrowserProjectBar
from .api_skill_references import ApiSkillReferenceHandler
from .services.message_window_service import MessageWindowService
from app.ui.components.chat import ChatBubble
from app.core.config import ConfigManager
from app.core.browser_sync import ChatProjectionReducer
from app.core.app_constants import UI_SIZES
from app.ui.theme import theme_manager
from app.ui.components.collapsible_sidebar import CollapsibleSideBar
from app.core.logging import get_logger
from app.core.debug import probe

logger = get_logger("app.ui.chat_page", side="ui")


class ChatPage(QWidget):
    request_focus = Signal()

    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        cfg = ConfigManager.load()
        self.message_window_service = MessageWindowService(
            default_turns=int(cfg.get('chat_message_load_turns', 200)),
            step_turns=int(cfg.get('chat_message_load_step_turns', 50)),
        )
        self._browser_all_messages = []
        # Keep the complete history independently of MessageArea's visible window.
        self._browser_message_projection = ChatProjectionReducer()
        self._browser_message_projection.set_resync_callback(self._request_browser_resync)
        self._api_all_messages = []
        self._api_approval_dialog = None
        self._api_pending_approval = None
        self._api_closed_requests = set()
        self._api_answered_approvals = set()
        self.api_skill_references = ApiSkillReferenceHandler(self)
        self.init_ui()
        self.connect_signals()
        self.sidebar_expanded = True
        self.last_sidebar_width = UI_SIZES["default_sidebar_width"]
        self.safety_timer = QTimer(self)
        self.safety_timer.setSingleShot(True)
        self.safety_timer.timeout.connect(self.reset_fix_btn)
        self.is_switching = False
        self.current_mode = "browser"
        self._api_round_state = "idle"
        self._api_round_payload = {}
        self._api_tool_status_by_id = {}
        self._browser_round_state = "idle"
        self._api_active_conv_id = ""
        self._api_conversations_by_id = {}

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = ChatHeader()
        layout.addWidget(self.header)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setStyleSheet(
            "QSplitter::handle { background-color: #374151; }"
            "QSplitter::handle:hover { background-color: #6366F1; }"
        )

        # === Left: QTabWidget (Browser / API) ===
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.session_list = SessionList()
        self.api_session_list = APISessionList()
        self.session_tabs.addTab(self.session_list, "🌐 Browser")
        self.session_tabs.addTab(self.api_session_list, "🤖 API")
        self.session_tabs.currentChanged.connect(self._on_tab_changed)

        self.side_container = CollapsibleSideBar(self.session_tabs, direction='left')
        self.side_container.request_toggle.connect(self.toggle_sidebar)
        self.splitter.addWidget(self.side_container)

        # === Right ===
        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        # ===== 内部子分页，用于Browser/API消息区和输入区分离 =====
        self.inner_stack = QStackedWidget()
        self.inner_stack.setMinimumWidth(0)
        self.inner_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        self.browser_page = QWidget()
        self.browser_page.setMinimumWidth(0)
        self.browser_page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        browser_layout = QVBoxLayout(self.browser_page)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        self.browser_controls = QFrame()
        browser_controls_layout = QHBoxLayout(self.browser_controls)
        browser_controls_layout.setContentsMargins(8, 6, 8, 6)
        self.browser_settings_btn = QPushButton("连接设置")
        self.browser_reconnect_btn = QPushButton("重新连接")
        self.browser_stop_btn = QPushButton("停止生成")
        for button in (self.browser_settings_btn, self.browser_reconnect_btn, self.browser_stop_btn):
            browser_controls_layout.addWidget(button)
        browser_controls_layout.addStretch()
        local_browser = os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1"
        self.browser_controls.setVisible(local_browser)
        self.browser_settings_btn.clicked.connect(self._configure_local_browser)
        self.browser_reconnect_btn.clicked.connect(self._reconnect_local_browser)
        self.browser_stop_btn.clicked.connect(self._stop_browser_request)
        browser_layout.addWidget(self.browser_controls)
        self.browser_msg_area = MessageArea()
        self.browser_input_area = InputArea()
        self.browser_msg_area.setMinimumWidth(0)
        self.browser_input_area.setMinimumWidth(0)
        self.browser_msg_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.browser_input_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.browser_splitter = QSplitter(Qt.Orientation.Vertical)
        self.browser_splitter.setMinimumWidth(0)
        self.browser_splitter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.browser_splitter.setHandleWidth(4)
        self.browser_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #1E293B; height: 4px; }"
            "QSplitter::handle:hover { background-color: #6366F1; }"
        )
        self.browser_input_panel = QWidget()
        self.browser_input_panel.setMinimumWidth(0)
        self.browser_input_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        browser_input_panel_layout = QVBoxLayout(self.browser_input_panel)
        browser_input_panel_layout.setContentsMargins(0, 0, 0, 0)
        browser_input_panel_layout.setSpacing(0)
        self.browser_project_bar = BrowserProjectBar()
        self.browser_project_bar.setMinimumWidth(0)
        self.browser_project_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        browser_input_panel_layout.addWidget(self.browser_input_area)
        browser_input_panel_layout.addWidget(self.browser_project_bar)
        self.browser_splitter.addWidget(self.browser_msg_area)
        self.browser_splitter.addWidget(self.browser_input_panel)
        self.browser_splitter.setStretchFactor(0, 8)
        self.browser_splitter.setStretchFactor(1, 2)
        self.browser_splitter.setSizes([700, 180])
        browser_layout.addWidget(self.browser_splitter)

        self.api_page = QWidget()
        self.api_page.setMinimumWidth(0)
        self.api_page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        api_layout = QVBoxLayout(self.api_page)
        api_layout.setContentsMargins(0, 0, 0, 0)
        self.api_selection_toolbar = QFrame()
        self.api_selection_toolbar.setVisible(False)
        api_toolbar_layout = QHBoxLayout(self.api_selection_toolbar)
        api_toolbar_layout.setContentsMargins(8, 6, 8, 6)
        self.api_selection_label = QLabel('已选中 0 条消息')
        self.api_delete_selected_btn = QPushButton('🗑️ 删除')
        self.api_delete_selected_btn.setEnabled(False)
        self.api_cancel_selection_btn = QPushButton('取消')
        api_toolbar_layout.addWidget(self.api_selection_label)
        api_toolbar_layout.addStretch()
        api_toolbar_layout.addWidget(self.api_delete_selected_btn)
        api_toolbar_layout.addWidget(self.api_cancel_selection_btn)
        api_layout.addWidget(self.api_selection_toolbar)
        self.api_stop_btn = QPushButton("停止当前请求")
        self.api_stop_btn.setEnabled(False)
        self.api_stop_btn.clicked.connect(self._stop_api_request)
        api_layout.addWidget(self.api_stop_btn)
        self.api_msg_area = MessageArea()
        self.api_input_area = InputArea()
        self.api_msg_area.setMinimumWidth(0)
        self.api_input_area.setMinimumWidth(0)
        self.api_msg_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.api_input_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.api_input_panel = QWidget()
        self.api_input_panel.setMinimumWidth(0)
        self.api_input_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        api_input_panel_layout = QVBoxLayout(self.api_input_panel)
        api_input_panel_layout.setContentsMargins(0, 0, 0, 0)
        api_input_panel_layout.setSpacing(0)
        self.api_model_usage_bar = ApiModelUsageBar()
        self.api_model_usage_bar.setMinimumWidth(0)
        self.api_model_usage_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        api_input_panel_layout.addWidget(self.api_input_area)
        api_input_panel_layout.addWidget(self.api_model_usage_bar)
        self.api_splitter = QSplitter(Qt.Orientation.Vertical)
        self.api_splitter.setMinimumWidth(0)
        self.api_splitter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.api_splitter.setHandleWidth(4)
        self.api_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #1E293B; height: 4px; }"
            "QSplitter::handle:hover { background-color: #6366F1; }"
        )
        self.api_splitter.addWidget(self.api_msg_area)
        self.api_splitter.addWidget(self.api_input_panel)
        self.api_splitter.setStretchFactor(0, 8)
        self.api_splitter.setStretchFactor(1, 2)
        self.api_splitter.setSizes([700, 180])
        api_layout.addWidget(self.api_splitter)

        self.inner_stack.addWidget(self.browser_page)
        self.inner_stack.addWidget(self.api_page)

        self.v_splitter.setHandleWidth(4)
        self.v_splitter.setMinimumWidth(0)
        self.v_splitter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.v_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #1E293B; height: 4px; }"
            "QSplitter::handle:hover { background-color: #6366F1; }"
        )
        self.v_splitter.addWidget(self.inner_stack)
        self.v_splitter.setStretchFactor(0, 1)

        self.splitter.addWidget(self.v_splitter)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setSizes([UI_SIZES["default_sidebar_width"], 900])
        layout.addWidget(self.splitter)

        # Issue 3: 建议栏显示/隐藏时调整 splitter 给输入区额外空间
        self._suggestion_extra = 0
        self.browser_input_area.extra_space_requested.connect(
            lambda px: self._adjust_splitter_for_suggestions(self.browser_splitter, px)
        )
        self.api_input_area.extra_space_requested.connect(
            lambda px: self._adjust_splitter_for_suggestions(self.api_splitter, px)
        )

        self._apply_tab_theme()
        theme_manager.theme_changed.connect(self._apply_tab_theme)

    def _adjust_splitter_for_suggestions(self, splitter, extra_px):
        """建议栏显示时扩大输入面板，隐藏时恢复。"""
        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        prev_extra = self._suggestion_extra
        if extra_px > 0 and prev_extra == 0:
            # 扩大输入面板
            delta = extra_px
            sizes[0] = max(100, sizes[0] - delta)
            sizes[1] = sizes[1] + delta
            self._suggestion_extra = delta
        elif extra_px == 0 and prev_extra > 0:
            # 恢复
            sizes[0] = sizes[0] + prev_extra
            sizes[1] = max(100, sizes[1] - prev_extra)
            self._suggestion_extra = 0
        else:
            return
        splitter.setSizes(sizes)

    def _apply_tab_theme(self):
        p = theme_manager.get_palette()
        self.session_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background-color: {p.BG_SECONDARY}; color: {p.TEXT_SECONDARY};
                padding: 5px 10px; border: none; border-bottom: 2px solid transparent;
                font-size: 11px;
            }}
            QTabBar::tab:selected {{
                color: {p.TEXT_PRIMARY}; border-bottom: 2px solid {p.ACCENT_PRIMARY};
            }}
            QTabBar::tab:hover {{ color: {p.TEXT_PRIMARY}; }}
        """)

    def _on_tab_changed(self, index):
        mode = "browser" if index == 0 else "api"
        self.on_mode_switch(mode)

    def toggle_sidebar(self):
        current_sizes = self.splitter.sizes()
        left_w = current_sizes[0]
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(300)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        if self.sidebar_expanded:
            self.last_sidebar_width = left_w
            self.side_container.set_content_visible(False)
            self.anim.setStartValue(left_w)
            self.anim.setEndValue(16)
        else:
            target_w = self.last_sidebar_width if self.last_sidebar_width > 100 else UI_SIZES["default_sidebar_width"]
            self.side_container.set_content_visible(True)
            self.anim.setStartValue(left_w)
            self.anim.setEndValue(target_w)
        self.anim.valueChanged.connect(self._update_splitter_width)
        self.anim.start()
        self.sidebar_expanded = not self.sidebar_expanded

    def _update_splitter_width(self, width):
        total = sum(self.splitter.sizes())
        self.splitter.setSizes([int(width), total - int(width)])

    def get_active_input_splitter(self):
        if getattr(self, "current_mode", "browser") == "api":
            return self.api_splitter
        return self.browser_splitter

    def get_input_height_state(self):
        try:
            splitter = self.get_active_input_splitter()
            return splitter.sizes()
        except Exception:
            return [700, 180]

    def set_input_height_state(self, sizes):
        try:
            if not isinstance(sizes, (list, tuple)) or len(sizes) < 2:
                return
            normalized = [int(sizes[0]), int(sizes[1])]
            if normalized[0] <= 0 or normalized[1] <= 0:
                return
            self.browser_splitter.setSizes(normalized)
            self.api_splitter.setSizes(normalized)
        except Exception as e:
            logger.warning(e)

    def connect_signals(self):
        self.browser_input_area.worker = self.worker
        self.api_input_area.worker = self.worker
        self.worker.input_area = self.browser_input_area

        self.worker.status_signal.connect(self.header.set_status)
        self.worker.sessions_signal.connect(self._dispatch_sessions)
        self.worker.batch_complete_signal.connect(self.reset_fix_btn)
        self.worker.occupancy_signal.connect(self.session_list.update_occupancy)

        if hasattr(self.worker, "mode_changed_signal"):
            self.worker.mode_changed_signal.connect(self.header.set_mode)

        if hasattr(self.worker, "latency_signal"):
            self.worker.latency_signal.connect(self.header.update_latency)

        if hasattr(self.worker, "request_wake_up"):
            self.header.request_wake.connect(self.worker.request_wake_up)
        self.header.request_fix.connect(self.on_fix_clicked)
        self.header.mode_switch_clicked.connect(self.on_mode_switch)
        self.header.license_changed.connect(lambda t: self.header.set_status(f"切换环境: {t}"))
        self.header.resume_sync_clicked.connect(self.resume_sync)
        # 新增分模式消息和输入信号
        self.worker.messages_signal.connect(self._on_mode_messages)
        self.worker.status_signal.connect(self.browser_input_area.log_message.emit)
        self.worker.status_signal.connect(self.api_input_area.log_message.emit)
        if hasattr(self.worker, "ai_state_signal"):
            self.worker.ai_state_signal.connect(self.browser_input_area.update_ai_state)
            self.worker.ai_state_signal.connect(self.api_input_area.update_ai_state)
            self.worker.ai_state_signal.connect(self._on_browser_ai_state)
        if hasattr(self.worker, "pending_message_consumed_signal"):
            self.worker.pending_message_consumed_signal.connect(self.browser_input_area.on_pending_consumed)

        if hasattr(self.worker, "subagent_suggestion_signal"):
            self.worker.subagent_suggestion_signal.connect(self._on_subagent_suggestion)

        if os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1":
            self.browser_input_area.local_browser_submit = self._submit_local_browser
            browser_results = getattr(self.worker, "browser_send_result_signal", None)
            if browser_results is not None:
                browser_results.connect(self.browser_input_area.on_browser_send_result)
        self.browser_input_area.request_send_text.connect(lambda t: self._send_text_in_mode("browser", t))
        self.api_input_area.request_send_text.connect(lambda t: self._send_text_in_mode("api", t))
        self.browser_input_area.request_send_compound.connect(lambda text, files: self._send_compound_in_mode("browser", text, files))
        self.api_input_area.request_send_compound.connect(lambda text, files: self._send_compound_in_mode("api", text, files))
        self.api_input_area.input_box.textChanged.connect(self.api_skill_references.update_suggestions_for_input)
        self.browser_input_area.log_message.connect(self.header.set_status)
        self.api_input_area.log_message.connect(self.header.set_status)

        # 流式API信号监听
        stream_bridge = getattr(self.worker, 'stream_bridge', None)
        _has_stream_bridge = (
            stream_bridge is not None
            and not callable(stream_bridge)
            and hasattr(stream_bridge, 'stream_chunk_signal')
            and hasattr(stream_bridge, 'stream_status_signal')
        )
        chunk_sig = getattr(self.worker, "api_stream_chunk_signal", None)
        status_sig = getattr(self.worker, "api_stream_status_signal", None)
        _has_remote_signals = (
            chunk_sig is not None and hasattr(chunk_sig, 'connect')
            and status_sig is not None and hasattr(status_sig, 'connect')
        )
        if _has_stream_bridge or _has_remote_signals:
            print(f"[DBG][ChatPage] stream wiring enabled | local_bridge={_has_stream_bridge} remote_signals={_has_remote_signals}")
            from app.ui.pages.chat.chat_page_stream import ChatPageStreamManager
            from app.ui.pages.chat.message_area_stream import MessageAreaStreamManager
            self._api_stream_manager = MessageAreaStreamManager(self.api_msg_area)
            self._chat_page_stream = ChatPageStreamManager(self.api_msg_area)
            self._chat_page_stream.set_active_conv_hook(lambda: getattr(self, '_api_active_conv_id', None))
            self._chat_page_stream.set_stream_manager(self._api_stream_manager)
            if not _has_remote_signals and _has_stream_bridge:
                print("[DBG][ChatPage] connect stream via worker.stream_bridge")
                self._chat_page_stream.connect_worker_signals(stream_bridge)
            else:
                print("[DBG][ChatPage] connect stream via remote worker signals")
                self.worker.api_stream_chunk_signal.connect(self._chat_page_stream._on_stream_chunk)
                self.worker.api_stream_status_signal.connect(self._chat_page_stream._on_stream_status)

        # Browser session list signals
        self.session_list.session_selected.connect(self.on_session_clicked)
        if hasattr(self.worker, "set_session_role"):
            self.session_list.role_assigned.connect(self.worker.set_session_role)

        # API session list signals
        runtime_options = getattr(self.worker, "agent_runtime_options_signal", None)
        if runtime_options is not None and hasattr(runtime_options, "connect"):
            runtime_options.connect(self.api_session_list.set_runtime_options)
            QTimer.singleShot(0, self.worker.get_agent_runtime_options)
        approvals = getattr(self.worker, "agent_runtime_approval_signal", None)
        if approvals is not None and hasattr(approvals, "connect"):
            approvals.connect(self._on_agent_tool_approval)
        self.api_session_list.session_selected.connect(self.on_api_session_clicked)
        self.api_session_list.new_conversation.connect(self._on_api_new_conversation)
        self.api_session_list.delete_conversation.connect(self._on_api_delete_conversation)
        self.api_session_list.rename_conversation.connect(self._on_api_rename_conversation)
        self.api_session_list.pin_conversation.connect(self._on_api_pin_conversation)
        self.api_session_list.unpin_conversation.connect(self._on_api_unpin_conversation)
        self.api_model_usage_bar.usage_changed.connect(self._on_api_model_usage_changed)

        self.api_msg_area.request_enter_multi_select_mode.connect(self._enter_api_multi_select_mode)
        self.api_msg_area.selection_count_changed.connect(self._on_api_selection_count_changed)
        self.api_delete_selected_btn.clicked.connect(self._delete_selected_api_messages)
        self.api_cancel_selection_btn.clicked.connect(self._cancel_api_multi_select_mode)
        self.browser_msg_area.request_load_more.connect(lambda: self._load_more_for_mode('browser'))
        self.api_msg_area.request_load_more.connect(lambda: self._load_more_for_mode('api'))
        if hasattr(self.browser_msg_area, 'request_resync'):
            self.browser_msg_area.request_resync.connect(self._request_browser_resync)
        if hasattr(self.worker, 'api_messages_deleted_signal'):
            self.worker.api_messages_deleted_signal.connect(self._on_api_messages_deleted)
        if hasattr(self.worker, 'api_round_state_signal'):
            self.worker.api_round_state_signal.connect(self._on_api_round_state_changed)
        if hasattr(self.worker, "context_status_signal"):
            self.worker.context_status_signal.connect(self._on_api_context_status_changed)
        if hasattr(self.worker, 'tool_status_signal'):
            self.worker.tool_status_signal.connect(self._on_tool_status_event)
        elif hasattr(self.worker, 'api_stream_status_signal'):
            self.worker.api_stream_status_signal.connect(self._on_tool_status_event)

        # 切换时把日志转发到 header 状态栏（提前连接，不依赖 docker_manager 就绪）
        self.browser_project_bar.log_message.connect(self.header.set_status)
        self.api_model_usage_bar.log_message.connect(self.header.set_status)
        # 环境切换走 RPC：env_changed(mode, path) -> worker.set_exec_mode(mode, path)
        self.browser_project_bar.env_changed.connect(self.worker.set_exec_mode)
        self.api_model_usage_bar.env_changed.connect(self.worker.set_exec_mode)
        if hasattr(self.worker, "switch_project"):
            self.browser_project_bar.project_changed.connect(self.worker.switch_project)
            self.api_model_usage_bar.project_changed.connect(self.worker.switch_project)
        # 绑定沙盒环境栏的 docker_manager，并同步初始状态
        QTimer.singleShot(0, self._bind_sandbox_bars)

    def _bind_sandbox_bars(self):
        """从 config 读当前执行环境配置，同步到两个状态栏的环境按钮。
        切换走 RPC（env_changed -> worker.set_exec_mode），无需本地 docker_manager 实例。
        """
        try:
            from app.core.config import ConfigManager
            cfg = ConfigManager.load()
            mode = cfg.get('sandbox_exec_mode', 'docker')
            python = cfg.get('sandbox_local_python', '')
            self.browser_project_bar.sync_exec_state(mode, python)
            self.api_model_usage_bar.sync_exec_state(mode, python)
            logger.info(f"[SandboxEnvBar] 初始状态同步完成: mode={mode}, python={python or '系统默认'}")
        except Exception as e:
            logger.warning(f"[SandboxEnvBar] 初始状态同步失败: {e}")

    def _dispatch_sessions(self, sessions):
        """根据数据内容分发会话列表到对应组件。

        设计原则（2026-03-20）：
        - 不追求 Browser / API 短期完全对称
        - 不触碰 Browser 模式专属状态机
        - API 问题优先通过独立小路修复
        """
        if not isinstance(sessions, list):
            return

        # 空列表：仅为 API 模式/Tab 开独立小路，避免误伤 Browser 主链路
        if not sessions:
            current_tab = self.session_tabs.currentIndex() if hasattr(self, 'session_tabs') else 0
            current_mode = getattr(self, 'current_mode', 'browser')
            if current_mode == 'api' or current_tab == 1:
                self._api_conversations_by_id = {}
                self._api_active_conv_id = ""
                self._sync_api_model_usage_bar()
                self.api_model_usage_bar.set_context_status({})
                self.api_session_list.update_sessions([])
                self._refresh_agent_runtime()
            return

        # 非空列表仍按现有数据特征判断，尽量不动 Browser 老路
        sample = sessions[0]
        if "id" in sample and "index" not in sample:
            self._api_conversations_by_id = {str(c.get("id", "")): c for c in sessions if isinstance(c, dict)}
            active = next((c for c in sessions if isinstance(c, dict) and c.get("active")), None)
            if active:
                self._api_active_conv_id = str(active.get("id", "") or "")
            elif self._api_active_conv_id not in self._api_conversations_by_id:
                self._api_active_conv_id = ""
            if active or not self._api_active_conv_id:
                self._sync_api_model_usage_bar()
            self.api_session_list.update_sessions(sessions)
            self._refresh_agent_runtime()
        else:
            self.session_list.update_list(sessions)

    def _refresh_agent_runtime(self):
        for name in ("get_agent_runtime_options", "get_agent_runtime_state"):
            callback = getattr(self.worker, name, None)
            if callable(callback):
                callback()

    def _api_runtime_busy(self):
        conv = getattr(self, "_api_conversations_by_id", {}).get(self._api_active_conv_id, {})
        runtime = self._api_round_payload.get("diagnostics", {}).get("runtime") or conv.get("runtime")
        return runtime == "pi" and self._api_round_state not in {"idle", "finalized", "failed", "cancelled"}

    def _on_api_new_conversation(self, title):
        if self._api_runtime_busy():
            self.header.set_status("请先停止并等待当前 Pi 请求结束，再新建对话")
            return
        runtime = self.api_session_list.selected_runtime()
        if runtime and hasattr(self.worker, "api_new_conversation"):
            self.worker.api_new_conversation(title, runtime=runtime)

    def _stop_api_request(self):
        payload = getattr(self, "_api_round_payload", {})
        if not self.api_stop_btn.isEnabled():
            return
        self._dismiss_agent_tool_approval()
        self.worker.api_cancel(conversation_id=payload.get("conversation_id") or self._api_active_conv_id,
                               request_id=payload.get("request_id"))
        self.api_stop_btn.setEnabled(False)
        self.header.set_status("正在停止，等待工具结束…")

    def _dismiss_agent_tool_approval(self):
        dialog = self._api_approval_dialog
        pending = self._api_pending_approval
        if pending:
            self._api_answered_approvals.add((pending["request_id"], pending["call_id"]))
        self._api_approval_dialog = None
        self._api_pending_approval = None
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()

    def _on_agent_tool_approval(self, payload):
        if not isinstance(payload, dict) or not all(payload.get(key) for key in ("conversation_id", "request_id", "call_id")):
            return
        if self._api_active_conv_id and payload["conversation_id"] != self._api_active_conv_id:
            return
        if payload["request_id"] in self._api_closed_requests or (payload["request_id"], payload["call_id"]) in self._api_answered_approvals:
            return
        active_request = self._api_round_payload.get("request_id")
        if active_request and active_request != payload["request_id"] and self._api_round_state not in {"idle", "finalized", "failed", "cancelled"}:
            return
        pending = self._api_pending_approval or {}
        if all(pending.get(key) == payload[key] for key in ("conversation_id", "request_id", "call_id")):
            return
        self._dismiss_agent_tool_approval()
        self._api_pending_approval = dict(payload)
        message = f"Pi 请求执行工具：{payload.get('name', '')}\n项目：{payload.get('project_root', '')}\n\n"
        arguments = json.dumps(payload.get("arguments", {}), ensure_ascii=False, indent=2)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("批准本次工具执行？")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message + "请核对以下完整参数后再批准")
        dialog.setDetailedText(arguments)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._api_approval_dialog = dialog

        def answer(result):
            if self._api_approval_dialog is not dialog:
                return  # Timeout, navigation, stop or a newer request dismissed it.
            self._api_approval_dialog = None
            self._api_pending_approval = None
            self._api_answered_approvals.add((payload["request_id"], payload["call_id"]))
            self.worker.api_approve_tool(payload["conversation_id"], payload["request_id"], payload["call_id"],
                                         result == QMessageBox.StandardButton.Yes)
            dialog.deleteLater()

        dialog.finished.connect(answer)
        for button in dialog.buttons():
            if dialog.buttonRole(button) == QMessageBox.ButtonRole.ActionRole:
                button.click()  # Expand the built-in scrollable, read-only details.
                break
        dialog.show()

    def _on_api_delete_conversation(self, conv_id):
        reply = QMessageBox.question(self, "删除对话", f"确认删除此对话？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if hasattr(self.worker, "api_delete_conversation"):
                self.worker.api_delete_conversation(conv_id)

    def _on_api_rename_conversation(self, conv_id, new_title):
        if hasattr(self.worker, "api_rename_conversation"):
            self.worker.api_rename_conversation(conv_id, new_title)

    def _on_api_pin_conversation(self, conv_id):
        if hasattr(self.worker, "api_pin_conversation"):
            self.worker.api_pin_conversation(conv_id)

    def _on_api_unpin_conversation(self, conv_id):
        if hasattr(self.worker, "api_unpin_conversation"):
            self.worker.api_unpin_conversation(conv_id)

    def _sync_api_model_usage_bar(self):
        conv = self._api_conversations_by_id.get(str(self._api_active_conv_id or ""), {})
        usage = conv.get("model_usage") if isinstance(conv, dict) else None
        self.api_model_usage_bar.set_conversation(self._api_active_conv_id, usage)

    def _on_api_model_usage_changed(self, usage):
        conv_id = str(self._api_active_conv_id or "").strip()
        if not conv_id:
            self.header.set_status("请先选择一个 API 对话")
            self._sync_api_model_usage_bar()
            return

        if hasattr(self.worker, "api_set_conversation_model_usage"):
            self.worker.api_set_conversation_model_usage(conv_id, usage)
        elif hasattr(self.worker, "set_conversation_model_usage"):
            self.worker.set_conversation_model_usage(conv_id, usage)

        conv = self._api_conversations_by_id.setdefault(conv_id, {})
        conv["model_usage"] = usage
        self.header.set_status("已更新本对话模型来源")

    def _on_api_context_status_changed(self, payload):
        if not isinstance(payload, dict):
            return
        conv_id = str(payload.get("conversation_id") or "").strip()
        if conv_id:
            self._api_active_conv_id = conv_id
            conv = self._api_conversations_by_id.setdefault(conv_id, {})
            if "conversation_model_usage" in payload:
                conv["model_usage"] = payload.get("conversation_model_usage")
                self._sync_api_model_usage_bar()
        self.api_model_usage_bar.set_context_status(payload)

    def _enter_api_multi_select_mode(self, initial_index):
        active = self._api_conversations_by_id.get(self._api_active_conv_id, {})
        if active.get("runtime") == "pi":
            self.header.set_status("Pi 历史是只读投影；不能用旧版历史编辑改变运行上下文")
            return
        self.api_selection_toolbar.setVisible(True)
        self.api_msg_area.enter_multi_select_mode(initial_index)

    def _cancel_api_multi_select_mode(self):
        self.api_msg_area.exit_multi_select_mode()
        self.api_selection_toolbar.setVisible(False)

    def _on_api_selection_count_changed(self, count):
        self.api_selection_label.setText(f'已选中 {count} 条消息')
        self.api_delete_selected_btn.setEnabled(count > 0)
        if count <= 0 and not self.api_msg_area.selection_mode:
            self.api_selection_toolbar.setVisible(False)

    def _delete_selected_api_messages(self):
        indexes = self.api_msg_area.get_selected_indexes()
        if not indexes:
            return
        reply = QMessageBox.question(self, '删除消息', f'确认删除选中的 {len(indexes)} 条消息？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if hasattr(self.worker, 'delete_api_messages'):
            self.worker.delete_api_messages(indexes)

    def _on_api_messages_deleted(self, payload):
        if not isinstance(payload, dict):
            return
        removed = int(payload.get('removed', 0) or 0)
        if removed <= 0:
            return
        self.api_msg_area.clear_selected_indexes()
        self.api_selection_toolbar.setVisible(True)

    def _load_more_for_mode(self, mode):
        self.message_window_service.expand_for_mode(mode)
        if mode == 'api':
            visible, has_more = self.message_window_service.slice_messages('api', self._api_all_messages)
            incoming_id = visible[0].get('id', '') if visible else ''
            self.api_msg_area.render_messages(visible, incoming_id)
            self.api_msg_area.set_load_more_visible(has_more)
            return
        visible, has_more = self.message_window_service.slice_messages('browser', self._browser_all_messages)
        incoming_id = visible[0].get('id', '') if visible else ''
        # Expanding the local window is not a replay of an old Worker event.
        # Cached messages can carry different historical sequence numbers.
        window = [dict(msg, _seq=0, _event='conversation.snapshot') for msg in visible]
        self.browser_msg_area.render_messages(window, incoming_id)
        self.browser_msg_area.set_load_more_visible(has_more)

    def update_api_sessions(self, conversations):
        self.api_session_list.update_sessions(conversations)

    def handle_quick_apply(self, filename, content):
        reply = QMessageBox.question(self, "⚡ 极速应用", f"覆盖 {filename}？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.worker.manual_save(filename, content)
            if hasattr(self.worker, "do_server_apply"): self.worker.do_server_apply([filename])

    def handle_ignore_file(self, filename):
        cfg = ConfigManager.load()
        clean_name = filename.replace("\\", "/")
        if clean_name not in cfg.get("ignored_files", ""):
            cfg["ignored_files"] += f"\n{clean_name}"
            ConfigManager.save(cfg)

    def handle_discard_staging(self, filename, content):
        if hasattr(self.worker, "ignore_block_content"):
            self.worker.ignore_block_content(filename, content)
            self.log_status(f"🗑️ 已永久拉黑该版本指纹: {filename}")
        else:
            self.log_status("⚠️ Worker 版本过低")

    def handle_undiscard_staging(self, filename, content):
        if hasattr(self.worker, "unignore_block_content"):
            self.worker.unignore_block_content(filename, content)
            self.log_status(f"♻️ 已撤销拉黑: {filename}")
            self._remove_local_ignore(filename)
        else:
            self.log_status("⚠️ Worker 版本过低")

    def _remove_local_ignore(self, filename):
        cfg = ConfigManager.load()
        ignored = cfg.get("ignored_files", "")
        if not ignored: return
        target = filename.replace("\\", "/").strip().lower()
        new_lines = []
        for line in ignored.split("\n"):
            clean_line = line.strip().replace("\\", "/")
            if clean_line.lower() != target:
                new_lines.append(line)
        cfg["ignored_files"] = "\n".join(new_lines)
        ConfigManager.save(cfg)

    def handle_force_save(self, name, content):
        self.worker.manual_save(name, content)

    def on_set_snapshot(self, idx):
        self.worker.set_manual_snapshot(idx)

    def on_correct_turn(self, bubble, new_val):
        bubbles = []
        target_idx = -1
        mode = self.current_mode
        msg_area = self.browser_msg_area if mode == "browser" else self.api_msg_area
        scroll_layout = msg_area.scroll_layout
        for i in range(scroll_layout.count()):
            item = scroll_layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), ChatBubble):
                w = item.widget()
                bubbles.append(w)
                if w == bubble: target_idx = len(bubbles) - 1
        if target_idx != -1:
            total = len(bubbles)
            offset_from_end = total - 1 - target_idx
            new_max = new_val + offset_from_end
            self.log_status(f"🛠️ 气泡校准: Bubble[{target_idx}]={new_val} -> Max={new_max}")
            self.worker.set_manual_turn(new_max)

    def activate_staging_area(self, text):
        target = self.api_input_area if self.current_mode == "api" else self.browser_input_area
        target.show_staging(text)
        self.request_focus.emit()

    def log_status(self, text):
        self.header.set_status(text)

    def on_fix_clicked(self):
        self.header.set_fix_btn_state(False, "⏳ 修复中...")
        self.worker.request_fix_all()
        self.safety_timer.start(15000)

    def reset_fix_btn(self):
        self.header.set_fix_btn_state(True, "🛠️ 修复")
        self.safety_timer.stop()

    def _append_local_api_user_message(self, text):
        text = (text or "").strip()
        if not text:
            return
        conv_id = str(
            getattr(self, '_api_active_conv_id', '')
            or getattr(self.api_session_list, '_active_conv_id', '')
            or ''
        )
        local_msg = {
            "role": "User",
            "id": f"local_api_user_{int(time.time() * 1000)}",
            "source": "api",
            "conversation_id": conv_id,
            "segments": [{"type": "text", "content": text}],
        }
        self._api_all_messages = list(self._api_all_messages or [])
        self._api_all_messages.append(local_msg)
        visible, has_more = self.message_window_service.slice_messages('api', self._api_all_messages)
        self.api_msg_area.render_messages(visible, local_msg.get("id", ""))
        self.api_msg_area.flush_render()  # 确保本地气泡立刻同步渲染完毕，防止与后续的流式气泡产生顺序竞态
        self.api_msg_area.set_load_more_visible(has_more)

    def _submit_local_browser(self, text, attachments, request_id):
        if self.current_mode != "browser":
            return False
        if attachments:
            return bool(self.worker.send_compound(text, attachments, browser_request_id=request_id))
        return bool(self.worker.send_text("div.aa-chat-input textarea", text, browser_request_id=request_id))

    def _configure_local_browser(self):
        from app.ui.components.local_browser_settings import LocalBrowserSettingsDialog
        dialog = LocalBrowserSettingsDialog(self)
        if dialog.exec():
            self.header.set_status("浏览器设置已保存，请点重新连接")

    def _reconnect_local_browser(self):
        request = getattr(self.worker, "request_browser_reconnect", None)
        if callable(request):
            request()
            self.header.set_status("正在重新连接浏览器…")

    def _stop_browser_request(self):
        self.browser_input_area.cancel_queue()
        self.browser_input_area.cancel_local_browser_submission()
        cancel = getattr(self.worker, "browser_cancel", None)
        if callable(cancel):
            cancel()
            self.header.set_status("已请求网页停止生成，等待确认…")

    def on_mode_switch(self, mode):
        if self._api_runtime_busy():
            self.session_tabs.blockSignals(True)
            self.session_tabs.setCurrentIndex(1 if self.current_mode == "api" else 0)
            self.session_tabs.blockSignals(False)
            self.header.set_status("请先停止并等待当前 Pi 请求结束，再切换模式")
            return
        self._dismiss_agent_tool_approval()
        self.api_stop_btn.setEnabled(False)
        try:
            if hasattr(self, '_api_stream_manager') and self._api_stream_manager:
                self._api_stream_manager.reset_stream_ui()
        except Exception as e:
            logger.warning(e)
        self.current_mode = mode
        self._api_round_state = 'idle'
        self._api_round_payload = {}
        self._api_tool_status_by_id = {}
        self.api_msg_area.clear_runtime_status()
        if hasattr(self.worker, "switch_mode"):
            self.worker.switch_mode(mode)
        # 切换内部消息区分页
        if mode == "browser":
            self.inner_stack.setCurrentIndex(0)
            self.browser_msg_area.render_messages([], "")
        else:
            self.inner_stack.setCurrentIndex(1)
            self.api_msg_area.render_messages([], "")
        if mode == "api":
            self.api_model_usage_bar.reload_options()
            self.header.set_status("🤖 切换到 API 模式")
            if self.session_tabs.currentIndex() != 1:
                self.session_tabs.blockSignals(True)
                self.session_tabs.setCurrentIndex(1)
                self.session_tabs.blockSignals(False)
        else:
            self.header.set_status("🌐 切换到浏览器模式")
            if self.session_tabs.currentIndex() != 0:
                self.session_tabs.blockSignals(True)
                self.session_tabs.setCurrentIndex(0)
                self.session_tabs.blockSignals(False)

    def on_api_session_clicked(self, conv_id):
        if self._api_runtime_busy():
            self.header.set_status("请先停止并等待当前 Pi 请求结束，再切换会话")
            self.api_session_list.update_sessions(list(self._api_conversations_by_id.values()))
            return
        self._dismiss_agent_tool_approval()
        self.api_stop_btn.setEnabled(False)
        self.message_window_service.reset_for_mode('api')
        self._api_active_conv_id = str(conv_id or "")
        self._sync_api_model_usage_bar()
        self._api_round_state = 'idle'
        self._api_round_payload = {}
        self._api_tool_status_by_id = {}
        self.api_msg_area.clear_runtime_status()
        try:
            if hasattr(self, '_api_stream_manager') and self._api_stream_manager:
                self._api_stream_manager.reset_stream_ui()
        except Exception as e:
            logger.warning(e)
        if hasattr(self.worker, "api_switch_conversation"):
            self.worker.api_switch_conversation(conv_id)
        # 兼容保留：resume_sync 仍存在，但不再承担旧视图冻结控制职责。
        self.resume_sync()

    def on_session_clicked(self, idx):
        self.message_window_service.reset_for_mode('browser')
        self.worker.request_switch_session(idx)
        self.header.set_status("请求切换会话...")
        # 兼容保留：resume_sync 仍存在，但不再承担旧视图冻结控制职责。
        self.resume_sync()

    def resume_sync(self):
        # 旧的视图冻结/同步机制已弱化；当前仅保留兼容入口。
        self.is_switching = True
        self.header.set_sync_visible(False)

    def _request_browser_resync(self):
        logger.warning("[page] 浏览器消息投影请求 resync")
        if hasattr(self.worker, "trigger_resync"):
            self.worker.trigger_resync()
        else:
            self.resume_sync()

    def on_messages_received(self, messages):
        # 兼容保留：旧的视图冻结/同步入口，当前主流程已改为 _on_mode_messages。
        print(f"📬 [ChatPage] 收到消息: {len(messages)} 条")
        if not messages or len(messages) == 0:
            return
        force_scroll = self.is_switching
        self.is_switching = False
        success = True # 这里需根据具体逻辑调整，目前默认True
        if not success:
            self.header.set_status("🚫 视图暂停")
            self.header.set_sync_visible(True)
        else:
            self.header.set_sync_visible(False)

    def _on_mode_messages(self, message):
        if not message:
            target_mode = self.current_mode
        else:
            source = message[0].get("source", "browser")
            target_mode = "api" if source == "api" else "browser"

        incoming_id = message[0].get("id", "") if message else ""
        if target_mode == 'api':
            incoming_conv = str(message[0].get('conversation_id') or '') if message else ''
            if incoming_conv and self._api_active_conv_id and incoming_conv != self._api_active_conv_id:
                return
            server_msgs = list(message or [])
            self._api_all_messages = list(server_msgs)

            round_state = str(getattr(self, '_api_round_state', 'idle') or 'idle')
            msg_count = len(server_msgs or [])
            last_role = ''
            try:
                last = (server_msgs or [])[-1] if server_msgs else {}
                last_role = str(last.get('role', '') or '') if isinstance(last, dict) else ''
            except Exception:
                pass

            probe("chatpage_messages_received", level="debug", side="ui",
                  state=round_state, msg_count=msg_count, last_role=last_role)

            hold_render_states = {
                'streaming_initial_reply',
                'detecting_tools',
                'running_tools',
                'generating_followup',
            }
            if round_state in hold_render_states:
                if round_state == 'streaming_initial_reply':
                    stream_manager = getattr(self, '_api_stream_manager', None)
                    active_stream_id = getattr(stream_manager, '_active_stream_id', None) if stream_manager else None
                    if active_stream_id:
                        probe("chatpage_hold_render", level="debug", side="ui",
                              state=round_state, cached_count=msg_count, active_stream=True)
                        return
                    probe("chatpage_stream_completed_takeover", level="info", side="ui",
                          state=round_state, cached_count=msg_count, active_stream=False)
                else:
                    self._api_messages_pending_render = True
                    probe("chatpage_hold_render", level="debug", side="ui",
                          state=round_state, cached_count=msg_count)
                    return

            self._sync_tool_results_into_runtime_status()
            self._render_api_messages_with_tool_status()
        else:
            # 注入 conversation_id 供增量渲染判断对话切换
            # 注意：RemoteWorker 有 __getattr__ 魔法，getattr 会返回函数而非 AttributeError
            # 必须直接查 __dict__ 绕过
            _raw = self.worker.__dict__.get('current_chat_id', '')
            browser_conv_id = str(_raw) if isinstance(_raw, str) else ''
            event_type = (message[0].get('_event', '') if message else '')
            for msg in message or []:
                if isinstance(msg, dict) and not msg.get('conversation_id'):
                    msg['conversation_id'] = browser_conv_id
            projection = self._browser_message_projection
            incoming_conv = str(message[0].get('conversation_id') or '') if message else ''
            incremental = event_type in {'message.upsert', 'message.remove'}
            if message:
                seq = message[0].get('_seq', 0)
                if seq > 0 and seq <= projection.state.last_seq:
                    return
                if incoming_conv and incoming_conv != projection.state.conversation_id:
                    if incremental:
                        self._request_browser_resync()
                        return
                    projection.reset()
                change = projection.apply_messages(message)
                if change['type'] in {'stale', 'empty', 'resync_needed'}:
                    return
                projection.state.conversation_id = incoming_conv
            else:
                projection.reset()
            self._browser_all_messages = projection.get_ordered_messages()
            visible, has_more = self.message_window_service.slice_messages('browser', self._browser_all_messages)
            if incremental:
                self.browser_msg_area.render_incremental(message, round_state=self._browser_round_state)
                self.browser_msg_area.set_load_more_visible(has_more)
                return
            browser_round_state = self._browser_round_state
            if browser_round_state == 'idle':
                _raw = getattr(self.worker, 'browser_round_state', None)
                if isinstance(_raw, str) and _raw:
                    browser_round_state = _raw
            self.browser_msg_area.render_messages(visible, incoming_id, round_state=browser_round_state)
            self.browser_msg_area.set_load_more_visible(has_more)

    def _on_browser_ai_state(self, payload):
        if not isinstance(payload, dict):
            return
        # 工具事件：实时更新工具卡状态
        if payload.get('type') == 'tool_event':
            tool_call_id = str(payload.get('tool_call_id', '') or '').strip()
            if tool_call_id:
                event = payload.get('_event', '')
                status = payload.get('status', '')
                tool_name = payload.get('tool_name', '')
                logger.info("[page] 收到工具事件 | event=%s | tool_call_id=%s | tool_name=%s | status=%s",
                            event, tool_call_id[:20], tool_name, status)
                if event == 'tool.status':
                    self.browser_msg_area.update_tool_status(tool_call_id, payload)
                elif event == 'tool.result':
                    self.browser_msg_area.update_tool_result(tool_call_id, payload)
            else:
                logger.warning("[page] 工具事件缺少 tool_call_id | payload=%s", {k: str(v)[:30] for k, v in payload.items()})
            return
        browser_round = payload.get('browser_round', '')
        if browser_round and isinstance(browser_round, str):
            old = self._browser_round_state
            self._browser_round_state = browser_round
            if old != browser_round:
                logger.info("[page] browser_round_state 更新 | %s → %s", old, browser_round)

    def _on_api_round_state_changed(self, payload):
        if not isinstance(payload, dict):
            return
        # 分发：tool_call 类型的事件转发给 _on_tool_status_event
        if str(payload.get('type', '') or '').strip() == 'tool_call':
            self._on_tool_status_event(payload)
            return
        conv_id = str(payload.get("conversation_id") or "")
        if self._api_active_conv_id and conv_id and conv_id != self._api_active_conv_id:
            return
        request_id = str(payload.get("request_id") or "")
        state = str(payload.get('state', '') or 'idle').strip() or 'idle'
        if request_id and request_id in self._api_closed_requests:
            return
        old_request = self._api_round_payload.get("request_id")
        if request_id and old_request and request_id != old_request and state != "streaming_initial_reply" and self._api_round_state not in {"idle", "finalized", "failed", "cancelled"}:
            return
        pending = self._api_pending_approval
        if pending and (state != "awaiting_approval" or request_id != pending["request_id"]):
            self._dismiss_agent_tool_approval()
        if request_id and state in {"idle", "finalized", "failed", "cancelled"}:
            self._api_closed_requests.add(request_id)
        self._api_round_payload = dict(payload)
        self._api_round_state = state
        self.api_stop_btn.setEnabled(state not in {"idle", "finalized", "failed", "cancelled"})
        trace_id = str(payload.get('trace_id', '') or '')
        round_id = str(payload.get('round_id', '') or '')

        probe("chatpage_round_state", level="info", side="ui",
              state=state, trace_id=trace_id, round_id=round_id,
              conv_id=payload.get('conversation_id', ''))

        if self.current_mode != "api" and self._api_runtime_busy():
            # A reconnect snapshot describes an already-running API request. Only
            # reveal its local view; switching the backend mode would be rejected.
            self.current_mode = "api"
            self.inner_stack.setCurrentIndex(1)
            self.session_tabs.blockSignals(True)
            self.session_tabs.setCurrentIndex(1)
            self.session_tabs.blockSignals(False)
            self.header.set_mode("api")
        if self.current_mode == 'api':
            tool_name = str(payload.get('tool_name', '') or '').strip()
            message = str(payload.get('message', '') or '').strip()
            runtime_text = ''
            if state == 'detecting_tools':
                runtime_text = message or '🧠 正在分析工具调用...'
                self.header.set_status(runtime_text)
                self.api_msg_area.show_runtime_status(runtime_text)
            elif state == 'browser_stateless':
                runtime_text = message or '正在操作 WebAI 网页...'
                self.header.set_status(runtime_text)
                self.api_msg_area.show_runtime_status(runtime_text)
            elif state == 'awaiting_approval':
                self.header.set_status('等待本次工具执行批准')
            elif state == 'running_tools':
                runtime_text = message or (f'🛠️ 正在执行 {tool_name}...' if tool_name else '🛠️ 正在执行工具...')
                self.header.set_status(runtime_text)
                self.api_msg_area.show_runtime_status(runtime_text)
            elif state == 'generating_followup':
                runtime_text = message or '🤖 正在生成后续回答...'
                self.header.set_status(runtime_text)
                self.api_msg_area.show_runtime_status(runtime_text)
            elif state in {'finalized', 'failed', 'cancelled'}:
                self.api_msg_area.clear_runtime_status()
                self.header.set_status(message or {'finalized': '请求完成', 'failed': '请求失败', 'cancelled': '请求已停止'}[state])
                cached_count = len(self._api_all_messages or [])
                probe("chatpage_render_finalized", level="info", side="ui",
                      trace_id=trace_id, round_id=round_id,
                      cached_count=cached_count,
                      loop_count=payload.get('loop_count', 0),
                      pending=getattr(self, '_api_messages_pending_render', False))
                # 只在 hold 期间确实收到过新消息时才立即渲染
                # 否则等 messages_signal 到达后再渲染（避免用过时数据清掉流式气泡）
                if getattr(self, '_api_messages_pending_render', False):
                    self._api_messages_pending_render = False
                    self._sync_tool_results_into_runtime_status()
                    self._render_api_messages_with_tool_status()
            elif state == 'idle':
                self.api_msg_area.clear_runtime_status()

    def _build_tool_status_snapshot(self):
        snapshot = {}
        for tool_call_id, payload in (self._api_tool_status_by_id or {}).items():
            if not tool_call_id:
                continue
            status = str(payload.get('status', '') or '').strip()
            message = str(payload.get('message', '') or '').strip()
            tool_name = str(payload.get('tool_name', '') or '').strip()
            content = str(payload.get('content', '') or '')
            success = payload.get('success', None)
            if not message:
                if status == 'running':
                    message = f'正在执行 {tool_name}...' if tool_name else '正在执行工具...'
                elif status == 'completed':
                    message = '执行完成'
                elif status == 'failed':
                    message = '执行失败'
            snapshot[tool_call_id] = {
                'status': status,
                'message': message,
                'tool_name': tool_name,
                'content': content,
                'success': success,
            }
        return snapshot

    def _render_api_messages_with_tool_status(self):
        # Pi 工具往返会在同一流中多次发布历史快照。直到流结束，历史不得
        # 删除 MessageAreaStreamManager 持有的临时气泡。
        stream = getattr(self, "_api_stream_manager", None)
        if stream is not None and getattr(stream, "_active_stream_id", None):
            self._api_messages_pending_render = True
            return
        visible, has_more = self.message_window_service.slice_messages('api', self._api_all_messages)
        enriched_visible = []
        status_snapshot = self._build_tool_status_snapshot()
        for msg in visible:
            if not isinstance(msg, dict):
                enriched_visible.append(msg)
                continue
            if self._is_ephemeral_api_tool_feedback(msg):
                continue
            cloned = dict(msg)
            segments = []
            for seg in (msg.get('segments', []) or []):
                if not isinstance(seg, dict):
                    segments.append(seg)
                    continue
                cloned_seg = dict(seg)
                _seg_type = cloned_seg.get('type', '')
                _seg_lang = str(cloned_seg.get('language', '') or '').strip().lower()
                _is_tool_call_seg = (_seg_type == 'tool_call') or (_seg_type == 'code' and _seg_lang == 'tool_call')
                if _is_tool_call_seg:
                    tool_call_id = str(cloned_seg.get('tool_call_id') or '').strip()
                    if tool_call_id and tool_call_id in status_snapshot:
                        runtime_payload = dict(status_snapshot[tool_call_id])
                        cloned_seg['runtime_status'] = runtime_payload
                        content = str(runtime_payload.get('content', '') or '')
                        success = runtime_payload.get('success', None)
                        if content:
                            cloned_seg['_bound_runtime_result'] = {
                                'content': content,
                                'success': success,
                                'tool_name': runtime_payload.get('tool_name', ''),
                            }
                segments.append(cloned_seg)
            cloned['segments'] = segments
            enriched_visible.append(cloned)
        incoming_id = enriched_visible[0].get('id', '') if enriched_visible else ''
        self.api_msg_area.render_messages(enriched_visible, incoming_id)
        self.api_msg_area.set_load_more_visible(has_more)

    def _is_ephemeral_api_tool_feedback(self, msg):
        if not isinstance(msg, dict):
            return False
        meta = msg.get('meta', {}) if isinstance(msg.get('meta', {}), dict) else {}
        if not bool(meta.get('ephemeral')):
            return False
        kind = str(msg.get('kind', '') or '').strip().lower()
        tool_kind = str(meta.get('tool_kind', '') or '').strip().lower()
        return kind == 'tool_feedback' or tool_kind == 'tool_feedback'

    def _on_tool_status_event(self, payload):
        if not isinstance(payload, dict):
            return
        if str(payload.get('type', '') or '').strip() != 'tool_call':
            return
        tool_call_id = str(payload.get('tool_call_id', '') or '').strip()
        if not tool_call_id:
            return
        status = str(payload.get('status', '') or '').strip()
        tool_name = str(payload.get('tool_name', '') or '').strip()
        message = str(payload.get('message', '') or '').strip()
        existing = dict(self._api_tool_status_by_id.get(tool_call_id, {}) or {})
        existing.update({
            'status': status,
            'tool_name': tool_name,
            'message': message,
        })
        if status in ('completed', 'failed', 'cancelled') and not message:
            existing['message'] = '执行完成' if status == 'completed' else '执行失败'
        self._api_tool_status_by_id[tool_call_id] = existing
        if self.current_mode == 'api':
            updated = False
            result_updated = False
            runtime_payload = self._api_tool_status_by_id.get(tool_call_id, {})
            if hasattr(self, 'api_msg_area') and self.api_msg_area:
                updated = bool(self.api_msg_area.update_tool_status(tool_call_id, runtime_payload))
                if runtime_payload.get('content'):
                    result_updated = bool(self.api_msg_area.update_tool_result(tool_call_id, runtime_payload))
            if not updated and not result_updated:
                self._render_api_messages_with_tool_status()

    def _sync_tool_results_into_runtime_status(self):
        for msg in (self._api_all_messages or []):
            if not isinstance(msg, dict):
                continue
            for seg in (msg.get('segments', []) or []):
                if not isinstance(seg, dict):
                    continue
                if seg.get('type') != 'tool_result':
                    continue
                tool_call_id = str(seg.get('tool_call_id', '') or '').strip()
                if not tool_call_id:
                    continue
                existing = dict(self._api_tool_status_by_id.get(tool_call_id, {}) or {})
                existing['content'] = str(seg.get('content', '') or '')
                existing['success'] = seg.get('success', None)
                if not existing.get('tool_name'):
                    existing['tool_name'] = str(seg.get('tool_name', '') or '').strip()
                status = str(existing.get('status', '') or '').strip()
                if not status:
                    existing['status'] = 'completed' if seg.get('success', True) else 'failed'
                message = str(existing.get('message', '') or '').strip()
                if not message:
                    existing['message'] = '执行完成' if seg.get('success', True) else '执行失败'
                self._api_tool_status_by_id[tool_call_id] = existing
    def _on_subagent_suggestion(self, suggestions):
        if not isinstance(suggestions, list) or not suggestions:
            return
        target = self.browser_input_area if self.current_mode == "browser" else self.api_input_area
        target.show_suggestions(suggestions)

    def _send_text_in_mode(self, mode, text):
        if mode == self.current_mode:
            if mode == "browser":
                self.worker.send_text("div.aa-chat-input textarea", text)
            else:
                handled, resolved_text = self.api_skill_references.handle(text)
                if handled:
                    return
                text = resolved_text or text
                self._api_round_state = 'streaming_initial_reply'
                self._append_local_api_user_message(text)
                probe("chatpage_send_text", level="info", side="ui", mode="api", text_len=len(text))
                if hasattr(self.worker, "api_send"):
                    self.worker.api_send(text, stream=True)

    def _send_compound_in_mode(self, mode, text, files):
        if mode != self.current_mode:
            return
        if mode == "browser":
            if hasattr(self.worker, "send_compound"):
                self.worker.send_compound(text, files)
            else:
                self.worker.send_text("div.aa-chat-input textarea", text)
        else:
            handled, resolved_text = self.api_skill_references.handle(text)
            if handled:
                return
            text = resolved_text or text
            if files and hasattr(self.worker, "status_signal"):
                try:
                    self.worker.status_signal.emit("⚠️ API 模式暂不支持附件上传，已仅发送文本")
                except Exception as e:
                    logger.warning(e)
            self._api_round_state = 'streaming_initial_reply'
            self._append_local_api_user_message(text)  # 先在界面渲染用户发出的消息
            if hasattr(self.worker, "api_send"):
                self.worker.api_send(text, stream=True)  # 启用流式输出
