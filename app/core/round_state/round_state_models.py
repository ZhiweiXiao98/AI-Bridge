"""浏览器模式回合状态机 - 数据模型"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
import time


class BrowserRoundState(Enum):
    """浏览器模式回合状态枚举。

    每个状态代表当前回合所处的阶段。
    """
    IDLE = "idle"                        # 空闲
    AI_STREAMING = "ai_streaming"        # AI 正在生成回复
    PROCESSING = "processing"            # AI 回复结束，正在处理输出
    FIXING = "fixing"                    # 流水线执行中（AutoFix 等）
    TOOL_EXECUTING = "tool_executing"    # 工具正在执行
    SYSTEM_SENDING = "system_sending"    # 工具结果发回网页


@dataclass
class RoundStateSnapshot:
    """状态快照，用于日志和外部查询。"""
    state: BrowserRoundState = BrowserRoundState.IDLE
    previous_state: Optional[BrowserRoundState] = None
    last_event: Optional[str] = None
    changed_at: float = field(default_factory=time.time)
    transition_count: int = 0
