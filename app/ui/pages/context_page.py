# filename: app/ui/pages/context_page.py
import os
import ast
import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, 
    QLabel, QPushButton, QSplitter, QFrame, QTextEdit, 
    QCheckBox, QTreeWidgetItemIterator, QApplication, QScrollArea,
    QComboBox, QTabWidget, QProgressBar
)
from PySide6.QtCore import Qt, Signal, QTimer, QPointF, QRectF, QThread
from PySide6.QtGui import QColor, QBrush, QPainter, QPen, QFont, QFontMetrics, QCursor, QPainterPath
from app.core.project_context import ProjectContext

from app.ui.theme import Theme, Palette, theme_manager
from app.core.services.context_scanner import ContextScanner

# =============================================================================
# Worker: ScannerThread (后台扫描线程)
# =============================================================================
class ScannerThread(QThread):
    progress_signal = Signal(str) # 进度消息
    finished_signal = Signal(object) # 结果数据包 (dict)

    def __init__(self, project_root):
        super().__init__()
        self.scanner = ContextScanner(project_root)

    def run(self):
        # 1. 执行扫描
        file_list, info_cache, _, _, stats = self.scanner.scan(
            progress_callback=lambda msg: self.progress_signal.emit(msg)
        )
        
        # 2. 后处理依赖关系 (CPU密集型)
        self.progress_signal.emit("正在构建依赖图谱...")
        dep_graph, rev_dep_graph = self.scanner.post_process_dependencies(file_list, info_cache)
        
        # 3. 统计最终关系数
        stats["total_relations"] = sum(len(v) for v in dep_graph.values())
        
        # 4. 打包结果
        result = {
            "file_list": file_list,
            "info_cache": info_cache,
            "dep_graph": dep_graph,
            "rev_dep_graph": rev_dep_graph,
            "stats": stats
        }
        self.finished_signal.emit(result)

