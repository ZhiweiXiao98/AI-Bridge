from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Literal


DeliveryMode = Literal["broadcast", "targeted"]


def _single_payload(*args: Any) -> Any:
    if not args:
        return {}
    if len(args) == 1:
        return args[0]
    return args


def _context_health_payload(total: Any, gap: Any) -> dict[str, Any]:
    return {"total": total, "gap": gap}


def _state_sync_payload(max_idx: Any, snap_idx: Any) -> dict[str, Any]:
    return {"max_idx": max_idx, "snap_idx": snap_idx}


def _one_arg(payload: Any) -> tuple[Any, ...]:
    return (payload,)


def _no_args(payload: Any) -> tuple[Any, ...]:
    return ()


def _context_health_args(payload: Any) -> tuple[int, int]:
    if not isinstance(payload, dict):
        payload = {}
    return (int(payload.get("total", 0) or 0), int(payload.get("gap", 0) or 0))


def _state_sync_args(payload: Any) -> tuple[int, int]:
    if not isinstance(payload, dict):
        payload = {}
    return (int(payload.get("max_idx", 0) or 0), int(payload.get("snap_idx", 0) or 0))


def _latency_args(payload: Any) -> tuple[int, ...]:
    return (int(time.time() * 1000) - int(payload),)


@dataclass(frozen=True)
class ServerSignalRoute:
    signal_name: str
    message_type: str
    delivery: DeliveryMode = "broadcast"
    payload_builder: Callable[..., Any] = _single_payload
    target_group: str | None = None


@dataclass(frozen=True)
class RemoteMessageRoute:
    message_type: str
    signal_name: str
    args_builder: Callable[[Any], tuple[Any, ...]] = _one_arg


SERVER_SIGNAL_ROUTES: tuple[ServerSignalRoute, ...] = (
    ServerSignalRoute("snapshot_ready_signal", "snapshot_ready"),
    ServerSignalRoute("status_signal", "status"),
    ServerSignalRoute("restart_needed_signal", "restart_needed"),
    ServerSignalRoute("batch_complete_signal", "batch_complete"),
    ServerSignalRoute("git_detail_signal", "git_detail"),
    ServerSignalRoute("git_workbench_signal", "git_workbench", delivery="targeted"),
    ServerSignalRoute("git_diff_preview_signal", "git_diff_preview", delivery="targeted"),
    ServerSignalRoute("git_config_signal", "git_config", delivery="targeted"),
    ServerSignalRoute("context_health_signal", "context_health", payload_builder=_context_health_payload),
    ServerSignalRoute("state_sync_signal", "state_sync", payload_builder=_state_sync_payload),
    ServerSignalRoute("update_list_signal", "update_list"),
    ServerSignalRoute("ai_state_signal", "ai_state"),
    ServerSignalRoute("occupancy_signal", "occupancy"),
    ServerSignalRoute("file_preview_signal", "file_preview", delivery="targeted"),
    ServerSignalRoute("test_result_signal", "test_result", delivery="targeted"),
    ServerSignalRoute("skills_data_signal", "skills_data", delivery="targeted"),
    ServerSignalRoute("system_prompt_signal", "system_prompt", delivery="targeted"),
    ServerSignalRoute("context_status_signal", "context_status"),
    ServerSignalRoute("context_workspace_signal", "context_workspace", delivery="targeted"),
    ServerSignalRoute("context_snapshot_signal", "context_snapshot", delivery="targeted"),
    ServerSignalRoute("api_conversations_signal", "api_conversations", delivery="targeted"),
    ServerSignalRoute("api_messages_deleted_signal", "api_messages_deleted", delivery="targeted"),
    ServerSignalRoute("api_manual_compact_signal", "api_manual_compact", delivery="targeted"),
    ServerSignalRoute("mode_changed_signal", "mode_changed"),
    ServerSignalRoute("subagent_suggestion_signal", "subagent_suggestion"),
    ServerSignalRoute("daemon_suggestion_signal", "daemon_suggestion"),
    ServerSignalRoute("queue_monitor_signal", "queue_monitor"),
    ServerSignalRoute("knowledge_health_signal", "knowledge_health"),
    ServerSignalRoute("api_stream_chunk_signal", "api_stream_chunk", delivery="targeted"),
    ServerSignalRoute("api_stream_status_signal", "api_stream_status", delivery="targeted"),
    ServerSignalRoute("api_round_state_signal", "api_round_state"),
    ServerSignalRoute("pending_message_consumed_signal", "pending_consumed", payload_builder=_single_payload),
)


