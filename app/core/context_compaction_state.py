from typing import Any, Dict


DEFAULT_COMPACT_BUFFER = 24000
DEFAULT_COMPACT_FAILURE_THRESHOLD = 3


def create_default_compact_state() -> Dict[str, Any]:
    return {
        "enabled": True,
        "compact_buffer": DEFAULT_COMPACT_BUFFER,
        "compact_count": 0,
        "last_compacted_at": 0.0,
        "last_trigger": "",
        "consecutive_failures": 0,
        "failure_threshold": DEFAULT_COMPACT_FAILURE_THRESHOLD,
        "last_error": "",
        "last_summary_preview": "",
        "recent_preserved_count": 0,
        "disabled_until_manual_retry": False,
    }


def normalize_compact_state(data: Any) -> Dict[str, Any]:
    defaults = create_default_compact_state()
    source = dict(data) if isinstance(data, dict) else {}
    state = dict(defaults)
    state.update(source)

    legacy_failure_count = source.get("failure_count", 0)
    legacy_last_compacted_count = source.get("last_compacted_count", 0)

    state["enabled"] = bool(state.get("enabled", True))
    state["compact_buffer"] = int(state.get("compact_buffer", DEFAULT_COMPACT_BUFFER) or DEFAULT_COMPACT_BUFFER)
    if "compact_count" in source:
        state["compact_count"] = int(source.get("compact_count", 0) or 0)
    else:
        state["compact_count"] = int(legacy_last_compacted_count or 0)
    state["last_compacted_at"] = float(state.get("last_compacted_at", 0.0) or 0.0)
    state["last_trigger"] = str(state.get("last_trigger", "") or "")
    if "consecutive_failures" in source:
        state["consecutive_failures"] = int(source.get("consecutive_failures", 0) or 0)
    else:
        state["consecutive_failures"] = int(legacy_failure_count or 0)
    state["failure_threshold"] = int(state.get("failure_threshold", DEFAULT_COMPACT_FAILURE_THRESHOLD) or DEFAULT_COMPACT_FAILURE_THRESHOLD)
    state["last_error"] = str(state.get("last_error", "") or "")
    state["last_summary_preview"] = str(state.get("last_summary_preview", "") or "")
    state["recent_preserved_count"] = int(state.get("recent_preserved_count", 0) or 0)
    state["disabled_until_manual_retry"] = bool(state.get("disabled_until_manual_retry", False))
    state.pop("failure_count", None)
    state.pop("last_compacted_count", None)
    return state


def can_attempt_compact(state: Dict[str, Any]) -> bool:
    normalized = normalize_compact_state(state)
    if not normalized.get("enabled", True):
        return False
    if normalized.get("disabled_until_manual_retry", False):
        return False
    return normalized.get("consecutive_failures", 0) < normalized.get("failure_threshold", DEFAULT_COMPACT_FAILURE_THRESHOLD)


def mark_compact_success(state: Dict[str, Any], summary_preview: str, compacted_count: int, preserved_count: int, now_ts: float, trigger: str = "") -> Dict[str, Any]:
    normalized = normalize_compact_state(state)
    normalized["consecutive_failures"] = 0
    normalized["last_error"] = ""
    normalized["last_compacted_at"] = float(now_ts)
    normalized["compact_count"] = int(normalized.get("compact_count", 0)) + 1
    normalized["last_trigger"] = str(trigger or normalized.get("last_trigger", "") or "")
    normalized["last_summary_preview"] = str(summary_preview or "")[:500]
    normalized["recent_preserved_count"] = int(preserved_count)
    normalized["disabled_until_manual_retry"] = False
    return normalized


def mark_compact_failure(state: Dict[str, Any], error_text: str) -> Dict[str, Any]:
    normalized = normalize_compact_state(state)
    normalized["consecutive_failures"] = int(normalized.get("consecutive_failures", 0)) + 1
    normalized["last_error"] = str(error_text or "")[:500]
    if normalized["consecutive_failures"] >= normalized.get("failure_threshold", DEFAULT_COMPACT_FAILURE_THRESHOLD):
        normalized["disabled_until_manual_retry"] = True
    return normalized
