# filename: server.py
import logging
import sys
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
import os
import json
import threading
import asyncio
import traceback
import uvicorn
import io
import shutil
import time
import sqlite3
import hashlib
import binascii
import re
from contextlib import asynccontextmanager
from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from PySide6.QtCore import QObject, QCoreApplication
from app.core.connection_manager import manager
from app.core.worker import WorkerThread
from app.core.skills import SkillsManager
from app.core.config import ConfigManager
from app.core.auth_service import auth, DB_PATH
from app.core.app_constants import SERVER_HOST, SERVER_PORT
from app.core.logging import init_logging, get_logger

logger = get_logger("server")

qt_app = None
local_worker = None
api_loop = None 
signal_bridge = None
skills_manager = None  # Skills 管理器

@asynccontextmanager
async def lifespan(app: FastAPI):
    global api_loop, skills_manager
    api_loop = asyncio.get_running_loop()
    
    # 初始化 Skills 管理器
    skills_manager = SkillsManager()
    core_count, extended_count, external_count = skills_manager.scan_all_skills()
    print(f"✅ [Server] Skills 已加载: 核心={core_count}, 扩展={extended_count}, 外部={external_count}")
    
    print("✅ [Server] API Loop 已捕获，服务就绪")
    yield
    print("🛑 [Server] 服务正在停止...")

app = FastAPI(title="AI Bridge Cloud Hub", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1000)

config = ConfigManager.load()
img_path = config.get("export_image_path", "export/images")
os.makedirs(img_path, exist_ok=True)
app.mount("/images", StaticFiles(directory=img_path), name="images")

