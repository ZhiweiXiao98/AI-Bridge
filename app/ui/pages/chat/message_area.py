import logging
import os
import time
import requests
import hashlib
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QScrollArea, QPushButton, QGridLayout, QLabel, QApplication)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from app.ui.components.chat import ChatBubble, CodeBox, ToolCallCard
from app.core.config import ConfigManager
from app.core.project_context import ProjectContext
from app.core.browser_sync.projection import ChatProjectionReducer
from app.ui.theme import Theme, Palette, theme_manager
from app.core.logging import get_logger

logger = get_logger("app.ui.message_area", side="ui")

class MessageArea(QWidget):
    request_scroll_bottom = Signal()
    request_manual_toggle = Signal(int, int, int)
    request_quick_apply = Signal(str, str)
    request_set_snapshot = Signal(int)
    request_correct_turn = Signal(object, int)
    request_ignore_file = Signal(str)
    request_save_file = Signal(str, str)
    request_discard_file = Signal(str, str)
    request_undiscard_file = Signal(str, str) # [New] 撤销信号
    request_enter_multi_select_mode = Signal(int)
    selection_count_changed = Signal(int)
    request_load_more = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_paused = False
        self.is_sticking_to_bottom = False
        
        self.pending_messages = []
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(20) 
        self.render_timer.timeout.connect(self._render_next_slice)
        self.current_render_idx = 0
        self.bubbles_cache = []
        self._bubbles_by_id = {}
        self._tool_cards_by_id = {}
        self._pending_tool_events = {}
        self._projection = ChatProjectionReducer()
        self.selection_mode = False
        self.selected_indexes = set()
        self.has_more_history = False
        # 增量渲染状态
        self._last_rendered_messages = None  # 上次渲染完成的消息列表快照
        self._last_conversation_id = ''  # 上次渲染的对话 ID
        self._last_streaming_update_time = 0  # AI_STREAMING 流式更新节流
        
        self.img_cache_dir = os.path.join(ProjectContext.get().get_project_root(), "export", "img_cache")
        if not os.path.exists(self.img_cache_dir): os.makedirs(self.img_cache_dir)
        
        self.init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.v_scrollbar = self.scroll_area.verticalScrollBar()
        self.v_scrollbar.valueChanged.connect(self.check_scroll_position)
        self.v_scrollbar.rangeChanged.connect(self.on_range_changed)
        self.v_scrollbar.sliderPressed.connect(self.stop_sticking)
        
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.addStretch()
        
        self.status_lbl = QLabel("等待数据...")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chat_layout.addWidget(self.status_lbl)

        self._runtime_status_lbl = QLabel("")
        self._runtime_status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._runtime_status_lbl.setVisible(False)
        self.chat_layout.insertWidget(max(0, self.chat_layout.count() - 1), self._runtime_status_lbl)
        
        self.scroll_area.setWidget(self.chat_container)
        layout.addWidget(self.scroll_area, 0, 0)
        
        self.scroll_btn = QPushButton("▼")
        self.scroll_btn.setFixedSize(40, 40)
        self.scroll_btn.clicked.connect(self.force_scroll_bottom)
        self.scroll_btn.hide()
        layout.addWidget(self.scroll_btn, 0, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)

        self.load_more_btn = QPushButton("加载更多消息")
        self.load_more_btn.clicked.connect(self.request_load_more.emit)
        self.load_more_btn.hide()
        layout.addWidget(self.load_more_btn, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.scroll_area.setStyleSheet(f"QScrollArea {{ border: none; background-color: {p.BG_PRIMARY}; }}")
        self.chat_container.setStyleSheet(f"background-color: {p.BG_PRIMARY};")
        self.status_lbl.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 14px; margin-top: 50px;")
        if hasattr(self, '_runtime_status_lbl'):
            self._runtime_status_lbl.setStyleSheet(
                f"background-color: {p.BG_SECONDARY}; color: {p.TEXT_SECONDARY}; "
                f"border: 1px solid {p.BORDER}; border-radius: 10px; "
                f"padding: 8px 12px; margin: 6px 15px; font-size: 13px;"
            )
        self.scroll_btn.setStyleSheet(f"QPushButton {{ background-color: {p.ACCENT_PRIMARY}; color: white; border-radius: 20px; font-weight: bold; border: 2px solid {p.BG_PRIMARY}; }}")
        self.load_more_btn.setStyleSheet(f"QPushButton {{ background-color: {p.BG_SECONDARY}; color: {p.TEXT_PRIMARY}; border-radius: 14px; padding: 6px 14px; border: 1px solid {p.BORDER}; }} QPushButton:hover {{ border: 1px solid {p.ACCENT_PRIMARY}; color: {p.ACCENT_PRIMARY}; }}")

    def set_paused(self, paused):
        self.is_paused = paused
        self.chat_container.setEnabled(not paused)

    def force_scroll_bottom(self): 
        self.is_sticking_to_bottom = True
        self.v_scrollbar.setValue(self.v_scrollbar.maximum())

    def stop_sticking(self):
        self.is_sticking_to_bottom = False

    def on_range_changed(self, min_val, max_val):
        if self.is_sticking_to_bottom:
            self.v_scrollbar.setValue(max_val)

    def check_scroll_position(self): 
        value = self.v_scrollbar.value()
        max_val = self.v_scrollbar.maximum()
        near_bottom = (max_val - value) <= 80

        if not near_bottom:
            self.scroll_btn.show()
            if self.is_sticking_to_bottom and not self.v_scrollbar.isSliderDown():
                self.is_sticking_to_bottom = False
        else: 
            self.scroll_btn.hide()
            if not self.v_scrollbar.isSliderDown():
                self.is_sticking_to_bottom = True
        self.load_more_btn.setVisible(self.has_more_history and value <= self.v_scrollbar.minimum())

    def enter_multi_select_mode(self, initial_index=None):
        self.selection_mode = True
        if initial_index is not None:
            self.selected_indexes.add(int(initial_index))
        self._apply_selection_state_to_bubbles()
        self.selection_count_changed.emit(len(self.selected_indexes))

    def exit_multi_select_mode(self):
        self.selection_mode = False
        self.selected_indexes.clear()
        self._apply_selection_state_to_bubbles()
        self.selection_count_changed.emit(0)

    def clear_selected_indexes(self):
        self.selected_indexes.clear()
        self._apply_selection_state_to_bubbles()
        self.selection_count_changed.emit(0)

    def _clear_all_bubbles(self):
        """清空所有气泡：从 layout 中移除、清空缓存和索引。"""
        widgets_to_remove = []
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble):
                widgets_to_remove.append(item.widget())
        for w in widgets_to_remove:
            self.chat_layout.removeWidget(w)
            w.deleteLater()
        self.bubbles_cache = []
        self._bubbles_by_id = {}
        self._tool_cards_by_id = {}
        self._pending_tool_events = {}

    def get_selected_indexes(self):
        return sorted(self.selected_indexes)

    def _on_bubble_selection_changed(self, index, checked):
        if checked:
            self.selected_indexes.add(int(index))
        else:
            self.selected_indexes.discard(int(index))
        self.selection_count_changed.emit(len(self.selected_indexes))

    def _apply_selection_state_to_bubbles(self):
        for bubble in self.bubbles_cache:
            bubble.set_selection_mode(self.selection_mode, bubble.index in self.selected_indexes)

    def set_load_more_visible(self, visible: bool):
        self.has_more_history = bool(visible)
        self.load_more_btn.setVisible(self.has_more_history and self.v_scrollbar.value() <= self.v_scrollbar.minimum())

    def show_runtime_status(self, text: str):
        if not hasattr(self, '_runtime_status_lbl'):
            return
        text = str(text or '').strip()
        if not text:
            self.clear_runtime_status()
            return
        self._runtime_status_lbl.setText(text)
        self._runtime_status_lbl.setVisible(True)
        self.is_sticking_to_bottom = True
        self.v_scrollbar.setValue(self.v_scrollbar.maximum())

    def clear_runtime_status(self):
        if hasattr(self, '_runtime_status_lbl'):
            self._runtime_status_lbl.setText('')
            self._runtime_status_lbl.setVisible(False)

    def render_incremental(self, changed_messages, round_state=None):
        """增量渲染入口：只处理变化的消息，不重建完整列表。

        增量推送时调用此方法，而非 render_messages。
        通过 projection reducer 的 apply_messages 处理变化消息，
        然后从 projection 获取完整有序列表进行局部刷新。
        """
        if not changed_messages:
            return False

        change = self._projection.apply_messages(changed_messages)
        change_type = change["type"]

        if change_type in ("stale", "empty"):
            return False

        added = change["added"]
        updated = change["updated"]
        removed = change["removed"]

        if not added and not updated and not removed:
            return False

        logger.info("[增量渲染] added=%s | updated=%s | removed=%s | seq=%s",
                    len(added), len(updated), len(removed), change.get("seq"))

        if removed:
            for rid in removed:
                bubble = self._bubbles_by_id.pop(rid, None)
                if bubble:
                    if bubble in self.bubbles_cache:
                        self.bubbles_cache.remove(bubble)
                    self.chat_layout.removeWidget(bubble)
                    bubble.deleteLater()

        all_messages = self._projection.get_ordered_messages()

        if updated:
            self._refresh_bubbles_by_msg_ids(all_messages, set(updated))

        if added:
            for mid in added:
                msg_data = self._projection.state.messages_by_id.get(mid)
                if not msg_data or msg_data.get('_hidden'):
                    continue
                idx = msg_data.get('index', 1)
                expected_is_user = (msg_data.get('role') == 'User')
                bubble = ChatBubble(msg_data, expected_is_user, index=idx)
                bubble.request_set_snapshot.connect(self.request_set_snapshot.emit)
                bubble.request_correct_turn.connect(self.request_correct_turn.emit)
                bubble.request_remote_action.connect(self.request_manual_toggle.emit)
                bubble.request_code_apply.connect(self.request_quick_apply.emit)
                bubble.request_multi_select_mode.connect(self.request_enter_multi_select_mode.emit)
                bubble.selection_changed.connect(self._on_bubble_selection_changed)
                bubble.request_discard_relay.connect(self.request_discard_file.emit)
                bubble.request_undiscard_relay.connect(self.request_undiscard_file.emit)
                bubble.set_selection_mode(self.selection_mode, bubble.index in self.selected_indexes)

                insert_pos = self._find_insert_position(msg_data.get('ordinal', 0))
                self.chat_layout.insertWidget(insert_pos, bubble)
                self.bubbles_cache.append(bubble)
                if bubble.message_id:
                    self._bubbles_by_id[bubble.message_id] = bubble

            self._rebuild_bubbles_cache_order()

        self._rebuild_tool_card_registry()
        self._try_cross_message_tool_binding()
        self._last_rendered_messages = list(all_messages)

        if self.is_sticking_to_bottom:
            self.v_scrollbar.setValue(self.v_scrollbar.maximum())

        return True

    def _find_insert_position(self, ordinal):
        """根据 ordinal 找到应插入的 layout 位置（在 stretch 之前）。"""
        stretch_idx = self.chat_layout.count() - 1
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble):
                bubble = item.widget()
                b_ordinal = getattr(bubble, 'current_data', {}).get('ordinal', 0)
                if b_ordinal > ordinal:
                    return i
        return stretch_idx

    def _rebuild_bubbles_cache_order(self):
        """根据 layout 中的实际顺序重建 bubbles_cache。"""
        new_cache = []
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble):
                new_cache.append(item.widget())
        self.bubbles_cache = new_cache

    def render_messages(self, messages, incoming_id, force_scroll=False, round_state=None):
        """增量渲染入口：通过 projection reducer 判断变更，只渲染变化部分。

        round_state: 状态机当前状态（如 'idle', 'ai_streaming', 'fixing' 等）
                     AI_STREAMING 时走轻量流式更新（只刷最后一个 AI 气泡）
                     其他状态走 projection reducer 驱动的增量渲染
        """
        if messages:
            self.status_lbl.hide()
        else:
            self.status_lbl.show()
            self.status_lbl.setText("暂无消息")

        self.render_timer.stop()

        _rs_display = str(round_state)[:30] if round_state else 'None'
        logger.debug("[渲染入口] round_state='%s' | msgs=%s | conv_id='%s'",
                     _rs_display, len(messages) if messages else 0,
                     str(messages[0].get('conversation_id', '')[:12]) if messages else '')

        # 检测对话是否切换（先于 apply_messages，避免旧投影状态污染 diff）
        new_conv_id = ''
        if messages:
            new_conv_id = str(messages[0].get('conversation_id', '') or '')
        if new_conv_id:
            conv_switched = (new_conv_id != self._last_conversation_id)
        elif not messages and self._last_conversation_id:
            conv_switched = True
        else:
            conv_switched = False

        if conv_switched:
            self._projection.reset()
            self._clear_all_bubbles()

        # === projection reducer 驱动 ===
        change = self._projection.apply_messages(messages)
        change_type = change["type"]

        if change_type in ("stale", "empty"):
            return False

        added = change["added"]
        updated = change["updated"]
        removed = change["removed"]
        has_changes = bool(added or updated or removed)

        if conv_switched or self._last_rendered_messages is None:
            logger.info("[渲染] 全量渲染 | conv_switched=%s | msgs=%s | seq=%s",
                        conv_switched, len(messages), change.get("seq"))
            self._last_conversation_id = new_conv_id
            self._last_rendered_messages = list(messages)
            self.pending_messages = messages
            self.current_render_idx = 0
        elif round_state == 'ai_streaming' and not added:
            return self._streaming_update(messages)
        elif has_changes:
            logger.info("[渲染] 局部刷新 | added=%s | updated=%s | removed=%s | seq=%s",
                        len(added), len(updated), len(removed), change.get("seq"))
            if removed:
                for rid in removed:
                    bubble = self._bubbles_by_id.pop(rid, None)
                    if bubble:
                        if bubble in self.bubbles_cache:
                            self.bubbles_cache.remove(bubble)
                        self.chat_layout.removeWidget(bubble)
                        bubble.deleteLater()

            if updated:
                self._refresh_bubbles_by_msg_ids(messages, set(updated))

            self.pending_messages = messages
            if added:
                if not self.bubbles_cache:
                    for i in range(self.chat_layout.count()):
                        item = self.chat_layout.itemAt(i)
                        if item and item.widget() and isinstance(item.widget(), ChatBubble):
                            self.bubbles_cache.append(item.widget())
                self.current_render_idx = self._find_render_start(messages, added)
            else:
                self.current_render_idx = len(messages)

            self._rebuild_tool_card_registry()
            self._try_cross_message_tool_binding()
            self._last_rendered_messages = list(messages)

            if updated and not added:
                if self.is_sticking_to_bottom:
                    self.v_scrollbar.setValue(self.v_scrollbar.maximum())
                return True
        else:
            logger.debug("[渲染] 投影无变化 | seq=%s | round_state='%s'", change.get("seq"), _rs_display)
            return False

        # 滚动判断
        sb = self.v_scrollbar
        was_at_bottom = (sb.value() >= sb.maximum() - 150)
        is_initial_load = (len(self.bubbles_cache) == 0 and len(messages) > 0)
        should_scroll = force_scroll or was_at_bottom or is_initial_load
        if not should_scroll and len(messages) > len(self._last_rendered_messages or []):
            if messages[-1].get('role') == 'User':
                should_scroll = True
        if should_scroll:
            self.is_sticking_to_bottom = True

        self.render_timer.start()
        return True

    def _find_render_start(self, messages, added_ids):
        """找到第一个新增消息在 messages 列表中的位置，作为增量渲染起点。"""
        for i, m in enumerate(messages):
            mid = str(m.get('id', '') or '')
            if mid in added_ids:
                return i
        return len(messages)

    def _streaming_update(self, messages):
        """AI_STREAMING 轻量流式更新：刷新最后两个 AI 气泡的内容。

        通过 _bubbles_by_id 按 message_id 查找气泡，不再依赖数组位置。
        刷新两个而非一个，留足冗余：上一轮 AI 的 ToolCallCard 可能因 block_key 变化
        未注册，刷新后才能被 tool_result 绑定到。
        节流 300ms，避免每轮轮询都刷 UI。
        """
        import time
        now = time.monotonic()
        if now - self._last_streaming_update_time < 0.3:
            return False

        ai_msgs = [(i, m) for i, m in enumerate(messages) if m.get('role') == 'AI']

        if not ai_msgs:
            return False

        refresh_msgs = ai_msgs[-2:] if len(ai_msgs) >= 2 else ai_msgs[-1:]

        refreshed = 0
        for _, msg in refresh_msgs:
            mid = str(msg.get('id', ''))
            bubble = self._bubbles_by_id.get(mid) if mid else None
            if bubble is None or getattr(bubble, 'is_user', False):
                continue
            idx = msg.get('index', 1)
            self._safe_update_bubble(bubble, msg, idx)
            refreshed += 1

        if refreshed > 0:
            self._rebuild_tool_card_registry()
            self._try_cross_message_tool_binding()
            logger.info("[流式更新] 完成 | 刷新=%d | msgs=%s", refreshed, len(messages))

        self._last_rendered_messages = list(messages)
        self._last_streaming_update_time = now

        if self.is_sticking_to_bottom:
            self.v_scrollbar.setValue(self.v_scrollbar.maximum())

        return True

    def _structural_diff(self, new_messages):
        """基于 (id, role) 的结构增量比对。
        
        只比 id + role，不比 segments 内容。
        滑动窗口场景下，新消息到来时窗口头部会滑出旧消息、尾部追加新消息。
        
        返回:
          (drop_head, update_from, action_desc) — 需要删除的头部气泡数、从哪个位置开始更新、描述
          None — 完全无结构变化
        """
        old = self._last_rendered_messages or []
        if not old:
            return (0, 0, 'first_render')
        
        # 建立旧消息 (id, role) → 旧位置索引
        old_key_to_idx = {}
        for i, m in enumerate(old):
            key = (m.get('id'), m.get('role'))
            if key not in old_key_to_idx:
                old_key_to_idx[key] = i
        
        # 在新列表中找到第一个在旧列表中也存在的 (id, role)
        first_overlap_new = None
        first_overlap_old = None
        for j, m in enumerate(new_messages):
            key = (m.get('id'), m.get('role'))
            if key in old_key_to_idx:
                first_overlap_new = j
                first_overlap_old = old_key_to_idx[key]
                break
        
        if first_overlap_new is None:
            # 完全没有重叠，全量渲染
            return (len(old), 0, 'no_overlap')
        
        # 头部滑出的旧消息数 = 旧列表中重叠点之前的消息数
        drop_head = first_overlap_old
        
        # 从重叠点开始，比对重叠部分是否有结构变化（只比 id + role）
        first_changed_new = None
        old_offset = first_overlap_old
        new_offset = first_overlap_new
        
        while old_offset < len(old) and new_offset < len(new_messages):
            o = old[old_offset]
            n = new_messages[new_offset]
            # 只比 id + role，不比 segments
            if o.get('id') != n.get('id') or o.get('role') != n.get('role'):
                first_changed_new = new_offset
                break
            old_offset += 1
            new_offset += 1
        
        # 旧列表比完了但新列表还有尾部新增
        if first_changed_new is None and new_offset < len(new_messages):
            first_changed_new = new_offset
        
        # 没有任何变化
        if first_changed_new is None and drop_head == 0:
            if len(new_messages) == len(old):
                return None  # 完全无结构变化
            # 新列表更短（窗口缩小），cleanup_excess_bubbles 会处理
            first_changed_new = len(new_messages)
        
        if first_changed_new is None:
            first_changed_new = len(new_messages)
        
        action = f'slide:{drop_head},overlap_new:{first_overlap_new},changed:{first_changed_new}'
        return (drop_head, first_changed_new, action)

    def flush_render(self):
        """强制立即完成所有待渲染消息，清空渲染队列。"""
        if self.render_timer.isActive():
            self.render_timer.stop()
            while self.current_render_idx < len(self.pending_messages):
                self._render_next_slice()
            self._render_next_slice()  # 触发最后一次收尾工作（含快照保存）

    def _safe_update_bubble(self, bubble, msg_data, idx):
        """安全更新气泡内容：断开信号 → update_content → 重连信号。"""
        try:
            bubble.request_correct_turn.disconnect()
            bubble.request_remote_action.disconnect()
            bubble.request_code_apply.disconnect()
            bubble.request_multi_select_mode.disconnect()
            bubble.selection_changed.disconnect()
            bubble.request_discard_relay.disconnect()
            bubble.request_undiscard_relay.disconnect()
        except Exception:
            pass
        bubble.update_content(msg_data, index=idx)
        bubble.request_correct_turn.connect(self.request_correct_turn.emit)
        bubble.request_remote_action.connect(self.request_manual_toggle.emit)
        bubble.request_code_apply.connect(self.request_quick_apply.emit)
        bubble.request_multi_select_mode.connect(self.request_enter_multi_select_mode.emit)
        bubble.selection_changed.connect(self._on_bubble_selection_changed)
        bubble.request_discard_relay.connect(self.request_discard_file.emit)
        bubble.request_undiscard_relay.connect(self.request_undiscard_file.emit)

    def _refresh_bubbles_by_msg_ids(self, messages, msg_ids):
        """对指定 message_id 的 AI 气泡执行 update_content，刷新 segments。"""
        if not msg_ids:
            return
        for m in messages:
            mid = str(m.get('id', ''))
            if mid not in msg_ids:
                continue
            bubble = self._bubbles_by_id.get(mid)
            if bubble is None:
                continue
            idx = m.get('index', 1)
            self._safe_update_bubble(bubble, m, idx)
            logger.info("[局部刷新] bubble已刷新 | idx=%s | msg_id=%s", idx, mid[:8])

    def _rebuild_tool_card_registry(self):
        self._tool_cards_by_id = {}
        for bubble in self.bubbles_cache:
            if not isinstance(bubble, ChatBubble):
                continue
            local_map = getattr(bubble, '_tool_cards_by_id', {}) or {}
            for tool_call_id, card in local_map.items():
                if tool_call_id and card:
                    self._tool_cards_by_id[str(tool_call_id)] = card

    def _replay_pending_tool_events(self):
        if not self._pending_tool_events:
            return
        now = time.time()
        replayed_keys = []
        for key, events in list(self._pending_tool_events.items()):
            card = self._tool_cards_by_id.get(key)
            if card is None:
                expired = [e for e in events if now - e[2] > 30]
                if expired:
                    logger.warning("[工具卡] pending事件超时丢弃 | tool_call_id=%s | count=%s",
                                  key[:20], len(expired))
                    events = [e for e in events if now - e[2] <= 30]
                    if not events:
                        replayed_keys.append(key)
                        continue
                    self._pending_tool_events[key] = events
                continue
            for evt_type, payload, ts in events:
                if evt_type == "status":
                    if hasattr(card, 'update_runtime_status'):
                        card.update_runtime_status(payload if isinstance(payload, dict) else {})
                elif evt_type == "result":
                    if not isinstance(payload, dict):
                        payload = {}
                    content = str(payload.get('content', '') or '')
                    success = payload.get('success', None)
                    if hasattr(card, 'set_result_text') and content:
                        card.set_result_text(content)
                    if hasattr(card, 'set_success') and success is not None:
                        card.set_success(bool(success))
            logger.info("[工具卡] pending事件回放成功 | tool_call_id=%s | count=%s",
                        key[:20], len(events))
            replayed_keys.append(key)
        for key in replayed_keys:
            self._pending_tool_events.pop(key, None)

    def _try_cross_message_tool_binding(self):
        """跨消息绑定：优先消费服务端 _bound_results，客户端绑定作为兼容兜底。

        服务端 normalizer 已将 tool_result 绑定到 AI 消息 tool_call segment 的
        _bound_results 字段。客户端优先消费此字段渲染工具结果。
        如果服务端未绑定（旧链路兼容），则走客户端 tool_call_id/block_key 匹配。
        """
        self._apply_server_bound_results()

        if not self._tool_cards_by_id:
            return
        _registry_keys = list(self._tool_cards_by_id.keys())
        logger.debug("[绑定-诊断] ToolCallCard 注册表 | 数量=%s | keys=%s", len(_registry_keys),
                    [k[:25] for k in _registry_keys[:10]])
        for bubble in self.bubbles_cache:
            if not isinstance(bubble, ChatBubble):
                continue
            result_map = getattr(bubble, '_tool_result_boxes_by_id', {}) or {}
            if not result_map:
                continue
            for tool_call_id, info in result_map.items():
                seg = info.get('seg') or {}
                widget = info.get('widget')
                card = self._tool_cards_by_id.get(tool_call_id)
                _bind_block_key = str(seg.get('block_key') or '').strip()
                _matched_by = ''
                if card is None:
                    if _bind_block_key:
                        card = self._tool_cards_by_id.get(_bind_block_key)
                        _matched_by = 'block_key'
                else:
                    _matched_by = 'tool_call_id'
                if card is None:
                    card = self._fuzzy_find_tool_card(bubble, _bind_block_key)
                    if card is not None:
                        _matched_by = 'fuzzy_code_index'
                    else:
                        logger.info("[绑定-诊断] 客户端绑定失败 | tool_call_id=%s | block_key=%s | 注册表keys=%s",
                                    str(tool_call_id)[:25], _bind_block_key[:25],
                                    [k[:25] for k in self._tool_cards_by_id.keys()][:10])
                        continue
                logger.debug("[绑定-诊断] 客户端绑定成功 | matched_by=%s | tool_call_id=%s | block_key=%s",
                            _matched_by, str(tool_call_id)[:25], _bind_block_key[:25])
                if tool_call_id and tool_call_id not in self._tool_cards_by_id:
                    self._tool_cards_by_id[tool_call_id] = card
                content = str(seg.get('content', '') or '')
                success = seg.get('success')
                tool_name = str(seg.get('tool_name', '') or '').strip()
                if hasattr(card, 'set_result_text') and content:
                    card.set_result_text(content)
                if hasattr(card, 'set_success') and success is not None:
                    card.set_success(bool(success))
                if hasattr(card, 'set_status_text'):
                    if success is True:
                        card.set_status_text('执行完成')
                    elif success is False:
                        card.set_status_text('执行失败')
                    elif tool_name:
                        card.set_status_text(f'{tool_name} 已返回结果')
                if widget is not None:
                    widget.setVisible(False)
                    self._hide_bubble_if_empty(bubble)

    def _apply_server_bound_results(self):
        """消费服务端 normalizer 绑定的 _bound_results，回填到 ToolCallCard。

        服务端在 normalizer._bind_tool_feedback_to_ai 中将 tool_result 绑定到
        AI 消息 tool_call segment 的 _bound_results 字段。
        客户端遍历所有 AI 气泡，找到含 _bound_results 的 segment，
        将结果回填到对应 ToolCallCard。
        """
        for bubble in self.bubbles_cache:
            if not isinstance(bubble, ChatBubble):
                continue
            if getattr(bubble, 'is_user', False):
                continue
            local_map = getattr(bubble, '_tool_cards_by_id', {}) or {}
            for tool_call_id, card in local_map.items():
                if not isinstance(card, ToolCallCard):
                    continue
                bound_results = getattr(card, '_bound_results', None)
                if not bound_results:
                    seg_data = getattr(card, '_seg_data', None)
                    if isinstance(seg_data, dict):
                        bound_results = seg_data.get('_bound_results')
                if not bound_results:
                    continue
                for result in bound_results:
                    content = str(result.get('content', '') or '')
                    success = result.get('success')
                    tool_name = str(result.get('tool_name', '') or '').strip()
                    if hasattr(card, 'set_result_text') and content:
                        card.set_result_text(content)
                    if hasattr(card, 'set_success') and success is not None:
                        card.set_success(bool(success))
                    if hasattr(card, 'set_status_text'):
                        if success is True:
                            card.set_status_text('执行完成')
                        elif success is False:
                            card.set_status_text('执行失败')
                        elif tool_name:
                            card.set_status_text(f'{tool_name} 已返回结果')
                logger.info("[服务端绑定] 结果已回填 | tool_call_id=%s | results=%s",
                            str(tool_call_id)[:20], len(bound_results))

    def _fuzzy_find_tool_card(self, result_bubble, block_key):
        """模糊查找 ToolCallCard：按 code_index + 气泡邻近度匹配。

        精确匹配（tool_call_id / block_key）失败时，解析 block_key 中的
        code_index，在 result_bubble 前方的 AI 气泡中查找对应 ToolCallCard。
        典型场景：AutoFix 修改代码后 block_key 变化，导致精确匹配失败。
        """
        if not block_key:
            return None
        parts = str(block_key).split(':')
        if len(parts) < 2:
            return None
        try:
            target_code_idx = int(parts[1])
        except ValueError:
            return None

        result_pos = -1
        for i, b in enumerate(self.bubbles_cache):
            if b is result_bubble:
                result_pos = i
                break
        if result_pos < 0:
            return None

        for i in range(result_pos - 1, max(result_pos - 6, -1), -1):
            bubble = self.bubbles_cache[i]
            if not isinstance(bubble, ChatBubble) or getattr(bubble, 'is_user', False):
                continue
            local_map = getattr(bubble, '_tool_cards_by_id', {}) or {}
            for key, card in local_map.items():
                if not isinstance(card, ToolCallCard):
                    continue
                key_parts = str(key).split(':')
                if len(key_parts) >= 2:
                    try:
                        if int(key_parts[1]) == target_code_idx:
                            logger.info("[绑定-模糊匹配] 匹配成功 | target_idx=%s | matched_key=%s | bubble_pos=%s",
                                        target_code_idx, str(key)[:25], i)
                            return card
                    except ValueError:
                        pass
        return None

    def _hide_bubble_if_empty(self, bubble):
        """检查气泡是否还有可见内容 widget，没有则隐藏整个气泡。"""
        if not isinstance(bubble, ChatBubble):
            return
        c_layout = getattr(bubble, 'c_layout', None)
        if c_layout is None:
            return
        has_visible_content = False
        for i in range(c_layout.count()):
            w = c_layout.itemAt(i).widget()
            if w is None:
                continue
            # 跳过 header（第一个 widget）
            if i == 0:
                continue
            if w.isVisible():
                has_visible_content = True
                break
        if not has_visible_content:
            bubble.setVisible(False)
            logger.debug("[跨消息绑定] 隐藏空气泡 | idx=%s", getattr(bubble, 'index', '?'))

    def update_tool_status(self, tool_call_id: str, payload: dict | None = None):
        key = str(tool_call_id or '').strip()
        if not key:
            return False
        card = self._tool_cards_by_id.get(key)
        if card is None:
            self._rebuild_tool_card_registry()
            card = self._tool_cards_by_id.get(key)
        if card is None:
            self._pending_tool_events.setdefault(key, []).append(
                ("status", payload, time.time())
            )
            logger.debug("[工具卡] update_tool_status 未找到卡片，存入pending | tool_call_id=%s | pending=%s",
                         key[:20], len(self._pending_tool_events.get(key, [])))
            return False
        if hasattr(card, 'update_runtime_status'):
            card.update_runtime_status(payload if isinstance(payload, dict) else {})
            logger.info("[工具卡] 状态已更新 | tool_call_id=%s | status=%s", key[:20], payload.get('status', '') if payload else '')
            return True
        return False

    def update_tool_result(self, tool_call_id: str, payload: dict | None = None):
        key = str(tool_call_id or '').strip()
        if not key:
            return False
        card = self._tool_cards_by_id.get(key)
        if card is None:
            self._rebuild_tool_card_registry()
            card = self._tool_cards_by_id.get(key)
        if card is None:
            self._pending_tool_events.setdefault(key, []).append(
                ("result", payload, time.time())
            )
            logger.debug("[工具卡] update_tool_result 未找到卡片，存入pending | tool_call_id=%s | pending=%s",
                         key[:20], len(self._pending_tool_events.get(key, [])))
            return False
        if not isinstance(payload, dict):
            payload = {}
        content = str(payload.get('content', '') or '')
        success = payload.get('success', None)
        tool_name = str(payload.get('tool_name', '') or '').strip()
        if hasattr(card, 'set_result_text') and content:
            card.set_result_text(content)
        if hasattr(card, 'set_success') and success is not None:
            card.set_success(bool(success))
        if hasattr(card, 'set_status_text'):
            if success is True:
                card.set_status_text('执行完成')
            elif success is False:
                card.set_status_text('执行失败')
            elif tool_name:
                card.set_status_text(f'{tool_name} 已返回结果')
        logger.info("[工具卡] 结果已回填 | tool_call_id=%s | success=%s | has_content=%s",
                    key[:20], success, bool(content))
        return True

    def _preload_image(self, url):
        if not url.startswith("http"): return url
        try:
            filename = hashlib.md5(url.encode()).hexdigest() + ".png"
            local_path = os.path.join(self.img_cache_dir, filename)
            
            if not os.path.exists(local_path):
                resp = requests.get(url, timeout=3, proxies={"http": None, "https": None})
                if resp.status_code == 200:
                    with open(local_path, "wb") as f: f.write(resp.content)
            
            if os.path.exists(local_path):
                return f"file:///{os.path.abspath(local_path).replace(os.sep, '/')}"
        except: pass
        return url

    def _render_next_slice(self):
        if self.current_render_idx >= len(self.pending_messages):
            self.render_timer.stop()
            self._cleanup_excess_bubbles()
            self._rebuild_tool_card_registry()
            self._replay_pending_tool_events()
            self._try_cross_message_tool_binding()
            # 保存渲染快照，供下次增量比对
            self._last_rendered_messages = list(self.pending_messages)
            if self.is_sticking_to_bottom:
                self.v_scrollbar.setValue(self.v_scrollbar.maximum())
                QTimer.singleShot(500, self.stop_sticking)
            return

        try:
            msg_data = self.pending_messages[self.current_render_idx]

            if msg_data.get('_hidden'):
                logger.debug("[渲染] 跳过隐藏消息 | idx=%s | role=%s",
                             msg_data.get('index', '?'), msg_data.get('role', '?'))
                self.current_render_idx += 1
                return

            idx = msg_data.get('index', self.current_render_idx+1)
            if 'segments' not in msg_data: msg_data['segments'] = []
            
            # [诊断] 打印每条消息的 segment 概要
            _segs = msg_data.get('segments', [])
            _role = msg_data.get('role', '?')
            _seg_summary = []
            for _s in _segs:
                if not isinstance(_s, dict):
                    _seg_summary.append(f'non-dict:{type(_s).__name__}')
                    continue
                _t = _s.get('type', '?')
                _c = str(_s.get('content', '') or '')
                _seg_summary.append(f'{_t}:{len(_c)}:{repr(_c[:40])}')
            logger.debug("[诊断] msg | idx=%s | role=%s | segs=%s", idx, _role, _seg_summary)
            
            for seg in msg_data['segments']:
                if seg.get('type') == 'image':
                    original_url = seg.get('url', '')
                    if original_url:
                        seg['url'] = self._preload_image(original_url)

            expected_is_user = (msg_data.get('role') == 'User')

            if self.current_render_idx < len(self.bubbles_cache):
                b = self.bubbles_cache[self.current_render_idx]
                if bool(getattr(b, 'is_user', False)) != bool(expected_is_user):
                    old_mid = getattr(b, 'message_id', '')
                    if old_mid and self._bubbles_by_id.get(old_mid) is b:
                        del self._bubbles_by_id[old_mid]
                    self.chat_layout.removeWidget(b)
                    b.deleteLater()
                    bubble = ChatBubble(msg_data, expected_is_user, index=idx)
                    bubble.request_set_snapshot.connect(self.request_set_snapshot.emit)
                    bubble.request_correct_turn.connect(self.request_correct_turn.emit)
                    bubble.request_remote_action.connect(self.request_manual_toggle.emit)
                    bubble.request_code_apply.connect(self.request_quick_apply.emit)
                    bubble.request_multi_select_mode.connect(self.request_enter_multi_select_mode.emit)
                    bubble.selection_changed.connect(self._on_bubble_selection_changed)
                    bubble.request_discard_relay.connect(self.request_discard_file.emit)
                    bubble.request_undiscard_relay.connect(self.request_undiscard_file.emit)
                    bubble.set_selection_mode(self.selection_mode, bubble.index in self.selected_indexes)
                    self.chat_layout.insertWidget(self.current_render_idx, bubble)
                    self.bubbles_cache[self.current_render_idx] = bubble
                    if bubble.message_id:
                        self._bubbles_by_id[bubble.message_id] = bubble
                else:
                    old_mid = getattr(b, 'message_id', '')
                    self._safe_update_bubble(b, msg_data, idx)
                    if old_mid and old_mid != b.message_id and self._bubbles_by_id.get(old_mid) is b:
                        del self._bubbles_by_id[old_mid]
                    if b.message_id:
                        self._bubbles_by_id[b.message_id] = b
                    b.set_selection_mode(self.selection_mode, b.index in self.selected_indexes)
            else:
                bubble = ChatBubble(msg_data, expected_is_user, index=idx)
                bubble.request_set_snapshot.connect(self.request_set_snapshot.emit)
                bubble.request_correct_turn.connect(self.request_correct_turn.emit)
                bubble.request_remote_action.connect(self.request_manual_toggle.emit)
                bubble.request_code_apply.connect(self.request_quick_apply.emit)
                bubble.request_multi_select_mode.connect(self.request_enter_multi_select_mode.emit)
                bubble.selection_changed.connect(self._on_bubble_selection_changed)
                bubble.request_discard_relay.connect(self.request_discard_file.emit)
                bubble.request_undiscard_relay.connect(self.request_undiscard_file.emit)
                bubble.set_selection_mode(self.selection_mode, bubble.index in self.selected_indexes)
                self.chat_layout.insertWidget(self.chat_layout.count()-1, bubble)
                self.bubbles_cache.append(bubble)
                if bubble.message_id:
                    self._bubbles_by_id[bubble.message_id] = bubble
                
            self.current_render_idx += 1
            
        except Exception as e:
            print(f"❌ [Slice Render Error] {e}")
            self.render_timer.stop()

    def _cleanup_excess_bubbles(self):
        while len(self.bubbles_cache) > len(self.pending_messages):
            b = self.bubbles_cache.pop()
            mid = getattr(b, 'message_id', '')
            if mid and self._bubbles_by_id.get(mid) is b:
                del self._bubbles_by_id[mid]
            self.chat_layout.removeWidget(b)
            b.deleteLater()