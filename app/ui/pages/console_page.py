import logging
# filename: app/ui/pages/console_page.py
import datetime
import re
import subprocess
import sys

import requests
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from app.core.config import ConfigManager
from app.core.utils.error_reporter import ErrorReporter
from app.core.utils.text_utils import is_test_log
from app.core.app_constants import LOCAL_SERVER_HOST, SERVER_PORT
from app.ui.theme import Theme, theme_manager
from app.core.logging import get_logger

logger = get_logger("app.ui.console_page", side="ui")


class UIHelper:
    @staticmethod
    def _apply_style(box):
        box.setStyleSheet(Theme.message_box())

    @staticmethod
    def info(parent, title, text):
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Information)
        UIHelper._apply_style(box)
        box.exec()

    @staticmethod
    def warning(parent, title, text):
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Warning)
        UIHelper._apply_style(box)
        box.exec()

    @staticmethod
    def confirm(parent, title, text):
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Question)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        UIHelper._apply_style(box)
        return box.exec() == QMessageBox.StandardButton.Yes


def parse_pytest_summary(full_text: str):
    passed = 0
    failed = 0
    duration = "0"

    summary_line = ""
    for line in reversed(full_text.splitlines()):
        if " in " in line and (
            "passed" in line or "failed" in line or "error" in line
        ):
            summary_line = line
            break

    if summary_line:
        m = re.search(r"(\d+)\s+passed", summary_line)
        if m:
            passed = int(m.group(1))

        m = re.search(r"(\d+)\s+failed", summary_line)
        if m:
            failed += int(m.group(1))

        m = re.search(r"(\d+)\s+error", summary_line)
        if m:
            failed += int(m.group(1))

        m = re.search(r"in\s+([\d\.]+)s", summary_line)
        if m:
            duration = m.group(1)
    else:
        passed = len(re.findall(r"::[^\n]*\bPASSED\b", full_text))
        failed = len(re.findall(r"::[^\n]*\bFAILED\b", full_text))
        failed += len(re.findall(r"::[^\n]*\bERROR\b", full_text))

    return {"passed": passed, "failed": failed, "duration": duration}


class TestRunnerThread(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int, int)
    result_signal = Signal(object)
    finished_signal = Signal(str)

    def run(self):
        cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
        full_log = []
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )

            total_tests = 0
            current_tests = 0

            assert process.stdout is not None
            for line in process.stdout:
                line = line.rstrip("\n")
                full_log.append(line)
                if not line.strip():
                    continue

                self.log_signal.emit(line)

                m = re.search(r"collected (\d+) items", line)
                if m:
                    total_tests = int(m.group(1))

                if "::" in line and ("PASSED" in line or "FAILED" in line or "ERROR" in line):
                    current_tests += 1
                    if total_tests > 0:
                        self.progress_signal.emit(current_tests, total_tests)

            process.wait()
            full_text = "\n".join(full_log)
            parsed = parse_pytest_summary(full_text)

            self.result_signal.emit(
                {
                    "passed": parsed["passed"],
                    "failed": parsed["failed"],
                    "duration": parsed["duration"],
                    "full_log": full_text,
                }
            )
            self.finished_signal.emit(full_text)

        except Exception as e:
            msg = f"❌ Execution Error: {e}"
            self.log_signal.emit(msg)
            self.finished_signal.emit(msg)


class StatCard(QFrame):
    def __init__(self, title, value="--", color_key="TEXT_SUCCESS", parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 80)
        self.color_key = color_key
        self.title_text = title
        self.value_text = str(value)

        self.layout_box = QVBoxLayout(self)
        self.lbl_title = QLabel(self.title_text)
        self.lbl_value = QLabel(self.value_text)
        self.layout_box.addWidget(self.lbl_title)
        self.layout_box.addWidget(self.lbl_value)

        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(Theme.stat_card())
        self.lbl_title.setStyleSheet(Theme.card_title())
        c = getattr(theme_manager.get_palette(), self.color_key, "#FFFFFF")
        self.lbl_value.setStyleSheet(Theme.card_value(c))

    def set_value(self, val, color_key=None):
        self.value_text = str(val)
        self.lbl_value.setText(self.value_text)
        if color_key:
            self.color_key = color_key
            self.apply_theme()


