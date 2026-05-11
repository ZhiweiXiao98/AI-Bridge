from PySide6.QtWidgets import (
    QComboBox, QSpinBox, QFrame, QLabel,
    QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy,
    QScrollArea, QPushButton,
)
from PySide6.QtCore import Qt, Signal, QEvent, QObject
from PySide6.QtGui import QPainter, QColor, QBrush


class ScrollSafeComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class ScrollSafeSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class ScrollSafeFilter(QObject):
    def __init__(self, parent_widget, parent=None):
        super().__init__(parent)
        self._parent = parent_widget

    def install(self):
        self._parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            if isinstance(obj, (QComboBox, QSpinBox)):
                event.ignore()
                return True
        return False


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        if self._checked != checked:
            self._checked = checked
            self.toggled.emit(checked)
            self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.toggled.emit(self._checked)
        self.update()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        from app.ui.theme import theme_manager
        p = theme_manager.get_palette()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_radius = 10
        thumb_radius = 8
        track_rect = self.rect().adjusted(2, 2, -2, -2)

        if self._checked:
            track_color = QColor(p.ACCENT_PRIMARY)
        else:
            track_color = QColor(p.BORDER)

        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(track_rect, track_radius, track_radius)

        if self._checked:
            thumb_x = self.width() - thumb_radius - 4
        else:
            thumb_x = thumb_radius + 4
        thumb_y = self.height() // 2

        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(thumb_x - thumb_radius, thumb_y - thumb_radius,
                            thumb_radius * 2, thumb_radius * 2)
        painter.end()


class SettingsField(QFrame):
    def __init__(self, label_text, widget, description=None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsField")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("settingsFieldLabel")
        layout.addWidget(label)

        if description:
            desc = QLabel(description)
            desc.setObjectName("settingsFieldDesc")
            desc.setWordWrap(True)
            layout.addWidget(desc)

        layout.addWidget(widget)


class SettingsCard(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setSpacing(16)

        if title:
            title_lbl = QLabel(title)
            title_lbl.setObjectName("settingsCardTitle")
            self._layout.addWidget(title_lbl)

    def add_field(self, field):
        self._layout.addWidget(field)

    def add_widget(self, widget):
        self._layout.addWidget(widget)

    def add_layout(self, layout):
        self._layout.addLayout(layout)

    def add_stretch(self):
        self._layout.addStretch()


class SettingsToggleRow(QFrame):
    toggled = Signal(bool)

    def __init__(self, title, description=None, checked=False, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsToggleRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("settingsToggleTitle")
        text_wrap.addWidget(title_lbl)

        if description:
            desc_lbl = QLabel(description)
            desc_lbl.setObjectName("settingsToggleDesc")
            desc_lbl.setWordWrap(True)
            text_wrap.addWidget(desc_lbl)

        layout.addLayout(text_wrap, 1)

        self.switch = ToggleSwitch(checked=checked)
        self.switch.toggled.connect(self.toggled.emit)
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def isChecked(self):
        return self.switch.isChecked()

    def setChecked(self, checked):
        self.switch.setChecked(checked)


class SettingsFieldRow(QFrame):
    def __init__(self, label_text, widget, side_widget=None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsFieldRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel(label_text)
        label.setObjectName("settingsFieldLabel")
        label.setFixedWidth(140)
        layout.addWidget(label)

        layout.addWidget(widget, 1)

        if side_widget:
            layout.addWidget(side_widget)


class CollapsiblePanel(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("collapsiblePanel")
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QPushButton(f"▶ {title}")
        self._header.setObjectName("collapsibleHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle)
        outer.addWidget(self._header)

        self._content = QFrame()
        self._content.setObjectName("collapsibleContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 8, 16, 12)
        self._content_layout.setSpacing(6)
        self._content.setVisible(False)
        outer.addWidget(self._content)

    def add_widget(self, widget):
        self._content_layout.addWidget(widget)

    def add_layout(self, layout):
        self._content_layout.addLayout(layout)

    def _toggle(self):
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        title_text = self._header.text()[2:]
        arrow = "▼" if self._expanded else "▶"
        self._header.setText(f"{arrow} {title_text}")

    def set_title(self, title):
        arrow = "▼" if self._expanded else "▶"
        self._header.setText(f"{arrow} {title}")

    def refresh_style(self):
        from app.ui.theme import theme_manager
        p = theme_manager.get_palette()
        self._header.setStyleSheet(
            f"QPushButton#collapsibleHeader {{"
            f"  background-color: {p.BG_TERTIARY};"
            f"  color: {p.TEXT_PRIMARY};"
            f"  border: 1px solid {p.BORDER};"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  text-align: left;"
            f"  font-weight: 600;"
            f"  font-size: 12px;"
            f"}}"
            f"QPushButton#collapsibleHeader:hover {{"
            f"  background-color: {p.BORDER};"
            f"}}"
        )
        self._content.setStyleSheet(
            f"QFrame#collapsibleContent {{"
            f"  background-color: {p.BG_TERTIARY};"
            f"  border: 1px solid {p.BORDER};"
            f"  border-top: none;"
            f"  border-radius: 0 0 8px 8px;"
            f"}}"
        )
