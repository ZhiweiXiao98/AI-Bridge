# filename: app/ui/components/task_panel.py
import time
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QListWidget, QListWidgetItem, QPushButton, QFrame, 
                               QProgressBar, QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QPropertyAnimation, QByteArray, QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor, QIcon, QFont
from app.ui.theme import theme_manager

class TaskCard(QFrame):
    """
    🎨 精致的任务卡片 (带呼吸特效与计时器)
    """
    cancel_requested = Signal(str) # task_id

    def __init__(self, task_data, is_active=False, is_mine=True):
        super().__init__()
        self.task_id = task_data.get('id')
        self.data = task_data
        self.is_active = is_active
        self.is_mine = is_mine
        
        # 计算初始耗时
        self.start_ts = time.time() - task_data.get('age', 0)
        
        self.init_ui()
        self.apply_style()
        
        # [New] 如果是激活状态，启动特效
        if self.is_active:
            self.start_breathing_effect()
            self.start_live_timer()

    def init_ui(self):
        self.setMinimumHeight(60)  # 确保任务条有足够高度
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        
        # 1. 图标区
        icon_char = self.data.get('icon', '❓')
        self.lbl_icon = QLabel(icon_char)
        self.lbl_icon.setFixedSize(24, 24)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("background: transparent; font-size: 16px;")
        
        if self.is_active:
            # 激活状态：给图标加个绿色背景圈
            self.lbl_icon.setStyleSheet("background-color: rgba(16, 185, 129, 0.2); border-radius: 12px; font-size: 16px;")
        layout.addWidget(self.lbl_icon)
        
        # 2. 信息区
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        # 标题
        title_text = self.data.get('label', '未知任务')
        lbl_title = QLabel(title_text)
        lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; border: none; background: transparent;")
        info_layout.addWidget(lbl_title)
        
        # 副标题 (将由 Timer 更新)
        self.lbl_sub = QLabel()
        self.lbl_sub.setStyleSheet("color: #888; font-size: 11px; border: none; background: transparent;")
        self.update_sub_text() # 初始化显示
        info_layout.addWidget(self.lbl_sub)
        
        layout.addLayout(info_layout)
        layout.addStretch()
        
        # 3. 状态/操作区
        if self.is_active:
            # 运行中状态
            status_layout = QVBoxLayout()
            self.lbl_status = QLabel("RUNNING")
            self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.lbl_status.setStyleSheet("color: #10B981; font-size: 9px; font-weight: bold; border: none; background: transparent;")
            
            # 简单的进度条动画
            p_bar = QProgressBar()
            p_bar.setFixedSize(60, 4)
            p_bar.setRange(0, 0) # Marquee mode
            p_bar.setTextVisible(False)
            p_bar.setStyleSheet("QProgressBar { border: none; background: #333; border-radius: 2px; } QProgressBar::chunk { background: #10B981; }")
            
            status_layout.addWidget(self.lbl_status)
            status_layout.addWidget(p_bar)
            layout.addLayout(status_layout)
            
        elif self.data.get('cancellable', False):
            # 取消按钮
            btn_cancel = QPushButton("×")
            btn_cancel.setFixedSize(24, 24)
            btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_cancel.setToolTip("取消此任务")
            btn_cancel.setStyleSheet("""
                QPushButton { border: none; color: #666; font-weight: bold; font-size: 18px; background: transparent; margin-right: 5px; }
                QPushButton:hover { color: #EF4444; background: rgba(239, 68, 68, 0.1); border-radius: 12px; }
            """)
            btn_cancel.clicked.connect(lambda: self.cancel_requested.emit(self.task_id))
            layout.addWidget(btn_cancel)
        else:
            # 排队中
            lbl_wait = QLabel("WAITING")
            lbl_wait.setStyleSheet("color: #666; font-size: 9px; font-weight: bold; border: none; background: transparent;")
            layout.addWidget(lbl_wait)

    def apply_style(self):
        p = theme_manager.get_palette()
        
        # 基础样式
        bg = p.BG_SECONDARY
        border = "1px solid " + p.BORDER
        
        if self.is_active:
            # 激活：主色调边框 + 轻微背景
            border = f"1px solid {p.ACCENT_PRIMARY}"
            bg = f"{p.ACCENT_PRIMARY}1A" # 10% alpha
        elif self.is_mine:
            # 我的任务：稍微亮一点的背景
            bg = p.BG_TERTIARY
            
        self.setStyleSheet(f"""
            TaskCard {{
                background-color: {bg};
                border: {border};
                border-radius: 6px;
            }}
            QLabel {{ color: {p.TEXT_PRIMARY}; }}
        """)

    # [New] 呼吸特效：让图标透明度循环变化
    def start_breathing_effect(self):
        self.opacity_effect = QGraphicsOpacityEffect(self.lbl_icon)
        self.lbl_icon.setGraphicsEffect(self.opacity_effect)
        
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(1000) # 1秒周期
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.4)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim.setLoopCount(-1) # 无限循环
        self.anim.start()

    # [New] 实时计时器
    def start_live_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_live_age)
        self.timer.start(1000) # 每秒刷新

    def update_live_age(self):
        # 强制刷新子标题
        self.update_sub_text()
        
        # 动态改变状态颜色 (超时警告)
        age = int(time.time() - self.start_ts)
        if age > 60:
            self.lbl_status.setText("SLOW")
            self.lbl_status.setStyleSheet("color: #EF4444; font-size: 9px; font-weight: bold; border: none; background: transparent;")
        elif age > 30:
            self.lbl_status.setText("BUSY")
            self.lbl_status.setStyleSheet("color: #F59E0B; font-size: 9px; font-weight: bold; border: none; background: transparent;")

    def update_sub_text(self):
        user = "我" if self.is_mine else self.data.get('username', 'Unknown')
        category = self.data.get('category', 'Sys')
        tool_name = str(self.data.get('tool_name', '') or '').strip()
        conversation_id = str(self.data.get('conversation_id', '') or '').strip()
        
        # 计算实时耗时
        age = int(time.time() - self.start_ts)
        
        if self.is_active:
            time_str = f"运行中: {age}s"
        else:
            time_str = "排队中"
        
        parts = [user, category]
        if tool_name:
            parts.append(tool_name)
        elif conversation_id:
            parts.append(conversation_id[:8])
        parts.append(time_str)
        self.lbl_sub.setText(" • ".join(parts))

