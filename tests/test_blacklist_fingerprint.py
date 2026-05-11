# filename: tests/test_blacklist_fingerprint.py
import pytest
import os
import sys
import json
import hashlib
from unittest.mock import MagicMock, patch

# 确保能导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.services.file_service import FileService, IGNORED_BLOCKS_FILE

class TestBlacklistFingerprint:
    
    @pytest.fixture
    def env(self, tmp_path):
        """搭建测试环境"""
        # 模拟导出目录
        export_code = tmp_path / "export" / "code"
        export_img = tmp_path / "export" / "images"
        os.makedirs(export_code, exist_ok=True)
        os.makedirs(export_img, exist_ok=True)
        
        # 切换工作目录到 tmp_path，以便 ignored_blocks.json 生成在临时目录
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        
        mock_config = {
            "export_code_path": str(export_code),
            "export_image_path": str(export_img),
            "ignored_files": ""
        }
        
        service = FileService(mock_config)
        
        yield {
            "service": service,
            "root": tmp_path,
            "code_dir": export_code
        }
        
        os.chdir(old_cwd)

    def test_add_and_persist_blacklist(self, env):
        """测试：添加指纹并持久化"""
        service = env["service"]
        content = "print('hello world')"
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # 执行添加
        service.add_ignored_content("test.py", content)
        
        # 1. 验证内存状态
        assert service.is_content_ignored(content) is True
        
        # 2. 验证文件持久化
        assert os.path.exists(IGNORED_BLOCKS_FILE)
        with open(IGNORED_BLOCKS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert content_hash in data
            
        print("\n✅ 指纹添加与持久化测试通过")

    def test_save_code_interception(self, env):
        """测试：save_code 应拦截已拉黑的内容"""
        service = env["service"]
        content = "def sensitive_logic(): pass"
        
        # 先拉黑
        service.add_ignored_content("logic.py", content)
        
        # 尝试保存
        success, msg = service.save_code("logic.py", content)
        
        # 验证拦截
        assert success is False
        assert msg == "Ignored by content hash"
        
        # 验证文件未生成
        target_file = env["code_dir"] / "logic.py"
        assert not target_file.exists()
        
        print("✅ save_code 拦截机制测试通过")

    def test_remove_ignore_logic(self, env):
        """测试：移除黑名单（后悔药功能）"""
        service = env["service"]
        content = "print('I will be back')"
        
        # 1. 拉黑
        service.add_ignored_content("temp.py", content)
        assert service.is_content_ignored(content) is True
        
        # 2. 移除
        success, msg = service.remove_ignored_content(content)
        assert success is True
        assert "已从黑名单中移除" in msg
        assert service.is_content_ignored(content) is False
        
        # 3. 再次保存应成功
        success_save, _ = service.save_code("temp.py", content)
        assert success_save is True
        assert (env["code_dir"] / "temp.py").exists()
        
        print("✅ 黑名单移除逻辑测试通过")

    def test_auto_cleanup_staging(self, env):
        """测试：拉黑时自动清理暂存区残留文件"""
        service = env["service"]
        code_dir = env["code_dir"]
        content = "old_version_code = 1"
        
        # 1. 模拟暂存区已存在该文件 (比如 Worker 刚扫描到的)
        staged_file = code_dir / "old.py"
        staged_file.write_text(content, encoding='utf-8')
        
        # 2. 执行拉黑 (模拟用户点击了应用更新，触发自动拉黑)
        service.add_ignored_content("old.py", content)
        
        # 3. 验证暂存区文件是否被删除
        assert not staged_file.exists()
        print("✅ 暂存区自动清理测试通过")

    def test_content_mismatch_safety(self, env):
        """测试：文件名相同但内容不同时不误删"""
        service = env["service"]
        code_dir = env["code_dir"]
        
        # 暂存区是新版本 V2
        content_v2 = "version = 2"
        staged_file = code_dir / "config.py"
        staged_file.write_text(content_v2, encoding='utf-8')
        
        # 用户拉黑的是旧版本 V1 (假设从历史记录操作)
        content_v1 = "version = 1"
        service.add_ignored_content("config.py", content_v1)
        
        # 验证 V2 文件依然存在 (不应被 V1 的拉黑操作误删)
        assert staged_file.exists()
        assert staged_file.read_text(encoding='utf-8') == content_v2
        print("✅ 内容指纹安全校验测试通过 (防止误删不同版本)")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])