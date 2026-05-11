import socket
import threading
import os
import sys
import shutil
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from app.core.config import ConfigManager
from app.core.app_constants import APP_ROOT, LOCAL_SERVER_HOST


class ConnectionManager:
    """
    负责管理 Chrome 浏览器与 Selenium WebDriver 的连接。
    提供端口检测、WebDriver 初始化和错误处理功能。
    """

    def __init__(self, port):
        """
        初始化连接管理器。
        :param port: Chrome 远程调试端口号 (例如 9527)。
        """
        self.port = port
        self.driver = None

    def is_port_open(self) -> bool:
        """
        检查指定的 TCP 端口是否处于开放状态（被监听）。
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            return s.connect_ex((LOCAL_SERVER_HOST, self.port)) == 0
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
            socket.setdefaulttimeout(15)
            print(f"🔧 [Selenium] ChromeDriver Service Path: {service.path}")
            container["driver"] = webdriver.Chrome(service=service, options=options)
            print("✅ [Selenium] WebDriver 创建成功！")
        except Exception as e:
            print(f"❌ [Selenium] WebDriver 创建崩溃: {e}")
            traceback.print_exc(file=sys.stderr)
            container["error"] = e
        finally:
            socket.setdefaulttimeout(None)
            print("🔧 [Selenium] WebDriver 初始化线程结束。")

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
        print(f"🔌 [ConnectionManager] 正在尝试连接 Chrome 远程调试端口 {self.port}...")

        if not self.is_port_open():
            print(f"❌ [ConnectionManager] 端口 {self.port} 未开放！请确保 Chrome 已启动并开启了远程调试。")
            return False, f"端口 {self.port} 未开放 (请点击 '启动 Chrome 服务')"

        print(f"✅ [ConnectionManager] 端口 {self.port} 是通的，正在初始化 WebDriver...")

        options = webdriver.ChromeOptions()
        options.add_experimental_option("debuggerAddress", f"{LOCAL_SERVER_HOST}:{self.port}")

        ok, service, service_msg = self._build_service()
        if not ok or service is None:
            return False, service_msg

        print(f"🔧 [ConnectionManager] {service_msg}")

        container = {}
        t = threading.Thread(target=self._init_thread, args=(service, options, container))
        t.daemon = True
        t.start()
        t.join(timeout=20)

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
        socket.setdefaulttimeout(None)
        print("✅ [ConnectionManager] WebDriver 已成功连接到 Chrome！")
        return True, f"已连接 (端口 {self.port})"
