# filename: app/ui/managers/workspace_manager.py
"""
工作区预设管理器
管理多个工作区布局预设
"""
import json
import os
from typing import Dict, List

class WorkspaceManager:
    """
    工作区预设管理器
    
    功能：
    - 保存/加载工作区预设
    - 管理多个预设
    - 切换预设
    """
    
    def __init__(self, config_dir="config"):
        """
        初始化管理器
        
        Args:
            config_dir: 配置目录
        """
        self.config_dir = config_dir
        self.presets_dir = os.path.join(config_dir, "workspace_presets")
        
        # 确保目录存在
        os.makedirs(self.presets_dir, exist_ok=True)
        
        # 当前预设
        self.current_preset = None
    
    def save_preset(self, name: str, layout: dict, description: str = ""):
        """
        保存工作区预设
        
        Args:
            name: 预设名称
            layout: 布局数据
            description: 预设描述
        """
        preset_file = os.path.join(self.presets_dir, f"{name}.json")
        
        preset_data = {
            "name": name,
            "description": description,
            "layout": layout
        }
        
        with open(preset_file, 'w', encoding='utf-8') as f:
            json.dump(preset_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 工作区预设已保存: {name}")
    
    def load_preset(self, name: str) -> dict:
        """
        加载工作区预设
        
        Args:
            name: 预设名称
        
        Returns:
            dict: 预设数据，失败返回 None
        """
        preset_file = os.path.join(self.presets_dir, f"{name}.json")
        
        if not os.path.exists(preset_file):
            print(f"⚠️ 预设不存在: {name}")
            return None
        
        try:
            with open(preset_file, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)
            
            self.current_preset = name
            print(f"📂 工作区预设已加载: {name}")
            return preset_data
        
        except Exception as e:
            print(f"❌ 加载预设失败: {e}")
            return None
    
    def delete_preset(self, name: str) -> bool:
        """
        删除工作区预设
        
        Args:
            name: 预设名称
        
        Returns:
            bool: 是否成功
        """
        preset_file = os.path.join(self.presets_dir, f"{name}.json")
        
        if os.path.exists(preset_file):
            os.remove(preset_file)
            print(f"🗑️ 工作区预设已删除: {name}")
            return True
        else:
            print(f"⚠️ 预设不存在: {name}")
            return False
    
    def list_presets(self) -> List[Dict]:
        """
        列出所有预设
        
        Returns:
            list: 预设列表
        """
        presets = []
        
        if not os.path.exists(self.presets_dir):
            return presets
        
        for filename in os.listdir(self.presets_dir):
            if filename.endswith('.json'):
                preset_file = os.path.join(self.presets_dir, filename)
                try:
                    with open(preset_file, 'r', encoding='utf-8') as f:
                        preset_data = json.load(f)
                    
                    presets.append({
                        "name": preset_data.get("name", filename[:-5]),
                        "description": preset_data.get("description", ""),
                        "file": filename
                    })
                except Exception as e:
                    print(f"⚠️ 读取预设失败 {filename}: {e}")
        
        return presets
    
    def create_default_presets(self):
        """创建默认预设"""
        # 默认布局
        default_layout = {
            "name": "默认",
            "description": "显示所有面板的默认布局",
            "panels": {}
        }
        self.save_preset("default", default_layout, "显示所有面板的默认布局")
        
        # 调试布局
        debug_layout = {
            "name": "调试",
            "description": "沙盒监控 + AI日志在底部",
            "panels": {}
        }
        self.save_preset("debug", debug_layout, "沙盒监控 + AI日志在底部")
        
        # 极简布局
        minimal_layout = {
            "name": "极简",
            "description": "隐藏所有面板",
            "panels": {}
        }
        self.save_preset("minimal", minimal_layout, "隐藏所有面板")
        
        print("✅ 默认预设已创建")