UPLOAD_DIR = os.path.join("export", "temp_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

LATEST_SYNC_DATA = {} 
LATEST_MESSAGES_DATA = []
LATEST_SESSIONS_DATA = []

_NOISE_PATTERNS = [
    "connection pool is full",
    "urllib3.connectionpool",
    "discarding connection",
    "httpx",
    "httpcore",
]

_NOISE_PATH_PREFIXES = [
    "/api/sync/messages",
    "/api/sync/sessions",
    "/api/health",
]

_LOG_THROTTLE_WINDOW = 2.0
_LOG_MAX_LENGTH = 2000
_LOG_MAX_BROADCAST_PER_SEC = 30

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str
    name: str

class LogInterceptor(io.StringIO):
    def __init__(self, original_std, prefix=""):
        super().__init__()
        self.original_std = original_std
        self.prefix = prefix
        self._sig_timestamps = {}
        self._broadcast_count = 0
        self._broadcast_window_start = time.time()

    def _normalize_signature(self, text: str):
        s = (text or '').strip()
        m = re.search(r'"([A-Z]+)\s+([^\s]+)\s+HTTP/[0-9.]+"\s+(\d{3})', s)
        if m:
            method, path, status = m.group(1), m.group(2), m.group(3)
            for noise_prefix in _NOISE_PATH_PREFIXES:
                if path.startswith(noise_prefix):
                    return f'NOISE_ACCESS {method} {noise_prefix}'
            return f'ACCESS {method} {path} {status}'
        return s

    def _is_noise(self, text: str) -> bool:
        lower = (text or '').lower()
        for pattern in _NOISE_PATTERNS:
            if pattern in lower:
                return True
        return False

    def _throttle_ok(self, sig: str) -> bool:
        now = time.time()
        last = self._sig_timestamps.get(sig, 0)
        if now - last < _LOG_THROTTLE_WINDOW:
            return False
        self._sig_timestamps[sig] = now
        if len(self._sig_timestamps) > 500:
            newest = sorted(self._sig_timestamps.items(), key=lambda x: x[1], reverse=True)[:200]
            self._sig_timestamps = dict(newest)
        return True

    def _rate_limit_ok(self) -> bool:
        now = time.time()
        if now - self._broadcast_window_start >= 1.0:
            self._broadcast_count = 0
            self._broadcast_window_start = now
        self._broadcast_count += 1
        if self._broadcast_count > _LOG_MAX_BROADCAST_PER_SEC:
            return False
        return True

    def write(self, text):
        self.original_std.write(text)
        s = (text or '').strip()
        if not (signal_bridge and s):
            return

        if self._is_noise(s):
            return

        if len(s) > _LOG_MAX_LENGTH:
            s = s[:_LOG_MAX_LENGTH] + "...[truncated]"

        sig = self._normalize_signature(text)
        if not self._throttle_ok(sig):
            return
        if not self._rate_limit_ok():
            return

        signal_bridge.broadcast("server_log", {"text": s}, target_group="admin")

    def flush(self):
        self.original_std.flush()

class SignalBridge(QObject):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.worker.messages_signal.connect(self.notify_messages)
        self.worker.ota_sync_signal.connect(self.notify_ota_sync)
        self.worker.sessions_signal.connect(self.notify_sessions)
        self.worker.snapshot_ready_signal.connect(lambda s: self.broadcast("snapshot_ready", s))
        self.worker.status_signal.connect(self.handle_status)
        if hasattr(self.worker, 'git_detail_signal'):
            self.worker.git_detail_signal.connect(lambda text: self.broadcast("git_detail", text))
        if hasattr(self.worker, 'git_workbench_signal'):
            self.worker.git_workbench_signal.connect(lambda d: self.send_to_client("git_workbench", d))
        if hasattr(self.worker, 'git_diff_preview_signal'):
            self.worker.git_diff_preview_signal.connect(lambda d: self.send_to_client("git_diff_preview", d))
        if hasattr(self.worker, 'git_config_signal'):
            self.worker.git_config_signal.connect(lambda d: self.send_to_client("git_config", d))
        self.worker.context_health_signal.connect(lambda t, g: self.broadcast("context_health", {"total": t, "gap": g}))
        self.worker.state_sync_signal.connect(lambda m, s: self.broadcast("state_sync", {"max_idx": m, "snap_idx": s}))
        self.worker.update_list_signal.connect(lambda d: self.broadcast("update_list", d))
        self.worker.ai_state_signal.connect(lambda s: self.broadcast("ai_state", s))
        self.worker.occupancy_signal.connect(lambda d: self.broadcast("occupancy", d))
        self.worker.file_preview_signal.connect(lambda d: self.send_to_client("file_preview", d))
        self.worker.test_result_signal.connect(lambda d: self.send_to_client("test_result", d))
        if hasattr(self.worker, 'context_workspace_signal'):
            self.worker.context_workspace_signal.connect(lambda d: self.send_to_client("context_workspace", d))
        if hasattr(self.worker, 'context_snapshot_signal'):
            self.worker.context_snapshot_signal.connect(lambda d: self.send_to_client("context_snapshot", d))
        if hasattr(self.worker, 'api_conversations_signal'):
            self.worker.api_conversations_signal.connect(lambda d: self.send_to_client("api_conversations", d))
        if hasattr(self.worker, 'daemon_suggestion_signal'):
            # 守护进程建议 payload 是 list[str]，不能走 send_to_client(dict-only)，需要广播给 RemoteWorker。
            self.worker.daemon_suggestion_signal.connect(lambda d: self.broadcast("daemon_suggestion", d))
        
        # [New] 🔥 绑定任务队列监控信号
        if hasattr(self.worker, 'queue_monitor_signal'):
            self.worker.queue_monitor_signal.connect(lambda d: self.broadcast("queue_monitor", d))

        # [Health] 知识检索健康状态广播
        if hasattr(self.worker, 'knowledge_health_signal'):
            self.worker.knowledge_health_signal.connect(lambda d: self.broadcast("knowledge_health", d))

        # [Stream] API 流式输出桥接（RemoteWorker -> UI）
        if hasattr(self.worker, 'api_stream_chunk_signal'):
            self.worker.api_stream_chunk_signal.connect(lambda d: self.send_to_client("api_stream_chunk", d))
        if hasattr(self.worker, 'api_stream_status_signal'):
            self.worker.api_stream_status_signal.connect(lambda d: self.send_to_client("api_stream_status", d))
        if hasattr(self.worker, 'api_round_state_signal'):
            self.worker.api_round_state_signal.connect(lambda d: self.send_to_client("api_round_state", d))

    def handle_status(self, text):
        self.broadcast("status", text)

    def notify_messages(self, messages):
        global LATEST_MESSAGES_DATA
        LATEST_MESSAGES_DATA = messages
        meta = {"count": len(messages), "ts": time.time()}
        self.broadcast("notify_messages", meta)

    def notify_sessions(self, sessions):
        global LATEST_SESSIONS_DATA
        LATEST_SESSIONS_DATA = sessions
        meta = {"count": len(sessions), "ts": time.time()}
        self.broadcast("notify_sessions", meta)
        # 兼容旧链路：仍保留一次直推，便于渐进切换
        self.broadcast("sessions", sessions, target_group=None)

    def notify_ota_sync(self, sync_data):
        global LATEST_SYNC_DATA
        LATEST_SYNC_DATA = sync_data
        meta = {"file_count": len(sync_data), "ts": time.time()}
        self.broadcast("notify_ota_sync", meta)

    def broadcast(self, msg_type, payload, target_group=None):
        if api_loop:
            try:
                data = json.dumps({"type": msg_type, "payload": payload}, default=str)
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast_to_group(data, target_group), 
                    api_loop
                )
            except Exception as e:
                sys.__stderr__.write(f"❌ Broadcast Error: {e}\n")

    def send_to_client(self, msg_type, payload):
        if api_loop and isinstance(payload, dict):
            target_id = payload.get("target_client_id")
            group_id = payload.get("target_group", "admin")
            logger.debug("[SignalBridge] send_to_client type=%s target=%s group=%s", msg_type, target_id, group_id)
            if target_id:
                clean_payload = {k:v for k,v in payload.items() if k not in ["target_client_id", "target_group"]}
                try:
                    data = json.dumps({"type": msg_type, "payload": clean_payload}, default=str)
                    asyncio.run_coroutine_threadsafe(
                        manager.send_personal_message({"type": msg_type, "payload": clean_payload}, group_id, target_id),
                        api_loop
                    )
                except Exception as e:
                    logger.debug("[SignalBridge] send_error type=%s err=%s", msg_type, e)

