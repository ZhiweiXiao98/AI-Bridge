import logging
# filename: start_client.py
# -*- coding: utf-8 -*-
import tkinter as tk
import subprocess
import sys
import threading
import os
import shutil
import datetime
import time
from app.core.logging import get_logger

logger = get_logger("start_client", side="core")

REMOTE_SCRIPT = "boot_remote.py"
RESTART_CODE = 42
UPDATE_CODE = 101

MAX_LOG_LINES = 6000
TRIM_BATCH = 1500

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
        sources = ["ALL", "CLIENT", "SERVER", "SYSTEM", "INSTALL", "UPDATE"]
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

    def _on_search_focus_in(self, event):
        if self.search_var.get() == "搜索...":
            self.search_entry.delete(0, "end")

    def _on_search_focus_out(self, event):
        if not self.search_var.get().strip():
            self.search_entry.insert(0, "搜索...")

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

    def append_line(self, text, source="CLIENT"):
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


class ClientLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Bridge - 远程客户端 (Remote Client)")
        self.root.geometry("700x500")
        self.root.configure(bg="#2D2D2D")
        self.root.minsize(500, 350)

        self.proc = None
        self.is_updating = False

        header = tk.Frame(root, bg="#252526")
        header.pack(fill="x", padx=0, pady=0)

        tk.Label(header, text="💻 AI Bridge Remote Client", font=("微软雅黑", 13, "bold"),
                 bg="#252526", fg="#E0E0E0").pack(side="left", padx=15, pady=10)

        self.client_status = tk.Label(header, text="● 停止", font=("Arial", 9),
                                       bg="#252526", fg="#FF5555")
        self.client_status.pack(side="right", padx=15, pady=10)

        btn_frame = tk.Frame(root, bg="#2D2D2D")
        btn_frame.pack(fill="x", padx=0, pady=0)

        self.btn_run = tk.Button(btn_frame, text="🚀 连接云端", bg="#2196F3", fg="white",
                                  font=("Arial", 10, "bold"), command=self.run_client,
                                  relief="flat", padx=10, pady=4, activebackground="#2196F3")
        self.btn_run.pack(side="left", expand=True, fill="x", padx=3, pady=6)

        self.log_panel = SmartLogPanel(root, bg="#1E1E1E")
        self.log_panel.pack(fill="both", expand=True, padx=0, pady=0)

        self.log("客户端启动器就绪 (v4.0 Smart Log)。")

        self.root.after(1000, self.run_client)

    def log(self, text):
        self.log_panel.append_line(text)

    def run_client(self):
        if self.proc and self.proc.poll() is None:
            return
        if self.is_updating:
            return

        cache_dir = os.path.join("export", "update_cache")
        if os.path.exists(cache_dir):
            self.log("🔍 检测到遗留的更新包，正在强制应用...")
            self.perform_update_sequence()
            return

        if not os.path.exists(REMOTE_SCRIPT):
            self.log(f"❌ 错误: 找不到 {REMOTE_SCRIPT}")
            return

        try:
            cmd = [sys.executable, "-u", REMOTE_SCRIPT]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.proc = subprocess.Popen(
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

            self.btn_run.config(state="disabled", text="运行中...")
            self.client_status.config(text="● 运行中", fg="#66BB6A")
            self.log(f"客户端进程启动 (PID: {self.proc.pid})")
            threading.Thread(target=self.monitor, args=(self.proc,), daemon=True).start()
        except Exception as e:
            self.log(f"启动失败: {e}")

    def perform_update_sequence(self):
        self.is_updating = True
        cache_dir = os.path.join("export", "update_cache")

        if not os.path.exists(cache_dir):
            self.is_updating = False
            self.root.after(1000, self.run_client)
            return

        try:
            count = 0
            for root, dirs, files in os.walk(cache_dir):
                for file in files:
                    src = os.path.join(root, file)
                    rel = os.path.relpath(src, cache_dir)
                    dest = os.path.join(os.getcwd(), rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
                    count += 1

            self.log(f"✅ 成功覆盖 {count} 个文件")

            for i in range(3):
                try:
                    shutil.rmtree(cache_dir)
                    break
                except Exception:
                    time.sleep(0.5)

            if os.path.exists(cache_dir):
                self.log("⚠️ 缓存目录占用，尝试强制删除...")
                shutil.rmtree(cache_dir, ignore_errors=True)

        except Exception as e:
            self.log(f"❌ 更新过程出错 (文件被占用?): {e}")

        finally:
            self.is_updating = False
            self.log("♻️ 准备重启客户端...")
            self.root.after(2000, self.run_client)

    def monitor(self, proc):
        while True:
            try:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                if line:
                    self.root.after(0, self.log, line.strip())
            except:
                break

        code = proc.poll()
        self.root.after(0, lambda: self.btn_run.config(state="normal", text="🚀 连接云端"))
        self.client_status.config(text="● 停止", fg="#FF5555")

        if code == RESTART_CODE:
            self.root.after(0, self.log, "♻️ 收到重启信号")
            self.root.after(1000, self.run_client)

        elif code == UPDATE_CODE:
            self.root.after(0, self.log, "⚡ [OTA] 收到升级请求 (Code 101)")
            self.root.after(500, self.perform_update_sequence)

        elif code == 3221226505:
            self.root.after(0, self.log, "⚠️ 客户端崩溃 (Code 0xC0000409)")
            self.root.after(1000, self.run_client)

        else:
            self.root.after(0, self.log, f"客户端异常退出 (Code: {code})")


if __name__ == "__main__":
    root = tk.Tk()
    ClientLauncher(root)
    root.mainloop()
