# filename: app/ui/theme.py
import os
import json
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from app.core.config import ConfigManager

THEME_DIR = "themes"

# === 颜色释义字典 (中文本地化) ===
COLOR_DEFINITIONS = {
    "BG_PRIMARY": ("主窗口背景", "应用的最底层背景，如大窗口的空白处。建议深色。"),
    "BG_SECONDARY": ("次级背景/容器", "侧边栏、卡片、弹窗的背景色。应比主背景稍亮。"),
    "BG_TERTIARY": ("三级背景/控件", "输入框、下拉框、进度条底色。应具有区分度。"),
    
    "TEXT_PRIMARY": ("主要文字", "标题、正文、重要信息的颜色。需与背景高对比。"),
    "TEXT_SECONDARY": ("次要文字", "标签、说明、未选中项的颜色。"),
    "TEXT_DANGER": ("错误/危险文字", "报错信息、删除按钮文字。通常为红色系。"),
    "TEXT_SUCCESS": ("成功/安全文字", "通过提示、运行成功。通常为绿色系。"),
    
    "BORDER": ("通用边框", "分割线、组件边框颜色。"),
    
    "ACCENT_PRIMARY": ("主强调色 (品牌色)", "主按钮、选中状态、高亮文字。决定应用的主色调。"),
    "ACCENT_HOVER": ("主强调色 (悬停)", "鼠标悬停在主按钮上时的颜色。"),
    
    "BTN_SUCCESS": ("成功按钮背景", "执行操作、添加、确认按钮的背景。"),
    "BTN_SUCCESS_HOVER": ("成功按钮 (悬停)", "成功按钮的悬停色。"),
    
    "BTN_DANGER": ("危险按钮背景", "停止、删除、清空按钮的背景。"),
    "BTN_DANGER_HOVER": ("危险按钮 (悬停)", "危险按钮的悬停色。"),
    
    "BTN_WARNING": ("警告按钮背景", "挂起、等待、次要操作按钮。"),
    "BTN_WARNING_HOVER": ("警告按钮 (悬停)", "警告按钮的悬停色。"),
}

class DarkPalette:
    BG_PRIMARY = "#111827"
    BG_SECONDARY = "#1F2937"
    BG_TERTIARY = "#374151"
    TEXT_PRIMARY = "#F3F4F6"
    TEXT_SECONDARY = "#9CA3AF"
    TEXT_DANGER = "#EF4444"
    TEXT_SUCCESS = "#10B981"
    BORDER = "#4B5563"
    ACCENT_PRIMARY = "#6366F1"
    ACCENT_HOVER = "#4F46E5"
    ACCENT_SECONDARY = "#818CF8"  # 次要强调色
    BTN_SUCCESS = "#059669"
    BTN_SUCCESS_HOVER = "#10B981"
    BTN_DANGER = "#DC2626"
    BTN_DANGER_HOVER = "#B91C1C"
    BTN_WARNING = "#D97706"
    BTN_WARNING_HOVER = "#F59E0B"
    
    # 标题栏颜色
    TITLEBAR_BG = "#1F2937"
    TITLEBAR_BORDER = "#374151"
    TITLEBAR_TEXT = "#F3F4F6"
    TITLEBAR_BUTTON_HOVER = "#374151"
    TITLEBAR_BUTTON_PRESSED = "#4B5563"

class LightPalette:
    BG_PRIMARY = "#F9FAFB"
    BG_SECONDARY = "#FFFFFF"
    BG_TERTIARY = "#E5E7EB"
    TEXT_PRIMARY = "#111827"
    TEXT_SECONDARY = "#4B5563"
    TEXT_DANGER = "#DC2626"
    TEXT_SUCCESS = "#059669"
    BORDER = "#D1D5DB"
    ACCENT_PRIMARY = "#4F46E5"
    ACCENT_HOVER = "#4338CA"
    ACCENT_SECONDARY = "#A5B4FC"  # 次要强调色
    BTN_SUCCESS = "#10B981"
    BTN_SUCCESS_HOVER = "#059669"
    BTN_DANGER = "#EF4444"
    BTN_DANGER_HOVER = "#DC2626"
    BTN_WARNING = "#F59E0B"
    BTN_WARNING_HOVER = "#D97706"
    
    # 标题栏颜色
    TITLEBAR_BG = "#FFFFFF"
    TITLEBAR_BORDER = "#E5E7EB"
    TITLEBAR_TEXT = "#111827"
    TITLEBAR_BUTTON_HOVER = "#F3F4F6"
    TITLEBAR_BUTTON_PRESSED = "#E5E7EB"

