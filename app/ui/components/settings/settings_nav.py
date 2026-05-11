from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QVBoxLayout, QLabel
from PySide6.QtCore import Signal


class SettingsNav(QFrame):
    nav_changed = Signal(int)

    def __init__(self, sections, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsNavBar")
        self.setFixedWidth(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 16)
        layout.setSpacing(0)

        title = QLabel("设置")
        title.setObjectName("settingsNavTitle")
        title.setStyleSheet("font-size: 16px; font-weight: 700; padding: 8px 16px 16px 16px; border: none; background: transparent;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("settingsNavList")
        self.list_widget.currentRowChanged.connect(self._on_row_changed)

        for i, section_info in enumerate(sections):
            item = QListWidgetItem(section_info.get("title", f"Section {i}"))
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

    def _on_row_changed(self, row):
        self.nav_changed.emit(row)

    def set_current(self, index):
        self.list_widget.setCurrentRow(index)

    def apply_theme(self):
        from app.ui.components.settings.settings_styles import nav_bar_style
        p = self._get_palette()
        self.setStyleSheet(nav_bar_style())
        title = self.findChild(QLabel, "settingsNavTitle")
        if title:
            title.setStyleSheet(
                f"font-size: 16px; font-weight: 700; padding: 8px 16px 16px 16px; "
                f"border: none; background: transparent; color: {p.TEXT_PRIMARY};"
            )

    def _get_palette(self):
        from app.ui.theme import theme_manager
        return theme_manager.get_palette()