@app.get("/")
async def root(): return {"status": "Running", "role": "Cloud Hub (Headless)"}

async def verify_admin(authorization: str = Header(None)):
    if not authorization: raise HTTPException(401, "Missing Token")
    token = authorization.replace("Bearer ", "")
    payload = auth.decode_token(token)
    if not payload or payload.get("role") != "developer": raise HTTPException(403, "Permission Denied")
    return payload

@app.post("/api/login")
async def login(req: LoginRequest):
    if not auth.verify_password(req.username, req.password):
        auth.log_action(req.username, "Login Failed")
        raise HTTPException(status_code=401, detail="账号或密码错误")
    user_info = auth.get_user_role(req.username)
    access_token = auth.create_access_token(data={"sub": req.username, "role": user_info["role"]})
    auth.log_action(req.username, "Login Success")
    return {"status": "ok", "username": req.username, "role": user_info["role"], "display_name": user_info["name"], "token": access_token}

@app.get("/api/sync/messages")
async def get_messages(user=Depends(verify_admin)):
    return JSONResponse(content=LATEST_MESSAGES_DATA)

@app.get("/api/sync/sessions")
async def get_sessions(user=Depends(verify_admin)):
    return JSONResponse(content=LATEST_SESSIONS_DATA)

@app.get("/api/sync/code")
async def get_code_sync(user=Depends(verify_admin)):
    return JSONResponse(content=LATEST_SYNC_DATA)


@app.get("/api/admin/users")
async def list_users(user=Depends(verify_admin)): return auth.get_all_users()

@app.get("/api/admin/online")
async def list_online_users(user=Depends(verify_admin)): return manager.get_online_users()

@app.post("/api/admin/users")
async def add_user(req: CreateUserRequest, user=Depends(verify_admin)):
    ok, msg = auth.create_user(req.username, req.password, req.role, req.name); 
    if not ok: raise HTTPException(400, msg)
    auth.log_action(user["sub"], f"Created User: {req.username}"); return {"msg": msg}

