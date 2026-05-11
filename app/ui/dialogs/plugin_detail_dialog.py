from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QTextEdit, QPushButton, QGroupBox, QFormLayout,
    QScrollArea, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
import os
import logging

from app.core.logging import get_logger

logger = get_logger("app.ui.plugin_detail_dialog", side="ui")


class PluginDetailDialog(QDialog):
    """
    插件详情对话框
    
    显示插件的完整信息，包括元数据、依赖、配置和文档。
    """
    
    def __init__(self, plugin_info: dict, plugin_loader, parent=None):
        """
        初始化插件详情对话框
        
        Args:
            plugin_info: 插件信息字典
            plugin_loader: 插件加载器实例
            parent: 父窗口
        """
        super().__init__(parent)
        
        self.plugin_info = self._normalize_plugin_info(plugin_info)
        self.plugin_loader = plugin_loader
        
        self.setWindowTitle(f"插件详情 - {self.plugin_info.get('name', 'Unknown')}")
        self.setMinimumSize(700, 600)
        
        self.init_ui()

    def _normalize_plugin_info(self, plugin_info):
        """将 PluginInfo 对象或 dict 统一转换为 dict。"""
        if isinstance(plugin_info, dict):
            return dict(plugin_info)

        def read_attr(obj, *names, default=None):
            for name in names:
                if hasattr(obj, name):
                    value = getattr(obj, name)
                    if value is not None:
                        return value
            return default

        return {
            'id': read_attr(plugin_info, 'id', default='N/A'),
            'name': read_attr(plugin_info, 'name', default='Unknown'),
            'version': read_attr(plugin_info, 'version', default='0.0.0'),
            'author': read_attr(plugin_info, 'author', default='N/A'),
            'description': read_attr(plugin_info, 'description', default='N/A'),
            'entry': read_attr(plugin_info, 'entry', 'entry_file', default='N/A'),
            'class': read_attr(plugin_info, 'class_name', 'class', default='N/A'),
            'default_area': read_attr(plugin_info, 'default_area', default='N/A'),
            'min_app_version': read_attr(plugin_info, 'min_app_version', default='N/A'),
            'enabled': read_attr(plugin_info, 'enabled', default=False),
            'icon': read_attr(plugin_info, 'icon', default='🔌'),
            'dependencies': read_attr(plugin_info, 'dependencies', default=[]),
            'plugin_dir': read_attr(plugin_info, 'plugin_dir', default=''),
            'config': read_attr(plugin_info, 'config', 'settings', default=None),
        }
        
    def init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标题栏
        header = self.create_header()
        layout.addWidget(header)
        
        # 标签页
        tabs = self.create_tabs()
        layout.addWidget(tabs)
        
        # 底部按钮
        buttons = self.create_buttons()
        layout.addLayout(buttons)
        
    def create_header(self) -> QWidget:
        """创建标题栏"""
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3B82F6, stop:1 #2563EB
                );
                padding: 20px;
            }
        """)
        
        layout = QVBoxLayout(header)
        
        # 插件图标和名称
        title_layout = QHBoxLayout()
        
        icon_label = QLabel(self.plugin_info.get('icon', '🔌'))
        icon_font = QFont()
        icon_font.setPixelSize(48)
        icon_label.setFont(icon_font)
        title_layout.addWidget(icon_label)
        
        info_layout = QVBoxLayout()
        
        name_label = QLabel(self.plugin_info.get('name', 'Unknown'))
        name_font = QFont()
        name_font.setPixelSize(24)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet("color: white;")
        info_layout.addWidget(name_label)
        
        version_label = QLabel(f"版本 {self.plugin_info.get('version', '0.0.0')}")
        version_label.setStyleSheet("color: rgba(255, 255, 255, 0.9); font-size: 14px;")
        info_layout.addWidget(version_label)
        
        title_layout.addLayout(info_layout)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 状态标签
        status_label = QLabel()
        if self.plugin_info.get('enabled', False):
            status_label.setText("✅ 已启用")
            status_label.setStyleSheet("""
                background-color: rgba(16, 185, 129, 0.2);
                color: #10B981;
                padding: 4px 12px;
                border-radius: 12px;
                font-weight: bold;
            """)
        else:
            status_label.setText("⭕ 已禁用")
            status_label.setStyleSheet("""
                background-color: rgba(107, 114, 128, 0.2);
                color: #6B7280;
                padding: 4px 12px;
                border-radius: 12px;
                font-weight: bold;
            """)
        layout.addWidget(status_label, alignment=Qt.AlignmentFlag.AlignLeft)
        
        return header
        
    def create_tabs(self) -> QTabWidget:
        """创建标签页"""
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: white;
            }
            QTabBar::tab {
                padding: 10px 20px;
                margin-right: 2px;
                background: #F3F4F6;
                border: none;
            }
            QTabBar::tab:selected {
                background: white;
                border-bottom: 3px solid #3B82F6;
            }
        """)
        
        # 基本信息标签页
        info_tab = self.create_info_tab()
        tabs.addTab(info_tab, "📋 基本信息")
        
        # 依赖关系标签页
        deps_tab = self.create_dependencies_tab()
        tabs.addTab(deps_tab, "🔗 依赖关系")
        
        # 配置选项标签页
        config_tab = self.create_config_tab()
        tabs.addTab(config_tab, "⚙️ 配置")
        
        # README 标签页
        readme_tab = self.create_readme_tab()
        tabs.addTab(readme_tab, "📖 文档")
        
        return tabs
        
    def create_info_tab(self) -> QWidget:
        """创建基本信息标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 创建信息组
        info_group = QGroupBox("插件信息")
        info_layout = QFormLayout(info_group)
        info_layout.setSpacing(12)
        
        # 添加信息字段
        fields = [
            ("ID", self.plugin_info.get('id', 'N/A')),
            ("名称", self.plugin_info.get('name', 'N/A')),
            ("版本", self.plugin_info.get('version', 'N/A')),
            ("作者", self.plugin_info.get('author', 'N/A')),
            ("描述", self.plugin_info.get('description', 'N/A')),
            ("入口文件", self.plugin_info.get('entry', 'N/A')),
            ("类名", self.plugin_info.get('class', 'N/A')),
            ("默认位置", self.plugin_info.get('default_area', 'N/A')),
            ("最低版本", self.plugin_info.get('min_app_version', 'N/A')),
        ]
        
        for label, value in fields:
            label_widget = QLabel(f"{label}:")
            label_widget.setStyleSheet("font-weight: bold; color: #374151;")
            
            value_widget = QLabel(str(value))
            value_widget.setWordWrap(True)
            value_widget.setStyleSheet("color: #6B7280;")
            
            info_layout.addRow(label_widget, value_widget)
        
        layout.addWidget(info_group)
        layout.addStretch()
        
        return widget
        
    def create_dependencies_tab(self) -> QWidget:
        """创建依赖关系标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        deps = self.plugin_info.get('dependencies', [])
        
        if deps:
            deps_group = QGroupBox(f"依赖项 ({len(deps)})")
            deps_layout = QVBoxLayout(deps_group)
            
            for dep in deps:
                dep_label = QLabel(f"• {dep}")
                dep_label.setStyleSheet("padding: 4px; color: #374151;")
                deps_layout.addWidget(dep_label)
            
            layout.addWidget(deps_group)
        else:
            no_deps_label = QLabel("此插件没有依赖项")
            no_deps_label.setStyleSheet("color: #6B7280; font-style: italic;")
            no_deps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_deps_label)
        
        layout.addStretch()
        
        return widget
        
    def create_config_tab(self) -> QWidget:
        """创建配置选项标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        config = self.plugin_info.get('config')
        
        if isinstance(config, dict) and config:
            config_group = QGroupBox("当前配置")
            config_layout = QFormLayout(config_group)
            
            for key, value in config.items():
                key_label = QLabel(f"{key}:")
                key_label.setStyleSheet("font-weight: bold; color: #374151;")
                
                value_label = QLabel(str(value))
                value_label.setWordWrap(True)
                value_label.setStyleSheet("color: #6B7280;")
                
                config_layout.addRow(key_label, value_label)
            
            layout.addWidget(config_group)
        else:
            no_config_label = QLabel("此插件没有配置项")
            no_config_label.setStyleSheet("color: #6B7280; font-style: italic;")
            no_config_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_config_label)
        
        layout.addStretch()
        
        return widget
        
    def create_readme_tab(self) -> QWidget:
        """创建 README 标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建文本编辑器
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                border: none;
                padding: 20px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                line-height: 1.6;
            }
        """)
        
        # 尝试加载 README
        try:
            plugin_path = self.plugin_info.get('plugin_dir')
            if not plugin_path:
                text_edit.setPlainText("此插件未提供目录信息，无法定位 README。")
            else:
                readme_path = os.path.join(plugin_path, 'README.md')
                if os.path.exists(readme_path):
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        readme_content = f.read()
                    text_edit.setPlainText(readme_content)
                else:
                    text_edit.setPlainText("此插件没有 README 文档。")
        except Exception as e:
            text_edit.setPlainText(f"加载 README 失败：{str(e)}")
            logger.error(f"加载 README 失败: {e}")
        
        layout.addWidget(text_edit)
        
        return widget
        
    def create_buttons(self) -> QHBoxLayout:
        """创建底部按钮"""
        layout = QHBoxLayout()
        layout.setContentsMargins(20, 10, 20, 20)
        
        layout.addStretch()
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        layout.addWidget(close_btn)
        
        return layout
