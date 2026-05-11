import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
APP_ROOT = PROJECT_ROOT

# ============================================================
# 集中配置 — 修改以下值即可全局生效
# 如需覆盖，请在 .env 文件中设置对应环境变量
# ============================================================

# --- 上游 AI 网页地址（浏览器模式） ---
# 修改此值以适配你使用的 AI 网站（如 ChatGPT、Claude 等）
# 格式：https://your-ai-website.com
UPSTREAM_AI_URL = os.environ.get("UPSTREAM_AI_URL", "https://web-ai.example.com")

# --- API 默认配置 ---
# OpenAI 兼容 API 的默认 Base URL
DEFAULT_API_BASE_URL = os.environ.get("DEFAULT_API_BASE_URL", "https://api.openai.com/v1")
# 默认模型名称
DEFAULT_API_MODEL = os.environ.get("DEFAULT_API_MODEL", "gpt-4o")
DEFAULT_API_MODEL_LITE = os.environ.get("DEFAULT_API_MODEL_LITE", "gpt-4o-mini")

# --- 服务器配置 ---
# 服务器监听地址
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
# 服务器监听端口
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8765"))
# 本地回环地址（Client/RemoteWorker 连接 Server 用）
LOCAL_SERVER_HOST = os.environ.get("LOCAL_SERVER_HOST", "127.0.0.1")

# --- Chrome 浏览器配置 ---
# Chrome 远程调试端口
CHROME_PORT = int(os.environ.get("CHROME_PORT", "9527"))

# --- 代理配置 ---
# 默认代理地址（仅作 UI placeholder 使用）
DEFAULT_PROXY_URL = os.environ.get("DEFAULT_PROXY_URL", "http://127.0.0.1:7890")

# --- 认证配置 ---
DEFAULT_AUTH_CREDENTIALS = {
    "admin": {
        "password": os.environ.get("AUTH_ADMIN_PASSWORD", "admin"),
        "role": "developer",
        "display_name": "Administrator",
    },
}

# ============================================================
# 以下为内部常量，一般不需要修改
# ============================================================

OPENAI_COMPAT_MODELS = [
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
    "claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022",
    "deepseek-chat", "deepseek-reasoner",
]

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-1.5-pro",
]

MAX_WORKERS = 4
DEFAULT_SYSTEM_BUDGET = 8000
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_CONTEXT_WINDOW = 128000

UPDATE_EXIT_CODE = 101
RESTART_EXIT_CODE = 42

UI_COLORS = {
    "bg_primary": "#1E293B",
    "bg_secondary": "#374151",
    "bg_dark": "#1E1E1E",
    "bg_card": "#27272a",
    "border": "#3f3f46",
    "border_light": "#52525b",
    "text_primary": "#f4f4f5",
    "text_secondary": "#888",
    "text_muted": "#666",
    "text_hint": "#495057",
    "text_light_muted": "#868e96",
    "success": "#10B981",
    "success_bg": "rgba(16, 185, 129, 0.2)",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "info": "#4ade80",
    "sidebar_bg": "#18181b",
}

UI_SIZES = {
    "sidebar_width": 70,
    "sidebar_button": (60, 60),
    "sidebar_icon": (28, 28),
    "default_window": (1200, 800),
    "default_sidebar_width": 260,
}