class TaskQueuePanel(QWidget):
    """
    🖥️ 任务队列仪表盘
    """
    cancel_signal = Signal(str) # 向外转发取消请求

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # 头部
        header_layout = QHBoxLayout()
        self.lbl_header = QLabel("任务调度 (空闲)")
        self.lbl_header.setStyleSheet("color: #888; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(self.lbl_header)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # 空状态视图
        self.empty_state = QWidget()
        es_layout = QVBoxLayout(self.empty_state)
        es_layout.setSpacing(10)
        es_layout.addStretch()
        
        lbl_icon = QLabel("☕")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icon.setStyleSheet("font-size: 32px; background: transparent;")
        
        lbl_text = QLabel("Worker 待命中\n系统资源空闲")
        lbl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_text.setStyleSheet("color: #666; font-weight: bold; font-size: 12px; background: transparent;")
        
        es_layout.addWidget(lbl_icon)
        es_layout.addWidget(lbl_text)
        es_layout.addStretch()
        layout.addWidget(self.empty_state)
        
        # 列表
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget { background: transparent; border: none; outline: none; }
            QListWidget::item { margin-bottom: 4px; border: none; }
            QListWidget::item:hover { background: transparent; }
            QListWidget::item:selected { background: transparent; }
        """)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_widget.hide() 
        layout.addWidget(self.list_widget)

    def update_data(self, snapshot, current_client_id="Host"):
        """接收 Worker 信号更新界面"""
        active = snapshot.get('active')
        queue = snapshot.get('queue', [])
        
        # 智能切换空状态
        if not active and not queue:
            self.list_widget.hide()
            self.empty_state.show()
            self.lbl_header.setText("任务调度 (空闲)")
            return
        
        self.empty_state.hide()
        self.list_widget.show()
        
        # 记录滚动条位置
        scroll_val = self.list_widget.verticalScrollBar().value()
        self.list_widget.clear()
        
        total_count = len(queue) + (1 if active else 0)
        state_text = "运行中" if active else "等待中"
        self.lbl_header.setText(f"任务调度 ({total_count}) - {state_text}")
        
        if active:
            self._add_card(active, is_active=True, current_cid=current_client_id)
            
        for task in queue:
            self._add_card(task, is_active=False, current_cid=current_client_id)
            
        self.list_widget.verticalScrollBar().setValue(scroll_val)

    def _add_card(self, task_data, is_active, current_cid):
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(200, 50)) 
        
        is_mine = task_data.get('client_id') == current_cid
        
        card = TaskCard(task_data, is_active=is_active, is_mine=is_mine)
        card.cancel_requested.connect(self.cancel_signal.emit)
        
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, card)