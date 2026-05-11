import logging
# filename: boot_remote.py
import sys


def _configure_stdio():
    for stream_name in ("stdout", "stderr"):
        try:
            stream = getattr(sys, stream_name, None)
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_configure_stdio()

import os
import traceback
import datetime
import requests 
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, QTranslator, QLibraryInfo, QLocale
from app.ui.main_window import MainWindow
from app.ui.login_window import LoginWindow
from app.core.remote_worker import RemoteWorker
from app.core.config import ConfigManager
from app.core.app_constants import DEFAULT_AUTH_CREDENTIALS, SERVER_PORT, LOCAL_SERVER_HOST
from app.core.utils.text_utils import is_test_log
logger = logging.getLogger("boot_remote")



def _is_test_log(text):
    return is_test_log(text)

def exception_hook(exctype, value, tb):
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    try:
        print(error_msg)
    except UnicodeEncodeError:
        # 处理 Unicode 编码错误
        print(error_msg.encode('utf-8', 'replace').decode('utf-8'))
    try:
        QMessageBox.critical(None, "Remote Client Crash", f"Error:\n{value}")
    except: pass
    sys.__excepthook__(exctype, value, tb)

def install_translator(app):
    """尝试加载 PyQt 的中文翻译文件"""
    translator = QTranslator()
    # 尝试加载 qtbase_zh_CN.qm
    # 通常位于 site-packages/PySide6/Qt6/translations
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    
    # 优先加载 qt_zh_CN (包含了 qtbase, qtmultimedia 等的集合)
    if translator.load("qt_zh_CN", path):
        app.installTranslator(translator)
        try:
            print(f"✅ 已加载系统翻译: qt_zh_CN from {path}")
        except UnicodeEncodeError:
            print(f"[OK] 已加载系统翻译: qt_zh_CN from {path}")
    elif translator.load("qtbase_zh_CN", path):
        app.installTranslator(translator)
        try:
            print(f"✅ 已加载基础翻译: qtbase_zh_CN from {path}")
        except UnicodeEncodeError:
            print(f"[OK] 已加载基础翻译: qtbase_zh_CN from {path}")
    else:
        try:
            print(f"⚠️ 未找到中文翻译文件 ({path})，部分原生控件可能显示英文。")
        except UnicodeEncodeError:
            print(f"[WARN] 未找到中文翻译文件 ({path})，部分原生控件可能显示英文。")

def main():
    sys.excepthook = exception_hook
    app = QApplication(sys.argv)
    app.setOrganizationName("AIBridge")
    app.setOrganizationDomain("ai.bridge.com")
    app.setApplicationName("RemoteClient")
    
    # [New] 加载翻译
    install_translator(app)
    
    # 检查是否以 admin 模式启动
    if "--admin" in sys.argv or "--panel" in sys.argv:
        try:
            print("🚀 正在以管理模式自动登录...")
        except UnicodeEncodeError:
            print("[INFO] 正在以管理模式自动登录...")
        try:
            url = f"http://{LOCAL_SERVER_HOST}:{SERVER_PORT}/api/login"
            resp = requests.post(
                url, json={"username": "admin", "password": DEFAULT_AUTH_CREDENTIALS["admin"]["password"]},                 
                timeout=10, proxies={"http": None, "https": None} 
            )
            if resp.status_code == 200:
                data = resp.json()
                profile = {"username": data["username"], "role": data["role"], "token": data["token"], "server_ip": LOCAL_SERVER_HOST}
                start_main_window(profile, jump_to_console="--panel" in sys.argv)
                sys.exit(app.exec())
            else:
                QMessageBox.critical(None, "错误", f"自动登录失败: {resp.text}")
                return
        except Exception as e:
            QMessageBox.critical(None, "错误", f"无法连接本地服务器: {e}")
            return

    login_win = LoginWindow()
    login_win.login_success.connect(lambda p: start_main_window(p, jump_to_console=False))
    login_win.show()
    sys.exit(app.exec())

def start_main_window(user_profile, jump_to_console=False):
    try:
        print(f"✅ 登录成功: {user_profile['username']}")
    except UnicodeEncodeError:
        print(f"[OK] 登录成功: {user_profile['username']}")
    
    config = ConfigManager.load()
    config["server_ip"] = user_profile["server_ip"]
    ConfigManager.save(config) 
    
    remote_worker = RemoteWorker(token=user_profile["token"])
    
    main_win = MainWindow(remote_worker, user_profile)
    main_win.show()
    
    if jump_to_console:
        main_win.switch_to_page(5)
        if hasattr(main_win, "console_page"):
            main_win.console_page.tabs.setCurrentIndex(1)
            
    QTimer.singleShot(3000, lambda: check_update_silently(remote_worker))
    
    global _main_window_ref 
    _main_window_ref = main_win

def check_update_silently(worker):
    try:
        print("🔄 [AutoUpdate] 正在检查服务端代码版本...")
    except UnicodeEncodeError:
        print("[AutoUpdate] 正在检查服务端代码版本...")
    if hasattr(worker, 'request_latest_code'):
        worker.request_latest_code()

if __name__ == "__main__":
    main()
