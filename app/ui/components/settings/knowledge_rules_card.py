from PySide6.QtCore import Qt
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class KnowledgeRulesCard(QGroupBox):
    def __init__(self, config=None, parent=None):
        super().__init__("🧠 知识库重建规则", parent)
        self.config = config or {}
        self._editors = []
        self._build_ui()
        self.load_from_config(self.config)

    def _safe_editor_text(self, editor):
        if editor is None:
            return ""
        try:
            if not isValid(editor):
                return ""
        except Exception:
            return ""
        try:
            return editor.toPlainText().strip()
        except RuntimeError:
            return ""

    def _safe_set_editor_text(self, editor, value):
        if editor is None:
            return
        try:
            if not isValid(editor):
                return
        except Exception:
            return
        try:
            editor.setPlainText(str(value or ""))
        except RuntimeError:
            pass

    def _build_ui(self):
        self.setObjectName("knowledgeRulesGroup")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title_desc = QLabel("控制 Git Push 后知识库的收录、过滤与清理策略。")
        title_desc.setObjectName("knowledgeRulesDesc")
        title_desc.setWordWrap(True)
        root.addWidget(title_desc)

        self.toggle_panel = QFrame()
        self.toggle_panel.setObjectName("knowledgeTogglePanel")
        toggle_layout = QVBoxLayout(self.toggle_panel)
        toggle_layout.setContentsMargins(14, 14, 14, 14)
        toggle_layout.setSpacing(10)

        self.knowledge_reindex_enabled_cb = self._create_toggle_row(
            toggle_layout,
            "🧠 启用规则过滤",
            "按路径前缀、扩展名和目录规则限制纳入知识库的文件。",
        )
        self.knowledge_reindex_after_git_push_cb = self._create_toggle_row(
            toggle_layout,
            "🚀 Git Push 后自动重建",
            "代码备份成功后，自动按当前规则刷新知识库索引。",
        )
        self.knowledge_reindex_only_non_empty_cb = self._create_toggle_row(
            toggle_layout,
            "📄 仅索引非空文本文件",
            "跳过空文件，减少无效索引项。",
        )
        self.knowledge_reindex_delete_stale_cb = self._create_toggle_row(
            toggle_layout,
            "🧹 清理历史失效索引",
            "移除已不再匹配规则或已失效的历史路径。",
        )
        root.addWidget(self.toggle_panel)

        self.rules_grid = QGridLayout()
        self.rules_grid.setHorizontalSpacing(12)
        self.rules_grid.setVerticalSpacing(12)

        card_exts, self.knowledge_target_exts_edit = self._create_editor_card(
            "📦 索引扩展名",
            "每行一个扩展名，例如 .py、.md、.json",
            "例如：\n.py\n.md\n.json",
        )
        card_dirs, self.knowledge_skip_dirs_edit = self._create_editor_card(
            "⏭️ 跳过目录",
            "命中这些目录名时，整目录将不参与知识库重建。",
            "例如：\nnode_modules\n.venv\n__pycache__",
        )
        card_prefixes, self.knowledge_include_prefixes_edit = self._create_editor_card(
            "✅ 包含前缀",
            "只收录这些相对路径前缀下的文件。",
            "例如：\napp/\ndocs/\ntests/",
        )
        card_delete, self.knowledge_forced_delete_prefixes_edit = self._create_editor_card(
            "🗑️ 强制删除前缀",
            "即使历史中已存在，也会在重建时从知识库中清理。",
            "例如：\nAI_Bridge_Client_Dist/",
        )

        self.rules_grid.addWidget(card_exts, 0, 0)
        self.rules_grid.addWidget(card_dirs, 0, 1)
        self.rules_grid.addWidget(card_prefixes, 1, 0)
        self.rules_grid.addWidget(card_delete, 1, 1)
        root.addLayout(self.rules_grid)
        root.addStretch()

    def _create_toggle_row(self, parent_layout, title, desc):
        row = QFrame()
        row.setObjectName("knowledgeToggleRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("knowledgeToggleTitle")
        desc_lbl = QLabel(desc)
        desc_lbl.setObjectName("knowledgeToggleDesc")
        desc_lbl.setWordWrap(True)

        text_wrap.addWidget(title_lbl)
        text_wrap.addWidget(desc_lbl)

        checkbox = QCheckBox()
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addLayout(text_wrap, 1)
        layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        parent_layout.addWidget(row)
        return checkbox

    def _create_editor_card(self, title, desc, placeholder):
        card = QFrame()
        card.setObjectName("knowledgeEditorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("knowledgeEditorTitle")
        desc_lbl = QLabel(desc)
        desc_lbl.setObjectName("knowledgeEditorDesc")
        desc_lbl.setWordWrap(True)

        editor = QPlainTextEdit()
        editor.setObjectName("knowledgeEditorInput")
        editor.setPlaceholderText(placeholder)
        editor.setMinimumHeight(132)
        editor.setTabChangesFocus(True)
        self._editors.append(editor)

        layout.addWidget(title_lbl)
        layout.addWidget(desc_lbl)
        layout.addWidget(editor)
        return card, editor

    def load_from_config(self, config):
        self.config = config or {}
        self.knowledge_reindex_enabled_cb.setChecked(bool(self.config.get("knowledge_reindex_enabled", True)))
        self.knowledge_reindex_after_git_push_cb.setChecked(bool(self.config.get("knowledge_reindex_after_git_push",True)))
        self.knowledge_reindex_only_non_empty_cb.setChecked(bool(self.config.get("knowledge_reindex_only_non_empty",True)))
        self.knowledge_reindex_delete_stale_cb.setChecked(bool(self.config.get("knowledge_reindex_delete_stale", True)))
        self._safe_set_editor_text(self.knowledge_target_exts_edit, self.config.get("knowledge_reindex_target_exts", ""))
        self._safe_set_editor_text(self.knowledge_skip_dirs_edit, self.config.get("knowledge_reindex_skip_dirs", ""))
        self._safe_set_editor_text(self.knowledge_include_prefixes_edit, self.config.get("knowledge_reindex_include_prefixes", ""))
        self._safe_set_editor_text(self.knowledge_forced_delete_prefixes_edit,self.config.get("knowledge_reindex_forced_delete_prefixes", ""))

    def to_config_dict(self):
        return {
            "knowledge_reindex_enabled": self.knowledge_reindex_enabled_cb.isChecked(),
            "knowledge_reindex_after_git_push": self.knowledge_reindex_after_git_push_cb.isChecked(),
            "knowledge_reindex_only_non_empty": self.knowledge_reindex_only_non_empty_cb.isChecked(),
            "knowledge_reindex_delete_stale": self.knowledge_reindex_delete_stale_cb.isChecked(),
            "knowledge_reindex_target_exts": self._safe_editor_text(self.knowledge_target_exts_edit),
            "knowledge_reindex_skip_dirs": self._safe_editor_text(self.knowledge_skip_dirs_edit),
            "knowledge_reindex_include_prefixes": self._safe_editor_text(self.knowledge_include_prefixes_edit),
            "knowledge_reindex_forced_delete_prefixes": self._safe_editor_text(self.knowledge_forced_delete_prefixes_edit),
        }

    def apply_theme(self, theme):
        try:
            if not isValid(self):
                return
        except Exception:
            return

        card_bg = getattr(theme, "surface", None) or "rgba(255, 255, 255, 0.05)"
        alt_bg = getattr(theme, "input_bg", None) or "rgba(255, 255, 255, 0.04)"
        border = getattr(theme, "border", None) or "rgba(255, 255, 255, 0.12)"
        text_muted = getattr(theme, "text_secondary", None) or "rgba(255, 255, 255, 0.72)"
        accent = getattr(theme, "accent", None) or "#6E7BFF"
        text_color = getattr(theme, "text", None) or "#FFFFFF"

        self.setStyleSheet(f"""
        QGroupBox#knowledgeRulesGroup {{
            border: 1px solid {border};
            border-radius: 16px;
            margin-top: 12px;
            padding-top: 12px;
            background: rgba(255, 255, 255, 0.02);
        }}
        QGroupBox#knowledgeRulesGroup::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 8px;
            color: {text_color};
            font-weight: 700;
        }}
        QLabel#knowledgeRulesDesc {{
            color: {text_muted};
            padding: 0 4px 2px 4px;
        }}
        QFrame#knowledgeTogglePanel, QFrame#knowledgeEditorCard {{
            background: {card_bg};
            border: 1px solid {border};
            border-radius: 14px;
        }}
        QFrame#knowledgeToggleRow {{
            background: {alt_bg};
            border: 1px solid transparent;
            border-radius: 12px;
        }}
        QFrame#knowledgeToggleRow:hover {{
            border: 1px solid {border};
        }}
        QLabel#knowledgeToggleTitle, QLabel#knowledgeEditorTitle {{
            color: {text_color};
            font-weight: 700;
        }}
        QLabel#knowledgeToggleDesc, QLabel#knowledgeEditorDesc {{
            color: {text_muted};
        }}
        QPlainTextEdit#knowledgeEditorInput {{
            background: {alt_bg};
            color: {text_color};
            border: 1px solid {border};
            border-radius: 12px;
            padding: 10px 12px;
            selection-background-color: {accent};
        }}
        QPlainTextEdit#knowledgeEditorInput:hover {{
            border: 1px solid {accent};
        }}
        QPlainTextEdit#knowledgeEditorInput:focus {{
            border: 1px solid {accent};
            background: rgba(255, 255, 255, 0.06);
        }}
        """)
