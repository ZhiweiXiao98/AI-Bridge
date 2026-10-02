import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
APP_ROOT = PROJECT_ROOT

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

MIMO_MODELS = [
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "mimo-v2-pro",
    "mimo-v2-omni",
    "mimo-v2-flash",
]

MIMO_DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"

PROVIDER_DISPLAY_NAMES = {
    "openai_compatible": "OpenAI 兼容",
    "mimo": "Xiaomi MiMo",
    "gemini": "Google Gemini",
    "web_ai": "网页 AI",
    "api": "OpenAI 兼容",
}

DEFAULT_AUTH_CREDENTIALS = {
    "admin": {"password": "admin", "role": "developer", "display_name": "超级管理员"},
    "vip01": {"password": "123456", "role": "vip", "display_name": "尊贵会员"},
    "user01": {"password": "123456", "role": "user", "display_name": "普通用户"},
}

CHROME_PORT = 9527
SERVER_PORT = 8765
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
    "sidebar_width": 54,
    "sidebar_button": (46, 46),
    "sidebar_icon": (22, 22),
    "default_window": (1360, 860),
    "default_sidebar_width": 180,
}
