from types import SimpleNamespace

from app.core.api_mode_config import (
    APIModeConfigManager,
    TOOL_CAPABILITY_SUPPORTED,
    TOOL_CAPABILITY_UNSUPPORTED,
    TOOL_PROTOCOL_MARKDOWN_ONLY,
    TOOL_PROTOCOL_NATIVE,
)
from app.core.app_constants import MIMO_MODELS
from app.core.api_source import APISource
from app.core.llm_provider import APIProvider, ProviderConfig


class _FakeConversationStore:
    active_id = "conv_1"

    def get_model_usage(self, conv_id):
        return None


class _FakeProvider:
    def __init__(self, result, models_result=None):
        self.result = result
        self.models_result = models_result or {"ok": True, "models": ["model-a"], "reason": ""}
        self.called = False

    def probe_tool_support(self):
        self.called = True
        return dict(self.result)

    def list_models(self):
        return dict(self.models_result)


def test_api_source_probe_skips_browser_stateless(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "browser_web",
        "profiles": {
            "browser_web": {
                "kind": "browser_stateless",
                "provider": "web_ai",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "browser_web"},
    })
    saved = {}
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: saved.update(data)))

    provider = _FakeProvider({"status": TOOL_CAPABILITY_SUPPORTED, "protocol": TOOL_PROTOCOL_NATIVE})
    source = APISource()
    source._initialized = True
    source.config_dict = cfg
    source.conv_store = _FakeConversationStore()
    source.llm_provider = provider

    result = source.probe_tool_support()

    assert provider.called is False
    assert result["status"] == TOOL_CAPABILITY_UNSUPPORTED
    assert result["protocol"] == TOOL_PROTOCOL_MARKDOWN_ONLY
    assert saved["profiles"]["browser_web"]["supports_tools"] is False


def test_api_source_probe_writes_supported_capability(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "api",
        "profiles": {
            "api": {
                "kind": "api",
                "provider": "openai_compatible",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "api"},
    })
    saved = {}
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: saved.update(data)))

    source = APISource()
    source._initialized = True
    source.config_dict = cfg
    source.conv_store = _FakeConversationStore()
    source.llm_provider = _FakeProvider({"status": TOOL_CAPABILITY_SUPPORTED, "protocol": TOOL_PROTOCOL_NATIVE})

    result = source.probe_tool_support()

    assert result["status"] == TOOL_CAPABILITY_SUPPORTED
    assert saved["profiles"]["api"]["supports_tools"] is True
    assert saved["profiles"]["api"]["tool_capability"]["protocol"] == TOOL_PROTOCOL_NATIVE


