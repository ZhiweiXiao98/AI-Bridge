"""Skills 管理面板 - 插件版本"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QPushButton, QScrollArea, QLineEdit,
    QComboBox, QGraphicsOpacityEffect, QDialog, QTextEdit, QApplication
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont
from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager


class SkillCard(QFrame):
    """紧凑的 Skill 卡片"""
    
    toggle_requested = Signal(str)
    detail_requested = Signal(dict)
    
    def __init__(self, skill_data):
        super().__init__()
        self.skill_data = skill_data
        self.is_enabled = skill_data.get('enabled', True)
        self.is_hovered = False
        
        self.setFixedSize(110, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.init_ui()
        self.setup_animations()
        self.apply_style()
        
        # 监听主题变化
        theme_manager.theme_changed.connect(self.on_theme_changed)
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 图标
        icon_label = QLabel(self.skill_data.get('icon', '🔧'))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 22px;")
        layout.addWidget(icon_label)
        
        # 名称
        name_label = QLabel(self.skill_data.get('name', 'Unknown'))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        p = theme_manager.get_palette()
        name_label.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {p.TEXT_PRIMARY};")
        layout.addWidget(name_label)
        
        # 状态标签
        self.status_label = QLabel("✓" if self.is_enabled else "✕")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        p = theme_manager.get_palette()
        bg_color = p.TEXT_SUCCESS if self.is_enabled else p.TEXT_SECONDARY
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: white;
            background-color: {bg_color};
            border-radius: 8px;
            padding: 2px 6px;
            font-weight: bold;
        """)
        layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignRight)
    
    def setup_animations(self):
        pass
    
    def apply_style(self):
        p = theme_manager.get_palette()
        
        if self.is_enabled:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {p.BG_SECONDARY};
                    border: 2px solid {p.ACCENT_PRIMARY};
                    border-radius: 8px;
                    opacity: 1.0;
                }}
                QFrame:hover {{
                    border-color: {p.ACCENT_SECONDARY};
                    background-color: {p.BG_TERTIARY};
                }}
            """)
            self.setGraphicsEffect(None)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {p.BG_SECONDARY};
                    border: 2px solid {p.BORDER};
                    border-radius: 8px;
                }}
                QFrame:hover {{
                    border-color: {p.TEXT_SECONDARY};
                    background-color: {p.BG_TERTIARY};
                }}
            """)
            opacity_effect = QGraphicsOpacityEffect(self)
            opacity_effect.setOpacity(0.5)
            self.setGraphicsEffect(opacity_effect)
    
    def enterEvent(self, event):
        self.is_hovered = True
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        self.is_hovered = False
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_requested.emit(self.skill_data.get('id', ''))
        elif event.button() == Qt.MouseButton.RightButton:
            self.detail_requested.emit(self.skill_data)
        super().mousePressEvent(event)
    
    def update_status(self, enabled: bool):
        self.is_enabled = enabled
        self.skill_data['enabled'] = enabled
        
        p = theme_manager.get_palette()
        self.status_label.setText("✓" if enabled else "✕")
        bg_color = p.TEXT_SUCCESS if enabled else p.TEXT_SECONDARY
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: white;
            background-color: {bg_color};
            border-radius: 8px;
            padding: 2px 6px;
            font-weight: bold;
        """)
        
        self.apply_style()
    
    def on_theme_changed(self):
        """主题变化时更新样式"""
        self.apply_style()
        
        # 更新名称标签颜色
        p = theme_manager.get_palette()
        for child in self.findChildren(QLabel):
            if child.text() not in ['✓', '✕'] and not any(emoji in child.text() for emoji in ['🔧', '📁', '🌐', '🔌']):
                child.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {p.TEXT_PRIMARY};")
        
        # 更新状态标签
        bg_color = p.TEXT_SUCCESS if self.is_enabled else p.TEXT_SECONDARY
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: white;
            background-color: {bg_color};
            border-radius: 8px;
            padding: 2px 6px;
            font-weight: bold;
        """)


