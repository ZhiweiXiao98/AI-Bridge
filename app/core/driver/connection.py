import socket
import threading
import time
import os
import sys
import shutil
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from app.core.config import ConfigManager
from app.core.app_constants import APP_ROOT, LOCAL_SERVER_HOST
from app.core.python_runtime import python_subprocess_environment
from app.core.driver.local_chrome import LocalChromeSession, BrowserSetupError


class TrustedDriverService(Service):
    """An explicit local driver path cannot be replaced by SE_CHROMEDRIVER."""
    def env_path(self):
        return None


class ConnectionManager:
    """
    负责管理 Chrome 浏览器与 Selenium WebDriver 的连接。
    提供端口检测、WebDriver 初始化和错误处理功能。
    """

    def __init__(self, port, config=None):
        """
        初始化连接管理器。
        :param port: Chrome 远程调试端口号 (例如 9527)。
        """
        self.port = port
        self.driver = None
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self._service = None
        self._init_worker = None
        self._owned_services = []
        self._init_workers = []
        self._shutdown_worker = None
        self.config = dict(config if config is not None else ConfigManager.load())
        self.local_desktop = os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1"
        self.local_session = LocalChromeSession(self.config) if self.local_desktop else None
        self.status_callback = None

    def configure(self, config):
        config = dict(config)
        self.config.clear()
        self.config.update(config)

    def start_browser(self, url=None, *, headless=False):
        if not self.local_session:
            return False, "远程服务模式请在服务端启动 Chrome"
        try:
            self.port = self.local_session.start(url, headless=headless)
            return True, "已启动 AI-Bridge 专用 Chrome（仅本机调试连接）"
        except (BrowserSetupError, OSError) as error:
            return False, str(error)

    def is_port_open(self) -> bool:
        """
        检查指定的 TCP 端口是否处于开放状态（被监听）。
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            if self._closed:
                return False
            host = "127.0.0.1" if self.local_desktop else LOCAL_SERVER_HOST
            return s.connect_ex((host, self.port)) == 0
        except Exception:
            return False
        finally:
            s.close()

    def _init_thread(self, service: Service, options: webdriver.ChromeOptions, container: dict):
        """
        在单独线程中初始化 Selenium WebDriver，避免主线程长时间阻塞。
        """
        print("🔧 [Selenium] WebDriver 初始化线程启动...")
        try:
            if self._closed:
                return
            if not self.local_desktop:
                socket.setdefaulttimeout(15)
            print(f"🔧 [Selenium] ChromeDriver Service Path: {service.path}")
            container["driver"] = webdriver.Chrome(service=service, options=options)
            if self.local_desktop:
                container["driver"].command_executor._client_config.timeout = 5
            print("✅ [Selenium] WebDriver 创建成功！")
        except Exception as e:
            print(f"❌ [Selenium] WebDriver 创建崩溃: {e}")
            traceback.print_exc(file=sys.stderr)
            container["error"] = e
        finally:
            if not self.local_desktop:
                socket.setdefaulttimeout(None)
            if self._closed:
                # This Service was created by this connection manager. Do not
                # call driver.quit(): the attached Chrome belongs to the user.
                service.stop()
            print("🔧 [Selenium] WebDriver 初始化线程结束。")

    def shutdown(self, timeout=3.0):
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lifecycle_lock:
            self._closed = True
            services = list(self._owned_services)
            if self._service is not None and self._service not in services:
                services.append(self._service)
            if services and self._shutdown_worker is None:
                def stop_services():
                    for service in services:
                        try:
                            service.stop()
                        except Exception:
                            traceback.print_exc(file=sys.stderr)
                self._shutdown_worker = threading.Thread(target=stop_services, daemon=True,
                                                        name="chromedriver-cleanup")
                self._shutdown_worker.start()
            threads = [self._shutdown_worker, *self._init_workers]
            if self._init_worker is not None and self._init_worker not in threads:
                threads.append(self._init_worker)
        for thread in threads:
            if thread and thread is not threading.current_thread():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        stopped = not any(thread and thread.is_alive() for thread in threads)
        if self.local_session:
            stopped = self.local_session.shutdown(max(0.0, deadline - time.monotonic())) and stopped
        if stopped:
            self.driver = None
        return stopped

    def _candidate_driver_paths(self):
        """
        收集本地可能存在的 chromedriver 路径。
        优先顺序：
        1. config.json 中的 chromedriver_path
        2. 当前项目内常见路径
        3. 系统 PATH 中的 chromedriver
        """
        cfg = ConfigManager.load()
        configured = str(cfg.get("chromedriver_path", "") or "").strip()

        if self.local_desktop:
            from app.core.local_paths import resource_path
            name = "chromedriver.exe" if sys.platform == "win32" else "chromedriver"
            return ([configured] if configured else []) + [str(resource_path("runtime", "chromedriver", name))]

        candidates = []
        if configured:
            candidates.append(configured)

        local_candidates = [
            "chromedriver.exe",
            "chromedriver",
            os.path.join(APP_ROOT, "drivers", "chromedriver.exe"),
            os.path.join(APP_ROOT, "drivers", "chromedriver"),
            os.path.join(APP_ROOT, "tools", "chromedriver.exe"),
            os.path.join(APP_ROOT, "tools", "chromedriver"),
        ]
        candidates.extend(local_candidates)

        path_driver = shutil.which("chromedriver")
        if path_driver:
            candidates.append(path_driver)

        normalized = []
        seen = set()
        for p in candidates:
            full = os.path.abspath(p)
            if full.lower() in seen:
                continue
            seen.add(full.lower())
            normalized.append(full)
        return normalized

    def _resolve_local_driver_path(self):
        """
        尝试解析本地可用的 chromedriver。
        """
        for path in self._candidate_driver_paths():
            if os.path.isfile(path):
                print(f"✅ [ConnectionManager] 发现本地 ChromeDriver: {path}")
                return path
        return None

    def _build_service(self):
        """
        创建 ChromeDriver Service。
        策略：
        1. 优先使用本地 driver
        2. 本地没有时，尝试 webdriver_manager 联网获取
        3. 联网失败时返回可读错误，而不是直接抛异常打爆线程
        """
        if self.local_session:
            try:
                if self.status_callback:
                    self.status_callback("正在准备匹配的官方 ChromeDriver…" if self.config.get("browser_allow_driver_download") is True
                                         else "正在检查本地 ChromeDriver（不会下载）…")
                driver = self.local_session.resolve_driver()
                return True, TrustedDriverService(driver, env=python_subprocess_environment()), "本地匹配 ChromeDriver 已就绪"
            except (BrowserSetupError, OSError) as error:
                return False, None, str(error)
        local_driver = self._resolve_local_driver_path()
        if local_driver:
            return True, Service(local_driver), f"使用本地 ChromeDriver: {local_driver}"

        print("⚠️ [ConnectionManager] 未找到本地 ChromeDriver，尝试通过 webdriver_manager 获取...")
        try:
            downloaded = ChromeDriverManager().install()
            print(f"✅ [ConnectionManager] webdriver_manager 获取成功: {downloaded}")
            return True, Service(downloaded), f"通过 webdriver_manager 获取 ChromeDriver: {downloaded}"
        except Exception as e:
            print(f"❌ [ConnectionManager] webdriver_manager 获取失败: {e}")
            traceback.print_exc(file=sys.stderr)
            msg = (
                "无法获取 ChromeDriver。已检查本地路径但未发现可用驱动，"
                "且 webdriver_manager 联网获取失败。\n"
                "请检查网络/代理环境，或在 config.json 中设置 chromedriver_path。"
            )
            return False, None, msg

    def connect(self) -> tuple[bool, str]:
        """
        尝试连接到 Chrome 浏览器并初始化 WebDriver。
        """
        if self._closed:
            return False, "浏览器连接正在关闭"
        if self.driver is not None:
            try:
                self.driver.window_handles
                return True, "Chrome 调试连接已就绪"
            except Exception:
                self.driver = None
        if self.local_session:
            ok, message = self.start_browser(headless=self.config.get("browser_headless") is True)
            if not ok:
                return False, message
        print(f"🔌 [ConnectionManager] 正在尝试连接 Chrome 远程调试端口 {self.port}...")

        if not self.is_port_open():
            print(f"❌ [ConnectionManager] 端口 {self.port} 未开放！请确保 Chrome 已启动并开启了远程调试。")
            return False, f"端口 {self.port} 未开放 (请点击 '启动 Chrome 服务')"

        print(f"✅ [ConnectionManager] 端口 {self.port} 是通的，正在初始化 WebDriver...")

        options = webdriver.ChromeOptions()
        host = "127.0.0.1" if self.local_session else LOCAL_SERVER_HOST
        options.add_experimental_option("debuggerAddress", f"{host}:{self.port}")
        if self.local_session:
            options.binary_location = self.local_session.binary
            options.ignore_local_proxy_environment_variables()

        ok, service, service_msg = self._build_service()
        if not ok or service is None:
            return False, service_msg

        print(f"🔧 [ConnectionManager] {service_msg}")

        container = {}
        with self._lifecycle_lock:
            if self._closed:
                return False, "浏览器连接正在关闭"
            self._service = service
            self._owned_services.append(service)
            t = threading.Thread(target=self._init_thread, args=(service, options, container), daemon=True)
            self._init_worker = t
            self._init_workers.append(t)
            t.start()
        t.join(timeout=20)

        if self._closed:
            return False, "浏览器连接正在关闭"

        if t.is_alive():
            print("❌ [ConnectionManager] WebDriver 初始化严重超时！")
            try:
                import selenium
                print(f"ℹ️ Selenium 版本: {selenium.__version__}")
            except ImportError:
                print("ℹ️ 未能检测到 Selenium 版本。")
            return False, "连接超时 (WebDriver 响应过慢，可能被卡死、版本不匹配，或 ChromeDriver 不可用)"

        if "error" in container:
            err = container["error"]
            print("❌ [ConnectionManager] WebDriver 初始化失败，错误详情请看上方日志。")
            return False, f"WebDriver 初始化失败: {err}"

        self.driver = container["driver"]
        if not self.local_desktop:
            socket.setdefaulttimeout(None)
        print("✅ [ConnectionManager] WebDriver 已成功连接到 Chrome！")
        return True, f"已连接 (端口 {self.port})"
