from app.core.model_capabilities import (
    REASONING_MODE_EFFORT,
    REASONING_MODE_NONE,
    REASONING_MODE_SWITCH,
    normalize_reasoning_for_capability,
    provider_reasoning_kwargs,
    resolve_model_capability,
)


def test_mimo_reasoning_is_switch_only():
    profile = {
        "kind": "api",
        "provider": "mimo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
        "reasoning": {"enabled": True, "effort": "high"},
    }

    capability = resolve_model_capability(profile)
    normalized = normalize_reasoning_for_capability(profile["reasoning"], capability)
    kwargs = provider_reasoning_kwargs(profile)

    assert capability["reasoning"]["mode"] == REASONING_MODE_SWITCH
    assert capability["reasoning"]["efforts"] == []
    assert normalized == {"enabled": True, "effort": "medium"}
    assert kwargs == {
        "supports_reasoning": False,
        "reasoning_enabled": True,
        "reasoning_effort": "medium",
    }


def test_explicit_supports_reasoning_uses_effort_levels():
    profile = {
        "kind": "api",
        "provider": "openai_compatible",
        "base_url": "https://api.vendor.test/v1",
        "model": "custom-reasoning-model",
        "supports_reasoning": True,
        "reasoning": {"enabled": True, "effort": "high"},
    }

    capability = resolve_model_capability(profile)
    kwargs = provider_reasoning_kwargs(profile)

    assert capability["reasoning"]["mode"] == REASONING_MODE_EFFORT
    assert capability["reasoning"]["efforts"] == ["low", "medium", "high"]
    assert kwargs["supports_reasoning"] is True
    assert kwargs["reasoning_enabled"] is True
    assert kwargs["reasoning_effort"] == "high"


def test_browser_profile_has_no_api_reasoning_controls():
    profile = {
        "kind": "browser_stateless",
        "provider": "web_ai",
        "model": "",
        "reasoning": {"enabled": True, "effort": "high"},
    }

    capability = resolve_model_capability(profile)
    kwargs = provider_reasoning_kwargs(profile)

    assert capability["reasoning"]["mode"] == REASONING_MODE_NONE
    assert kwargs == {
        "supports_reasoning": False,
        "reasoning_enabled": False,
        "reasoning_effort": "medium",
    }


def test_official_openai_non_reasoning_model_ignores_profile_reasoning_flag():
    profile = {
        "kind": "api",
        "provider": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "supports_reasoning": True,
        "reasoning": {"enabled": True, "effort": "high"},
    }

    capability = resolve_model_capability(profile)
    kwargs = provider_reasoning_kwargs(profile)

    assert capability["reasoning"]["mode"] == REASONING_MODE_NONE
    assert kwargs == {
        "supports_reasoning": False,
        "reasoning_enabled": False,
        "reasoning_effort": "medium",
    }


def test_profile_capability_override_wins_over_defaults():
    profile = {
        "kind": "api",
        "provider": "openai_compatible",
        "model": "vendor-model",
        "capabilities": {
            "reasoning": {
                "mode": "effort",
                "efforts": ["low", "high"],
            }
        },
        "reasoning": {"enabled": True, "effort": "medium"},
    }

    capability = resolve_model_capability(profile)
    normalized = normalize_reasoning_for_capability(profile["reasoning"], capability)

    assert capability["reasoning"]["mode"] == REASONING_MODE_EFFORT
    assert capability["reasoning"]["efforts"] == ["low", "high"]
    assert normalized == {"enabled": True, "effort": "low"}
