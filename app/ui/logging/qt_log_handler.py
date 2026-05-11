# filename: app/ui/logging/qt_log_handler.py
"""
Qt 面板日志 Handler

职责：
- 将标准 logging 输出桥接到 Qt Signal
- 由 RuntimeLogPanel 消费并显示
- 支持日志级别过滤，避免高频日志淹没面板
- 线程安全：logging 线程通过 Signal 跨线程传递到 UI 线程

V2 增强：
- 传递结构化日志元数据（级别、来源、模块名、时间戳）到面板
- 面板可基于元数据做精确筛选，而非仅靠文本匹配
- 集成 NoiseControlConfig 动态噪声过滤
"""

import logging
import json
from PySide6.QtCore import QObject, Signal


class LogPanelBridge(QObject):
    """
    日志面板桥接器

    将 logging record 转换为 Qt Signal，
    确保 UI 更新在主线程执行。

    V2: 使用 str 信号传递 JSON 序列化的结构化日志条目，
    包含 level / side / name / message / timestamp 等字段，
    面板端可精确解析，不再依赖文本正则匹配。
    """
    # 结构化日志信号：JSON 字符串
    log_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)


class QtPanelLogHandler(logging.Handler):
    """
    自定义 logging Handler，将日志输出到 Qt 面板

    特性：
    - 通过 Qt Signal 跨线程安全传递日志
    - 支持最低级别过滤（默认 INFO）
    - 支持标签过滤（只显示特定 tag 的日志）
    - 支持来源过滤（只显示特定 side 的日志）
    - 支持噪声关键词过滤（过滤流式 chunk 等高频日志）
    - V2: 传递结构化元数据，面板端可精确筛选
    """

    NOISE_KEYWORDS = [
        "stream_chunk",
        "chunk_delta",
        "rpc_forward",
        "sync_poll",
        "/api/sync/",
        "heartbeat",
        "ping",
        "pong",
    ]

    # 中文级别名称映射
    LEVEL_NAMES_CN = {
        logging.DEBUG: "调试",
        logging.INFO: "信息",
        logging.WARNING: "警告",
        logging.ERROR: "错误",
        logging.CRITICAL: "严重",
    }

    LEVEL_STYLES = {
        logging.DEBUG: "🔍",
        logging.INFO: "ℹ️",
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "🔥",
    }

    # 中文来源映射（仅使用标准英文键）
    SIDE_NAMES_CN = {
        "ui": "界面",
        "worker": "工作",
        "rpc": "远程",
        "debug": "调试",
        "server": "服务",
        "core": "核心",
    }

    def __init__(self, bridge=None, level=logging.INFO, filter_noise=True):
        super().__init__(level)
        self.bridge = bridge or LogPanelBridge()
        self.filter_noise = filter_noise
        self._tag_filter = None
        self._side_filter = None
        self.addFilter(self._should_emit)

    def _should_emit(self, record):
        if self._tag_filter:
            tag = getattr(record, "tag", None)
            if tag and tag != self._tag_filter:
                return False

        if self._side_filter:
            side = getattr(record, "side", None)
            if side and side != self._side_filter:
                return False

        if self.filter_noise:
            msg = record.getMessage().lower()
            for kw in self.NOISE_KEYWORDS:
                if kw.lower() in msg:
                    return False

        return True

    def emit(self, record):
        try:
            entry = self._build_entry(record)
            self.bridge.log_signal.emit(json.dumps(entry, ensure_ascii=False))
        except Exception:
            self.handleError(record)

    def _build_entry(self, record):
        """构建结构化日志条目"""
        level_no = record.levelno
        side_raw = getattr(record, "side", "")
        side_key = getattr(record, "side_key", "")  # 原始英文键，用于面板筛选
        # 规范化 side_key：确保是标准英文键
        if not side_key or side_key not in self.SIDE_NAMES_CN:
            # 从 side_raw 反推
            _reverse = {v: k for k, v in self.SIDE_NAMES_CN.items() if len(k) <= 6}
            side_key = _reverse.get(side_raw.strip() if side_raw else "", side_key)

        # 时间戳：优先使用 record.created，否则用当前时间
        from datetime import datetime
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        except (AttributeError, OSError):
            ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "level": level_no,
            "level_name": self.LEVEL_NAMES_CN.get(level_no, record.levelname),
            "level_icon": self.LEVEL_STYLES.get(level_no, ""),
            "side": side_key,  # 英文键，供面板筛选
            "side_name": self.SIDE_NAMES_CN.get(side_key, side_key),  # 中文显示名
            "name": record.name,
            "message": record.getMessage(),
            "timestamp": ts,
            "trace_id": getattr(record, "trace_id", "-"),
        }
        return entry

    # 保留旧接口兼容：纯文本格式化（不再作为主通道）
    def format(self, record):
        level = record.levelno
        icon = self.LEVEL_STYLES.get(level, "")
        name = record.name
        message = record.getMessage()
        trace_id = getattr(record, "trace_id", "-")

        if trace_id and trace_id != "-":
            return f"{icon} [{name}] {message} (trace:{trace_id})"
        return f"{icon} [{name}] {message}"

    def set_tag_filter(self, tag=None):
        self._tag_filter = tag

    def set_side_filter(self, side=None):
        self._side_filter = side

    def set_noise_filter(self, enabled=True):
        self.filter_noise = enabled
