from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Signal

from app.core.api_mode_config import APIModeConfigManager
from app.ui.theme import Theme, theme_manager
from app.ui.components.settings.settings_widgets import (
    ScrollSafeComboBox, SettingsCard,
)
from app.ui.components.settings.settings_styles import card_style
from app.ui.pages.console_page import UIHelper


class SettingsApiFallbackSection(QFrame):
    config_changed = Signal(dict)
    section_id = "api_fallback"
    section_title = "Fallback"

    def __init__(self, api_config=None, parent=None):
        super().__init__(parent)
        self.api_mode_config = api_config or APIModeConfigManager.load()
        self._build_ui()
        self._reload_chain_list()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)

        title = QLabel("Fallback Chains")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        subtitle = QLabel("按顺序排列的 Profile 列表，调用失败时自动尝试下一个")
        subtitle.setObjectName("sectionSubtitle")
        root.addWidget(subtitle)

        card = SettingsCard("Chain 管理")
        self._card = card

        chain_list_row = QHBoxLayout()
        self.api_chain_list = QListWidget()
        self.api_chain_list.setFixedHeight(160)
        self.api_chain_list.currentItemChanged.connect(self._on_chain_selected)
        chain_list_row.addWidget(self.api_chain_list, 1)

        chain_ops = QVBoxLayout()
        self.api_chain_add_btn = QPushButton("新建")
        self.api_chain_add_btn.clicked.connect(self._create_chain)
        self.api_chain_rename_btn = QPushButton("重命名")
        self.api_chain_rename_btn.clicked.connect(self._rename_chain)
        self.api_chain_delete_btn = QPushButton("删除")
        self.api_chain_delete_btn.clicked.connect(self._delete_chain)
        chain_ops.addWidget(self.api_chain_add_btn)
        chain_ops.addWidget(self.api_chain_rename_btn)
        chain_ops.addWidget(self.api_chain_delete_btn)
        chain_ops.addStretch()
        chain_list_row.addLayout(chain_ops)
        card.add_layout(chain_list_row)

        card2 = SettingsCard("Chain 详情")
        self._card2 = card2

        profile_add_row = QHBoxLayout()
        self.api_chain_profile_combo = ScrollSafeComboBox()
        self.api_chain_profile_add_btn = QPushButton("添加 Profile")
        self.api_chain_profile_add_btn.clicked.connect(self._add_profile_to_chain)
        profile_add_row.addWidget(self.api_chain_profile_combo, 1)
        profile_add_row.addWidget(self.api_chain_profile_add_btn)
        card2.add_layout(profile_add_row)

        profile_list_row = QHBoxLayout()
        self.api_chain_profile_list = QListWidget()
        self.api_chain_profile_list.setFixedHeight(120)
        profile_list_row.addWidget(self.api_chain_profile_list, 1)

        profile_ops = QVBoxLayout()
        self.api_chain_profile_up_btn = QPushButton("上移")
        self.api_chain_profile_up_btn.clicked.connect(self._move_chain_profile_up)
        self.api_chain_profile_down_btn = QPushButton("下移")
        self.api_chain_profile_down_btn.clicked.connect(self._move_chain_profile_down)
        self.api_chain_profile_remove_btn = QPushButton("移除")
        self.api_chain_profile_remove_btn.clicked.connect(self._remove_profile_from_chain)
        profile_ops.addWidget(self.api_chain_profile_up_btn)
        profile_ops.addWidget(self.api_chain_profile_down_btn)
        profile_ops.addWidget(self.api_chain_profile_remove_btn)
        profile_ops.addStretch()
        profile_list_row.addLayout(profile_ops)
        card2.add_layout(profile_list_row)

        root.addWidget(card)
        root.addWidget(card2)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.api_fallback_reload_btn = QPushButton("重载")
        self.api_fallback_reload_btn.clicked.connect(self._reload_fallback_chains)
        btn_row.addWidget(self.api_fallback_reload_btn)
        root.addLayout(btn_row)

        root.addStretch()

    def load_from_config(self, config, api_config=None):
        if api_config:
            self.api_mode_config = api_config
        self._reload_chain_list()

    def collect_config(self):
        return {}

    def _on_chain_selected(self, current, previous):
        if not current:
            self.api_chain_profile_list.clear()
            return
        chain_name = current.text()
        chain_profiles = self.api_mode_config.get("fallback_chains", {}).get(chain_name, [])
        self.api_chain_profile_list.clear()
        for profile_ref in chain_profiles:
            self.api_chain_profile_list.addItem(profile_ref)
        self._reload_chain_profile_candidates()

    def _reload_chain_profile_candidates(self):
        self.api_chain_profile_combo.clear()
        for profile_key, profile_data in self.api_mode_config.get("profiles", {}).items():
            profile_name = profile_data.get("name", profile_key)
            self.api_chain_profile_combo.addItem(f"{profile_name}", profile_key)

    def _reload_chain_list(self):
        self.api_chain_list.clear()
        for chain_name in self.api_mode_config.get("fallback_chains", {}).keys():
            self.api_chain_list.addItem(chain_name)

    def _create_chain(self):
        name, ok = QInputDialog.getText(self, "新建 Chain", "请输入 Chain 名称:")
        if ok and name:
            try:
                APIModeConfigManager.create_fallback_chain(name, [])
                self.api_mode_config = APIModeConfigManager.load()
                self._reload_chain_list()
            except ValueError as e:
                UIHelper.warning(self, "错误", str(e))

    def _rename_chain(self):
        current_item = self.api_chain_list.currentItem()
        if not current_item:
            return
        old_name = current_item.text()
        new_name, ok = QInputDialog.getText(self, "重命名 Chain", "新名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            try:
                APIModeConfigManager.rename_fallback_chain(old_name, new_name)
                self.api_mode_config = APIModeConfigManager.load()
                self._reload_chain_list()
            except ValueError as e:
                UIHelper.warning(self, "错误", str(e))

    def _delete_chain(self):
        current_item = self.api_chain_list.currentItem()
        if not current_item:
            return
        chain_name = current_item.text()
        reply = QMessageBox.question(self, "确认删除", f"确定要删除 Chain '{chain_name}' 吗？")
        if reply == QMessageBox.Yes:
            APIModeConfigManager.delete_fallback_chain(chain_name)
            self.api_mode_config = APIModeConfigManager.load()
            self._reload_chain_list()

    def _add_profile_to_chain(self):
        current_chain = self.api_chain_list.currentItem()
        if not current_chain:
            UIHelper.warning(self, "提示", "请先选择一个 Chain")
            return
        chain_name = current_chain.text()
        profile_ref = self.api_chain_profile_combo.currentData()
        if not profile_ref:
            return
        chain_profiles = list(self.api_mode_config.get("fallback_chains", {}).get(chain_name, []))
        if profile_ref in chain_profiles:
            UIHelper.warning(self, "提示", "该 Profile 已在 Chain 中")
            return
        chain_profiles.append(profile_ref)
        APIModeConfigManager.update_fallback_chain(chain_name, chain_profiles)
        self.api_mode_config = APIModeConfigManager.load()
        self._on_chain_selected(current_chain, None)

    def _remove_profile_from_chain(self):
        current_chain = self.api_chain_list.currentItem()
        current_profile = self.api_chain_profile_list.currentItem()
        if not current_chain or not current_profile:
            return
        chain_name = current_chain.text()
        profile_ref = current_profile.text()
        chain_profiles = list(self.api_mode_config.get("fallback_chains", {}).get(chain_name, []))
        if profile_ref in chain_profiles:
            chain_profiles.remove(profile_ref)
            APIModeConfigManager.update_fallback_chain(chain_name, chain_profiles)
            self.api_mode_config = APIModeConfigManager.load()
            self._on_chain_selected(current_chain, None)

    def _move_chain_profile_up(self):
        current_chain = self.api_chain_list.currentItem()
        current_row = self.api_chain_profile_list.currentRow()
        if not current_chain or current_row <= 0:
            return
        chain_name = current_chain.text()
        chain_profiles = list(self.api_mode_config.get("fallback_chains", {}).get(chain_name, []))
        chain_profiles[current_row], chain_profiles[current_row - 1] = chain_profiles[current_row - 1], chain_profiles[current_row]
        APIModeConfigManager.update_fallback_chain(chain_name, chain_profiles)
        self.api_mode_config = APIModeConfigManager.load()
        self._on_chain_selected(current_chain, None)
        self.api_chain_profile_list.setCurrentRow(current_row - 1)

    def _move_chain_profile_down(self):
        current_chain = self.api_chain_list.currentItem()
        current_row = self.api_chain_profile_list.currentRow()
        if not current_chain or current_row < 0:
            return
        chain_name = current_chain.text()
        chain_profiles = list(self.api_mode_config.get("fallback_chains", {}).get(chain_name, []))
        if current_row >= len(chain_profiles) - 1:
            return
        chain_profiles[current_row], chain_profiles[current_row + 1] = chain_profiles[current_row + 1], chain_profiles[current_row]
        APIModeConfigManager.update_fallback_chain(chain_name, chain_profiles)
        self.api_mode_config = APIModeConfigManager.load()
        self._on_chain_selected(current_chain, None)
        self.api_chain_profile_list.setCurrentRow(current_row + 1)

    def _reload_fallback_chains(self):
        self.api_mode_config = APIModeConfigManager.load()
        self._reload_chain_list()
        UIHelper.info(self, "已重载", "Fallback Chains 配置已从文件重新加载。")

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

        self.api_chain_profile_combo.setStyleSheet(Theme.combo_box())

        btn_ss = f"background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 6px; padding: 5px 12px;"
        for btn in [self.api_chain_add_btn, self.api_chain_rename_btn, self.api_chain_delete_btn,
                     self.api_chain_profile_add_btn, self.api_chain_profile_up_btn,
                     self.api_chain_profile_down_btn, self.api_chain_profile_remove_btn,
                     self.api_fallback_reload_btn]:
            btn.setStyleSheet(btn_ss)
