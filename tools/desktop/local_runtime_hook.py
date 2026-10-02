"""冻结启动早期分离只读资源与可写状态，不从应用安装目录读取用户配置。"""
import os
from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    resource_root = Path(sys._MEIPASS).resolve()
    explicit = os.environ.get("AI_BRIDGE_LOCAL_HOME")
    if explicit:
        home = Path(explicit).expanduser().resolve()
    elif sys.platform == "win32":
        home = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "AI-Bridge-Local"
    elif sys.platform == "darwin":
        home = Path.home() / "Library/Application Support/AI-Bridge-Local"
    else:
        home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ai-bridge-local"
    home.mkdir(parents=True, exist_ok=True)
    os.environ["AI_BRIDGE_LOCAL_HOME"] = str(home)
    os.environ["AI_BRIDGE_RESOURCE_ROOT"] = str(resource_root)
    # 在任何 ConfigManager、日志、数据库模块 import 前生效。
    os.chdir(home)
    from app.core import app_constants
    app_constants.APP_ROOT = str(home)
    app_constants.PROJECT_ROOT = str(home)
    app_constants.RESOURCE_ROOT = str(resource_root)
