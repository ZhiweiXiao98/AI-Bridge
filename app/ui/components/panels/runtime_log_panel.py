# filename: app/ui/components/panels/runtime_log_panel.py
"""
运行日志面板 - V2 增强版

增强功能：
- 工具栏：暂停/继续、清空、自动滚动开关
- 级别筛选下拉框（全部/严重/错误/警告/信息/调试）
- 来源筛选下拉框（全部/核心/界面/工作/远程/服务/调试）
- 实时搜索框（同时筛选过往日志和未来日志）
- 行数状态显示
- 日志级别着色（ERROR 红色、WARNING 黄色、INFO 绿色、DEBUG 灰色）
- 支持最大行数限制，自动清理旧日志
- 保留原有同步轮询日志过滤功能
- 兼容原有 server_log_signal 接口（纯文本）和新的结构化日志接口
- 中文母语适配：级别名称、来源标签、UI 文案全部中文化
"""

import datetime
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QFrame, QLabel,
    QGroupBox, QPushButton, QComboBox, QLineEdit, QToolBar,
    QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QTextCursor, QTextCharFormat, QColor, QFont, QTextDocument,
)
from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager

MAX_LOG_LINES = 5000
TRIM_THRESHOLD = 6000

# ─── 级别颜色（正文着色 = 严重程度） ──────────────────────
LEVEL_COLORS = {
    "CRITICAL": "#ef4444",
    "ERROR": "#f87171",
    "WARNING": "#fbbf24",
    "SUCCESS": "#22c55e",
    "INFO": "#4ade80",
    "DEBUG": "#71717a",
}

# ─── 来源颜色（前缀着色 = 谁发的） ──────────────────────
SIDE_COLORS = {
    "core": "#fbbf24",
    "ui": "#a78bfa",
    "worker": "#38bdf8",
    "rpc": "#fb923c",
    "server": "#facc15",
    "debug": "#71717a",
    "install": "#c084fc",
    "update": "#86efac",
    "system": "#9ca3af",
}

# ─── 级别图标 ───────────────────────────────────────────
LEVEL_ICONS = {
    "CRITICAL": "🔥",
    "ERROR": "❌",
    "WARNING": "⚠️",
    "SUCCESS": "✅",
    "INFO": "ℹ️",
    "DEBUG": "🔍",
}

# ─── 中文级别名称 ────────────────────────────────────────
LEVEL_NAMES_CN = {
    "CRITICAL": "严重",
    "ERROR": "错误",
    "WARNING": "警告",
    "SUCCESS": "成功",
    "INFO": "信息",
    "DEBUG": "调试",
}

# ─── 中文来源名称 ────────────────────────────────────────
SIDE_NAMES_CN = {
    "core": "核心",
    "ui": "界面",
    "worker": "工作",
    "rpc": "远程",
    "server": "服务",
    "debug": "调试",
    "install": "安装",
    "update": "更新",
    "system": "系统",
}

# ─── 级别数值排序（用于筛选 >= 某级别） ──────────────────
LEVEL_ORDER = {
    "DEBUG": 0,
    "INFO": 1,
    "SUCCESS": 2,
    "WARNING": 3,
    "ERROR": 4,
    "CRITICAL": 5,
}


def _detect_level(text: str) -> str:
    """从纯文本日志中推断级别（兼容 server_log_signal 等纯文本来源）"""
    lower = text.lower()
    for icon in ("🔥",):
        if icon in text:
            return "CRITICAL"
    for icon in ("❌",):
        if icon in text:
            return "ERROR"
    if "⚠️" in text:
        return "WARNING"
    if "✅" in text or "成功" in text:
        return "SUCCESS"
    if "🔍" in text:
        return "DEBUG"
    if "ℹ️" in text:
        return "INFO"
    if "error" in lower or "exception" in lower or "traceback" in lower or "失败" in text:
        return "ERROR"
    if "warning" in lower or "warn" in lower or "警告" in text:
        return "WARNING"
    return "INFO"


