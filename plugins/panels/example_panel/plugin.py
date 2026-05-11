"""
示例面板插件

这是一个简单的示例插件，展示如何开发自定义面板。
"""

from PySide6.QtCore import Qt
from app.ui.plugins.base_panel_plugin import BasePanelPlugin
from app.ui.components.dockable_panel import DockablePanel

# 导入面板实现
try:
    from .panel import ExamplePanel
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from panel import ExamplePanel


class ExamplePanelPlugin(BasePanelPlugin):
    """示例面板插件类"""
    
    def __init__(self):
        """初始化插件"""
        super().__init__()
        
        # 设置插件元数据
        self.plugin_id = "example_panel"
        self.plugin_name = "示例面板"
        self.plugin_version = "1.0.0"
        self.plugin_author = "AI Bridge Team"
        self.plugin_description = "这是一个示例面板插件，展示如何开发自定义面板"
        self.plugin_icon = "🎨"
        
        # 设置面板配置
        self.default_area = Qt.DockWidgetArea.RightDockWidgetArea
        self.min_app_version = "1.0.0"
        
        # 插件配置
        self.config = {
            "auto_refresh": True,
            "refresh_interval": 5
        }
    
    def create_panel(self) -> DockablePanel:
        """
        创建面板实例
        
        Returns:
            DockablePanel: 面板实例
        """
        panel = ExamplePanel()
        
        # 应用配置
        if hasattr(panel, 'set_auto_refresh'):
            panel.set_auto_refresh(self.config.get('auto_refresh', True))
        
        if hasattr(panel, 'set_refresh_interval'):
            panel.set_refresh_interval(self.config.get('refresh_interval', 5))
        
        return panel
    
    def on_load(self) -> None:
        """插件加载时调用"""
        print(f"[{self.plugin_name}] 插件加载")
    
    def on_unload(self) -> None:
        """插件卸载时调用"""
        print(f"[{self.plugin_name}] 插件卸载")
    
    def on_enable(self) -> None:
        """插件启用时调用"""
        print(f"[{self.plugin_name}] 插件启用")
    
    def on_disable(self) -> None:
        """插件禁用时调用"""
        print(f"[{self.plugin_name}] 插件禁用")
    
    def on_panel_created(self, panel: DockablePanel) -> None:
        """
        面板创建后调用
        
        Args:
            panel: 创建的面板实例
        """
        print(f"[{self.plugin_name}] 面板已创建: {panel.panel_id}")
    
    def on_panel_closed(self, panel: DockablePanel) -> None:
        """
        面板关闭时调用
        
        Args:
            panel: 被关闭的面板实例
        """
        print(f"[{self.plugin_name}] 面板已关闭: {panel.panel_id}")
    
    def get_config_schema(self) -> dict:
        """
        获取配置模式
        
        Returns:
            dict: 配置模式定义
        """
        return {
            "auto_refresh": {
                "type": "bool",
                "default": True,
                "description": "自动刷新"
            },
            "refresh_interval": {
                "type": "int",
                "default": 5,
                "min": 1,
                "max": 60,
                "description": "刷新间隔（秒）"
            }
        }
    
    def load_config(self, config: dict) -> None:
        """
        加载配置
        
        Args:
            config: 配置字典
        """
        self.config.update(config)
        print(f"[{self.plugin_name}] 配置已加载: {self.config}")
    
    def save_config(self) -> dict:
        """
        保存配置
        
        Returns:
            dict: 配置字典
        """
        return self.config.copy()