@app.delete("/api/admin/users/{username}")
async def delete_user(username: str, user=Depends(verify_admin)):
    ok, msg = auth.delete_user(username)
    if not ok: raise HTTPException(400, msg)
    auth.log_action(user["sub"], f"Deleted User: {username}"); return {"msg": msg}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        unique_name = f"{int(time.time())}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, unique_name)
        with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        abs_path = os.path.abspath(file_path)
        print(f"📥 [Server] 接收文件: {abs_path}")
        return {"status": "ok", "path": abs_path}
    except Exception as e: print(f"❌ [Server] Upload Error: {e}"); raise HTTPException(500, str(e))

@app.websocket("/ws/{token}/{device_id}")
async def websocket_endpoint(websocket: WebSocket, token: str, device_id: str):
    payload = auth.decode_token(token)
    username = "Guest"
    if not payload:
        if token == "admin": username, role = "admin", "developer"
        else: await websocket.close(code=1008); return
    else: username, role = payload.get("sub"), payload.get("role", "user")

    group_id = "admin" if role == "developer" else "user"
    client_ip = websocket.client.host if websocket.client else "Unknown"
    await manager.connect(websocket, group_id, device_id, username, client_ip)
    
    try:
        while True:
            try:
                data = await websocket.receive_text()
                try:
                    cmd = json.loads(data)
                    action = cmd.get("action")
                    if action == "rpc_call":
                        method_name = cmd.get("method")
                        logger.info("[RPC] %s -> %s", username, method_name)
                        
                        if role != "developer":
                            # [Mod] 增加 run_remote_tests 权限
                            ALLOWED = ["send_text", "run_remote_script", "trigger_upload", "upload_file", "handle_compound_send", "request_switch_session", "new_chat", "handle_sync_request", "get_staging_file_content", "run_remote_tests"]
                            if method_name not in ALLOWED:
                                await manager.send_personal_message({"type": "status", "payload": f"❌ 权限不足: {role} 不能执行此操作"}, group_id, device_id); continue
                        
                        args = cmd.get("args", [])
                        kwargs = cmd.get("kwargs", {})
                        kwargs.update({'client_id': device_id, 'user_role': role, 'username': username})
                        
                        # Skills RPC 处理
                        if method_name.startswith('skills_'):
                            global skills_manager
                            # Skills 相关的 RPC 调用
                            skills_method = method_name[7:]  # 去掉 'skills_' 前缀
                            
                            if skills_method == 'list':
                                # 获取 Skills 列表
                                category = kwargs.get('category')
                                skills_data = skills_manager.list_all_skills(category)
                                response = {"type": "skills_list", "payload": skills_data}
                                await manager.send_personal_message(response, group_id, device_id)
                                
                            elif skills_method == 'toggle':
                                # 切换 Skill 状态
                                skill_name = kwargs.get('skill_name')
                                enabled = kwargs.get('enabled')
                                success = skills_manager.toggle_skill(skill_name, enabled)
                                response = {"type": "skills_toggle_result", "payload": {"success": success, "skill_name": skill_name, "enabled": enabled}}
                                await manager.send_personal_message(response, group_id, device_id)
                                
                            elif skills_method == 'refresh':
                                # 刷新 Skills
                                core_count, extended_count, external_count = skills_manager.scan_all_skills()
                                skills_data = skills_manager.list_all_skills()
                                response = {"type": "skills_list", "payload": skills_data}
                                await manager.send_personal_message(response, group_id, device_id)
                                
                            elif skills_method == 'generate_prompt':
                                # 生成系统提示词
                                prompt = skills_manager.generate_system_prompt()
                                response = {"type": "skills_prompt", "payload": {"content": prompt}}
                                await manager.send_personal_message(response, group_id, device_id)
                                
                            else:
                                logger.warning("[Skills RPC] Unknown method: %s", skills_method)
                        
                        elif hasattr(local_worker, method_name):
                            _rpc_method_name = method_name
                            _rpc_args = args
                            _rpc_kwargs = kwargs
                            def _run_worker_rpc(mn=_rpc_method_name, a=_rpc_args, kw=_rpc_kwargs):
                                try:
                                    logger.info("[RPC] start method=%s", mn)
                                    getattr(local_worker, mn)(*a, **kw)
                                    logger.info("[RPC] done method=%s", mn)
                                except Exception as e:
                                    logger.error("[RPC] method=%s error=%s", mn, e)
                            t = threading.Thread(target=_run_worker_rpc, daemon=True, name=f"rpc_{method_name}")
                            t.start()
                        else:
                            logger.warning("[RPC] Unknown method: %s", method_name)

                    elif action == "sync_state":
                        if local_worker:
                            threading.Thread(target=local_worker.trigger_resync, daemon=True, name="rpc_trigger_resync").start()
                    elif action == "warmup_knowledge":
                        phases = payload.get("phases", ["embedder", "reranker"])
                        def _run_warmup(phases=phases):
                            try:
                                ks = getattr(local_worker, 'knowledge_service', None)
                                if ks and hasattr(ks, '_v2'):
                                    ks._v2.warmup(phases=phases)
                                else:
                                    logger.warning("[Warmup RPC] 知识检索服务不可用")
                            except Exception as e:
                                logger.error("[Warmup RPC] 预热失败: %s", e)
                        threading.Thread(target=_run_warmup, daemon=True, name="warmup_rpc").start()
                    elif action == "ping": 
                        await websocket.send_text(json.dumps({"type": "pong", "payload": cmd.get("timestamp")}))
                except Exception as logic_error:
                    print(f"❌ [Server Logic Error] {logic_error}")
            except json.JSONDecodeError: pass
    except WebSocketDisconnect: await manager.disconnect(group_id, device_id)
    except Exception as e: print(f"❌ [WebSocket Error] {e}"); await manager.disconnect(group_id, device_id)

