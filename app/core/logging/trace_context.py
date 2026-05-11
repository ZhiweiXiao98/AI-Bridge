# filename: app/core/logging/trace_context.py
"""
全链路追踪上下文

职责：
- 为每次请求生成唯一 trace_id
- 管理 round_id / stream_id / conversation_id 等追踪字段
- 提供线程安全的上下文存取
- 支持日志自动附加追踪信息
"""

import threading
import uuid
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TraceContext:
    trace_id: str = ""
    conversation_id: str = ""
    round_id: str = ""
    stream_id: str = ""
    client_id: str = ""
    side: str = ""
    thread_name: str = ""
    created_at: float = 0.0

    def to_dict(self):
        return {
            "trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "round_id": self.round_id,
            "stream_id": self.stream_id,
            "client_id": self.client_id,
            "side": self.side,
            "thread_name": self.thread_name,
            "created_at": self.created_at,
        }

    def summary(self):
        parts = [f"trace={self.trace_id[:8]}"]
        if self.conversation_id:
            parts.append(f"conv={self.conversation_id[:8]}")
        if self.round_id:
            parts.append(f"round={self.round_id}")
        return " | ".join(parts)


_local = threading.local()


def generate_trace_id():
    return f"T-{uuid.uuid4().hex[:12]}"


def generate_round_id():
    return f"R-{uuid.uuid4().hex[:8]}"


def generate_stream_id():
    return f"S-{uuid.uuid4().hex[:8]}"


def get_current_trace() -> Optional[TraceContext]:
    return getattr(_local, "trace", None)


def set_current_trace(ctx: TraceContext):
    _local.trace = ctx


def clear_current_trace():
    _local.trace = None


def new_trace(
    conversation_id: str = "",
    client_id: str = "",
    side: str = "",
) -> TraceContext:
    """
    创建新的追踪上下文并设为当前线程活跃上下文

    Args:
        conversation_id: 会话 ID
        client_id: 客户端 ID
        side: 进程侧标识

    Returns:
        TraceContext: 新创建的追踪上下文
    """
    ctx = TraceContext(
        trace_id=generate_trace_id(),
        conversation_id=conversation_id,
        round_id="",
        stream_id="",
        client_id=client_id,
        side=side,
        thread_name=threading.current_thread().name,
        created_at=time.time(),
    )
    set_current_trace(ctx)
    return ctx


def new_round(round_id: str = "") -> str:
    """
    在当前追踪上下文中开启新回合

    Args:
        round_id: 指定 round_id，为空则自动生成

    Returns:
        str: round_id
    """
    ctx = get_current_trace()
    if ctx is None:
        ctx = new_trace()
    rid = round_id or generate_round_id()
    ctx.round_id = rid
    return rid


def new_stream(stream_id: str = "") -> str:
    """
    在当前追踪上下文中开启新流

    Args:
        stream_id: 指定 stream_id，为空则自动生成

    Returns:
        str: stream_id
    """
    ctx = get_current_trace()
    if ctx is None:
        ctx = new_trace()
    sid = stream_id or generate_stream_id()
    ctx.stream_id = sid
    return sid


@contextmanager
def trace_scope(conversation_id: str = "", client_id: str = "", side: str = ""):
    """
    追踪上下文作用域管理器

    用法:
        with trace_scope(conversation_id="conv-123", side="worker") as ctx:
            # 在此作用域内，所有日志自动附加 trace_id
            logger.info("处理请求", extra={"trace_id": ctx.trace_id})
    """
    prev = get_current_trace()
    ctx = new_trace(conversation_id=conversation_id, client_id=client_id, side=side)
    try:
        yield ctx
    finally:
        if prev is not None:
            set_current_trace(prev)
        else:
            clear_current_trace()


def get_trace_extra():
    """
    获取当前追踪上下文的 extra 字典，用于 logger 调用

    用法:
        logger.info("消息", extra=get_trace_extra())
    """
    ctx = get_current_trace()
    if ctx is None:
        return {"trace_id": "-", "side": "", "conversation_id": "-", "round_id": "-", "stream_id": "-"}
    extra = {"trace_id": ctx.trace_id, "side": ctx.side}
    extra["conversation_id"] = ctx.conversation_id or "-"
    extra["round_id"] = ctx.round_id or "-"
    extra["stream_id"] = ctx.stream_id or "-"
    return extra
