# filename: app/ui/components/theme_editor.py
import json
import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QColorDialog, QScrollArea, QWidget, 
                               QGridLayout, QLineEdit, QMessageBox, QFrame,
                               QSpinBox, QAbstractSpinBox)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from app.ui.theme import DarkPalette, THEME_DIR, COLOR_DEFINITIONS, theme_manager

# === 翻译映射表 ===
TRANSLATION_MAP = {
    "Basic colors": "基本颜色",
    "Custom colors": "自定义颜色",
    "Add to Custom Colors": "添加到自定义",
    "Pick Screen Color": "屏幕取色",
    "OK": "确定",
    "Cancel": "取消",
    "&Add to Custom Colors": "添加到自定义(&A)",
    "&Pick Screen Color": "屏幕取色(&P)",
    "&Basic colors": "基本颜色",
    "&Custom colors": "自定义颜色",
    "Hue:": "色相(H):",
    "Sat:": "饱和(S):",
    "Val:": "亮度(V):",
    "Red:": "红(R):",
    "Green:": "绿(G):",
    "Blue:": "蓝(B):",
    "Alpha channel:": "透明度(A):",
    "HTML:": "HTML代码:"
}

class LocalizedColorDialog(QColorDialog):
    """
    原生 QColorDialog 的汉化与美化封装版
    """
    def __init__(self, initial_color, parent=None):
        super().__init__(initial_color, parent)
        self.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True) # 使用 Qt 自身的高级弹窗
        self.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, True)    # 显示透明度
        self.setWindowTitle("🎨 颜色选择器")
        
        # 应用美化样式
        self._apply_style()
        
        # [Hack] 强制汉化：因为官方翻译文件可能缺失，我们手动遍历子控件改名
        # 延时执行以确保控件已创建
        QTimer.singleShot(0, self._hack_translate)

    def _apply_style(self):
        p = theme_manager.get_palette()
        # 针对 Qt Color Dialog 的特定样式微调
        self.setStyleSheet(f"""
            QDialog {{ background-color: {p.BG_SECONDARY}; color: {p.TEXT_PRIMARY}; }}
            QLabel {{ color: {p.TEXT_PRIMARY}; }}
            
            /* 输入框美化 */
            QSpinBox {{ 
                background-color: {p.BG_TERTIARY}; 
                color: {p.TEXT_PRIMARY}; 
                border: 1px solid {p.BORDER}; 
                border-radius: 4px;
                padding: 2px;
            }}
            QLineEdit {{
                background-color: {p.BG_TERTIARY}; 
                color: {p.TEXT_PRIMARY}; 
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 2px;
            }}
            
            /* 按钮美化 */
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 60px;
            }}
            QPushButton:hover {{
                background-color: {p.BORDER};
            }}
            QPushButton:pressed {{
                background-color: {p.ACCENT_PRIMARY};
                color: white;
            }}
        """)

    def _hack_translate(self):
        """暴力遍历所有子控件，根据文本内容进行替换"""
        # 1. 替换 Label 和 Button
        for widget in self.findChildren((QLabel, QPushButton)):
            text = widget.text().strip()
            if text in TRANSLATION_MAP:
                widget.setText(TRANSLATION_MAP[text])
        
        # 2. 某些内部 Label 可能比较隐蔽，根据内容特征再次尝试
        for label in self.findChildren(QLabel):
            txt = label.text()
            # 处理带快捷键的文本 (&H)
            clean_txt = txt.replace("&", "")
            if clean_txt in TRANSLATION_MAP:
                label.setText(TRANSLATION_MAP[clean_txt])
            elif txt in TRANSLATION_MAP:
                label.setText(TRANSLATION_MAP[txt])

