import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QProgressBar, QSizePolicy, QToolButton,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont

from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager


class DocCard(QFrame):
    generate_requested = Signal(str)
    open_requested = Signal(str)

    def __init__(self, filename: str, status: str, last_generated: float = 0, parent=None):
        super().__init__(parent)
        self.filename = filename
        self._status = status
        self._last_generated = last_generated
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("docCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()
        self.apply_theme()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.status_dot = QLabel("●")
        self.status_dot.setFixedWidth(14)
        self.status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.status_dot)

        self.name_label = QLabel(self.filename)
        name_font = QFont()
        name_font.setPixelSize(13)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_row.addWidget(self.name_label)

        self.status_badge = QLabel(self._status_text())
        self.status_badge.setObjectName("statusBadge")
        badge_font = QFont()
        badge_font.setPixelSize(10)
        self.status_badge.setFont(badge_font)
        self.status_badge.setFixedHeight(20)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setStyleSheet("padding: 2px 8px; border-radius: 10px;")
        top_row.addWidget(self.status_badge)

        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        self.time_label = QLabel(self._time_text())
        time_font = QFont()
        time_font.setPixelSize(10)
        self.time_label.setFont(time_font)
        self.time_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bottom_row.addWidget(self.time_label)

        self.gen_btn = QToolButton()
        self.gen_btn.setText("⟳" if self._status == "outdated" else "▶")
        self.gen_btn.setFixedSize(26, 26)
        self.gen_btn.setToolTip("生成 HTML")
        self.gen_btn.clicked.connect(lambda: self.generate_requested.emit(self.filename))
        bottom_row.addWidget(self.gen_btn)

        if self._status in ("up_to_date", "outdated"):
            self.open_btn = QToolButton()
            self.open_btn.setText("↗")
            self.open_btn.setFixedSize(26, 26)
            self.open_btn.setToolTip("打开 HTML")
            self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.filename))
            bottom_row.addWidget(self.open_btn)

        layout.addLayout(bottom_row)

    def update_status(self, status: str, last_generated: float = 0):
        self._status = status
        self._last_generated = last_generated
        self.status_badge.setText(self._status_text())
        self.time_label.setText(self._time_text())
        self.gen_btn.setText("⟳" if status == "outdated" else "▶")
        self.apply_theme()

    def _status_text(self) -> str:
        return {"up_to_date": "已生成", "outdated": "需更新", "missing": "未生成"}.get(self._status, "未知")

    def _time_text(self) -> str:
        if not self._last_generated:
            return ""
        diff = time.time() - self._last_generated
        if diff < 60:
            return "刚刚生成"
        elif diff < 3600:
            return f"{int(diff / 60)} 分钟前生成"
        elif diff < 86400:
            return f"{int(diff / 3600)} 小时前生成"
        else:
            return f"{int(diff / 86400)} 天前生成"

    def apply_theme(self):
        p = theme_manager.get_palette()
        status_colors = {
            "up_to_date": p.TEXT_SUCCESS,
            "outdated": p.BTN_WARNING,
            "missing": p.TEXT_SECONDARY,
        }
        badge_bgs = {
            "up_to_date": f"rgba(16,185,129,0.15)",
            "outdated": f"rgba(245,158,11,0.15)",
            "missing": f"rgba(156,163,175,0.15)",
        }
        color = status_colors.get(self._status, p.TEXT_SECONDARY)
        badge_bg = badge_bgs.get(self._status, p.BG_TERTIARY)

        self.setStyleSheet(f"""
            QFrame#docCard {{
                background-color: {p.BG_SECONDARY};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                border-left: 3px solid {color};
            }}
            QFrame#docCard:hover {{
                border-color: {p.ACCENT_PRIMARY};
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            QLabel#statusBadge {{
                background-color: {badge_bg};
                color: {color};
            }}
            QToolButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_SECONDARY};
                border: none;
                border-radius: 13px;
                font-size: 14px;
            }}
            QToolButton:hover {{
                background-color: {p.ACCENT_PRIMARY};
                color: white;
            }}
        """)
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 10px; background: transparent; border: none;")
        self.name_label.setStyleSheet(f"color: {p.TEXT_PRIMARY}; background: transparent; border: none;")
        self.time_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; background: transparent; border: none;")


