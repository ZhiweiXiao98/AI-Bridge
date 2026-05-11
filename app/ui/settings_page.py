import os
import warnings

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QStackedWidget,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QTimer

from app.core.config import ConfigManager
from app.core.api_mode_config import APIModeConfigManager
from app.ui.theme import get_available_themes, THEME_DIR, theme_manager, Theme
from app.ui.components.theme_editor import ThemeEditorDialog
from app.ui.components.settings.knowledge_rules_card import KnowledgeRulesCard
from app.ui.components.settings.settings_nav import SettingsNav
from app.ui.components.settings.settings_basic import SettingsBasicSection
from app.ui.components.settings.settings_api import SettingsApiSection
from app.ui.components.settings.settings_api_fallback import SettingsApiFallbackSection
from app.ui.components.settings.settings_api_usage import SettingsApiUsageSection
from app.ui.components.settings.settings_daemon import SettingsDaemonSection
from app.ui.components.settings.settings_context import SettingsContextSection
from app.ui.components.settings.settings_blacklist import SettingsBlacklistSection
from app.ui.components.settings.settings_styles import all_styles, bottom_bar_style
from app.ui.components.settings.settings_widgets import ScrollSafeFilter
from app.ui.pages.console_page import UIHelper
from app.core.logging import get_logger

logger = get_logger("app.ui.settings_page", side="ui")


SECTIONS = [
    {"id": "basic", "title": "基础配置"},
    {"id": "api", "title": "API 配置"},
    {"id": "api_fallback", "title": "Fallback"},
    {"id": "api_usage", "title": "对话配置"},
    {"id": "daemon", "title": "守护进程"},
    {"id": "context", "title": "快照推送"},
    {"id": "blacklist", "title": "黑名单"},
]


