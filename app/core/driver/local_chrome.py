"""Owned desktop Chrome session: isolated profile, ephemeral loopback debugger."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from app.core.local_paths import local_home, resource_path
from app.core.python_runtime import python_subprocess_environment


class BrowserSetupError(RuntimeError):
    pass


def browser_url(config):
    value = str(config.get("browser_start_url", os.environ.get("UPSTREAM_AI_URL", "")) or "").strip()
    return validate_browser_url(value)


def validate_browser_url(value):
    value = str(value or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise BrowserSetupError("目标网页地址格式无效，请输入完整的 http/https 地址") from exc
    if not value or value == "about:blank" or parsed.hostname == "web-ai.example.com":
        return "about:blank"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or origin(value) is None:
        raise BrowserSetupError("目标网页地址必须是没有内嵌用户名或密码的 http/https 地址")
    return value


def origin(url):
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def find_chrome(config):
    configured = str(config.get("chrome_binary") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir() and path.suffix == ".app":
            path = path / "Contents/MacOS" / path.stem
        if not path.is_absolute() or not path.is_file():
            raise BrowserSetupError("Chrome 路径无效，请在“连接设置”中选择已安装的 Chrome 可执行文件")
        return str(path)
    if sys.platform == "darwin":
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    elif sys.platform == "win32":
        candidates = [Path(os.environ[key]) / "Google/Chrome/Application/chrome.exe"
                      for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(key)]
    else:
        candidates = [Path(path) for path in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                                             "/usr/bin/chromium", "/usr/bin/chromium-browser")]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise BrowserSetupError("未找到 Google Chrome。请从 https://www.google.com/chrome/ 安装，或在“连接设置”中指定 Chrome 路径。客户端不会自动下载浏览器。")


def executable_version(path):
    try:
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True,
                                timeout=5, env=python_subprocess_environment())
        match = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\b", result.stdout or result.stderr or "")
        if result.returncode == 0 and match:
            return match.group(1)
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise BrowserSetupError("无法读取浏览器或驱动版本，请检查所选可执行文件与当前系统架构是否匹配")


class LocalChromeSession:
    def __init__(self, config):
        self.config = config
        self.profile = local_home() / "browser-profile"
        self.process = None
        self.port = None
        self.binary = None
        self.version = ""
        self.debugger_id = ""
        self._closed = False
        self._lock = threading.Lock()
        self._manager_process = None
        self._descendants = {}
        self._owned_processes = []
        self._monitor_stop = threading.Event()
        self._monitor_thread = None

    def _track_process(self, process):
        with self._lock:
            self._owned_processes.append(process)
            if self._monitor_thread is None:
                self._monitor_thread = threading.Thread(target=self._monitor_owned_tree, daemon=True,
                                                        name="local-chrome-ownership")
                self._monitor_thread.start()

    def _capture_descendants(self):
        import psutil
        with self._lock:
            processes = list(self._owned_processes)
        for process in processes:
            if process.poll() is None:
                try:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        # Keep a psutil identity (PID + creation time), never a
                        # process-name match, even after the parent exits.
                        key = (child.pid, child.create_time())
                        with self._lock:
                            self._descendants[key] = child
                except (psutil.Error, OSError):
                    pass

    def _monitor_owned_tree(self):
        while not self._monitor_stop.is_set():
            self._capture_descendants()
            self._monitor_stop.wait(0.1)

    def start(self, url=None, *, headless=False, timeout=12.0):
        if self._closed:
            raise BrowserSetupError("浏览器会话正在关闭")
        if self.process is not None and self.process.poll() is None and self.port:
            return self.port
        port_file = self.profile / "DevToolsActivePort"
        process = self.process
        if process is None or process.poll() is not None:
            self.binary = find_chrome(self.config)
            target = browser_url(self.config) if url is None else validate_browser_url(url)
            self.profile.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.profile.is_symlink():
                raise BrowserSetupError("专用浏览器资料目录不能链接到其他浏览器的用户资料，请更换本地数据目录")
            port_file.unlink(missing_ok=True)
            command = [self.binary, f"--user-data-dir={self.profile}", "--remote-debugging-address=127.0.0.1",
                       "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check", "--disable-sync"]
            if headless:
                command += ["--headless=new", "--disable-gpu", "--window-size=1280,900"]
            command.append(target)
            # Never disable Chrome's sandbox or use a user's regular browser profile.
            log_dir = local_home() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                if self._closed:
                    raise BrowserSetupError("浏览器会话正在关闭")
                with (log_dir / "chrome-startup.log").open("ab") as log:
                    self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                    stderr=log, env=python_subprocess_environment())
                process = self.process
            self._track_process(process)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._closed:
                raise BrowserSetupError("浏览器会话正在关闭")
            if process.poll() is not None:
                raise BrowserSetupError("Chrome 未能启动专用窗口。请关闭此前的 AI-Bridge 专用 Chrome 窗口后重试；也请检查系统是否允许启动 Chrome。未接管其他浏览器。")
            try:
                lines = port_file.read_text().splitlines()
                port = int(lines[0])
                browser_id = lines[1]
                if not 1 <= port <= 65535 or not browser_id.startswith("/devtools/browser/"):
                    raise ValueError("invalid debugger metadata")
                opener = build_opener(ProxyHandler({}))
                with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as response:
                    metadata = json.load(response)
                endpoint = urlsplit(metadata.get("webSocketDebuggerUrl", ""))
                if endpoint.hostname not in {"127.0.0.1", "localhost"} or endpoint.port != port or endpoint.path != browser_id:
                    raise ValueError("unexpected debugger endpoint")
                self.port, self.debugger_id = port, browser_id
                actual_version = str(metadata.get("Browser", "")).split("/")[-1]
                if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", actual_version):
                    self.version = actual_version
                else:
                    raise ValueError("missing actual browser version")
                return port
            except (OSError, ValueError, IndexError):
                time.sleep(0.1)
        raise BrowserSetupError("专用 Chrome 调试连接启动超时。请检查 Chrome 是否被系统安全提示阻止，然后重新连接。")

    def resolve_driver(self):
        configured = str(self.config.get("chromedriver_path") or "").strip()
        name = "chromedriver.exe" if sys.platform == "win32" else "chromedriver"
        if configured:
            driver = Path(configured).expanduser()
            if not driver.is_absolute() or not driver.is_file():
                raise BrowserSetupError("ChromeDriver 路径无效，请在“连接设置”中选择匹配版本的驱动")
        else:
            bundled = resource_path("runtime", "chromedriver", name)
            driver = bundled if bundled.is_file() else self._manager_driver()
        version = executable_version(driver)
        if version.split(".")[0] != self.version.split(".")[0]:
            raise BrowserSetupError(f"Chrome {self.version} 与 ChromeDriver {version} 不匹配。请选择匹配驱动，或允许下载官方匹配驱动后重新连接。")
        return str(driver)

    def _manager_driver(self):
        from selenium.webdriver.common import selenium_manager
        platform = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
        manager = Path(selenium_manager.__file__).parent / platform / ("selenium-manager.exe" if sys.platform == "win32" else "selenium-manager")
        if not manager.is_file():
            raise BrowserSetupError("安装包缺少官方 Selenium Manager，请重新安装或指定 ChromeDriver")
        cache = local_home() / "browser-runtime" / "selenium-cache"
        cache.mkdir(parents=True, exist_ok=True)
        allow_download = self.config.get("browser_allow_driver_download") is True
        command = [str(manager), "--browser", "chrome", "--browser-path", self.binary,
                   "--cache-path", str(cache), "--avoid-browser-download", "--avoid-stats",
                   "--skip-driver-in-path", "--skip-browser-in-path", "--timeout", "45", "--output", "json"]
        if not allow_download:
            command.append("--offline")
        env = {key: value for key, value in python_subprocess_environment().items() if not key.startswith("SE_")}
        with self._lock:
            if self._closed:
                raise BrowserSetupError("浏览器会话正在关闭")
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            self._manager_process = process
        self._track_process(process)
        try:
            output, _ = process.communicate(timeout=60 if allow_download else 8)
            result = json.loads(output).get("result", {})
            driver = Path(result.get("driver_path") or "")
            if process.returncode or not driver.is_file() or not driver.resolve().is_relative_to(cache.resolve()):
                raise ValueError("no trusted matching driver")
            return driver
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)
            if not allow_download:
                raise BrowserSetupError("尚未准备匹配的 ChromeDriver。请在“连接设置”中选择驱动，或勾选“允许从官方来源下载匹配驱动”后重新连接；尚未联网下载。") from exc
            raise BrowserSetupError("官方匹配驱动准备失败。请检查网络后重试，或从 Chrome for Testing 官方网站获取匹配驱动并指定路径。") from exc
        finally:
            with self._lock:
                if self._manager_process is process:
                    self._manager_process = None

    def shutdown(self, timeout=3.0):
        import psutil
        self._closed = True
        self._monitor_stop.set()
        deadline = time.monotonic() + max(0.0, timeout)
        self._capture_descendants()
        with self._lock:
            processes = list(self._owned_processes)
            for process in (self._manager_process, self.process):
                if process is not None and process not in processes:
                    processes.append(process)
            descendants = list(self._descendants.values())
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    # Retry via the normal bounded shutdown flow. The browser
                    # keeps a live owner until its profile has been flushed.
                    pass
        living = []
        for child in descendants:
            try:
                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    child.terminate()
                    living.append(child)
            except psutil.NoSuchProcess:
                pass
        if living:
            _, living = psutil.wait_procs(living, timeout=max(0.0, deadline - time.monotonic()))
        if self._monitor_thread and self._monitor_thread is not threading.current_thread():
            self._monitor_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        still_running = []
        for child in living:
            try:
                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    still_running.append(child)
            except psutil.NoSuchProcess:
                pass
        return all(process.poll() is not None for process in processes) and not still_running
