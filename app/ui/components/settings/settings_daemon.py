from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton,
)
from PySide6.QtCore import Signal

from app.core.api_mode_config import APIModeConfigManager
from app.ui.theme import Theme, theme_manager
from app.ui.components.settings.settings_widgets import (
    ScrollSafeComboBox, ScrollSafeSpinBox, SettingsCard, SettingsField,
    SettingsToggleRow, CollapsiblePanel,
)
from app.ui.components.settings.settings_styles import card_style
from app.ui.pages.console_page import UIHelper


class SettingsDaemonSection(QFrame):
    config_changed = Signal(dict)
    section_id = "daemon"
    section_title = "守护进程"

    def __init__(self, config=None, api_config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.api_mode_config = api_config or APIModeConfigManager.load()
        self._build_ui()
        self.load_from_config(self.config, self.api_mode_config)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)

        title = QLabel("守护进程")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        subtitle = QLabel("配置后台 AI 助手的核心与轻量模型")
        subtitle.setObjectName("sectionSubtitle")
        root.addWidget(subtitle)

        self.daemon_enabled_toggle = SettingsToggleRow(
            "启用守护进程", "后台 AI 助手，可提供回复建议等功能", True
        )
        root.addWidget(self.daemon_enabled_toggle)

        card_core = SettingsCard("Core 模型")
        self._card_core = card_core

        core_type_row = QHBoxLayout()
        core_type_row.setSpacing(16)
        self.daemon_core_type_profile_rb = QRadioButton("Profile")
        self.daemon_core_type_chain_rb = QRadioButton("Chain")
        self.daemon_core_type_profile_rb.toggled.connect(self._on_core_type_changed)
        core_type_row.addWidget(self.daemon_core_type_profile_rb)
        core_type_row.addWidget(self.daemon_core_type_chain_rb)
        core_type_row.addStretch()
        card_core.add_layout(core_type_row)

        self.daemon_core_combo = ScrollSafeComboBox()
        self.daemon_core_combo.currentIndexChanged.connect(lambda: self._update_summary("core"))
        card_core.add_field(SettingsField("选择", self.daemon_core_combo))

        self._core_summary_panel = CollapsiblePanel("Core 配置摘要")
        self._core_summary_label = QLabel("未选择")
        self._core_summary_label.setObjectName("summaryContent")
        self._core_summary_label.setWordWrap(True)
        self._core_summary_panel.add_widget(self._core_summary_label)
        card_core.add_widget(self._core_summary_panel)

        root.addWidget(card_core)

        card_lite = SettingsCard("Lite 模型")
        self._card_lite = card_lite

        lite_type_row = QHBoxLayout()
        lite_type_row.setSpacing(16)
        self.daemon_lite_type_profile_rb = QRadioButton("Profile")
        self.daemon_lite_type_chain_rb = QRadioButton("Chain")
        self.daemon_lite_type_profile_rb.toggled.connect(self._on_lite_type_changed)
        lite_type_row.addWidget(self.daemon_lite_type_profile_rb)
        lite_type_row.addWidget(self.daemon_lite_type_chain_rb)
        lite_type_row.addStretch()
        card_lite.add_layout(lite_type_row)

        self.daemon_lite_combo = ScrollSafeComboBox()
        self.daemon_lite_combo.currentIndexChanged.connect(lambda: self._update_summary("lite"))
        card_lite.add_field(SettingsField("选择", self.daemon_lite_combo))

        self._lite_summary_panel = CollapsiblePanel("Lite 配置摘要")
        self._lite_summary_label = QLabel("未选择")
        self._lite_summary_label.setObjectName("summaryContent")
        self._lite_summary_label.setWordWrap(True)
        self._lite_summary_panel.add_widget(self._lite_summary_label)
        card_lite.add_widget(self._lite_summary_panel)

        root.addWidget(card_lite)

        card_suggest = SettingsCard("回复建议")
        self._card_suggest = card_suggest

        self.daemon_suggest_enabled_toggle = SettingsToggleRow(
            "启用回复建议", "在对话中提供 AI 生成的回复建议", True
        )
        card_suggest.add_widget(self.daemon_suggest_enabled_toggle)

        self.daemon_suggest_max_spin = ScrollSafeSpinBox()
        self.daemon_suggest_max_spin.setRange(1, 5)
        card_suggest.add_field(SettingsField("最大建议数", self.daemon_suggest_max_spin))

        hint = QLabel("提示词可在 Prompt/Daemon_Suggest.md 中直接编辑")
        hint.setObjectName("sectionSubtitle")
        card_suggest.add_widget(hint)

        root.addWidget(card_suggest)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.daemon_reload_btn = QPushButton("重载")
        self.daemon_reload_btn.clicked.connect(self._reload)
        self.daemon_save_btn = QPushButton("保存")
        self.daemon_save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.daemon_reload_btn)
        btn_row.addWidget(self.daemon_save_btn)
        root.addLayout(btn_row)

        root.addStretch()

    def _update_summary(self, tier):
        if tier == "core":
            is_profile = self.daemon_core_type_profile_rb.isChecked()
            ref = self.daemon_core_combo.currentData()
            panel = self._core_summary_panel
            label = self._core_summary_label
        else:
            is_profile = self.daemon_lite_type_profile_rb.isChecked()
            ref = self.daemon_lite_combo.currentData()
            panel = self._lite_summary_panel
            label = self._lite_summary_label

        if not ref:
            label.setText("未选择")
            panel.set_title(f"{tier.title()} 配置摘要")
            return

        if is_profile:
            pd = self.api_mode_config.get("profiles", {}).get(ref, {})
            vendor = pd.get("vendor", "未知")
            model = pd.get("model", "未知")
            base_url = pd.get("base_url", "")
            label.setText(
                f"类型: Profile\n"
                f"名称: {pd.get('name', ref)}\n"
                f"供应商: {vendor}\n"
                f"模型: {model}\n"
                f"Base URL: {base_url}"
            )
            panel.set_title(f"摘要 · Profile: {pd.get('name', ref)}")
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
            label.setText(
                f"类型: Chain\n"
                f"名称: {ref}\n"
                f"包含 Profile ({len(profiles)} 个):\n{chain_desc}"
            )
            panel.set_title(f"摘要 · Chain: {ref}")

    def load_from_config(self, config, api_config=None):
        if config:
            self.config = config
        if api_config:
            self.api_mode_config = api_config

        daemon_cfg = self.config.get("daemon", {})
        if not daemon_cfg:
            daemon_cfg = {
                "enabled": True,
                "core": {"type": "profile", "ref": "default"},
                "lite": {"type": "profile", "ref": "default"},
                "tasks": {"suggest": {"enabled": True, "max_suggestions": 3}},
            }

        self.daemon_enabled_toggle.setChecked(daemon_cfg.get("enabled", True))

        core_cfg = daemon_cfg.get("core", {"type": "profile", "ref": "default"})
        if core_cfg.get("type") == "profile":
            self.daemon_core_type_profile_rb.setChecked(True)
        else:
            self.daemon_core_type_chain_rb.setChecked(True)
        self._populate_combo(self.daemon_core_combo, core_cfg.get("type"), core_cfg.get("ref"))

        lite_cfg = daemon_cfg.get("lite", {"type": "profile", "ref": "default"})
        if lite_cfg.get("type") == "profile":
            self.daemon_lite_type_profile_rb.setChecked(True)
        else:
            self.daemon_lite_type_chain_rb.setChecked(True)
        self._populate_combo(self.daemon_lite_combo, lite_cfg.get("type"), lite_cfg.get("ref"))

        suggest_cfg = daemon_cfg.get("tasks", {}).get("suggest", {})
        self.daemon_suggest_enabled_toggle.setChecked(suggest_cfg.get("enabled", True))
        self.daemon_suggest_max_spin.setValue(int(suggest_cfg.get("max_suggestions", 3)))

        self._update_summary("core")
        self._update_summary("lite")

    def collect_config(self):
        return {
            "daemon": {
                "enabled": self.daemon_enabled_toggle.isChecked(),
                "core": {
                    "type": "profile" if self.daemon_core_type_profile_rb.isChecked() else "chain",
                    "ref": str(self.daemon_core_combo.currentData() or "default"),
                },
                "lite": {
                    "type": "profile" if self.daemon_lite_type_profile_rb.isChecked() else "chain",
                    "ref": str(self.daemon_lite_combo.currentData() or "default"),
                },
                "tasks": {
                    "suggest": {
                        "enabled": self.daemon_suggest_enabled_toggle.isChecked(),
                        "max_suggestions": self.daemon_suggest_max_spin.value(),
                    },
                },
            },
        }

    def _populate_combo(self, combo, ref_type, current_ref):
        combo.blockSignals(True)
        combo.clear()
        if ref_type == "profile":
            for pk, pd in self.api_mode_config.get("profiles", {}).items():
                combo.addItem(f"{pd.get('name', pk)}", pk)
                if pk == current_ref:
                    combo.setCurrentIndex(combo.count() - 1)
        else:
            for cn in self.api_mode_config.get("fallback_chains", {}).keys():
                combo.addItem(cn, cn)
                if cn == current_ref:
                    combo.setCurrentIndex(combo.count() - 1)
        combo.blockSignals(False)

    def _on_core_type_changed(self):
        if self.daemon_core_type_profile_rb.isChecked():
            self._populate_combo(self.daemon_core_combo, "profile", "default")
        else:
            self._populate_combo(self.daemon_core_combo, "chain", "")
        self._update_summary("core")

    def _on_lite_type_changed(self):
        if self.daemon_lite_type_profile_rb.isChecked():
            self._populate_combo(self.daemon_lite_combo, "profile", "default")
        else:
            self._populate_combo(self.daemon_lite_combo, "chain", "")
        self._update_summary("lite")

    def _save(self):
        from app.core.config import ConfigManager
        self.config.update(self.collect_config())
        ConfigManager.save(self.config)
        self.config = ConfigManager.load()
        self.config_changed.emit({"action": "daemon_saved"})
        UIHelper.info(self, "已保存", "守护进程配置已保存。")

    def _reload(self):
        from app.core.config import ConfigManager
        self.config = ConfigManager.load()
        self.api_mode_config = APIModeConfigManager.load()
        self.load_from_config(self.config, self.api_mode_config)
        UIHelper.info(self, "已重载", "守护进程配置已从文件重新加载。")

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")

        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "sectionTitle":
                lbl.setStyleSheet(Theme.section_title())
            elif lbl.objectName() == "sectionSubtitle":
                lbl.setStyleSheet(Theme.section_subtitle())

        for card in [self._card_core, self._card_lite, self._card_suggest]:
            card.setStyleSheet(card_style())

        for cb in [self.daemon_core_combo, self.daemon_lite_combo]:
            cb.setStyleSheet(Theme.combo_box())

        self.daemon_suggest_max_spin.setStyleSheet(Theme.input_field())

        rb_ss = (
            f"QRadioButton {{ color: {p.TEXT_PRIMARY}; spacing: 8px; }}"
            f"QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px; "
            f"  border: 2px solid {p.BORDER}; background-color: {p.BG_PRIMARY}; }}"
            f"QRadioButton::indicator:checked {{ "
            f"  border: 2px solid {p.ACCENT_PRIMARY}; background-color: {p.ACCENT_PRIMARY}; }}"
        )
        for rb in [self.daemon_core_type_profile_rb, self.daemon_core_type_chain_rb,
                    self.daemon_lite_type_profile_rb, self.daemon_lite_type_chain_rb]:
            rb.setStyleSheet(rb_ss)

        self.daemon_enabled_toggle.setStyleSheet(
            f"QFrame#settingsToggleRow {{ background-color: {p.BG_TERTIARY}; border: 1px solid transparent; border-radius: 10px; }}"
            f"QFrame#settingsToggleRow:hover {{ border: 1px solid {p.BORDER}; }}"
            f"QLabel#settingsToggleTitle {{ color: {p.TEXT_PRIMARY}; font-weight: 600; }}"
            f"QLabel#settingsToggleDesc {{ color: {p.TEXT_SECONDARY}; }}"
        )
        self.daemon_suggest_enabled_toggle.setStyleSheet(
            f"QFrame#settingsToggleRow {{ background-color: {p.BG_TERTIARY}; border: 1px solid transparent; border-radius: 10px; }}"
            f"QFrame#settingsToggleRow:hover {{ border: 1px solid {p.BORDER}; }}"
            f"QLabel#settingsToggleTitle {{ color: {p.TEXT_PRIMARY}; font-weight: 600; }}"
            f"QLabel#settingsToggleDesc {{ color: {p.TEXT_SECONDARY}; }}"
        )

        btn_ss = f"background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 6px; padding: 5px 12px;"
        self.daemon_reload_btn.setStyleSheet(btn_ss)
        self.daemon_save_btn.setStyleSheet(Theme.button_primary())

        self._core_summary_panel.refresh_style()
        self._lite_summary_panel.refresh_style()
        for lbl in [self._core_summary_label, self._lite_summary_label]:
            lbl.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px; background: transparent;")
