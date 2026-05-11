import logging
# filename: start_server.py
# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import filedialog
import subprocess
import os
import json
import socket
import sys
import threading
import datetime
import time
import shutil
from app.core.app_constants import CHROME_PORT, SERVER_PORT, RESTART_EXIT_CODE, UPDATE_EXIT_CODE, UPSTREAM_AI_URL, LOCAL_SERVER_HOST
from app.core.logging import get_logger

logger = get_logger("start_server", side="core")

SERVER_SCRIPT = "server.py"
CLIENT_SCRIPT = "boot_remote.py"
CONFIG_FILE = "server_config.json"
RESTART_CODE = RESTART_EXIT_CODE
UPDATE_CODE = UPDATE_EXIT_CODE
MAGIC_CMD_RESTART = "::MAGIC_CMD_RESTART_SERVER::"

MAX_LOG_LINES = 8000
TRIM_BATCH = 2000

NOISE_PATTERNS = [
    "/api/sync/messages",
    "/api/sync/sessions",
    "heartbeat",
    "ping",
    "pong",
    "[DBG][StreamChunk]",
    "chunk_delta",
]

LEVEL_COLORS = {
    "ERROR": "#FF5555",
    "CRITICAL": "#FF2222",
    "WARNING": "#FFB74D",
    "INFO": "#CCCCCC",
    "DEBUG": "#666666",
    "SUCCESS": "#66BB6A",
    "SERVER": "#FFD700",
    "CLIENT": "#00E5FF",
    "SYSTEM": "#9E9E9E",
    "UPDATE": "#76FF03",
    "INSTALL": "#E040FB",
}

SEVERITY_ORDER = {"DEBUG": 0, "INFO": 1, "SUCCESS": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}


def _classify_line(text: str) -> tuple:
    """Return (severity_level, category) — severity is DEBUG/INFO/…/CRITICAL, category is GENERAL/INSTALL/UPDATE/SYSTEM."""
    lower = text.lower()

    # 优先识别标准 logger 格式，避免把真实 DEBUG/WARNING/ERROR 误判成 INFO
    if "| critical" in lower:
        return "CRITICAL", "GENERAL"
    if "| error" in lower:
        return "ERROR", "GENERAL"
    if "| warning" in lower or "| warn" in lower:
        return "WARNING", "GENERAL"
    if "| debug" in lower:
        return "DEBUG", "GENERAL"
    if "| info" in lower:
        return "INFO", "GENERAL"

    for icon in ("🔥", "❌"):
        if icon in text:
            return "ERROR", "GENERAL"
    if "⚠️" in text or "warn" in lower:
        return "WARNING", "GENERAL"
    if "✅" in text or "成功" in text:
        return "SUCCESS", "GENERAL"
    if "📦" in text or "[Pip]" in text or "[Install]" in text:
        return "INFO", "INSTALL"
    if "⚡" in text or "[Update]" in text or "升级" in text:
        return "INFO", "UPDATE"
    if "♻️" in text or "[System]" in text:
        return "INFO", "SYSTEM"
    if "[DBG]" in text or "[debug]" in lower:
        return "DEBUG", "GENERAL"
    if "error" in lower or "exception" in lower or "traceback" in lower or "失败" in text:
        return "ERROR", "GENERAL"
    return "INFO", "GENERAL"


def _is_noise(text: str) -> bool:
    lower = text.lower()
    for p in NOISE_PATTERNS:
        if p.lower() in lower:
            return True
    return False