def test_api_source_probe_available_models_uses_active_provider(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "api",
        "profiles": {
            "api": {
                "kind": "api",
                "provider": "openai_compatible",
                "model": "current-model",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "api"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))

    source = APISource()
    source._initialized = True
    source.config_dict = cfg
    source.conv_store = _FakeConversationStore()
    source.llm_provider = _FakeProvider(
        {"status": TOOL_CAPABILITY_SUPPORTED, "protocol": TOOL_PROTOCOL_NATIVE},
        models_result={"ok": True, "models": ["model-a", "model-b"], "reason": ""},
    )

    result = source.probe_available_models()

    assert result["ok"] is True
    assert result["models"] == ["model-a", "model-b"]
    assert result["profile_key"] == "api"
    assert result["current_model"] == "current-model"


def test_api_source_runtime_profile_applies_conversation_overrides(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "api",
        "profiles": {
            "api": {
                "kind": "api",
                "provider": "openai_compatible",
                "base_url": "https://api.vendor.test/v1",
                "model": "profile-model",
                "supports_reasoning": True,
                "reasoning": {"enabled": False, "effort": "medium"},
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "api"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))

    class StoreWithOverride:
        active_id = "conv_1"

        def get_model_usage(self, conv_id):
            return {
                "type": "profile",
                "ref": "api",
                "model": "conversation-model",
                "reasoning": {"enabled": True, "effort": "high"},
            }

    source = APISource()
    source._initialized = True
    source.config_dict = cfg
    source.conv_store = StoreWithOverride()
    source.llm_provider = None
    created = {}
    source._create_llm_provider = lambda payload, profile_key="": created.update({"payload": payload, "profile_key": profile_key}) or object()

    profile = source.get_runtime_profile()
    source._apply_runtime_for_conversation("conv_1")

    assert profile["_profile_key"] == "api"
    assert profile["model"] == "conversation-model"
    assert profile["reasoning"] == {"enabled": True, "effort": "high"}
    assert created["profile_key"] == "api"
    assert created["payload"]["api"]["model"] == "conversation-model"
    assert created["payload"]["api"]["reasoning_enabled"] is True
    assert created["payload"]["api"]["reasoning_effort"] == "high"


def test_api_source_probe_available_models_falls_back_to_mimo_catalog(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "mimo",
        "profiles": {
            "mimo": {
                "kind": "api",
                "provider": "mimo",
                "base_url": "https://api.xiaomimimo.com/v1",
                "model": "mimo-v2.5-pro",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "mimo"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))

    source = APISource()
    source._initialized = True
    source.config_dict = cfg
    source.conv_store = _FakeConversationStore()
    source.llm_provider = _FakeProvider(
        {"status": TOOL_CAPABILITY_SUPPORTED, "protocol": TOOL_PROTOCOL_NATIVE},
        models_result={"ok": False, "models": [], "reason": "404 not found", "endpoint_ok": False},
    )

    result = source.probe_available_models()

    assert result["ok"] is True
    assert result["models"] == MIMO_MODELS
    assert result["source"] == "provider_catalog"
    assert result["catalog_name"] == "xiaomi_mimo_official"
    assert result["endpoint_ok"] is False


def test_api_source_probe_available_models_filters_mimo_audio_models(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "mimo",
        "profiles": {
            "mimo": {
                "kind": "api",
                "provider": "mimo",
                "base_url": "https://api.xiaomimimo.com/v1",
                "model": "mimo-v2.5-pro",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "mimo"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))

    source = APISource()
    source._initialized = True
    source.config_dict = cfg
    source.conv_store = _FakeConversationStore()
    source.llm_provider = _FakeProvider(
        {"status": TOOL_CAPABILITY_SUPPORTED, "protocol": TOOL_PROTOCOL_NATIVE},
        models_result={
            "ok": True,
            "models": ["mimo-v2.5-pro", "mimo-v2.5-asr", "mimo-v2.5-tts", "mimo-v2-flash"],
            "reason": "",
            "source": "models_endpoint",
            "endpoint_ok": True,
        },
    )

    result = source.probe_available_models()

    assert result["ok"] is True
    assert result["models"] == ["mimo-v2.5-pro", "mimo-v2-flash"]
    assert result["source"] == "models_endpoint_filtered"
    assert result["raw_model_count"] == 4


def test_api_provider_probe_detects_tool_calls():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(model="test-model")
    message = SimpleNamespace(tool_calls=[SimpleNamespace(id="call_1")])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )

    result = provider.probe_tool_support()

    assert result["status"] == TOOL_CAPABILITY_SUPPORTED
    assert result["protocol"] == TOOL_PROTOCOL_NATIVE


def test_api_provider_only_sends_reasoning_effort_when_supported():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(
        model="test-model",
        supports_reasoning=True,
        reasoning_enabled=True,
        reasoning_effort="high",
    )

    kwargs = provider._chat_create_kwargs([{"role": "user", "content": "hi"}])

    assert kwargs["reasoning_effort"] == "high"

    provider.config.supports_reasoning = False
    kwargs = provider._chat_create_kwargs([{"role": "user", "content": "hi"}])

    assert "reasoning_effort" not in kwargs


def test_api_provider_mimo_tool_probe_uses_official_chat_params():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(
        provider="mimo",
        api_key="sk-test",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-pro",
    )
    captured = []
    message = SimpleNamespace(tool_calls=[SimpleNamespace(id="call_1")])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def _create(**kwargs):
        captured.append(kwargs)
        return response

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )

    result = provider.probe_tool_support()

    assert result["status"] == TOOL_CAPABILITY_SUPPORTED
    assert captured[0]["max_completion_tokens"] == 64
    assert "max_tokens" not in captured[0]
    assert captured[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured[0]["tool_choice"] == {"type": "function", "function": {"name": "probe_tool"}}


def test_api_provider_probe_retries_when_forced_tool_choice_is_unsupported():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(model="test-model")
    calls = []
    message = SimpleNamespace(tool_calls=[SimpleNamespace(id="call_1")])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def _create(**kwargs):
        calls.append(kwargs)
        if isinstance(kwargs.get("tool_choice"), dict):
            raise RuntimeError("Unknown parameter: tool_choice")
        return response

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )

    result = provider.probe_tool_support()

    assert result["status"] == TOOL_CAPABILITY_SUPPORTED
    assert result["protocol"] == TOOL_PROTOCOL_NATIVE
    assert result["probe_attempt"] == "auto"
    assert len(calls) == 2


def test_api_provider_probe_marks_unsupported_parameter_error():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(model="test-model")

    def _raise(**kwargs):
        raise RuntimeError("Unknown parameter: tools")

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_raise))
    )

    result = provider.probe_tool_support()

    assert result["status"] == TOOL_CAPABILITY_UNSUPPORTED


def test_api_provider_list_models_returns_model_ids():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(model="test-model")
    response = SimpleNamespace(data=[
        SimpleNamespace(id="model-b"),
        SimpleNamespace(id="model-a"),
        SimpleNamespace(id="model-a"),
    ])
    provider._client = SimpleNamespace(models=SimpleNamespace(list=lambda: response))

    result = provider.list_models()

    assert result == {
        "ok": True,
        "models": ["model-a", "model-b"],
        "reason": "",
        "source": "models_endpoint",
        "endpoint_ok": True,
    }
