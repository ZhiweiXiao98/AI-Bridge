from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PySide6.QtCore import Signal

from app.ui.theme import Theme, theme_manager
from app.ui.components.settings.settings_widgets import SettingsCard
from app.ui.components.settings.settings_styles import card_style


class SettingsBlacklistSection(QFrame):
    config_changed = Signal(dict)
    section_id = "blacklist"
    section_title = "黑名单"

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._build_ui()
        self.load_from_config(self.config)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)

        title = QLabel("黑名单管理")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        subtitle = QLabel("被忽略的文件列表，这些文件不会参与知识库索引")
        subtitle.setObjectName("sectionSubtitle")
        root.addWidget(subtitle)

        card = SettingsCard("忽略文件")
        self._card = card

        from PySide6.QtWidgets import QPlainTextEdit
        self.ignore_edit = QPlainTextEdit()
        self.ignore_edit.setPlaceholderText("每行一个文件路径或模式...")
        self.ignore_edit.setMinimumHeight(120)
        card.add_widget(self.ignore_edit)

        root.addWidget(card)
        root.addStretch()

    def load_from_config(self, config, api_config=None):
        self.config = config or {}
        self.ignore_edit.setPlainText(self.config.get("ignored_files", ""))

    def collect_config(self):
        return {
            "ignored_files": self.ignore_edit.toPlainText().strip(),
        }

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")

        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "sectionTitle":
                lbl.setStyleSheet(Theme.section_title())
            elif lbl.objectName() == "sectionSubtitle":
                lbl.setStyleSheet(Theme.section_subtitle())

        self._card.setStyleSheet(card_style())
        self.ignore_edit.setStyleSheet(Theme.log_editor())
