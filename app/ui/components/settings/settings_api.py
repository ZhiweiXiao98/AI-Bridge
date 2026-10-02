import json
import os
import logging
from copy import deepcopy
from datetime import datetime

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QToolButton, QRadioButton,
    QPlainTextEdit, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Signal

from app.core.api_mode_config import (
    APIModeConfigManager,
    TOOL_PROTOCOL_MARKDOWN_ONLY,
    TOOL_PROTOCOL_NATIVE,
)
from app.core.app_constants import OPENAI_COMPAT_MODELS, GEMINI_MODELS, MIMO_MODELS, MIMO_DEFAULT_BASE_URL, DEFAULT_API_BASE_URL, DEFAULT_API_MODEL, DEFAULT_PROXY_URL
from app.core.model_capabilities import (
    REASONING_MODE_EFFORT,
    REASONING_MODE_NONE,
    normalize_reasoning_for_capability,
    reasoning_tooltip,
    resolve_model_capability,
)
from app.ui.theme import Theme, theme_manager
from app.ui.components.settings.settings_widgets import (
    ScrollSafeComboBox, ScrollSafeSpinBox, SettingsCard, SettingsField,
    SettingsFieldRow,
)
from app.ui.components.settings.settings_styles import card_style
from app.ui.pages.console_page import UIHelper

logger = logging.getLogger(__name__)


