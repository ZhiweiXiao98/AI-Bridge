# filename: app/ui/modeling_page.py
import os
import shutil
import subprocess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, 
                               QListWidget, QListWidgetItem, QPushButton, QLabel, QSplitter, 
                               QFrame, QMessageBox, QMenu, QInputDialog, QApplication)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QColor, QBrush, QAction, QCursor
from app.ui.components.editor import CodeEditor, PythonHighlighter
from app.core.project_context import ProjectContext
from app.ui.theme import Theme, Palette, theme_manager

class ModelingPage(QWidget):
    request_inject_prompt = Signal(str)
    request_run_script = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_path = os.path.abspath(os.path.join(ProjectContext.get().get_project_root(), "export", "code", "rhino"))
        self.init_ui()
        self.scan_projects()
        
        # [Theme]
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def init_ui(self):
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # === 左侧：项目树 ===
        left_panel = QWidget()
        l_layout = QVBoxLayout(left_panel); l_layout.setContentsMargins(10, 10, 5, 10)
        self.l_header = QLabel("📦 模型库 (Projects)")
        
        self.project_tree = QTreeWidget(); self.project_tree.setHeaderHidden(True)
        self.project_tree.itemClicked.connect(self.on_project_selected)
        self.project_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_tree.customContextMenuRequested.connect(self.show_project_menu)
        
        l_layout.addWidget(self.l_header); l_layout.addWidget(self.project_tree)
        
        # === 右侧：文件列表 + 预览 ===
        right_panel = QWidget()
        r_layout = QVBoxLayout(right_panel); r_layout.setContentsMargins(5, 10, 10, 10)
        
        # 工具栏
        toolbar = QHBoxLayout()
        self.lbl_current_project = QLabel("未选择项目")
        
        self.btn_run = QPushButton("▶ 运行脚本")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.clicked.connect(self.on_run_clicked)
        self.btn_run.setEnabled(False)

        self.btn_inject = QPushButton("📋 注入协议")
        self.btn_inject.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_inject.clicked.connect(self.on_inject_clicked)
        self.btn_inject.setEnabled(False)
        
        toolbar.addWidget(self.lbl_current_project)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_run)
        toolbar.addWidget(self.btn_inject)
        
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.on_file_dbl_click)
        self.file_list.itemClicked.connect(self.on_file_selected)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_menu)
        
        # 代码预览区
        preview_container = QWidget()
        pv_layout = QVBoxLayout(preview_container); pv_layout.setContentsMargins(0, 0, 0, 0)
        self.pv_header = QLabel("👁️ 代码预览 (Preview)")
        
        self.preview_editor = CodeEditor()
        self.preview_editor.setReadOnly(True)
        self.preview_highlighter = PythonHighlighter(self.preview_editor.document())
        
        pv_layout.addWidget(self.pv_header)
        pv_layout.addWidget(self.preview_editor)
        
        self.right_splitter.addWidget(self.file_list)
        self.right_splitter.addWidget(preview_container)
        self.right_splitter.setStretchFactor(0, 2)
        self.right_splitter.setStretchFactor(1, 3)
        
        r_layout.addLayout(toolbar)
        r_layout.addWidget(self.right_splitter)
        
        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setStretchFactor(1, 2)
        
        layout.addWidget(self.main_splitter)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY};")
        
        # Headers
        header_style = f"color: {p.TEXT_SECONDARY}; font-weight: bold; font-size: 12px; margin-bottom: 5px;"
        self.l_header.setStyleSheet(header_style)
        self.pv_header.setStyleSheet(header_style)
        
        # Labels
        self.lbl_current_project.setStyleSheet(f"color: {p.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;")
        
        # Buttons
        self.btn_run.setStyleSheet(Theme.button_primary())
        self.btn_inject.setStyleSheet(Theme.button_success_small())
        
        # Lists & Trees
        list_style = f"""
            QTreeWidget, QListWidget {{ 
                background-color: {p.BG_SECONDARY}; 
                border: 1px solid {p.BORDER}; 
                border-radius: 6px; 
                color: {p.TEXT_PRIMARY}; 
                outline: none;
            }} 
            QTreeWidget::item, QListWidget::item {{ padding: 8px; }} 
            QTreeWidget::item:hover, QListWidget::item:hover {{ background-color: {p.BG_TERTIARY}; }} 
            QTreeWidget::item:selected, QListWidget::item:selected {{ background-color: {p.ACCENT_PRIMARY}; color: white; }}
        """
        self.project_tree.setStyleSheet(list_style)
        self.file_list.setStyleSheet(list_style)
        
        # Splitter
        splitter_style = f"QSplitter::handle {{ background-color: {p.BORDER}; }}"
        self.main_splitter.setStyleSheet(splitter_style)
        self.right_splitter.setStyleSheet(splitter_style)
        
        # Preview Editor (Container style only, internal handled by CodeEditor)
        self.preview_editor.setStyleSheet(f"QPlainTextEdit {{ border: 1px solid {p.BORDER}; border-radius: 6px; }}")

    def scan_projects(self):
        self.project_tree.clear()
        if not os.path.exists(self.root_path): os.makedirs(self.root_path, exist_ok=True)
        root_item = QTreeWidgetItem(self.project_tree, ["📂 杂项 (Misc)"])
        root_item.setData(0, Qt.ItemDataRole.UserRole, self.root_path)
        try:
            for name in os.listdir(self.root_path):
                full_path = os.path.join(self.root_path, name)
                if os.path.isdir(full_path):
                    item = QTreeWidgetItem(self.project_tree, [f"🏗️ {name}"])
                    item.setData(0, Qt.ItemDataRole.UserRole, full_path)
        except: pass
        self.project_tree.expandAll()

    def on_project_selected(self, item, col):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.current_path = path
            project_name = item.text(0).replace("🏗️ ", "").replace("📂 ", "")
            self.lbl_current_project.setText(project_name)
            self.btn_inject.setEnabled(True)
            self.load_files(path)
            self.preview_editor.setPlainText("") 

    def load_files(self, folder_path):
        self.file_list.clear()
        self.btn_run.setEnabled(False)
        try:
            p = theme_manager.get_palette()
            files = [f for f in os.listdir(folder_path) if f.endswith(".py")]
            files.sort()
            for f in files:
                icon = "🚀" if "main" in f.lower() else "📜"
                color = p.TEXT_PRIMARY if "main" in f.lower() else p.TEXT_SECONDARY
                item = QListWidgetItem(f"{icon} {f}")
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(folder_path, f))
                item.setForeground(QBrush(QColor(color)))
                self.file_list.addItem(item)
        except: pass

    def on_file_selected(self, item):
        self.btn_run.setEnabled(True)
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.preview_editor.setPlainText(content)
            except Exception as e:
                self.preview_editor.setPlainText(f"# 无法读取文件预览: {e}")

    def show_project_menu(self, pos):
        self._show_dynamic_menu(self.project_tree, pos, is_project=True)

    def show_file_menu(self, pos):
        self._show_dynamic_menu(self.file_list, pos, is_project=False)

    def _show_dynamic_menu(self, widget, pos, is_project):
        item = widget.itemAt(pos)
        p = theme_manager.get_palette()
        
        menu = QMenu()
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {p.BG_SECONDARY}; color: {p.TEXT_PRIMARY}; border: 1px solid {p.BORDER}; }} 
            QMenu::item {{ padding: 5px 20px; }} 
            QMenu::item:selected {{ background-color: {p.ACCENT_PRIMARY}; color: white; }}
        """)
        
        if is_project:
            act_new = menu.addAction("✨ 新建项目")
            target_path = self.root_path
            act_open, act_del = None, None
            if item:
                target_path = item.data(0, Qt.ItemDataRole.UserRole)
                menu.addSeparator()
                act_open = menu.addAction("📂 打开所在目录")
                if target_path != self.root_path: act_del = menu.addAction("🗑️ 删除项目")
            
            action = menu.exec(widget.mapToGlobal(pos))
            if action == act_new: self.create_new_project()
            elif action == act_open: self.open_in_explorer(target_path)
            elif act_del and action == act_del: self.delete_path(target_path, is_dir=True)
        else:
            if not item: return
            path = item.data(Qt.ItemDataRole.UserRole)
            act_run = menu.addAction("▶ 运行")
            act_edit = menu.addAction("📝 编辑 (系统默认)")
            menu.addSeparator()
            act_rename = menu.addAction("✏️ 重命名")
            act_del = menu.addAction("🗑️ 删除")
            
            action = menu.exec(widget.mapToGlobal(pos))
            if action == act_run: self.request_run_script.emit(path)
            elif action == act_edit: os.startfile(path)
            elif action == act_rename: self.rename_file(path)
            elif action == act_del: self.delete_path(path, is_dir=False)

    def create_new_project(self):
        name, ok = QInputDialog.getText(self, "新建项目", "请输入项目名称:")
        if ok and name:
            new_path = os.path.join(self.root_path, name)
            if os.path.exists(new_path):
                QMessageBox.warning(self, "错误", "该项目已存在")
            else:
                os.makedirs(new_path)
                template = """# filename: rhino/{0}/main.py