# =============================================================================
# Component: DependencyRadar (依赖雷达图)
# =============================================================================
class DependencyRadar(QWidget):
    node_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.center_node = None
        self.parents = []   
        self.children = []  
        self.setMinimumHeight(350)
        self.setStyleSheet("background-color: #1E1E1E;")
        self.hit_list = []
        self.setMouseTracking(True)

    def set_data(self, center, parents, children):
        self.center_node = center
        self.parents = sorted(list(parents))
        self.children = sorted(list(children))
        self.update() 

    def mouseMoveEvent(self, event):
        pos = event.pos()
        is_hover = False
        for rect, _ in self.hit_list:
            if rect.contains(QPointF(pos)):
                is_hover = True
                break
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if is_hover else Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            for rect, path in self.hit_list:
                if rect.contains(QPointF(pos)):
                    self.node_clicked.emit(path)
                    return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.hit_list = [] 
        
        if not self.center_node:
            self._draw_placeholder(p)
            return
        
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        node_w, gap_x = 220, 280 
        
        self._draw_links(p, self.parents, cx - gap_x, cy, cx, cy, node_w, True)
        self._draw_links(p, self.children, cx, cy, cx + gap_x, cy, node_w, False)

        self._draw_node(p, cx, cy, self.center_node, theme_manager.get_palette().ACCENT_PRIMARY, True)
        self._draw_group(p, self.parents, cx - gap_x, cy, theme_manager.get_palette().BTN_WARNING)
        self._draw_group(p, self.children, cx + gap_x, cy, theme_manager.get_palette().TEXT_SUCCESS)
        self._draw_labels(p, cx, gap_x)

    def _draw_placeholder(self, p):
        p.setPen(QColor("#6B7280"))
        p.setFont(QFont("Microsoft YaHei", 12))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "👈 请在左侧选择一个文件以查看架构透视")

    def _draw_labels(self, p, cx, gap_x):
        p.setPen(QColor(theme_manager.get_palette().TEXT_SECONDARY))
        p.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        if self.parents: p.drawText(int(cx - gap_x - 100), 30, 200, 30, Qt.AlignmentFlag.AlignCenter, f"👈 被引用 ({len(self.parents)})")
        if self.children: p.drawText(int(cx + gap_x - 100), 30, 200, 30, Qt.AlignmentFlag.AlignCenter, f"👉 依赖 ({len(self.children)})")

    def _draw_group(self, p, nodes, x_base, cy, color):
        if not nodes: return
        limit = 12
        step_y = 50
        start_y = cy - ((min(len(nodes), limit) - 1) * step_y) / 2
        for i, text in enumerate(nodes[:limit]):
            self._draw_node(p, x_base, start_y + i * step_y, text, color)
        if len(nodes) > limit:
            p.setPen(QColor("#9CA3AF"))
            p.drawText(int(x_base - 50), int(start_y + limit * step_y), 100, 30, Qt.AlignmentFlag.AlignCenter, "...")

    def _draw_links(self, p, nodes, x1, y1, x2, y2, nw, is_left):
        if not nodes: return
        limit = 12
        step_y = 50
        start_y = y1 - ((min(len(nodes), limit) - 1) * step_y) / 2
        pen = QPen(QColor(theme_manager.get_palette().BORDER), 2)
        p.setPen(pen)
        for i in range(min(len(nodes), limit)):
            ny = start_y + i * step_y
            pt1 = QPointF(x1 + nw/2, ny) if is_left else QPointF(x1 + nw/2, y2)
            pt2 = QPointF(x2 - nw/2, y2) if is_left else QPointF(x2 - nw/2, ny)
            path = QPainterPath()
            path.moveTo(pt1)
            path.cubicTo(QPointF((pt1.x()+pt2.x())/2, pt1.y()), QPointF((pt1.x()+pt2.x())/2, pt2.y()), pt2)
            p.drawPath(path)

    def _draw_node(self, p, x, y, text, color, center=False):
        w, h = 200, 34
        r = QRectF(x - w/2, y - h/2, w, h)
        self.hit_list.append((r, text))
        bg = QColor(color); bg.setAlpha(200 if center else 40)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor("white"), 2) if center else QPen(QColor(color).lighter(), 1))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor(theme_manager.get_palette().TEXT_PRIMARY))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold if center else QFont.Weight.Normal))
        txt = text if len(text) < 30 else ".../" + os.path.basename(text)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, QFontMetrics(p.font()).elidedText(txt, Qt.TextElideMode.ElideMiddle, int(w-20)))

