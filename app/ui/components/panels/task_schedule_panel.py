# filename: app/ui/components/panels/task_schedule_panel.py
"""
任务调度面板
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from app.ui.components.dockable_panel import DockablePanel
from app.ui.components.task_panel import TaskQueuePanel
from app.ui.theme import theme_manager

class TaskSchedulePanel(DockablePanel):
    """任务调度面板"""
    # 向外转发取消请求（task_id）
    cancel_signal = Signal(str)
    
    def __init__(self):
        super().__init__("task_schedule", "任务调度", "📅")
        self.init_content()
    
    def create_content(self):
        """创建面板内容"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 使用现有的 TaskQueuePanel
        self.task_panel = TaskQueuePanel()
        self.task_panel.lbl_header.hide()  # 隐藏标题（因为面板已经有标题了）
        
        # 转发内部取消信号到面板级别
        self.task_panel.cancel_signal.connect(self.cancel_signal.emit)
        
        layout.addWidget(self.task_panel)
        
        return widget
    
    def update_task_queue(self, data, client_id="Host"):
        """更新任务队列"""
        if hasattr(self, 'task_panel'):
            self.task_panel.update_data(data, current_client_id=client_id)
