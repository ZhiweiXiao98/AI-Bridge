# filename: app/ui/login_window.py
import requests
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, 
                               QPushButton, QMessageBox, QFrame, QFormLayout, QApplication)
from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QFont, QPixmap
from app.ui.theme import Theme, Palette, theme_manager
from app.ui.pages.console_page import UIHelper
from app.core.app_constants import LOCAL_SERVER_HOST, SERVER_PORT

class LoginWindow(QWidget):
    login_success = Signal(object) 

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Bridge - 登录")
        self.resize(400, 500)
        self.settings = QSettings("AIBridge", "Login")
        
        self.init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        self.title_lbl = QLabel("AI Bridge")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_lbl)
        
        self.subtitle = QLabel("SaaS 协同开发平台")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle)

        self.form_frame = QFrame()
        self.form_layout = QVBoxLayout(self.form_frame)
        self.form_layout.setSpacing(15)

        self.server_ip = QLineEdit()
        self.server_ip.setPlaceholderText(f"服务器地址 (例如 {LOCAL_SERVER_HOST})")
        self.server_ip.setText(self.settings.value("last_ip", LOCAL_SERVER_HOST))
        
        self.username = QLineEdit()
        self.username.setPlaceholderText("账号")
        self.username.setText(self.settings.value("last_user", ""))
        
        self.password = QLineEdit()
        self.password.setPlaceholderText("密码")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self.do_login)

        self.lbl_ip = QLabel("服务器 IP")
        self.lbl_user = QLabel("账号")
        self.lbl_pwd = QLabel("密码")

        self.form_layout.addWidget(self.lbl_ip)
        self.form_layout.addWidget(self.server_ip)
        self.form_layout.addWidget(self.lbl_user)
        self.form_layout.addWidget(self.username)
        self.form_layout.addWidget(self.lbl_pwd)
        self.form_layout.addWidget(self.password)
        
        layout.addWidget(self.form_frame)

        self.btn_login = QPushButton("登 录")
        self.btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login.clicked.connect(self.do_login)
        layout.addWidget(self.btn_login)
        
        layout.addStretch()
        
        self.ver_lbl = QLabel("Client v5.6 (Themed)")
        self.ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.ver_lbl)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY};")
        
        self.title_lbl.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {p.        ACCENT_PRIMARY}; margin-bottom: 10px;")
        self.subtitle.setStyleSheet(f"font-size: 14px; color: {p.TEXT_SECONDARY};         margin-bottom: 30px;")
        
        self.form_frame.setStyleSheet(f"background-color: {p.BG_SECONDARY}; border-radius:         8px; padding: 10px;")
        
        input_style = f"""
            QLineEdit {{ 
                background-color: {p.BG_TERTIARY}; 
                border: 1px solid {p.BORDER}; 
                border-radius: 4px; 
                padding: 10px; 
                color: {p.TEXT_PRIMARY}; 
                font-size: 14px;
            }}
            QLineEdit:focus {{ border: 1px solid {p.ACCENT_PRIMARY}; }}
        """
        self.server_ip.setStyleSheet(input_style)
        self.username.setStyleSheet(input_style)
        self.password.setStyleSheet(input_style)
        
        self.lbl_ip.setStyleSheet(f"color: {p.TEXT_SECONDARY};")
        self.lbl_user.setStyleSheet(f"color: {p.TEXT_SECONDARY};")
        self.lbl_pwd.setStyleSheet(f"color: {p.TEXT_SECONDARY};")
        
        self.btn_login.setStyleSheet(Theme.button_primary().replace("font-size: 14px",         "font-size: 16px; padding: 12px;"))
        self.ver_lbl.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 10px;")

    def do_login(self):
        ip = self.server_ip.text().strip()
        user = self.username.text().strip()
        pwd = self.password.text() 
        
        if not ip or not user or not pwd:
            UIHelper.warning(self, "提示", "请填写完整信息")
            return

        self.btn_login.setEnabled(False)
        self.btn_login.setText("正在认证 (Timeout 30s)...")
        QApplication.processEvents()
        
        try:
            if not ip.startswith("http"):
                if ":" not in ip: target_url = f"http://{ip}:{SERVER_PORT}/api/login"
                else: target_url = f"http://{ip}/api/login"
            else: target_url = f"{ip}/api/login"

            resp = requests.post(
                target_url, 
                json={"username": user, "password": pwd}, 
                timeout=30,
                proxies={"http": None, "https": None} 
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.settings.setValue("last_ip", ip)
                self.settings.setValue("last_user", user)
                
                user_profile = {
                    "username": data["username"],
                    "role": data["role"],
                    "token": data["token"],
                    "server_ip": ip
                }
                self.login_success.emit(user_profile)
                self.close()
            else:
                UIHelper.warning(self, "登录失败", f"认证错误: {resp.status_code}\n服务器返回                : {resp.text}")
        except Exception as e:
            UIHelper.warning(self, "连接错误", f"无法连接到服务器:\n{e}\n\n(请确认 IP 地址是            否为服务端 IP)")
        finally:
            self.btn_login.setEnabled(True)
            self.btn_login.setText("登 录")