class CustomPalette:
    def __init__(self, data):
        default = {k: v for k, v in DarkPalette.__dict__.items() if not k.startswith("__")}
        default.update(data)
        for k, v in default.items():
            setattr(self, k, v)

class ThemeManager(QObject):
    theme_changed = Signal()

    def __init__(self):
        super().__init__()
        self._loaded_themes = {
            "Dark": DarkPalette,
            "Light": LightPalette
        }
        self.current_palette = DarkPalette
        self.load_custom_themes()
        self.reload_from_config()

    def load_custom_themes(self):
        if not os.path.exists(THEME_DIR):
            try: os.makedirs(THEME_DIR)
            except: pass
        else:
            for f in os.listdir(THEME_DIR):
                if f.endswith(".json"):
                    name = f[:-5]
                    try:
                        with open(os.path.join(THEME_DIR, f), "r", encoding='utf-8') as fp:
                            data = json.load(fp)
                            self._loaded_themes[name] = CustomPalette(data)
                    except Exception as e:
                        print(f"Failed to load theme {f}: {e}")

    def get_available_themes(self):
        self.load_custom_themes()
        return list(self._loaded_themes.keys())

    def reload_from_config(self):
        config = ConfigManager.load()
        theme_name = config.get("theme", "Dark")
        self.current_palette = self._loaded_themes.get(theme_name, DarkPalette)
        self.theme_changed.emit()

    def set_theme(self, theme_name):
        palette = self._loaded_themes.get(theme_name)
        if palette and palette is not self.current_palette:
            self.current_palette = palette
            self.theme_changed.emit()

    def get_palette(self):
        return self.current_palette

    def get_stylesheet(self):
        p = self.current_palette
        def c(name): return getattr(p, name, "#FF00FF")

        return f"""
            QMainWindow, QWidget {{
                background-color: {c('BG_PRIMARY')};
                color: {c('TEXT_PRIMARY')} !important;
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
            QScrollBar:vertical {{
                border: none;
                background: {c('BG_PRIMARY')};
                width: 10px;
                margin: 0px 0px 0px 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {c('BORDER')};
                min-height: 20px;
                border-radius: 5px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            QLineEdit, QTextEdit, QPlainTextEdit {{
                background-color: {c('BG_TERTIARY')};
                color: {c('TEXT_PRIMARY')} !important;
                border: 1px solid {c('BORDER')};
                border-radius: 6px;
                padding: 5px;
                selection-background-color: {c('ACCENT_PRIMARY')};
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border: 1px solid {c('ACCENT_PRIMARY')};
            }}
            QSplitter::handle {{
                background-color: {c('BORDER')};
            }}
            QListWidget {{
                background-color: {c('BG_SECONDARY')};
                border: 1px solid {c('BORDER')};
                border-radius: 6px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {c('BG_PRIMARY')};
            }}
            QListWidget::item:selected {{
                background-color: {c('BG_TERTIARY')};
                color: {c('ACCENT_PRIMARY')};
                border-left: 3px solid {c('ACCENT_PRIMARY')};
            }}
            QListWidget::item:hover {{
                background-color: {c('BG_TERTIARY')};
            }}
            QToolButton#SidebarBtn {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
                color: {c('TEXT_SECONDARY')};
                padding: 5px;
                font-size: 11px;
                font-weight: bold;
            }}
            QToolButton#SidebarBtn:hover {{
                background-color: {c('BG_TERTIARY')};
                color: {c('TEXT_PRIMARY')} !important;
            }}
            QToolButton#SidebarBtn:checked {{
                background-color: {c('ACCENT_PRIMARY')};
                color: #FFFFFF;
            }}
            QPushButton {{
                background-color: {c('BG_TERTIARY')};
                border: 1px solid {c('BORDER')};
                border-radius: 5px;
                padding: 6px 12px;
                color: {c('TEXT_PRIMARY')} !important;
            }}
            QPushButton:hover {{
                background-color: {c('BORDER')};
            }}
            QPushButton:pressed {{
                background-color: {c('BG_PRIMARY')};
            }}
            QMenu {{
                background-color: {c('BG_SECONDARY')};
                border: 1px solid {c('BORDER')};
                padding: 5px;
            }}
            QMenu::item {{
                padding: 5px 20px;
                color: {c('TEXT_PRIMARY')} !important;
            }}
            QMenu::item:selected {{
                background-color: {c('ACCENT_PRIMARY')};
                color: white;
            }}
            QDockWidget {{
                titlebar-close-icon: url(close.png);
                titlebar-normal-icon: url(float.png);
            }}
            QDockWidget::title {{
                background: {c('BG_SECONDARY')};
                color: {c('TEXT_PRIMARY')} !important;
                padding: 6px;
                border: 1px solid {c('BORDER')};
                font-weight: bold;
            }}
            QDockWidget::close-button, QDockWidget::float-button {{
                background: transparent;
                border: none;
                padding: 2px;
            }}
            QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
                background: {c('BG_TERTIARY')};
            }}
            QTabBar {{
                background-color: {c('BG_SECONDARY')};
            }}
            QTabBar::tab {{
                background-color: {c('BG_SECONDARY')};
                color: {c('TEXT_SECONDARY')};
                border: 1px solid {c('BORDER')};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 6px 12px;
                margin-right: 2px;
                min-width: 80px;
            }}
            QTabBar::tab:selected {{
                background-color: {c('BG_PRIMARY')};
                color: {c('TEXT_PRIMARY')} !important;
                border-bottom: 2px solid {c('ACCENT_PRIMARY')};
            }}
            QTabBar::tab:hover {{
                background-color: {c('BG_TERTIARY')};
                color: {c('TEXT_PRIMARY')} !important;
            }}
            QTabWidget::pane {{
                border: 1px solid {c('BORDER')};
                background-color: {c('BG_PRIMARY')};
            }}
            QWidget#titleBar {{
                background-color: {c('TITLEBAR_BG')};
                border-bottom: 1px solid {c('TITLEBAR_BORDER')};
                border-radius: 6px 6px 0px 0px;
            }}
            QWidget#simpleTitleBar {{
                background-color: {c('TITLEBAR_BG')};
                border-bottom: 1px solid {c('TITLEBAR_BORDER')};
                border-radius: 4px;
            }}
            QPushButton#titleBarButton {{
                background-color: transparent;
                color: {c('TEXT_SECONDARY')};
                border: none;
                border-radius: 4px;
                font-size: 18px;
                font-weight: bold;
            }}
            QPushButton#titleBarButton:hover {{
                background-color: {c('BG_TERTIARY')};
                color: {c('TEXT_PRIMARY')} !important;
            }}
            QPushButton#titleBarButton:pressed {{
                background-color: {c('BORDER')};
            }}
        """