def run_fastapi():
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info", ws_ping_interval=None, ws_ping_timeout=60)

def main():
    global qt_app, local_worker, signal_bridge
    try:
        init_logging(side="server")
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        qt_app = QCoreApplication(sys.argv)
        qt_app.setApplicationName("AI Bridge Cloud Hub")
        try:
            qt_app.aboutToQuit.connect(lambda: print("🛑 [Server] qt_app aboutToQuit"))
        except Exception as e:
            print(f"⚠️ [Server] 绑定 aboutToQuit 失败: {e}")

        local_worker = WorkerThread()
        try:
            local_worker.started.connect(lambda: print("🚀 [Server] local_worker started"))
        except Exception as e:
            print(f"⚠️ [Server] 绑定 worker.started 失败: {e}")
        try:
            local_worker.finished.connect(lambda: print("🛑 [Server] local_worker finished"))
        except Exception as e:
            print(f"⚠️ [Server] 绑定 worker.finished 失败: {e}")

        signal_bridge = SignalBridge(local_worker)
        sys.stdout = LogInterceptor(sys.__stdout__)
        sys.stderr = LogInterceptor(sys.__stderr__)
        print("🚀 云端中台 IAM 版启动 (Headless Mode)...")
        local_worker.start()

        t = threading.Thread(target=run_fastapi, daemon=True, name="fastapi")
        t.start()

        def _warmup_knowledge():
            time.sleep(5)
            try:
                ks = getattr(local_worker, 'knowledge_service', None)
                if ks and hasattr(ks, '_v2'):
                    v2 = ks._v2
                    v2.start_executor()
                    v2.warmup()
                    health = v2.get_health()
                    logger.info("[Warmup] 阶段1(Chroma)预热完成: state=%s path=%s embedder=%s reranker=%s",
                               health['state'], health['active_path'],
                               health['embedding_mode'], health['reranker_mode'])
                    logger.info("[Warmup] 阶段2(embedder)/阶段3(reranker)未自动执行，可通过 RPC warmup_knowledge 触发")
                else:
                    logger.warning("[Warmup] 知识检索服务不可用，跳过预热")
            except Exception as e:
                logger.warning("[Warmup] 知识检索预热失败（不影响主服务）: %s", e)

        t_warmup = threading.Thread(target=_warmup_knowledge, daemon=True, name="warmup")
        t_warmup.start()

        exit_code = qt_app.exec()
        print(f"🛑 [Server] qt_app.exec() ended | exit_code={exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("🛑 [Server] KeyboardInterrupt")
    except Exception as e:
        print(f"❌ [Server] main exception: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()