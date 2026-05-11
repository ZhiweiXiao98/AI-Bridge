"""全局状态管理 — 单例，所有 UI 组件共享"""

import os

_DEFAULT_PORT = int(os.environ.get("BRIDGE_SERVER_PORT", "8765"))


class AppState:
    def __init__(self):
        self.host: str = ""
        self.port: int = _DEFAULT_PORT
        self.token: str | None = None
        self.role: str = "user"
        self.username: str = ""
        self.display_name: str = ""
        self.device_id: str = ""
        self.connected: bool = False
        self.latency_ms: int = 0

        # 模式
        self.mode: str = "browser"  # "browser" | "api"

        # 消息
        self.messages: list = []
        self.sessions: list = []
        self.current_session_index: int = -1

        # AI 状态
        self.ai_state: str = "idle"  # idle | thinking | streaming
        self.status_text: str = ""

        # 流式
        self.streaming_content: str = ""
        self.streaming_active: bool = False
        self.current_stream_id: str = ""

        # 登录记忆
        self.saved_host: str = ""
        self.saved_port: int = _DEFAULT_PORT
        self.saved_username: str = ""