# =============================================================================
# Page: ContextPage (主界面)
# =============================================================================
class ContextPage(QWidget):
    request_push_pack = Signal(str, str) 

    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.project_root = ProjectContext.get().get_project_root()
        
        self.file_list = []
        self.dep_graph = {}
        self.rev_dep_graph = {}
        self.file_info_cache = {}
        self.file_nodes_map = {} 
        self.scan_thread = None
        
        self.init_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        self.apply_theme()
        
        QTimer.singleShot(500, self.start_scanning)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 1. Dashboard
        self.dashboard = QFrame()
        self.dashboard.setFixedHeight(60)
        d_layout = QHBoxLayout(self.dashboard)
        
        self.lbl_title = QLabel("🛸 架构全景")
        self.lbl_loading = QLabel("准备就绪")
        self.progress_bar = QProgressBar() 
        self.progress_bar.setRange(0, 0)   
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.hide()
        
        self.stats_files = QLabel("📁 --")
        self.stats_tokens = QLabel("🔤 --")
        self.stats_graph = QLabel("🕸️ --")
        
        self.btn_rescan = QPushButton("🔄 全局扫描")
        self.btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rescan.clicked.connect(self.start_scanning)
        
        d_layout.addWidget(self.lbl_title)
        d_layout.addSpacing(20)
        d_layout.addWidget(self.progress_bar)
        d_layout.addWidget(self.lbl_loading)
        d_layout.addStretch()
        d_layout.addWidget(self.stats_files)
        d_layout.addSpacing(15)
        d_layout.addWidget(self.stats_tokens)
        d_layout.addSpacing(15)
        d_layout.addWidget(self.stats_graph)
        d_layout.addSpacing(20)
        d_layout.addWidget(self.btn_rescan)
        
        layout.addWidget(self.dashboard)
        
        # 2. Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        
        # --- Left ---
        left_widget = QWidget()
        l_layout = QVBoxLayout(left_widget)
        l_layout.setContentsMargins(10, 10, 5, 10)
        
        filter_row = QHBoxLayout()
        self.combo_view = QComboBox()
        self.combo_view.addItems(["📂 物理视图", "🧠 逻辑视图", "🔒 安全视图"])
        self.combo_view.currentIndexChanged.connect(self.switch_tree_view)
        filter_row.addWidget(QLabel("视图模式:"))
        filter_row.addWidget(self.combo_view, 1)
        l_layout.addLayout(filter_row)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["组件名称", "功能描述", "大小", "安全级"])
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 200)
        self.tree.setColumnWidth(2, 60)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.itemClicked.connect(self.on_item_clicked)
        l_layout.addWidget(self.tree)
        
        sel_bar = QHBoxLayout()
        self.chk_auto_dep = QCheckBox("🔗 自动关联依赖")
        self.chk_auto_dep.setChecked(True)
        self.btn_sel_core = QPushButton("Core"); self.btn_sel_core.clicked.connect(lambda: self.select_by_keyword("app/core"))
        self.btn_sel_ui = QPushButton("UI"); self.btn_sel_ui.clicked.connect(lambda: self.select_by_keyword("app/ui"))
        self.btn_sel_all = QPushButton("全选/反选"); self.btn_sel_all.clicked.connect(self.toggle_select_all)
        
        sel_bar.addWidget(self.chk_auto_dep)
        sel_bar.addWidget(self.btn_sel_all)
        sel_bar.addStretch()
        sel_bar.addWidget(QLabel("速选:"))
        sel_bar.addWidget(self.btn_sel_core)
        sel_bar.addWidget(self.btn_sel_ui)
        l_layout.addLayout(sel_bar)
        
        self.splitter.addWidget(left_widget)
        
        # --- Right ---
        right_widget = QWidget()
        r_layout = QVBoxLayout(right_widget)
        r_layout.setContentsMargins(5, 10, 10, 10)
        
        self.radar = DependencyRadar()
        self.radar.node_clicked.connect(self.jump_to_file)
        r_layout.addWidget(self.radar, 3) 
        
        self.detail_tabs = QTabWidget()
        
        # 1. 结构
        self.txt_structure = QTextEdit(); self.txt_structure.setReadOnly(True)
        self.detail_tabs.addTab(self.txt_structure, "📐 代码骨架")
        
        # 2. 预览
        self.txt_preview = QTextEdit(); self.txt_preview.setReadOnly(True)
        self.txt_preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.detail_tabs.addTab(self.txt_preview, "📝 源码预览")
        
        # 3. [Fix] 动态读取导航图
        self.txt_map = QTextEdit(); self.txt_map.setReadOnly(True)
        self.detail_tabs.addTab(self.txt_map, "🗺️ 导航图")
        
        # 尝试读取文档
        doc_path = os.path.join(self.project_root, "docs", "PROJECT_STRUCTURE.md")
        if os.path.exists(doc_path):
            try:
                with open(doc_path, "r", encoding="utf-8") as f:
                    self.txt_map.setMarkdown(f.read())
            except Exception as e:
                self.txt_map.setPlainText(f"⚠️ 读取文档失败: {e}")
        else:
            self.txt_map.setHtml(f"<h3 style='color:gray'>⚠️ 未找到文档</h3><p>请确保文件存在: {doc_path}</p>")
        
        r_layout.addWidget(self.detail_tabs, 4)
        
        send_group = QFrame(); send_group.setObjectName("SendGroup")
        s_layout = QVBoxLayout(send_group); s_layout.setContentsMargins(10, 10, 10, 10)
        s_layout.addWidget(QLabel("🎯 任务目标 (Goal):"))
        self.goal_input = QTextEdit()
        self.goal_input.setPlaceholderText("描述任务（如：修复 worker.py 死锁）...")
        self.goal_input.setFixedHeight(50)
        s_layout.addWidget(self.goal_input)
        
        self.btn_pack = QPushButton("📦 生成快照并发送")
        self.btn_pack.setFixedHeight(45)
        self.btn_pack.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pack.clicked.connect(self.send_to_ai)
        s_layout.addWidget(self.btn_pack)
        r_layout.addWidget(send_group, 3)
        
        self.splitter.addWidget(right_widget)
        self.splitter.setSizes([450, 800])
        layout.addWidget(self.splitter)

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY};")
        self.dashboard.setStyleSheet(f"background-color: {p.BG_SECONDARY}; border-bottom: 1px solid {p.BORDER};")
        self.lbl_title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {p.TEXT_PRIMARY};")
        self.lbl_loading.setStyleSheet(f"color: {p.BTN_WARNING}; font-weight: bold;")
        stats_style = f"color: {p.ACCENT_PRIMARY}; font-weight: bold; background: {p.BG_TERTIARY}; padding: 4px 10px; border-radius: 4px; border: 1px solid {p.BORDER};"
        self.stats_files.setStyleSheet(stats_style); self.stats_tokens.setStyleSheet(stats_style); self.stats_graph.setStyleSheet(stats_style)
        self.btn_rescan.setStyleSheet(Theme.button_primary().replace("padding: 4px", "padding: 6px"))
        self.tree.setStyleSheet(Theme.table_widget()) 
        self.radar.setStyleSheet(f"background-color: {p.BG_SECONDARY}; border: 1px solid {p.BORDER}; border-radius: 8px;")
        self.detail_tabs.setStyleSheet(f"QTabWidget::pane {{ border: 1px solid {p.BORDER}; background: {p.BG_SECONDARY}; }} QTabBar::tab {{ background: {p.BG_TERTIARY}; color: {p.TEXT_SECONDARY}; padding: 6px 15px; }} QTabBar::tab:selected {{ background: {p.ACCENT_PRIMARY}; color: white; }}")
        editor_style = Theme.log_editor()
        self.txt_structure.setStyleSheet(editor_style)
        self.txt_preview.setStyleSheet(editor_style)
        self.txt_map.setStyleSheet(editor_style)
        self.goal_input.setStyleSheet(editor_style)
        self.findChild(QFrame, "SendGroup").setStyleSheet(f"background-color: {p.BG_SECONDARY}; border: 1px solid {p.BORDER}; border-radius: 8px;")
        self.btn_pack.setStyleSheet(Theme.button_success_small().replace("padding: 5px 10px;", "").replace("font-size: 14px", "font-size: 15px"))
        sub_btn_style = f"background-color: {p.BG_TERTIARY}; border: 1px solid {p.BORDER}; color: {p.TEXT_PRIMARY}; padding: 4px 10px; border-radius: 4px;"
        self.btn_sel_core.setStyleSheet(sub_btn_style); self.btn_sel_ui.setStyleSheet(sub_btn_style); self.btn_sel_all.setStyleSheet(sub_btn_style)

    def start_scanning(self):
        if self.scan_thread and self.scan_thread.isRunning(): return
        self.btn_rescan.setEnabled(False)
        self.progress_bar.show()
        self.lbl_loading.setText("正在扫描文件系统...")
        self.lbl_loading.show()
        self.scan_thread = ScannerThread(self.project_root)
        self.scan_thread.progress_signal.connect(self.lbl_loading.setText)
        self.scan_thread.finished_signal.connect(self.on_scan_finished)
        self.scan_thread.start()

    # [Fix] 兼容性别名：main_window.py 调用的是 refresh_data
    def refresh_data(self):
        self.start_scanning()

    def on_scan_finished(self, result):
        self.btn_rescan.setEnabled(True)
        self.progress_bar.hide()
        self.lbl_loading.hide()
        self.file_list = result["file_list"]
        self.file_info_cache = result["info_cache"]
        self.dep_graph = result["dep_graph"]
        self.rev_dep_graph = result["rev_dep_graph"]
        stats = result["stats"]
        self._build_tree_view()
        self.stats_files.setText(f"📁 {stats['total_files']} 文件")
        self.stats_tokens.setText(f"🔤 ~{stats['total_tokens']} Tokens")
        self.stats_graph.setText(f"🕸️ {stats['total_relations']} 引用")

    def _build_tree_view(self):
        self.tree.clear()
        self.file_nodes_map.clear()
        mode = self.combo_view.currentIndex()
        root_item = QTreeWidgetItem(self.tree, ["Project Root"])
        root_item.setExpanded(True)
        groups_cache = {}
        sorted_files = sorted(self.file_list, key=lambda x: x[0])
        
        for rel_path, full_path in sorted_files:
            info = self.file_info_cache.get(rel_path, {})
            filename = os.path.basename(rel_path)
            parent_node = root_item
            
            if mode == 0: 
                parts = rel_path.split("/")
                current_level = root_item
                for part in parts[:-1]:
                    found = None
                    for i in range(current_level.childCount()):
                        if current_level.child(i).text(0) == part:
                            found = current_level.child(i); break
                    if not found:
                        found = QTreeWidgetItem(current_level, [part, "", "", ""])
                        found.setIcon(0, QApplication.style().standardIcon(QApplication.style().StandardPixmap.SP_DirIcon))
                        found.setFlags(found.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                        found.setCheckState(0, Qt.CheckState.Unchecked)
                    current_level = found
                parent_node = current_level
            
            elif mode == 1: 
                group_name = "🧩 Misc"
                if "app/core" in rel_path: group_name = "🧠 Core (Brain)"
                elif "app/ui" in rel_path: group_name = "🎨 UI (Face)"
                elif "driver" in rel_path: group_name = "🚜 Driver (Hand)"
                elif "server" in rel_path: group_name = "☁️ Server"
                elif "tests" in rel_path: group_name = "🧪 Tests"
                if group_name not in groups_cache:
                    g_node = QTreeWidgetItem(root_item, [group_name])
                    g_node.setExpanded(True)
                    g_node.setFlags(g_node.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                    g_node.setCheckState(0, Qt.CheckState.Unchecked)
                    groups_cache[group_name] = g_node
                parent_node = groups_cache[group_name]

            elif mode == 2: 
                cat = info.get("category", "UNKNOWN")
                if cat == "CRITICAL": group_name = "🔴 核心架构 (需重启)"
                elif cat == "CLIENT_ONLY": group_name = "🔵 客户端逻辑 (热更)"
                else: group_name = "🟢 安全资源 (无感)"
                if group_name not in groups_cache:
                    g_node = QTreeWidgetItem(root_item, [group_name])
                    g_node.setExpanded(True)
                    g_node.setFlags(g_node.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                    g_node.setCheckState(0, Qt.CheckState.Unchecked)
                    groups_cache[group_name] = g_node
                parent_node = groups_cache[group_name]

            size_str = f"{info.get('size',0)/1024:.1f} KB"
            safe_lvl = info.get("category", "UNKNOWN")
            safe_icon = "🔒" if safe_lvl == "CRITICAL" else "🛡️" if safe_lvl == "CLIENT_ONLY" else "✅"
            doc = info.get("doc", "")
            if not doc and "test" in filename: doc = "Unit Test"
            
            item = QTreeWidgetItem(parent_node, [filename, doc, size_str, safe_icon])
            item.setData(0, Qt.ItemDataRole.UserRole, rel_path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            
            p = theme_manager.get_palette()
            if safe_lvl == "CRITICAL": item.setForeground(0, QBrush(QColor(p.TEXT_DANGER)))
            elif safe_lvl == "CLIENT_ONLY": item.setForeground(0, QBrush(QColor(p.ACCENT_PRIMARY)))
            
            self.file_nodes_map[rel_path] = item

    def switch_tree_view(self, index): self._build_tree_view()

    def jump_to_file(self, path):
        if path in self.file_nodes_map:
            item = self.file_nodes_map[path]
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
            self.on_item_clicked(item, 0)

    def on_item_clicked(self, item, col):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path: 
            self.radar.set_data(None, [], [])
            self.txt_structure.setHtml(f"<h3 style='color:gray'>📂 {item.text(0)}</h3>")
            return
        
        parents = self.rev_dep_graph.get(path, set())
        children = self.dep_graph.get(path, set())
        self.radar.set_data(path, parents, children)
        
        info = self.file_info_cache.get(path, {})
        p = theme_manager.get_palette()
        
        struct_html = f"<h2 style='color:{p.ACCENT_PRIMARY}'>{os.path.basename(path)}</h2>"
        struct_html += f"<p style='color:{p.TEXT_SECONDARY}'>{path}</p>"
        
        if info.get('doc'):
            struct_html += f"<div style='background-color:{p.BG_TERTIARY}; padding:5px; border-radius:4px;'><i>{info['doc']}</i></div><hr>"
        
        if info.get('classes'):
            struct_html += f"<h4 style='color:{p.TEXT_SUCCESS}'>📦 Classes ({len(info['classes'])}):</h4><ul>"
            for c in info['classes']: struct_html += f"<li>{c}</li>"
            struct_html += "</ul>"
            
        if info.get('funcs'):
            struct_html += f"<h4 style='color:{p.BTN_WARNING}'>ƒ Functions ({len(info['funcs'])}):</h4>"
            shown = info['funcs'][:10]
            struct_html += ", ".join(shown)
            if len(info['funcs']) > 10: struct_html += "..."
        
        self.txt_structure.setHtml(struct_html)
        
        try:
            full = os.path.join(self.project_root, path)
            with open(full, 'r', encoding='utf-8', errors='ignore') as f:
                head = "".join([next(f) for _ in range(50)])
            self.txt_preview.setPlainText(head)
        except: self.txt_preview.setPlainText("(无法读取文件内容)")

    def on_item_changed(self, item, col):
        if col == 0 and self.chk_auto_dep.isChecked() and item.checkState(0) == Qt.CheckState.Checked:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and path in self.dep_graph:
                deps = self.dep_graph[path]
                self.tree.blockSignals(True) 
                for dep in deps:
                    node = self.file_nodes_map.get(dep)
                    if node:
                        node.setCheckState(0, Qt.CheckState.Checked)
                        parent = node.parent()
                        while parent:
                            parent.setExpanded(True)
                            parent = parent.parent()
                self.tree.blockSignals(False)
        self.update_pack_stats()

    def update_pack_stats(self):
        count = 0; tokens = 0
        iterator = QTreeWidgetItemIterator(self.tree, QTreeWidgetItemIterator.IteratorFlag.Checked)
        while iterator.value():
            item = iterator.value()
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path: 
                count += 1
                info = self.file_info_cache.get(path, {})
                tokens += info.get('token', 0)
            iterator += 1
        self.btn_pack.setText(f"📦 生成快照 ({count} 文件, ~{tokens} Tokens)")

    def select_by_keyword(self, keyword):
        self.tree.blockSignals(True)
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and keyword in path:
                item.setCheckState(0, Qt.CheckState.Checked)
                parent = item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
            iterator += 1
        self.tree.blockSignals(False)
        self.update_pack_stats()

    def toggle_select_all(self):
        root = self.tree.invisibleRootItem()
        if root.childCount() == 0: return
        first_state = root.child(0).checkState(0)
        new_state = Qt.CheckState.Checked if first_state == Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            item.setCheckState(0, new_state)
            iterator += 1
        self.tree.blockSignals(False)
        self.update_pack_stats()

    def send_to_ai(self):
        paths = []
        iterator = QTreeWidgetItemIterator(self.tree, QTreeWidgetItemIterator.IteratorFlag.Checked)
        while iterator.value():
            item = iterator.value()
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path: paths.append(path)
            iterator += 1
        if not paths: return
        content = ""
        for p in paths:
            full = os.path.join(self.project_root, p)
            try:
                with open(full, 'r', encoding='utf-8', errors='ignore') as f: file_content = f.read()
                content += f"<<<AI_BRIDGE_FILE_START path={p}>>>\n{file_content}\n<<<AI_BRIDGE_FILE_END path={p}>>>\n\n"
            except: pass
        goal = self.goal_input.toPlainText().strip()
        self.request_push_pack.emit(content, goal)