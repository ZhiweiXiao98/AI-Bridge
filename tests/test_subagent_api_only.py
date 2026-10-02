from app.core.subagent.subagent_config import SubagentConfig


def _subagent_config():
    return object.__new__(SubagentConfig)


def test_subagent_rejects_browser_stateless_profile():
    cfg = _subagent_config()
    api_config = {
        "profiles": {
            "browser_web": {
                "kind": "browser_stateless",
                "provider": "web_ai",
                "model": "web",
            }
        }
    }

    resolved = cfg._resolve_profile(api_config, "profile", "browser_web")

    assert resolved == {}


def test_subagent_chain_uses_first_api_profile_and_skips_browser_profile():
    cfg = _subagent_config()
    api_config = {
        "profiles": {
            "browser_web": {
                "kind": "browser_stateless",
                "provider": "web_ai",
                "model": "web",
            },
            "api_lite": {
                "kind": "api",
                "provider": "openai_compatible",
                "api_key": "sk-test",
                "model": "lite",
            },
        },
        "fallback_chains": {
            "mixed": {
                "profiles": ["browser_web", "api_lite"],
            }
        },
    }

    resolved = cfg._resolve_profile(api_config, "chain", "mixed")

    assert resolved["model"] == "lite"
    assert resolved["kind"] == "api"

