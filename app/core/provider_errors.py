"""Provider error classification for API mode."""

from __future__ import annotations

from typing import Any, Dict, Optional


ERROR_CATEGORY_CREDENTIALS = "credentials"
ERROR_CATEGORY_AUTH = "auth"
ERROR_CATEGORY_PERMISSION = "permission"
ERROR_CATEGORY_RATE_LIMIT = "rate_limit"
ERROR_CATEGORY_QUOTA = "quota"
ERROR_CATEGORY_TIMEOUT = "timeout"
ERROR_CATEGORY_CONNECTION = "connection"
ERROR_CATEGORY_TRANSIENT = "transient"
ERROR_CATEGORY_MODEL = "model"
ERROR_CATEGORY_BAD_REQUEST = "bad_request"
ERROR_CATEGORY_UNKNOWN = "unknown"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _status_code(error: Exception) -> Optional[int]:
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    return None


def _with_raw(user_message: str, raw_message: str) -> str:
    if not raw_message or raw_message in user_message:
        return user_message
    return f"{user_message}（原始错误：{raw_message[:240]}）"


def classify_provider_error(error: Exception) -> Dict[str, Any]:
    raw = _text(error)
    msg = _lower(raw)
    status = _status_code(error)

    category = ERROR_CATEGORY_UNKNOWN
    retryable = False
    user_message = "Provider 调用失败，详情请查看日志。"

    if "missing credentials" in msg or "api key" in msg and ("missing" in msg or "not set" in msg):
        category = ERROR_CATEGORY_CREDENTIALS
        user_message = "缺少 API Key 或认证信息，请在设置页补全后保存。"
    elif status == 401 or "invalid api key" in msg or "unauthorized" in msg or "authentication" in msg:
        category = ERROR_CATEGORY_AUTH
        user_message = "API Key 无效或认证失败，请检查密钥和 Provider。"
    elif status == 403 or "permission" in msg or "forbidden" in msg:
        category = ERROR_CATEGORY_PERMISSION
        user_message = "当前密钥没有访问该模型或接口的权限。"
    elif status == 429 or "rate limit" in msg or "too many requests" in msg:
        category = ERROR_CATEGORY_RATE_LIMIT
        retryable = True
        user_message = "Provider 限流，稍后重试或切换备用模型。"
    elif "insufficient_quota" in msg or "quota" in msg or "billing" in msg or "余额" in msg:
        category = ERROR_CATEGORY_QUOTA
        user_message = "额度不足或计费状态异常，请检查 Provider 账户。"
    elif "timeout" in msg or "timed out" in msg:
        category = ERROR_CATEGORY_TIMEOUT
        retryable = True
        user_message = "Provider 请求超时，可能是网络或服务端响应过慢。"
    elif "connection" in msg or "connecterror" in msg or "proxy" in msg or "network" in msg:
        category = ERROR_CATEGORY_CONNECTION
        retryable = True
        user_message = "网络、代理或 Provider 连接失败，请检查 Base URL 和代理配置。"
    elif status in (500, 502, 503, 504, 529) or "overloaded" in msg or "service unavailable" in msg:
        category = ERROR_CATEGORY_TRANSIENT
        retryable = True
        user_message = "Provider 服务临时不可用，稍后可重试或走 fallback。"
    elif status == 404 or "model" in msg and ("not found" in msg or "does not exist" in msg):
        category = ERROR_CATEGORY_MODEL
        user_message = "模型不存在或当前 Provider 不开放该模型，请重新选择模型。"
    elif status == 400 or "bad request" in msg or "unknown parameter" in msg or "unsupported parameter" in msg:
        category = ERROR_CATEGORY_BAD_REQUEST
        user_message = "请求参数不被 Provider 接受，请检查模型能力、工具调用或 reasoning 配置。"

    return {
        "category": category,
        "retryable": retryable,
        "status_code": status,
        "raw_message": raw,
        "user_message": _with_raw(user_message, raw),
    }


def is_retryable_provider_error(error: Exception) -> bool:
    return bool(classify_provider_error(error).get("retryable"))
