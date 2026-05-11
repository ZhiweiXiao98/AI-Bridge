# filename: app/ui/managers/panel_manager.py
"""
面板管理器 - 简化版（使用 Qt 默认停靠）
"""
import json
import os
from PySide6.QtCore import QObject, Signal, QPoint
from PySide6.QtWidgets import QMainWindow
from app.ui.components.icon_bar import IconBar
from app.ui.components.panel_icons import PanelIcons
from app.core.app_constants import APP_ROOT

class PanelManager(QObject):
    """面板管理器"""
    
    panel_registered = Signal(str)
    panel_shown = Signal(str)
    panel_hidden = Signal(str)
    all_panels_registered = Signal()
    
    def __init__(self, main_window: QMainWindow):
        super().__init__()
        
        self.main_window = main_window
        self.panels = {}
        self.panel_configs = {}
        self.panel_states = {}
        
        self.icon_bar = None
        
        # 配置文件路径
        self.config_dir = os.path.join(APP_ROOT, "config")
        self.layout_file = os.path.join(self.config_dir, "panel_layout.json")
        self.default_layout_file = os.path.join(self.config_dir, "panel_layout_default.json")
        
        os.makedirs(self.config_dir, exist_ok=True)
        
        # 面板注册计数器（用于事件驱动的布局恢复）
        self.expected_panels_count = 0
        self.registered_panels_count = 0
    
    def set_icon_bar(self, icon_bar: IconBar):
        """设置图标栏"""
        self.icon_bar = icon_bar
        self.icon_bar.icon_clicked.connect(self.on_icon_clicked)
    
    def register_panel(self, panel, config):
        """注册面板"""
        panel_id = config["id"]
        
        self.panels[panel_id] = panel
        self.panel_configs[panel_id] = config
        self.panel_states[panel_id] = "docked"
        
        panel.minimize_requested.connect(self.on_panel_minimize)
        panel.docked.connect(self.on_panel_docked)
        panel.closed.connect(self.on_panel_closed)
        
        self.main_window.addDockWidget(config.get("default_area"), panel)
        
        self.panel_registered.emit(panel_id)
        print(f"✅ 面板已注册: {panel_id}")
        
        # 更新计数器
        self.registered_panels_count += 1
        
        # 如果所有面板都已注册，发出信号
        if self.expected_panels_count > 0 and self.registered_panels_count >= self.expected_panels_count:
            self.all_panels_registered.emit()
            print(f"✅ 所有面板已注册 ({self.registered_panels_count}/{self.expected_panels_count})")
    
    def show_panel(self, panel_id):
        if panel_id in self.panels:
            panel = self.panels[panel_id]
            panel.show()
            self.panel_states[panel_id] = "docked"
            self.remove_icon(panel_id)
            self.panel_shown.emit(panel_id)
    
    def hide_panel(self, panel_id):
        if panel_id in self.panels:
            panel = self.panels[panel_id]
            panel.hide()
            self.panel_states[panel_id] = "hidden"
            self.remove_icon(panel_id)
            self.panel_hidden.emit(panel_id)
    
    def toggle_panel(self, panel_id):
        if panel_id in self.panels:
            panel = self.panels[panel_id]
            if panel.isVisible():
                self.hide_panel(panel_id)
            else:
                self.show_panel(panel_id)
    
    def on_panel_minimize(self, panel_id):
        if panel_id in self.panels:
            panel = self.panels[panel_id]
            panel.hide()
            self.add_icon(panel_id)
            self.panel_states[panel_id] = "minimized"
            print(f"➖ {panel_id} 已最小化")
    
    def on_panel_docked(self, panel_id):
        self.remove_icon(panel_id)
        self.panel_states[panel_id] = "docked"
        print(f"🔗 {panel_id} 已停靠")
    
    def on_panel_closed(self, panel_id):
        state = self.panel_states.get(panel_id, "docked")
        
        if state == "floating":
            self.panel_states[panel_id] = "minimized"
        else:
            self.remove_icon(panel_id)
            self.panel_states[panel_id] = "hidden"
    
    def on_icon_clicked(self, panel_id):
        if panel_id in self.panels:
            panel = self.panels[panel_id]
            
            if panel.isVisible() and self.panel_states[panel_id] == "floating":
                panel.hide()
                self.panel_states[panel_id] = "minimized"
            else:
                if self.icon_bar:
                    icon_bar_pos = self.icon_bar.mapToGlobal(QPoint(0, 0))
                    panel_pos = QPoint(icon_bar_pos.x() - 310, icon_bar_pos.y() + 50)
                    panel.show_floating(panel_pos)
                else:
                    panel.show()
                
                self.panel_states[panel_id] = "floating"
                if self.icon_bar:
                    self.icon_bar.set_icon_active(panel_id, True)
    
    def add_icon(self, panel_id):
        if self.icon_bar and panel_id in self.panel_configs:
            config = self.panel_configs[panel_id]
            icon = PanelIcons.get_icon(config["title"])
            self.icon_bar.add_panel_icon(
                panel_id,
                config.get("icon_name", config["title"][:2]),
                icon,
                config.get("description", "")
            )
    
    def remove_icon(self, panel_id):
        if self.icon_bar:
            self.icon_bar.remove_panel_icon(panel_id)
    
    def save_layout(self, filename=None):
        filename = filename or self.layout_file
        
        layout = {
            "panels": {},
            "icon_bar": {
                "visible": self.icon_bar is not None,
                "icons": list(self.icon_bar.icon_buttons.keys()) if self.icon_bar else []
            }
        }
        
        for panel_id, panel in self.panels.items():
            layout["panels"][panel_id] = panel.get_state()
            layout["panels"][panel_id]["state"] = self.panel_states.get(panel_id, "docked")
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(layout, f, indent=2, ensure_ascii=False)
        
        print(f"💾 布局已保存: {filename}")
    
    def load_layout(self, filename=None):
        filename = filename or self.layout_file
        
        if not os.path.exists(filename):
            print(f"⚠️ 布局文件不存在: {filename}")
            return False
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                layout = json.load(f)
            
            for panel_id, state in layout.get("panels", {}).items():
                if panel_id in self.panels:
                    panel = self.panels[panel_id]
                    panel.restore_state(state)
                    self.panel_states[panel_id] = state.get("state", "docked")
            
            icon_bar_data = layout.get("icon_bar", {})
            for panel_id in icon_bar_data.get("icons", []):
                self.add_icon(panel_id)
            
            print(f"📂 布局已加载: {filename}")
            return True
        
        except Exception as e:
            print(f"❌ 加载布局失败: {e}")
            return False
    
    def save_as_default(self):
        self.save_layout(self.default_layout_file)
        print("✅ 已保存为默认布局")
    
    def load_default(self):
        if os.path.exists(self.default_layout_file):
            return self.load_layout(self.default_layout_file)
        else:
            print("⚠️ 默认布局不存在")
            return False
    
    def reset_layout(self):
        for panel_id, panel in self.panels.items():
            panel.show()
            self.panel_states[panel_id] = "docked"
            self.remove_icon(panel_id)
        
        print("🔄 布局已重置")
    
    def get_panel(self, panel_id):
        return self.panels.get(panel_id)
    
    def get_all_panels(self):
        return self.panels.copy()

    def get_layout(self):
        """获取当前布局配置（返回新格式字典）"""
        panels_data = {}

        for panel_id, panel in self.panels.items():
            panels_data[panel_id] = {
                "visible": panel.isVisible(),
                "floating": panel.isFloating(),
                "area": self.main_window.dockWidgetArea(panel).value if not panel.isFloating() else None,
                "geometry": {
                    "x": panel.x(),
                    "y": panel.y(),
                    "width": panel.width(),
                    "height": panel.height()
                },
                "state": "floating" if panel.isFloating() else "docked"
            }

        # 返回新格式
        layout = {
            "panels": panels_data,
            "icon_bar": {
                "visible": self.icon_bar.isVisible() if self.icon_bar else True,
                "icons": list(self.panels.keys()) if self.icon_bar else []
            }
        }

        return layout

    def save_layout(self):
        """保存当前布局到默认配置文件（使用 Qt 状态机制）"""
        # 启动保护：避免启动时立即保存
        if getattr(self.main_window, 'is_loading', False):
            print("⏸️ 启动中，跳过布局保存")
            return
        
        import base64
        
        # 获取面板配置
        layout = self.get_layout()
        
        # 保存 Qt 主窗口状态（包含所有 DockWidget 的完整布局信息）
        qt_state = self.main_window.saveState()
        layout["qt_state"] = base64.b64encode(qt_state).decode('utf-8')
        
        # 保存到配置文件
        config_file = os.path.join(APP_ROOT, ".config", "panel_layout.json")
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(layout, f, indent=2)
        
        print(f"✅ 面板布局已保存到: {config_file}")

    def restore_layout(self, layout):
        """恢复布局配置（事件驱动版本）"""
        if not layout:
            print("⚠️ 布局配置为空")
            return
        
        from PySide6.QtCore import Qt, QTimer
        import base64

        # 🔧 优先使用 Qt 状态恢复（如果存在）
        if "qt_state" in layout:
            try:
                qt_state_str = layout["qt_state"]
                qt_state = base64.b64decode(qt_state_str.encode('utf-8'))
                
                # 立即恢复 Qt 状态（不再延迟）
                self.main_window.restoreState(qt_state)
                print("✅ 已使用 Qt 状态恢复布局")
                
                # 恢复后立即更新标题栏状态（处理 Tab 化面板）
                def update_title_bars():
                    """恢复 Qt 状态后，更新所有面板的标题栏"""
                    for panel_id, panel in self.panels.items():
                        if not panel:
                            continue
                        
                        # 检查面板是否被 Tab 化
                        parent = panel.parent()
                        is_tabbed = False
                        
                        if parent and not panel.isFloating():
                            from PySide6.QtWidgets import QMainWindow
                            if isinstance(parent, QMainWindow):
                                area = parent.dockWidgetArea(panel)
                                if area != 0:
                                    tabified = parent.tabifiedDockWidgets(panel)
                                    is_tabbed = len(tabified) > 0
                        
                        # 根据状态设置标题栏
                        if is_tabbed:
                            if hasattr(panel, 'simple_title_bar_widget'):
                                panel.setTitleBarWidget(panel.simple_title_bar_widget)
                        else:
                            if hasattr(panel, 'title_bar_widget'):
                                panel.setTitleBarWidget(panel.title_bar_widget)
                
                # 使用较短的延迟来更新标题栏
                QTimer.singleShot(100, update_title_bars)
                
                # 恢复可见性（延迟以确保 Qt 状态已应用）
                def restore_visibility():
                    if "panels" in layout:
                        panels_data = layout["panels"]
                        for panel_id, config in panels_data.items():
                            panel = self.panels.get(panel_id)
                            if panel:
                                if config.get('visible', False):
                                    panel.show()
                                else:
                                    panel.hide()
                
                # 使用较短的延迟（因为 Qt 状态已经恢复）
                QTimer.singleShot(200, restore_visibility)
                print("✅ 布局恢复完成")
                return
            except Exception as e:
                print(f"⚠️ Qt 状态恢复失败，使用备用方案: {e}")

        
        # 🔧 格式检测和转换
        if "panels" in layout:
            # 新格式: {"panels": {...}, "icon_bar": {...}}
            panels_data = layout["panels"]
            icon_bar_data = layout.get("icon_bar", {})
            print("📂 检测到新格式布局")
        else:
            # 旧格式: {panel_id: config}
            panels_data = layout
            icon_bar_data = {}
            print("📂 检测到旧格式布局（向后兼容）")
        
        # 第一阶段：恢复可见性、浮动状态和停靠区域
        for panel_id, config in panels_data.items():
            panel = self.panels.get(panel_id)
            if not panel:
                print(f"⚠️ 面板 {panel_id} 不存在")
                continue
            
            try:
                # 恢复浮动状态
                is_floating = config.get('floating', False)
                panel.setFloating(is_floating)
                
                # 恢复停靠区域
                if not is_floating and config.get('area') is not None:
                    area = Qt.DockWidgetArea(config['area'])
                    self.main_window.addDockWidget(area, panel)
                
                # 恢复可见性
                if config.get('visible', False):
                    panel.show()
                else:
                    panel.hide()
                
                # 浮动面板立即恢复几何
                geometry = config.get('geometry', {})
                if is_floating and geometry:
                    panel.setGeometry(
                        geometry.get('x', 100),
                        geometry.get('y', 100),
                        geometry.get('width', 400),
                        geometry.get('height', 300)
                    )
                
                print(f"✅ 已恢复面板: {panel_id}")
                
            except Exception as e:
                print(f"❌ 恢复面板 {panel_id} 失败: {e}")
        
        # 第二阶段：延迟恢复停靠面板大小（等待布局稳定）
        def restore_dock_sizes():
            docks_to_resize = []
            sizes_to_apply = []
            
            for panel_id, config in panels_data.items():
                panel = self.panels.get(panel_id)
                if not panel or config.get('floating', False):
                    continue
                
                geometry = config.get('geometry', {})
                if geometry:
                    docks_to_resize.append(panel)
                    # 根据停靠方向选择宽度或高度
                    area = config.get('area')
                    if area in [1, 2]:  # Left or Right
                        sizes_to_apply.append(geometry.get('width', 400))
                    else:  # Top or Bottom
                        sizes_to_apply.append(geometry.get('height', 300))
            
            if docks_to_resize:
                try:
                    self.main_window.resizeDocks(docks_to_resize, sizes_to_apply, Qt.Orientation.Horizontal)
                    print(f"✅ 已恢复 {len(docks_to_resize)} 个停靠面板的大小")
                except Exception as e:
                    print(f"⚠️ 恢复停靠面板大小失败: {e}")
        
        # 延迟 300ms 执行大小恢复（比之前的 500ms 更快）
        QTimer.singleShot(300, restore_dock_sizes)
        
        print("✅ 布局恢复完成")