theme_manager = ThemeManager()

def get_available_themes():
    return theme_manager.get_available_themes()

def get_palette():
    return theme_manager.get_palette()

class DynamicPalette:
    def __getattr__(self, name):
        return getattr(theme_manager.get_palette(), name)

Palette = DynamicPalette()

class Theme:
    """全局样式生成器"""
    
    @staticmethod
    def message_box():
        p = theme_manager.get_palette()
        return f"""
            QMessageBox {{ 
                background-color: {p.BG_SECONDARY}; 
                border: 1px solid {p.BORDER}; 
            }}
            QMessageBox QLabel {{ 
                color: {p.TEXT_PRIMARY}; 
                font-size: 13px; 
                background-color: transparent; 
            }}
            QPushButton {{ 
                background-color: {p.ACCENT_PRIMARY}; 
                color: white; 
                padding: 6px 12px; 
                border-radius: 4px; 
                min-width: 60px;
            }}
            QPushButton:hover {{ 
                background-color: {p.ACCENT_HOVER}; 
            }}
        """

    @staticmethod
    def stat_card():
        p = theme_manager.get_palette()
        return f"""
            QFrame {{ 
                background-color: {p.BG_SECONDARY}; 
                border: 1px solid {p.BORDER}; 
                border-radius: 8px; 
            }}
        """

    @staticmethod
    def card_title():
        p = theme_manager.get_palette()
        return f"color: {p.TEXT_SECONDARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;"

    @staticmethod
    def card_value(color=None):
        p = theme_manager.get_palette()
        c = color if color else p.TEXT_PRIMARY
        return f"color: {c}; font-size: 24px; font-weight: bold; border: none; background: transparent;"

    @staticmethod
    def panel_container():
        p = theme_manager.get_palette()
        return f"background-color: {p.BG_SECONDARY}; border-radius: 8px; border: 1px solid {p.BORDER};"

    @staticmethod
    def group_box():
        p = theme_manager.get_palette()
        return f"""
            QGroupBox {{ 
                color: {p.TEXT_SECONDARY}; 
                border: 1px solid {p.BORDER}; 
                border-radius: 6px; 
                margin-top: 10px; 
                padding-top: 10px; 
            }}
            QGroupBox::title {{ 
                subcontrol-origin: margin; 
                left: 10px; 
                padding: 0 5px; 
            }}
        """

    @staticmethod
    def log_editor():
        p = theme_manager.get_palette()
        is_light = p.BG_PRIMARY.lower().startswith("#f") or p.BG_PRIMARY.lower().startswith("#e")
        bg = "#F3F4F6" if is_light else "#0F172A"
        fg = "#1F2937" if is_light else "#D1D5DB"
        return f"""
            QPlainTextEdit {{ 
                background-color: {bg}; 
                color: {fg}; 
                font-family: Consolas; 
                font-size: 11px; 
                border: 1px solid {p.BORDER}; 
                border-radius: 6px; 
                padding: 10px; 
            }}
        """

    @staticmethod
    def progress_bar():
        p = theme_manager.get_palette()
        return f"""
            QProgressBar {{ 
                border: none; 
                background-color: {p.BG_TERTIARY}; 
                border-radius: 2px; 
            }} 
            QProgressBar::chunk {{ 
                background-color: {p.TEXT_SUCCESS}; 
                border-radius: 2px; 
            }}
        """

    @staticmethod
    def table_widget():
        p = theme_manager.get_palette()
        return f"""
            QTableWidget {{ 
                background-color: {p.BG_PRIMARY}; 
                border: 1px solid {p.BORDER}; 
                color: {p.TEXT_PRIMARY}; 
                gridline-color: {p.BORDER};
            }} 
            QHeaderView::section {{ 
                background-color: {p.BG_SECONDARY}; 
                color: {p.TEXT_PRIMARY}; 
                padding: 5px; 
                border: 1px solid {p.BG_PRIMARY}; 
            }}
            QTableWidget::item:selected {{
                background-color: {p.ACCENT_PRIMARY};
                color: white;
            }}
        """

    @staticmethod
    def button_primary():
        p = theme_manager.get_palette()
        return f"""
            QPushButton {{ 
                background-color: {p.ACCENT_PRIMARY}; 
                color: white; 
                font-weight: bold; 
                border-radius: 6px; 
                font-size: 14px; 
            }}
            QPushButton:hover {{ background-color: {p.ACCENT_HOVER}; }}
            QPushButton:disabled {{ background-color: {p.BORDER}; color: {p.TEXT_SECONDARY}; }}
        """

    @staticmethod
    def button_danger():
        p = theme_manager.get_palette()
        return f"""
            QPushButton {{ 
                background-color: {p.BTN_DANGER}; 
                color: white; 
                font-weight: bold; 
                border-radius: 6px; 
                font-size: 14px; 
            }}
            QPushButton:hover {{ background-color: {p.BTN_DANGER_HOVER}; }}
        """

    @staticmethod
    def button_success_small():
        p = theme_manager.get_palette()
        return f"""
            QPushButton {{
                background-color: {p.BTN_SUCCESS}; 
                color: white; 
                padding: 5px 10px; 
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {p.BTN_SUCCESS_HOVER}; }}
        """

    @staticmethod
    def button_warning_small():
        p = theme_manager.get_palette()
        return f"""
            QPushButton {{
                background-color: {p.BTN_WARNING}; 
                color: white; 
                padding: 5px 10px; 
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {p.BTN_WARNING_HOVER}; }}
        """

    @staticmethod
    def combo_box():
        p = theme_manager.get_palette()
        return f"""
            QComboBox {{
                background-color: {p.BG_TERTIARY}; 
                color: {p.TEXT_PRIMARY}; 
                border: 1px solid {p.BORDER}; 
                border-radius: 6px;
                padding: 5px 10px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox:focus {{
                border: 1px solid {p.ACCENT_PRIMARY};
            }}
        """

    @staticmethod
    def input_field():
        p = theme_manager.get_palette()
        return f"""
            QLineEdit, QSpinBox, QDoubleSpinBox {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 6px 10px;
                selection-background-color: {p.ACCENT_PRIMARY};
            }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {p.ACCENT_PRIMARY};
            }}
        """

    @staticmethod
    def card_container():
        p = theme_manager.get_palette()
        return f"""
            QFrame {{
                background-color: {p.BG_SECONDARY};
                border: 1px solid {p.BORDER};
                border-radius: 12px;
            }}
        """

    @staticmethod
    def section_title():
        p = theme_manager.get_palette()
        return f"color: {p.TEXT_PRIMARY}; font-size: 20px; font-weight: 700; border: none; background: transparent;"

    @staticmethod
    def section_subtitle():
        p = theme_manager.get_palette()
        return f"color: {p.TEXT_SECONDARY}; font-size: 12px; border: none; background: transparent;"