class SkillsPanelWidget(DockablePanel):
    """Skills 管理面板 - 插件版本"""
    
    rpc_request = Signal(str, dict)
    
    def __init__(self):
        self.skill_cards = {}
        super().__init__("skills", "Skills", "🎯")
        self.init_content()
        
        # 监听主题变化
        theme_manager.theme_changed.connect(self.apply_theme)
    
    def create_content(self):
        widget = QWidget()
        self.content_widget = widget  # 保存引用以便主题更新
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 工具栏
        toolbar = self.create_toolbar()
        main_layout.addWidget(toolbar)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Skills 容器
        self.skills_container = QWidget()
        self.skills_layout = QGridLayout(self.skills_container)
        self.skills_layout.setSpacing(5)
        self.skills_layout.setContentsMargins(8, 8, 8, 8)
        
        scroll.setWidget(self.skills_container)
        main_layout.addWidget(scroll, 1)
        
        # 状态栏
        self.lbl_status = QLabel("就绪")
        p = theme_manager.get_palette()
        self.lbl_status.setStyleSheet(f"padding: 6px 12px; font-size: 10px; color: {p.TEXT_SECONDARY};")
        main_layout.addWidget(self.lbl_status)
        
        # 背景色
        p = theme_manager.get_palette()
        widget.setStyleSheet(f"background-color: {p.BG_PRIMARY};")
        
        return widget

    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar = QFrame()
        self.toolbar = toolbar  # 保存引用以便主题更新
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        
        # 筛选器
        self.cmb_category = QComboBox()
        self.cmb_category.addItems(["全部", "核心", "扩展", "外部"])
        self.cmb_category.setFixedWidth(80)
        self.cmb_category.currentTextChanged.connect(self.filter_skills)
        layout.addWidget(self.cmb_category)
        
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["全部", "已启用", "已禁用"])
        self.cmb_status.setFixedWidth(80)
        self.cmb_status.currentTextChanged.connect(self.filter_skills)
        layout.addWidget(self.cmb_status)
        
        layout.addStretch()
        
        # 搜索框
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("搜索...")
        self.txt_search.setFixedWidth(150)
        self.txt_search.textChanged.connect(self.filter_skills)
        layout.addWidget(self.txt_search)
        
        # 按钮
        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setObjectName("EmojiToolButton")
        self.btn_refresh.setFixedSize(30, 30)
        self.btn_refresh.setToolTip("刷新")
        self.btn_refresh.clicked.connect(self.request_refresh)
        layout.addWidget(self.btn_refresh)
        
        self.btn_add = QPushButton("➕")
        self.btn_add.setObjectName("EmojiToolButton")
        self.btn_add.setFixedSize(30, 30)
        self.btn_add.setToolTip("导入")
        self.btn_add.clicked.connect(self.import_skill)
        layout.addWidget(self.btn_add)
        
        self.btn_prompt = QPushButton("📝")
        self.btn_prompt.setObjectName("EmojiToolButton")
        self.btn_prompt.setFixedSize(30, 30)
        self.btn_prompt.setToolTip("生成提示词")
        self.btn_prompt.clicked.connect(self.generate_prompt)
        layout.addWidget(self.btn_prompt)
        
        self.apply_toolbar_style(toolbar)
        return toolbar
    
    def apply_toolbar_style(self, toolbar):
        p = theme_manager.get_palette()
        toolbar.setStyleSheet(f"""
            QFrame {{
                background-color: {p.BG_SECONDARY};
                border: none;
                border-bottom: 1px solid {p.BORDER};
            }}
            QComboBox {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 10px;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }}
            QComboBox:hover {{ border-color: {p.ACCENT_PRIMARY}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                selection-background-color: {p.ACCENT_PRIMARY};
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }}
            QLineEdit {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 10px;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }}
            QLineEdit:focus {{ border-color: {p.ACCENT_PRIMARY}; }}
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                font-size: 12px;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }}
            QPushButton#EmojiToolButton {{
                font-size: 16px;
                padding: 0px;
                text-align: center;
                font-family: "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Symbol";
            }}
            QPushButton:hover {{
                background-color: {p.ACCENT_PRIMARY};
                border-color: {p.ACCENT_PRIMARY};
            }}
        """)
    
    def update_skills_data(self, skills_data):
        """更新 Skills 数据"""
        for card in self.skill_cards.values():
            card.deleteLater()
        self.skill_cards.clear()
        
        container_width = self.skills_container.width()
        card_width = 110 + 8
        cols = max(2, container_width // card_width)
        
        row, col = 0, 0
        
        for skill in skills_data:
            card = SkillCard(skill)
            card.toggle_requested.connect(self.toggle_skill)
            card.detail_requested.connect(self.show_skill_detail)
            
            self.skills_layout.addWidget(card, row, col)
            self.skill_cards[skill.get('id', '')] = card
            
            col += 1
            if col >= cols:
                col = 0
                row += 1
        
        self.lbl_status.setText(f"共 {len(skills_data)} 个 Skills")
    
    def filter_skills(self):
        """筛选 Skills"""
        category = self.cmb_category.currentText()
        status = self.cmb_status.currentText()
        search_text = self.txt_search.text().lower()

        category_map = {
            "全部": None,
            "核心": {"core", "核心"},
            "扩展": {"extension", "extended", "ext", "扩展"},
            "外部": {"external", "third_party", "plugin", "外部"},
        }
        selected_categories = category_map.get(category)
        
        for skill_id, card in self.skill_cards.items():
            skill = card.skill_data
            raw_category = str(skill.get('category', '') or '').strip().lower()
            
            if selected_categories is not None and raw_category not in {c.lower() for c in selected_categories}:
                card.hide()
                continue
            
            if status == "已启用" and not skill.get('enabled', True):
                card.hide()
                continue
            elif status == "已禁用" and skill.get('enabled', True):
                card.hide()
                continue
            
            if search_text and search_text not in skill.get('name', '').lower():
                card.hide()
                continue
            
            card.show()
    
    def toggle_skill(self, skill_id):
        card = self.skill_cards.get(skill_id)
        current_enabled = card.skill_data.get('enabled', True) if card else False
        new_enabled = not current_enabled
        self.rpc_request.emit('skills_toggle', {'skill_name': skill_id, 'enabled': new_enabled})

    def reload_skill(self, skill_id):
        if not skill_id:
            self.lbl_status.setText("重载失败：缺少 skill_id")
            return
        self.lbl_status.setText(f"正在重载 {skill_id}...")
        self.rpc_request.emit('reload_skill', {'skill_name': skill_id})
    
    def show_skill_detail(self, skill_data):
        dialog = QDialog(self)
        dialog.setWindowTitle(skill_data.get('name', 'Skill'))
        dialog.resize(600, 400)

        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(f"""
名称: {skill_data.get('name', 'N/A')}
分类: {skill_data.get('category', 'N/A')}
描述: {skill_data.get('description', 'N/A')}
状态: {'已启用' if skill_data.get('enabled') else '已禁用'}
危险: {'是' if skill_data.get('dangerous') else '否'}
        """)
        layout.addWidget(text_edit)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_reload = QPushButton("🔄 重载")
        btn_reload.clicked.connect(lambda: self.reload_skill(skill_data.get('id') or skill_data.get('name', '')))
        btn_layout.addWidget(btn_reload)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.close)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

        dialog.exec()
    
    def request_refresh(self):
        """请求刷新 Skills"""
        print("🔄 [SkillsPanel] 请求刷新")
        self.lbl_status.setText("刷新中...")
        self.rpc_request.emit('refresh_skills', {})
    
    def import_skill(self):
        self.rpc_request.emit('import_skill', {})
    
    def generate_prompt(self):
        self.rpc_request.emit('generate_prompt', {})
    
    def display_system_prompt(self, prompt_data):
        """显示系统提示词对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("系统提示词")
        dialog.resize(800, 600)
        
        # 应用主题色
        p = theme_manager.get_palette()
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {p.BG_PRIMARY};
            }}
            QTextEdit {{
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                font-family: "Consolas", "Monaco", monospace;
                font-size: 11px;
            }}
            QPushButton {{
                background-color: {p.ACCENT_PRIMARY};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }}
            QPushButton:hover {{
                background-color: {p.ACCENT_SECONDARY};
            }}
        """)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(prompt_data.get('content', ''))
        layout.addWidget(text_edit)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_copy = QPushButton("📋 复制")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(text_edit.toPlainText()))
        btn_layout.addWidget(btn_copy)
        
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.close)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        
        dialog.exec()
    
    def apply_theme(self):
        """应用主题到所有组件"""
        # 先调用基类方法，应用标题栏样式
        super().apply_theme()
        
        p = theme_manager.get_palette()
        
        # 更新主容器背景
        if hasattr(self, 'content_widget'):
            self.content_widget.setStyleSheet(f"background-color: {p.BG_PRIMARY};")
        
        # 更新工具栏
        if hasattr(self, 'toolbar'):
            self.apply_toolbar_style(self.toolbar)
        
        # 更新状态栏
        if hasattr(self, 'lbl_status'):
            self.lbl_status.setStyleSheet(f"padding: 6px 12px; font-size: 10px; color: {p.TEXT_SECONDARY};")
        
        # 更新所有卡片
        for card in self.skill_cards.values():
            card.apply_style()
            # 更新卡片内的名称标签颜色
            for child in card.findChildren(QLabel):
                if child.text() not in ['✓', '✕'] and '🔧' not in child.text():
                    child.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {p.TEXT_PRIMARY};")

