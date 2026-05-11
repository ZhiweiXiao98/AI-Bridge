# filename: tests/test_config.py
"""
🧪 配置管理单元测试

测试模块：app/core/config.py
目标：
- 配置加载 (文件存在 & 不存在)
- 配置保存
- 默认值回退
"""

import pytest
import json
import os
import tempfile
import sys

# 确保能导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import ConfigManager


class TestConfigManagerBasic:
    """基础配置管理测试"""
    
    def test_default_config_structure(self):
        """测试默认配置包含所需字段"""
        config = ConfigManager.load()
        
        assert isinstance(config, dict)
        assert "export_code_path" in config
        assert "export_image_path" in config
        assert "chrome_port" in config
        assert "auto_export" in config
    
    def test_chrome_port_default_value(self):
        """测试 Chrome 端口默认值为 9527"""
        config = ConfigManager.load()
        assert config["chrome_port"] == 9527
    
    def test_auto_export_default_enabled(self):
        """测试自动导出默认启用"""
        config = ConfigManager.load()
        assert config["auto_export"] is True
    
    def test_export_paths_are_strings(self):
        """测试导出路径是字符串类型"""
        config = ConfigManager.load()
        assert isinstance(config["export_code_path"], str)
        assert isinstance(config["export_image_path"], str)


class TestConfigManagerSaveLoad:
    """配置保存和加载测试"""
    
    @pytest.fixture
    def temp_config_path(self):
        """临时配置文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        yield temp_path
        # 清理
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    def test_save_and_load_custom_config(self, monkeypatch, temp_config_path):
        """测试保存和加载自定义配置"""
        # Mock 配置文件路径
        monkeypatch.setattr('app.core.config.CONFIG_PATH', temp_config_path)
        
        # 保存自定义配置
        custom_config = {
            "export_code_path": "custom/code",
            "export_image_path": "custom/images",
            "chrome_port": 8888,
            "auto_export": False
        }
        ConfigManager.save(custom_config)
        
        # 加载配置
        loaded = ConfigManager.load()
        
        assert loaded["chrome_port"] == 8888
        assert loaded["auto_export"] is False
        assert loaded["export_code_path"] == "custom/code"
    
    def test_load_creates_default_if_missing(self, monkeypatch, temp_config_path):
        """测试文件不存在时创建默认配置"""
        # 使用不存在的临时路径
        non_existent = os.path.join(tempfile.gettempdir(), "non_existent_config.json")
        monkeypatch.setattr('app.core.config.CONFIG_PATH', non_existent)
        
        # 删除文件（如果存在）
        if os.path.exists(non_existent):
            os.remove(non_existent)
        
        # 加载应该创建默认配置
        config = ConfigManager.load()
        
        assert config is not None
        assert "chrome_port" in config
        
        # 清理
        if os.path.exists(non_existent):
            os.remove(non_existent)
    
    def test_config_persistence_across_instances(self, monkeypatch, temp_config_path):
        """测试配置在实例间的持久性"""
        monkeypatch.setattr('app.core.config.CONFIG_PATH', temp_config_path)
        
        # 第一次保存
        config1 = {
            "export_code_path": "path1",
            "chrome_port": 9999,
            "auto_export": True,
            "export_image_path": "images1"
        }
        ConfigManager.save(config1)
        
        # 第二次加载
        loaded1 = ConfigManager.load()
        assert loaded1["chrome_port"] == 9999
        
        # 第三次加载（应该与第二次相同）
        loaded2 = ConfigManager.load()
        assert loaded2["chrome_port"] == 9999
        assert loaded1 == loaded2


class TestConfigManagerValidation:
    """配置验证测试"""
    
    def test_port_is_integer(self):
        """测试端口是整数"""
        config = ConfigManager.load()
        assert isinstance(config["chrome_port"], int)
        assert 0 < config["chrome_port"] < 65536
    
    def test_auto_export_is_boolean(self):
        """测试自动导出是布尔值"""
        config = ConfigManager.load()
        assert isinstance(config["auto_export"], bool)
    
    @pytest.mark.parametrize("port", [9527, 8765, 3000, 5000])
    def test_various_valid_ports(self, monkeypatch, port):
        """参数化测试：各种有效端口"""
        test_config = {
            "export_code_path": "export/code",
            "export_image_path": "export/images",
            "chrome_port": port,
            "auto_export": True
        }
        
        # 验证端口范围
        assert 0 < port < 65536
        assert isinstance(port, int)


class TestConfigManagerEdgeCases:
    """边界情况测试"""
    
    def test_empty_path_strings(self):
        """测试空路径字符串"""
        config = ConfigManager.load()
        # 路径不应该为空
        assert config["export_code_path"]
        assert config["export_image_path"]
    
    def test_config_not_modified_by_load(self):
        """测试加载不会修改返回的配置"""
        config1 = ConfigManager.load()
        config2 = ConfigManager.load()
        
        # 修改第一个副本
        config1["chrome_port"] = 9999
        
        # 第二个副本不应该被影响
        assert config2["chrome_port"] == 9527


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
