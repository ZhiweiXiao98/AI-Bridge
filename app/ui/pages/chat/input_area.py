# filename: app/ui/pages/chat/input_area.py
import os
import uuid
import unicodedata
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QPlainTextEdit, QListWidget, QListWidgetItem,
                               QFileDialog, QSizePolicy)
from PySide6.QtCore import Qt, QTimer, Signal, QMimeData
from PySide6.QtGui import QIcon, QDrag
from app.ui.components.input import ChatInput
from app.ui.theme import Theme, Palette, theme_manager


class SuggestionChip(QPushButton):
    chip_clicked = Signal(str)
    chip_drag_started = Signal(str)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._suggestion_text = str(text or "")
        self._wrap_width_px = 0
        self.setToolTip(self._suggestion_text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMaximumWidth(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._update_display_text()
        self.clicked.connect(self._on_click)

    def _wrap_display_text(self, text: str, max_width_px: int) -> str:
        """按像素宽度插入换行，避免建议气泡在不同宽度下显示不全。"""
        text = str(text or "").strip()
        if not text:
            return ""

        metrics = self.fontMetrics()
        wrapped_lines = []
        for raw_line in text.splitlines():
            line = ""
            line_width = 0
            for ch in raw_line:
                ch_width = metrics.horizontalAdvance(ch)
                if line and line_width + ch_width > max_width_px:
                    wrapped_lines.append(line)
                    line = ch
                    line_width = ch_width
                else:
                    line += ch
                    line_width += ch_width
            if line:
                wrapped_lines.append(line)
        return "\n".join(wrapped_lines)

    def _update_display_text(self):
        if self._wrap_width_px > 0:
            self.setText(self._wrap_display_text(self._suggestion_text, self._wrap_width_px))
        else:
            self.setText(self._suggestion_text)
        self.updateGeometry()

    def set_wrap_width(self, max_width_px: int):
        max_width_px = max(80, int(max_width_px or 0))
        if self._wrap_width_px == max_width_px:
            return
        self._wrap_width_px = max_width_px
        self._update_display_text()

    @property
    def suggestion_text(self) -> str:
        return self._suggestion_text

    def _on_click(self):
        self.chip_clicked.emit(self._suggestion_text)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(self._suggestion_text)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
            self.chip_drag_started.emit(self._suggestion_text)
        else:
            super().mouseMoveEvent(event)


class SuggestionBar(QFrame):
    suggestion_adopted = Signal(str)
    bar_dismissed = Signal()  # 建议栏被关闭（非采纳方式）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuggestionBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._chips = []
        self.hide()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.bar_dismissed.emit()

    def _refresh_chip_wraps(self):
        if not self._chips:
            return
        content_width = max(0, self.contentsRect().width())
        chip_width = max(120, content_width - 24)
        for chip in self._chips:
            chip.set_wrap_width(chip_width)

    def show_suggestions(self, suggestions: list, auto_dismiss_seconds: int = 8):
        self._clear_chips()
        self._layout.setContentsMargins(48, 0, 88, 0)

        for text in suggestions:
            chip = SuggestionChip(str(text))
            chip.setMaximumWidth(16777215)
            chip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            chip.chip_clicked.connect(self._on_chip_clicked)
            self._layout.addWidget(chip)
            self._chips.append(chip)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        close_row.addWidget(close_btn)
        self._layout.addLayout(close_row)

        self.show()
        self._layout.activate()
        self._refresh_chip_wraps()
        self.adjustSize()
        self.updateGeometry()
        if self.parentWidget():
            self.parentWidget().updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_chip_wraps()

    def _clear_chips(self):
        for chip in self._chips:
            try:
                chip.chip_clicked.disconnect(self._on_chip_clicked)
            except Exception:
                pass
            self._layout.removeWidget(chip)
            chip.deleteLater()
        self._chips.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            sub_layout = item.layout()
            if sub_layout:
                while sub_layout.count():
                    sub_item = sub_layout.takeAt(0)
                    sub_w = sub_item.widget()
                    if sub_w:
                        sub_w.deleteLater()

    def _on_chip_clicked(self, text: str):
        self.suggestion_adopted.emit(text)
        self.hide()

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"#SuggestionBar {{ background: transparent; }}")
        for chip in self._chips:
            chip.setStyleSheet(f"""
                QPushButton {{
                    background-color: {p.BG_TERTIARY};
                    color: {p.TEXT_PRIMARY};
                    border: 1px solid {p.BORDER};
                    border-radius: 14px;
                    padding: 6px 12px;
                    font-size: 12px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: {p.BORDER};
                    border-color: {p.ACCENT_PRIMARY};
                }}
            """)

class InputArea(QFrame):
    request_send_text = Signal(str)
    request_send_compound = Signal(str, list)
    request_upload = Signal(str)
    log_message = Signal(str)
    extra_space_requested = Signal(int)  # 额外空间需求（像素），0 表示收回

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InputContainer")
        self.setMinimumHeight(64)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        self.pending_attachments = []
        self.local_browser_submit = None
        self._local_browser_submission = None
        self._failed_browser_submission = None
        self.queued_payload = None
        self.is_ai_busy = False
        self.is_view_paused = False
        self.last_ai_state_payload = None # 缓存上次状态以便重绘
        self._pending_guide_active = False  # 是否已点击「随工具发送」

        self.init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        il = QVBoxLayout(self)
        il.setContentsMargins(10, 6, 10, 10)
        il.setSpacing(3)

        self.ai_state_bar = QLabel("AI 就绪")
        self.ai_state_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ai_state_bar.setFixedHeight(20)
        self.ai_state_bar.setMinimumWidth(0)
        self.ai_state_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        il.addWidget(self.ai_state_bar)

        self.suggestion_bar = SuggestionBar()
        self.suggestion_bar.suggestion_adopted.connect(self._adopt_suggestion)
        self.suggestion_bar.bar_dismissed.connect(self._emit_suggestion_collapse)
        il.addWidget(self.suggestion_bar)

        # 待发消息悬浮条：AI busy 时显示，供用户选择「随工具发送」或取消
        self.pending_bar = QFrame()
        self.pending_bar.setObjectName("PendingBar")
        self.pending_bar.hide()
        pending_layout = QHBoxLayout(self.pending_bar)
        pending_layout.setContentsMargins(8, 4, 8, 4)
        pending_layout.setSpacing(6)
        self.pending_bar_label = QLabel()
        self.pending_bar_label.setMaximumWidth(300)
        pending_layout.addWidget(self.pending_bar_label, 1)
        self.pending_guide_btn = QPushButton("⚡ 随工具发送")
        self.pending_guide_btn.setFixedHeight(26)
        self.pending_guide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pending_guide_btn.clicked.connect(self._on_guide_send)
        pending_layout.addWidget(self.pending_guide_btn)
        self.pending_cancel_btn = QPushButton("✕")
        self.pending_cancel_btn.setFixedSize(26, 26)
        self.pending_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pending_cancel_btn.clicked.connect(self.cancel_queue)
        pending_layout.addWidget(self.pending_cancel_btn)
        il.addWidget(self.pending_bar)

        self.staging_area = QPlainTextEdit()
        self.staging_area.setPlaceholderText("提示词暂存区...")
        self.staging_area.setFixedHeight(80)
        self.staging_area.setMinimumWidth(0)
        self.staging_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.staging_area.hide()

        self.attachment_list = QListWidget()
        self.attachment_list.setFixedHeight(60)
        self.attachment_list.setFlow(QListWidget.Flow.LeftToRight)
        self.attachment_list.hide()
        self.attachment_list.itemClicked.connect(self.remove_attachment)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0,0,0,0)

        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedSize(32, 32)
        self.attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.attach_btn.clicked.connect(self.on_attach)

        self.input_box = ChatInput()
        self.input_box.setObjectName("MsgInput")
        self.input_box.setMinimumWidth(0)
        self.input_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.input_box.setPlaceholderText("输入指令给 AI...")
        self.input_box.image_pasted_signal.connect(self.add_attachment)
        self.input_box.enter_pressed_signal.connect(self.on_send)

        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("SendBtn")
        self.send_btn.setFixedSize(60, 32)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self.on_send)

        input_row.addWidget(self.attach_btn)
        input_row.addWidget(self.input_box)
        input_row.addWidget(self.send_btn)

        self.btn_close_stage = QPushButton("×")
        self.btn_close_stage.setFixedSize(20, 20)
        self.btn_close_stage.clicked.connect(self.hide_staging)

        il.addWidget(self.staging_area)
        il.addWidget(self.attachment_list)
        il.addLayout(input_row)

    def apply_theme(self):
        p = theme_manager.get_palette()

        self.setStyleSheet(f"#InputContainer {{ background-color: {p.BG_PRIMARY}; border-top:         1px solid {p.BORDER}; }}")

        # 刷新状态栏样式 (如果已有状态)
        if self.last_ai_state_payload:
            self.update_ai_state(self.last_ai_state_payload)
        else:
            self.ai_state_bar.setStyleSheet(f"background-color: {p.BG_TERTIARY}; color: {p.            TEXT_SECONDARY}; border: 1px solid {p.BORDER}; border-radius: 4px; padding: 2px;             font-size: 10px;")

        self.staging_area.setStyleSheet(f"QPlainTextEdit {{ background-color: {p.        BG_TERTIARY}; color: {p.ACCENT_PRIMARY}; border: 1px dashed {p.ACCENT_PRIMARY};         border-radius: 6px; padding: 8px; font-family: Consolas; }}")

        self.attachment_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; }}
            QListWidget::item {{ background: {p.BG_TERTIARY}; border-radius: 4px;             margin-right: 5px; color: {p.TEXT_PRIMARY}; padding: 2px; }}
            QListWidget::item:hover {{ background: {p.BORDER}; }}
        """)

        # 附件按钮 (圆形)
        self.attach_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {p.BG_TERTIARY}; color: {p.TEXT_SECONDARY};             border-radius: 20px; font-size: 20px; border: 1px solid {p.BORDER}; }}
            QPushButton:hover {{ background-color: {p.BORDER}; color: {p.TEXT_PRIMARY}; }}
        """)

        # 输入框
        self.input_box.setStyleSheet(f"""
            background-color: {p.BG_TERTIARY};
            color: {p.TEXT_PRIMARY};
            border: 1px solid {p.BORDER};
            border-radius: 8px;
            padding: 8px;
            font-size: 13px;
            font-family: Segoe UI Emoji, Apple Color Emoji, Noto Color Emoji, Segoe UI Symbol, Segoe UI, sans-serif;
        """)

        self.send_btn.setStyleSheet(Theme.button_primary())
        self.btn_close_stage.setStyleSheet(f"border: none; color: {p.TEXT_SECONDARY};         font-weight: bold;")
        self.pending_bar.setStyleSheet(f"#PendingBar {{ background-color: {p.BG_TERTIARY}; border: 1px solid {p.BTN_WARNING}; border-radius: 6px; }}")
        self.pending_bar_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        self.pending_guide_btn.setStyleSheet(f"background-color: {p.BTN_WARNING}; color: white; border-radius: 4px; padding: 2px 8px; font-size: 12px;")
        self.pending_cancel_btn.setStyleSheet(f"background-color: transparent; color: {p.TEXT_SECONDARY}; border: none; font-size: 14px;")

    def set_view_paused(self, paused):
        self.is_view_paused = paused

    def update_ai_state(self, payload):
        self.last_ai_state_payload = payload # 缓存
        p = theme_manager.get_palette()

        if isinstance(payload, str):
            state = payload
            user = None
        else:
            state = payload.get("state", "idle")
            user = payload.get("user")

        user_text = f"(操作者: {user})" if user else ""
        self.is_ai_busy = state in ("busy", "tool_executing", "fixing", "switching")

        if self.is_ai_busy:
            self.suggestion_bar.hide()

        if state == "busy":
            self.ai_state_bar.setText(f"✨ AI 正在思考/生成中... {user_text}")
            self.ai_state_bar.setStyleSheet(f"background-color: {p.BTN_SUCCESS}; color: white; font-weight: bold; border-radius: 4px; padding: 2px;")

        elif state == "tool_executing":
            self.ai_state_bar.setText(f"🔧 工具执行中，请稍候... {user_text}")
            self.ai_state_bar.setStyleSheet(f"background-color: {p.ACCENT_PRIMARY}; color: white; font-weight: bold; border-radius: 4px; padding: 2px;")

        elif state == "fixing":
            self.ai_state_bar.setText(f"🔨 正在整理代码/修复格式... {user_text}")
            self.ai_state_bar.setStyleSheet(f"background-color: {p.BTN_WARNING}; color: white; font-weight: bold; border-radius: 4px; padding: 2px;")

        elif state == "switching":
            self.ai_state_bar.setText(f"🔄 正在切换会话窗口... {user_text}")
            self.ai_state_bar.setStyleSheet(f"background-color: {p.ACCENT_PRIMARY}; color: white; font-weight: bold; border-radius: 4px; padding: 2px;")

        elif state == "idle":
            self.ai_state_bar.setText("🟢 AI 就绪 (Idle)")
            self.ai_state_bar.setStyleSheet(f"background-color: {p.BG_TERTIARY}; color: {p.            TEXT_SECONDARY}; border: 1px solid {p.BORDER}; border-radius: 4px; padding: 2px;             font-size: 10px;")

            if self.queued_payload:
                QTimer.singleShot(3000, self.check_auto_send)

        self.ai_state_bar.show()

    def _browser_draft_snapshot(self):
        return (self.staging_area.toPlainText(), self.input_box.toPlainText(), tuple(self.pending_attachments))

    def _submit_local_browser(self, text, attachments):
        if self._local_browser_submission is not None:
            self.log_message.emit("正在等待网页确认上一条消息，未重复发送")
            return False
        request_id = uuid.uuid4().hex
        snapshot = self._browser_draft_snapshot()
        self._local_browser_submission = (request_id, snapshot, text, tuple(attachments))
        accepted = self.local_browser_submit(text, list(attachments), request_id)
        if not accepted:
            self._local_browser_submission = None
            self.log_message.emit("浏览器尚未接受发送，草稿已保留")
            return False
        self.send_btn.setEnabled(False)
        self.log_message.emit("正在等待网页确认发送；草稿暂时保留")
        return True

    def on_browser_send_result(self, payload):
        if not isinstance(payload, dict) or self._local_browser_submission is None:
            return
        request_id, snapshot, text, attachments = self._local_browser_submission
        if payload.get("request_id") != request_id:
            return
        self._local_browser_submission = None
        self.send_btn.setEnabled(True)
        if payload.get("ok"):
            if self._browser_draft_snapshot() == snapshot:
                self.clear_inputs()
            self._failed_browser_submission = None
            self.log_message.emit("网页已确认收到消息")
        else:
            self._failed_browser_submission = (snapshot, text, attachments)
            self.log_message.emit(str(payload.get("message") or "网页未确认收到消息") + "；未清除草稿")

    def cancel_local_browser_submission(self):
        # Late acknowledgements cannot clear a draft after the user's Stop.
        self._local_browser_submission = None
        self.send_btn.setEnabled(True)

    def check_auto_send(self):
        if not self.is_ai_busy and self.queued_payload:
            # 已通过「随工具发送」路径消费，跳过重复发送
            if self._pending_guide_active:
                self.log_message.emit("✅ 待发消息已随工具结果发出，跳过重复发送")
                self.cancel_queue()
                self.clear_inputs()
                return
            self.log_message.emit("🚀 正在自动发送挂起任务...")
            text, attachments = self.queued_payload
            if callable(self.local_browser_submit):
                accepted = self._submit_local_browser(text, attachments)
                self.cancel_queue()
                if not accepted:
                    self.log_message.emit("待发消息没有发送，内容已保留供重试")
                return
            if hasattr(self.worker, 'send_compound'):
                self.worker.send_compound(text, attachments)
            else:
                self.request_send_text.emit(text)
            self.cancel_queue()
            self.clear_inputs()

    def on_send(self):
        stage_text = self.staging_area.toPlainText().strip()
        user_text = self.input_box.toPlainText().strip()
        final_text = (stage_text + "\n" + user_text).strip()

        if not final_text and not self.pending_attachments: return

        if self.is_ai_busy or self.is_view_paused:
            p = theme_manager.get_palette()
            self.queued_payload = (final_text, list(self.pending_attachments))
            self._pending_guide_active = False
            self.suggestion_bar.hide()
            # 显示待发悬浮条，不自动调 set_pending_message
            # 只有用户主动点「随工具发送」才会绑定到工具回流
            preview = final_text[:30] + ("..." if len(final_text) > 30 else "")
            self.pending_bar_label.setText(f"⏳ 待发: {preview}")
            self.pending_guide_btn.setText("⚡ 随工具发送")
            self.pending_guide_btn.setEnabled(True)
            self.pending_bar.show()
            self.input_box.setReadOnly(True)
            self.input_box.setStyleSheet(f"background-color: {p.BG_PRIMARY}; color: {p.TEXT_SECONDARY}; border: 1px solid {p.BORDER}; border-radius: 8px; padding: 12px;")
            self.send_btn.setText("⏳ 待发")
            self.send_btn.setStyleSheet(f"background-color: {p.BTN_WARNING}; color: white; border-radius: 8px; font-weight: bold;")
            try: self.send_btn.clicked.disconnect()
            except: pass
            self.send_btn.clicked.connect(self.cancel_queue)
            self.log_message.emit("⏳ 任务已挂起，等待 AI 就绪...")
            return

        if callable(self.local_browser_submit):
            self._submit_local_browser(final_text, list(self.pending_attachments))
            return

        # 根据内容类型分发：有附件优先走 compound，由上层页面按模式处理
        if self.pending_attachments:
            self.request_send_compound.emit(final_text, list(self.pending_attachments))
        else:
            self.request_send_text.emit(final_text)

        self.clear_inputs()
        self.log_message.emit("✅ 发送指令")

    def cancel_queue(self):
        self.queued_payload = None
        self._pending_guide_active = False
        self.pending_bar.hide()
        # 取消时清除 worker 侧的 pending（如果已绑定）
        if hasattr(self.worker, 'pending_user_message'):
            self.worker.pending_user_message = None
        self.input_box.setReadOnly(False)
        self.apply_theme()
        self.send_btn.setText("发送")
        try: self.send_btn.clicked.disconnect()
        except: pass
        self.send_btn.clicked.connect(self.on_send)
        self.log_message.emit("🚫 挂起任务已取消")

    def clear_inputs(self):
        self.input_box.clear()
        self.staging_area.clear()
        self.staging_area.hide()
        self.pending_attachments.clear()
        self.attachment_list.clear()
        self.attachment_list.hide()

    def on_attach(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择附件", "", "All Files (*)")
        if p: self.add_attachment(p)

    def add_attachment(self, path):
        if path in self.pending_attachments: return
        self.pending_attachments.append(path)

        item = QListWidgetItem()
        name = os.path.basename(path)
        item.setText(name)
        item.setToolTip(f"{path}\n(点击移除)")
        ext = os.path.splitext(name)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']: item.setIcon(QIcon(path))
        else: item.setIcon(QIcon("assets/icons/file.png"))

        self.attachment_list.addItem(item)
        self.attachment_list.show()
        self.log_message.emit(f"📎 已添加附件: {name}")

    def remove_attachment(self, item):
        row = self.attachment_list.row(item)
        self.attachment_list.takeItem(row)
        target_name = item.text()
        for p in self.pending_attachments:
            if os.path.basename(p) == target_name:
                self.pending_attachments.remove(p); break

        if self.attachment_list.count() == 0: self.attachment_list.hide()

    def show_staging(self, text):
        self.staging_area.setPlainText(text)
        self.staging_area.setVisible(True)
        self.staging_area.setFocus()

    def hide_staging(self):
        self.staging_area.hide()
        self.staging_area.clear()

    def show_suggestions(self, suggestions: list):
        if self.is_ai_busy:
            return
        self.suggestion_bar.show_suggestions(suggestions)
        self.suggestion_bar.apply_theme()
        # 通知父级需要额外空间
        QTimer.singleShot(50, self._emit_suggestion_height)

    def _adopt_suggestion(self, text: str):
        cursor = self.input_box.textCursor()
        if str(text or "").startswith("$"):
            plain = self.input_box.toPlainText()
            pos = cursor.position()
            start = pos
            while start > 0 and not plain[start - 1].isspace():
                start -= 1
            if start < pos and plain[start:pos].startswith("/"):
                cursor.setPosition(start)
                cursor.setPosition(pos, cursor.MoveMode.KeepAnchor)
                cursor.insertText(text + " ")
            else:
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText(text + " ")
        else:
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
        self.input_box.setTextCursor(cursor)
        self.input_box.setFocus()
        self._emit_suggestion_collapse()

    def _emit_suggestion_height(self):
        """建议栏显示后，通知需要额外空间。"""
        if self.suggestion_bar.isVisible():
            h = self.suggestion_bar.sizeHint().height()
            self.extra_space_requested.emit(max(h, 60))

    def _emit_suggestion_collapse(self):
        """建议栏隐藏后，收回额外空间。"""
        self.extra_space_requested.emit(0)

    def _on_guide_send(self):
        """用户点击「随工具发送」，将待发消息绑定到下次工具回流。"""
        if not self.queued_payload:
            return
        text, attachments = self.queued_payload
        if hasattr(self.worker, 'set_pending_message'):
            self.worker.set_pending_message(text, attachments)
        self._pending_guide_active = True
        self.pending_guide_btn.setText("⏳ 已绑定，等待工具完成...")
        self.pending_guide_btn.setEnabled(False)
        self.log_message.emit("⚡ 待发消息已绑定到下次工具回流")

    def on_pending_consumed(self):
        """worker 消费了待发消息后回调，清除悬浮条和排队状态。"""
        import logging
        logging.getLogger(__name__).info("[pending] on_pending_consumed 被调用")
        self.log_message.emit("✅ 待发消息已随工具结果发出")
        self.cancel_queue()
        self.clear_inputs()
