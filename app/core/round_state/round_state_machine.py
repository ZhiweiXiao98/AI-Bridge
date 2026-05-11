"""浏览器模式回合状态机 - 核心实现

职责：
- 维护当前状态
- 根据事件驱动状态转换
- 非法转换打 WARNING 但不阻断
- 线程安全
- 状态变更回调通知
- 流水线生命周期管理（try_pipeline_end 等高层方法）
"""
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from app.core.logging import get_logger
from .round_state_models import BrowserRoundState, RoundStateSnapshot
from .round_state_events import RoundStateEvent

logger = get_logger("app.core.round_state", side="worker")

# 合法转换表：(当前状态, 事件) → 目标状态
_TRANSITIONS: Dict[Tuple[BrowserRoundState, RoundStateEvent], BrowserRoundState] = {
    # idle 出发
    (BrowserRoundState.IDLE, RoundStateEvent.BUSY_DETECTED): BrowserRoundState.AI_STREAMING,
    (BrowserRoundState.IDLE, RoundStateEvent.BUSY_TO_IDLE): BrowserRoundState.IDLE,  # 流水线已回 idle，轮询延迟检测到 busy→idle，静默
    (BrowserRoundState.IDLE, RoundStateEvent.TOOL_EXECUTION_START): BrowserRoundState.TOOL_EXECUTING,
    (BrowserRoundState.IDLE, RoundStateEvent.PIPELINE_START): BrowserRoundState.FIXING,

    # ai_streaming
    (BrowserRoundState.AI_STREAMING, RoundStateEvent.BUSY_DETECTED): BrowserRoundState.AI_STREAMING,  # 重复 busy 检测，保持
    (BrowserRoundState.AI_STREAMING, RoundStateEvent.BUSY_TO_IDLE): BrowserRoundState.PROCESSING,

    # processing
    (BrowserRoundState.PROCESSING, RoundStateEvent.PIPELINE_START): BrowserRoundState.FIXING,

    # fixing
    (BrowserRoundState.FIXING, RoundStateEvent.PIPELINE_END): BrowserRoundState.IDLE,
    (BrowserRoundState.FIXING, RoundStateEvent.TOOL_EXECUTION_START): BrowserRoundState.TOOL_EXECUTING,

    # tool_executing
    (BrowserRoundState.TOOL_EXECUTING, RoundStateEvent.TOOL_RESULT_READY): BrowserRoundState.SYSTEM_SENDING,
    (BrowserRoundState.TOOL_EXECUTING, RoundStateEvent.TOOL_EXECUTION_FAILED): BrowserRoundState.IDLE,

    # system_sending
    (BrowserRoundState.SYSTEM_SENDING, RoundStateEvent.BUSY_DETECTED): BrowserRoundState.AI_STREAMING,  # AI 开始回复
    (BrowserRoundState.SYSTEM_SENDING, RoundStateEvent.BUSY_TO_IDLE): BrowserRoundState.PROCESSING,  # AI 回复太快，轮询直接看到完成
    (BrowserRoundState.SYSTEM_SENDING, RoundStateEvent.TOOL_SEND_COMPLETE): BrowserRoundState.AI_STREAMING,
    (BrowserRoundState.SYSTEM_SENDING, RoundStateEvent.PIPELINE_START): BrowserRoundState.FIXING,  # 快速回复后直接进流水线
    (BrowserRoundState.SYSTEM_SENDING, RoundStateEvent.TOOL_EXECUTION_START): BrowserRoundState.TOOL_EXECUTING,  # 快速回复含工具调用
    (BrowserRoundState.SYSTEM_SENDING, RoundStateEvent.ERROR_RESET): BrowserRoundState.IDLE,
}

# 任何状态都可以响应的全局事件
_GLOBAL_EVENTS: Dict[RoundStateEvent, BrowserRoundState] = {
    RoundStateEvent.ERROR_RESET: BrowserRoundState.IDLE,
    RoundStateEvent.FORCE_IDLE: BrowserRoundState.IDLE,
}

# PIPELINE_END 合法转换的源状态集合
_PIPELINE_END_VALID_SOURCES = frozenset({
    BrowserRoundState.FIXING,
})

# 不应回 IDLE 的活跃状态（工具执行中 / 结果发送中）
_ACTIVE_STATES = frozenset({
    BrowserRoundState.TOOL_EXECUTING,
    BrowserRoundState.SYSTEM_SENDING,
})

# 状态枚举值 → UI 显示字符串的映射
_UI_STATE_MAP: Dict[BrowserRoundState, str] = {
    BrowserRoundState.IDLE: "idle",
    BrowserRoundState.AI_STREAMING: "busy",
    BrowserRoundState.PROCESSING: "fixing",
    BrowserRoundState.FIXING: "fixing",
    BrowserRoundState.TOOL_EXECUTING: "tool_executing",
    BrowserRoundState.SYSTEM_SENDING: "busy",
}


