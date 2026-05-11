# filename: app/ui/components/panels/sandbox_monitor_panel.py
"""
沙盒监控面板
显示代码执行历史、统计信息和容器状态
"""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont
from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import Theme, Palette

class SandboxMonitorPanel(DockablePanel):
    """沙盒监控面板"""
    
    refresh_requested = Signal()
    clear_history_requested = Signal()
    
    def __init__(self):
        super().__init__("sandbox_monitor", "沙盒监控", "🐳")
        self.init_content()

        # 低频兜底轮询：保留事件驱动的同时，避免事件链断裂后面板永久不刷新
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_requested.emit)
        self.refresh_timer.start(10000)
    
    def create_content(self):
        """创建面板内容"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 1. 统计信息卡片
        stats_group = QGroupBox("📊 执行统计")
        stats_group.setStyleSheet(Theme.group_box())
        stats_layout = QHBoxLayout(stats_group)
        stats_layout.setSpacing(10)
        
        # 总执行次数
        self.total_card = self._create_stat_card("总执行", "0", Palette.TEXT_PRIMARY)
        stats_layout.addWidget(self.total_card)
        
        # 成功次数
        self.success_card = self._create_stat_card("成功", "0", Palette.TEXT_SUCCESS)
        stats_layout.addWidget(self.success_card)
        
        # 失败次数
        self.failed_card = self._create_stat_card("失败", "0", Palette.TEXT_DANGER)
        stats_layout.addWidget(self.failed_card)
        
        # 成功率
        self.rate_card = self._create_stat_card("成功率", "0%", Palette.ACCENT_PRIMARY)
        stats_layout.addWidget(self.rate_card)
        
        # 平均耗时
        self.duration_card = self._create_stat_card("平均耗时", "0s", Palette.TEXT_SECONDARY)
        stats_layout.addWidget(self.duration_card)
        
        layout.addWidget(stats_group)
        
        # 2. 容器状态
        container_group = QGroupBox("🐳 容器状态")
        container_group.setStyleSheet(Theme.group_box())
        container_layout = QHBoxLayout(container_group)
        
        self.container_status = QLabel("检查中...")
        self.container_status.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 13px;")
        container_layout.addWidget(self.container_status)
        
        container_layout.addStretch()
        
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet(Theme.button_success_small())
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.refresh_btn = refresh_btn
        container_layout.addWidget(refresh_btn)
        
        layout.addWidget(container_group)
        
        # 3. 执行历史表格
        history_group = QGroupBox("📜 执行历史（最近 10 条）")
        history_group.setStyleSheet(Theme.group_box())
        history_layout = QVBoxLayout(history_group)
        
        self.history_table = QTableWidget()
        # 设置表格样式 - 使用主题系统颜色
        self.history_table.setStyleSheet("""
            QTableWidget {{
                background-color: {bg_primary};
                alternate-background-color: {bg_secondary};
                color: {text_primary};
                gridline-color: {border};
                border: 1px solid {border};
            }}
            QTableWidget::item {{
                padding: 5px;
                color: {text_primary};
            }}
            QTableWidget::item:selected {{
                background-color: {accent};
                color: {text_primary};
            }}
            QHeaderView::section {{
                background-color: {bg_secondary};
                color: {text_primary};
                padding: 5px;
                border: 1px solid {border};
                font-weight: bold;
            }}
        """.format(
            bg_primary=Palette.BG_PRIMARY,
            bg_secondary=Palette.BG_SECONDARY,
            text_primary=Palette.TEXT_PRIMARY,
            border=Palette.BORDER,
            accent=Palette.ACCENT_PRIMARY
        ))
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["时间", "状态", "耗时", "代码预览", "输出预览"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        history_layout.addWidget(self.history_table)
        
        # 清空历史按钮
        clear_btn = QPushButton("🗑️ 清空历史")
        clear_btn.clicked.connect(self.clear_history_requested.emit)
        history_layout.addWidget(clear_btn)
        
        layout.addWidget(history_group)
        
        return widget
    
    def _create_stat_card(self, title, value, color):
        """创建统计卡片"""
        card = QWidget()
        card.setStyleSheet(Theme.stat_card())
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(5)
        
        title_label = QLabel(title)
        title_label.setStyleSheet(Theme.card_title())
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title_label)
        
        value_label = QLabel(value)
        value_label.setStyleSheet(Theme.card_value(color))
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setObjectName("value")
        card_layout.addWidget(value_label)
        
        return card
    
    def update_statistics(self, stats):
        """更新统计信息"""
        self.total_card.findChild(QLabel, "value").setText(str(stats.get('total', 0)))
        self.success_card.findChild(QLabel, "value").setText(str(stats.get('success', 0)))
        self.failed_card.findChild(QLabel, "value").setText(str(stats.get('failed', 0)))
        self.rate_card.findChild(QLabel, "value").setText(f"{stats.get('success_rate', 0)}%")
        self.duration_card.findChild(QLabel, "value").setText(f"{stats.get('avg_duration', 0)}s")
    
    def update_container_status(self, status, container_id=None):
        """更新容器状态"""
        if status == "running":
            self.container_status.setText(f"✅ 运行中 ({container_id[:12] if container_id else 'N/A'})")
            self.container_status.setStyleSheet(f"color: {Palette.TEXT_SUCCESS}; font-size: 13px;")
        elif status == "stopped":
            self.container_status.setText("⏸️ 已停止")
            self.container_status.setStyleSheet(f"color: {Palette.TEXT_DANGER}; font-size: 13px;")
        else:
            self.container_status.setText("❌ 不可用")
            self.container_status.setStyleSheet(f"color: {Palette.TEXT_DANGER}; font-size: 13px;")
    
    def _on_refresh_clicked(self):
        """刷新按钮点击处理"""
        self.refresh_btn.setText("⏳ 刷新中...")
        self.refresh_btn.setEnabled(False)
        self.refresh_requested.emit()
        QTimer.singleShot(1000, self._restore_refresh_btn)
    
    def _restore_refresh_btn(self):
        """恢复刷新按钮状态"""
        self.refresh_btn.setText("🔄 刷新")
        self.refresh_btn.setEnabled(True)
    
    def update_history(self, history):
        """更新执行历史"""
        self.history_table.setRowCount(0)
        
        for record in history:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            
            # 时间
            time_item = QTableWidgetItem(record['datetime'])
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(row, 0, time_item)
            
            # 状态
            status = "✅ 成功" if record['success'] else "❌ 失败"
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if record['success']:
                status_item.setForeground(QColor(Palette.TEXT_SUCCESS))
            else:
                status_item.setForeground(QColor(Palette.TEXT_DANGER))
            self.history_table.setItem(row, 1, status_item)
            
            # 耗时
            duration_item = QTableWidgetItem(f"{record['duration']}s")
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(row, 2, duration_item)
            
            # 代码预览
            code_preview = record['code'][:50] + "..." if len(record['code']) > 50 else record['code']
            code_item = QTableWidgetItem(code_preview)
            self.history_table.setItem(row, 3, code_item)
            
            # 输出预览
            output_preview = record['output'][:50] + "..." if len(record['output']) > 50 else record['output']
            output_item = QTableWidgetItem(output_preview)
            self.history_table.setItem(row, 4, output_item)
