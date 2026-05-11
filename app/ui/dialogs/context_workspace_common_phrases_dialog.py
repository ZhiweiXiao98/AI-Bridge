# filename: export/code/app/ui/dialogs/context_workspace_common_phrases_dialog.py
import json
import os
from typing import List, Optional
from app.core.app_constants import APP_ROOT

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QMessageBox,
    QScrollArea,
    QFrame,
)

from app.ui.components.animated_reorder_container import AnimatedReorderContainer
from app.ui.theme import theme_manager


class _PhraseListItem(QFrame):
    clicked = Signal(str)

    def __init__(self, phrase_id: str, title: str, parent=None):
        super().__init__(parent)
        self.phrase_id = phrase_id
        self.setObjectName("CommonPhraseItem")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.drag_lbl = QLabel("⋮⋮")
        self.drag_lbl.setObjectName("CommonPhraseDragHandle")
        self.drag_lbl.setFixedWidth(18)
        self.drag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("CommonPhraseTitle")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self.order_badge = QLabel("")
        self.order_badge.setObjectName("CommonPhraseOrderBadge")
        self.order_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.order_badge.setFixedSize(24, 24)
        self.order_badge.hide()

        layout.addWidget(self.drag_lbl)
        layout.addWidget(self.title_lbl, 1)
        layout.addWidget(self.order_badge)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.phrase_id)
        super().mousePressEvent(event)

    def set_title(self, title: str):
        self.title_lbl.setText(title)

    def set_selected_order(self, order: Optional[int]):
        selected = order is not None
        self.setProperty("selected", selected)
        if selected:
            self.order_badge.setText(str(order))
            self.order_badge.show()
        else:
            self.order_badge.clear()
            self.order_badge.hide()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class ContextWorkspaceCommonPhrasesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("常用语")
        self.resize(820, 560)

        self._phrases = []
        self._selected_payload = None
        self._selected_ids_in_order: List[str] = []
        self._current_phrase_id: Optional[str] = None
        self._suppress_editor_updates = False

        self._build_ui()
        self._load_phrases()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hint = QLabel("维护常用提示语；左侧支持拖拽排序与有序多选，发送时按选择顺序进入提示词暂存区。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(10)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        left_hint = QLabel("左侧仅显示标题；数字徽标表示多选顺序。")
        left_hint.setObjectName("CommonPhraseSubHint")
        left_hint.setWordWrap(True)
        left_col.addWidget(left_hint)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_scroll.setObjectName("CommonPhraseScroll")

        self.list_container = AnimatedReorderContainer()
        self.list_container.setObjectName("CommonPhraseListContainer")
        self.list_container.set_spacing(6)
        self.list_container.set_scroll_host(self.list_scroll)
        self.list_container.order_changed.connect(self._on_order_changed)
        self.list_scroll.setWidget(self.list_container)
        left_col.addWidget(self.list_scroll, 1)

        list_actions = QHBoxLayout()
        self.add_btn = QPushButton("新增")
        self.delete_btn = QPushButton("删除所选")
        self.add_btn.clicked.connect(self._add_phrase)
        self.delete_btn.clicked.connect(self._delete_selected_phrases)
        list_actions.addWidget(self.add_btn)
        list_actions.addWidget(self.delete_btn)
        list_actions.addStretch()
        left_col.addLayout(list_actions)

        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addWidget(QLabel("标题"))

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("例如：继续实现 / 先分析再修改")
        self.title_edit.textChanged.connect(self._update_current_phrase)
        right_col.addWidget(self.title_edit)

        right_col.addWidget(QLabel("内容"))
        self.content_edit = QPlainTextEdit()
        self.content_edit.setPlaceholderText("输入要放入提示词暂存区的常用语内容...")
        self.content_edit.textChanged.connect(self._update_current_phrase)
        right_col.addWidget(self.content_edit, 1)

        body.addLayout(left_col, 2)
        body.addLayout(right_col, 3)
        layout.addLayout(body, 1)

        footer = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.insert_btn = QPushButton("发送所选到暂存区")
        self.close_btn = QPushButton("关闭")
        self.save_btn.clicked.connect(self._save_phrases)
        self.insert_btn.clicked.connect(self._accept_insert)
        self.close_btn.clicked.connect(self.reject)
        footer.addStretch()
        footer.addWidget(self.save_btn)
        footer.addWidget(self.insert_btn)
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)

    def _config_path(self):
        return os.path.join(APP_ROOT, ".config", "context_workspace_common_phrases.json")

    def _default_phrases(self):
        return [
            {
                "id": "phrase_continue_impl",
                "title": "继续实现",
                "content": "请基于当前上下文继续实现，不要重复已完成部分；先检查现状，再继续修改。",
            },
            {
                "id": "phrase_analyze_first",
                "title": "先分析再修改",
                "content": "请先阅读相关代码并分析现状，列出修改点与风险，再开始实施。",
            },
        ]

    def _make_phrase_id(self):
        existing = {str(item.get("id", "") or "") for item in self._phrases if isinstance(item, dict)}
        index = len(existing) + 1
        while True:
            candidate = f"phrase_{index}"
            if candidate not in existing:
                return candidate
            index += 1

    def _normalize_phrase(self, item):
        if not isinstance(item, dict):
            return None
        phrase_id = str(item.get("id", "") or "").strip() or self._make_phrase_id()
        title = str(item.get("title", "") or "").strip() or "未命名常用语"
        content = str(item.get("content", "") or "").strip()
        return {"id": phrase_id, "title": title, "content": content}

    def _load_phrases(self):
        path = self._config_path()
        phrases = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                phrases = data.get("phrases", []) or []
            except Exception:
                phrases = []

        normalized = []
        for item in phrases:
            normalized_item = self._normalize_phrase(item)
            if normalized_item:
                normalized.append(normalized_item)

        self._phrases = normalized or self._default_phrases()
        self._selected_ids_in_order = []
        self._current_phrase_id = self._phrases[0]["id"] if self._phrases else None
        self._reload_list()
        self._load_current_phrase_to_editor()

    def _reload_list(self):
        current_id = self._current_phrase_id
        self.list_container.clear_items()

        for item in self._phrases:
            phrase_id = item["id"]
            title = str(item.get("title", "") or "").strip() or "未命名常用语"
            widget = _PhraseListItem(phrase_id, title)
            widget.clicked.connect(self._toggle_selection)
            self.list_container.add_item(phrase_id, widget, drag_handle=widget.drag_lbl)

        if current_id and any(x["id"] == current_id for x in self._phrases):
            self._current_phrase_id = current_id
        elif self._phrases:
            self._current_phrase_id = self._phrases[0]["id"]
        else:
            self._current_phrase_id = None

        self._refresh_selection_badges()

    def _widget_for_phrase(self, phrase_id):
        if not phrase_id:
            return None
        return self.list_container.widget_for_item(phrase_id)

    def _refresh_selection_badges(self):
        valid_ids = {item["id"] for item in self._phrases}
        self._selected_ids_in_order = [pid for pid in self._selected_ids_in_order if pid in valid_ids]

        if self._current_phrase_id not in valid_ids:
            self._current_phrase_id = self._phrases[0]["id"] if self._phrases else None

        for idx, pid in enumerate(self._selected_ids_in_order, start=1):
            widget = self._widget_for_phrase(pid)
            if widget:
                widget.set_selected_order(idx)

        for item in self._phrases:
            if item["id"] not in self._selected_ids_in_order:
                widget = self._widget_for_phrase(item["id"])
                if widget:
                    widget.set_selected_order(None)

    def _toggle_selection(self, phrase_id: str):
        if phrase_id in self._selected_ids_in_order:
            self._selected_ids_in_order = [pid for pid in self._selected_ids_in_order if pid != phrase_id]
        else:
            self._selected_ids_in_order.append(phrase_id)

        self._current_phrase_id = phrase_id
        self._refresh_selection_badges()
        self._load_current_phrase_to_editor()

    def _find_phrase(self, phrase_id):
        if not phrase_id:
            return None
        for item in self._phrases:
            if item.get("id") == phrase_id:
                return item
        return None

    def _load_current_phrase_to_editor(self):
        item = self._find_phrase(self._current_phrase_id)
        self._suppress_editor_updates = True
        try:
            if not item:
                self.title_edit.clear()
                self.content_edit.clear()
            else:
                self.title_edit.setText(str(item.get("title", "") or ""))
                self.content_edit.setPlainText(str(item.get("content", "") or ""))
        finally:
            self._suppress_editor_updates = False

    def _update_current_phrase(self):
        if self._suppress_editor_updates:
            return

        item = self._find_phrase(self._current_phrase_id)
        if not item:
            return

        item["title"] = self.title_edit.text().strip() or "未命名常用语"
        item["content"] = self.content_edit.toPlainText().strip()

        widget = self._widget_for_phrase(item["id"])
        if widget:
            widget.set_title(item["title"])

    def _add_phrase(self):
        phrase = {
            "id": self._make_phrase_id(),
            "title": "新常用语",
            "content": "",
        }
        self._phrases.append(phrase)
        self._current_phrase_id = phrase["id"]
        self._reload_list()
        self._load_current_phrase_to_editor()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _delete_selected_phrases(self):
        if not self._selected_ids_in_order:
            QMessageBox.information(self, "提示", "请先选择要删除的常用语。")
            return

        count = len(self._selected_ids_in_order)
        reply = QMessageBox.question(self, "删除常用语", f"确认删除选中的 {count} 条常用语吗？")
        if reply != QMessageBox.StandardButton.Yes:
            return

        selected = set(self._selected_ids_in_order)
        self._phrases = [item for item in self._phrases if item.get("id") not in selected]
        self._selected_ids_in_order = []
        self._current_phrase_id = self._phrases[0]["id"] if self._phrases else None
        self._reload_list()
        self._load_current_phrase_to_editor()

    def _selected_phrases_for_send(self):
        if not self._selected_ids_in_order:
            QMessageBox.information(self, "提示", "请先按顺序选择要发送的常用语。")
            return None

        payloads = []
        for phrase_id in self._selected_ids_in_order:
            item = self._find_phrase(phrase_id)
            if not item:
                continue

            title = str(item.get("title", "") or "").strip() or "未命名常用语"
            content = str(item.get("content", "") or "").strip()
            if not content:
                QMessageBox.warning(self, "内容为空", f"常用语“{title}”内容为空，无法发送。")
                return None

            payloads.append({
                "id": phrase_id,
                "title": title,
                "content": content,
            })

        if not payloads:
            QMessageBox.information(self, "提示", "当前没有可发送的常用语。")
            return None

        return payloads

    def _save_phrases(self):
        normalized = []
        for item in self._phrases:
            normalized_item = self._normalize_phrase(item)
            if not normalized_item:
                continue
            normalized.append(normalized_item)

        path = self._config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"phrases": normalized}, f, ensure_ascii=False, indent=2)

        self._phrases = normalized or self._default_phrases()
        self._refresh_after_data_change(keep_current=True)
        QMessageBox.information(self, "已保存", "常用语已保存。")

    def _refresh_after_data_change(self, keep_current=False):
        current_id = self._current_phrase_id if keep_current else None
        valid_ids = {item["id"] for item in self._phrases}
        self._selected_ids_in_order = [pid for pid in self._selected_ids_in_order if pid in valid_ids]

        if current_id in valid_ids:
            self._current_phrase_id = current_id
        else:
            self._current_phrase_id = self._phrases[0]["id"] if self._phrases else None

        self._reload_list()
        self._load_current_phrase_to_editor()

    def _on_order_changed(self, ordered_ids):
        ordered_ids = [str(x) for x in (ordered_ids or [])]
        item_map = {item["id"]: item for item in self._phrases}
        self._phrases = [item_map[pid] for pid in ordered_ids if pid in item_map]
        self._selected_ids_in_order = [pid for pid in self._selected_ids_in_order if pid in item_map]
        self._refresh_selection_badges()

    def _accept_insert(self):
        payloads = self._selected_phrases_for_send()
        if not payloads:
            return
        self._selected_payload = payloads
        self.accept()

    def selected_phrase_text(self):
        payloads = self._selected_payload or []
        if isinstance(payloads, dict):
            return str(payloads.get("content", "") or "")

        contents = [str(item.get("content", "") or "").strip() for item in payloads if isinstance(item, dict)]
        contents = [x for x in contents if x]
        return "\n\n".join(contents)

    def apply_theme(self):
        p = theme_manager.get_palette()
        style = "\n".join([
            "QDialog {",
            f"    background-color: {p.BG_PRIMARY};",
            f"    color: {p.TEXT_PRIMARY};",
            "}",
            "QLabel {",
            f"    color: {p.TEXT_PRIMARY};",
            "}",
            "#CommonPhraseSubHint {",
            f"    color: {p.TEXT_SECONDARY};",
            "}",
            "QScrollArea, QLineEdit, QPlainTextEdit {",
            f"    background-color: {p.BG_SECONDARY};",
            f"    color: {p.TEXT_PRIMARY};",
            f"    border: 1px solid {p.BORDER};",
            "    border-radius: 6px;",
            "    padding: 6px;",
            "}",
            "#CommonPhraseListContainer {",
            "    background: transparent;",
            "}",
            "#AnimatedReorderItem {",
            "    background: transparent;",
            "    border: none;",
            "}",
            "#CommonPhraseItem {",
            f"    background-color: {p.BG_SECONDARY};",
            f"    border: 1px solid {p.BORDER};",
            "    border-radius: 8px;",
            "}",
            "#CommonPhraseItem[selected=\"true\"] {",
            f"    background-color: {p.BG_TERTIARY};",
            f"    border: 1px solid {p.ACCENT_PRIMARY};",
            "}",
            "#CommonPhraseDragHandle {",
            f"    color: {p.TEXT_SECONDARY};",
            "    font-size: 14px;",
            "    font-weight: bold;",
            "}",
            "#CommonPhraseTitle {",
            f"    color: {p.TEXT_PRIMARY};",
            "    font-size: 13px;",
            "}",
            "#CommonPhraseOrderBadge {",
            f"    background-color: {p.ACCENT_PRIMARY};",
            "    color: white;",
            "    border-radius: 12px;",
            "    font-weight: bold;",
            "}",
            "QPushButton {",
            f"    background-color: {p.BG_TERTIARY};",
            f"    color: {p.TEXT_PRIMARY};",
            f"    border: 1px solid {p.BORDER};",
            "    border-radius: 6px;",
            "    padding: 6px 12px;",
            "    min-height: 28px;",
            "}",
            "QPushButton:hover {",
            f"    background-color: {p.BORDER};",
            "}",
        ])
        self.setStyleSheet(style)