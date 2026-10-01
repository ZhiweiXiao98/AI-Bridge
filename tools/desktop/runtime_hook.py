"""Set writable per-user state before the frozen client's imports run."""
import os
from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    if os.environ.get("AI_BRIDGE_CLIENT_HOME"):
        home = Path(os.environ["AI_BRIDGE_CLIENT_HOME"]).expanduser().resolve()
    elif sys.platform == "win32":
        home = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "AI-Bridge"
    elif sys.platform == "darwin":
        home = Path.home() / "Library/Application Support/AI-Bridge"
    else:
        home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ai-bridge"
    home.mkdir(parents=True, exist_ok=True)
    os.chdir(home)
    from app.core import app_constants
    app_constants.APP_ROOT = str(home)
    app_constants.PROJECT_ROOT = str(home)
