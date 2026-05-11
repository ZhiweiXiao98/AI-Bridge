# filename: app/core/debug/probe.py
"""
统一调试探针机制

职责：
- 提供统一的 probe() 函数，替代临时 print 插桩
- 支持按 tag / side / level 过滤
- 支持配置开关，默认不输出高噪探针
- 自动附加 trace_id / module / thread 等上下文
- 可选同步显示到运行日志面板
"""

import logging
import threading
import os
from typing import Optional

from app.core.logging.trace_context import get_current_trace, get_trace_extra

_probe_logger = logging.getLogger("probe")

_enabled = True
_tag_whitelist = set()
_side_whitelist = set()
_level_override = {}
_verbose = False


def probe(
    tag: str,
    level: str = "debug",
    side: str = "",
    trace_id: str = "",
    conversation_id: str = "",
    round_id: str = "",
    **kwargs,
):
    """
    统一调试探针

    Args:
        tag: 探针标签，用于分类和过滤，如 'api_round_state', 'chatpage_render'
        level: 日志级别 debug/info/warning/error
        side: 进程侧标识 ui/worker/rpc/server
        trace_id: 追踪 ID，为空则自动从上下文获取
        conversation_id: 会话 ID
        round_id: 回合 ID
        **kwargs: 附加键值对，会以 key=value 格式拼接到消息中

    用法:
        probe("api_round_state", side="worker", state="detecting_tools")
        probe("chatpage_finalized", side="ui", cached_count=5, last_role="assistant")
    """
    if not _enabled:
        return

    if _tag_whitelist and tag not in _tag_whitelist:
        return

    if _side_whitelist and side and side not in _side_whitelist:
        return

    ctx = get_current_trace()
    tid = trace_id or (ctx.trace_id if ctx else "-")
    cid = conversation_id or (ctx.conversation_id if ctx else "")
    rid = round_id or (ctx.round_id if ctx else "")
    effective_side = side or (ctx.side if ctx else "")

    parts = [f"[{tag}]"]
    if effective_side:
        parts.append(f"side={effective_side}")
    if tid and tid != "-":
        parts.append(f"trace={tid[:8]}")
    if cid:
        parts.append(f"conv={cid[:8]}")
    if rid:
        parts.append(f"round={rid}")

    for k, v in kwargs.items():
        parts.append(f"{k}={v}")

    message = " | ".join(parts)

    extra = {
        "trace_id": tid,
        "side": effective_side,
        "tag": tag,
    }
    if cid:
        extra["conversation_id"] = cid
    if rid:
        extra["round_id"] = rid

    log_level = getattr(logging, level.upper(), logging.DEBUG)
    if tag in _level_override:
        log_level = _level_override[tag]

    _probe_logger.log(log_level, message, extra=extra)


def enable_probe(enabled=True):
    """全局启用/禁用探针"""
    global _enabled
    _enabled = enabled


def set_tag_whitelist(tags=None):
    """
    设置标签白名单，仅白名单内的标签会输出

    Args:
        tags: 标签集合，None 或空集合表示不过滤
    """
    global _tag_whitelist
    _tag_whitelist = set(tags) if tags else set()


def set_side_whitelist(sides=None):
    """
    设置进程侧白名单

    Args:
        sides: 进程侧集合，None 或空集合表示不过滤
    """
    global _side_whitelist
    _side_whitelist = set(sides) if sides else set()


def set_tag_level(tag, level):
    """
    为特定标签设置日志级别

    Args:
        tag: 标签名
        level: 日志级别名 (debug/info/warning/error)
    """
    _level_override[tag] = getattr(logging, level.upper(), logging.DEBUG)


def set_verbose(verbose=True):
    """
    设置详细模式

    详细模式下，所有探针都会输出，不受白名单限制
    """
    global _verbose, _tag_whitelist, _side_whitelist
    _verbose = verbose
    if verbose:
        _tag_whitelist = set()
        _side_whitelist = set()


def is_enabled():
    """检查探针是否启用"""
    return _enabled
