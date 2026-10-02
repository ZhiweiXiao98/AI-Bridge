"""实验聊天窗口 (Experimental Chat UI)

PySide6 测试窗口，连接 experimental/server.py :8200
用于验证上下文管理系统的完整链路

启动: python experimental/chat_ui.py
前提: experimental/server.py 已在 :8200 运行
"""

import sys
import json
import requests
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QStatusBar,
    QGroupBox, QSplitter, QListWidget, QListWidgetItem, QMenu,
    QInputDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QAction

API_BASE = "http://localhost:8200"


# ============================================================
# 后台线程
# ============================================================

class ChatWorker(QThread):
    reply_ready = Signal(str)
    error_occurred = Signal(str)
    tokens_updated = Signal(dict)

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def run(self):
        try:
            resp = requests.post(
                f"{API_BASE}/chat",
                json={"message": self.message},
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                self.reply_ready.emit(data["reply"])
                self.tokens_updated.emit(data["tokens_used"])
            else:
                self.error_occurred.emit(f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            self.error_occurred.emit(str(e))


class ApiWorker(QThread):
    """通用 API 调用线程"""
    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, method: str, url: str, data=None):
        super().__init__()
        self.method = method
        self.url = url
        self.data = data

    def run(self):
        try:
            if self.method == "GET":
                resp = requests.get(self.url, timeout=10)
            elif self.method == "POST":
                resp = requests.post(self.url, json=self.data or {}, timeout=10)
            elif self.method == "DELETE":
                resp = requests.delete(self.url, timeout=10)
            elif self.method == "PUT":
                resp = requests.put(self.url, json=self.data or {}, timeout=10)
            else:
                self.error_occurred.emit(f"未知方法: {self.method}")
                return

            if resp.status_code == 200:
                self.result_ready.emit(resp.json())
            else:
                self.error_occurred.emit(f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            self.error_occurred.emit(str(e))


# ============================================================
# 主窗口
# ============================================================

class ChatWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Context Manager 实验窗口")
        self.resize(1100, 700)
        self._worker = None
        self._api_worker = None
        self._init_ui()
        self._check_server()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        main_splitter = QSplitter(Qt.Horizontal)

        # ---- 左侧：对话列表 ----
        conv_group = QGroupBox("对话列表")
        conv_layout = QVBoxLayout(conv_group)

        btn_layout = QHBoxLayout()
        self.new_conv_btn = QPushButton("+ 新建")
        self.new_conv_btn.clicked.connect(self._new_conversation)
        btn_layout.addWidget(self.new_conv_btn)
        conv_layout.addLayout(btn_layout)

        self.conv_list = QListWidget()
        self.conv_list.setMinimumWidth(200)
        self.conv_list.setMaximumWidth(260)
        self.conv_list.itemClicked.connect(self._on_conv_clicked)
        self.conv_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.conv_list.customContextMenuRequested.connect(self._conv_context_menu)
        conv_layout.addWidget(self.conv_list)

        main_splitter.addWidget(conv_group)

        # ---- 中间：聊天区域 ----
        chat_group = QGroupBox("对话")
        chat_layout = QVBoxLayout(chat_group)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFont(QFont("Consolas", 11))
        chat_layout.addWidget(self.chat_display)

        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息，按 Enter 发送...")
        self.input_field.returnPressed.connect(self._send_message)
        input_layout.addWidget(self.input_field)

        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self.send_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_context)
        input_layout.addWidget(self.clear_btn)

        chat_layout.addLayout(input_layout)
        main_splitter.addWidget(chat_group)

        # ---- 右侧：Token 状态 ----
        status_group = QGroupBox("Token 状态")
        status_layout = QVBoxLayout(status_group)

        self.token_display = QTextEdit()
        self.token_display.setReadOnly(True)
        self.token_display.setFont(QFont("Consolas", 10))
        self.token_display.setMaximumWidth(300)
        status_layout.addWidget(self.token_display)

        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.clicked.connect(self._refresh_status)
        status_layout.addWidget(self.refresh_btn)

        main_splitter.addWidget(status_group)
        main_splitter.setSizes([220, 580, 300])

        layout.addWidget(main_splitter)
        self.statusBar().showMessage("就绪")

    # ============================================================
    # 服务检查
    # ============================================================

    def _check_server(self):
        try:
            resp = requests.get(f"{API_BASE}/health", timeout=3)
            if resp.status_code == 200:
                self.statusBar().showMessage("✅ 服务已连接")
                self._load_conversations()
            else:
                self.statusBar().showMessage("⚠️ 服务异常")
        except Exception:
            self.statusBar().showMessage("❌ 服务未启动，请先运行 server.py")

    # ============================================================
    # 对话列表管理
    # ============================================================

    def _load_conversations(self):
        """从服务端加载对话列表"""
        try:
            resp = requests.get(f"{API_BASE}/conversations", timeout=5)
            if resp.status_code == 200:
                convs = resp.json().get("conversations", [])
                self._update_conv_list(convs)
                # 加载当前活跃对话的历史
                self._load_active_history()
        except Exception as e:
            self.statusBar().showMessage(f"❌ 加载对话列表失败: {e}")

    def _update_conv_list(self, conversations: list):
        """更新对话列表 UI"""
        self.conv_list.clear()
        for conv in conversations:
            icon = conv.get("icon", "🤖")
            title = conv.get("title", "未命名")
            turns = conv.get("turns", 0)
            tokens = conv.get("tokens_used", 0)
            date = conv.get("date", "")
            active = conv.get("active", False)

            label = f"{icon} {title}"
            if turns > 0:
                label += f"({turns}轮)"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, conv["id"])
            item.setToolTip(f"ID: {conv['id']}\n日期: {date}\nTokens: {tokens}")

            if active:
                font = item.font()
                font.setBold(True)
                item.setFont(font)

            self.conv_list.addItem(item)
            if active:
                self.conv_list.setCurrentItem(item)

    def _load_active_history(self):
        """加载当前活跃对话的聊天历史"""
        try:
            resp = requests.get(f"{API_BASE}/history", timeout=5)
            if resp.status_code == 200:
                history = resp.json().get("history", [])
                self.chat_display.clear()
                for msg in history:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user":
                        self.chat_display.append(f"👤 {content}")
                    elif role == "assistant":
                        self.chat_display.append(f"🤖 {content}")
                if history:
                    self.chat_display.append("---")
                    self.chat_display.append("")
                self._refresh_status()
        except Exception:
            pass

    def _on_conv_clicked(self, item):
        """点击切换对话"""
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            resp = requests.post(f"{API_BASE}/conversations/{conv_id}/switch", timeout=5)
            if resp.status_code == 200:
                convs = resp.json().get("conversations", [])
                self._update_conv_list(convs)
                self._load_active_history()
                self.statusBar().showMessage(f"✅ 已切换对话")
        except Exception as e:
            self.statusBar().showMessage(f"❌ 切换失败: {e}")

    def _new_conversation(self):
        """新建对话"""
        title, ok = QInputDialog.getText(self, "新建对话", "对话标题:", text="新对话")
        if not ok or not title.strip():
            return
        try:
            resp = requests.post(
                f"{API_BASE}/conversations",
                json={"title": title.strip()},
                timeout=5,
            )
            if resp.status_code == 200:
                convs = resp.json().get("conversations", [])
                self._update_conv_list(convs)
                self.chat_display.clear()
                self.token_display.clear()
                self.statusBar().showMessage(f"✅ 已创建: {title}")
        except Exception as e:
            self.statusBar().showMessage(f"❌ 创建失败: {e}")

    def _conv_context_menu(self, pos):
        """对话列表右键菜单"""
        item = self.conv_list.itemAt(pos)
        if not item:
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        act_rename = QAction("✏️ 重命名", self)
        act_delete = QAction("🗑️ 删除", self)

        act_rename.triggered.connect(lambda: self._rename_conversation(conv_id))
        act_delete.triggered.connect(lambda: self._delete_conversation(conv_id))

        menu.addAction(act_rename)
        menu.addSeparator()
        menu.addAction(act_delete)
        menu.exec(self.conv_list.mapToGlobal(pos))

    def _rename_conversation(self, conv_id: str):
        """重命名对话"""
        new_title, ok = QInputDialog.getText(self, "重命名", "新标题:")
        if not ok or not new_title.strip():
            return
        try:
            resp = requests.put(
                f"{API_BASE}/conversations/{conv_id}/rename",
                json={"title": new_title.strip()},
                timeout=5,
            )
            if resp.status_code == 200:
                self._load_conversations()
                self.statusBar().showMessage(f"✅ 已重命名")
        except Exception as e:
            self.statusBar().showMessage(f"❌ 重命名失败: {e}")

    def _delete_conversation(self, conv_id: str):
        """删除对话"""
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这个对话吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            resp = requests.delete(f"{API_BASE}/conversations/{conv_id}", timeout=5)
            if resp.status_code == 200:
                convs = resp.json().get("conversations", [])
                self._update_conv_list(convs)
                self._load_active_history()
                self.statusBar().showMessage(f"✅ 已删除")
        except Exception as e:
            self.statusBar().showMessage(f"❌ 删除失败: {e}")

    # ============================================================
    # 聊天
    # ============================================================

    def _send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.chat_display.append(f"👤 {text}")
        self.chat_display.append("")
        self.input_field.clear()
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.statusBar().showMessage("⏳ 等待回复...")

        self._worker = ChatWorker(text)
        self._worker.reply_ready.connect(self._on_reply)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.tokens_updated.connect(self._on_tokens)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_reply(self, reply: str):
        self.chat_display.append(f"🤖 {reply}")
        self.chat_display.append("---")
        self.chat_display.append("")
        # 刷新对话列表（更新轮数等）
        self._load_conversations_silent()

    def _on_error(self, error: str):
        self.chat_display.append(f"❌ 错误: {error}")
        self.chat_display.append("")

    def _on_tokens(self, usage: dict):
        lines = []
        for layer in ["system", "long_term", "working", "short_term"]:
            if layer in usage:
                info = usage[layer]
                lines.append(f"{layer}: {info['used']}/{info['budget']}")
        lines.append("")
        lines.append(f"总计: {usage.get('total_used', 0)}/{usage.get('total_budget', 0)}")
        lines.append(f"利用率: {usage.get('utilization', 0)}%")
        lines.append(f"对话轮数: {usage.get('history_turns', 0)}")
        self.token_display.setPlainText(chr(10).join(lines))

    def _on_finished(self):
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_field.setFocus()
        self.statusBar().showMessage("✅ 就绪")

    def _load_conversations_silent(self):
        """静默刷新对话列表（不切换历史）"""
        try:
            resp = requests.get(f"{API_BASE}/conversations", timeout=3)
            if resp.status_code == 200:
                convs = resp.json().get("conversations", [])
                self._update_conv_list(convs)
        except Exception:
            pass

    def _clear_context(self):
        try:
            resp = requests.post(f"{API_BASE}/context/clear", timeout=5)
            if resp.status_code == 200:
                self.chat_display.clear()
                self.token_display.clear()
                self.statusBar().showMessage("✅ 上下文已清空")
                self._load_conversations_silent()
        except Exception as e:
            self.statusBar().showMessage(f"❌ 清空失败: {e}")

    def _refresh_status(self):
        try:
            resp = requests.get(f"{API_BASE}/context/status", timeout=5)
            if resp.status_code == 200:
                self._on_tokens(resp.json())
        except Exception as e:
            self.statusBar().showMessage(f"❌ 刷新失败: {e}")


# ============================================================
# 入口
# ============================================================

def main():
    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