class DocOrganizerPanel(DockablePanel):
    generate_requested = Signal(str)
    generate_all_requested = Signal()
    open_html_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self):
        self.total_label = None
        self.up_to_date_label = None
        self.outdated_label = None
        self.missing_label = None
        self.refresh_btn = None
        self.generate_all_btn = None
        self.progress_bar = None
        super().__init__("doc_organizer", "资料整理", "📚")
        self._cards: dict[str, DocCard] = {}
        self.init_content()
        self.apply_theme()

    def create_content(self):
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)

        self.total_label = QLabel("📄 0 篇")
        self.total_label.setObjectName("summaryLabel")
        self.up_to_date_label = QLabel("✅ 0 已生成")
        self.up_to_date_label.setObjectName("summaryLabel")
        self.outdated_label = QLabel("⚠️ 0 需更新")
        self.outdated_label.setObjectName("summaryLabel")
        self.missing_label = QLabel("○ 0 未生成")
        self.missing_label.setObjectName("summaryLabel")

        for lbl in (self.total_label, self.up_to_date_label, self.outdated_label, self.missing_label):
            summary_row.addWidget(lbl)
        summary_row.addStretch()
        main_layout.addLayout(summary_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.setObjectName("actionBtn")
        self.refresh_btn.setFixedHeight(28)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        action_row.addWidget(self.refresh_btn)

        self.generate_all_btn = QPushButton("⚡ 全部生成")
        self.generate_all_btn.setObjectName("actionBtn")
        self.generate_all_btn.setFixedHeight(28)
        self.generate_all_btn.clicked.connect(self.generate_all_requested.emit)
        action_row.addWidget(self.generate_all_btn)

        action_row.addStretch()
        main_layout.addLayout(action_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch()

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll, stretch=1)

        return widget

    def update_doc_list(self, statuses: list):
        for card in self._cards.values():
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        for i in range(self.cards_layout.count()):
            item = self.cards_layout.itemAt(i)
            if item and item.widget() and item.widget() is not self.cards_layout:
                item.widget().setParent(None)

        for status in statuses:
            card = DocCard(
                filename=status.filename,
                status=status.status,
                last_generated=status.last_generated,
            )
            card.generate_requested.connect(self.generate_requested.emit)
            card.open_requested.connect(self.open_html_requested.emit)
            self._cards[status.filename] = card
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        summary = {"total": 0, "up_to_date": 0, "outdated": 0, "missing": 0}
        for s in statuses:
            summary["total"] += 1
            if s.status in summary:
                summary[s.status] += 1

        self.total_label.setText(f"📄 {summary['total']} 篇")
        self.up_to_date_label.setText(f"✅ {summary['up_to_date']} 已生成")
        self.outdated_label.setText(f"⚠️ {summary['outdated']} 需更新")
        self.missing_label.setText(f"○ {summary['missing']} 未生成")

    def update_card_status(self, filename: str, status: str, last_generated: float = 0):
        card = self._cards.get(filename)
        if card:
            card.update_status(status, last_generated)

    def show_progress(self, current: int, total: int):
        self.progress_bar.show()
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def hide_progress(self):
        self.progress_bar.hide()

    def apply_theme(self):
        super().apply_theme()
        if not hasattr(self, 'total_label'):
            return
        p = theme_manager.get_palette()
        summary_style = f"color: {p.TEXT_SECONDARY}; font-size: 11px; background: transparent; border: none;"
        for lbl in (self.total_label, self.up_to_date_label, self.outdated_label, self.missing_label):
            if lbl:
                lbl.setStyleSheet(summary_style)

        btn_style = f"""
            QPushButton#actionBtn {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
            }}
            QPushButton#actionBtn:hover {{
                background-color: {p.ACCENT_PRIMARY};
                border-color: {p.ACCENT_PRIMARY};
                color: white;
            }}
        """
        for btn in (self.refresh_btn, self.generate_all_btn):
            if btn:
                btn.setStyleSheet(btn_style)

        if self.progress_bar:
            self.progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {p.BG_TERTIARY};
                    border: none;
                    border-radius: 2px;
                }}
                QProgressBar::chunk {{
                    background-color: {p.ACCENT_PRIMARY};
                    border-radius: 2px;
                }}
            """)

        if self.widget():
            scroll = self.widget().findChild(QScrollArea)
            if scroll:
                scroll.setStyleSheet(f"""
                    QScrollArea {{
                        background: transparent;
                        border: none;
                    }}
                    QScrollBar:vertical {{
                        background: {p.BG_PRIMARY};
                        width: 6px;
                        border-radius: 3px;
                    }}
                    QScrollBar::handle:vertical {{
                        background: {p.BG_TERTIARY};
                        border-radius: 3px;
                        min-height: 30px;
                    }}
                    QScrollBar::handle:vertical:hover {{
                        background: {p.ACCENT_PRIMARY};
                    }}
                """)