class BrowserRoundStateMachine:
    """浏览器模式回合状态机。

    用法：
        sm = BrowserRoundStateMachine()
        sm.on_state_change(callback)  # 注册回调
        sm.handle_event(RoundStateEvent.BUSY_DETECTED)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state = BrowserRoundState.IDLE
        self._previous_state: Optional[BrowserRoundState] = None
        self._last_event: Optional[RoundStateEvent] = None
        self._changed_at: float = time.time()
        self._transition_count: int = 0
        self._callbacks: List[Callable[[BrowserRoundState, BrowserRoundState, RoundStateEvent], None]] = []

    @property
    def state(self) -> BrowserRoundState:
        """当前状态（线程安全读取）。"""
        with self._lock:
            return self._state

    @property
    def state_value(self) -> str:
        """当前状态的字符串值，兼容旧代码 `_browser_round_state` 的用法。"""
        return self.state.value

    @property
    def ui_state(self) -> str:
        """当前状态对应的 UI 显示字符串（idle / busy / fixing / tool_executing）。"""
        return _UI_STATE_MAP.get(self.state, self.state.value)

    def get_snapshot(self) -> RoundStateSnapshot:
        """获取当前状态快照。"""
        with self._lock:
            return RoundStateSnapshot(
                state=self._state,
                previous_state=self._previous_state,
                last_event=self._last_event.value if self._last_event else None,
                changed_at=self._changed_at,
                transition_count=self._transition_count,
            )

    def on_state_change(self, callback: Callable[[BrowserRoundState, BrowserRoundState, RoundStateEvent], None]):
        """注册状态变更回调。

        callback(old_state, new_state, event) 在状态实际变更后调用。
        回调在持锁外执行，避免死锁。
        """
        self._callbacks.append(callback)

    def handle_event(self, event: RoundStateEvent) -> BrowserRoundState:
        """处理事件，驱动状态转换。

        返回转换后的状态。
        非法转换打 WARNING 但不阻断，状态保持不变。
        """
        old_state: BrowserRoundState
        new_state: BrowserRoundState
        changed = False

        with self._lock:
            old_state = self._state

            # 优先检查全局事件
            if event in _GLOBAL_EVENTS:
                new_state = _GLOBAL_EVENTS[event]
            else:
                key = (old_state, event)
                if key in _TRANSITIONS:
                    new_state = _TRANSITIONS[key]
                else:
                    # 非法转换
                    logger.warning(
                        "[状态机] 非法转换 | state=%s | event=%s | 忽略",
                        old_state.value, event.value,
                    )
                    return old_state

            if new_state != old_state:
                self._previous_state = old_state
                self._state = new_state
                self._last_event = event
                self._changed_at = time.time()
                self._transition_count += 1
                changed = True
                logger.info(
                    "[状态机] %s → %s (event=%s) | #%d",
                    old_state.value, new_state.value, event.value, self._transition_count,
                )
            else:
                # 同状态事件（如重复 BUSY_DETECTED），静默
                logger.debug(
                    "[状态机] 同状态事件 | state=%s | event=%s",
                    old_state.value, event.value,
                )

        # 回调在锁外执行
        if changed:
            for cb in self._callbacks:
                try:
                    cb(old_state, new_state, event)
                except Exception as e:
                    logger.error("[状态机] 回调异常: %s", e)

        return new_state if changed else old_state

    def try_pipeline_end(self) -> BrowserRoundState:
        """流水线结束：尝试 PIPELINE_END 转换。

        封装完整的状态判断逻辑，调用方无需关心当前状态：
        - FIXING：无工具，PIPELINE_END → IDLE
        - TOOL_EXECUTING / SYSTEM_SENDING：有工具在执行/发送，
          绝对不能回 IDLE，等后续流转自行处理
        - IDLE：工具异常已自行回 idle，无需再发 PIPELINE_END
        - 其他：静默跳过
        """
        cur = self.state
        if cur in _PIPELINE_END_VALID_SOURCES:
            return self.handle_event(RoundStateEvent.PIPELINE_END)
        elif cur in _ACTIVE_STATES:
            logger.info(
                "[状态机] try_pipeline_end: 状态=%s，等待后续流转（不回 idle）",
                cur.value,
            )
            return cur
        else:
            logger.debug(
                "[状态机] try_pipeline_end: 状态=%s，无需 PIPELINE_END",
                cur.value,
            )
            return cur

    def is_idle(self) -> bool:
        """是否处于空闲状态。"""
        return self.state == BrowserRoundState.IDLE

    def is_fixing_only(self) -> bool:
        """流水线是否停留在 FIXING（未触发工具执行）。

        用于 snapshot 推送决策：只有 FIXING 时才推 after_autofix snapshot，
        有工具 (TOOL_EXECUTING/SYSTEM_SENDING) 时不推，等后续 AI 回复后再推。
        """
        return self.state == BrowserRoundState.FIXING

    def try_tool_failed(self) -> BrowserRoundState:
        """工具执行异常兜底：仅在 TOOL_EXECUTING 时回 IDLE。

        正常路径下工具成功/失败都有 response_text → TOOL_RESULT_READY → SYSTEM_SENDING，
        不会走到这里。只有 maybe_handle_tool_from_messages 抛异常时才需要此方法。
        """
        if self.state == BrowserRoundState.TOOL_EXECUTING:
            logger.warning("[状态机] try_tool_failed: 工具执行未产生结果，回 idle")
            return self.handle_event(RoundStateEvent.TOOL_EXECUTION_FAILED)
        return self.state

    def is_busy(self) -> bool:
        """是否处于非空闲状态（任何工作中状态）。"""
        return self.state != BrowserRoundState.IDLE

    def is_tool_phase(self) -> bool:
        """是否处于工具相关阶段（executing 或 sending）。"""
        return self.state in (BrowserRoundState.TOOL_EXECUTING, BrowserRoundState.SYSTEM_SENDING)
