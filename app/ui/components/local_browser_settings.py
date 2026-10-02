"""本地浏览器连接设置；保存配置本身不启动浏览器或下载驱动。"""
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from app.core.config import ConfigManager
from app.core.driver.local_chrome import BrowserSetupError, validate_browser_url




class LocalBrowserSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("浏览器连接设置")
        self.setMinimumWidth(560)
        self.config = ConfigManager.load()
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "浏览器模式使用已安装的 Chrome。应用会打开独立的浏览器资料目录，"
            "不会读取普通 Chrome 的登录资料。请在打开的浏览器中自行登录目标网站。\n"
            "网址必须与站点适配器匹配；能打开网页不代表已支持该网站的对话操作。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.url_edit = QLineEdit(str(self.config.get("browser_start_url", "")))
        self.url_edit.setPlaceholderText("https://你的对话网站（留空打开空白页）")
        form.addRow("对话网站", self.url_edit)
        self.chrome_edit = QLineEdit(str(self.config.get("chrome_binary", "")))
        self.chrome_edit.setPlaceholderText("留空自动查找已安装的 Chrome")
        self.driver_edit = QLineEdit(str(self.config.get("chromedriver_path", "")))
        self.driver_edit.setPlaceholderText("留空使用已准备好的匹配驱动")
        for label, field in (("Chrome 程序", self.chrome_edit), ("ChromeDriver 程序", self.driver_edit)):
            row = QHBoxLayout()
            row.addWidget(field)
            browse = QPushButton("选择")
            browse.clicked.connect(lambda _=False, target=field: self._browse(target))
            row.addWidget(browse)
            form.addRow(label, row)
        layout.addLayout(form)
        self.download_check = QCheckBox("允许从 Chrome 官方源获取匹配的 ChromeDriver")
        self.download_check.setChecked(bool(self.config.get("browser_allow_driver_download", False)))
        self.download_check.setToolTip("需要联网，仅用于获取驱动；不自动下载 Chrome，不上传对话或登录资料")
        layout.addWidget(self.download_check)
        note = QLabel("保存后点“重新连接”。停止生成会请求网页停止当前回复；它不会删除网站会话。")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self, target):
        filename, _ = QFileDialog.getOpenFileName(self, "选择程序", target.text())
        if filename:
            target.setText(filename)

    def save(self):
        try:
            url = validate_browser_url(self.url_edit.text())
        except (ValueError, BrowserSetupError) as exc:
            QMessageBox.warning(self, "网址无效", str(exc))
            return
        config = ConfigManager.load()
        config.update(browser_start_url=url, chrome_binary=self.chrome_edit.text().strip(),
                      chromedriver_path=self.driver_edit.text().strip(), browser_source="external_chrome",
                      browser_allow_driver_download=self.download_check.isChecked())
        ConfigManager.save(config)
        self.accept()
