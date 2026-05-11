# filename: app/ui/pages/chat/page.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QSplitter, QMessageBox, QApplication, QStackedWidget, QPushButton, QHBoxLayout, QFrame, QTabWidget, QGraphicsOpacityEffect, QLabel)
from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve, QPoint, QRect, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QPainter, QBrush, QPen

from .header import ChatHeader
from .session_list import SessionList
from .api_session_list import APISessionList
from .input_area import InputArea
from .message_area import MessageArea
from .status_bar import ApiModelUsageBar
from .services.message_window_service import MessageWindowService
from app.ui.components.chat import ChatBubble
from app.core.config import ConfigManager
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
            default_turns=int(cfg.get('chat_message_load_turns', 20)),
            step_turns=int(cfg.get('chat_message_load_step_turns', 10)),
        )
        self._browser_all_messages = []
        self._api_all_messages = []
        self.init_ui()
        self.connect_signals()
        self.sidebar_expanded = True
        self.last_sidebar_width = 260
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

        self.browser_page = QWidget()
        browser_layout = QVBoxLayout(self.browser_page)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        self.browser_msg_area = MessageArea()
        self.browser_input_area = InputArea()
        self.browser_splitter = QSplitter(Qt.Orientation.Vertical)
        self.browser_splitter.setHandleWidth(4)
        self.browser_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #1E293B; height: 4px; }"
            "QSplitter::handle:hover { background-color: #6366F1; }"
        )
        self.browser_splitter.addWidget(self.browser_msg_area)
        self.browser_splitter.addWidget(self.browser_input_area)
        self.browser_splitter.setStretchFactor(0, 8)
        self.browser_splitter.setStretchFactor(1, 2)
        self.browser_splitter.setSizes([700, 180])
        browser_layout.addWidget(self.browser_splitter)

        self.api_page = QWidget()
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
        self.api_msg_area = MessageArea()
        self.api_input_area = InputArea()
        self.api_input_panel = QWidget()
        api_input_panel_layout = QVBoxLayout(self.api_input_panel)
        api_input_panel_layout.setContentsMargins(0, 0, 0, 0)
        api_input_panel_layout.setSpacing(0)
        self.api_model_usage_bar = ApiModelUsageBar()
        api_input_panel_layout.addWidget(self.api_input_area)
        api_input_panel_layout.addWidget(self.api_model_usage_bar)
        self.api_splitter = QSplitter(Qt.Orientation.Vertical)
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
        self.v_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #1E293B; height: 4px; }"
            "QSplitter::handle:hover { background-color: #6366F1; }"
        )
        self.v_splitter.addWidget(self.inner_stack)
        self.v_splitter.setStretchFactor(0, 1)

        self.splitter.addWidget(self.v_splitter)
        self.splitter.setCollapsible(0, False)
        self.splitter.setSizes([260, 800])
        layout.addWidget(self.splitter)

        self._apply_tab_theme()
        theme_manager.theme_changed.connect(self._apply_tab_theme)

    def _apply_tab_theme(self):
        p = theme_manager.get_palette()
        self.session_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background-color: {p.BG_SECONDARY}; color: {p.TEXT_SECONDARY};
                padding: 8px 16px; border: none; border-bottom: 2px solid transparent;
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
            target_w = self.last_sidebar_width if self.last_sidebar_width > 100 else 260
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
        self.worker.context_health_signal.connect(lambda t, g: self.header.update_health(g))
        self.worker.sessions_signal.connect(self._dispatch_sessions)
        self.worker.state_sync_signal.connect(self.header.update_stats)
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

        if hasattr(self.worker, "daemon_suggestion_signal"):
            self.worker.daemon_suggestion_signal.connect(self._on_daemon_suggestion)

        self.browser_input_area.request_send_text.connect(lambda t: self._send_text_in_mode("browser", t))
        self.api_input_area.request_send_text.connect(lambda t: self._send_text_in_mode("api", t))
        self.browser_input_area.request_send_compound.connect(lambda text, files: self._send_compound_in_mode("browser", text, files))
        self.api_input_area.request_send_compound.connect(lambda text, files: self._send_compound_in_mode("api", text, files))
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
            self._chat_page_stream.set_active_conv_hook(lambda: getattr(self.api_session_list, '_active_conv_id', None))
            self._chat_page_stream.set_stream_manager(self._api_stream_manager)
            if _has_stream_bridge:
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
        else:
            self.session_list.update_list(sessions)

    def _on_api_new_conversation(self, title):
        if hasattr(self.worker, "api_new_conversation"):
            self.worker.api_new_conversation(title)

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
        self.browser_msg_area.render_messages(visible, incoming_id)
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

    def get_input_height_state(self): return self.v_splitter.sizes()
    def set_input_height_state(self, s): self.v_splitter.setSizes(s)

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
        local_msg = {
            "role": "User",
            "id": f"local_0",
            "source": "api",
            "segments": [{"type": "text", "content": text}],
        }
        self._api_all_messages = list(self._api_all_messages or [])
        self._api_all_messages.append(local_msg)
        visible, has_more = self.message_window_service.slice_messages('api', self._api_all_messages)
        self.api_msg_area.render_messages(visible, local_msg.get("id", ""))
        self.api_msg_area.flush_render()  # 确保本地气泡立刻同步渲染完毕，防止与后续的流式气泡产生顺序竞态
        self.api_msg_area.set_load_more_visible(has_more)

    def on_mode_switch(self, mode):
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
            if event_type == 'message.upsert':
                for msg in message or []:
                    if isinstance(msg, dict) and not msg.get('conversation_id'):
                        msg['conversation_id'] = browser_conv_id
                self.browser_msg_area.render_incremental(message, round_state=self._browser_round_state)
                return
            self._browser_all_messages = list(message or [])
            if browser_conv_id:
                for msg in self._browser_all_messages:
                    if isinstance(msg, dict) and not msg.get('conversation_id'):
                        msg['conversation_id'] = browser_conv_id
            visible, has_more = self.message_window_service.slice_messages('browser', self._browser_all_messages)
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
        self._api_round_payload = dict(payload)
        state = str(payload.get('state', '') or 'idle').strip() or 'idle'
        self._api_round_state = state
        trace_id = str(payload.get('trace_id', '') or '')
        round_id = str(payload.get('round_id', '') or '')

        probe("chatpage_round_state", level="info", side="ui",
              state=state, trace_id=trace_id, round_id=round_id,
              conv_id=payload.get('conversation_id', ''))

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
            elif state == 'running_tools':
                runtime_text = message or (f'🛠️ 正在执行 {tool_name}...' if tool_name else '🛠️ 正在执行工具...')
                self.header.set_status(runtime_text)
                self.api_msg_area.show_runtime_status(runtime_text)
            elif state == 'generating_followup':
                runtime_text = message or '🤖 正在生成后续回答...'
                self.header.set_status(runtime_text)
                self.api_msg_area.show_runtime_status(runtime_text)
            elif state == 'finalized':
                self.api_msg_area.clear_runtime_status()
                cached_count = len(self._api_all_messages or [])
                probe("chatpage_render_finalized", level="info", side="ui",
                      trace_id=trace_id, round_id=round_id,
                      cached_count=cached_count,
                      loop_count=payload.get('loop_count', 0))
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
        visible, has_more = self.message_window_service.slice_messages('api', self._api_all_messages)
        enriched_visible = []
        status_snapshot = self._build_tool_status_snapshot()
        for msg in visible:
            if not isinstance(msg, dict):
                enriched_visible.append(msg)
                continue
            cloned = dict(msg)
            segments = []
            for seg in (msg.get('segments', []) or []):
                if not isinstance(seg, dict):
                    segments.append(seg)
                    continue
                cloned_seg = dict(seg)
                if cloned_seg.get('type') == 'tool_call':
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
    def _on_daemon_suggestion(self, suggestions):
        if not isinstance(suggestions, list) or not suggestions:
            return
        target = self.browser_input_area if self.current_mode == "browser" else self.api_input_area
        target.show_suggestions(suggestions)

    def _send_text_in_mode(self, mode, text):
        if mode == self.current_mode:
            if mode == "browser":
                self.worker.send_text("div.aa-chat-input textarea", text)
            else:
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
            if files and hasattr(self.worker, "status_signal"):
                try:
                    self.worker.status_signal.emit("⚠️ API 模式暂不支持附件上传，已仅发送文本")
                except Exception as e:
                    logger.warning(e)
            self._api_round_state = 'streaming_initial_reply'
            self._append_local_api_user_message(text)  # 先在界面渲染用户发出的消息
            if hasattr(self.worker, "api_send"):
                self.worker.api_send(text, stream=True)  # 启用流式输出
