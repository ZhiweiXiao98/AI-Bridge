"""浏览器模式回合状态机模块。

提供事件驱动的状态管理，替代 worker.py 中散落的 _browser_round_state 直接赋值。
"""
from .round_state_models import BrowserRoundState, RoundStateSnapshot
from .round_state_events import RoundStateEvent
from .round_state_machine import BrowserRoundStateMachine

__all__ = [
    "BrowserRoundState",
    "RoundStateSnapshot",
    "RoundStateEvent",
    "BrowserRoundStateMachine",
]