def _detect_side(text: str) -> str:
    """从纯文本日志中推断来源"""
    lower = text.lower()
    if "[server]" in lower or "服务" in text:
        return "server"
    if "[worker]" in lower or "[工作]" in text:
        return "worker"
    if "[ui]" in lower or "[界面]" in text:
        return "ui"
    if "[rpc]" in lower or "[远程]" in text:
        return "rpc"
    if "📦" in text or "[pip]" in lower or "[install]" in lower:
        return "install"
    if "⚡" in text or "[update]" in lower or "升级" in text:
        return "update"
    if "♻️" in text or "[system]" in lower:
        return "system"
    return ""


class _LogEntry:
    """内存中的结构化日志条目，用于实时筛选"""
    __slots__ = ("timestamp", "level", "level_cn", "side", "side_cn",
                 "name", "message", "icon", "raw_text", "trace_id")

    def __init__(self, timestamp="", level="INFO", level_cn="信息",
                 side="", side_cn="", name="", message="",
                 icon="ℹ️", raw_text="", trace_id="-"):
        self.timestamp = timestamp
        self.level = level
        self.level_cn = level_cn
        self.side = side
        self.side_cn = side_cn
        self.name = name
        self.message = message
        self.icon = icon
        self.raw_text = raw_text
        self.trace_id = trace_id

    @property
    def display_text(self):
        """格式化后的显示文本"""
        parts = []
        if self.side_cn:
            parts.append(f"[{self.side_cn}]")
        if self.name and self.name != "app":
            # 简化模块名：app.core.worker → core.worker
            short = self.name
            if short.startswith("app."):
                short = short[4:]
            if short.startswith("start_"):
                short = short[6:]
            parts.append(f"[{short}]")
        prefix = " ".join(parts)
        if prefix:
            return f"{self.icon} {prefix} {self.message}"
        return f"{self.icon} {self.message}"

    @property
    def search_text(self):
        """用于搜索的全文"""
        return f"{self.level} {self.level_cn} {self.side} {self.side_cn} {self.name} {self.message} {self.trace_id}".lower()


