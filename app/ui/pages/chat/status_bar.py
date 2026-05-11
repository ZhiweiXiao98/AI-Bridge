# filename: app/ui/pages/chat/status_bar.py
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal

from app.core.api_mode_config import APIModeConfigManager
from app.core.project_context import ProjectContext
from app.core.logging import get_logger
from app.ui.theme import Theme, theme_manager

logger = get_logger("app.ui.chat_status_bar", side="ui")


class ApiModelUsageBar(QFrame):
    usage_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ApiModelUsageBar")
        self._loading = False
        self._conversation_id = ""
        self._current_usage = None
        self._api_mode_config = {}
        self._context_status = {}
        self._project_ctx = ProjectContext.get()
        self._build_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        try:
            self._project_ctx.project_switched.connect(lambda *_: self.refresh_project())
        except Exception as e:
            logger.warning(e)
        self.reload_options()
        self.refresh_project()
        self.apply_theme()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 6, 20, 0)
        layout.setSpacing(10)

        self.project_label = QLabel("项目")
        self.project_value_label = QLabel("当前项目")
        self.project_value_label.setMinimumWidth(140)
        self.project_value_label.setToolTip("")

        self.label = QLabel("本对话模型")
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo.currentIndexChanged.connect(self._on_selection_changed)

        self.summary_label = QLabel("使用全局默认")
        self.summary_label.setMinimumWidth(160)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.capacity_label = QLabel("上下文")
        self.capacity_value_label = QLabel("--%")
        self.capacity_value_label.setMinimumWidth(160)
        self.capacity_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.project_label)
        layout.addWidget(self.project_value_label)
        layout.addWidget(self.label)
        layout.addWidget(self.combo)
        layout.addWidget(self.summary_label, 1)
        layout.addWidget(self.capacity_label)
        layout.addWidget(self.capacity_value_label)

    def reload_options(self):
        self._api_mode_config = APIModeConfigManager.load()
        self._populate_options()
        self.set_conversation(self._conversation_id, self._current_usage)

    def set_conversation(self, conv_id, usage):
        self._conversation_id = str(conv_id or "")
        self._current_usage = usage if isinstance(usage, dict) else None
        self._select_usage(self._current_usage)
        self.combo.setEnabled(bool(self._conversation_id))
        if not self._conversation_id:
            self.summary_label.setText("请先选择 API 对话")

    def refresh_project(self):
        try:
            root = self._project_ctx.get_project_root()
            name = self._project_ctx.project_name or "未命名项目"
            self.project_value_label.setText(name)
            self.project_value_label.setToolTip(root)
        except Exception:
            self.project_value_label.setText("未知项目")
            self.project_value_label.setToolTip("")

    def set_context_status(self, payload):
        self._context_status = payload if isinstance(payload, dict) else {}
        self._update_capacity()

    def _populate_options(self):
        self._loading = True
        self.combo.clear()
        self.combo.addItem("使用全局默认", "")

        profiles = self._api_mode_config.get("profiles", {}) or {}
        if profiles:
            self.combo.insertSeparator(self.combo.count())
        for key, profile in profiles.items():
            name = profile.get("name") or key
            kind = profile.get("kind") or "api"
            provider = profile.get("provider") or profile.get("vendor") or "api"
            self.combo.addItem(f"Profile · {name}", f"profile:{key}")
            self.combo.setItemData(
                self.combo.count() - 1,
                f"{key} · {provider} · {kind}",
                Qt.ItemDataRole.ToolTipRole,
            )

        chains = self._api_mode_config.get("fallback_chains", {}) or {}
        if chains:
            self.combo.insertSeparator(self.combo.count())
        for key in chains.keys():
            self.combo.addItem(f"Chain · {key}", f"chain:{key}")

        self._loading = False

    def _select_usage(self, usage):
        self._loading = True
        target = ""
        if isinstance(usage, dict):
            usage_type = str(usage.get("type") or "").strip()
            ref = str(usage.get("ref") or "").strip()
            if usage_type in ("profile", "chain") and ref:
                target = f"{usage_type}:{ref}"
        idx = self.combo.findData(target)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._loading = False
        self._update_summary()

    def _current_combo_usage(self):
        data = str(self.combo.currentData() or "")
        if not data:
            return None
        usage_type, _, ref = data.partition(":")
        if usage_type not in ("profile", "chain") or not ref:
            return None
        return {"type": usage_type, "ref": ref}

    def _on_selection_changed(self):
        if self._loading:
            return
        usage = self._current_combo_usage()
        self._current_usage = usage
        self._update_summary()
        self.usage_changed.emit(usage)

    def _update_summary(self):
        usage = self._current_combo_usage()
        if not usage:
            try:
                default_key = APIModeConfigManager.get_active_profile_key(self._api_mode_config)
                profile = self._api_mode_config.get("profiles", {}).get(default_key, {})
                self.summary_label.setText(f"默认：{profile.get('name') or default_key}")
            except Exception:
                self.summary_label.setText("使用全局默认")
            return

        ref = usage.get("ref", "")
        if usage.get("type") == "profile":
            profile = self._api_mode_config.get("profiles", {}).get(ref, {})
            self.summary_label.setText(f"本对话：{profile.get('name') or ref}")
        else:
            self.summary_label.setText(f"本对话 Chain：{ref}")

    def _update_capacity(self):
        usage = self._context_status or {}
        try:
            utilization = float(usage.get("utilization", 0) or 0)
            used = int(usage.get("total_used", usage.get("used", 0)) or 0)
            total = int(usage.get("total_budget", usage.get("total", 0)) or 0)
        except Exception:
            utilization, used, total = 0, 0, 0

        if total <= 0 and used <= 0:
            self.capacity_value_label.setText("--%")
            self.capacity_value_label.setToolTip("暂无上下文容量数据")
            self._apply_capacity_color(0)
            return

        if utilization <= 0 and total > 0:
            utilization = round((used / total) * 100, 1)
        percent = int(round(utilization))
        if total > 0:
            self.capacity_value_label.setText(f"{percent}% · {used:,}/{total:,}")
            self.capacity_value_label.setToolTip(f"已使用 {used:,} tokens / 总容量 {total:,} tokens")
        else:
            self.capacity_value_label.setText(f"{percent}% · {used:,}")
            self.capacity_value_label.setToolTip(f"已使用 {used:,} tokens")
        self._apply_capacity_color(percent)

    def _apply_capacity_color(self, percent):
        p = theme_manager.get_palette()
        color = p.TEXT_SUCCESS
        if percent >= 85:
            color = p.TEXT_DANGER
        elif percent >= 60:
            color = p.BTN_WARNING
        self.capacity_value_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"""
            QFrame#ApiModelUsageBar {{
                background-color: {p.BG_PRIMARY};
                border-top: 1px solid {p.BORDER};
            }}
        """)
        for lbl in (self.project_label, self.label, self.capacity_label):
            lbl.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        self.project_value_label.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        self.combo.setStyleSheet(Theme.combo_box())
        self.summary_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        self._update_capacity()
