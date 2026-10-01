from app.core.api_source import APISource
from app.core.api_mode_config import APIModeConfigManager
from app.core.provider_errors import (
    ERROR_CATEGORY_BAD_REQUEST,
    ERROR_CATEGORY_CREDENTIALS,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_TIMEOUT,
    classify_provider_error,
)


class StatusError(RuntimeError):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def test_provider_error_classifies_missing_credentials():
    info = classify_provider_error(RuntimeError("Missing credentials"))

    assert info["category"] == ERROR_CATEGORY_CREDENTIALS
    assert info["retryable"] is False
    assert "缺少 API Key" in info["user_message"]
    assert "Missing credentials" in info["user_message"]


def test_provider_error_classifies_rate_limit_as_retryable():
    info = classify_provider_error(StatusError("rate limit exceeded", 429))

    assert info["category"] == ERROR_CATEGORY_RATE_LIMIT
    assert info["retryable"] is True
    assert info["status_code"] == 429


def test_provider_error_classifies_timeout_as_retryable():
    info = classify_provider_error(TimeoutError("request timed out"))

    assert info["category"] == ERROR_CATEGORY_TIMEOUT
    assert info["retryable"] is True


def test_provider_error_classifies_unsupported_parameter_as_bad_request():
    info = classify_provider_error(StatusError("Unknown parameter: reasoning_effort", 400))

    assert info["category"] == ERROR_CATEGORY_BAD_REQUEST
    assert info["retryable"] is False
    assert "请求参数" in info["user_message"]


def test_api_source_exposes_retryable_error_wrapper():
    source = APISource.__new__(APISource)

    assert source.is_retryable_error(StatusError("too many requests", 429)) is True
    assert source.is_retryable_error(StatusError("Unknown parameter: tools", 400)) is False


def test_api_source_fallback_event_carries_classified_error(monkeypatch):
    class Store:
        active_id = "conv_1"

    class PrimaryProvider:
        def chat(self, messages):
            raise StatusError("Unknown parameter: reasoning_effort", 400)

    class BackupProvider:
        def chat(self, messages):
            return "ok"

    source = APISource.__new__(APISource)
    source._initialized = True
    source.conv_store = Store()
    source.llm_provider = PrimaryProvider()
    source.last_fallback_event = None
    source.provider_init_error = None
    source.current_runtime_profile_key = "primary"
    source._ensure_init = lambda: None
    source._apply_runtime_for_conversation = lambda conv_id=None: ("primary", {})
    source._resolve_profile_key = lambda *args, **kwargs: "primary"
    source._get_fallback_candidates = lambda: ["backup"]

    def _apply_profile_runtime(profile_key, persist_active=True, profile_override=None, config=None):
        source.current_runtime_profile_key = profile_key
        source.llm_provider = BackupProvider()

    source._apply_profile_runtime = _apply_profile_runtime
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: {}))

    assert source._chat_with_fallback_sync([{"role": "user", "content": "hi"}]) == "ok"
    assert source.last_fallback_event["from"] == "primary"
    assert source.last_fallback_event["to"] == "backup"
    assert source.last_fallback_event["category"] == ERROR_CATEGORY_BAD_REQUEST
    assert "请求参数" in source.last_fallback_event["user_message"]
