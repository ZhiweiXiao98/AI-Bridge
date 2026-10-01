"""Model capability helpers for API mode.

The first productized slice is reasoning control shape.  Providers expose this
as different wire formats, so UI and runtime payloads should derive from one
resolver instead of hard-coding one universal control.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

REASONING_MODE_NONE = "none"
REASONING_MODE_SWITCH = "switch"
REASONING_MODE_EFFORT = "effort"

REASONING_EFFORTS = ("low", "medium", "high")

_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4")
_OPENAI_HOST_MARKERS = ("api.openai.com", "api.openai.azure.com")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_lower(value: Any) -> str:
    return _clean_text(value).lower()


def _normalize_efforts(values: Optional[Iterable[Any]]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        effort = _clean_lower(value)
        if effort in REASONING_EFFORTS and effort not in result:
            result.append(effort)
    return result


def _profile_reasoning(profile: dict) -> dict:
    payload = profile.get("reasoning") if isinstance(profile, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    effort = _clean_lower(payload.get("effort")) or "medium"
    if effort not in REASONING_EFFORTS:
        effort = "medium"
    return {
        "enabled": bool(payload.get("enabled", False)),
        "effort": effort,
    }


def _default_effort(profile: dict, efforts: list[str]) -> str:
    preferred = _profile_reasoning(profile).get("effort") or "medium"
    if preferred in efforts:
        return preferred
    if "medium" in efforts:
        return "medium"
    return efforts[0] if efforts else "medium"


def _reasoning_payload_has_signal(payload: dict) -> bool:
    return any(
        key in payload
        for key in ("mode", "supported", "supports_reasoning", "efforts", "levels")
    )


def _explicit_reasoning_payload(profile: dict, model: str) -> Optional[dict]:
    candidates = []
    capabilities = profile.get("model_capabilities") if isinstance(profile, dict) else None
    if isinstance(capabilities, dict):
        model_payload = capabilities.get(model)
        if isinstance(model_payload, dict):
            candidates.append(model_payload.get("reasoning") if isinstance(model_payload.get("reasoning"), dict) else model_payload)
        candidates.append(capabilities.get("reasoning") if isinstance(capabilities.get("reasoning"), dict) else capabilities)

    capabilities = profile.get("capabilities") if isinstance(profile, dict) else None
    if isinstance(capabilities, dict):
        candidates.append(capabilities.get("reasoning") if isinstance(capabilities.get("reasoning"), dict) else capabilities)

    for payload in candidates:
        if isinstance(payload, dict) and _reasoning_payload_has_signal(payload):
            return payload
    return None


def _is_mimo_profile(profile: dict, model: str) -> bool:
    provider = _clean_lower(profile.get("provider"))
    base_url = _clean_lower(profile.get("base_url"))
    return (
        provider == "mimo"
        or "xiaomimimo.com" in base_url
        or _clean_lower(model).startswith("mimo-")
    )


def _is_official_openai_profile(profile: dict) -> bool:
    provider = _clean_lower(profile.get("provider")) or "openai_compatible"
    base_url = _clean_lower(profile.get("base_url")) or "https://api.openai.com/v1"
    if provider not in ("openai_compatible", "api", "openai"):
        return False
    return any(marker in base_url for marker in _OPENAI_HOST_MARKERS)


def _is_openai_reasoning_model(profile: dict, model: str) -> bool:
    if not _is_official_openai_profile(profile):
        return False
    name = _clean_lower(model)
    return any(name == prefix or name.startswith(f"{prefix}-") for prefix in _OPENAI_REASONING_PREFIXES)


def _build_reasoning(
    *,
    mode: str,
    profile: dict,
    efforts: Optional[Iterable[Any]] = None,
    source: str,
    note: str = "",
) -> dict:
    mode = mode if mode in (REASONING_MODE_NONE, REASONING_MODE_SWITCH, REASONING_MODE_EFFORT) else REASONING_MODE_NONE
    effort_list = _normalize_efforts(efforts)
    if mode == REASONING_MODE_EFFORT and not effort_list:
        effort_list = list(REASONING_EFFORTS)
    if mode != REASONING_MODE_EFFORT:
        effort_list = []
    return {
        "supported": mode != REASONING_MODE_NONE,
        "mode": mode,
        "efforts": effort_list,
        "default_effort": _default_effort(profile, effort_list),
        "source": source,
        "note": note,
    }


def resolve_model_capability(profile: Optional[dict], model: Optional[str] = None) -> Dict[str, Any]:
    """Resolve API-mode capability facts used by UI and provider payloads."""
    profile = profile if isinstance(profile, dict) else {}
    model_name = _clean_text(model) or _clean_text(profile.get("model"))
    provider = _clean_lower(profile.get("provider")) or "openai_compatible"
    kind = _clean_lower(profile.get("kind")) or "api"

    if kind == "browser_stateless" or provider == "web_ai":
        reasoning = _build_reasoning(
            mode=REASONING_MODE_NONE,
            profile=profile,
            source="profile_kind",
            note="网页 Profile 不使用 API reasoning 参数",
        )
    else:
        explicit = _explicit_reasoning_payload(profile, model_name)
        if explicit is not None:
            supported = explicit.get("supported", explicit.get("supports_reasoning", True))
            mode = _clean_lower(explicit.get("mode"))
            if supported is False:
                mode = REASONING_MODE_NONE
            elif mode not in (REASONING_MODE_NONE, REASONING_MODE_SWITCH, REASONING_MODE_EFFORT):
                mode = REASONING_MODE_EFFORT if explicit.get("supports_reasoning") else REASONING_MODE_SWITCH
            reasoning = _build_reasoning(
                mode=mode,
                profile=profile,
                efforts=explicit.get("efforts") or explicit.get("levels"),
                source="profile_capabilities",
                note=_clean_text(explicit.get("note")),
            )
        elif _is_mimo_profile(profile, model_name):
            reasoning = _build_reasoning(
                mode=REASONING_MODE_SWITCH,
                profile=profile,
                source="provider_catalog",
                note="MiMo 使用 thinking enabled/disabled，不提供强度档位",
            )
        elif bool(profile.get("supports_reasoning", False)):
            if model_name and _is_official_openai_profile(profile) and not _is_openai_reasoning_model(profile, model_name):
                reasoning = _build_reasoning(
                    mode=REASONING_MODE_NONE,
                    profile=profile,
                    source="model_pattern",
                    note="官方 OpenAI 非 reasoning 模型不透传 reasoning_effort",
                )
            else:
                reasoning = _build_reasoning(
                    mode=REASONING_MODE_EFFORT,
                    profile=profile,
                    efforts=profile.get("reasoning_efforts") or REASONING_EFFORTS,
                    source="profile_flag",
                    note="Profile 显式声明支持 reasoning_effort",
                )
        elif _is_openai_reasoning_model(profile, model_name):
            reasoning = _build_reasoning(
                mode=REASONING_MODE_EFFORT,
                profile=profile,
                efforts=REASONING_EFFORTS,
                source="model_pattern",
                note="官方 OpenAI reasoning 模型前缀推断",
            )
        else:
            reasoning = _build_reasoning(
                mode=REASONING_MODE_NONE,
                profile=profile,
                source="default",
                note="当前模型没有可控 reasoning 参数声明",
            )

    tool_capability = profile.get("tool_capability") if isinstance(profile.get("tool_capability"), dict) else {}
    return {
        "provider": provider,
        "kind": kind,
        "model": model_name,
        "reasoning": reasoning,
        "tools": {
            "status": _clean_text(tool_capability.get("status")) or "unknown",
            "protocol": _clean_text(tool_capability.get("protocol")),
            "supported": bool(profile.get("supports_tools", False)),
        },
    }


def normalize_reasoning_for_capability(reasoning: Optional[dict], capability: Optional[dict]) -> dict:
    reasoning = reasoning if isinstance(reasoning, dict) else {}
    reasoning_cap = (capability or {}).get("reasoning") if isinstance(capability, dict) else {}
    reasoning_cap = reasoning_cap if isinstance(reasoning_cap, dict) else {}
    mode = _clean_lower(reasoning_cap.get("mode")) or REASONING_MODE_NONE
    enabled = bool(reasoning.get("enabled", False)) and mode != REASONING_MODE_NONE

    efforts = _normalize_efforts(reasoning_cap.get("efforts"))
    default_effort = _clean_lower(reasoning_cap.get("default_effort")) or "medium"
    effort = _clean_lower(reasoning.get("effort")) or default_effort
    if mode == REASONING_MODE_EFFORT and efforts:
        if effort not in efforts:
            effort = default_effort if default_effort in efforts else efforts[0]
    elif mode != REASONING_MODE_EFFORT:
        effort = "medium"
    elif effort not in REASONING_EFFORTS:
        effort = "medium"

    return {
        "enabled": enabled,
        "effort": effort,
    }


def provider_reasoning_kwargs(profile: Optional[dict]) -> dict:
    """Return ProviderConfig reasoning fields for an already-resolved profile."""
    profile = profile if isinstance(profile, dict) else {}
    capability = resolve_model_capability(profile)
    reasoning = normalize_reasoning_for_capability(profile.get("reasoning"), capability)
    mode = capability.get("reasoning", {}).get("mode")
    return {
        "supports_reasoning": mode == REASONING_MODE_EFFORT,
        "reasoning_enabled": bool(reasoning.get("enabled")),
        "reasoning_effort": reasoning.get("effort") or "medium",
    }


def reasoning_summary_text(reasoning: Optional[dict], capability: Optional[dict]) -> str:
    reasoning_cap = (capability or {}).get("reasoning") if isinstance(capability, dict) else {}
    mode = _clean_lower(reasoning_cap.get("mode")) or REASONING_MODE_NONE
    normalized = normalize_reasoning_for_capability(reasoning, capability)
    if mode == REASONING_MODE_NONE:
        return "无可控思考"
    if not normalized.get("enabled"):
        return "思考关"
    if mode == REASONING_MODE_SWITCH:
        return "思考开"
    effort = normalized.get("effort") or "medium"
    labels = {"low": "低", "medium": "中", "high": "高"}
    return f"思考{labels.get(effort, effort)}"


def reasoning_tooltip(capability: Optional[dict]) -> str:
    reasoning_cap = (capability or {}).get("reasoning") if isinstance(capability, dict) else {}
    mode = _clean_lower(reasoning_cap.get("mode")) or REASONING_MODE_NONE
    note = _clean_text(reasoning_cap.get("note"))
    if mode == REASONING_MODE_SWITCH:
        text = "当前模型支持思考开关，不支持强度档位。"
    elif mode == REASONING_MODE_EFFORT:
        efforts = ", ".join(reasoning_cap.get("efforts") or REASONING_EFFORTS)
        text = f"当前模型支持 reasoning_effort：{efforts}。"
    else:
        text = "当前模型未声明可控 reasoning 参数。"
    return f"{text}\n{note}" if note else text
