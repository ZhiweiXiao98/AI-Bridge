# filename: app/core/logging/log_manager.py
"""
统一日志管理器 - AI Bridge 日志基础设施

职责：
- 统一 logging 初始化与 handler 配置
- 提供 get_logger() 统一获取 logger
- 区分 UI / Worker / RPC / Debug 日志文件
- 支持运行时动态调整日志级别
- 支持面板 handler 的注册与移除

关键设计：
- root logger 设为 WARNING，避免第三方库 DEBUG 日志洪水
- 仅 app.* 命名空间的 logger 允许 DEBUG
- 第三方库（selenium/urllib3/httpx 等）强制 WARNING
- 文件 handler 仅记录 app.* 命名空间的日志
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime

_initialized = False
_panel_handler = None
_log_dir = None

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(side)s | %(name)s | %(trace_id)s | %(conversation_id)s | %(round_id)s | %(message)s"
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(trace_id)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DEFAULT_LEVEL = logging.INFO
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3

LOG_FILES = {
    "app": "app.log",
    "ui": "ui.log",
    "worker": "worker.log",
    "rpc": "rpc.log",
    "debug_trace": "debug_trace.log",
}

SIDE_MAP = {
    "ui": "界面  ",
    "worker": "工作  ",
    "rpc": "远程  ",
    "debug": "调试  ",
    "server": "服务  ",
    "core": "核心  ",
}

THIRD_PARTY_LOGGERS = [
    "selenium",
    "urllib3",
    "httpx",
    "httpcore",
    "asyncio",
    "multipart",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "fastapi",
    "google",
    "google.genai",
    "openai",
    "docker",
    "websocket",
    "chromedriver",
    "PIL",
    "tiktoken",
    "bs4",
    "sentence_transformers",
    "chromadb",
]


class AppNamespaceFilter(logging.Filter):
    """
    仅允许 app.* 命名空间的日志通过

    防止第三方库日志写入文件和面板
    """

    def filter(self, record):
        name = record.name
        if name.startswith("app."):
            return True
        if name in ("log_manager", "probe"):
            return True
        if name.startswith("probe"):
            return True
        return False


class SideFilter(logging.Filter):
    def __init__(self, side="core"):
        super().__init__()
        self._side_key = side
        self.side = SIDE_MAP.get(side, side.upper().ljust(5))

    def filter(self, record):
        if not hasattr(record, "side"):
            record.side = self.side
            record.side_key = self._side_key
        else:
            # 保存原始英文键，面板端筛选依赖此字段
            if not hasattr(record, "side_key"):
                record.side_key = record.side if record.side in SIDE_MAP else "core"
            record.side = SIDE_MAP.get(record.side, str(record.side).upper().ljust(5))
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


class TraceIdFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        if not hasattr(record, "side"):
            record.side = "核心  "
            record.side_key = "core"
        if not hasattr(record, "side_key"):
            # 回退：从现有 side 反推 side_key
            _reverse = {v.strip(): k for k, v in SIDE_MAP.items()}
            record.side_key = _reverse.get(record.side.strip() if hasattr(record, 'side') and record.side else "", "core")
        if not hasattr(record, "conversation_id"):
            record.conversation_id = "-"
        if not hasattr(record, "round_id"):
            record.round_id = "-"
        if not hasattr(record, "stream_id"):
            record.stream_id = "-"
        return True


def _ensure_log_dir(log_dir=None):
    global _log_dir
    if log_dir:
        _log_dir = log_dir
    elif _log_dir is None:
        from app.core.app_constants import APP_ROOT
        _log_dir = os.path.join(APP_ROOT, "logs")
    os.makedirs(_log_dir, exist_ok=True)
    return _log_dir


def _create_file_handler(filename, level=logging.DEBUG, fmt=None, app_only=True):
    log_dir = _ensure_log_dir()
    filepath = os.path.join(log_dir, filename)
    handler = RotatingFileHandler(
        filepath,
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    handler.addFilter(TraceIdFilter())
    if app_only:
        handler.addFilter(AppNamespaceFilter())
    handler.setFormatter(formatter)
    return handler


def _create_console_handler(level=None, fmt=None):
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level or DEFAULT_LEVEL)
    formatter = logging.Formatter(fmt or CONSOLE_FORMAT, datefmt=DATE_FORMAT)
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(formatter)
    return handler


def _suppress_third_party():
    """
    将第三方库的 logger 强制设为 WARNING

    防止 selenium/urllib3/httpx 等库的 DEBUG 日志洪水
    """
    for name in THIRD_PARTY_LOGGERS:
        third_party_logger = logging.getLogger(name)
        third_party_logger.setLevel(logging.WARNING)
        third_party_logger.propagate = True


def init_logging(level=None, log_dir=None, console=True, files=True, side="core"):
    """
    初始化统一日志系统

    Args:
        level: 根日志级别，默认 INFO
        log_dir: 日志文件目录，默认 ./logs
        console: 是否启用控制台输出
        files: 是否启用文件输出
        side: 当前进程侧标识 (ui/worker/rpc/server/core)
    """
    global _initialized, _panel_handler

    if _initialized:
        return

    effective_level = level or DEFAULT_LEVEL

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)

    root_logger.handlers.clear()

    app_logger = logging.getLogger("app")
    app_logger.setLevel(effective_level)
    app_logger.propagate = True

    probe_logger = logging.getLogger("probe")
    probe_logger.setLevel(effective_level)
    probe_logger.propagate = True

    _suppress_third_party()

    if console:
        console_handler = _create_console_handler(level=effective_level)
        console_handler.addFilter(SideFilter(side))
        root_logger.addHandler(console_handler)

    if files:
        _ensure_log_dir(log_dir)
        for log_key, filename in LOG_FILES.items():
            if log_key == "debug_trace":
                fh = _create_file_handler(filename, level=logging.DEBUG, app_only=True)
            else:
                fh = _create_file_handler(filename, level=effective_level, app_only=True)
            fh.addFilter(SideFilter(side))
            root_logger.addHandler(fh)

    _initialized = True

    init_logger = logging.getLogger("log_manager")
    init_logger.info(
        "日志系统初始化完成 | side=%s | level=%s | log_dir=%s | console=%s | files=%s",
        side, logging.getLevelName(effective_level), _log_dir, console, files
    )


def get_logger(name, side=None):
    """
    获取统一配置的 logger

    Args:
        name: logger 名称，建议使用模块路径如 'app.core.worker'
        side: 进程侧标识，如 'ui', 'worker', 'rpc', 'server', 'core'

    Returns:
        logging.Logger: 已配置的 logger 实例
    """
    logger = logging.getLogger(name)

    if name.startswith("app."):
        logger.setLevel(logging.DEBUG)

    return logger


def register_panel_handler(handler):
    """
    注册面板日志 handler（由 qt_log_handler 调用）

    Args:
        handler: logging.Handler 实例，通常是 QtPanelLogHandler
    """
    global _panel_handler
    root_logger = logging.getLogger()
    if _panel_handler is not None:
        try:
            root_logger.removeHandler(_panel_handler)
        except Exception:
            pass
    _panel_handler = handler
    handler.addFilter(AppNamespaceFilter())
    root_logger.addHandler(handler)


def unregister_panel_handler():
    """移除面板日志 handler"""
    global _panel_handler
    if _panel_handler is not None:
        root_logger = logging.getLogger()
        try:
            root_logger.removeHandler(_panel_handler)
        except Exception:
            pass
        _panel_handler = None


def set_level(level, logger_name=None):
    """
    动态调整日志级别

    Args:
        level: 日志级别 (logging.DEBUG, logging.INFO, etc.)
        logger_name: 指定 logger 名称，None 则调整 app 命名空间
    """
    if logger_name:
        target = logging.getLogger(logger_name)
    else:
        target = logging.getLogger("app")
    target.setLevel(level)


def set_console_level(level):
    """仅调整控制台 handler 的日志级别"""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
            handler.setLevel(level)


def get_log_dir():
    """获取当前日志文件目录"""
    return _ensure_log_dir()


def is_initialized():
    """检查日志系统是否已初始化"""
    return _initialized