class SettingsApiSection(QFrame):
    config_changed = Signal(dict)
    section_id = "api"
    section_title = "API 配置"

    OPENAI_COMPAT_MODELS = OPENAI_COMPAT_MODELS
    GEMINI_MODELS = GEMINI_MODELS
    MIMO_MODELS = MIMO_MODELS
    OPENAI_DEFAULT_BASE_URL = DEFAULT_API_BASE_URL

    def __init__(self, config=None, api_config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.api_mode_config = api_config or APIModeConfigManager.load()
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        self._loading_form = False
        self._syncing_effective_json = False
        self._effective_json_dirty = False
        self._build_ui()
        self._connect_effective_json_sync()
        self.load_from_config(self.config, self.api_mode_config)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)

        title = QLabel("API 配置")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        subtitle = QLabel("管理 API Profile、密钥、模型与参数")
        subtitle.setObjectName("sectionSubtitle")
        root.addWidget(subtitle)

        card_profile = SettingsCard("Profile 管理")
        self._card_profile = card_profile

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        self.api_profile_combo = ScrollSafeComboBox()
        self.api_profile_add_btn = QPushButton("新建")
        self.api_profile_add_btn.setFixedWidth(50)
        self.api_browser_profile_add_btn = QPushButton("新建浏览器")
        self.api_browser_profile_add_btn.setFixedWidth(86)
        self.api_profile_rename_btn = QPushButton("重命名")
        self.api_profile_rename_btn.setFixedWidth(60)
        self.api_profile_del_btn = QPushButton("删除")
        self.api_profile_del_btn.setFixedWidth(50)
        profile_row.addWidget(self.api_profile_combo, 1)
        profile_row.addWidget(self.api_profile_add_btn)
        profile_row.addWidget(self.api_browser_profile_add_btn)
        profile_row.addWidget(self.api_profile_rename_btn)
        profile_row.addWidget(self.api_profile_del_btn)
        card_profile.add_layout(profile_row)

        self.api_profile_combo.currentIndexChanged.connect(self._on_api_profile_changed)
        self.api_profile_add_btn.clicked.connect(self._create_api_profile)
        self.api_browser_profile_add_btn.clicked.connect(self._create_browser_profile)
        self.api_profile_rename_btn.clicked.connect(self._rename_api_profile)
        self.api_profile_del_btn.clicked.connect(self._delete_api_profile)

        root.addWidget(card_profile)

        card_provider = SettingsCard("Provider / 连接方式")
        self._card_provider = card_provider

        self.api_provider_combo = ScrollSafeComboBox()
        self.api_provider_combo.addItem("OpenAI 兼容", "openai_compatible")
        self.api_provider_combo.addItem("Xiaomi MiMo", "mimo")
        self.api_provider_combo.addItem("Google Gemini (SDK)", "gemini")
        self.api_provider_combo.addItem("网页 AI（无上下文）", "web_ai")
        if os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1":
            item = self.api_provider_combo.model().item(self.api_provider_combo.findData("web_ai"))
            item.setEnabled(False)
            item.setToolTip("本地版本请使用聊天页的浏览器标签，不启用会清空网页对话的无状态 Profile")
            self.api_browser_profile_add_btn.setEnabled(False)
            self.api_browser_profile_add_btn.setToolTip("请使用聊天页的浏览器标签")
        self.api_provider_combo.currentIndexChanged.connect(self._on_api_provider_changed)
        card_provider.add_field(SettingsField("Provider", self.api_provider_combo))

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-... 或 API 密钥")
        self.api_key_toggle_btn = QToolButton()
        self.api_key_toggle_btn.setText("显示")
        self.api_key_toggle_btn.setFixedWidth(50)
        self.api_key_toggle_btn.clicked.connect(self._toggle_api_key_visibility)
        self.api_key_row = SettingsFieldRow("API Key", self.api_key_edit, self.api_key_toggle_btn)
        card_provider.add_field(self.api_key_row)

        self.api_base_url_edit = QLineEdit()
        self.api_base_url_edit.setPlaceholderText(DEFAULT_API_BASE_URL)
        self.api_base_url_field = SettingsField("Base URL", self.api_base_url_edit)
        card_provider.add_field(self.api_base_url_field)

        self.api_proxy_edit = QLineEdit()
        self.api_proxy_edit.setPlaceholderText(f"{DEFAULT_PROXY_URL} 或 socks5://...")
        self.api_proxy_field = SettingsField("代理 URL", self.api_proxy_edit)
        card_provider.add_field(self.api_proxy_field)

        self.browser_provider_hint = QLabel("浏览器源通过已打开的 Chrome/WebAI 网页工作，不使用 API Key、Base URL 或普通模型参数。")
        self.browser_provider_hint.setWordWrap(True)
        self.browser_provider_hint.setVisible(False)
        card_provider.add_widget(self.browser_provider_hint)

        probe_row = QHBoxLayout()
        probe_row.setSpacing(8)
        self.api_tool_capability_lbl = QLabel("")
        self.api_tool_capability_lbl.setWordWrap(True)
        self.api_probe_tools_btn = QPushButton("探测原生工具")
        self.api_probe_tools_btn.clicked.connect(self._probe_api_tool_support)
        probe_row.addWidget(self.api_tool_capability_lbl, 1)
        probe_row.addWidget(self.api_probe_tools_btn)
        card_provider.add_layout(probe_row)

        root.addWidget(card_provider)

        card_browser = SettingsCard("浏览器 Profile")
        self._card_browser = card_browser

        self.browser_source_combo = ScrollSafeComboBox()
        self.browser_source_combo.addItem("外接 Chrome 调试端口", "external_chrome")
        self.browser_source_combo.addItem("内置浏览器 WebEngine（尚不支持自动对话）", "embedded_qt")
        if os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1":
            self.browser_source_combo.model().item(1).setEnabled(False)
        card_browser.add_field(SettingsField(
            "浏览器源",
            self.browser_source_combo,
            "默认使用外接 Chrome，保持现有功能稳定；选择内置浏览器后，后续浏览器 Profile 会走 AI Bridge 内部 WebEngine 源。",
        ))

        self.browser_conversation_name_edit = QLineEdit()
        self.browser_conversation_name_edit.setPlaceholderText("例如：修复Subagentbug")
        card_browser.add_field(SettingsField(
            "网页目标对话名称",
            self.browser_conversation_name_edit,
            "必填。填 WebAI 网页左侧会话列表里看到的对话标题。软件会使用当前已打开并登录的 WebAI 浏览器页面，发送前先切到这个网页对话。",
        ))

        self.browser_profile_edit = QLineEdit()
        self.browser_profile_edit.setPlaceholderText("current_debug_session")
        self.browser_profile_field = SettingsField(
            "浏览器连接名",
            self.browser_profile_edit,
            "内部选项。一般保持 current_debug_session，表示使用当前已经打开并登录的 Chrome/WebAI 页面。",
        )
        self.browser_profile_field.setVisible(False)
        card_browser.add_field(self.browser_profile_field)

        self.browser_queue_spin = ScrollSafeSpinBox()
        self.browser_queue_spin.setRange(1, 50)
        self.browser_queue_spin.setSingleStep(1)
        card_browser.add_field(SettingsField(
            "同时任务数",
            self.browser_queue_spin,
            "建议保持 1。浏览器网页一次只处理一条消息，调大可能导致多个任务互相抢同一个网页。",
        ))

        root.addWidget(card_browser)

        card_model = SettingsCard("模型与参数")
        self._card_model = card_model

        self.api_model_combo = ScrollSafeComboBox()
        self.api_model_combo.setEditable(True)
        self.api_model_combo.currentTextChanged.connect(self._refresh_reasoning_controls_for_form)
        card_model.add_field(SettingsField("模型", self.api_model_combo))

        model_probe_row = QHBoxLayout()
        model_probe_row.setSpacing(8)
        self.api_models_probe_lbl = QLabel("")
        self.api_models_probe_lbl.setWordWrap(True)
        self.api_probe_models_btn = QPushButton("探测可用模型")
        self.api_probe_models_btn.clicked.connect(self._probe_api_models)
        model_probe_row.addWidget(self.api_models_probe_lbl, 1)
        model_probe_row.addWidget(self.api_probe_models_btn)
        card_model.add_layout(model_probe_row)

        self.api_temp_spin = ScrollSafeSpinBox()
        self.api_temp_spin.setRange(0, 20)
        self.api_temp_spin.setToolTip("温度 x10，例如 7 = 0.7")
        card_model.add_field(SettingsField("温度 (x10)", self.api_temp_spin, "例如 7 = 0.7"))

        self.api_max_tokens_spin = ScrollSafeSpinBox()
        self.api_max_tokens_spin.setRange(256, 128000)
        self.api_max_tokens_spin.setSingleStep(1024)
        card_model.add_field(SettingsField("最大输出 Tokens", self.api_max_tokens_spin))

        root.addWidget(card_model)

        card_context = SettingsCard("上下文与推理")
        self._card_context = card_context

        self.api_context_spin = ScrollSafeSpinBox()
        self.api_context_spin.setRange(4000, 200000)
        self.api_context_spin.setSingleStep(8000)
        card_context.add_field(SettingsField("上下文窗口 (Tokens)", self.api_context_spin))

        self.api_system_budget_spin = ScrollSafeSpinBox()
        self.api_system_budget_spin.setRange(500, 64000)
        self.api_system_budget_spin.setSingleStep(500)
        card_context.add_field(SettingsField("System Prompt 预算", self.api_system_budget_spin))

        self.api_developer_role_cb = QCheckBox("使用 developer role 发送核心提示词")
        self.api_developer_role_cb.setToolTip("适用于支持 developer role 的 OpenAI 兼容接口，用来降低供应商默认身份提示词的干扰。")
        card_context.add_widget(self.api_developer_role_cb)

        self.api_reasoning_cb = QCheckBox("启用深度思考")
        self.api_reasoning_cb.stateChanged.connect(self._refresh_reasoning_controls_for_form)
        card_context.add_widget(self.api_reasoning_cb)

        self.api_reasoning_effort = ScrollSafeComboBox()
        self.api_reasoning_effort.addItems(["low", "medium", "high"])
        self.api_reasoning_effort_field = SettingsField("思考强度", self.api_reasoning_effort)
        card_context.add_field(self.api_reasoning_effort_field)

        root.addWidget(card_context)

        card_effective = SettingsCard("当前生效配置")
        self._card_effective = card_effective

        self.api_effective_summary = QPlainTextEdit()
        self.api_effective_summary.setReadOnly(False)
        self.api_effective_summary.setFixedHeight(220)
        self.api_effective_summary.setPlaceholderText("这里显示当前 API 配置 JSON。可直接修改，保存时会应用。")
        self.api_effective_summary.textChanged.connect(self._on_effective_json_edited)
        card_effective.add_widget(self.api_effective_summary)

        root.addWidget(card_effective)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.api_reload_btn = QPushButton("重载")
        self.api_reload_btn.clicked.connect(self._reload_api_settings)
        self.api_apply_btn = QPushButton("保存并应用")
        self.api_apply_btn.clicked.connect(self._save_api_settings)
        btn_row.addWidget(self.api_reload_btn)
        btn_row.addWidget(self.api_apply_btn)
        root.addLayout(btn_row)

        root.addStretch()

    def load_from_config(self, config, api_config=None):
        self._loading_form = True
        if api_config:
            self.api_mode_config = api_config
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        self._reload_api_profile_list()

        provider = str(self.api_profile.get("provider", "openai_compatible") or "openai_compatible")
        if self.api_profile.get("kind") == "browser_stateless":
            provider = "web_ai"
        self.api_provider_combo.blockSignals(True)
        idx = self.api_provider_combo.findData(provider)
        if idx >= 0:
            self.api_provider_combo.setCurrentIndex(idx)
        self.api_provider_combo.blockSignals(False)

        self.api_key_edit.setText(self.api_profile.get("api_key", ""))
        self.api_base_url_edit.setText(self.api_profile.get("base_url", DEFAULT_API_BASE_URL))
        self.api_proxy_edit.setText(self.api_profile.get("proxy_url", ""))

        saved_model = self.api_profile.get("model", DEFAULT_API_MODEL)
        self._refresh_provider_ui(provider=provider, model_text=saved_model)

        self.api_temp_spin.setValue(int(round(float(self.api_profile.get("temperature", 0.7)) * 10)))
        self.api_max_tokens_spin.setValue(int(self.api_profile.get("max_output_tokens", 4096)))
        self.api_context_spin.setValue(int(self.api_mode_config.get("conversation_defaults", {}).get("context", {}).get("max_window_tokens", 128000)))
        self.api_system_budget_spin.setValue(int(self.api_mode_config.get("conversation_defaults", {}).get("context", {}).get("system_budget", 8000)))
        self.api_developer_role_cb.setChecked(
            str(self.api_profile.get("system_prompt_role", "system") or "system").strip().lower() == "developer"
        )
        self.api_reasoning_cb.setChecked(bool(self.api_profile.get("reasoning", {}).get("enabled", False)))

        effort = str(self.api_profile.get("reasoning", {}).get("effort", "medium"))
        idx_effort = self.api_reasoning_effort.findText(effort)
        if idx_effort >= 0:
            self.api_reasoning_effort.setCurrentIndex(idx_effort)
        else:
            self.api_reasoning_effort.setCurrentText("medium")
        self._refresh_reasoning_controls_for_form(provider=provider, model_text=saved_model)

        self.browser_conversation_name_edit.setText(
            self.api_profile.get("conversation_name", "")
            or (
                self.api_profile.get("browser_profile", "")
                if self.api_profile.get("browser_profile", "") != "current_debug_session"
                else ""
            )
        )
        self.browser_profile_edit.setText(self.api_profile.get("browser_profile", "current_debug_session"))
        source = str(self.api_profile.get("browser_source", "external_chrome") or "external_chrome")
        source_idx = self.browser_source_combo.findData(source)
        self.browser_source_combo.setCurrentIndex(source_idx if source_idx >= 0 else 0)
        self.browser_queue_spin.setValue(int(self.api_profile.get("max_queue_size", 1)))

        self._refresh_profile_kind_ui()
        self._loading_form = False
        self._refresh_tool_capability_label()
        self.refresh_effective_summary()

    def collect_config(self):
        return {}

    def _collect_api_config_from_form(self, base_config=None):
        config = deepcopy(base_config or self.api_mode_config or APIModeConfigManager.load())
        active_profile_name = config.get("active_profile", "default")
        profiles = config.setdefault("profiles", {})
        profile = profiles.setdefault(active_profile_name, {})

        provider = self._current_provider()
        if provider == "web_ai":
            profile["kind"] = "browser_stateless"
            profile["provider"] = "web_ai"
            profile["conversation_name"] = self.browser_conversation_name_edit.text().strip()
            profile.setdefault("conversation_url", "")
            profile["browser_source"] = self.browser_source_combo.currentData() or "external_chrome"
            profile["browser_profile"] = self.browser_profile_edit.text().strip() or "current_debug_session"
            profile["supports_parallel"] = False
            profile["cost_level"] = profile.get("cost_level", "low")
            profile["role"] = profile.get("role", "primary_reasoning")
            profile["reliability_level"] = profile.get("reliability_level", "medium")
            profile["timeout_seconds"] = int(profile.get("timeout_seconds", profile.get("timeout", 180)) or 180)
            profile["timeout"] = int(profile.get("timeout", profile.get("timeout_seconds", 180)) or 180)
            profile["max_queue_size"] = self.browser_queue_spin.value()
            for legacy_key in ("allow_api_assist", "allow_api_takeover", "takeover_policy", "forbidden_task_types"):
                profile.pop(legacy_key, None)
        else:
            profile["kind"] = "api"
            profile["provider"] = provider
            profile["api_key"] = self.api_key_edit.text().strip()
            if provider == "gemini":
                profile["base_url"] = ""
            elif provider == "mimo":
                base_url = self.api_base_url_edit.text().strip()
                profile["base_url"] = base_url if base_url else MIMO_DEFAULT_BASE_URL
            else:
                profile["base_url"] = self.api_base_url_edit.text().strip()
            profile["proxy_url"] = self.api_proxy_edit.text().strip()
            profile["model"] = self.api_model_combo.currentText().strip()
            profile["temperature"] = self.api_temp_spin.value() / 10.0
            profile["max_output_tokens"] = self.api_max_tokens_spin.value()
            profile["system_prompt_role"] = "developer" if self.api_developer_role_cb.isChecked() else "system"
            profile.setdefault("reasoning", {})
            profile["reasoning"].update(self._form_reasoning_payload(provider=provider, model_text=profile["model"]))

        config.setdefault("conversation_defaults", {}).setdefault("context", {})
        config["conversation_defaults"]["context"]["max_window_tokens"] = self.api_context_spin.value()
        config["conversation_defaults"]["context"]["system_budget"] = self.api_system_budget_spin.value()

        return APIModeConfigManager._normalize(config)

    def collect_api_config(self):
        if self._effective_json_dirty:
            try:
                parsed = json.loads(self.api_effective_summary.toPlainText() or "{}")
                if not isinstance(parsed, dict):
                    raise ValueError("顶层必须是 JSON object")
                self.api_mode_config = APIModeConfigManager._normalize(parsed)
                self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
                return self.api_mode_config
            except Exception as e:
                UIHelper.warning(self, "JSON 格式错误", f"当前生效配置不是有效 JSON，无法保存：\n{e}")
                raise

        self.api_mode_config = self._collect_api_config_from_form()
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        return self.api_mode_config

    def _current_provider(self):
        return str(self.api_provider_combo.currentData() or "openai_compatible")

    def _current_form_profile(self, provider=None, model_text=None):
        provider = provider or self._current_provider()
        profile = deepcopy(self.api_profile) if isinstance(self.api_profile, dict) else {}
        profile["provider"] = provider
        profile["kind"] = "browser_stateless" if provider == "web_ai" else "api"
        profile["model"] = model_text if model_text is not None else self.api_model_combo.currentText().strip()
        profile["base_url"] = self.api_base_url_edit.text().strip()
        if provider == "mimo" and not profile["base_url"]:
            profile["base_url"] = MIMO_DEFAULT_BASE_URL
        profile["reasoning"] = {
            "enabled": bool(self.api_reasoning_cb.isChecked()),
            "effort": str(self.api_reasoning_effort.currentData() or self.api_reasoning_effort.currentText() or "medium").strip(),
        }
        return profile

    def _set_reasoning_effort_options(self, efforts, selected="medium"):
        options = [str(e).strip().lower() for e in (efforts or []) if str(e).strip().lower() in ("low", "medium", "high")]
        if not options:
            options = ["medium"]
        selected = str(selected or "medium").strip().lower()
        if selected not in options:
            selected = "medium" if "medium" in options else options[0]

        self.api_reasoning_effort.blockSignals(True)
        self.api_reasoning_effort.clear()
        for effort in options:
            self.api_reasoning_effort.addItem(effort, effort)
        idx = self.api_reasoning_effort.findData(selected)
        self.api_reasoning_effort.setCurrentIndex(idx if idx >= 0 else 0)
        self.api_reasoning_effort.blockSignals(False)

    def _refresh_reasoning_controls_for_form(self, *_args, provider=None, model_text=None):
        if not hasattr(self, "api_reasoning_cb"):
            return
        provider = provider or self._current_provider()
        profile = self._current_form_profile(provider=provider, model_text=model_text)
        capability = resolve_model_capability(profile, profile.get("model"))
        reasoning_cap = capability.get("reasoning", {})
        mode = str(reasoning_cap.get("mode") or REASONING_MODE_NONE)
        normalized = normalize_reasoning_for_capability(profile.get("reasoning"), capability)

        self._set_reasoning_effort_options(reasoning_cap.get("efforts") or [], normalized.get("effort", "medium"))
        if mode != REASONING_MODE_NONE:
            self.api_reasoning_cb.blockSignals(True)
            self.api_reasoning_cb.setChecked(bool(normalized.get("enabled")))
            self.api_reasoning_cb.blockSignals(False)

        is_browser = provider == "web_ai"
        self.api_reasoning_cb.setVisible((not is_browser) and mode != REASONING_MODE_NONE)
        self.api_reasoning_cb.setEnabled((not is_browser) and mode != REASONING_MODE_NONE)
        self.api_reasoning_cb.setToolTip(reasoning_tooltip(capability))
        self.api_reasoning_effort_field.setVisible((not is_browser) and mode == REASONING_MODE_EFFORT)
        self.api_reasoning_effort.setEnabled((not is_browser) and mode == REASONING_MODE_EFFORT and self.api_reasoning_cb.isChecked())
        self.api_reasoning_effort.setToolTip(reasoning_tooltip(capability))

    def _form_reasoning_payload(self, provider=None, model_text=None):
        profile = self._current_form_profile(provider=provider, model_text=model_text)
        capability = resolve_model_capability(profile, profile.get("model"))
        return normalize_reasoning_for_capability(profile.get("reasoning"), capability)

    def _connect_effective_json_sync(self):
        widgets = [
            self.api_provider_combo, self.api_key_edit, self.api_base_url_edit, self.api_proxy_edit,
            self.api_model_combo, self.api_temp_spin, self.api_max_tokens_spin,
            self.api_context_spin, self.api_system_budget_spin,
            self.api_developer_role_cb, self.api_reasoning_cb, self.api_reasoning_effort,
            self.browser_conversation_name_edit, self.browser_profile_edit,
            self.browser_source_combo,
            self.browser_queue_spin,
        ]
        for widget in widgets:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._on_form_changed_for_effective_json)
            if hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(self._on_form_changed_for_effective_json)
            if hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._on_form_changed_for_effective_json)
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._on_form_changed_for_effective_json)
            if hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self._on_form_changed_for_effective_json)
            if hasattr(widget, "toggled"):
                widget.toggled.connect(self._on_form_changed_for_effective_json)

    def _on_form_changed_for_effective_json(self, *args):
        if self._loading_form or self._syncing_effective_json:
            return
        self._effective_json_dirty = False
        self.refresh_effective_summary()

    def _on_effective_json_edited(self):
        if self._syncing_effective_json:
            return
        self._effective_json_dirty = True

    def _refresh_provider_ui(self, provider=None, model_text=None):
        provider = provider or self._current_provider()
        model_text = model_text if model_text is not None else self.api_model_combo.currentText().strip()

        profile_models = self._profile_available_models(provider)
        if profile_models:
            models = profile_models
        elif provider == "gemini":
            models = self.GEMINI_MODELS
        elif provider == "mimo":
            models = self.MIMO_MODELS
        else:
            models = self.OPENAI_COMPAT_MODELS

        self.api_model_combo.blockSignals(True)
        self.api_model_combo.clear()
        self.api_model_combo.addItems(models)
        if model_text:
            idx = self.api_model_combo.findText(model_text)
            if idx >= 0:
                self.api_model_combo.setCurrentIndex(idx)
            else:
                self.api_model_combo.setCurrentText(model_text)
        self.api_model_combo.blockSignals(False)

        if provider == "gemini":
            self.api_key_edit.setPlaceholderText("Google AI Studio Gemini API Key")
            self.api_base_url_edit.setPlaceholderText("Gemini SDK 模式无需填写")
            self.api_base_url_edit.setEnabled(False)
        elif provider == "mimo":
            self.api_key_edit.setPlaceholderText("小米 MiMo API Key")
            self.api_base_url_edit.setPlaceholderText(MIMO_DEFAULT_BASE_URL)
            self.api_base_url_edit.setEnabled(True)
        elif provider == "web_ai":
            self.api_key_edit.setPlaceholderText("网页 AI Profile 不使用 API Key")
            self.api_base_url_edit.setPlaceholderText("网页 AI Profile 不使用 Base URL")
            self.api_base_url_edit.setEnabled(False)
        else:
            self.api_key_edit.setPlaceholderText("sk-... 或 API 密钥")
            self.api_base_url_edit.setPlaceholderText(self.OPENAI_DEFAULT_BASE_URL)
            self.api_base_url_edit.setEnabled(True)
        self._refresh_profile_kind_ui()

    def _profile_available_models(self, provider=None):
        provider = provider or self._current_provider()
        model_payload = self.api_profile.get("available_models")
        if not isinstance(model_payload, dict):
            return []
        payload_provider = str(model_payload.get("provider", "") or "").strip()
        if payload_provider and payload_provider != provider:
            return []
        return [str(m).strip() for m in (model_payload.get("models") or []) if str(m).strip()]

    def _set_model_combo_options(self, models, selected=None):
        models = [str(m).strip() for m in (models or []) if str(m).strip()]
        if not models:
            return
        selected = str(selected or "").strip()
        self.api_model_combo.blockSignals(True)
        self.api_model_combo.clear()
        self.api_model_combo.addItems(models)
        self.api_model_combo.setMaxVisibleItems(max(5, min(len(models), 20)))
        target = selected if selected in models else models[0]
        idx = self.api_model_combo.findText(target)
        if idx >= 0:
            self.api_model_combo.setCurrentIndex(idx)
        else:
            self.api_model_combo.setCurrentText(target)
        self.api_model_combo.blockSignals(False)
        self._refresh_reasoning_controls_for_form(model_text=target)

    def _remember_available_models(self, result, models, selected):
        active = self.api_mode_config.get("active_profile", "default")
        profiles = self.api_mode_config.setdefault("profiles", {})
        profile = profiles.setdefault(active, {})
        profile["model"] = selected
        profile["available_models"] = {
            "provider": self._current_provider(),
            "models": list(models),
            "source": str(result.get("source", "") or ""),
            "checked_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "endpoint_ok": bool(result.get("endpoint_ok")),
            "raw_model_count": int(result.get("raw_model_count", len(models)) or len(models)),
        }
        self.api_mode_config = APIModeConfigManager._normalize(self.api_mode_config)
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        APIModeConfigManager.save(self.api_mode_config)

    def _on_api_provider_changed(self):
        provider = self._current_provider()
        self._apply_provider_defaults(provider)
        self._refresh_provider_ui(provider=provider, model_text=self._provider_default_model(provider))

    def _provider_default_model(self, provider: str) -> str:
        if provider == "gemini":
            return self.GEMINI_MODELS[0] if self.GEMINI_MODELS else ""
        if provider == "mimo":
            return self.MIMO_MODELS[0] if self.MIMO_MODELS else ""
        if provider == "web_ai":
            return ""
        return self.OPENAI_COMPAT_MODELS[0] if self.OPENAI_COMPAT_MODELS else ""

    def _apply_provider_defaults(self, provider: str):
        current_base_url = self.api_base_url_edit.text().strip()
        known_default_urls = {
            "",
            self.OPENAI_DEFAULT_BASE_URL,
            MIMO_DEFAULT_BASE_URL,
        }
        if provider == "mimo":
            if current_base_url in known_default_urls:
                self.api_base_url_edit.setText(MIMO_DEFAULT_BASE_URL)
        elif provider == "openai_compatible":
            if current_base_url in ("", MIMO_DEFAULT_BASE_URL):
                self.api_base_url_edit.setText(self.OPENAI_DEFAULT_BASE_URL)
        elif provider in ("gemini", "web_ai"):
            if current_base_url in known_default_urls:
                self.api_base_url_edit.setText("")

    def _refresh_profile_kind_ui(self):
        is_browser = self._current_provider() == "web_ai"
        if os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1":
            self.browser_provider_hint.setText("此本地版本未启用无状态网页 Profile；请使用聊天页的浏览器标签，避免自动清空网站对话。")
        is_gemini = self._current_provider() == "gemini"
        self._card_browser.setVisible(is_browser)
        self._card_model.setVisible(not is_browser)
        self.api_key_row.setVisible(not is_browser)
        self.api_base_url_field.setVisible(not is_browser)
        self.api_proxy_field.setVisible(not is_browser)
        self.browser_provider_hint.setVisible(is_browser)
        self.api_developer_role_cb.setVisible(not is_browser)
        self.api_base_url_edit.setEnabled((not is_browser) and (not is_gemini))
        if hasattr(self, "api_probe_tools_btn"):
            self.api_probe_tools_btn.setEnabled(not is_browser)
        if hasattr(self, "api_probe_models_btn"):
            self.api_probe_models_btn.setEnabled(not is_browser)
        self._refresh_reasoning_controls_for_form()
        self._refresh_tool_capability_label()

    def _format_tool_capability(self, capability=None):
        capability = capability or self.api_profile.get("tool_capability", {}) or {}
        status = str(capability.get("status", "unknown") or "unknown")
        protocol = str(capability.get("protocol", "") or "")
        reason = str(capability.get("reason", "") or "")

        if self._current_provider() == "web_ai" or protocol == TOOL_PROTOCOL_MARKDOWN_ONLY:
            return "工具协议：网页源固定使用 Markdown 回退，不发起原生工具探测。"
        if status == "supported" or protocol == TOOL_PROTOCOL_NATIVE:
            return "工具协议：已支持原生工具调用。"
        if status == "unsupported":
            suffix = f"（{reason}）" if reason else ""
            return f"工具协议：不支持原生工具，使用 Markdown 回退{suffix}。"
        if status == "partial":
            suffix = f"（{reason}）" if reason else ""
            return f"工具协议：探测不确定，暂用 Markdown 回退{suffix}。"
        return "工具协议：尚未探测，默认先使用 Markdown 回退。"

    def _refresh_tool_capability_label(self):
        if not hasattr(self, "api_tool_capability_lbl"):
            return
        self.api_tool_capability_lbl.setText(self._format_tool_capability())

    def set_api_tool_probe_pending(self, pending):
        if not hasattr(self, "api_probe_tools_btn"):
            return
        self.api_probe_tools_btn.setEnabled(not pending and self._current_provider() != "web_ai")
        self.api_probe_tools_btn.setText("探测中..." if pending else "探测原生工具")
        if pending and hasattr(self, "api_tool_capability_lbl"):
            self.api_tool_capability_lbl.setText("工具协议：正在向当前 API Profile 发送原生工具探测请求...")

    def on_api_tool_probe_result(self, result):
        self.set_api_tool_probe_pending(False)
        self.api_mode_config = APIModeConfigManager.load()
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        self._refresh_tool_capability_label()
        if result:
            self.api_tool_capability_lbl.setText(self._format_tool_capability(result))
        self.refresh_effective_summary()

    def set_api_models_probe_pending(self, pending):
        if not hasattr(self, "api_probe_models_btn"):
            return
        self.api_probe_models_btn.setEnabled(not pending and self._current_provider() != "web_ai")
        self.api_probe_models_btn.setText("探测中..." if pending else "探测可用模型")
        if pending and hasattr(self, "api_models_probe_lbl"):
            self.api_models_probe_lbl.setText("模型探测：正在读取当前 API Profile 的模型列表...")

    def on_api_models_probe_result(self, result):
        self.set_api_models_probe_pending(False)
        result = result or {}
        models = [str(m).strip() for m in (result.get("models") or []) if str(m).strip()]
        if result.get("ok") and models:
            current_text = self.api_model_combo.currentText().strip()
            selected = current_text if current_text in models else models[0]
            self._set_model_combo_options(models, selected=selected)
            self._remember_available_models(result, models, selected)
            preview = ", ".join(models[:5])
            suffix = "..." if len(models) > 5 else ""
            source = str(result.get("source", "") or "")
            endpoint_ok = bool(result.get("endpoint_ok"))
            reason = str(result.get("reason", "") or "").strip()
            if source == "provider_catalog":
                endpoint_text = "在线列表不可用" if not endpoint_ok else "在线列表未返回模型"
                detail = f"；{endpoint_text}：{reason[:120]}" if reason else f"；{endpoint_text}"
                self.api_models_probe_lbl.setText(
                    f"模型探测：已使用 Provider 官方模型目录，并更新模型下拉框，载入 {len(models)} 个模型：{preview}{suffix}{detail}"
                )
            elif source == "models_endpoint_filtered":
                raw_count = int(result.get("raw_model_count", len(models)) or len(models))
                self.api_models_probe_lbl.setText(
                    f"模型探测：在线读取成功，返回 {raw_count} 个模型，已过滤到 {len(models)} 个聊天模型并更新下拉框：{preview}{suffix}"
                )
            else:
                self.api_models_probe_lbl.setText(f"模型探测：在线读取成功，已更新下拉框，发现 {len(models)} 个模型：{preview}{suffix}")
        else:
            reason = str(result.get("reason", "") or "未返回模型列表")
            self.api_models_probe_lbl.setText(f"模型探测：失败或无结果（{reason}）")
        self.refresh_effective_summary()

    def _on_api_profile_changed(self):
        key = self.api_profile_combo.currentData()
        if not key:
            return
        try:
            APIModeConfigManager.set_active_profile(str(key))
            self.api_mode_config = APIModeConfigManager.load()
            if self.api_mode_config.get("fallback_chain"):
                active = self.api_mode_config.get("active_profile", "default")
                self.api_mode_config["fallback_chain"] = [x for x in self.api_mode_config.get("fallback_chain", []) if x != active]
                APIModeConfigManager.save(self.api_mode_config)
                self.api_mode_config = APIModeConfigManager.load()
            self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
            self._reload_api_profile_list()
            self.load_from_config(self.config, self.api_mode_config)
            self.config_changed.emit({"action": "api_profile_changed"})
        except Exception as e:
            UIHelper.warning(self, "切换失败", str(e))

    def _create_api_profile(self):
        name, ok = QInputDialog.getText(self, "新建模型配置", "请给这套模型配置起个名字")
        if not ok or not name.strip():
            return
        key = name.strip()
        try:
            APIModeConfigManager.create_profile(key, {"name": key})
            self.api_mode_config = APIModeConfigManager.load()
            self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
            self._reload_api_profile_list()
            self.load_from_config(self.config, self.api_mode_config)
            UIHelper.info(self, "已创建", f"Profile 已创建: {key}")
        except Exception as e:
            UIHelper.warning(self, "创建失败", str(e))

    def _create_browser_profile(self):
        if os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1":
            UIHelper.warning(self, "请使用浏览器标签", "本地版本不启用会清空网站对话的无状态网页 Profile。")
            return
        name, ok = QInputDialog.getText(self, "新建浏览器 Profile", "请给这套浏览器 Profile 起个名字")
        if not ok or not name.strip():
            return
        key = name.strip()
        try:
            APIModeConfigManager.create_browser_stateless_profile(key, {"name": key})
            self.api_mode_config = APIModeConfigManager.load()
            self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
            self._reload_api_profile_list()
            self.load_from_config(self.config, self.api_mode_config)
            UIHelper.info(self, "已创建", f"浏览器 Profile 已创建: {key}")
        except Exception as e:
            UIHelper.warning(self, "创建失败", str(e))

    def _rename_api_profile(self):
        old_key = self.api_profile_combo.currentData()
        if not old_key:
            return
        name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=str(old_key))
        if not ok or not name.strip() or name.strip() == old_key:
            return
        try:
            APIModeConfigManager.rename_profile(str(old_key), name.strip())
            self.api_mode_config = APIModeConfigManager.load()
            self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
            self._reload_api_profile_list()
            self.load_from_config(self.config, self.api_mode_config)
            UIHelper.info(self, "已重命名", f"配置已重命名为: {name.strip()}")
        except Exception as e:
            UIHelper.warning(self, "重命名失败", str(e))

    def _delete_api_profile(self):
        key = self.api_profile_combo.currentData()
        if not key:
            return
        reply = QMessageBox.question(self, "删除 Profile", f"确认删除 Profile: {key}?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            APIModeConfigManager.delete_profile(str(key))
            self.api_mode_config = APIModeConfigManager.load()
            self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
            self._reload_api_profile_list()
            self.load_from_config(self.config, self.api_mode_config)
            UIHelper.info(self, "已删除", f"Profile 已删除: {key}")
        except Exception as e:
            UIHelper.warning(self, "删除失败", str(e))

    def _toggle_api_key_visibility(self):
        if self.api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.api_key_toggle_btn.setText("隐藏")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.api_key_toggle_btn.setText("显示")

    def _reload_api_settings(self):
        self.api_mode_config = APIModeConfigManager.load()
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        self.load_from_config(self.config, self.api_mode_config)
        UIHelper.info(self, "已重载", "API 配置已从文件重新加载。")

    def _probe_api_tool_support(self):
        try:
            api_config = self.collect_api_config()
        except Exception:
            return
        APIModeConfigManager.save(api_config)
        self.api_mode_config = APIModeConfigManager.load()
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        self.config_changed.emit({"action": "api_probe_tools"})

    def _probe_api_models(self):
        try:
            api_config = self.collect_api_config()
        except Exception:
            return
        APIModeConfigManager.save(api_config)
        self.api_mode_config = APIModeConfigManager.load()
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        self.config_changed.emit({"action": "api_probe_models"})

    def _save_api_settings(self):
        try:
            api_config = self.collect_api_config()
        except Exception:
            return
        active = api_config.get("active_profile", "default")
        profile = (api_config.get("profiles", {}) or {}).get(active, {})
        if profile.get("kind") == "browser_stateless" and not (
            str(profile.get("conversation_name") or "").strip()
            or str(profile.get("conversation_url") or "").strip()
        ):
            logger.warning("[SettingsApi] browser Profile save blocked: empty conversation target | profile=%s", active)
            UIHelper.warning(
                self,
                "缺少目标对话",
                f"浏览器 Profile「{active}」还没有填写目标对话名称。\n请填写网页左侧会话列表里的对话名称后再保存。",
            )
            return
        logger.info(
            "[SettingsApi] saving API config | active=%s kind=%s conversation_name=%s conversation_url=%s",
            active,
            profile.get("kind"),
            profile.get("conversation_name", ""),
            profile.get("conversation_url", ""),
        )
        APIModeConfigManager.save(api_config)
        self.api_mode_config = APIModeConfigManager.load()
        self.api_profile = APIModeConfigManager.get_editing_profile(self.api_mode_config)
        self.load_from_config(self.config, self.api_mode_config)
        self.config_changed.emit({"action": "api_saved"})
        UIHelper.info(self, "已保存", "API 配置已保存。")

    def _reload_api_profile_list(self):
        if not hasattr(self, "api_profile_combo"):
            return
        cfg = APIModeConfigManager.load()
        active = cfg.get("active_profile", "default")
        profiles = cfg.get("profiles", {})
        self.api_profile_combo.blockSignals(True)
        self.api_profile_combo.clear()
        for key in profiles.keys():
            self.api_profile_combo.addItem(key, key)
        idx = self.api_profile_combo.findData(active)
        if idx >= 0:
            self.api_profile_combo.setCurrentIndex(idx)
        self.api_profile_combo.blockSignals(False)

    def refresh_effective_summary(self, runtime_applied=False):
        try:
            cfg = self._collect_api_config_from_form()
            summary = json.dumps(cfg, ensure_ascii=False, indent=2)
            self._syncing_effective_json = True
            self.api_effective_summary.setPlainText(summary)
            self._effective_json_dirty = False
        except Exception:
            pass
        finally:
            self._syncing_effective_json = False

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")

        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "sectionTitle":
                lbl.setStyleSheet(Theme.section_title())
            elif lbl.objectName() == "sectionSubtitle":
                lbl.setStyleSheet(Theme.section_subtitle())

        for card in [self._card_profile, self._card_provider, self._card_browser, self._card_model,
                      self._card_context, self._card_effective]:
            card.setStyleSheet(card_style())

        input_ss = Theme.input_field()
        for w in [self.api_key_edit, self.api_base_url_edit, self.api_proxy_edit,
                   self.api_temp_spin, self.api_max_tokens_spin,
                   self.api_context_spin, self.api_system_budget_spin,
                   self.browser_conversation_name_edit, self.browser_profile_edit,
                   self.browser_queue_spin]:
            w.setStyleSheet(input_ss)

        for cb in [self.api_profile_combo, self.api_provider_combo,
                    self.api_model_combo, self.api_reasoning_effort]:
            cb.setStyleSheet(Theme.combo_box())

        self.api_effective_summary.setStyleSheet(Theme.log_editor())
        for cb in [self.api_developer_role_cb, self.api_reasoning_cb]:
            cb.setStyleSheet(f"color: {p.TEXT_PRIMARY};")

        self.browser_provider_hint.setStyleSheet(
            f"color: {p.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
        )
        self.api_tool_capability_lbl.setStyleSheet(
            f"color: {p.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
        )
        self.api_models_probe_lbl.setStyleSheet(
            f"color: {p.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
        )

        btn_ss = f"background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 6px; padding: 5px 12px;"
        for btn in [self.api_profile_add_btn, self.api_browser_profile_add_btn, self.api_profile_rename_btn,
                     self.api_profile_del_btn, self.api_key_toggle_btn,
                     self.api_reload_btn, self.api_probe_tools_btn, self.api_probe_models_btn]:
            btn.setStyleSheet(btn_ss)

        self.api_apply_btn.setStyleSheet(Theme.button_primary())
