from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit,
)
from PySide6.QtCore import Signal

from app.ui.theme import Theme, theme_manager
from app.ui.components.settings.settings_widgets import (
    ScrollSafeComboBox, ScrollSafeSpinBox, SettingsCard, SettingsField,
)
from app.ui.components.settings.settings_styles import card_style
from app.ui.pages.console_page import UIHelper


class SettingsContextSection(QFrame):
    config_changed = Signal(dict)
    request_snapshot = Signal(list)
    section_id = "context"
    section_title = "快照推送"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctx_selected_session_idx = None
        self._ctx_sessions_initialized = False
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)

        title = QLabel("模块快照推送")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        subtitle = QLabel("向 AI 推送代码模块快照，提供项目上下文")
        subtitle.setObjectName("sectionSubtitle")
        root.addWidget(subtitle)

        card = SettingsCard("推送配置")
        self._card = card

        self.ctx_pack_combo = ScrollSafeComboBox()
        self.ctx_pack_combo.addItem("UI(Chat) - 聊天界面", "ui_chat")
        self.ctx_pack_combo.addItem("Core(Worker) - Worker/State", "worker_state")
        self.ctx_pack_combo.addItem("System(Update) - OTA/更新", "update_ota")
        self.ctx_pack_combo.addItem("Driver(Web) - 网页交互/解析", "driver_web")
        self.ctx_pack_combo.addItem("Server(Auth) - 服务端/鉴权", "server_auth")
        self.ctx_pack_combo.addItem("Tests - 测试套件", "tests")
        self.ctx_pack_combo.addItem("DevTools - 设置/控制台", "devtools")
        card.add_field(SettingsField("模块包", self.ctx_pack_combo))

        session_row = QHBoxLayout()
        session_row.setSpacing(12)
        self.ctx_session_combo = ScrollSafeComboBox()
        self.ctx_session_combo.currentIndexChanged.connect(self._on_session_combo_changed)
        self.ctx_session_spin = ScrollSafeSpinBox()
        self.ctx_session_spin.setRange(0, 9999)
        self.ctx_session_spin.setValue(0)
        session_row.addWidget(QLabel("指派会话:"), 0)
        session_row.addWidget(self.ctx_session_combo, 2)
        session_row.addWidget(QLabel("手动 Index:"), 0)
        session_row.addWidget(self.ctx_session_spin, 1)
        card.add_layout(session_row)

        tip = QLabel("会话列表来自左侧会话栏（2秒刷新）")
        tip.setObjectName("sectionSubtitle")
        card.add_widget(tip)

        self.ctx_goal_edit = QPlainTextEdit()
        self.ctx_goal_edit.setPlaceholderText("可选：描述本次任务目标...")
        self.ctx_goal_edit.setFixedHeight(80)
        card.add_field(SettingsField("任务目标", self.ctx_goal_edit))

        root.addWidget(card)

        card2 = SettingsCard("快照操作")
        self._card2 = card2

        snap_row = QHBoxLayout()
        snap_row.addStretch()
        self.snap_btn = QPushButton("生成快照")
        self.snap_btn.clicked.connect(self._on_snap_clicked)
        snap_row.addWidget(self.snap_btn)
        card2.add_layout(snap_row)

        root.addWidget(card2)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.ctx_push_btn = QPushButton("推送模块快照")
        self.ctx_push_btn.clicked.connect(self._push_context_pack)
        btn_row.addWidget(self.ctx_push_btn)
        root.addLayout(btn_row)

        root.addStretch()

    def _on_snap_clicked(self):
        self.snap_btn.setEnabled(False)
        self.snap_btn.setText("生成中...")
        self.request_snapshot.emit([])
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: [self.snap_btn.setEnabled(True), self.snap_btn.setText("生成快照")])

    def load_from_config(self, config, api_config=None):
        pass

    def collect_config(self):
        return {}

    def _on_session_combo_changed(self):
        try:
            idx = self.ctx_session_combo.currentData()
            if idx is None:
                return
            self._ctx_selected_session_idx = int(idx)
            self.ctx_session_spin.setValue(int(idx))
        except Exception:
            pass

    def on_sessions_update(self, sessions):
        if not isinstance(sessions, list):
            return

        current_selected = self._ctx_selected_session_idx
        if current_selected is None:
            try:
                current_selected = self.ctx_session_combo.currentData()
                if current_selected is not None:
                    current_selected = int(current_selected)
            except Exception:
                current_selected = None

        items = []
        active_idx = None
        for s in sessions:
            try:
                idx = int(s.get("index", 0))
                title = str(s.get("title", "New Chat"))
                active = bool(s.get("active", False))
                if active:
                    active_idx = idx
                label = f"{'✅ ' if active else ''}{title} (#{idx})"
                items.append((idx, label))
            except Exception:
                pass

        if not items:
            return

        self.ctx_session_combo.blockSignals(True)
        self.ctx_session_combo.clear()
        for idx, label in items:
            self.ctx_session_combo.addItem(label, idx)

        chosen = None
        if current_selected is not None and any(idx == current_selected for idx, _ in items):
            chosen = current_selected
        else:
            if not self._ctx_sessions_initialized and active_idx is not None:
                chosen = active_idx
            else:
                chosen = items[0][0]

        try:
            for i in range(self.ctx_session_combo.count()):
                if int(self.ctx_session_combo.itemData(i)) == int(chosen):
                    self.ctx_session_combo.setCurrentIndex(i)
                    break
            self._ctx_selected_session_idx = int(chosen)
            self.ctx_session_spin.setValue(int(chosen))
        except Exception:
            pass

        self._ctx_sessions_initialized = True
        self.ctx_session_combo.blockSignals(False)

    def _push_context_pack(self):
        main_win = self.window()
        worker = getattr(main_win, "worker", None)
        if not worker:
            UIHelper.warning(self, "错误", "未找到 Worker 实例")
            return
        if not hasattr(worker, "send_context_pack"):
            UIHelper.warning(self, "不支持", "当前 Worker 不支持 Context Pack 推送")
            return

        pack_key = self.ctx_pack_combo.currentData()
        idx = None
        try:
            idx = self.ctx_session_combo.currentData()
        except Exception:
            idx = None
        if idx is None:
            idx = int(self.ctx_session_spin.value())
        else:
            try:
                idx = int(idx)
            except Exception:
                idx = int(self.ctx_session_spin.value())

        goal = self.ctx_goal_edit.toPlainText().strip()
        worker.send_context_pack(pack_key, idx, goal)
        UIHelper.info(self, "已入队", f"Context Pack 已入队发送。\nPack: {pack_key}\nSession: {idx}")

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")

        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "sectionTitle":
                lbl.setStyleSheet(Theme.section_title())
            elif lbl.objectName() == "sectionSubtitle":
                lbl.setStyleSheet(Theme.section_subtitle())

        for card in [self._card, self._card2]:
            card.setStyleSheet(card_style())

        for cb in [self.ctx_pack_combo, self.ctx_session_combo]:
            cb.setStyleSheet(Theme.combo_box())

        self.ctx_session_spin.setStyleSheet(Theme.input_field())
        self.ctx_goal_edit.setStyleSheet(Theme.log_editor())
        self.ctx_push_btn.setStyleSheet(Theme.button_primary())
        self.snap_btn.setStyleSheet(Theme.button_success_small())
