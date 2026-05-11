from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox, QMenu
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QColor, QFont, QAction
from typing import Optional, List
import logging

from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager
from app.core.logging import get_logger

logger = get_logger("app.ui.plugin_manager_panel", side="ui")


class PluginManagerPanel(DockablePanel):
    """
    插件管理面板
    
    提供插件管理的图形界面，允许用户：
    - 查看所有已安装的插件
    - 启用或禁用插件
    - 卸载插件
    - 查看插件详细信息
    - 刷新插件列表
    """
    
    # 信号
    plugin_enabled = Signal(str)  # 插件ID
    plugin_disabled = Signal(str)  # 插件ID
    plugin_uninstalled = Signal(str)  # 插件ID
    plugin_detail_requested = Signal(str)  # 插件ID
    
    def __init__(self, plugin_loader, parent=None):
        """
        初始化插件管理面板
        
        Args:
            plugin_loader: 插件加载器实例
            parent: 父窗口
        """
        super().__init__(
            panel_id="plugin_manager",
            title="插件管理器",
            icon_name="🔌",
            parent=parent
        )
        
        self.plugin_loader = plugin_loader
        # 创建内容 widget
        self.content_widget = QWidget()
        self.setWidget(self.content_widget)
        
        self.init_ui()
        self.load_plugins()
        
        # 监听主题变化
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()
        
    def init_ui(self):
        """初始化用户界面"""
        # 主布局
        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 顶部工具栏
        toolbar = self.create_toolbar()
        layout.addLayout(toolbar)
        
        # 插件列表表格
        self.plugin_table = self.create_plugin_table()
        layout.addWidget(self.plugin_table)
        
        # 底部状态栏
        self.status_label = QLabel("就绪")
        # 样式将在 apply_theme 中设置
        layout.addWidget(self.status_label)
        
    def create_toolbar(self) -> QHBoxLayout:
        """创建工具栏"""
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        # 标题
        self.title_label = QLabel("已安装的插件")
        title_font = QFont()
        title_font.setPixelSize(14)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        # 样式将在 apply_theme 中设置
        toolbar.addWidget(self.title_label)
        
        toolbar.addStretch()
        
        # 刷新按钮
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.setToolTip("重新扫描插件目录")
        self.refresh_btn.clicked.connect(self.refresh_plugins)
        toolbar.addWidget(self.refresh_btn)
        
        return toolbar
        
    def create_plugin_table(self) -> QTableWidget:
        """创建插件列表表格"""
        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels([
            "状态", "名称", "版本", "作者", "描述", "操作"
        ])
        
        # 设置表格属性
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(36)
        
        # 设置列宽
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        
        table.setColumnWidth(0, 60)  # 状态
        table.setColumnWidth(2, 80)  # 版本
        table.setColumnWidth(5, 120)  # 操作
        
        # 样式将在 apply_theme 中设置
        
        # 双击查看详情
        table.cellDoubleClicked.connect(self.on_plugin_double_clicked)
        
        return table
        
    def load_plugins(self):
        """加载插件列表"""
        try:
            # 扫描插件
            plugins = self.plugin_loader.scan_plugins()
            
            # 清空表格
            self.plugin_table.setRowCount(0)
            
            # 填充表格
            for plugin_info in plugins:
                self.add_plugin_row(plugin_info)
            
            # 更新状态
            self.status_label.setText(f"共 {len(plugins)} 个插件")
            
            logger.info(f"加载了 {len(plugins)} 个插件")
            
            # 应用主题到新加载的组件
            self.apply_theme()
            
        except Exception as e:
            logger.error(f"加载插件列表失败: {e}")
            QMessageBox.critical(
                self,
                "错误",
                f"加载插件列表失败：{str(e)}"
            )
            
    def add_plugin_row(self, plugin_info: dict):
        """添加插件行"""
        row = self.plugin_table.rowCount()
        self.plugin_table.insertRow(row)
        
        # 状态
        status_item = QTableWidgetItem()
        if plugin_info.enabled:
            status_item.setText("✅ 启用")
            status_item.setForeground(QColor(theme_manager.get_palette().TEXT_SUCCESS))
        else:
            status_item.setText("⭕ 禁用")
            status_item.setForeground(QColor(theme_manager.get_palette().TEXT_SECONDARY))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plugin_table.setItem(row, 0, status_item)
        
        # 名称
        name_item = QTableWidgetItem(plugin_info.name)
        name_item.setData(Qt.ItemDataRole.UserRole, plugin_info.id)
        self.plugin_table.setItem(row, 1, name_item)
        
        # 版本
        version_item = QTableWidgetItem(plugin_info.version)
        version_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plugin_table.setItem(row, 2, version_item)
        
        # 作者
        author_item = QTableWidgetItem(plugin_info.author)
        self.plugin_table.setItem(row, 3, author_item)
        
        # 描述
        desc_item = QTableWidgetItem(plugin_info.description)
        self.plugin_table.setItem(row, 4, desc_item)
        
        # 操作按钮
        actions_widget = self.create_action_buttons(plugin_info)
        self.plugin_table.setCellWidget(row, 5, actions_widget)
        
    def create_action_buttons(self, plugin_info: dict) -> QWidget:
        """创建操作按钮"""
        widget = QWidget()
        widget.setObjectName("PluginActionCell")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        plugin_id = plugin_info.id
        is_enabled = plugin_info.enabled
        
        # 启用/禁用按钮
        toggle_btn = QPushButton("禁用" if is_enabled else "启用")
        toggle_btn.setObjectName("PluginActionButton")
        toggle_btn.setFixedSize(58, 24)
        toggle_btn.clicked.connect(
            lambda: self.toggle_plugin(plugin_id, is_enabled)
        )
        layout.addWidget(toggle_btn)
        
        # 详情按钮
        detail_btn = QPushButton("详情")
        detail_btn.setObjectName("PluginActionButton")
        detail_btn.setFixedSize(58, 24)
        detail_btn.clicked.connect(
            lambda: self.show_plugin_detail(plugin_id)
        )
        layout.addWidget(detail_btn)
        
        layout.addStretch()
        return widget
        
    def toggle_plugin(self, plugin_id: str, is_enabled: bool):
        """切换插件启用状态"""
        try:
            if is_enabled:
                # 禁用插件
                result = QMessageBox.question(
                    self,
                    "确认",
                    f"确定要禁用插件 '{plugin_id}' 吗？\n\n禁用后需要重启应用才能生效。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if result == QMessageBox.StandardButton.Yes:
                    self.plugin_loader.disable_plugin(plugin_id)
                    self.plugin_disabled.emit(plugin_id)
                    QMessageBox.information(
                        self,
                        "成功",
                        f"插件 '{plugin_id}' 已禁用。\n\n请重启应用以使更改生效。"
                    )
                    self.refresh_plugins()
            else:
                # 启用插件
                result = QMessageBox.question(
                    self,
                    "确认",
                    f"确定要启用插件 '{plugin_id}' 吗？\n\n启用后需要重启应用才能生效。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if result == QMessageBox.StandardButton.Yes:
                    self.plugin_loader.enable_plugin(plugin_id)
                    self.plugin_enabled.emit(plugin_id)
                    QMessageBox.information(
                        self,
                        "成功",
                        f"插件 '{plugin_id}' 已启用。\n\n请重启应用以使更改生效。"
                    )
                    self.refresh_plugins()
                    
        except Exception as e:
            logger.error(f"切换插件状态失败: {e}")
            QMessageBox.critical(
                self,
                "错误",
                f"操作失败：{str(e)}"
            )
            
    def show_plugin_detail(self, plugin_id: str):
        """显示插件详情"""
        self.plugin_detail_requested.emit(plugin_id)
        
    def refresh_plugins(self):
        """刷新插件列表"""
        self.status_label.setText("正在刷新...")
        self.load_plugins()
        
    def on_plugin_double_clicked(self, row: int, column: int):
        """处理插件双击事件"""
        name_item = self.plugin_table.item(row, 1)
        if name_item:
            plugin_id = name_item.data(Qt.ItemDataRole.UserRole)
            self.show_plugin_detail(plugin_id)
    
    def apply_theme(self):
        """应用主题到所有组件"""
        # 先调用基类方法，应用标题栏样式
        super().apply_theme()
        
        p = theme_manager.get_palette()
        
        # 更新标题标签
        if hasattr(self, 'title_label'):
            self.title_label.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        
        # 更新状态栏
        if hasattr(self, 'status_label'):
            self.status_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        
        # 更新表格样式
        if hasattr(self, 'plugin_table'):
            self.plugin_table.setStyleSheet(f"""
                QTableWidget {{
                    border: 1px solid {p.BORDER};
                    border-radius: 4px;
                    background-color: {p.BG_SECONDARY};
                    color: {p.TEXT_PRIMARY};
                }}
                QTableWidget::item {{
                    padding: 1px 2px;
                    color: {p.TEXT_PRIMARY};
                }}
                QTableWidget::item:selected {{
                    background-color: {p.ACCENT_PRIMARY};
                    color: white;
                }}
                QTableWidget::item:alternate {{
                    background-color: {p.BG_TERTIARY};
                }}
                QHeaderView::section {{
                    background-color: {p.BG_TERTIARY};
                    padding: 8px;
                    border: none;
                    border-bottom: 2px solid {p.BORDER};
                    font-weight: bold;
                    color: {p.TEXT_PRIMARY};
                }}
                QWidget#PluginActionCell {{
                    background: transparent;
                    border: none;
                }}
                QPushButton#PluginActionButton {{
                    background-color: {p.BG_PRIMARY};
                    color: {p.TEXT_PRIMARY};
                    border: 1px solid {p.BORDER};
                    border-radius: 4px;
                    padding: 0px;
                    font-size: 11px;
                    font-weight: 600;
                    min-height: 24px;
                }}
                QPushButton#PluginActionButton:hover {{
                    background-color: {p.ACCENT_PRIMARY};
                    color: white;
                    border-color: {p.ACCENT_PRIMARY};
                }}
                QPushButton#PluginActionButton:pressed{{
                    background-color: {p.ACCENT_SECONDARY};
                    color: white;
                    border-color: {p.ACCENT_SECONDARY};
                }}
            """)
            
            # 强制刷新操作列组件样式，避免被全局 QTableWidget 样式吞掉
            for row in range(self.plugin_table.rowCount()):
                cell_widget = self.plugin_table.cellWidget(row, 5)
                if cell_widget:
                    cell_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                    cell_widget.setStyleSheet("QWidget#PluginActionCell { background: transparent; border: none; }")
                    for btn in cell_widget.findChildren(QPushButton):
                        btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                        btn.style().unpolish(btn)
                        btn.style().polish(btn)
                        btn.update()
        
        # 更新刷新按钮
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {p.ACCENT_PRIMARY};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {p.ACCENT_SECONDARY};
                }}
            """)