"""浏览器模式回合状态机 - 事件定义"""
from enum import Enum


class RoundStateEvent(Enum):
    """触发状态转换的事件。

    每个事件对应一个外部动作或检测结果，
    状态机根据 (当前状态, 事件) 决定下一个状态。
    """

    # --- 轮询检测 ---
    BUSY_DETECTED = "busy_detected"              # 检测到 AI 正在生成（is_busy=True）
    BUSY_TO_IDLE = "busy_to_idle"                # 检测到 busy→idle 转换（was_busy=True, current_busy=False）

    # --- 流水线 ---
    PIPELINE_START = "pipeline_start"            # 流水线入口（_background_process_ai_response）
    PIPELINE_END = "pipeline_end"                # 流水线正常结束

    # --- 工具执行 ---
    TOOL_EXECUTION_START = "tool_execution_start"  # 工具开始执行
    TOOL_RESULT_READY = "tool_result_ready"        # 工具结果就绪，准备发回
    TOOL_SEND_COMPLETE = "tool_send_complete"      # 工具结果已发回网页（system_sending 完成）
    TOOL_EXECUTION_FAILED = "tool_execution_failed"  # 工具执行失败/无结果

    # --- 通用 ---
    ERROR_RESET = "error_reset"                  # 异常恢复，强制回 idle
    FORCE_IDLE = "force_idle"                    # 外部强制重置（如用户切换对话）