REMOTE_MESSAGE_ROUTES: dict[str, RemoteMessageRoute] = {
    "status": RemoteMessageRoute("status", "status_signal"),
    "git_detail": RemoteMessageRoute("git_detail", "git_detail_signal"),
    "context_health": RemoteMessageRoute("context_health", "context_health_signal", _context_health_args),
    "sessions": RemoteMessageRoute("sessions", "sessions_signal"),
    "state_sync": RemoteMessageRoute("state_sync", "state_sync_signal", _state_sync_args),
    "restart_needed": RemoteMessageRoute("restart_needed", "restart_needed_signal"),
    "snapshot_ready": RemoteMessageRoute("snapshot_ready", "snapshot_ready_signal"),
    "batch_complete": RemoteMessageRoute("batch_complete", "batch_complete_signal", _no_args),
    "update_list": RemoteMessageRoute("update_list", "update_list_signal"),
    "server_log": RemoteMessageRoute("server_log", "server_log_signal", lambda p: ((p or {}).get("text", "") if isinstance(p, dict) else "" ,)),
    "git_workbench": RemoteMessageRoute("git_workbench", "git_workbench_signal"),
    "git_diff_preview": RemoteMessageRoute("git_diff_preview", "git_diff_preview_signal"),
    "git_config": RemoteMessageRoute("git_config", "git_config_signal"),
    "ai_state": RemoteMessageRoute("ai_state", "ai_state_signal"),
    "occupancy": RemoteMessageRoute("occupancy", "occupancy_signal"),
    "file_preview": RemoteMessageRoute("file_preview", "file_preview_signal"),
    "test_result": RemoteMessageRoute("test_result", "test_result_signal"),
    "queue_monitor": RemoteMessageRoute("queue_monitor", "queue_monitor_signal"),
    "knowledge_health": RemoteMessageRoute("knowledge_health", "knowledge_health_signal"),
    "subagent_suggestion": RemoteMessageRoute("subagent_suggestion", "subagent_suggestion_signal"),
    "daemon_suggestion": RemoteMessageRoute("daemon_suggestion", "daemon_suggestion_signal"),
    "skills_data": RemoteMessageRoute("skills_data", "skills_data_signal"),
    "system_prompt": RemoteMessageRoute("system_prompt", "system_prompt_signal"),
    "skills_list": RemoteMessageRoute("skills_list", "skills_list_signal"),
    "skills_toggle_result": RemoteMessageRoute("skills_toggle_result", "skills_toggle_result_signal"),
    "skills_prompt": RemoteMessageRoute("skills_prompt", "skills_prompt_signal"),
    "context_status": RemoteMessageRoute("context_status", "context_status_signal"),
    "context_workspace": RemoteMessageRoute("context_workspace", "context_workspace_signal"),
    "context_snapshot": RemoteMessageRoute("context_snapshot", "context_snapshot_signal"),
    "api_conversations": RemoteMessageRoute("api_conversations", "api_conversations_signal"),
    "api_messages_deleted": RemoteMessageRoute("api_messages_deleted", "api_messages_deleted_signal"),
    "api_manual_compact": RemoteMessageRoute("api_manual_compact", "api_manual_compact_signal"),
    "mode_changed": RemoteMessageRoute("mode_changed", "mode_changed_signal"),
    "api_stream_chunk": RemoteMessageRoute("api_stream_chunk", "api_stream_chunk_signal"),
    "api_stream_status": RemoteMessageRoute("api_stream_status", "api_stream_status_signal"),
    "api_round_state": RemoteMessageRoute("api_round_state", "api_round_state_signal"),
    "pending_consumed": RemoteMessageRoute("pending_consumed", "pending_message_consumed_signal", _no_args),
    "pong": RemoteMessageRoute("pong", "latency_signal", _latency_args),
}


def build_notification_meta(payload: Any, count_key: str = "count") -> dict[str, Any]:
    try:
        count = len(payload)
    except Exception:
        count = 0
    return {count_key: count, "ts": time.time()}
