# filename: app/ui/components/panels/context_workspace_panel.py
import json
import os

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QFrame, QComboBox, QCheckBox, QScrollArea
)
from app.core.app_constants import APP_ROOT
from app.ui.components.animated_reorder_container import AnimatedReorderContainer
from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager
from app.ui.components.panels.context_workspace_panel_presenter import ContextWorkspacePanelPresenter
from app.ui.dialogs.context_detail_dialog import ContextDetailDialog


MODULE_ORDER_KEY = 'context_workspace'
DEFAULT_MODULE_ORDER = ['system', 'task', 'memory', 'capacity', 'compact']


class _ContextModuleCard(QFrame):
    def __init__(self, module_id: str, title: str, parent=None):
        super().__init__(parent)
        self.module_id = module_id
        self.setObjectName('ContextModuleCard')
        self.setFrameShape(QFrame.NoFrame)
        self.setAcceptDrops(False)
        self._build_ui(title)
        self.apply_card_theme()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)
        super().mousePressEvent(event)

    def _build_ui(self, title: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self.drag_lbl = QLabel('⋮⋮')
        self.drag_lbl.setObjectName('ContextModuleGrip')
        self.drag_lbl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.drag_lbl.setFixedWidth(12)
        layout.addWidget(self.drag_lbl)

        self.drag_lbl.setCursor(Qt.OpenHandCursor)
        main_col = QVBoxLayout()
        main_col.setContentsMargins(0, 0, 0, 0)
        main_col.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName('ContextModuleTitle')
        self.status_badge = QLabel('-')
        self.status_badge.setObjectName('ContextModuleBadge')
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setMinimumWidth(64)
        self.status_badge.setMinimumHeight(22)

        head.addWidget(self.title_lbl)
        head.addStretch()
        head.addWidget(self.status_badge)
        main_col.addLayout(head)

        self.summary_lbl = QLabel('-')
        self.summary_lbl.setObjectName('ContextModuleSummary')
        self.summary_lbl.setWordWrap(False)
        main_col.addWidget(self.summary_lbl)

        self.detail_lbl = QLabel('')
        self.detail_lbl.setObjectName('ContextModuleDetail')
        self.detail_lbl.setWordWrap(False)
        self.detail_lbl.setVisible(False)
        main_col.addWidget(self.detail_lbl)

        layout.addLayout(main_col, 1)

        action_col = QVBoxLayout()
        action_col.setContentsMargins(0, 0, 0, 0)
        action_col.setSpacing(3)
        self.primary_btn = QPushButton('查看')
        self.secondary_btn = QPushButton('更多')
        self.primary_btn.setMinimumWidth(80)
        self.secondary_btn.setMinimumWidth(80)
        self.primary_btn.setMinimumHeight(26)
        self.secondary_btn.setMinimumHeight(26)
        action_col.addWidget(self.primary_btn)
        action_col.addWidget(self.secondary_btn)
        layout.addLayout(action_col)

    def set_status(self, text: str):
        value = text or '-'
        self.status_badge.setText(value)
        self.status_badge.setToolTip(value)

    def set_summary(self, text: str):
        value = (text or '-').replace('\n', ' · ')
        self.summary_lbl.setText(value)
        self.summary_lbl.setToolTip(text or '-')

    def set_detail(self, text: str):
        value = (text or '').strip()
        compact_value = value.replace('\n', ' · ')
        self.detail_lbl.setVisible(bool(value))
        self.detail_lbl.setText(compact_value)
        self.detail_lbl.setToolTip(value)

    def apply_card_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"""
            QFrame#ContextModuleCard {{
                background-color: {p.BG_SECONDARY};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QLabel#ContextModuleGrip {{
                color: {p.TEXT_SECONDARY};
                font-size: 12px;
                background: transparent;
                border: none;
            }}
            QLabel#ContextModuleTitle {{
                color: {p.TEXT_PRIMARY};
                font-size: 12px;
                font-weight: 700;
                background: transparent;
                border: none;
            }}
            QLabel#ContextModuleSummary {{
                color: {p.TEXT_PRIMARY};
                font-size: 11px;
                background: transparent;
                border: none;
                min-height: 16px;
                padding: 0;
            }}
            QLabel#ContextModuleDetail {{
                color: {p.TEXT_SECONDARY};
                font-size: 10px;
                background: transparent;
                border: none;
                min-height: 14px;
                padding: 0;
            }}
            QLabel#ContextModuleBadge {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 700;
                min-height: 22px;
            }}
        """)


