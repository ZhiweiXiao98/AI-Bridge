# filename: app/core/services/scheduler_service.py
import queue
import uuid
import time
import threading

# === 任务元数据定义 ===
# 格式: Action: (Label, Category[AI/Sys], Cancellable, Icon)
TASK_METADATA = {
    "real_send_text":       ("发送消息", "AI", False, "💬"),
    "compound_send_task":   ("多模态发送", "AI", False, "🖼️"),
    "task_agent_loop":      ("Agent 自动修复", "AI", True, "🚑"),
    "switch_session_task":  ("切换会话", "AI", False, "🔄"),
    "new_chat_task":        ("新建会话", "AI", False, "✨"),
    "do_server_backup":     ("Git 备份", "Sys", True, "💾"),
    "task_fix_all":         ("批量修复", "Sys", True, "🛠️"),
    "run_remote_tests":     ("运行测试", "Sys", True, "🧪"),
    "task_manual_toggle":   ("代码块切换", "Sys", False, "🖱️"),
    "upload_file_task":     ("文件上传", "AI", False, "📂"),
}

class Task:
    def __init__(self, client_id, action, args, kwargs):
        self.id = str(uuid.uuid4())[:8]
        self.client_id = client_id
        self.username = kwargs.get('username', 'Anonymous') 
        self.action = action        
        self.args = args            
        self.kwargs = kwargs        
        self.timestamp = time.time()
        self.tool_call_id = str(kwargs.get('tool_call_id', '') or '').strip()
        self.tool_name = str(kwargs.get('tool_name', '') or '').strip()
        self.conversation_id = str(kwargs.get('conversation_id', '') or '').strip()
        
        # 自动填充元数据
        meta = TASK_METADATA.get(action, (action, "Sys", False, "❓"))
        self.label = meta[0]
        self.category = meta[1]
        self.cancellable = meta[2]
        self.icon = meta[3]

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "client_id": self.client_id,
            "action": self.action,
            "label": self.label,
            "category": self.category,
            "cancellable": self.cancellable,
            "icon": self.icon,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "conversation_id": self.conversation_id,
            "age": round(time.time() - self.timestamp, 1)
        }

class SchedulerService:
    def __init__(self):
        self.queue = queue.Queue()
        self.client_states = {} 
        self.active_client_id = None 
        self.active_username = None 
        self.current_task = None # 当前正在执行的任务
        self._lock = threading.Lock() # 用于快照操作的锁

    def add_task(self, client_id, action, *args, **kwargs):
        task = Task(client_id, action, args, kwargs)
        self.queue.put(task)
        
        username = kwargs.get('username', 'Unknown')
        with self._lock:
            if client_id not in self.client_states:
                self.client_states[client_id] = {"index": 0, "username": username}
            else:
                self.client_states[client_id]["username"] = username
            
        print(f"🚦 [Scheduler] 任务入列: {task.label} (User: {username}) Q:{self.queue.qsize()}")
        return task.id

    def get_next_task(self):
        if not self.queue.empty():
            task = self.queue.get()
            self.active_username = task.username 
            self.current_task = task # 记录当前任务
            return task
        self.current_task = None
        return None
    
    def mark_task_complete(self):
        """任务完成时调用 (可选，用于精确状态)"""
        self.current_task = None

    def get_queue_snapshot(self):
        """
        📸 获取当前队列的快照 (用于前端可视化)
        返回: (active_task, queued_tasks_list)
        """
        # 注意: queue.queue 是 deque 对象，但在多线程下直接迭代可能不安全
        # 最好加锁或快速 list() 复制
        # queue.Queue 内部有 mutex，但我们要访问内部 deque
        
        # 这种访问方式依赖于 Python queue 实现细节，但在标准库中是稳定的
        with self.queue.mutex:
            snapshot = list(self.queue.queue)
            
        active_data = self.current_task.to_dict() if self.current_task else None
        queue_data = [t.to_dict() for t in snapshot]
        
        return active_data, queue_data

    def cancel_task(self, task_id):
        """
        🗑️ 取消指定 ID 的任务 (从队列中移除)
        """
        deleted = False
        new_queue = []
        
        with self.queue.mutex:
            original_tasks = list(self.queue.queue)
            for t in original_tasks:
                if t.id == task_id and t.cancellable:
                    deleted = True
                    print(f"🚫 [Scheduler] 任务已取消: {t.label} ({t.id})")
                else:
                    new_queue.append(t)
            
            if deleted:
                self.queue.queue.clear()
                self.queue.queue.extend(new_queue)
                
        return deleted

    def get_client_session(self, client_id):
        with self._lock:
            if client_id in self.client_states:
                return self.client_states[client_id]["index"]
        return 0

    def set_client_session(self, client_id, session_index):
        with self._lock:
            if client_id not in self.client_states:
                self.client_states[client_id] = {"index": session_index, "username": "Unknown"}
            else:
                self.client_states[client_id]["index"] = session_index

    def get_occupancy_map(self):
        with self._lock:
            occupancy = {}
            for cid, data in self.client_states.items():
                idx = data["index"]
                user = data["username"]
                if idx not in occupancy: occupancy[idx] = []
                if user not in occupancy[idx]: 
                    occupancy[idx].append(user)
            return occupancy