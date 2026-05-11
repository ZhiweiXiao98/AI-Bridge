import logging
# filename: app/core/remote_worker.py
import json
import time
import os
from app.core.project_context import ProjectContext
import uuid
import requests
import threading
import hashlib
import shutil
from PySide6.QtCore import QThread, Signal, QObject, QUrl, Slot, QTimer
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtNetwork import QNetworkProxy
from app.core.config import ConfigManager
from app.core.app_constants import SERVER_PORT, LOCAL_SERVER_HOST
from app.core.logging import get_logger

logger = get_logger("app.core.remote_worker", side="worker")

class SocketAgent(QObject):
    msg_received = Signal(str)
    status_changed = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.socket = None
        self.retry_count = 0
        self._reconnect_timer = None
        self._stopping = False

    def setup(self):
        self.socket = QWebSocket()
        self.socket.setParent(self)
        # [Fix] 显式设置无代理，防止系统代理干扰连接
        self.socket.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.socket.connected.connect(self.on_connected)
        self.socket.disconnected.connect(self.on_disconnected)
        self.socket.errorOccurred.connect(self.on_error)
        self.socket.textMessageReceived.connect(self.msg_received)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self.do_connect)
        self.do_connect()

    def do_connect(self):
        if self._stopping or not self.socket:
            return
        self.status_changed.emit(f"📡 连接云端: {self.url}")
        self.socket.open(QUrl(self.url))

    def on_connected(self):
        self.status_changed.emit("✅ 已连接")
        self.retry_count = 0
        if self._reconnect_timer and self._reconnect_timer.isActive():
            self._reconnect_timer.stop()
        # 连接成功后立即请求同步状态
        self.send_payload(json.dumps({"action": "sync_state"}))

    def on_disconnected(self):
        if self._stopping:
            return
        self.status_changed.emit("⚠️ 连接断开，等待重连...")
        if self._reconnect_timer and not self._reconnect_timer.isActive():
            self._reconnect_timer.start(2000)

    def on_error(self, error_code):
        err_str = self.socket.errorString() if self.socket else "unknown socket error"
        print(f"🔥 [Socket Error {error_code}] {err_str}")
        self.status_changed.emit(f"❌ 错误: {err_str}")

    @Slot(str)
    def send_payload(self, json_str):
        if self._stopping:
            return
        if self.socket and self.socket.isValid():
            self.socket.sendTextMessage(json_str)

    def force_reset(self):
        if self._stopping:
            return
        if self._reconnect_timer and self._reconnect_timer.isActive():
            self._reconnect_timer.stop()
        if self.socket:
            self.socket.abort()

    def shutdown(self):
        self._stopping = True
        if self._reconnect_timer and self._reconnect_timer.isActive():
            self._reconnect_timer.stop()
        if self.socket:
            try:
                self.socket.connected.disconnect(self.on_connected)
            except Exception as e:
                logger.warning(e)
            try:
                self.socket.disconnected.disconnect(self.on_disconnected)
            except Exception as e:
                logger.warning(e)
            try:
                self.socket.errorOccurred.disconnect(self.on_error)
            except Exception as e:
                logger.warning(e)
            try:
                self.socket.textMessageReceived.disconnect(self.msg_received)
            except Exception as e:
                logger.warning(e)
            self.socket.abort()
            self.socket.deleteLater()
            self.socket = None

