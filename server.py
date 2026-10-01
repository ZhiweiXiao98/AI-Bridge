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
import argparse
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
from app.core.remote_protocol import SERVER_SIGNAL_ROUTES, build_notification_meta

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
        self._connect_signal_routes()

    def _connect_signal_routes(self):
        for route in SERVER_SIGNAL_ROUTES:
            signal = getattr(self.worker, route.signal_name, None)
            if signal is None:
                continue
            signal.connect(self._make_signal_route_slot(route))

    def _make_signal_route_slot(self, route):
        def _slot(*args):
            payload = route.payload_builder(*args)
            if route.delivery == "targeted" or (isinstance(payload, dict) and payload.get("target_client_id")):
                self.send_to_client(route.message_type, payload)
            else:
                self.broadcast(route.message_type, payload, target_group=route.target_group)
        return _slot

    def handle_status(self, text):
        self.broadcast("status", text)

    def notify_messages(self, messages):
        global LATEST_MESSAGES_DATA
        LATEST_MESSAGES_DATA = messages
        meta = build_notification_meta(messages)
        self.broadcast("notify_messages", meta)

    def notify_sessions(self, sessions):
        global LATEST_SESSIONS_DATA
        LATEST_SESSIONS_DATA = sessions
        meta = build_notification_meta(sessions)
        self.broadcast("notify_sessions", meta)
        # 兼容旧链路：仍保留一次直推，便于渐进切换
        self.broadcast("sessions", sessions, target_group=None)

    def notify_ota_sync(self, sync_data):
        global LATEST_SYNC_DATA
        LATEST_SYNC_DATA = sync_data
        meta = build_notification_meta(sync_data, count_key="file_count")
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
                clean_payload = {k:v for k,v in payload.items() if k not in ["target_client_id", "target_group", "target_username", "target_verified_login"]}
                try:
                    data = json.dumps({"type": msg_type, "payload": clean_payload}, default=str)
                    asyncio.run_coroutine_threadsafe(
                        manager.send_personal_message({"type": msg_type, "payload": clean_payload}, group_id, target_id,
                                                      expected_username=payload.get("target_username"),
                                                      expected_verified_login=payload.get("target_verified_login", False)),
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
    if not payload or not isinstance(payload.get("sub"), str) or not payload["sub"].strip():
        await websocket.close(code=1008)
        return
    username, role = payload["sub"], payload.get("role", "user")

    group_id = "admin" if role == "developer" else "user"
    client_ip = websocket.client.host if websocket.client else "Unknown"
    await manager.connect(websocket, group_id, device_id, username, client_ip, verified_login=bool(payload))

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
                        request_id = str(cmd.get("request_id") or "")
                        expect_response = bool(cmd.get("expect_response") or request_id)

                        def _send_rpc_result(ok=True, result=None, error=""):
                            if not expect_response or not request_id or not api_loop:
                                return
                            payload = {
                                "request_id": request_id,
                                "ok": bool(ok),
                                "result": result,
                                "error": str(error or ""),
                            }
                            asyncio.run_coroutine_threadsafe(
                                manager.send_personal_message({"type": "rpc_result", "payload": payload}, group_id, device_id),
                                api_loop,
                            )

                        if role != "developer":
                            # [Mod] 增加 run_remote_tests 权限
                            ALLOWED = ["send_text", "run_remote_script", "trigger_upload", "upload_file", "handle_compound_send", "request_switch_session", "new_chat", "handle_sync_request", "get_staging_file_content", "run_remote_tests"]
                            if method_name not in ALLOWED:
                                error_msg = f"权限不足: {role} 不能执行此操作"
                                await manager.send_personal_message({"type": "status", "payload": f"❌ {error_msg}"}, group_id, device_id)
                                _send_rpc_result(ok=False, error=error_msg)
                                continue

                        # Runtime controls require a validated login; the legacy "admin"
                        # token shortcut is not an authenticated approval authority.
                        runtime_methods = {"get_agent_runtime_options", "get_agent_runtime_state", "api_cancel", "api_approve_tool"}
                        runtime_call = method_name in runtime_methods
                        if method_name == "api_new_conversation":
                            runtime_call = (cmd.get("kwargs") or {}).get("runtime", "pi") != "legacy"
                        if method_name == "api_send":
                            source = getattr(local_worker, "api_source", None)
                            runtime_call = bool(source and source.get_conversation_runtime() != "legacy")
                        if runtime_call and not payload:
                            error_msg = "Agent runtime requires a verified account login; legacy admin shortcut is not accepted"
                            await manager.send_personal_message({"type": "status", "payload": f"❌ {error_msg}"}, group_id, device_id)
                            _send_rpc_result(ok=False, error=error_msg)
                            continue

                        args = cmd.get("args", [])
                        kwargs = cmd.get("kwargs", {})
                        kwargs.update({'client_id': device_id, 'user_role': role, 'username': username, 'verified_login': bool(payload)})

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
                                # 生成系统提示词（同时返回全量和摘要）
                                tool_protocol = kwargs.get('tool_protocol', 'markdown_fallback')
                                full_prompt = skills_manager.generate_system_prompt(tool_protocol=tool_protocol, summary_only=False)
                                summary_prompt = skills_manager.generate_system_prompt(tool_protocol=tool_protocol, summary_only=True)
                                response = {"type": "skills_prompt", "payload": {"content": full_prompt, "summary": summary_prompt}}
                                await manager.send_personal_message(response, group_id, device_id)

                            elif skills_method == 'get_detail':
                                # 获取单个 Skill 完整文档（AI 按需查询，节省 token）
                                skill_name = kwargs.get('skill_name', '')
                                detail = skills_manager.get_skill_detail(skill_name)
                                if detail:
                                    response = {"type": "skills_detail", "payload": {"skill_name": skill_name, "content": detail}}
                                else:
                                    response = {"type": "skills_detail", "payload": {"skill_name": skill_name, "content": None, "error": f"Skill '{skill_name}' not found"}}
                                await manager.send_personal_message(response, group_id, device_id)

                            else:
                                logger.warning("[Skills RPC] Unknown method: %s", skills_method)

                        elif method_name == 'switch_project':
                            # 服务端项目切换：在服务端进程内执行 switch_to，
                            # 真正触发服务端的 os.chdir 和 WorkerProjectSwitchBridge 槽函数
                            from app.core.project_context import ProjectContext
                            target_path = kwargs.get('path')
                            def _run_switch_project(p=target_path):
                                try:
                                    logger.info("[RPC] start method=switch_project path=%s", p)
                                    ok = ProjectContext.get().switch_to(p)
                                    logger.info("[RPC] done method=switch_project ok=%s cwd=%s", ok, os.getcwd())
                                    _send_rpc_result(ok=True, result=ok)
                                except Exception as e:
                                    logger.error("[RPC] method=switch_project error=%s", e)
                                    local_worker.safe_emit_status(f"❌ 项目切换失败: {e}")
                                    _send_rpc_result(ok=False, error=str(e))
                            threading.Thread(target=_run_switch_project, daemon=True, name="rpc_switch_project").start()

                        elif hasattr(local_worker, method_name):
                            _rpc_method_name = method_name
                            _rpc_args = args
                            _rpc_kwargs = kwargs
                            def _run_worker_rpc(mn=_rpc_method_name, a=_rpc_args, kw=_rpc_kwargs):
                                try:
                                    logger.info("[RPC] start method=%s", mn)
                                    result = getattr(local_worker, mn)(*a, **kw)
                                    logger.info("[RPC] done method=%s", mn)
                                    _send_rpc_result(ok=True, result=result)
                                except Exception as e:
                                    logger.error("[RPC] method=%s error=%s", mn, e)
                                    local_worker.safe_emit_status(f"❌ {mn}: {e}")
                                    _send_rpc_result(ok=False, error=str(e))
                            t = threading.Thread(target=_run_worker_rpc, daemon=True, name=f"rpc_{method_name}")
                            t.start()
                        else:
                            logger.warning("[RPC] Unknown method: %s", method_name)
                            _send_rpc_result(ok=False, error=f"Unknown method: {method_name}")

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
    except WebSocketDisconnect: await manager.disconnect(group_id, device_id, websocket)
    except Exception as e: print(f"❌ [WebSocket Error] {e}"); await manager.disconnect(group_id, device_id, websocket)

def run_fastapi():
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info", ws_ping_interval=None, ws_ping_timeout=60)

def parse_startup_mode(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", choices=["browser", "api"], default=None)
    parser.add_argument("--startup-mode", choices=["browser", "api"], default=None)
    args, _ = parser.parse_known_args(argv[1:] if argv else None)
    return args.mode or args.startup_mode or "browser"

def main():
    global qt_app, local_worker, signal_bridge
    try:
        startup_mode = parse_startup_mode(sys.argv)
        init_logging(side="server")
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        qt_app = QCoreApplication([sys.argv[0]])
        qt_app.setApplicationName("AI Bridge Cloud Hub")
        try:
            qt_app.aboutToQuit.connect(lambda: print("🛑 [Server] qt_app aboutToQuit"))
        except Exception as e:
            print(f"⚠️ [Server] 绑定 aboutToQuit 失败: {e}")

        local_worker = WorkerThread(startup_mode=startup_mode)
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
        print(f"🚀 云端中台 IAM 版启动 (Headless Mode, startup_mode={startup_mode})...")
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
