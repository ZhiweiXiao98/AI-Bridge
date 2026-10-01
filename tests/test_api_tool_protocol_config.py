from app.core.api_mode_config import (
    APIModeConfigManager,
    TOOL_CAPABILITY_SUPPORTED,
    TOOL_PROTOCOL_MARKDOWN,
    TOOL_PROTOCOL_MARKDOWN_ONLY,
    TOOL_PROTOCOL_NATIVE,
)


def test_browser_stateless_profile_uses_markdown_only_protocol():
    cfg = APIModeConfigManager._normalize({
        "profiles": {
            "web": {
                "kind": "browser_stateless",
                "provider": "web_ai",
                "supports_tools": True,
            }
        }
    })
    profile = cfg["profiles"]["web"]

    assert profile["supports_tools"] is False
    assert profile["tool_capability"]["protocol"] == TOOL_PROTOCOL_MARKDOWN_ONLY
    assert APIModeConfigManager.resolve_tool_protocol(profile) == TOOL_PROTOCOL_MARKDOWN_ONLY


def test_supported_http_profile_uses_native_protocol():
    cfg = APIModeConfigManager._normalize({
        "profiles": {
            "api": {
                "kind": "api",
                "provider": "openai_compatible",
                "tool_capability": {"status": TOOL_CAPABILITY_SUPPORTED},
            }
        }
    })
    profile = cfg["profiles"]["api"]

    assert APIModeConfigManager.resolve_tool_protocol(profile) == TOOL_PROTOCOL_NATIVE


def test_unknown_http_profile_defaults_to_markdown_fallback():
    cfg = APIModeConfigManager._normalize({
        "profiles": {
            "api": {
                "kind": "api",
                "provider": "openai_compatible",
                "supports_tools": False,
            }
        }
    })
    profile = cfg["profiles"]["api"]

    assert APIModeConfigManager.resolve_tool_protocol(profile) == TOOL_PROTOCOL_MARKDOWN
