"""
面板插件加载器

负责扫描、加载、管理面板插件的生命周期。
"""

import os
import json
import importlib.util
import sys
from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass
from app.ui.plugins.base_panel_plugin import BasePanelPlugin
from app.ui.components.dockable_panel import DockablePanel


@dataclass
class PluginInfo:
    """插件信息数据类"""
    id: str
    name: str
    version: str
    author: str
    description: str
    icon: str
    entry: str  # 入口文件名
    class_name: str  # 插件类名
    default_area: str
    dependencies: List[str]
    min_app_version: str
    plugin_dir: str  # 插件目录路径
    enabled: bool = True
    builtin: bool = False  # 是否为内置插件


class PanelPluginLoader:
    """
    面板插件加载器
    
    负责：
    - 扫描插件目录
    - 加载插件模块
    - 验证插件格式
    - 管理插件生命周期
    - 处理插件依赖
    """
    
    def __init__(self, plugin_dirs: List[str]):
        """
        初始化插件加载器
        
        Args:
            plugin_dirs: 插件目录列表
        """
        self.plugin_dirs = plugin_dirs
        self.plugins: Dict[str, BasePanelPlugin] = {}  # 已加载的插件实例
        self.plugin_infos: Dict[str, PluginInfo] = {}  # 插件信息
        self.plugin_modules: Dict[str, Any] = {}  # 插件模块
        
        print(f"[PluginLoader] 初始化，插件目录: {plugin_dirs}")
    
    def scan_plugins(self) -> List[PluginInfo]:
        """
        扫描所有插件目录
        
        Returns:
            List[PluginInfo]: 发现的插件信息列表
        """
        print("[PluginLoader] 开始扫描插件...")
        discovered_plugins = []
        
        for plugin_dir in self.plugin_dirs:
            if not os.path.exists(plugin_dir):
                print(f"[PluginLoader] 目录不存在，跳过: {plugin_dir}")
                continue
            
            print(f"[PluginLoader] 扫描目录: {plugin_dir}")
            plugins = self._scan_directory(plugin_dir)
            discovered_plugins.extend(plugins)
        
        # 保存插件信息
        for plugin_info in discovered_plugins:
            self.plugin_infos[plugin_info.id] = plugin_info
        
        print(f"[PluginLoader] 扫描完成，发现 {len(discovered_plugins)} 个插件")
        return discovered_plugins
    
    def _scan_directory(self, directory: str) -> List[PluginInfo]:
        """
        扫描单个目录
        
        Args:
            directory: 目录路径
        
        Returns:
            List[PluginInfo]: 插件信息列表
        """
        plugins = []
        
        try:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                
                # 跳过非目录
                if not os.path.isdir(item_path):
                    continue
                
                # 跳过特殊目录
                if item.startswith('_') or item.startswith('.'):
                    continue
                
                # 查找 plugin.json
                plugin_json = os.path.join(item_path, 'plugin.json')
                if not os.path.exists(plugin_json):
                    continue
                
                # 解析插件信息
                plugin_info = self._parse_plugin_json(plugin_json, item_path)
                if plugin_info:
                    plugins.append(plugin_info)
                    print(f"[PluginLoader] 发现插件: {plugin_info.name} (v{plugin_info.version})")
        
        except Exception as e:
            print(f"[PluginLoader] 扫描目录失败 {directory}: {e}")
        
        return plugins
    
    def _parse_plugin_json(self, json_path: str, plugin_dir: str) -> Optional[PluginInfo]:
        """
        解析 plugin.json 文件
        
        Args:
            json_path: plugin.json 文件路径
            plugin_dir: 插件目录路径
        
        Returns:
            Optional[PluginInfo]: 插件信息，解析失败返回 None
        """
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 验证必需字段
            required_fields = ['id', 'name', 'version', 'entry', 'class']
            for field in required_fields:
                if field not in data:
                    print(f"[PluginLoader] 插件配置缺少必需字段 '{field}': {json_path}")
                    return None
            
            # 创建插件信息
            plugin_info = PluginInfo(
                id=data['id'],
                name=data['name'],
                version=data['version'],
                author=data.get('author', 'Unknown'),
                description=data.get('description', ''),
                icon=data.get('icon', '📦'),
                entry=data['entry'],
                class_name=data['class'],
                default_area=data.get('default_area', 'right'),
                dependencies=data.get('dependencies', []),
                min_app_version=data.get('min_app_version', '1.0.0'),
                plugin_dir=plugin_dir,
                enabled=data.get('enabled', True),
                builtin=data.get('builtin', False)
            )
            
            return plugin_info
        
        except json.JSONDecodeError as e:
            print(f"[PluginLoader] JSON 解析失败 {json_path}: {e}")
            return None
        except Exception as e:
            print(f"[PluginLoader] 解析插件配置失败 {json_path}: {e}")
            return None
    
    def load_plugin(self, plugin_id: str) -> Optional[BasePanelPlugin]:
        """
        加载插件
        
        Args:
            plugin_id: 插件 ID
        
        Returns:
            Optional[BasePanelPlugin]: 插件实例，加载失败返回 None
        """
        # 检查是否已加载
        if plugin_id in self.plugins:
            print(f"[PluginLoader] 插件已加载: {plugin_id}")
            return self.plugins[plugin_id]
        
        # 获取插件信息
        plugin_info = self.plugin_infos.get(plugin_id)
        if not plugin_info:
            print(f"[PluginLoader] 插件不存在: {plugin_id}")
            return None
        
        print(f"[PluginLoader] 加载插件: {plugin_info.name} (v{plugin_info.version})")
        
        try:
            # 检查依赖
            if not self._check_dependencies(plugin_info):
                print(f"[PluginLoader] 依赖检查失败: {plugin_id}")
                return None
            
            # 加载模块
            plugin_module = self._load_module(plugin_info)
            if not plugin_module:
                return None
            
            # 获取插件类
            plugin_class = getattr(plugin_module, plugin_info.class_name, None)
            if not plugin_class:
                print(f"[PluginLoader] 找不到插件类 '{plugin_info.class_name}': {plugin_id}")
                return None
            
            # 创建插件实例
            plugin_instance = plugin_class()
            
            # 验证插件
            if not isinstance(plugin_instance, BasePanelPlugin):
                print(f"[PluginLoader] 插件类必须继承 BasePanelPlugin: {plugin_id}")
                return None
            
            # 验证插件配置
            is_valid, error_msg = plugin_instance.validate()
            if not is_valid:
                print(f"[PluginLoader] 插件验证失败: {error_msg}")
                return None
            
            # 调用加载钩子
            plugin_instance.on_load()
            plugin_instance._set_loaded(True)
            
            # 保存插件实例
            self.plugins[plugin_id] = plugin_instance
            self.plugin_modules[plugin_id] = plugin_module
            
            print(f"[PluginLoader] 插件加载成功: {plugin_info.name}")
            return plugin_instance
        
        except Exception as e:
            print(f"[PluginLoader] 加载插件失败 {plugin_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _load_module(self, plugin_info: PluginInfo) -> Optional[Any]:
        """
        加载插件模块
        
        Args:
            plugin_info: 插件信息
        
        Returns:
            Optional[Any]: 插件模块，加载失败返回 None
        """
        try:
            # 构建模块路径
            entry_path = os.path.join(plugin_info.plugin_dir, plugin_info.entry)
            
            if not os.path.exists(entry_path):
                print(f"[PluginLoader] 入口文件不存在: {entry_path}")
                return None
            
            # 生成模块名
            module_name = f"plugin_{plugin_info.id}"
            
            # 加载模块
            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if not spec or not spec.loader:
                print(f"[PluginLoader] 无法创建模块规范: {entry_path}")
                return None
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            return module
        
        except Exception as e:
            print(f"[PluginLoader] 加载模块失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _check_dependencies(self, plugin_info: PluginInfo) -> bool:
        """
        检查插件依赖
        
        Args:
            plugin_info: 插件信息
        
        Returns:
            bool: 依赖是否满足
        """
        for dep_id in plugin_info.dependencies:
            if dep_id not in self.plugins:
                print(f"[PluginLoader] 缺少依赖插件: {dep_id}")
                return False
        return True
    
    def unload_plugin(self, plugin_id: str) -> bool:
        """
        卸载插件
        
        Args:
            plugin_id: 插件 ID
        
        Returns:
            bool: 是否成功卸载
        """
        if plugin_id not in self.plugins:
            print(f"[PluginLoader] 插件未加载: {plugin_id}")
            return False
        
        try:
            plugin = self.plugins[plugin_id]
            
            # 调用卸载钩子
            plugin.on_unload()
            plugin._set_loaded(False)
            
            # 移除插件
            del self.plugins[plugin_id]
            
            # 移除模块
            if plugin_id in self.plugin_modules:
                module_name = f"plugin_{plugin_id}"
                if module_name in sys.modules:
                    del sys.modules[module_name]
                del self.plugin_modules[plugin_id]
            
            print(f"[PluginLoader] 插件卸载成功: {plugin_id}")
            return True
        
        except Exception as e:
            print(f"[PluginLoader] 卸载插件失败 {plugin_id}: {e}")
            return False
    
    def reload_plugin(self, plugin_id: str) -> Optional[BasePanelPlugin]:
        """
        重新加载插件
        
        Args:
            plugin_id: 插件 ID
        
        Returns:
            Optional[BasePanelPlugin]: 插件实例
        """
        print(f"[PluginLoader] 重新加载插件: {plugin_id}")
        self.unload_plugin(plugin_id)
        return self.load_plugin(plugin_id)
    
    def get_plugin(self, plugin_id: str) -> Optional[BasePanelPlugin]:
        """
        获取已加载的插件
        
        Args:
            plugin_id: 插件 ID
        
        Returns:
            Optional[BasePanelPlugin]: 插件实例
        """
        return self.plugins.get(plugin_id)
    
    def get_plugin_info(self, plugin_id: str) -> Optional[PluginInfo]:
        """
        获取插件信息
        
        Args:
            plugin_id: 插件 ID
        
        Returns:
            Optional[PluginInfo]: 插件信息
        """
        return self.plugin_infos.get(plugin_id)
    
    def get_all_plugins(self) -> Dict[str, BasePanelPlugin]:
        """获取所有已加载的插件"""
        return self.plugins.copy()
    
    def get_all_plugin_infos(self) -> Dict[str, PluginInfo]:
        """获取所有插件信息"""
        return self.plugin_infos.copy()
    
    def validate_plugin(self, plugin_dir: str) -> tuple[bool, str]:
        """
        验证插件目录
        
        Args:
            plugin_dir: 插件目录路径
        
        Returns:
            tuple: (是否有效, 错误信息)
        """
        # 检查 plugin.json
        plugin_json = os.path.join(plugin_dir, 'plugin.json')
        if not os.path.exists(plugin_json):
            return False, "缺少 plugin.json 文件"
        
        # 解析 plugin.json
        plugin_info = self._parse_plugin_json(plugin_json, plugin_dir)
        if not plugin_info:
            return False, "plugin.json 格式错误"
        
        # 检查入口文件
        entry_path = os.path.join(plugin_dir, plugin_info.entry)
        if not os.path.exists(entry_path):
            return False, f"入口文件不存在: {plugin_info.entry}"
        
        return True, ""