class RuntimeLogPanel(DockablePanel):
    """运行日志面板 - V2 增强版"""

    def __init__(self):
        super().__init__("runtime_log", "运行日志", "📜")
        self._entries: list[_LogEntry] = []  # 结构化日志存储
        self._paused = False
        self._pending_entries: list[_LogEntry] = []
        self._auto_scroll = True
        self._filter_level = "ALL"
        self._filter_side = "ALL"
        self._search_text = ""
        self._line_count = 0
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(100)  # 100ms 批量刷新
        self._refresh_timer.timeout.connect(self._do_refresh)
        self._refresh_pending = False
        self.init_content()

    # ─── UI 构建 ────────────────────────────────────────

    def create_content(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 同步状态区域
        self.sync_group = QGroupBox("🌐 同步状态")
        sync_layout = QVBoxLayout(self.sync_group)
        sync_layout.setContentsMargins(10, 8, 10, 8)
        sync_layout.setSpacing(4)

        self.sync_messages_label = QLabel("消息同步：暂无")
        self.sync_sessions_label = QLabel("会话同步：暂无")
        self.sync_messages_label.setObjectName("syncStatusLabel")
        self.sync_sessions_label.setObjectName("syncStatusLabel")

        sync_layout.addWidget(self.sync_messages_label)
        sync_layout.addWidget(self.sync_sessions_label)

        # ─── 工具栏 ─────────────────────────────────────
        toolbar = QWidget()
        toolbar.setObjectName("logToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(6, 4, 6, 4)
        toolbar_layout.setSpacing(4)

        # 暂停/继续
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setObjectName("logToolBtn")
        self.btn_pause.setFixedHeight(26)
        self.btn_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pause.clicked.connect(self._toggle_pause)
        toolbar_layout.addWidget(self.btn_pause)

        # 清空
        self.btn_clear = QPushButton("🗑 清空")
        self.btn_clear.setObjectName("logToolBtn")
        self.btn_clear.setFixedHeight(26)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear)
        toolbar_layout.addWidget(self.btn_clear)

        # 自动滚动
        self.btn_scroll = QPushButton("📌 滚动:开")
        self.btn_scroll.setObjectName("logToolBtn")
        self.btn_scroll.setFixedHeight(26)
        self.btn_scroll.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scroll.clicked.connect(self._toggle_scroll)
        toolbar_layout.addWidget(self.btn_scroll)

        # 分隔线
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setFixedWidth(1)
        toolbar_layout.addWidget(sep1)

        # 级别筛选
        lbl_level = QLabel("级别:")
        lbl_level.setObjectName("logToolLabel")
        toolbar_layout.addWidget(lbl_level)

        self.combo_level = QComboBox()
        self.combo_level.setObjectName("logCombo")
        self.combo_level.setFixedHeight(26)
        self.combo_level.setMinimumWidth(70)
        self.combo_level.addItems(["全部", "严重", "错误", "警告", "成功", "信息", "调试"])
        self.combo_level.currentIndexChanged.connect(self._on_level_filter_changed)
        toolbar_layout.addWidget(self.combo_level)

        # 来源筛选
        lbl_side = QLabel("来源:")
        lbl_side.setObjectName("logToolLabel")
        toolbar_layout.addWidget(lbl_side)

        self.combo_side = QComboBox()
        self.combo_side.setObjectName("logCombo")
        self.combo_side.setFixedHeight(26)
        self.combo_side.setMinimumWidth(70)
        self.combo_side.addItems(["全部", "核心", "界面", "工作", "远程", "服务", "安装", "更新", "系统", "调试"])
        self.combo_side.currentIndexChanged.connect(self._on_side_filter_changed)
        toolbar_layout.addWidget(self.combo_side)

        # 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFixedWidth(1)
        toolbar_layout.addWidget(sep2)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setObjectName("logSearch")
        self.search_input.setFixedHeight(26)
        self.search_input.setMinimumWidth(120)
        self.search_input.setPlaceholderText("🔍 搜索日志...")
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar_layout.addWidget(self.search_input)

        # 弹簧
        toolbar_layout.addStretch()

        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setObjectName("logStatus")
        toolbar_layout.addWidget(self.status_label)

        layout.addWidget(self.sync_group)
        layout.addWidget(toolbar)

        # ─── 日志显示区 ──────────────────────────────────
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFrameShape(QFrame.Shape.NoFrame)
        self.log_area.setMaximumBlockCount(MAX_LOG_LINES)
        self.log_area.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_area.setFont(QFont("Consolas", 10))
        layout.addWidget(self.log_area)

        theme_manager.theme_changed.connect(self.apply_content_theme)
        self.apply_content_theme()

        return widget

    # ─── 主题 ───────────────────────────────────────────

    def apply_content_theme(self):
        p = theme_manager.get_palette()

        self.log_area.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #18181b;
                color: {p.TEXT_SUCCESS};
                font-family: Consolas, "Microsoft YaHei", "Courier New";
                font-size: 11px;
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 8px;
                selection-background-color: #264F78;
            }}
        """)

        self.sync_group.setStyleSheet(f"""
            QGroupBox {{
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                margin-top: 6px;
                padding-top: 8px;
                background-color: #18181b;
                font-size: 11px;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px 0 4px;
            }}
            QLabel#syncStatusLabel {{
                color: {p.TEXT_SECONDARY};
                font-size: 11px;
                padding: 1px 0;
            }}
        """)

        # 工具栏样式
        btn_bg = "#3f3f46"
        btn_hover = "#52525b"
        self.setStyleSheet(f"""
            QWidget#logToolbar {{
                background-color: #27272a;
                border-bottom: 1px solid {p.BORDER};
            }}
            QPushButton#logToolBtn {{
                background-color: {btn_bg};
                color: #d4d4d8;
                border: 1px solid #52525b;
                border-radius: 3px;
                padding: 2px 10px;
                font-size: 11px;
                font-family: "Microsoft YaHei", sans-serif;
            }}
            QPushButton#logToolBtn:hover {{
                background-color: {btn_hover};
            }}
            QPushButton#logToolBtn:checked {{
                background-color: #166534;
                border-color: #22c55e;
            }}
            QLabel#logToolLabel {{
                color: #a1a1aa;
                font-size: 11px;
                font-family: "Microsoft YaHei", sans-serif;
            }}
            QComboBox#logCombo {{
                background-color: {btn_bg};
                color: #d4d4d8;
                border: 1px solid #52525b;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
                font-family: "Microsoft YaHei", sans-serif;
            }}
            QComboBox#logCombo::drop-down {{
                border: none;
                width: 16px;
            }}
            QComboBox#logCombo QAbstractItemView {{
                background-color: #27272a;
                color: #d4d4d8;
                selection-background-color: #3f3f46;
                font-family: "Microsoft YaHei", sans-serif;
            }}
            QLineEdit#logSearch {{
                background-color: {btn_bg};
                color: #d4d4d8;
                border: 1px solid #52525b;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 11px;
                font-family: "Microsoft YaHei", sans-serif;
            }}
            QLineEdit#logSearch:focus {{
                border-color: #22c55e;
            }}
            QLabel#logStatus {{
                color: #71717a;
                font-size: 10px;
                font-family: Consolas, "Microsoft YaHei";
                padding-right: 4px;
            }}
        """)

    # ─── 同步状态 ───────────────────────────────────────

    def _update_sync_status(self, kind):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        if kind == "messages":
            self.sync_messages_label.setText(f"消息同步：{ts}")
        elif kind == "sessions":
            self.sync_sessions_label.setText(f"会话同步：{ts}")

    # ─── 工具栏事件 ─────────────────────────────────────

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.btn_pause.setText("▶ 继续")
            self.btn_pause.setStyleSheet(
                "background-color: #166534; color: #4ade80; border: 1px solid #22c55e; "
                "border-radius: 3px; padding: 2px 10px; font-size: 11px;"
            )
        else:
            self.btn_pause.setText("⏸ 暂停")
            self.btn_pause.setStyleSheet("")
            self._flush_pending()

    def _toggle_scroll(self):
        self._auto_scroll = not self._auto_scroll
        state = "开" if self._auto_scroll else "关"
        self.btn_scroll.setText(f"📌 滚动:{state}")

    def _clear(self):
        self._entries.clear()
        self._pending_entries.clear()
        self._line_count = 0
        self.log_area.clear()
        self._update_status()

    def _on_level_filter_changed(self, index):
        level_map = ["ALL", "CRITICAL", "ERROR", "WARNING", "SUCCESS", "INFO", "DEBUG"]
        if 0 <= index < len(level_map):
            self._filter_level = level_map[index]
        else:
            self._filter_level = "ALL"
        self._refresh_display()

    def _on_side_filter_changed(self, index):
        side_map = ["ALL", "core", "ui", "worker", "rpc", "server", "install", "update", "system", "debug"]
        if 0 <= index < len(side_map):
            self._filter_side = side_map[index]
        else:
            self._filter_side = "ALL"
        self._refresh_display()

    def _on_search_changed(self, text):
        self._search_text = text.strip().lower()
        self._refresh_display()

    # ─── 筛选逻辑 ───────────────────────────────────────

    def _should_show(self, entry: _LogEntry) -> bool:
        """判断日志条目是否应该显示（基于当前筛选条件）"""
        # 级别筛选：显示 >= 所选级别的日志
        if self._filter_level != "ALL":
            min_order = LEVEL_ORDER.get(self._filter_level, 0)
            entry_order = LEVEL_ORDER.get(entry.level, 1)
            if entry_order < min_order:
                return False

        # 来源筛选
        if self._filter_side != "ALL":
            if entry.side != self._filter_side:
                return False

        # 搜索筛选
        if self._search_text:
            if self._search_text not in entry.search_text:
                return False

        return True

    # ─── 显示刷新 ───────────────────────────────────────

    def _refresh_display(self):
        """根据当前筛选条件重新渲染所有日志"""
        self.log_area.clear()
        self._line_count = 0

        cursor = self.log_area.textCursor()
        level_fmt = QTextCharFormat()
        side_fmt = QTextCharFormat()

        for entry in self._entries:
            if not self._should_show(entry):
                continue

            # Level color for message text (severity)
            level_color = LEVEL_COLORS.get(entry.level, LEVEL_COLORS["INFO"])
            level_fmt.setForeground(QColor(level_color))

            # Side color for source prefix (who sent it)
            side_color = SIDE_COLORS.get(entry.side, None)
            if side_color:
                side_fmt.setForeground(QColor(side_color))
            else:
                side_fmt.setForeground(QColor(level_color))

            ts = entry.timestamp or datetime.datetime.now().strftime("%H:%M:%S")
            display = entry.display_text

            # Highlight format for search matches
            highlight_fmt = QTextCharFormat(level_fmt)
            highlight_fmt.setBackground(QColor("#5C4A00"))
            highlight_fmt.setForeground(QColor("#FFD700"))

            # [timestamp] with level color
            cursor.insertText(f"[{ts}] ", level_fmt)

            # Source prefix [side_cn] with side color
            if entry.side_cn:
                cursor.insertText(f"[{entry.side_cn}] ", side_fmt)

            # Module prefix [name] with side color
            if entry.name and entry.name != "app":
                short = entry.name
                if short.startswith("app."):
                    short = short[4:]
                if short.startswith("start_"):
                    short = short[6:]
                cursor.insertText(f"[{short}] ", side_fmt)

            # Icon + message with level color (and search highlight)
            msg = f"{entry.icon} {entry.message}" if entry.icon else entry.message
            if self._search_text and self._search_text in display.lower():
                self._insert_with_highlight(cursor, msg, level_fmt, highlight_fmt)
            else:
                cursor.insertText(msg, level_fmt)

            cursor.insertText("\n", level_fmt)
            self._line_count += 1

        self._update_status()

        if self._auto_scroll:
            sb = self.log_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _insert_with_highlight(self, cursor, text, normal_fmt, highlight_fmt):
        """插入文本，对搜索词匹配部分高亮"""
        lower_text = text.lower()
        keyword = self._search_text
        pos = 0

        while pos < len(text):
            idx = lower_text.find(keyword, pos)
            if idx == -1:
                cursor.insertText(text[pos:], normal_fmt)
                break
            if idx > pos:
                cursor.insertText(text[pos:idx], normal_fmt)
            cursor.insertText(text[idx:idx + len(keyword)], highlight_fmt)
            pos = idx + len(keyword)

    def _schedule_refresh(self):
        """批量刷新，避免每条日志都触发完整重绘"""
        if not self._refresh_pending:
            self._refresh_pending = True
            self._refresh_timer.start()

    def _do_refresh(self):
        """定时器触发的增量刷新"""
        self._refresh_pending = False
        self._append_new_entries()

    def _append_new_entries(self):
        """增量追加新条目到显示区"""
        cursor = self.log_area.textCursor()
        level_fmt = QTextCharFormat()
        side_fmt = QTextCharFormat()

        for entry in self._pending_entries:
            self._entries.append(entry)

            if not self._should_show(entry):
                continue

            # Level color for message text (severity)
            level_color = LEVEL_COLORS.get(entry.level, LEVEL_COLORS["INFO"])
            level_fmt.setForeground(QColor(level_color))

            # Side color for source prefix (who sent it)
            side_color = SIDE_COLORS.get(entry.side, None)
            if side_color:
                side_fmt.setForeground(QColor(side_color))
            else:
                side_fmt.setForeground(QColor(level_color))

            ts = entry.timestamp or datetime.datetime.now().strftime("%H:%M:%S")
            display = entry.display_text

            highlight_fmt = QTextCharFormat(level_fmt)
            highlight_fmt.setBackground(QColor("#5C4A00"))
            highlight_fmt.setForeground(QColor("#FFD700"))

            cursor.movePosition(QTextCursor.MoveOperation.End)

            # [timestamp] with level color
            cursor.insertText(f"[{ts}] ", level_fmt)

            # Source prefix [side_cn] with side color
            if entry.side_cn:
                cursor.insertText(f"[{entry.side_cn}] ", side_fmt)

            # Module prefix [name] with side color
            if entry.name and entry.name != "app":
                short = entry.name
                if short.startswith("app."):
                    short = short[4:]
                if short.startswith("start_"):
                    short = short[6:]
                cursor.insertText(f"[{short}] ", side_fmt)

            # Icon + message with level color (and search highlight)
            msg = f"{entry.icon} {entry.message}" if entry.icon else entry.message
            if self._search_text and self._search_text in display.lower():
                self._insert_with_highlight(cursor, msg, level_fmt, highlight_fmt)
            else:
                cursor.insertText(msg, level_fmt)

            cursor.insertText("\n", level_fmt)
            self._line_count += 1

        self._pending_entries.clear()
        self._trim_if_needed()
        self._update_status()

        if self._auto_scroll:
            sb = self.log_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _flush_pending(self):
        """恢复暂停后，刷新暂存区的日志"""
        self._append_new_entries()

    # ─── 日志入口 ───────────────────────────────────────

    def append_log(self, text):
        """
        添加日志。兼容两种输入格式：
        1. 结构化 JSON（来自 QtPanelLogHandler V2）
        2. 纯文本（来自 server_log_signal 等旧接口）
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return

        # 同步轮询类日志不进入主日志区，只更新顶部状态
        lower_text = clean_text.lower()
        if "/api/sync/messages" in lower_text:
            self._update_sync_status("messages")
            return
        if "/api/sync/sessions" in lower_text:
            self._update_sync_status("sessions")
            return

        # 尝试解析结构化 JSON
        entry = self._parse_entry(clean_text)

        if self._paused:
            self._pending_entries.append(entry)
            return

        self._pending_entries.append(entry)
        self._schedule_refresh()

    def _parse_entry(self, text: str) -> _LogEntry:
        """解析日志文本为结构化条目"""
        # 尝试 JSON 解析（V2 结构化日志）
        if text.startswith("{"):
            try:
                data = json.loads(text)
                if "level" in data and "message" in data:
                    level_no = data.get("level", 20)
                    level_name = self._level_no_to_name(level_no)
                    side_raw = str(data.get("side", "")).strip()
                    return _LogEntry(
                        timestamp=data.get("timestamp", ""),
                        level=level_name,
                        level_cn=data.get("level_name", LEVEL_NAMES_CN.get(level_name, level_name)),
                        side=side_raw,
                        side_cn=data.get("side_name", SIDE_NAMES_CN.get(side_raw, side_raw)),
                        name=data.get("name", ""),
                        message=data.get("message", ""),
                        icon=data.get("level_icon", LEVEL_ICONS.get(level_name, "")),
                        raw_text=text,
                        trace_id=data.get("trace_id", "-"),
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        # 纯文本回退：推断元数据
        level = _detect_level(text)
        side = _detect_side(text)
        ts = datetime.datetime.now().strftime("%H:%M:%S")

        # 从文本中提取模块名，如 [app.core.worker]
        name = ""
        import re
        m = re.search(r'\[([a-zA-Z_][\w.]+)\]', text)
        if m:
            name = m.group(1)

        return _LogEntry(
            timestamp=ts,
            level=level,
            level_cn=LEVEL_NAMES_CN.get(level, level),
            side=side,
            side_cn=SIDE_NAMES_CN.get(side, side),
            name=name,
            message=text,
            icon=LEVEL_ICONS.get(level, ""),
            raw_text=text,
            trace_id="-",
        )

    @staticmethod
    def _level_no_to_name(level_no: int) -> str:
        """将 logging 级别数值转为名称"""
        mapping = {10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR", 50: "CRITICAL"}
        return mapping.get(level_no, "INFO")

    # ─── 裁剪和状态 ─────────────────────────────────────

    def _trim_if_needed(self):
        if len(self._entries) > TRIM_THRESHOLD:
            # 裁剪内存条目
            self._entries = self._entries[-(MAX_LOG_LINES):]
            # QPlainTextEdit 的 maximumBlockCount 会自动处理显示裁剪

    def _update_status(self):
        total = len(self._entries)
        shown = self._line_count
        if self._search_text or self._filter_level != "ALL" or self._filter_side != "ALL":
            self.status_label.setText(f"筛选: {shown}/{total}")
        else:
            self.status_label.setText(f"行数: {total}")