class ColorButton(QPushButton):
    def __init__(self, color_hex, parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.setFixedSize(90, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_style()
        self.clicked.connect(self.pick_color)

    def update_style(self):
        c = QColor(self.color_hex)
        yiq = ((c.red()*299) + (c.green()*587) + (c.blue()*114)) / 1000
        fg_color = 'black' if yiq >= 128 else 'white'
        
        self.setText(self.color_hex)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.color_hex}; 
                border: 1px solid #555; 
                border-radius: 4px;
                color: {fg_color};
                font-family: Consolas;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border: 1px solid #FFF;
            }}
        """)

    def pick_color(self):
        # 使用我们的汉化版 Dialog
        dlg = LocalizedColorDialog(QColor(self.color_hex), self)
        if dlg.exec():
            color = dlg.currentColor()
            if color.isValid():
                # 保持 HexARGB 格式 (包含透明度)
                self.color_hex = color.name(QColor.NameFormat.HexArgb).upper()
                self.update_style()

class ThemeEditorDialog(QDialog):
    def __init__(self, parent=None, base_theme_data=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 主题工坊 (Theme Studio)")
        self.resize(700, 800)
        
        self.palette_data = {k: v for k, v in DarkPalette.__dict__.items() if not k.startswith("__")}
        if base_theme_data:
            self.palette_data.update(base_theme_data)
            
        self.inputs = {}
        self.init_ui()
        
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 1. 顶部：元数据区
        self.header_frame = QFrame()
        h_layout = QHBoxLayout(self.header_frame)
        h_layout.setContentsMargins(15, 15, 15, 15)
        
        self.lbl_name = QLabel("📝 主题名称:")
        self.name_edit = QLineEdit("MyCustomTheme")
        self.name_edit.setPlaceholderText("例如: CyberPunk")
        h_layout.addWidget(self.lbl_name)
        h_layout.addWidget(self.name_edit)
        main_layout.addWidget(self.header_frame)
        
        # 2. 颜色编辑区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(content)
        self.grid.setVerticalSpacing(15)
        self.grid.setHorizontalSpacing(20)
        self.grid.setColumnStretch(1, 1) 
        
        row = 0
        self.group_titles = []
        self.labels = []
        
        groups = {
            "🖼️ 全局背景": ["BG_PRIMARY", "BG_SECONDARY", "BG_TERTIARY", "BORDER"],
            "🔤 文字系统": ["TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_SUCCESS", "TEXT_DANGER"],
            "✨ 品牌色": ["ACCENT_PRIMARY", "ACCENT_HOVER"],
            "🔘 功能按钮": ["BTN_SUCCESS", "BTN_SUCCESS_HOVER", "BTN_WARNING", "BTN_WARNING_HOVER", "BTN_DANGER", "BTN_DANGER_HOVER"]
        ,
            "🎨 标题栏": [
                "TITLEBAR_BG",
                "TITLEBAR_BORDER", 
                "TITLEBAR_TEXT",
                "TITLEBAR_BUTTON_HOVER",
                "TITLEBAR_BUTTON_PRESSED",
            ]}
        
        for group_name, keys in groups.items():
            title_frame = QFrame()
            title_frame.setFixedHeight(30)
            title_layout = QHBoxLayout(title_frame)
            title_layout.setContentsMargins(0, 5, 0, 0)
            lbl_title = QLabel(group_name)
            self.group_titles.append(lbl_title)
            title_layout.addWidget(lbl_title)
            
            self.grid.addWidget(title_frame, row, 0, 1, 3)
            row += 1
            
            for key in keys:
                if key not in self.palette_data: continue
                val = self.palette_data[key]
                cn_name, desc = COLOR_DEFINITIONS.get(key, (key, ""))
                
                lbl_name = QLabel(cn_name)
                lbl_desc = QLabel(desc)
                btn = ColorButton(val)
                self.inputs[key] = btn
                self.labels.append((lbl_name, lbl_desc))
                
                self.grid.addWidget(lbl_name, row, 0)
                self.grid.addWidget(lbl_desc, row, 1)
                self.grid.addWidget(btn, row, 2)
                row += 1
            
            spacer = QWidget(); spacer.setFixedHeight(10); self.grid.addWidget(spacer, row, 0); row += 1
            
        self.scroll.setWidget(content)
        main_layout.addWidget(self.scroll)
        
        # 3. 底部操作栏
        self.btn_frame = QFrame()
        btn_layout = QHBoxLayout(self.btn_frame)
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton("✅ 保存并应用主题")
        self.btn_save.clicked.connect(self.save_theme)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        main_layout.addWidget(self.btn_frame)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY};")
        
        self.header_frame.setStyleSheet(f"background-color: {p.BG_PRIMARY}; border-radius: 8px; border: 1px solid {p.BORDER};")
        self.name_edit.setStyleSheet(f"background: {p.BG_TERTIARY}; color: {p.TEXT_PRIMARY}; padding: 8px; border: 1px solid {p.BORDER}; border-radius: 4px; font-family: Consolas; font-weight: bold;")
        self.lbl_name.setStyleSheet(f"color: {p.TEXT_PRIMARY};")
        
        for t in self.group_titles:
            t.setStyleSheet(f"color: {p.ACCENT_PRIMARY}; font-weight: bold; font-size: 14px; border-bottom: 2px solid {p.BORDER};")
            
        for lname, ldesc in self.labels:
            lname.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {p.TEXT_PRIMARY};")
            ldesc.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 11px;")
            
        self.btn_frame.setStyleSheet(f"border-top: 1px solid {p.BORDER}; padding-top: 10px;")
        self.btn_cancel.setStyleSheet(f"background-color: transparent; color: {p.TEXT_SECONDARY}; padding: 10px; font-weight: bold;")
        self.btn_save.setStyleSheet(f"background-color: {p.BTN_SUCCESS}; color: white; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px;")

    def save_theme(self):
        name = self.name_edit.text().strip()
        if not name or not name.isalnum():
            QMessageBox.warning(self, "格式错误", "主题名称只能包含字母和数字")
            return
            
        new_data = {}
        for k, btn in self.inputs.items():
            new_data[k] = btn.color_hex
            
        if not os.path.exists(THEME_DIR):
            os.makedirs(THEME_DIR)
            
        path = os.path.join(THEME_DIR, f"{name}.json")
        try:
            with open(path, "w", encoding='utf-8') as f:
                json.dump(new_data, f, indent=4)
            
            QMessageBox.information(self, "保存成功", f"主题 '{name}' 已保存！")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法写入文件: {e}")