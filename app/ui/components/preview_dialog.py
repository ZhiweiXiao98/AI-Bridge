import logging
# filename: app/ui/components/preview_dialog.py
import difflib
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTextEdit, QProgressBar, QWidget, QSplitter)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from app.ui.theme import Theme, theme_manager
from app.core.utils.pseudocode_generator import PseudocodeGenerator
from app.core.logging import get_logger

logger = get_logger("app.ui.preview_dialog", side="ui")

class CodePreviewDialog(QDialog):
    """
    代码预览对话框 - 逐行对齐版
    左侧：Diff 差异视图（红绿标记）
    右侧：逐行对应的中文伪代码
    """
    def __init__(self, filename=None, parent=None, **kwargs):
        super().__init__(parent)
        
        self.filename = filename or "Untitled"
        self.setWindowFlags(
            Qt.WindowType.Dialog | 
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setWindowTitle(f"代码审查: {self.filename}")
        self.resize(1400, 850)
        
        self.generator = PseudocodeGenerator()
        self.current_code = ""
        self.old_code = None
        
        self.init_ui(self.filename)
        
        try:
            theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme()
        except Exception as e:
            logger.warning(e)

    def init_ui(self, filename):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 极简标题栏
        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 0, 10, 0)
        title_layout.setSpacing(8)
        
        self.lbl_file = QLabel(f"📄 {filename}")
        self.lbl_status = QLabel("")
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(2)
        self.progress.setFixedWidth(80)
        self.progress.hide()
        
        title_layout.addWidget(self.lbl_file)
        title_layout.addWidget(self.progress)
        title_layout.addStretch()
        title_layout.addWidget(self.lbl_status)
        
        layout.addWidget(title_bar)
        
        # 主内容区：左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧容器
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        
        self.left_label = QLabel("📝 Diff")
        self.left_label.setFixedHeight(22)
        left_layout.addWidget(self.left_label)
        
        self.diff_editor = QTextEdit()
        self.diff_editor.setReadOnly(True)
        self.diff_editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        left_layout.addWidget(self.diff_editor)
        
        # 右侧容器
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        self.right_label = QLabel("🇨🇳 伪代码")
        self.right_label.setFixedHeight(22)
        right_layout.addWidget(self.right_label)
        
        self.pseudo_editor = QTextEdit()
        self.pseudo_editor.setReadOnly(True)
        self.pseudo_editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        right_layout.addWidget(self.pseudo_editor)
        
        # 设置等宽字体
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.diff_editor.setFont(font)
        self.pseudo_editor.setFont(font)
        
        # 同步滚动
        self.diff_editor.verticalScrollBar().valueChanged.connect(
            self.pseudo_editor.verticalScrollBar().setValue
        )
        self.pseudo_editor.verticalScrollBar().valueChanged.connect(
            self.diff_editor.verticalScrollBar().setValue
        )
        
        splitter.addWidget(left_container)
        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
        
        # 紧凑的底部按钮栏
        btn_bar = QWidget()
        btn_bar.setFixedHeight(40)
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(10, 5, 10, 5)
        btn_layout.setSpacing(8)
        
        self.btn_copy_pseudo = QPushButton("📋 复制")
        self.btn_copy_pseudo.setFixedWidth(70)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setFixedWidth(70)
        
        self.btn_copy_pseudo.clicked.connect(self.copy_pseudocode)
        self.btn_close.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.btn_copy_pseudo)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        
        layout.addWidget(btn_bar)

    def apply_theme(self):
        p = theme_manager.get_palette()
        
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {p.BG_PRIMARY};
                color: {p.TEXT_PRIMARY};
            }}
        """)
        
        self.lbl_file.setStyleSheet(f"color: {p.ACCENT_PRIMARY}; font-size: 11px; font-weight: bold;")
        self.lbl_status.setStyleSheet(f"color: {p.BTN_WARNING}; font-size: 10px;")
        
        # 修复标题栏颜色
        label_style = f"""
            QLabel {{
                padding: 2px 8px;
                font-size: 11px;
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                border-bottom: 1px solid {p.BORDER};
            }}
        """
        self.left_label.setStyleSheet(label_style)
        self.right_label.setStyleSheet(label_style)
        
        self.progress.setStyleSheet(Theme.progress_bar())
        
        editor_style = f"""
            QTextEdit {{
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                border: none;
                padding: 6px;
            }}
        """
        self.diff_editor.setStyleSheet(editor_style)
        self.pseudo_editor.setStyleSheet(editor_style)
        
        self.btn_copy_pseudo.setStyleSheet(Theme.button_secondary())
        self.btn_close.setStyleSheet(Theme.button_primary())

    def update_content(self, new_text, old_text=None):
        """更新内容：基于 Diff 逐行生成伪代码"""
        if new_text.startswith("⚠️") or new_text.startswith("❌"):
            p = theme_manager.get_palette()
            self.diff_editor.setHtml(f"<div style='color:{p.TEXT_DANGER}; padding:20px;'>{new_text}</div>")
            self.pseudo_editor.clear()
            return
        
        self.current_code = new_text
        self.old_code = old_text
        
        # 生成 Diff HTML 和对应的伪代码 HTML（同时生成，确保对齐）
        diff_html, pseudo_html = self.generate_aligned_content(new_text, old_text)
        self.diff_editor.setHtml(diff_html)
        self.pseudo_editor.setHtml(pseudo_html)

    def generate_aligned_content(self, new_text, old_text):
        """同时生成 Diff 和对应的伪代码（确保行号对齐）"""
        p = theme_manager.get_palette()
        is_light = p.BG_PRIMARY.upper().startswith("#F")
        
        # 计算最大行号，确定行号列宽度
        lines_new = new_text.splitlines()
        max_line_num = len(lines_new)
        line_num_width = max(30, len(str(max_line_num)) * 8 + 8)
        
        # 颜色配置
        c_add_bg = "#DCFCE7" if is_light else "#1E3A2F"
        c_add_fg = "#15803D" if is_light else "#A6E22E"
        c_del_bg = "#FEE2E2" if is_light else "#3A1E1E"
        c_del_fg = "#B91C1C" if is_light else "#F92672"
        c_text = p.TEXT_PRIMARY
        c_meta = p.TEXT_SECONDARY
        
        # 固定行高
        row_height = "18px"
        
        # 统一的单元格样式函数
        def line_num_style(num_text):
            return f"color:{c_meta}; text-align:right; padding:2px 4px; border-right:1px solid {p.BORDER}; width:{line_num_width}px; min-width:{line_num_width}px; max-width:{line_num_width}px; user-select:none; vertical-align:top; font-size:11px; height:{row_height}; line-height:{row_height};"
        
        def code_cell_style(color, bg=None):
            base = f"padding:2px 8px; color:{color}; vertical-align:top; height:{row_height}; line-height:{row_height};"
            if bg:
                base += f" background:{bg};"
            return base
        
        # 如果没有旧代码，显示全新代码
        if old_text is None:
            diff_rows = []
            pseudo_rows = []
            
            for i, line in enumerate(lines_new, 1):
                safe_line = self.escape_html(line)
                pseudo_line = self.generate_line_pseudo(line)
                safe_pseudo = self.escape_html(pseudo_line)
                
                diff_rows.append(f"<tr style='height:{row_height};'><td style='{line_num_style(i)}'>{i}</td><td style='{code_cell_style(c_add_fg, c_add_bg)}'>{safe_line}</td></tr>")
                pseudo_rows.append(f"<tr style='height:{row_height};'><td style='{line_num_style(i)}'>{i}</td><td style='{code_cell_style(c_text)}'>{safe_pseudo}</td></tr>")
            
            diff_html = f"<table width='100%' cellspacing='0' cellpadding='0' style='font-family:Consolas; font-size:11px; border-collapse:collapse; table-layout:fixed;'>{''.join(diff_rows)}</table>"
            pseudo_html = f"<table width='100%' cellspacing='0' cellpadding='0' style='font-family:Consolas; font-size:11px; border-collapse:collapse; table-layout:fixed;'>{''.join(pseudo_rows)}</table>"
            return diff_html, pseudo_html
        
        # 有旧代码，生成 Diff
        lines_old = old_text.splitlines()
        diff = list(difflib.unified_diff(lines_old, lines_new, lineterm='', n=10000))
        
        # 跳过头部信息
        start_idx = 0
        for i, line in enumerate(diff):
            if line.startswith('@@'):
                start_idx = i + 1
                break
        
        valid_diff = diff[start_idx:]
        diff_rows = []
        pseudo_rows = []
        line_num = 1
        
        for line in valid_diff:
            # 跳过 "\ No newline at end of file" 行
            if line.startswith('\\'):
                continue
            
            code_line = line[1:] if len(line) > 1 else ""
            safe_line = self.escape_html(code_line)
            
            if line.startswith('+'):
                # 新增行
                pseudo_line = self.generate_line_pseudo(code_line)
                safe_pseudo = self.escape_html(pseudo_line)
                
                diff_rows.append(f"<tr style='background:{c_add_bg}; height:{row_height};'><td style='{line_num_style(line_num)}'>{line_num}</td><td style='{code_cell_style(c_add_fg)}'>{safe_line}</td></tr>")
                pseudo_rows.append(f"<tr style='height:{row_height};'><td style='{line_num_style(line_num)}'>{line_num}</td><td style='{code_cell_style(c_text)}'>{safe_pseudo}</td></tr>")
                line_num += 1
                
            elif line.startswith('-'):
                # 删除行
                diff_rows.append(f"<tr style='background:{c_del_bg}; height:{row_height};'><td style='{line_num_style('-')}'>-</td><td style='{code_cell_style(c_del_fg)}'>{safe_line}</td></tr>")
                pseudo_rows.append(f"<tr style='height:{row_height};'><td style='{line_num_style('-')}'>-</td><td style='{code_cell_style(c_meta)}; font-style:italic;'>(已删除)</td></tr>")
                
            else:
                # 未变更行
                pseudo_line = self.generate_line_pseudo(code_line)
                safe_pseudo = self.escape_html(pseudo_line)
                
                diff_rows.append(f"<tr style='height:{row_height};'><td style='{line_num_style(line_num)}'>{line_num}</td><td style='{code_cell_style(c_text)}'>{safe_line}</td></tr>")
                pseudo_rows.append(f"<tr style='height:{row_height};'><td style='{line_num_style(line_num)}'>{line_num}</td><td style='{code_cell_style(c_text)}'>{safe_pseudo}</td></tr>")
                line_num += 1
        
        diff_html = f"<table width='100%' cellspacing='0' cellpadding='0' style='font-family:Consolas; font-size:11px; border-collapse:collapse; table-layout:fixed;'>{''.join(diff_rows)}</table>"
        pseudo_html = f"<table width='100%' cellspacing='0' cellpadding='0' style='font-family:Consolas; font-size:11px; border-collapse:collapse; table-layout:fixed;'>{''.join(pseudo_rows)}</table>"
        
        return diff_html, pseudo_html

    def generate_line_pseudo(self, line):
        """为单行代码生成更易读的伪代码"""
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        indent_str = "  " * (indent // 4)  # 保持缩进
        
        # 空行
        if not stripped:
            return ""
        
        # 注释行（保持原样）
        if stripped.startswith('#'):
            return line
        
        # 导入语句
        if stripped.startswith('import '):
            module = stripped.replace('import ', '').strip()
            return f"{indent_str}导入 {module} 模块"
        
        if stripped.startswith('from '):
            parts = stripped.split(' import ')
            if len(parts) == 2:
                module = parts[0].replace('from ', '').strip()
                items = parts[1].strip()
                return f"{indent_str}从 {module} 导入 {items}"
        
        # 类定义
        if stripped.startswith('class '):
            parts = stripped.split('(')
            class_name = parts[0].replace('class ', '').strip().rstrip(':')
            if len(parts) > 1:
                parent = parts[1].rstrip('):').strip()
                return f"{indent_str}定义类 {class_name}（继承自 {parent}）"
            return f"{indent_str}定义类 {class_name}"
        
        # 函数定义
        if stripped.startswith('def '):
            func_part = stripped.split('(')[0].replace('def ', '').strip()
            params_part = stripped.split('(')[1].split(')')[0] if '(' in stripped else ""
            if params_part:
                return f"{indent_str}定义函数 {func_part}（参数：{params_part}）"
            return f"{indent_str}定义函数 {func_part}"
        
        # 返回语句
        if stripped.startswith('return '):
            value = stripped.replace('return ', '').strip()
            if value:
                return f"{indent_str}返回 {value}"
            return f"{indent_str}返回"
        
        # if 语句
        if stripped.startswith('if '):
            condition = stripped.replace('if ', '').rstrip(':').strip()
            return f"{indent_str}如果 {condition}"
        
        # elif 语句
        if stripped.startswith('elif '):
            condition = stripped.replace('elif ', '').rstrip(':').strip()
            return f"{indent_str}否则如果 {condition}"
        
        # else 语句
        if stripped.startswith('else:'):
            return f"{indent_str}否则"
        
        # for 循环
        if stripped.startswith('for '):
            loop_part = stripped.replace('for ', '').rstrip(':').strip()
            return f"{indent_str}遍历 {loop_part}"
        
        # while 循环
        if stripped.startswith('while '):
            condition = stripped.replace('while ', '').rstrip(':').strip()
            return f"{indent_str}当 {condition} 时循环"
        
        # try 语句
        if stripped.startswith('try:'):
            return f"{indent_str}尝试执行"
        
        # except 语句
        if stripped.startswith('except '):
            exception = stripped.replace('except ', '').rstrip(':').strip()
            if exception:
                return f"{indent_str}捕获 {exception} 异常"
            return f"{indent_str}捕获异常"
        
        # finally 语句
        if stripped.startswith('finally:'):
            return f"{indent_str}最终执行"
        
        # with 语句
        if stripped.startswith('with '):
            context = stripped.replace('with ', '').rstrip(':').strip()
            return f"{indent_str}使用 {context}"
        
        # 赋值语句
        if '=' in stripped and not any(op in stripped for op in ['==', '!=', '<=', '>=', '+=', '-=', '*=', '/=']):
            parts = stripped.split('=', 1)
            var_name = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ""
            if value:
                return f"{indent_str}设置 {var_name} = {value}"
            return f"{indent_str}设置 {var_name}"
        
        # 函数调用
        if '(' in stripped and ')' in stripped:
            func_name = stripped.split('(')[0].strip().split('.')[-1]
            return f"{indent_str}调用 {func_name}()"
        
        # 其他语句
        return f"{indent_str}{stripped}"

    def escape_html(self, text):
        """HTML 转义"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;")

    def copy_pseudocode(self):
        """复制伪代码到剪贴板"""
        try:
            pseudo_text = self.generator.generate(self.current_code)
            from PySide6.QtGui import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(pseudo_text)
            self.lbl_status.setText("✅ 已复制")
        except Exception as e:
            self.lbl_status.setText("❌ 失败")

    def set_loading(self, is_loading):
        """设置加载状态"""
        if is_loading:
            self.progress.show()
            self.diff_editor.setHtml("<div style='padding:20px;'>⏳ 加载中...</div>")
            self.pseudo_editor.clear()
            self.lbl_status.setText("加载中...")
        else:
            self.progress.hide()
            self.lbl_status.setText("")
