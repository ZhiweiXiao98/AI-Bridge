"""
面板插件基类

定义了面板插件的标准接口和生命周期管理。
所有面板插件都应该继承这个基类。
"""

from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
from PySide6.QtCore import Qt
from app.ui.components.dockable_panel import DockablePanel


class BasePanelPlugin(ABC):
    """
    面板插件基类
    
    所有面板插件必须继承此类并实现抽象方法。
    """
    
    def __init__(self):
        """初始化插件"""
        # 插件元数据（子类必须设置）
        self.plugin_id: str = ""  # 插件唯一标识
        self.plugin_name: str = ""  # 插件显示名称
        self.plugin_version: str = "1.0.0"  # 插件版本
        self.plugin_author: str = ""  # 插件作者
        self.plugin_description: str = ""  # 插件描述
        self.plugin_icon: str = "📦"  # 插件图标（emoji 或图标名）
        
        # 面板配置
        self.default_area: Qt.DockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea
        self.min_app_version: str = "1.0.0"  # 最低应用版本要求
        
        # 插件依赖
        self.dependencies: list = []  # 依赖的其他插件 ID 列表
        
        # 运行时状态
        self._loaded: bool = False
        self._enabled: bool = True
        self._panel_instance: Optional[DockablePanel] = None
    
    # ==================== 抽象方法（子类必须实现） ====================
    
    @abstractmethod
    def create_panel(self) -> DockablePanel:
        """
        创建面板实例
        
        Returns:
            DockablePanel: 面板实例
        
        Note:
            - 此方法必须返回一个 DockablePanel 实例
            - 每次调用都应该创建新的实例
            - 面板的 panel_id 应该与 plugin_id 一致
        """
        raise NotImplementedError("子类必须实现 create_panel 方法")
    
    # ==================== 生命周期钩子（子类可选重写） ====================
    
    def on_load(self) -> None:
        """
        插件加载时调用
        
        在插件被加载到系统时调用，可以用于：
        - 初始化资源
        - 注册服务
        - 加载配置
        """
        pass
    
    def on_unload(self) -> None:
        """
        插件卸载时调用
        
        在插件被卸载时调用，可以用于：
        - 清理资源
        - 注销服务
        - 保存配置
        """
        pass
    
    def on_enable(self) -> None:
        """
        插件启用时调用
        
        在插件被启用时调用（默认启用）
        """
        pass
    
    def on_disable(self) -> None:
        """
        插件禁用时调用
        
        在插件被禁用时调用
        """
        pass
    
    def on_panel_created(self, panel: DockablePanel) -> None:
        """
        面板创建后调用
        
        Args:
            panel: 创建的面板实例
        
        可以用于：
        - 连接信号
        - 初始化面板状态
        - 注册事件处理器
        """
        pass
    
    def on_panel_closed(self, panel: DockablePanel) -> None:
        """
        面板关闭时调用
        
        Args:
            panel: 被关闭的面板实例
        
        可以用于：
        - 清理资源
        - 保存状态
        """
        pass
    
    # ==================== 配置管理（子类可选重写） ====================
    
    def get_config_schema(self) -> Dict[str, Any]:
        """
        获取配置模式
        
        Returns:
            dict: 配置模式定义
        
        Example:
            {
                "auto_start": {
                    "type": "bool",
                    "default": True,
                    "description": "启动时自动打开面板"
                },
                "refresh_interval": {
                    "type": "int",
                    "default": 5,
                    "min": 1,
                    "max": 60,
                    "description": "刷新间隔（秒）"
                }
            }
        """
        return {}
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """
        加载配置
        
        Args:
            config: 配置字典
        """
        pass
    
    def save_config(self) -> Dict[str, Any]:
        """
        保存配置
        
        Returns:
            dict: 配置字典
        """
        return {}
    
    # ==================== 内部方法（不建议子类重写） ====================
    
    def _set_loaded(self, loaded: bool) -> None:
        """设置加载状态（内部使用）"""
        self._loaded = loaded
    
    def _set_enabled(self, enabled: bool) -> None:
        """设置启用状态（内部使用）"""
        self._enabled = enabled
    
    def _set_panel_instance(self, panel: Optional[DockablePanel]) -> None:
        """设置面板实例（内部使用）"""
        self._panel_instance = panel
    
    # ==================== 公共属性 ====================
    
    @property
    def is_loaded(self) -> bool:
        """插件是否已加载"""
        return self._loaded
    
    @property
    def is_enabled(self) -> bool:
        """插件是否已启用"""
        return self._enabled
    
    @property
    def panel_instance(self) -> Optional[DockablePanel]:
        """当前面板实例"""
        return self._panel_instance
    
    # ==================== 工具方法 ====================
    
    def validate(self) -> tuple[bool, str]:
        """
        验证插件配置
        
        Returns:
            tuple: (是否有效, 错误信息)
        """
        if not self.plugin_id:
            return False, "plugin_id 不能为空"
        
        if not self.plugin_name:
            return False, "plugin_name 不能为空"
        
        if not self.plugin_version:
            return False, "plugin_version 不能为空"
        
        return True, ""
    
    def get_info(self) -> Dict[str, Any]:
        """
        获取插件信息
        
        Returns:
            dict: 插件信息字典
        """
        return {
            "id": self.plugin_id,
            "name": self.plugin_name,
            "version": self.plugin_version,
            "author": self.plugin_author,
            "description": self.plugin_description,
            "icon": self.plugin_icon,
            "default_area": self.default_area,
            "min_app_version": self.min_app_version,
            "dependencies": self.dependencies,
            "loaded": self._loaded,
            "enabled": self._enabled,
        }
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.plugin_id}, name={self.plugin_name}, version={self.plugin_version})>"