class RemoteWorker(QThread):
    # === 信号定义 (与 WorkerThread 保持一致以便 UI 对接) ===
    status_signal = Signal(str)
    messages_signal = Signal(list)
    context_health_signal = Signal(int, int) 
    sessions_signal = Signal(list)
    state_sync_signal = Signal(int, int)     
    restart_needed_signal = Signal(bool)
    snapshot_ready_signal = Signal(str) 
    batch_complete_signal = Signal()
    update_list_signal = Signal(list)
    git_detail_signal = Signal(str)
    git_workbench_signal = Signal(object)
    git_diff_preview_signal = Signal(object)
    git_config_signal = Signal(object)
    server_log_signal = Signal(str)
    ota_sync_signal = Signal(object)
    ai_state_signal = Signal(object)
    occupancy_signal = Signal(object)
    file_preview_signal = Signal(object) 
    latency_signal = Signal(int)
    
    # [New] 测试结果与任务队列监控信号
    test_result_signal = Signal(object)
    skills_list_signal = Signal(list)
    skills_toggle_result_signal = Signal(dict)
    skills_prompt_signal = Signal(dict)
    queue_monitor_signal = Signal(object)
    skills_data_signal = Signal(object)  # Skills 数据
    system_prompt_signal = Signal(object)  # 系统提示词
    context_status_signal = Signal(object)  # API模式: 上下文状态
    context_workspace_signal = Signal(object)  # 上下文工作台完整负载
    api_conversations_signal = Signal(object)  # API 对话列表
    api_messages_deleted_signal = Signal(object)  # API 历史消息删除结果
    context_snapshot_signal = Signal(object)  # 上下文快照（调试浮窗）
    mode_changed_signal = Signal(str)       # 模式切换通知
    code_execution_completed = Signal()     # 代码执行完成

    api_stream_chunk_signal = Signal(object)   # 流式文本块信号
    api_stream_status_signal = Signal(object)  # 流式状态信号
    api_round_state_signal = Signal(object)    # API 单回合状态信号
    knowledge_health_signal = Signal(object)   # 知识检索健康状态
    daemon_suggestion_signal = Signal(object)  # 守护进程回复建议
    _request_send = Signal(str)
    _request_reset = Signal() 

    def __init__(self, token="admin"):
        super().__init__()
        self.token = token 
        self.config = ConfigManager.load()
        host = self.config.get("server_ip", LOCAL_SERVER_HOST) 
        port = self.config.get("server_port", SERVER_PORT)
        
        # 生成唯一 Client ID
        unique_id = str(uuid.uuid4())[:8]
        self.client_id = f"Client_{unique_id}"
        
        self.target_url = f"ws://{host}:{port}/ws/{token}/{self.client_id}"
        self.api_url = f"http://{host}:{port}/api"
        self._agent = None
        self._is_shutting_down = False
        
        # 健康检查定时器 (心跳包)
        self.ping_timer = QTimer(self)
        self.ping_timer.timeout.connect(self.check_health)
        self.ping_timer.start(5000)
        
        self.last_pong_time = time.time()
        self.missed_pongs = 0
        
        self._is_pulling_msg = False
        self._msg_pull_pending = False
        self._is_pulling_sessions = False
        self._sessions_pull_pending = False
        self._last_sessions_pull_ts = 0.0
        self._sessions_pull_min_interval = 10.0
        self.no_proxy = {"http": None, "https": None}

        self._http_session = requests.Session()
        self._http_session.trust_env = False
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=4,
            pool_maxsize=8,
            max_retries=1,
        )
        self._http_session.mount("http://", adapter)
        self._http_session.mount("https://", adapter)
        self._http_session.proxies = self.no_proxy

    def check_health(self):
        if self._is_shutting_down:
            return
        ts = int(time.time() * 1000)
        self._request_send.emit(json.dumps({"action": "ping", "timestamp": ts}))
        
        # 简单的网络健康度监测
        now = time.time()
        if now - self.last_pong_time > 30: 
            self.missed_pongs += 1
            threshold = 12 
            if self.missed_pongs % 2 == 0:
                self.status_signal.emit(f"⚠️ 网络拥堵 ({self.missed_pongs}/{threshold})")
            if self.missed_pongs >= threshold:
                self.status_signal.emit("🔥 连接假死，正在重置...")
                self._request_reset.emit() 
                self.missed_pongs = 0
                self.last_pong_time = now

    # === 公共接口 (UI 调用入口) ===
    
    def request_latest_code(self):
        self.status_signal.emit("☁️ 正在检查代码更新...")
        self.run_driver_action("handle_sync_request")

    def get_staging_file_content(self, rel_path):
        self.run_driver_action("get_staging_file_content", rel_path)

    def run_remote_tests(self):
        self.status_signal.emit("🧪 请求云端执行测试...")
        self.run_driver_action("run_remote_tests")

    def get_git_workbench_state(self, limit=30):
        self.run_driver_action("get_git_workbench_state", limit)

    def get_git_file_diff(self, path, kind=None):
        if kind is None:
            self.run_driver_action("get_git_file_diff", path)
        else:
            self.run_driver_action("get_git_file_diff", path, kind)

    def do_server_push_only(self):
        self.run_driver_action("do_server_push_only")


    def get_git_config_snapshot(self):
        self.run_driver_action("get_git_config_snapshot")

    def do_server_git_init(self):
        self.run_driver_action("do_server_git_init")

    def do_server_git_set_user(self, name, email):
        self.run_driver_action("do_server_git_set_user", name, email)

    def do_server_git_set_remote(self, name, url):
        self.run_driver_action("do_server_git_set_remote", name, url)

    def do_server_set_upstream(self):
        self.run_driver_action("do_server_set_upstream")

    def run_git_connectivity_checks(self):
        self.run_driver_action("run_git_connectivity_checks")
    def run(self):
        # 初始化 WebSocket 代理
        self._agent = SocketAgent(self.target_url)
        self._request_send.connect(self._agent.send_payload)
        self._request_reset.connect(self._agent.force_reset)
        self._agent.msg_received.connect(self.on_agent_msg)
        self._agent.status_changed.connect(self.status_signal)
        self._agent.setup()
        self.exec()

    def stop_worker(self):
        self._is_shutting_down = True
        if self.ping_timer.isActive():
            self.ping_timer.stop()
        try:
            self._request_reset.emit()
        except Exception as e:
            logger.warning(e)
        if self._agent is not None:
            try:
                self._request_send.disconnect(self._agent.send_payload)
            except Exception as e:
                logger.warning(e)
            try:
                self._request_reset.disconnect(self._agent.force_reset)
            except Exception as e:
                logger.warning(e)
            try:
                self._agent.msg_received.disconnect(self.on_agent_msg)
            except Exception as e:
                logger.warning(e)
            try:
                self._agent.status_changed.disconnect(self.status_signal)
            except Exception as e:
                logger.warning(e)
            try:
                self._agent.shutdown()
            except Exception as e:
                logger.warning(e)
            self._agent = None
        try:
            self._http_session.close()
        except Exception:
            pass
        self.quit()
        self.wait(3000)

    # === 消息拉取逻辑 ===
    
    def _trigger_msg_pull(self):
        if self._is_pulling_msg:
            self._msg_pull_pending = True
            return
        self._is_pulling_msg = True
        self._msg_pull_pending = False
        threading.Thread(target=self._pull_msg_thread, daemon=True).start()

    def _pull_msg_thread(self):
        try:
            logger.debug("[RemoteWorker] 开始拉取消息...")
            self._pull_data_core("sync/messages", self.messages_signal)
        finally:
            self._is_pulling_msg = False
            if self._msg_pull_pending:
                self._trigger_msg_pull()

    def _trigger_sessions_pull(self):
        now = time.time()
        min_interval = float(getattr(self, '_sessions_pull_min_interval', 10.0) or 10.0)
        last_ts = float(getattr(self, '_last_sessions_pull_ts', 0.0) or 0.0)
        if now - last_ts < min_interval:
            return
        self._last_sessions_pull_ts = now
        if self._is_pulling_sessions:
            self._sessions_pull_pending = True
            return
        self._is_pulling_sessions = True
        self._sessions_pull_pending = False
        threading.Thread(target=self._pull_sessions_thread, daemon=True).start()

    def _pull_sessions_thread(self):
        try:
            logger.debug("[RemoteWorker] 开始拉取会话列表...")
            self._pull_data_core("sync/sessions", self.sessions_signal)
        finally:
            self._is_pulling_sessions = False
            if self._sessions_pull_pending:
                self._trigger_sessions_pull()

    def _pull_data_core(self, endpoint, callback_signal):
        try:
            url = f"{self.api_url}/{endpoint}"
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = self._http_session.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if "messages" in endpoint and not isinstance(data, list):
                    data = [] 
                if "messages" in endpoint:
                    logger.debug("[RemoteWorker] 拉取到 %s 条消息，发射信号", len(data))
                callback_signal.emit(data)
            else:
                logger.warning("Pull Failed: %s %s", resp.status_code, resp.text)
        except Exception as e:
            logger.warning("Pull Error: %s", e)

    # === 消息处理核心 ===
    @Slot(str)
    def on_agent_msg(self, message):
        mtype = "unknown" 
        try:
            data = json.loads(message)
            mtype = data.get("type")
            payload = data.get("payload")
            
            # 日志：记录收到的消息类型
            self.last_pong_time = time.time()
            self.missed_pongs = 0
            
            # --- 信号分发 ---
            if mtype == "notify_messages":
                self._trigger_msg_pull()
            elif mtype == "notify_sessions":
                self._trigger_sessions_pull()
            elif mtype == "notify_ota_sync":
                self.status_signal.emit("📦 检测到代码更新，正在下载...")
                threading.Thread(target=self._process_ota_pull, daemon=True).start()
            
            elif mtype == "status":
                self.status_signal.emit(payload)
                if isinstance(payload, str) and "🔧 工具执行完成" in payload:
                    self.code_execution_completed.emit()
            elif mtype == "git_detail":
                self.git_detail_signal.emit(payload)
            elif mtype == "context_health": self.context_health_signal.emit(payload.get("total", 0), payload.get("gap", 0))
            elif mtype == "sessions":
                self.sessions_signal.emit(payload)
            elif mtype == "state_sync": self.state_sync_signal.emit(payload.get("max_idx", 0), payload.get("snap_idx", 0))
            elif mtype == "restart_needed": self.restart_needed_signal.emit(payload)
            elif mtype == "snapshot_ready": self.snapshot_ready_signal.emit(payload)
            elif mtype == "batch_complete": self.batch_complete_signal.emit()
            elif mtype == "update_list": self.update_list_signal.emit(payload)
            elif mtype == "server_log": 
                if isinstance(payload, dict): self.server_log_signal.emit(payload.get("text", ""))
            elif mtype == "git_workbench": self.git_workbench_signal.emit(payload)
            elif mtype == "git_diff_preview": self.git_diff_preview_signal.emit(payload)
            elif mtype == "git_config": self.git_config_signal.emit(payload)
            elif mtype == "ai_state": self.ai_state_signal.emit(payload)
            elif mtype == "occupancy": self.occupancy_signal.emit(payload)
            elif mtype == "file_preview": self.file_preview_signal.emit(payload)
            elif mtype == "test_result": self.test_result_signal.emit(payload)
            elif mtype == "queue_monitor": self.queue_monitor_signal.emit(payload) # [New] 队列监控
            elif mtype == "knowledge_health": self.knowledge_health_signal.emit(payload)
            elif mtype == "daemon_suggestion":
                try:
                    count = len(payload or []) if isinstance(payload, (list, tuple)) else 1
                    logger.info("[RemoteWorker] 收到守护建议: count=%s", count)
                except Exception:
                    pass
                self.daemon_suggestion_signal.emit(payload)
            elif mtype == "skills_list": self.skills_list_signal.emit(payload)
            elif mtype == "skills_toggle_result": self.skills_toggle_result_signal.emit(payload)
            elif mtype == "skills_prompt": self.skills_prompt_signal.emit(payload)
            elif mtype == "context_workspace": self.context_workspace_signal.emit(payload)
            elif mtype == "context_snapshot": self.context_snapshot_signal.emit(payload)
            elif mtype == "api_conversations": self.api_conversations_signal.emit(payload)
            elif mtype == "api_messages_deleted": self.api_messages_deleted_signal.emit(payload)
            elif mtype == "api_stream_chunk":
                try:
                    print(f"[DBG][RemoteWorker] recv api_stream_chunk status={payload.get('status') if isinstance(payload, dict) else type(payload)}")
                except Exception as e:
                    logger.warning(e)
                self.api_stream_chunk_signal.emit(payload)
            elif mtype == "api_stream_status":
                try:
                    print(f"[DBG][RemoteWorker] recv api_stream_status status={payload.get('status') if isinstance(payload, dict) else type(payload)}")
                except Exception as e:
                    logger.warning(e)
                self.api_stream_status_signal.emit(payload)
            elif mtype == "api_round_state":
                self.api_round_state_signal.emit(payload)
            elif mtype == "pong":
                now = int(time.time() * 1000)
                sent_time = int(payload)
                self.latency_signal.emit(now - sent_time)
                
        except Exception as e:
            print(f"[Remote] Signal Error ({mtype}): {e}")

    # === OTA (热更新) 逻辑 ===
    def _process_ota_pull(self):
        try:
            url = f"{self.api_url}/sync/code"
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = self._http_session.get(url, headers=headers, timeout=120)
            if resp.status_code == 200:
                payload = resp.json()
                if not isinstance(payload, dict): payload = {}
                self._process_ota_payload(payload)
            else:
                self.status_signal.emit(f"❌ 代码下载失败: {resp.status_code}")
        except Exception as e:
            self.status_signal.emit(f"❌ 代码下载异常: {e}")

    def _process_ota_payload(self, payload):
        cache_root = os.path.join(ProjectContext.get().get_project_root(), "export", "update_cache")
        if not os.path.exists(cache_root): os.makedirs(cache_root)
        real_update_count = 0
        updated_files = []
        all_safe = True
        
        for rel_path, content in payload.items():
            local_path = rel_path 
            is_different = True
            if os.path.exists(local_path):
                try:
                    with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                        local_content = f.read()
                    # 哈希比对防止重复写入
                    local_hash = self._calculate_str_hash(local_content)
                    remote_hash = self._calculate_str_hash(content)
                    if local_hash == remote_hash:
                        is_different = False
                    else:
                        print(f"🔍 [OTA Debug] {rel_path}: 哈希不匹配")
                        print(f"   本地: {local_hash[:16]}... 远程: {remote_hash[:16]}...")
                except Exception as e:
                    print(f"⚠️ Hash Check Failed for {local_path}: {e}")
                    is_different = True
            
            if is_different:
                full_cache_path = os.path.join(cache_root, rel_path)
                dir_name = os.path.dirname(full_cache_path)
                if not os.path.exists(dir_name): os.makedirs(dir_name)
                
                with open(full_cache_path, 'w', encoding='utf-8', newline='\n') as f: 
                    f.write(content.replace('\r\n', '\n'))
                
                real_update_count += 1
                updated_files.append(rel_path)
                if not self._is_safe_to_hot_swap(rel_path): all_safe = False
        
        if real_update_count > 0:
            if all_safe:
                # 尝试热应用非关键文件
                if self._apply_hot_swap(cache_root, updated_files):
                    self.status_signal.emit(f"✅ 已热更新 {real_update_count} 个文件 (无需重启)")
                else: self.status_signal.emit("⚠️ 热更新失败，请手动重启")
            else:
                print(f"📦 [OTA] 捕获到 {real_update_count} 个核心更新，准备重启...")
                self.restart_needed_signal.emit(True) 
        else: self.status_signal.emit("✅ 代码已是最新")

    def _calculate_str_hash(self, content):
        normalized = content.replace('\r\n', '\n').strip()
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def _is_safe_to_hot_swap(self, rel_path):
        """判断文件是否可以热替换（不涉及核心运行时）"""
        p = rel_path.replace('\\', '/')
        if p.startswith("tests/") or p.startswith("tools/") or p.startswith("docs/") or p.startswith("scripts/"): return True
        if p in ["dump_code.py", "README.md", "AI_README.md", "pytest.ini", "print_tree.py"]: return True
        return False

    def _apply_hot_swap(self, cache_root, updated_files):
        try:
            cwd = ProjectContext.get().get_project_root()
            for rel_path in updated_files:
                src = os.path.join(cache_root, rel_path)
                dst = os.path.join(cwd, rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            return True
        except Exception as e: print(f"Hot Swap Failed: {e}"); return False

    # === 复合发送 (文本+附件) ===
    def send_compound(self, text, file_paths):
        if not file_paths and text:
            self.run_driver_action("send_text", "div.aa-chat-input textarea", text)
            return
        self.status_signal.emit(f"📦 正在打包发送 ({len(file_paths)} 文件 + 文本)...")
        threading.Thread(target=self._send_compound_bg, args=(text, file_paths), daemon=True).start()

    def switch_mode(self, mode, **kwargs):
        """显式 RPC 包装：切换消息源模式"""
        self.run_driver_action("switch_mode", mode, **kwargs)

    def api_send(self, text, **kwargs):
        """显式 RPC 包装：API 模式发送消息"""
        self.run_driver_action("api_send", text, **kwargs)

    def api_switch_conversation(self, conv_id, **kwargs):
        """显式 RPC 包装：切换 API 模式对话。"""
        self.run_driver_action("api_switch_conversation", conv_id, **kwargs)

    def api_new_conversation(self, title="新对话", **kwargs):
        """显式 RPC 包装：新建 API 模式对话。"""
        self.run_driver_action("api_new_conversation", title, **kwargs)

    def api_delete_conversation(self, conv_id, **kwargs):
        """显式 RPC 包装：删除 API 模式对话。"""
        self.run_driver_action("api_delete_conversation", conv_id, **kwargs)

    def api_rename_conversation(self, conv_id, title, **kwargs):
        """显式 RPC 包装：重命名 API 模式对话。"""
        self.run_driver_action("api_rename_conversation", conv_id, title, **kwargs)

    def api_pin_conversation(self, conv_id, **kwargs):
        """显式 RPC 包装：置顶 API 模式对话。"""
        self.run_driver_action("api_pin_conversation", conv_id, **kwargs)

    def api_unpin_conversation(self, conv_id, **kwargs):
        """显式 RPC 包装：取消置顶 API 模式对话。"""
        self.run_driver_action("api_unpin_conversation", conv_id, **kwargs)

    def api_set_conversation_model_usage(self, conv_id, usage=None, **kwargs):
        """显式 RPC 包装：设置单个 API 对话使用的 Profile/Chain。"""
        self.run_driver_action("api_set_conversation_model_usage", conv_id, usage, **kwargs)

    def delete_api_messages(self, indexes, conversation_id=None, **kwargs):
        """显式 RPC 包装：删除 API 模式指定历史消息。"""
        self.run_driver_action("delete_api_messages", indexes, conversation_id=conversation_id, **kwargs)


    def _send_compound_bg(self, text, file_paths):
        server_paths = []
        try:
            for local_path in file_paths:
                if not os.path.exists(local_path): continue
                self.status_signal.emit(f"📤 上传中: {os.path.basename(local_path)}")
                with open(local_path, 'rb') as f:
                    files = {'file': (os.path.basename(local_path), f)}
                    # 上传到服务端
                    resp = self._http_session.post(f"{self.api_url}/upload", files=files, timeout=120)
                if resp.status_code == 200: server_paths.append(resp.json().get("path"))
                else: self.status_signal.emit(f"⚠️ 上传失败: {os.path.basename(local_path)}")
            
            if server_paths:
                self.status_signal.emit("✅ 文件就绪，正在投送...")
                self.run_driver_action("handle_compound_send", text, server_paths)
            elif text: 
                self.run_driver_action("send_text", "div.aa-chat-input textarea", text)
        except Exception as e: self.status_signal.emit(f"❌ 发送异常: {e}")

    # === RPC 包装方法 (提供给 UI 显式调用) ===
    def do_server_backup(self, msg, **kwargs):
        self.run_driver_action("do_server_backup", msg)

    def _run_git_bg(self, msg): pass # Client side stub

    def do_server_clear_cache(self, **kwargs):
        self.run_driver_action("do_server_clear_cache")

    def run_driver_action(self, method, *args, **kwargs):
        payload = {"action": "rpc_call", "method": method, "args": args, "kwargs": kwargs}
        self._request_send.emit(json.dumps(payload))

    # === 动态 RPC 代理 (兜底) ===
    # 已知数据属性：这些属性在 WorkerThread 上是普通值而非方法，
    # RemoteWorker 不应将其包装为 RPC 代理，否则 getattr/hasattr 会被静默吞掉
    _NON_RPC_ATTRS = frozenset({
        'current_chat_id', 'last_messages_snapshot', 'was_busy',
        'current_bubble_count', 'toggle_queue', 'connector',
        'api_source', 'state_service', 'engine', 'file_service',
    })

    def __getattr__(self, name):
        """
        核心 RPC 魔法：
        如果调用的方法不存在（如 request_auto_fix），自动打包成 RPC 请求发给 Server。
        已知数据属性和内部属性会正常抛出 AttributeError，避免误拦截。
        """
        if name.startswith("_"): raise AttributeError(name)
        if name.endswith("_signal"): raise AttributeError(name)
        if name in self._NON_RPC_ATTRS: raise AttributeError(name)
        
        def dynamic_method(*args, **kwargs):
            payload = { "action": "rpc_call", "method": name, "args": args, "kwargs": kwargs }
            self._request_send.emit(json.dumps(payload))
        
        return dynamic_method

    def get_context_workspace_payload(self, conversation_id=None):
        if conversation_id is None:
            self.run_driver_action('get_context_workspace_payload')
        else:
            self.run_driver_action('get_context_workspace_payload', conversation_id)

    def get_api_conversations(self):
        self.run_driver_action('get_api_conversations')

    def update_context_workspace_system_prompt(self, content, conversation_id=None):
        if conversation_id is None:
            self.run_driver_action('update_context_workspace_system_prompt', content)
        else:
            self.run_driver_action('update_context_workspace_system_prompt', content, conversation_id)

    def update_context_workspace_working_memory(self, data, conversation_id=None):
        if conversation_id is None:
            self.run_driver_action('update_context_workspace_working_memory', data)
        else:
            self.run_driver_action('update_context_workspace_working_memory', data, conversation_id)

    def clear_context_workspace_working_memory(self, conversation_id=None):
        if conversation_id is None:
            self.run_driver_action('clear_context_workspace_working_memory')
        else:
            self.run_driver_action('clear_context_workspace_working_memory', conversation_id)

    def clear_context_workspace_long_term(self, conversation_id=None):
        if conversation_id is None:
            self.run_driver_action('clear_context_workspace_long_term')
        else:
            self.run_driver_action('clear_context_workspace_long_term', conversation_id)

    def get_last_request_snapshot(self, conversation_id=None):
        if conversation_id is None:
            self.run_driver_action('get_last_request_snapshot')
        else:
            self.run_driver_action('get_last_request_snapshot', conversation_id)

    def skills_list(self, category=None):
        """获取 Skills 列表"""
        payload = {"action": "rpc_call", "method": "skills_list", "kwargs": {"category": category}}
        self._request_send.emit(json.dumps(payload))
    
    def skills_toggle(self, skill_name, enabled):
        """切换 Skill 状态"""
        payload = {"action": "rpc_call", "method": "skills_toggle", "kwargs": {"skill_name": skill_name, "enabled": enabled}}
        self._request_send.emit(json.dumps(payload))
    
    def skills_refresh(self):
        """刷新 Skills"""
        payload = {"action": "rpc_call", "method": "skills_refresh", "kwargs": {}}
        self._request_send.emit(json.dumps(payload))

    def skills_reload(self, skill_name):
        """重载单个 Skill"""
        payload = {"action": "rpc_call", "method": "reload_skill", "kwargs": {"skill_name": skill_name}}
        self._request_send.emit(json.dumps(payload))
    
    def skills_generate_prompt(self):
        """生成系统提示词"""
        payload = {"action": "rpc_call", "method": "skills_generate_prompt", "kwargs": {}}
        self._request_send.emit(json.dumps(payload))