class TestDashboard(QWidget):
    request_auto_report = Signal(str)

    def _is_test_log(self, text):
        return is_test_log(text)

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.last_full_log = ""
        self.init_ui()
        self.apply_theme()

        theme_manager.theme_changed.connect(self.apply_theme)

        if self.worker:
            if hasattr(self.worker, "sessions_signal"):
                self.worker.sessions_signal.connect(self.update_session_combo)
            if hasattr(self.worker, "server_log_signal"):
                self.worker.server_log_signal.connect(self.on_server_log_received)
            if hasattr(self.worker, "test_result_signal"):
                self.worker.test_result_signal.connect(self.on_test_finished)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(15)

        stats_layout = QHBoxLayout()
        self.card_total = StatCard("TOTAL TESTS", "0", "TEXT_PRIMARY")
        self.card_pass = StatCard("PASSED", "0", "TEXT_SUCCESS")
        self.card_fail = StatCard("FAILED", "0", "TEXT_DANGER")
        self.card_time = StatCard("DURATION", "0s", "ACCENT_PRIMARY")
        stats_layout.addWidget(self.card_total)
        stats_layout.addWidget(self.card_pass)
        stats_layout.addWidget(self.card_fail)
        stats_layout.addWidget(self.card_time)
        stats_layout.addStretch()

        self.control_panel = QFrame()
        cp_layout = QVBoxLayout(self.control_panel)
        cp_layout.setContentsMargins(15, 15, 15, 15)

        self.btn_run = QPushButton("🚀 运行全量测试 (Server)")
        self.btn_run.setFixedSize(220, 40)
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.clicked.connect(self.start_test)

        self.sidecar_group = QGroupBox("🚑 侧车维修站 (Agent Sidecar)")
        sg_layout = QHBoxLayout(self.sidecar_group)

        self.lbl_sidecar = QLabel("指派会话:")
        self.combo_sessions = QComboBox()
        self.combo_sessions.setMinimumWidth(200)

        self.btn_set_mechanic = QPushButton("🔗 设为维修工")
        self.btn_set_mechanic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_set_mechanic.clicked.connect(self.set_current_mechanic)

        self.btn_new_mechanic = QPushButton("➕ 新建侧车")
        self.btn_new_mechanic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_mechanic.clicked.connect(self.create_new_mechanic)

        sg_layout.addWidget(self.lbl_sidecar)
        sg_layout.addWidget(self.combo_sessions)
        sg_layout.addWidget(self.btn_set_mechanic)
        sg_layout.addWidget(self.btn_new_mechanic)
        sg_layout.addStretch()

        self.btn_report = QPushButton("🚑 自动修复 (发送报错到侧车)")
        self.btn_report.setFixedHeight(40)
        self.btn_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_report.clicked.connect(self.send_ai_report)
        self.btn_report.hide()

        cp_layout.addWidget(self.btn_run)
        cp_layout.addWidget(self.sidecar_group)
        cp_layout.addWidget(self.btn_report)

        right_panel = QVBoxLayout()
        right_panel.addWidget(self.control_panel)
        right_panel.addStretch()

        top_split = QHBoxLayout()
        top_split.addLayout(stats_layout, 2)
        top_split.addLayout(right_panel, 1)
        self.main_layout.addLayout(top_split)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.main_layout.addWidget(self.progress)

        self.log_header = QLabel("🖥️ Test Console Output (Remote Stream)")
        self.main_layout.addWidget(self.log_header)

        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.main_layout.addWidget(self.log_area)

    def apply_theme(self):
        self.control_panel.setStyleSheet(Theme.panel_container())
        self.btn_run.setStyleSheet(Theme.button_primary())
        self.sidecar_group.setStyleSheet(Theme.group_box())
        self.combo_sessions.setStyleSheet(Theme.combo_box())
        self.btn_set_mechanic.setStyleSheet(Theme.button_success_small())

        p = theme_manager.get_palette()
        self.btn_new_mechanic.setStyleSheet(
            Theme.button_success_small().replace(p.BTN_SUCCESS, p.BORDER)
        )
        self.btn_report.setStyleSheet(Theme.button_danger())
        self.progress.setStyleSheet(Theme.progress_bar())
        self.log_header.setStyleSheet(
            f"color: {p.TEXT_SECONDARY}; font-weight: bold; margin-top: 10px;"
        )
        self.log_area.setStyleSheet(Theme.log_editor())
        self.lbl_sidecar.setStyleSheet(f"color: {p.TEXT_PRIMARY};")

    def update_session_combo(self, sessions):
        current_data = self.combo_sessions.currentData()
        self.combo_sessions.clear()

        for s in sessions:
            idx = s.get("index")
            title = s.get("title", f"Session #{idx}")
            self.combo_sessions.addItem(f"{title} (#{idx})", idx)

        if current_data is not None:
            for i in range(self.combo_sessions.count()):
                if self.combo_sessions.itemData(i) == current_data:
                    self.combo_sessions.setCurrentIndex(i)
                    break

    def set_current_mechanic(self):
        idx = self.combo_sessions.currentData()
        if idx is None:
            UIHelper.warning(self, "未选择会话", "请先选择一个会话。")
            return
        if hasattr(self.worker, "set_session_role"):
            self.worker.set_session_role(idx, "mechanic")
            UIHelper.info(self, "设置成功", f"会话 #{idx} 已指定为侧车 (Mechanic)。")

    def create_new_mechanic(self):
        if hasattr(self.worker, "new_chat"):
            self.worker.new_chat()
            UIHelper.info(self, "指令已发送", "正在创建新会话...")

    def start_test(self):
        self.log_area.clear()
        self.log_area.appendPlainText("⏳ 正在请求云端运行测试...")
        self.btn_run.setEnabled(False)
        self.btn_run.setText("测试运行中...")
        self.btn_report.hide()

        self.progress.setRange(0, 0)
        self.card_total.set_value("-")
        self.card_pass.set_value("-")
        self.card_fail.set_value("-")
        self.card_time.set_value("...")

        if hasattr(self.worker, "run_remote_tests"):
            self.worker.run_remote_tests()
        else:
            self.log_area.appendPlainText("❌ 错误：当前 Worker 不支持远程测试。")
            self.btn_run.setEnabled(True)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def on_server_log_received(self, text):
        if not self._is_test_log(text):
            return
        clean_text = text.replace('[测试日志] ', '').replace('[TestLog] ', '')
        self.append_log(clean_text)

    def append_log(self, text):
        p = theme_manager.get_palette()
        color = p.TEXT_SECONDARY
        if "PASSED" in text:
            color = p.TEXT_SUCCESS
        elif "FAILED" in text:
            color = p.TEXT_DANGER
        elif "ERROR " in text and "tests/" in text:
            color = p.TEXT_DANGER

        self.log_area.appendHtml(f'<span style="color:{color};">{text}</span>')
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_test_finished(self, data):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.btn_run.setEnabled(True)
        self.btn_run.setText("🚀 运行全量测试 (Server)")

        raw_log = data.get("full_log", "") or self.last_full_log
        if raw_log:
            parsed = parse_pytest_summary(raw_log)
            passed = parsed["passed"]
            failed = parsed["failed"]
            duration = parsed["duration"]
            self.last_full_log = raw_log
        else:
            passed = int(data.get("passed", 0))
            failed = int(data.get("failed", 0))
            duration = str(data.get("duration", "0"))

        total = passed + failed
        self.card_total.set_value(total)
        self.card_pass.set_value(passed)
        self.card_fail.set_value(failed, "TEXT_DANGER" if failed > 0 else "TEXT_SECONDARY")
        self.card_time.set_value(f"{duration}s")

        p = theme_manager.get_palette()
        if failed > 0:
            self.log_area.appendHtml(
                f'<br><b style="color:{p.TEXT_DANGER}; font-size:14px;">❌ 测试失败: {failed} 个错误</b>'
            )
            self.btn_report.show()
        else:
            self.log_area.appendHtml(
                f'<br><b style="color:{p.TEXT_SUCCESS}; font-size:14px;">✅ 所有测试通过!</b>'
            )

    def send_ai_report(self):
        report = ErrorReporter.generate_report(self.last_full_log)
        self.request_auto_report.emit(report)
        self.btn_report.setText("🔄 修复指令已发送")
        self.btn_report.setEnabled(False)


class UserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加新用户")
        self.resize(300, 250)

        self.username = QLineEdit()
        self.password = QLineEdit()
        self.name = QLineEdit()
        self.role = QComboBox()
        self.role.addItems(["user", "vip", "developer", "guest"])

        layout = QFormLayout(self)
        layout.addRow("账号:", self.username)
        layout.addRow("密码:", self.password)
        layout.addRow("昵称:", self.name)
        layout.addRow("角色:", self.role)

        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        btn_box = QHBoxLayout()
        btn_box.addWidget(self.ok_btn)
        layout.addRow(btn_box)

        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_SECONDARY}; color: {p.TEXT_PRIMARY};")
        style = (
            f"QLineEdit {{ background: {p.BG_TERTIARY}; border: 1px solid {p.BORDER}; "
            f"padding: 5px; color: {p.TEXT_PRIMARY}; }}"
        )
        self.username.setStyleSheet(style)
        self.password.setStyleSheet(style)
        self.name.setStyleSheet(style)
        self.role.setStyleSheet(Theme.combo_box())
        self.ok_btn.setStyleSheet(Theme.button_success_small())

    def get_data(self):
        return {
            "username": self.username.text(),
            "password": self.password.text(),
            "role": self.role.currentText(),
            "name": self.name.text(),
        }


class UserManagerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager.load()
        self.token = ""
        self.init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.load_users)
        self.add_btn = QPushButton("➕ 添加")
        self.add_btn.clicked.connect(self.add_user)

        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.add_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["账号", "状态", "昵称", "角色", "设备 IP", "创建时间", "操作"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def apply_theme(self):
        self.refresh_btn.setStyleSheet(
            Theme.button_primary().replace("font-size: 14px", "font-size: 12px; padding: 5px;")
        )
        self.add_btn.setStyleSheet(Theme.button_success_small())
        self.table.setStyleSheet(Theme.table_widget())

    def set_token(self, token):
        self.token = token
        self.load_users()

    def _get_api_url(self, endpoint):
        host = self.config.get("server_ip", LOCAL_SERVER_HOST)
        port = self.config.get("server_port", SERVER_PORT)
        return f"http://{host}:{port}/api/admin/{endpoint}"

    def load_users(self):
        if not self.token:
            return
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            resp_users = requests.get(self._get_api_url("users"), headers=headers, timeout=3)
            resp_online = requests.get(self._get_api_url("online"), headers=headers, timeout=3)
            if resp_users.status_code != 200:
                return

            p = theme_manager.get_palette()
            users = resp_users.json()
            online_map = {
                o.get("username"): o
                for o in (resp_online.json() if resp_online.status_code == 200 else [])
            }

            self.table.setRowCount(len(users))
            for i, u in enumerate(users):
                username = u.get("username", "")
                self.table.setItem(i, 0, QTableWidgetItem(username))

                is_online = username in online_map
                status = QTableWidgetItem("🟢 在线" if is_online else "⚫ 离线")
                status.setForeground(QColor(p.TEXT_SUCCESS) if is_online else QColor(p.TEXT_SECONDARY))
                self.table.setItem(i, 1, status)

                self.table.setItem(i, 2, QTableWidgetItem(u.get("name", "")))
                self.table.setItem(i, 3, QTableWidgetItem(str(u.get("role", "")).upper()))
                self.table.setItem(
                    i, 4, QTableWidgetItem(online_map[username].get("ip", "-") if is_online else "-")
                )
                created = str(u.get("created_at", ""))
                self.table.setItem(i, 5, QTableWidgetItem(created[:19] if created else "-"))

                del_btn = QPushButton("🗑️")
                del_btn.clicked.connect(lambda _, user=username: self.delete_user(user))
                del_btn.setStyleSheet(
                    f"background: transparent; color: {p.TEXT_DANGER}; border: none;"
                )
                self.table.setCellWidget(i, 6, del_btn)

        except Exception as e:
            print(f"Load failed: {e}")

    def add_user(self):
        dlg = UserDialog(self)
        if dlg.exec():
            try:
                requests.post(
                    self._get_api_url("users"),
                    json=dlg.get_data(),
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=3,
                )
                self.load_users()
            except Exception as e:
                logger.warning(e)

    def delete_user(self, username):
        if UIHelper.confirm(self, "确认", f"删除 {username}?"):
            try:
                requests.delete(
                    f"{self._get_api_url('users')}/{username}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=3,
                )
                self.load_users()
            except Exception as e:
                logger.warning(e)


class ConsolePage(QWidget):
    def _is_test_log(self, text):
        return is_test_log(text)

    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.init_ui()

        if hasattr(self.worker, "server_log_signal"):
            self.worker.server_log_signal.connect(self.append_server_log)

        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()

        self.log_tab = QWidget()
        l_layout = QVBoxLayout(self.log_tab)
        self.header = QLabel("🖥️ 云端日志流 (Server Logs)")
        l_layout.addWidget(self.header)

        self.console_log = QPlainTextEdit()
        self.console_log.setReadOnly(True)
        l_layout.addWidget(self.console_log)

        self.user_tab = UserManagerTab()
        self.test_tab = TestDashboard(self.worker)
        if hasattr(self.worker, "request_auto_fix"):
            self.test_tab.request_auto_report.connect(self.worker.request_auto_fix)

        QTimer.singleShot(1000, self.inject_token)

        self.tabs.addTab(self.test_tab, "🛠️ 单元测试 & 修复")
        self.tabs.addTab(self.log_tab, "运行日志")
        self.tabs.addTab(self.user_tab, "用户管理")
        layout.addWidget(self.tabs)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")
        self.tabs.setStyleSheet(
            f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background: {p.BG_SECONDARY};
                color: {p.TEXT_SECONDARY};
                padding: 10px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background: {p.ACCENT_PRIMARY};
                color: white;
                font-weight: bold;
            }}
            QTabBar::tab:hover {{
                background: {p.BG_TERTIARY};
            }}
            """
        )
        self.header.setStyleSheet(
            f"color: {p.TEXT_PRIMARY}; font-weight: bold; font-size: 14px;"
        )
        self.console_log.setStyleSheet(Theme.log_editor())

    def inject_token(self):
        parent = self.parent()
        while parent:
            if hasattr(parent, "user_profile"):
                self.user_tab.set_token(parent.user_profile.get("token"))
                break
            parent = parent.parent()

    def append_server_log(self, text):
        stripped = text.strip()

        # 测试日志不进入“运行日志”窗口
        if stripped.startswith("[测试日志]") or stripped.startswith("[TestLog]"):
            return

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {stripped}" if not stripped.startswith("[") else stripped
        self.console_log.appendPlainText(line)
        sb = self.console_log.verticalScrollBar()
        sb.setValue(sb.maximum())