class SmartLogPanel(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._line_count = 0
        self._auto_scroll = True
        self._filter_level = "ALL"
        self._filter_source = "ALL"
        self._search_text = ""
        self._paused = False
        self._pending_lines = []
        self._all_lines = []
        self._flush_timer = None

        self._build_ui()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg="#2D2D2D")
        toolbar.pack(fill="x", padx=0, pady=0)

        btn_style = {"bg": "#3C3C3C", "fg": "#CCCCCC", "font": ("Arial", 9),
                      "relief": "flat", "padx": 8, "pady": 2, "activebackground": "#505050"}

        self.btn_pause = tk.Button(toolbar, text="⏸ 暂停", command=self._toggle_pause, **btn_style)
        self.btn_pause.pack(side="left", padx=2, pady=3)

        self.btn_clear = tk.Button(toolbar, text="🗑 清空", command=self._clear, **btn_style)
        self.btn_clear.pack(side="left", padx=2, pady=3)

        self.btn_scroll = tk.Button(toolbar, text="📌 自动滚动: 开", command=self._toggle_scroll, **btn_style)
        self.btn_scroll.pack(side="left", padx=2, pady=3)

        sep1 = tk.Frame(toolbar, width=1, bg="#555555")
        sep1.pack(side="left", fill="y", padx=6, pady=4)

        tk.Label(toolbar, text="级别:", bg="#2D2D2D", fg="#999999", font=("Arial", 9)).pack(side="left", padx=(4, 2))
        self.level_var = tk.StringVar(value="ALL")
        levels = ["ALL", "CRITICAL", "ERROR", "WARNING", "SUCCESS", "INFO", "DEBUG"]
        self.level_menu = tk.OptionMenu(toolbar, self.level_var, *levels, command=self._on_level_change)
        self.level_menu.config(bg="#3C3C3C", fg="#CCCCCC", font=("Arial", 9), relief="flat",
                                activebackground="#505050", highlightthickness=0)
        self.level_menu["menu"].config(bg="#3C3C3C", fg="#CCCCCC")
        self.level_menu.pack(side="left", padx=2, pady=3)

        tk.Label(toolbar, text="来源:", bg="#2D2D2D", fg="#999999", font=("Arial", 9)).pack(side="left", padx=(4, 2))
        self.source_var = tk.StringVar(value="ALL")
        sources = ["ALL", "SERVER", "CLIENT", "SYSTEM", "INSTALL", "UPDATE"]
        self.source_menu = tk.OptionMenu(toolbar, self.source_var, *sources, command=self._on_source_change)
        self.source_menu.config(bg="#3C3C3C", fg="#CCCCCC", font=("Arial", 9), relief="flat",
                                 activebackground="#505050", highlightthickness=0)
        self.source_menu["menu"].config(bg="#3C3C3C", fg="#CCCCCC")
        self.source_menu.pack(side="left", padx=2, pady=3)

        sep2 = tk.Frame(toolbar, width=1, bg="#555555")
        sep2.pack(side="left", fill="y", padx=6, pady=4)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        self.search_entry = tk.Entry(toolbar, textvariable=self.search_var, width=16,
                                      bg="#3C3C3C", fg="#CCCCCC", insertbackground="#CCCCCC",
                                      font=("Consolas", 9), relief="flat")
        self.search_entry.pack(side="left", padx=2, pady=3)
        self.search_entry.insert(0, "搜索...")

        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)

        self.status_label = tk.Label(toolbar, text="", bg="#2D2D2D", fg="#666666", font=("Consolas", 8))
        self.status_label.pack(side="right", padx=8, pady=3)

        log_frame = tk.Frame(self, bg="#1E1E1E")
        log_frame.pack(fill="both", expand=True)

        self.text = tk.Text(log_frame, bg="#1E1E1E", fg="#CCCCCC", font=("Consolas", 9),
                             wrap="word", state="disabled", cursor="arrow",
                             selectbackground="#264F78", selectforeground="#FFFFFF",
                             padx=6, pady=4)
        scrollbar = tk.Scrollbar(log_frame, command=self.text.yview, troughcolor="#2D2D2D")
        self.text.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        for tag, color in LEVEL_COLORS.items():
            self.text.tag_config(tag, foreground=color)
        self.text.tag_config("highlight", background="#5C4A00", foreground="#FFD700")

        self.text.bind("<MouseWheel>", self._on_mousewheel)

    def _on_search_focus_in(self, event):
        if self.search_var.get() == "搜索...":
            self.search_entry.delete(0, "end")

    def _on_search_focus_out(self, event):
        if not self.search_var.get().strip():
            self.search_entry.insert(0, "搜索...")

    def _on_mousewheel(self, event):
        if event.delta > 0:
            self.text.yview_scroll(-3, "units")
        else:
            self.text.yview_scroll(3, "units")

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.btn_pause.config(text="▶ 继续", bg="#4CAF50")
        else:
            self.btn_pause.config(text="⏸ 暂停", bg="#3C3C3C")
            self._flush_pending()

    def _toggle_scroll(self):
        self._auto_scroll = not self._auto_scroll
        state = "开" if self._auto_scroll else "关"
        self.btn_scroll.config(text=f"📌 自动滚动: {state}")

    def _clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self._line_count = 0
        self._all_lines.clear()
        self._pending_lines.clear()
        self._update_status()

    def _on_level_change(self, val):
        self._filter_level = val
        self._refresh_display()

    def _on_source_change(self, val):
        self._filter_source = val
        self._refresh_display()

    def _on_search_change(self, *args):
        text = self.search_var.get()
        if text == "搜索...":
            self._search_text = ""
        else:
            self._search_text = text.strip().lower()
        self._refresh_display()

    def _should_show(self, level, category, source, text):
        # Level filter: severity >= selected level
        if self._filter_level != "ALL":
            min_level = SEVERITY_ORDER.get(self._filter_level, 0)
            line_level = SEVERITY_ORDER.get(level, 0)
            if line_level < min_level:
                return False

        # Source/Category filter: match source OR category
        if self._filter_source != "ALL":
            if source != self._filter_source and category != self._filter_source:
                return False

        # Search filter
        if self._search_text:
            if self._search_text not in text.lower():
                return False

        return True

    def append_line(self, text, source="SERVER"):
        if _is_noise(text):
            return

        level, category = _classify_line(text)
        ts = datetime.datetime.now().strftime("%H:%M:%S")

        # Always store the line (never discard)
        self._all_lines.append((text, source, level, category, ts))
        if len(self._all_lines) > MAX_LOG_LINES:
            self._all_lines = self._all_lines[-MAX_LOG_LINES + TRIM_BATCH:]

        if self._paused:
            self._pending_lines.append((text, source, level, category, ts))
            return

        # Only display if it passes the current filter
        if self._should_show(level, category, source, text):
            self._write_line(text, source, level, category, ts)

    def _flush_pending(self):
        lines = self._pending_lines[:]
        self._pending_lines.clear()
        for text, source, level, category, ts in lines:
            if self._should_show(level, category, source, text):
                self._write_line(text, source, level, category, ts)

    def _refresh_display(self):
        """Re-render all stored log lines based on current filter settings."""
        if not hasattr(self, "text"):
            return
        saved_scroll = self._auto_scroll
        self._auto_scroll = False

        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self._line_count = 0

        for entry in self._all_lines:
            text, source, level, category, ts = entry
            if self._should_show(level, category, source, text):
                self._write_line(text, source, level, category, ts, skip_status=True)

        self._auto_scroll = saved_scroll
        self._trim_if_needed()
        if self._auto_scroll:
            self.text.see("end")
        self._update_status()

    def _write_line(self, text, source, level, category, ts=None, skip_status=False):
        if ts is None:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
        # Prefix shows source/category (who sent it); text shows severity level (how bad it is)
        prefix_tag = category if category in LEVEL_COLORS else (source if source in LEVEL_COLORS else level)
        level_tag = level if level in LEVEL_COLORS else "INFO"

        self.text.config(state="normal")
        self.text.insert("end", f"[{ts}] ", "SYSTEM")
        self.text.insert("end", f"[{source[:3]}] ", prefix_tag)
        self.text.insert("end", f"{text}\n", level_tag)
        self.text.config(state="disabled")

        self._line_count += 1

        if not skip_status:
            self._trim_if_needed()
            if self._auto_scroll:
                self.text.see("end")
            self._update_status()

    def _trim_if_needed(self):
        if self._line_count > MAX_LOG_LINES:
            self.text.config(state="normal")
            self.text.delete("1.0", f"{TRIM_BATCH}.0")
            self.text.config(state="disabled")
            self._line_count -= TRIM_BATCH

    def _update_status(self):
        self.status_label.config(text=f"行数: {self._line_count}")


class ServerLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Bridge - 云端中台控制台 (Server Host)")
        self.root.geometry("900x600")
        self.root.configure(bg="#1E1E1E")
        self.root.minsize(700, 400)

        self.chrome_path = ""
        self.proc_server = None
        self.proc_client = None
        self.load_settings()

        header = tk.Frame(root, bg="#252526")
        header.pack(fill="x", padx=0, pady=0)

        tk.Label(header, text="☁️ AI Bridge Server Host", font=("微软雅黑", 13, "bold"),
                 bg="#252526", fg="#E0E0E0").pack(side="left", padx=15, pady=10)

        status_frame = tk.Frame(header, bg="#252526")
        status_frame.pack(side="right", padx=15, pady=10)

        self.server_status = tk.Label(status_frame, text="● Server 停止", font=("Arial", 9),
                                       bg="#252526", fg="#FF5555")
        self.server_status.pack(side="left", padx=8)

        self.client_status = tk.Label(status_frame, text="● Client 停止", font=("Arial", 9),
                                       bg="#252526", fg="#FF5555")
        self.client_status.pack(side="left", padx=8)

        btn_frame = tk.Frame(root, bg="#2D2D2D")
        btn_frame.pack(fill="x", padx=0, pady=0)

        btn_defs = [
            ("1. 启动 Chrome", "#4CAF50", self.launch_chrome),
            ("2. 启动 Server", "#FF9800", self.toggle_server),
            ("3. 本地 IDE", "#2196F3", self.run_local_client),
            ("4. 管理后台", "#9C27B0", self.run_admin_panel),
        ]
        for text, color, cmd in btn_defs:
            btn = tk.Button(btn_frame, text=text, bg=color, fg="white",
                            font=("Arial", 10, "bold"), command=cmd,
                            relief="flat", padx=10, pady=4, activebackground=color)
            btn.pack(side="left", expand=True, fill="x", padx=3, pady=6)
            if "Server" in text:
                self.btn_server = btn

        self.log_panel = SmartLogPanel(root, bg="#1E1E1E")
        self.log_panel.pack(fill="both", expand=True, padx=0, pady=0)

        self.log("Server Launcher 就绪 (v6.0 Smart Log)。", "SYSTEM")

    def log(self, text, source="SERVER"):
        self.log_panel.append_line(text, source)

    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self.chrome_path = json.load(f).get("chrome_path", "")
            except Exception as e:
                logger.warning(e)

    def launch_chrome(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sock.connect_ex((LOCAL_SERVER_HOST, CHROME_PORT)) == 0:
            self.log("提示: Chrome 已在运行", "SYSTEM")
            return
        if not self.chrome_path or not os.path.exists(self.chrome_path):
            self.chrome_path = filedialog.askopenfilename(filetypes=[("Exe", "*.exe")])
            if self.chrome_path:
                with open(CONFIG_FILE, "w") as f:
                    json.dump({"chrome_path": self.chrome_path}, f)
        if self.chrome_path:
            user_data = os.path.abspath("Chrome_143_Clean_Data")
            cmd = (
                f'start "" "{self.chrome_path}" '
                f'--remote-debugging-port={CHROME_PORT} '
                f'--user-data-dir="{user_data}" '
                f'--disable-backgrounding-occluded-windows '
                f'--disable-features=CalculateNativeWinOcclusion '
                f'"{UPSTREAM_AI_URL}/chat"'
            )
            os.system(cmd)
            self.log("Chrome 服务已启动", "SYSTEM")

    def kill_port_zombies(self, port):
        try:
            cmd_find = f"netstat -ano | findstr :{port}"
            result = subprocess.run(cmd_find, shell=True, capture_output=True, text=True)
            if not result.stdout:
                return
            pids = set()
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) > 4:
                    pids.add(parts[-1])

            client_pid = str(self.proc_client.pid) if self.proc_client and self.proc_client.poll() is None else None

            for pid in pids:
                if pid == "0":
                    continue
                if pid == client_pid:
                    continue
                self.log(f"🔫 [Zombie Hunter] 猎杀占用端口 {port} 的进程 PID={pid}...", "SYSTEM")
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            time.sleep(1.0)
        except Exception as e:
            self.log(f"⚠️ 猎杀失败: {e}", "ERROR")

    def toggle_server(self):
        if self.proc_server and self.proc_server.poll() is None:
            self.proc_server.terminate()
            self.proc_server = None
            self.btn_server.config(text="2. 启动 Server", bg="#FF9800")
            self.server_status.config(text="● Server 停止", fg="#FF5555")
            self.log("Server 已停止", "SYSTEM")
        else:
            self.start_process("server")

    def run_local_client(self):
        if self.proc_client and self.proc_client.poll() is None:
            self.log("本地 IDE 已在运行", "CLIENT")
            return
        self.ensure_local_config()
        self.start_process("client")

    def run_admin_panel(self):
        if self.proc_client and self.proc_client.poll() is None:
            self.log("客户端已运行，请先关闭", "ERROR")
            return
        self.ensure_local_config()
        self.start_process("client", extra_args=["--panel"])

    def ensure_local_config(self):
        try:
            from app.core.config import ConfigManager
            config = ConfigManager.load()
            if config.get("server_ip") != LOCAL_SERVER_HOST:
                config["server_ip"] = LOCAL_SERVER_HOST
                config["server_port"] = SERVER_PORT
                ConfigManager.save(config)
                self.log(f"已配置 IDE 连接本地 ({LOCAL_SERVER_HOST})", "SYSTEM")
        except Exception as e:
            logger.warning(e)

    def apply_updates(self):
        cache_dir = "update_cache"
        if not os.path.exists(cache_dir):
            return

        backup_dir = os.path.join("backup", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(backup_dir, exist_ok=True)
        self.log(f"📦 [Update] 备份旧文件至 {backup_dir}...", "UPDATE")

        req_changed = False
        launcher_updated = False

        try:
            count = 0
            for root, dirs, files in os.walk(cache_dir):
                for file in files:
                    src = os.path.join(root, file)
                    rel = os.path.relpath(src, cache_dir)
                    dest = os.path.join(os.getcwd(), rel)

                    if rel == "requirements.txt":
                        req_changed = True
                    if rel == "start_server.py":
                        launcher_updated = True

                    if os.path.exists(dest):
                        backup_path = os.path.join(backup_dir, rel)
                        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                        shutil.copy2(dest, backup_path)

                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
                    count += 1

            for i in range(3):
                try:
                    shutil.rmtree(cache_dir)
                    break
                except Exception:
                    time.sleep(0.5)

            if os.path.exists(cache_dir):
                self.log("⚠️ 缓存目录被占用，强制清理...", "SYSTEM")
                shutil.rmtree(cache_dir, ignore_errors=True)

            self.log(f"✅ [Update] 搬运完成 ({count} files)", "UPDATE")

            if req_changed:
                self.log("📦 [Pip] 正在安装依赖...", "INSTALL")
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], shell=True)
                self.log("✅ [Pip] 安装完成", "INSTALL")

            if launcher_updated:
                self.log("♻️ [System] 启动器自身已更新，准备重启...", "SYSTEM")
                time.sleep(1.0)
                os.execv(sys.executable, [sys.executable] + sys.argv)

        except Exception as e:
            self.log(f"❌ [Update] 更新异常: {e}", "ERROR")

    def start_process(self, ptype, extra_args=None):
        script = SERVER_SCRIPT if ptype == "server" else CLIENT_SCRIPT
        if not os.path.exists(script):
            self.log(f"错误: 找不到 {script}", "ERROR")
            return

        if ptype == "server":
            self.kill_port_zombies(SERVER_PORT)

        try:
            cmd = [sys.executable, "-u", script]
            if ptype == "client":
                cmd.append("--admin")
                if extra_args:
                    cmd.extend(extra_args)

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                startupinfo=si,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            source = "SERVER" if ptype == "server" else "CLIENT"
            if ptype == "server":
                self.proc_server = proc
                self.btn_server.config(text="⏹ 停止 Server", bg="#BF360C")
                self.server_status.config(text="● Server 运行中", fg="#66BB6A")
            else:
                self.proc_client = proc
                self.client_status.config(text="● Client 运行中", fg="#66BB6A")

            self.log(f"{ptype.upper()} 启动 (PID: {proc.pid})", source)
            threading.Thread(target=self.monitor, args=(proc, ptype), daemon=True).start()
        except Exception as e:
            self.log(f"启动失败: {e}", "ERROR")

    def monitor(self, proc, ptype):
        source = "SERVER" if ptype == "server" else "CLIENT"
        while True:
            try:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    continue

                text = line.strip()

                if ptype == "client" and (text.startswith("[测试日志]") or text.startswith("[TestLog]")):
                    continue

                self.root.after(0, self.log, text, source)

                if MAGIC_CMD_RESTART in text and ptype == "server":
                    self.root.after(0, self.log, "⚡ [Supervisor] 收到重启指令，强制终止 Server...", "UPDATE")
                    proc.kill()
                    proc.wait(timeout=5)
                    self.kill_port_zombies(SERVER_PORT)
                    self.root.after(500, self.apply_updates)
                    self.root.after(2000, lambda: self.start_process(ptype))
                    return

            except:
                break

        code = proc.poll()
        if ptype == "client":
            self.client_status.config(text="● Client 停止", fg="#FF5555")
            if code == 42:
                self.root.after(0, self.log, "♻️ Client 重启...", "UPDATE")
                self.root.after(1000, lambda: self.start_process(ptype))
            elif code == 101:
                self.root.after(0, self.log, "⚡ Client 升级...", "UPDATE")
                self.root.after(500, self.apply_updates)
                self.root.after(2000, lambda: self.start_process(ptype))
            else:
                self.root.after(0, self.log, f"Client 退出 (Code: {code})", "ERROR")
        else:
            self.server_status.config(text="● Server 停止", fg="#FF5555")
            self.root.after(0, lambda: self.btn_server.config(text="2. 启动 Server", bg="#FF9800"))
            self.root.after(0, self.log, f"Server 退出 (Code: {code})", "ERROR")


if __name__ == "__main__":
    root = tk.Tk()
    ServerLauncher(root)
    root.mainloop()