try:
    import scriptcontext as sc
    import Rhino
    sc.doc = Rhino.RhinoDoc.ActiveDoc
except: pass

import rhinoscriptsyntax as rs

def main():
    rs.EnableRedraw(False)
    print("🚀 {0} 项目已初始化")
    # Logic here
    rs.EnableRedraw(True)

if __name__ == "__main__":
    main()
""".format(name)
                with open(os.path.join(new_path, "main.py"), "w", encoding="utf-8") as f:
                    f.write(template)
                self.scan_projects()

    def open_in_explorer(self, path):
        if os.name == 'nt': os.startfile(path)
        else: subprocess.call(['xdg-open', path])

    def delete_path(self, path, is_dir=False):
        name = os.path.basename(path)
        reply = QMessageBox.question(self, "确认删除", f"确定要删除 '{name}' 吗？\n此操作不可恢复！", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if is_dir: shutil.rmtree(path)
                else: os.remove(path)
                self.scan_projects()
                if not is_dir and hasattr(self, 'current_path'): self.load_files(self.current_path)
                self.preview_editor.setPlainText("")
            except Exception as e: QMessageBox.critical(self, "错误", f"删除失败: {e}")

    def rename_file(self, path):
        old_name = os.path.basename(path)
        new_name, ok = QInputDialog.getText(self, "重命名", "新文件名:", text=old_name)
        if ok and new_name:
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(path, new_path)
                if hasattr(self, 'current_path'): self.load_files(self.current_path)
            except Exception as e: QMessageBox.critical(self, "错误", f"重命名失败: {e}")

    def on_inject_clicked(self):
        project_name = self.lbl_current_project.text()
        prompt = f"[系统指令] Rhino 项目: {project_name}"
        self.request_inject_prompt.emit(prompt)

    def on_run_clicked(self):
        item = self.file_list.currentItem()
        if item: self.on_file_dbl_click(item)

    def on_file_dbl_click(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path: self.request_run_script.emit(path)