class SettingsPage(QWidget):
    config_saved = Signal(object)
    request_snapshot = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager.load()
        self.api_mode_config = APIModeConfigManager.load()
        self._last_api_context_status = {}
        self._scroll_filters = []

        self._build_ui()

        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

        QTimer.singleShot(1000, self.bind_worker_signals)

    def closeEvent(self, event):
        try:
            theme_manager.theme_changed.disconnect(self.apply_theme)
        except Exception as e:
            logger.warning(e)
        super().closeEvent(event)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav = SettingsNav(SECTIONS)
        self.nav.nav_changed.connect(self._on_nav_changed)
        root.addWidget(self.nav)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        self.stack = QStackedWidget()
        self._sections = {}
        self._create_sections()
        center.addWidget(self.stack, 1)

        bottom = QFrame()
        bottom.setObjectName("settingsBottomBar")
        bottom.setFixedHeight(56)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(24, 8, 24, 8)
        bottom_layout.setSpacing(12)

        self.save_btn = QPushButton("保存配置")
        self.save_btn.clicked.connect(self.save_settings)
        bottom_layout.addWidget(self.save_btn)

        bottom_layout.addStretch()
        center.addWidget(bottom)

        root.addLayout(center, 1)

        self.nav.set_current(0)

    def _create_sections(self):
        section_classes = {
            "basic": SettingsBasicSection,
            "api": SettingsApiSection,
            "api_fallback": SettingsApiFallbackSection,
            "api_usage": SettingsApiUsageSection,
            "daemon": SettingsDaemonSection,
            "context": SettingsContextSection,
            "blacklist": SettingsBlacklistSection,
        }

        for i, sec_info in enumerate(SECTIONS):
            sec_id = sec_info["id"]
            cls = section_classes.get(sec_id)
            if not cls:
                continue

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setObjectName("settingsSectionScroll")

            if sec_id == "basic":
                widget = cls(config=self.config)
            elif sec_id == "api":
                widget = cls(config=self.config, api_config=self.api_mode_config)
            elif sec_id in ("api_fallback", "api_usage"):
                widget = cls(api_config=self.api_mode_config)
            elif sec_id == "daemon":
                widget = cls(config=self.config, api_config=self.api_mode_config)
            elif sec_id == "blacklist":
                widget = cls(config=self.config)
            else:
                widget = cls()

            widget.config_changed.connect(self._on_section_config_changed)

            if sec_id == "context" and hasattr(widget, "request_snapshot"):
                widget.request_snapshot.connect(self.request_snapshot.emit)

            scroll_filter = ScrollSafeFilter(scroll)
            scroll_filter.install()
            self._scroll_filters.append(scroll_filter)

            scroll.setWidget(widget)
            self.stack.addWidget(scroll)
            self._sections[sec_id] = widget

        self.knowledge_rules_card = KnowledgeRulesCard(self.config)

    def _on_nav_changed(self, index):
        self.stack.setCurrentIndex(index)

    def _on_section_config_changed(self, payload):
        action = payload.get("action", "") if isinstance(payload, dict) else ""
        if action in ("api_saved", "api_profile_changed", "api_usage_saved", "daemon_saved"):
            self._try_reload_api_runtime()
        elif action == "theme_preview":
            theme_name = payload.get("theme", "")
            if theme_name:
                theme_manager.set_theme(theme_name)

    def _try_reload_api_runtime(self):
        main_win = self.window()
        worker = getattr(main_win, "worker", None)
        if worker and hasattr(worker, "reload_api_runtime_config"):
            try:
                return bool(worker.reload_api_runtime_config())
            except Exception:
                return False
        return False

    def bind_worker_signals(self):
        main_win = self.window()
        worker = getattr(main_win, "worker", None)
        if not worker:
            return

        if hasattr(worker, "sessions_signal"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    worker.sessions_signal.disconnect(self.on_sessions_update)
                except Exception:
                    pass
            worker.sessions_signal.connect(self.on_sessions_update)

        if hasattr(worker, "context_status_signal"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    worker.context_status_signal.disconnect(self.on_api_context_status_update)
                except Exception:
                    pass
            worker.context_status_signal.connect(self.on_api_context_status_update)

    def on_sessions_update(self, sessions):
        ctx_section = self._sections.get("context")
        if ctx_section and hasattr(ctx_section, "on_sessions_update"):
            ctx_section.on_sessions_update(sessions)

    def on_api_context_status_update(self, payload):
        self._last_api_context_status = payload or {}
        api_section = self._sections.get("api")
        if api_section and hasattr(api_section, "refresh_effective_summary"):
            api_section.refresh_effective_summary(runtime_applied=False)

    def save_settings(self):
        old_theme = self.config.get("theme", "Dark")

        basic = self._sections.get("basic")
        daemon = self._sections.get("daemon")
        blacklist = self._sections.get("blacklist")
        api_usage = self._sections.get("api_usage")

        new_config = {}
        if basic:
            new_config.update(basic.collect_config())
        if daemon:
            new_config.update(daemon.collect_config())
        if blacklist:
            new_config.update(blacklist.collect_config())

        if basic:
            new_config["theme"] = basic.theme_combo.currentText()

        new_config.update(self.knowledge_rules_card.to_config_dict())

        ConfigManager.save(new_config)
        self.config = ConfigManager.load()
        self.config_saved.emit(new_config)

        if api_usage:
            api_cfg = api_usage.collect_api_config()
            APIModeConfigManager.save(api_cfg)
            self.api_mode_config = APIModeConfigManager.load()

        new_theme = new_config.get("theme", "Dark")
        if old_theme != new_theme:
            theme_manager.reload_from_config()
            UIHelper.info(self, "已应用", f"主题已切换为: {new_theme}")
        else:
            UIHelper.info(self, "已保存", "全局配置已更新。")

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(all_styles() + f"background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY};")

        self.nav.apply_theme()

        for sec_id, section in self._sections.items():
            if hasattr(section, "apply_theme"):
                section.apply_theme()

        for i in range(self.stack.count()):
            scroll_area = self.stack.widget(i)
            if scroll_area and isinstance(scroll_area, QScrollArea):
                scroll_area.setStyleSheet(
                    f"QScrollArea#settingsSectionScroll {{ background-color: {p.BG_PRIMARY}; border: none; }}"
                )
                content = scroll_area.widget()
                if content:
                    content.setStyleSheet(f"background-color: {p.BG_PRIMARY};")

        bottom = self.findChild(QFrame, "settingsBottomBar")
        if bottom:
            bottom.setStyleSheet(bottom_bar_style())

        self.save_btn.setStyleSheet(Theme.button_primary())

        if hasattr(self, "knowledge_rules_card") and self.knowledge_rules_card is not None:
            try:
                self.knowledge_rules_card.apply_theme(theme_manager.current_palette)
            except RuntimeError:
                pass
