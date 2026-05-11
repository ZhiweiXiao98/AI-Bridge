from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton,
)
from PySide6.QtCore import Signal

from app.core.api_mode_config import APIModeConfigManager
from app.ui.theme import Theme, theme_manager
from app.ui.components.settings.settings_widgets import (
    ScrollSafeComboBox, SettingsCard, SettingsField,
    CollapsiblePanel,
)
from app.ui.components.settings.settings_styles import card_style
from app.ui.pages.console_page import UIHelper


class SettingsApiUsageSection(QFrame):
    config_changed = Signal(dict)
    section_id = "api_usage"
    section_title = "对话配置"

    def __init__(self, api_config=None, parent=None):
        super().__init__(parent)
        self.api_mode_config = api_config or APIModeConfigManager.load()
        self._build_ui()
        self.load_from_config({}, self.api_mode_config)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)

        title = QLabel("API 模式对话配置")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        subtitle = QLabel("配置 API 模式对话使用的模型来源")
        subtitle.setObjectName("sectionSubtitle")
        root.addWidget(subtitle)

        card = SettingsCard("模型来源")
        self._card = card

        type_row = QHBoxLayout()
        type_row.setSpacing(16)
        self.api_mode_usage_type_profile_rb = QRadioButton("Profile")
        self.api_mode_usage_type_chain_rb = QRadioButton("Chain")
        self.api_mode_usage_type_profile_rb.toggled.connect(self._on_type_changed)
        type_row.addWidget(self.api_mode_usage_type_profile_rb)
        type_row.addWidget(self.api_mode_usage_type_chain_rb)
        type_row.addStretch()
        card.add_layout(type_row)

        self.api_mode_usage_combo = ScrollSafeComboBox()
        self.api_mode_usage_combo.currentIndexChanged.connect(self._update_summary)
        card.add_field(SettingsField("选择", self.api_mode_usage_combo))

        self._summary_panel = CollapsiblePanel("当前配置摘要")
        self._summary_content_label = QLabel("未选择")
        self._summary_content_label.setObjectName("summaryContent")
        self._summary_content_label.setWordWrap(True)
        self._summary_panel.add_widget(self._summary_content_label)
        card.add_widget(self._summary_panel)

        root.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.api_mode_usage_reload_btn = QPushButton("重载")
        self.api_mode_usage_reload_btn.clicked.connect(self._reload)
        self.api_mode_usage_save_btn = QPushButton("保存")
        self.api_mode_usage_save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.api_mode_usage_reload_btn)
        btn_row.addWidget(self.api_mode_usage_save_btn)
        root.addLayout(btn_row)

        root.addStretch()

    def _update_summary(self):
        is_profile = self.api_mode_usage_type_profile_rb.isChecked()
        ref = self.api_mode_usage_combo.currentData()

        if not ref:
            self._summary_content_label.setText("未选择")
            self._summary_panel.set_title("当前配置摘要")
            return

        if is_profile:
            pd = self.api_mode_config.get("profiles", {}).get(ref, {})
            vendor = pd.get("vendor", "未知")
            model = pd.get("model", "未知")
            base_url = pd.get("base_url", "")
            self._summary_content_label.setText(
                f"类型: Profile\n"
                f"名称: {pd.get('name', ref)}\n"
                f"供应商: {vendor}\n"
                f"模型: {model}\n"
                f"Base URL: {base_url}"
            )
            self._summary_panel.set_title(f"摘要 · Profile: {pd.get('name', ref)}")
        else:
            chain = self.api_mode_config.get("fallback_chains", {}).get(ref, {})
            profiles = chain.get("profiles", [])
            profile_lines = []
            for i, p_ref in enumerate(profiles, 1):
                pd = self.api_mode_config.get("profiles", {}).get(p_ref, {})
                vendor = pd.get("vendor", "未知")
                model = pd.get("model", "未知")
                profile_lines.append(f"  {i}. {pd.get('name', p_ref)} ({vendor} / {model})")
            chain_desc = "\n".join(profile_lines) if profile_lines else "  (空)"
            self._summary_content_label.setText(
                f"类型: Chain\n"
                f"名称: {ref}\n"
                f"包含 Profile ({len(profiles)} 个):\n{chain_desc}"
            )
            self._summary_panel.set_title(f"摘要 · Chain: {ref}")

    def load_from_config(self, config, api_config=None):
        if api_config:
            self.api_mode_config = api_config
        usage = self.api_mode_config.get("api_mode_usage", {"type": "profile", "ref": "default"})
        usage_type = usage.get("type", "profile")
        usage_ref = usage.get("ref", "default")

        if usage_type == "profile":
            self.api_mode_usage_type_profile_rb.setChecked(True)
        else:
            self.api_mode_usage_type_chain_rb.setChecked(True)
        self._populate_combo(usage_type, usage_ref)
        self._update_summary()

    def collect_config(self):
        return {}

    def collect_api_config(self):
        self.api_mode_config["api_mode_usage"] = {
            "type": "profile" if self.api_mode_usage_type_profile_rb.isChecked() else "chain",
            "ref": str(self.api_mode_usage_combo.currentData() or "default"),
        }
        return self.api_mode_config

    def _populate_combo(self, usage_type, current_ref):
        self.api_mode_usage_combo.blockSignals(True)
        self.api_mode_usage_combo.clear()
        if usage_type == "profile":
            for pk, pd in self.api_mode_config.get("profiles", {}).items():
                self.api_mode_usage_combo.addItem(f"{pd.get('name', pk)}", pk)
                if pk == current_ref:
                    self.api_mode_usage_combo.setCurrentIndex(self.api_mode_usage_combo.count() - 1)
        else:
            for cn in self.api_mode_config.get("fallback_chains", {}).keys():
                self.api_mode_usage_combo.addItem(cn, cn)
                if cn == current_ref:
                    self.api_mode_usage_combo.setCurrentIndex(self.api_mode_usage_combo.count() - 1)
        self.api_mode_usage_combo.blockSignals(False)
        self._update_summary()

    def _on_type_changed(self):
        if self.api_mode_usage_type_profile_rb.isChecked():
            self._populate_combo("profile", "default")
        else:
            self._populate_combo("chain", "")

    def _save(self):
        api_config = self.collect_api_config()
        APIModeConfigManager.save(api_config)
        self.api_mode_config = APIModeConfigManager.load()
        self.config_changed.emit({"action": "api_usage_saved"})
        UIHelper.info(self, "已保存", "API 模式对话配置已保存。")

    def _reload(self):
        self.api_mode_config = APIModeConfigManager.load()
        self.load_from_config({}, self.api_mode_config)
        UIHelper.info(self, "已重载", "API 模式对话配置已重新加载。")

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")

        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "sectionTitle":
                lbl.setStyleSheet(Theme.section_title())
            elif lbl.objectName() == "sectionSubtitle":
                lbl.setStyleSheet(Theme.section_subtitle())

        self._card.setStyleSheet(card_style())
        self.api_mode_usage_combo.setStyleSheet(Theme.combo_box())

        for rb in [self.api_mode_usage_type_profile_rb, self.api_mode_usage_type_chain_rb]:
            rb.setStyleSheet(
                f"QRadioButton {{ color: {p.TEXT_PRIMARY}; spacing: 8px; }}"
                f"QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px; "
                f"  border: 2px solid {p.BORDER}; background-color: {p.BG_PRIMARY}; }}"
                f"QRadioButton::indicator:checked {{ "
                f"  border: 2px solid {p.ACCENT_PRIMARY}; background-color: {p.ACCENT_PRIMARY}; }}"
            )

        btn_ss = f"background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 6px; padding: 5px 12px;"
        self.api_mode_usage_reload_btn.setStyleSheet(btn_ss)
        self.api_mode_usage_save_btn.setStyleSheet(Theme.button_primary())

        self._summary_panel.refresh_style()
        self._summary_content_label.setStyleSheet(
            f"color: {p.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
        )
