import os
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Signal

from app.core.app_constants import CHROME_PORT
from app.core.config import ConfigManager
from app.ui.theme import Theme, theme_manager, get_available_themes, THEME_DIR
from app.ui.components.theme_editor import ThemeEditorDialog
from app.ui.components.settings.settings_widgets import (
    ScrollSafeComboBox, ScrollSafeSpinBox, SettingsCard, SettingsField,
    SettingsToggleRow, SettingsFieldRow,
)
from app.ui.components.settings.settings_styles import card_style, field_style, toggle_row_style


class SettingsBasicSection(QFrame):
    config_changed = Signal(dict)
    section_id = "basic"
    section_title = "基础配置"

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._build_ui()
        self.load_from_config(self.config)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)

        title = QLabel("基础配置")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        subtitle = QLabel("主题、路径、端口与自动化偏好")
        subtitle.setObjectName("sectionSubtitle")
        root.addWidget(subtitle)

        card = SettingsCard("界面与路径")
        self._card = card

        self.theme_combo = ScrollSafeComboBox()
        self._refresh_themes()
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        card.add_field(SettingsField("界面主题", self.theme_combo))

        theme_btn_row = QHBoxLayout()
        theme_btn_row.setSpacing(8)
        self.theme_edit_btn = QPushButton("创建主题")
        self.theme_edit_btn.clicked.connect(self._open_theme_editor)
        self.theme_del_btn = QPushButton("删除")
        self.theme_del_btn.setFixedWidth(60)
        self.theme_del_btn.clicked.connect(self._delete_current_theme)
        theme_btn_row.addWidget(self.theme_edit_btn)
        theme_btn_row.addWidget(self.theme_del_btn)
        theme_btn_row.addStretch()
        card.add_layout(theme_btn_row)

        self.code_path_edit = QLineEdit()
        self.code_browse_btn = QPushButton("浏览")
        self.code_browse_btn.setFixedWidth(60)
        self.code_browse_btn.clicked.connect(lambda: self._browse_folder(self.code_path_edit))
        code_row = SettingsFieldRow("脚本暂存区", self.code_path_edit, self.code_browse_btn)
        card.add_field(code_row)

        self.img_path_edit = QLineEdit()
        self.img_browse_btn = QPushButton("浏览")
        self.img_browse_btn.setFixedWidth(60)
        self.img_browse_btn.clicked.connect(lambda: self._browse_folder(self.img_path_edit))
        img_row = SettingsFieldRow("图片导出路径", self.img_path_edit, self.code_browse_btn)
        card.add_field(img_row)

        root.addWidget(card)

        card2 = SettingsCard("端口与自动化")
        self._card2 = card2

        self.port_edit = QLineEdit()
        card2.add_field(SettingsField("Chrome 端口", self.port_edit))

        self.fix_limit_spin = ScrollSafeSpinBox()
        self.fix_limit_spin.setRange(1, 100)
        card2.add_field(SettingsField("修复回溯 (条)", self.fix_limit_spin))

        self.auto_export_toggle = SettingsToggleRow(
            "启用自动导出", "自动将代码和图片导出到指定路径", False
        )
        card2.add_widget(self.auto_export_toggle)

        root.addWidget(card2)

        card3 = SettingsCard("消息加载")
        self._card3 = card3

        self.chat_load_turns_spin = ScrollSafeSpinBox()
        self.chat_load_turns_spin.setRange(1, 500)
        card3.add_field(SettingsField("默认消息加载轮数", self.chat_load_turns_spin))

        self.chat_load_step_turns_spin = ScrollSafeSpinBox()
        self.chat_load_step_turns_spin.setRange(1, 200)
        card3.add_field(SettingsField("加载更多步长 (轮)", self.chat_load_step_turns_spin))

        root.addWidget(card3)
        root.addStretch()

    def _refresh_themes(self):
        current = self.theme_combo.currentText()
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        themes = get_available_themes()
        for t in themes:
            self.theme_combo.addItem(t)
        idx = self.theme_combo.findText(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        elif self.theme_combo.count() > 0:
            self.theme_combo.setCurrentIndex(0)
        self.theme_combo.blockSignals(False)

    def _on_theme_changed(self, theme_name):
        if not theme_name:
            return
        self.config["theme"] = theme_name
        self.config_changed.emit({"action": "theme_preview", "theme": theme_name})

    def _open_theme_editor(self):
        dlg = ThemeEditorDialog(self)
        if dlg.exec() == 1:
            self._refresh_themes()

    def _delete_current_theme(self):
        theme_name = self.theme_combo.currentText()
        if not theme_name:
            return
        built_in = ["Dark", "Light"]
        if theme_name in built_in:
            QMessageBox.warning(self, "无法删除", f"'{theme_name}' 是内置主题，不可删除。")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除主题 '{theme_name}' 吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        theme_file = os.path.join(THEME_DIR, f"{theme_name}.json")
        if os.path.exists(theme_file):
            os.remove(theme_file)
            self._refresh_themes()
            self.config_changed.emit({"action": "theme_deleted"})
        else:
            QMessageBox.warning(self, "未找到", f"主题文件不存在: {theme_file}")

    def _browse_folder(self, line_edit):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹", line_edit.text())
        if folder:
            line_edit.setText(folder)

    def load_from_config(self, config):
        self.config = config or {}
        self.port_edit.setText(str(self.config.get("chrome_port", CHROME_PORT)))
        self.fix_limit_spin.setValue(self.config.get("fix_limit", 5))
        self.auto_export_toggle.setChecked(self.config.get("auto_export", True))
        self.code_path_edit.setText(self.config.get("export_code_path", ""))
        self.img_path_edit.setText(self.config.get("export_image_path", ""))
        self.chat_load_turns_spin.setValue(int(self.config.get("chat_message_load_turns", 20)))
        self.chat_load_step_turns_spin.setValue(int(self.config.get("chat_message_load_step_turns", 10)))

        theme_name = self.config.get("theme", "Dark")
        idx = self.theme_combo.findText(theme_name)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

    def collect_config(self):
        return {
            "chrome_port": int(self.port_edit.text()),
            "fix_limit": self.fix_limit_spin.value(),
            "auto_export": self.auto_export_toggle.isChecked(),
            "export_code_path": self.code_path_edit.text(),
            "export_image_path": self.img_path_edit.text(),
            "chat_message_load_turns": self.chat_load_turns_spin.value(),
            "chat_message_load_step_turns": self.chat_load_step_turns_spin.value(),
        }

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")

        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "sectionTitle":
                lbl.setStyleSheet(Theme.section_title())
            elif lbl.objectName() == "sectionSubtitle":
                lbl.setStyleSheet(Theme.section_subtitle())

        for card in [self._card, self._card2, self._card3]:
            card.setStyleSheet(card_style())

        input_ss = Theme.input_field()
        for w in [self.code_path_edit, self.img_path_edit, self.port_edit,
                   self.fix_limit_spin, self.chat_load_turns_spin, self.chat_load_step_turns_spin]:
            w.setStyleSheet(input_ss)

        self.theme_combo.setStyleSheet(Theme.combo_box())

        btn_ss = f"background-color: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; border-radius: 6px; padding: 5px 12px;"
        for btn in [self.theme_edit_btn, self.theme_del_btn, self.code_browse_btn, self.img_browse_btn]:
            btn.setStyleSheet(btn_ss)

        self.auto_export_toggle.setStyleSheet(toggle_row_style())
