# 主窗口集成 Skills 面板示例代码
# 这是一个完整的示例，展示如何将 Skills 面板集成到主窗口

from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
from PySide6.QtCore import QThread

from app.ui.panels.skills_panel import SkillsPanel
from app.core.worker import WorkerThread


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("应用主窗口")
        self.setMinimumSize(1200, 800)
        
        self.setup_ui()
        self.setup_worker()
        
    def setup_ui(self):
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # 创建标签页
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # 添加其他面板（示例）
        # self.tabs.addTab(self.chat_panel, "💬 对话")
        # self.tabs.addTab(self.files_panel, "📁 文件")
        
        # === 添加 Skills 面板 ===
        self.skills_panel = SkillsPanel()
        self.skills_panel.rpc_request.connect(self.handle_skills_rpc)
        self.tabs.addTab(self.skills_panel, "🎯 Skills")
        
    def setup_worker(self):
        # 创建 Worker 线程
        self.worker = WorkerThread()
        
        # 连接基础信号
        # self.worker.status_signal.connect(self.update_status)
        # self.worker.messages_signal.connect(self.update_messages)
        # ... 其他信号连接 ...
        
        # === 连接 Skills 相关信号 ===
        self.worker.skills_data_signal.connect(self.handle_skills_data)
        self.worker.system_prompt_signal.connect(self.handle_system_prompt)
        
        # 启动 Worker
        self.worker.start()
        
    # === Skills 面板相关方法 ===
    
    def handle_skills_rpc(self, method, kwargs):
        """处理 Skills 面板的 RPC 请求"""
        if hasattr(self.worker, method):
            # 调用 worker 的对应方法
            getattr(self.worker, method)(**kwargs)
        else:
            print(f"警告: Worker 没有方法 {method}")
            
    def handle_skills_data(self, data):
        """处理 Skills 数据"""
        # 判断是否是发给本客户端的
        if data.get('target_client_id') == 'Host':
            self.skills_panel.update_skills_data(data['skills'])
            
    def handle_system_prompt(self, data):
        """处理系统提示词"""
        if data.get('target_client_id') == 'Host':
            self.skills_panel.display_system_prompt(data['prompt'])
            
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止 Worker 线程
        if hasattr(self, 'worker'):
            self.worker.running = False
            self.worker.wait()
        
        event.accept()


# 如果你的主窗口已经存在，只需要添加以下代码：

# 1. 在 __init__ 或 setup_ui 中添加:
# self.skills_panel = SkillsPanel()
# self.skills_panel.rpc_request.connect(self.handle_skills_rpc)
# self.tabs.addTab(self.skills_panel, "🎯 Skills")

# 2. 在 setup_worker 或信号连接处添加:
# self.worker.skills_data_signal.connect(self.handle_skills_data)
# self.worker.system_prompt_signal.connect(self.handle_system_prompt)

# 3. 添加三个处理方法:
# def handle_skills_rpc(self, method, kwargs):
#     if hasattr(self.worker, method):
#         getattr(self.worker, method)(**kwargs)
#
# def handle_skills_data(self, data):
#     if data.get('target_client_id') == 'Host':
#         self.skills_panel.update_skills_data(data['skills'])
#
# def handle_system_prompt(self, data):
#     if data.get('target_client_id') == 'Host':
#         self.skills_panel.display_system_prompt(data['prompt'])
