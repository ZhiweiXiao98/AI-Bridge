"""
示例面板实现

展示一个简单的面板，包含基本的 UI 组件和功能。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTextEdit, QLineEdit, QGroupBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from app.ui.components.dockable_panel import DockablePanel
import datetime


class ExamplePanel(DockablePanel):
    """示例面板"""
    
    def __init__(self):
        """初始化面板"""
        super().__init__(
            panel_id="example_panel",
            title="示例面板",
            icon_name="🎨"
        )
        
        # 配置
        self.auto_refresh = True
        self.refresh_interval = 5  # 秒
        
        # 计数器
        self.counter = 0
        
        # 定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.on_timer)
        
        # 初始化内容
        self.init_content()
    
    def create_content(self) -> QWidget:
        """
        创建面板内容
        
        Returns:
            QWidget: 面板内容组件
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("🎨 欢迎使用示例面板")
        title_font = QFont()
        title_font.setPixelSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # 描述
        desc_label = QLabel(
            "这是一个示例面板插件，展示了如何开发自定义面板。\n"
            "你可以基于这个模板创建自己的面板。"
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #6B7280; font-size: 13px;")
        layout.addWidget(desc_label)
        
        # 信息组
        info_group = self.create_info_group()
        layout.addWidget(info_group)
        
        # 控制组
        control_group = self.create_control_group()
        layout.addWidget(control_group)
        
        # 日志区域
        log_group = self.create_log_group()
        layout.addWidget(log_group)
        
        layout.addStretch()
        
        return widget
    
    def create_info_group(self) -> QGroupBox:
        """创建信息组"""
        group = QGroupBox("面板信息")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        
        # 当前时间
        self.time_label = QLabel()
        self.update_time()
        layout.addWidget(self.time_label)
        
        # 计数器
        self.counter_label = QLabel(f"计数器: {self.counter}")
        layout.addWidget(self.counter_label)
        
        # 状态
        self.status_label = QLabel("状态: 运行中")
        self.status_label.setStyleSheet("color: #10B981;")
        layout.addWidget(self.status_label)
        
        return group
    
    def create_control_group(self) -> QGroupBox:
        """创建控制组"""
        group = QGroupBox("控制")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        
        # 输入框
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入一些文本...")
        input_layout.addWidget(self.input_field)
        
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self.on_add_clicked)
        input_layout.addWidget(add_btn)
        
        layout.addLayout(input_layout)
        
        # 按钮行
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("启动定时器")
        self.start_btn.clicked.connect(self.on_start_clicked)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止定时器")
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)
        
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.on_clear_clicked)
        button_layout.addWidget(clear_btn)
        
        layout.addLayout(button_layout)
        
        return group
    
    def create_log_group(self) -> QGroupBox:
        """创建日志组"""
        group = QGroupBox("日志")
        layout = QVBoxLayout(group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet(
            "background-color: #1F2937; "
            "color: #E5E7EB; "
            "border: 1px solid #374151; "
            "border-radius: 4px; "
            "padding: 8px; "
            "font-family: 'Consolas', 'Monaco', monospace; "
            "font-size: 12px;"
        )
        layout.addWidget(self.log_text)
        
        return group
    
    def on_add_clicked(self):
        """添加按钮点击"""
        text = self.input_field.text().strip()
        if text:
            self.add_log(f"添加: {text}")
            self.input_field.clear()
        else:
            self.add_log("请输入文本")
    
    def on_start_clicked(self):
        """启动定时器"""
        if not self.timer.isActive():
            self.timer.start(self.refresh_interval * 1000)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.add_log(f"定时器已启动 (间隔: {self.refresh_interval}秒)")
    
    def on_stop_clicked(self):
        """停止定时器"""
        if self.timer.isActive():
            self.timer.stop()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.add_log("定时器已停止")
    
    def on_clear_clicked(self):
        """清空日志"""
        self.log_text.clear()
        self.add_log("日志已清空")
    
    def on_timer(self):
        """定时器触发"""
        self.counter += 1
        self.counter_label.setText(f"计数器: {self.counter}")
        self.update_time()
        self.add_log(f"定时器触发 #{self.counter}")
    
    def update_time(self):
        """更新时间显示"""
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.setText(f"当前时间: {current_time}")
    
    def add_log(self, message: str):
        """
        添加日志
        
        Args:
            message: 日志消息
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def set_auto_refresh(self, enabled: bool):
        """
        设置自动刷新
        
        Args:
            enabled: 是否启用
        """
        self.auto_refresh = enabled
        if enabled and not self.timer.isActive():
            self.on_start_clicked()
    
    def set_refresh_interval(self, interval: int):
        """
        设置刷新间隔
        
        Args:
            interval: 间隔秒数
        """
        self.refresh_interval = interval
        if self.timer.isActive():
            self.timer.setInterval(interval * 1000)
    
    def closeEvent(self, event):
        """面板关闭事件"""
        # 停止定时器
        if self.timer.isActive():
            self.timer.stop()
        
        # 调用父类方法
        super().closeEvent(event)
