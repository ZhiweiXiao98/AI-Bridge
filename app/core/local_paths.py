"""本地应用的只读资源与用户数据分离；导入此模块不会启动服务。"""
from __future__ import annotations

import os
from pathlib import Path
import sys


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])).resolve()


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def local_home() -> Path:
    override = os.environ.get("AI_BRIDGE_LOCAL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "AI-Bridge-Local"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/AI-Bridge-Local"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ai-bridge-local"


def configure_local_paths() -> Path:
    """必须早于 ConfigManager、Worker 和 UI 的导入，源码运行也使用独立数据目录。"""
    home = local_home()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    # 新文件仅本机当前用户可读；不修改已有目录的共享/权限设置。
    if os.name != "nt":
        os.umask(0o077)
    os.environ["AI_BRIDGE_LOCAL_MODE"] = "1"
    os.environ["AI_BRIDGE_LOCAL_HOME"] = str(home)
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.chdir(home)
    from app.core import app_constants
    app_constants.APP_ROOT = str(home)
    app_constants.PROJECT_ROOT = str(home)
    app_constants.RESOURCE_ROOT = str(resource_root())
    return home