class ContextWorkspacePanel(DockablePanel):
    refresh_requested = Signal(str)
    request_conversations = Signal()
    save_system_requested = Signal(str, str)
    save_working_requested = Signal(str, object)
    clear_working_requested = Signal(str)
    clear_long_term_requested = Signal(str)
    manual_compact_requested = Signal(str)
    request_snapshot_requested = Signal(str)
    manage_plan_binding_requested = Signal(str)
    open_common_phrases_requested = Signal()

    def __init__(self, parent=None):
        super().__init__('context_workspace', '上下文工作台', '🧠', parent)
        self._payload = {}
        self._conversation_items = []
        self._current_conversation_id = ''
        self._suppress_combo_signal = False
        self._view_model = {}
        self._module_cards = {}
        self._module_titles = {
            'system': '系统提示词',
            'task': '当前任务',
            'memory': '长期记忆',
            'capacity': '容量健康',
            'compact': '历史压缩',
        }
        self.init_content()
        theme_manager.theme_changed.connect(self.apply_content_theme)
        self.apply_content_theme()
        self._build_module_list()

    def create_content(self):
        body = QWidget()
        body.setObjectName('ContextWorkspaceRoot')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QFrame()
        toolbar.setObjectName('ContextToolbar')
        top = QHBoxLayout(toolbar)
        top.setContentsMargins(8, 6, 8, 6)
        top.setSpacing(6)

        self.target_lbl = QLabel('目标对话')
        self.target_lbl.setObjectName('ContextSectionHint')

        self.conv_combo = QComboBox()
        self.conv_combo.setMinimumWidth(180)
        self.conv_combo.setToolTip('选择要管理的 API 对话。')
        self.conv_combo.currentIndexChanged.connect(self._on_conversation_changed)

        self.refresh_list_btn = QPushButton('刷新列表')
        self.refresh_list_btn.setToolTip('重新加载 API 对话列表。')
        self.refresh_list_btn.clicked.connect(self.request_conversations.emit)

        self.follow_checkbox = QCheckBox('跟随当前')
        self.follow_checkbox.setChecked(True)
        self.follow_checkbox.setToolTip('手动切换目标后会退出跟随模式。')

        self.refresh_btn = QPushButton('刷新')
        self.refresh_btn.setToolTip('重新读取当前目标对话的上下文信息。')
        self.refresh_btn.clicked.connect(self._emit_refresh)

        self.snapshot_btn = QPushButton('快照')
        self.snapshot_btn.setToolTip('查看最近一次实际发送给模型的完整上下文快照。')
        self.snapshot_btn.clicked.connect(lambda: self.request_snapshot_requested.emit(self.current_conversation_id()))

        top.addWidget(self.target_lbl)
        top.addWidget(self.conv_combo, 1)
        top.addWidget(self.refresh_list_btn)
        top.addWidget(self.follow_checkbox)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.snapshot_btn)
        layout.addWidget(toolbar)

        self.overview_card = QFrame()
        self.overview_card.setObjectName('ContextOverviewCard')
        self.overview_card.setToolTip('显示当前目标对话、配置模式与上下文模块状态摘要。更多解释性信息通过悬浮提示查看。')
        overview_layout = QVBoxLayout(self.overview_card)
        overview_layout.setContentsMargins(8, 6, 8, 6)
        overview_layout.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self.overview_title_lbl = QLabel('未加载对话')
        self.overview_title_lbl.setObjectName('ContextOverviewTitle')
        self.overview_title_lbl.setToolTip('当前正在查看的 API 对话标题。')
        self.overview_profile_badge = QLabel('-')
        self.overview_profile_badge.setObjectName('ContextOverviewBadge')
        self.overview_profile_badge.setToolTip('运行配置 / Profile。')
        self.overview_mode_badge = QLabel('-')
        self.overview_mode_badge.setObjectName('ContextOverviewBadge')
        self.overview_mode_badge.setToolTip('当前工作模式。')
        self.overview_follow_badge = QLabel('-')
        self.overview_follow_badge.setObjectName('ContextOverviewBadge')
        self.overview_follow_badge.setToolTip('当前是否跟随 active API 对话。')
        title_row.addWidget(self.overview_title_lbl)
        title_row.addStretch()
        title_row.addWidget(self.overview_profile_badge)
        title_row.addWidget(self.overview_mode_badge)
        title_row.addWidget(self.overview_follow_badge)
        overview_layout.addLayout(title_row)

        self.overview_status_lbl = QLabel('系统 - · 任务 - · 记忆 - · 容量 -')
        self.overview_status_lbl.setObjectName('ContextOverviewStatus')
        self.overview_status_lbl.setWordWrap(False)
        self.overview_status_lbl.setToolTip('上下文各模块状态摘要。')
        overview_layout.addWidget(self.overview_status_lbl)
        layout.addWidget(self.overview_card)

        self.module_scroll = QScrollArea()
        self.module_scroll.setWidgetResizable(True)
        self.module_scroll.setFrameShape(QFrame.NoFrame)
        self.module_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.module_scroll.setObjectName('ContextModuleScroll')

        self.module_list = AnimatedReorderContainer()
        self.module_list.setObjectName('ContextModuleList')
        self.module_list.set_spacing(8)
        self.module_list.set_scroll_host(self.module_scroll)
        self.module_list.order_changed.connect(self._on_module_order_changed)
        self.module_scroll.setWidget(self.module_list)
        layout.addWidget(self.module_scroll, 1)

        return body

    def _build_module_list(self):
        order = self._load_module_order()
        self.module_list.clear_items()
        self._module_cards = {}

        for module_id in order:
            title = self._module_titles.get(module_id, module_id)
            card = _ContextModuleCard(module_id, title)
            self._configure_module_card(card)
            self.module_list.add_item(module_id, card, drag_handle=card.drag_lbl)
            self._module_cards[module_id] = card

        self._render_view_model(self._view_model or {})

    def _configure_module_card(self, card: _ContextModuleCard):
        if card.module_id == 'system':
            card.primary_btn.setText('编辑')
            card.secondary_btn.setText('常用语')
            card.primary_btn.clicked.connect(self._open_system_dialog)
            card.secondary_btn.clicked.connect(self.open_common_phrases_requested.emit)
        elif card.module_id == 'task':
            card.primary_btn.setText('编辑')
            card.secondary_btn.setText('计划书')
            card.primary_btn.clicked.connect(self._open_working_dialog)
            card.secondary_btn.clicked.connect(lambda: self.manage_plan_binding_requested.emit(self.current_conversation_id()))
        elif card.module_id == 'memory':
            card.primary_btn.setText('查看')
            card.secondary_btn.setText('清空')
            card.primary_btn.clicked.connect(self._open_long_term_dialog)
            card.secondary_btn.clicked.connect(lambda: self.clear_long_term_requested.emit(self.current_conversation_id()))
        elif card.module_id == 'capacity':
            card.primary_btn.setText('详情')
            card.secondary_btn.setText('快照')
            card.primary_btn.clicked.connect(self._open_capacity_dialog)
            card.secondary_btn.clicked.connect(lambda: self.request_snapshot_requested.emit(self.current_conversation_id()))
        elif card.module_id == 'compact':
            card.primary_btn.setText('详情')
            card.secondary_btn.setText('压缩')
            card.primary_btn.clicked.connect(self._open_compact_dialog)
            card.secondary_btn.clicked.connect(lambda: self.manual_compact_requested.emit(self.current_conversation_id()))

    def _layout_config_path(self):
        return os.path.join(APP_ROOT, '.config', 'panel_layout.json')

    def _load_module_order(self):
        order = []
        path = self._layout_config_path()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                order = ((data.get(MODULE_ORDER_KEY) or {}).get('module_order') or [])
            except Exception:
                order = []
        normalized = [m for m in order if m in DEFAULT_MODULE_ORDER]
        for module_id in DEFAULT_MODULE_ORDER:
            if module_id not in normalized:
                normalized.append(module_id)
        return normalized

    def _save_module_order(self):
        path = self._layout_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {}
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data.setdefault(MODULE_ORDER_KEY, {})
        data[MODULE_ORDER_KEY]['module_order'] = self._current_module_order()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _current_module_order(self):
        return self.module_list.item_order()

    def _on_module_order_changed(self, *args):
        self._save_module_order()

    def current_conversation_id(self):
        return (self._current_conversation_id or '').strip()

    def _emit_refresh(self):
        self.refresh_requested.emit(self.current_conversation_id())

    def _emit_save_system(self, text: str):
        self.save_system_requested.emit(self.current_conversation_id(), text)

    def _emit_save_working(self, text: str):
        try:
            data = json.loads((text or '').strip()) if (text or '').strip() else {}
            if not isinstance(data, dict):
                raise ValueError('当前任务记录必须是 JSON 对象，例如 {"current_goal": "整理接口文档"}')
            self.save_working_requested.emit(self.current_conversation_id(), data)
        except Exception as e:
            QMessageBox.warning(self, 'JSON 格式错误', str(e))

    def get_working_memory_data(self):
        working = self._payload.get('working_memory', {}) if isinstance(self._payload, dict) else {}
        return dict(working) if isinstance(working, dict) else {}

    def _open_system_dialog(self):
        dlg = ContextDetailDialog(
            '编辑系统提示词',
            sections=[
                {'title': '当前对话系统提示词', 'content': self._view_model.get('system_edit_text', '') or '当前未设置系统提示词。'},
            ],
            parent=self,
            editable=True,
            initial_text=self._view_model.get('system_edit_text', ''),
            save_button_text='保存当前对话',
        )
        if dlg.exec():
            self._emit_save_system(dlg.get_result_text())

    def _open_working_dialog(self):
        dlg = ContextDetailDialog(
            '编辑当前任务',
            sections=[
                {'title': '任务摘要', 'content': self._view_model.get('task_summary_text', '') + '\n' + self._view_model.get('task_meta_text', '')},
            ],
            parent=self,
            editable=True,
            initial_text=self._view_model.get('working_text', '{}'),
            save_button_text='保存任务',
        )
        if dlg.exec():
            self._emit_save_working(dlg.get_result_text())

    def _open_long_term_dialog(self):
        dlg = ContextDetailDialog(
            '长期记忆详情',
            sections=[
                {'title': '长期记忆内容', 'content': self._view_model.get('long_term_text', '') or '暂无长期记忆内容。'},
            ],
            parent=self,
        )
        dlg.exec()

    def _open_capacity_dialog(self):
        dlg = ContextDetailDialog(
            '容量详情',
            sections=[
                {'title': '容量摘要', 'content': self._view_model.get('capacity_summary_text', '')},
                {'title': '运行配置', 'content': self._view_model.get('runtime_text', '')},
            ],
            parent=self,
        )
        dlg.exec()

    def _open_compact_dialog(self):
        dlg = ContextDetailDialog(
            '历史压缩详情',
            sections=[
                {'title': '压缩状态', 'content': self._view_model.get('compact_text', '')},
                {'title': '最近摘要预览', 'content': self._view_model.get('compact_summary_text', '')},
                {'title': 'History 预览', 'content': self._view_model.get('history_preview_text', '')},
            ],
            parent=self,
        )
        dlg.exec()

    def _on_conversation_changed(self, index):
        if self._suppress_combo_signal:
            return
        conv_id = self.conv_combo.itemData(index) if index >= 0 else ''
        conv_id = (conv_id or '').strip()
        self._current_conversation_id = conv_id
        if conv_id:
            self.follow_checkbox.setChecked(False)
            self._emit_refresh()

    def update_conversation_list(self, conversations):
        items = conversations.get('items', []) if isinstance(conversations, dict) else conversations
        items = items if isinstance(items, list) else []
        self._conversation_items = items

        current_id = self.current_conversation_id()
        payload_conv_id = (self._payload.get('conversation_id') or '').strip()
        preferred_id = current_id or payload_conv_id

        self._suppress_combo_signal = True
        try:
            self.conv_combo.clear()
            self.conv_combo.addItem('当前 active API 对话', '')
            selected_index = 0
            for i, item in enumerate(items, start=1):
                title = item.get('title') or item.get('name') or item.get('id') or '未命名对话'
                conv_id = (item.get('id') or '').strip()
                runtime_profile = item.get('runtime_profile_key') or item.get('profile') or ''
                label = title if not runtime_profile else f'{title} [{runtime_profile}]'
                self.conv_combo.addItem(label, conv_id)
                if preferred_id and conv_id == preferred_id:
                    selected_index = i
            self.conv_combo.setCurrentIndex(selected_index)
            self._current_conversation_id = (self.conv_combo.currentData() or '').strip()
        finally:
            self._suppress_combo_signal = False

    def update_payload(self, payload: dict):
        self._payload = payload or {}
        view_model = ContextWorkspacePanelPresenter.build_view_model(self._payload)
        self._view_model = view_model
        self._sync_target_conversation(view_model['payload_conversation_id'])
        self._render_view_model(view_model)

    def _sync_target_conversation(self, payload_conversation_id: str):
        if not (self.follow_checkbox.isChecked() and payload_conversation_id):
            return
        self._current_conversation_id = payload_conversation_id
        idx = self.conv_combo.findData(payload_conversation_id)
        self._suppress_combo_signal = True
        try:
            if idx >= 0:
                self.conv_combo.setCurrentIndex(idx)
        finally:
            self._suppress_combo_signal = False

    def _render_view_model(self, view_model: dict):
        title_text = view_model.get('title_text', '未命名对话')
        meta_text = view_model.get('meta_text', '未加载')
        follow_hint = view_model.get('follow_hint_text', '')
        self.overview_title_lbl.setText(title_text)
        self.overview_title_lbl.setToolTip(f'{title_text}\n{meta_text}\n{follow_hint}'.strip())
        self.overview_profile_badge.setText(view_model.get('profile_text', '-'))
        self.overview_mode_badge.setText(view_model.get('mode_text', '-'))
        self.overview_follow_badge.setText('跟随中' if self.follow_checkbox.isChecked() else '已锁定')
        self.overview_status_lbl.setText(
            f"系统 {view_model.get('system_status_text', '-')} · 任务 {view_model.get('task_status_text', '-')} · "
            f"记忆 {view_model.get('long_term_status_text', '-')} · 容量 {view_model.get('capacity_status_text', '-')}"
        )
        self.overview_status_lbl.setToolTip(
            f"{meta_text}\n{follow_hint}\n"
            f"系统：{view_model.get('system_summary_text', '-') }\n"
            f"任务：{view_model.get('task_summary_text', '-') }\n"
            f"记忆：{view_model.get('long_term_summary_text', '-') }\n"
            f"容量：{view_model.get('capacity_summary_text', '-') }"
        )

        module_data = {
            'system': (
                view_model.get('system_status_text', '-'),
                view_model.get('system_summary_text', '-'),
                '',
            ),
            'task': (
                view_model.get('task_status_text', '-'),
                view_model.get('task_summary_text', '-'),
                view_model.get('task_meta_text', ''),
            ),
            'memory': (
                view_model.get('long_term_status_text', '-'),
                view_model.get('long_term_summary_text', '-'),
                view_model.get('long_term_preview_text', ''),
            ),
            'capacity': (
                view_model.get('capacity_status_text', '-'),
                view_model.get('capacity_summary_text', '-'),
                view_model.get('capacity_preview_text', ''),
            ),
            'compact': (
                view_model.get('compact_status_text', '-'),
                view_model.get('compact_summary_line_text', '-'),
                view_model.get('compact_preview_text', ''),
            ),
        }

        for module_id, values in module_data.items():
            card = self._module_cards.get(module_id)
            if not card:
                continue
            status, summary, detail = values
            card.set_status(status)
            card.set_summary(summary)
            card.set_detail(detail)

    def apply_content_theme(self):
        p = theme_manager.get_palette()

        root_style = f"""
            QWidget#ContextWorkspaceRoot {{
                background-color: {p.BG_PRIMARY};
            }}
            QFrame#ContextToolbar, QFrame#ContextOverviewCard {{
                background-color: {p.BG_SECONDARY};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QScrollArea#ContextModuleScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#ContextModuleScroll > QWidget > QWidget {{
                background: transparent;
            }}
            QWidget#ContextModuleList {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QFrame#AnimatedReorderItem {{
                background: transparent;
                border: none;
            }}
            QFrame#AnimatedReorderItem[dragging="true"] {{
                background: rgba(255, 255, 255, 0.02);
                border: 1px dashed rgba(120, 160, 255, 0.40);
                border-radius: 8px;
            }}
            QLabel#ContextSectionHint {{
                color: {p.TEXT_SECONDARY};
                background: transparent;
                border: none;
            }}
            QLabel#ContextOverviewTitle {{
                color: {p.TEXT_PRIMARY};
                font-size: 13px;
                font-weight: 700;
                background: transparent;
                border: none;
            }}
            QLabel#ContextOverviewStatus {{
                color: {p.TEXT_PRIMARY};
                font-size: 10px;
                background: transparent;
                border: none;
                padding-top: 1px;
            }}
            QLabel#ContextOverviewBadge {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 700;
                min-height: 20px;
            }}
        """
        self.widget().setStyleSheet(root_style)

        compact_btn = f"""
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 3px 8px;
                min-height: 26px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {p.BORDER};
            }}
        """
        primary_btn = f"""
            QPushButton {{
                background-color: {p.ACCENT_PRIMARY};
                color: #FFFFFF;
                border: 1px solid {p.ACCENT_PRIMARY};
                border-radius: 6px;
                padding: 3px 8px;
                min-height: 26px;
                font-size: 10px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {p.ACCENT_HOVER};
                border: 1px solid {p.ACCENT_HOVER};
            }}
        """

        self.refresh_btn.setStyleSheet(compact_btn)
        self.snapshot_btn.setStyleSheet(compact_btn)
        self.refresh_list_btn.setStyleSheet(compact_btn)
        self.conv_combo.setStyleSheet(compact_btn)
        self.follow_checkbox.setStyleSheet(f"color: {p.TEXT_PRIMARY};")

        for card in self._module_cards.values():
            card.apply_card_theme()
            card.primary_btn.setStyleSheet(primary_btn)
            card.secondary_btn.setStyleSheet(compact_btn)
