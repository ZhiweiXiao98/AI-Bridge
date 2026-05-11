# filename: tests/test_file_service.py
import pytest
import os
import sys
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.services.file_service import FileService

class TestFileService:
    
    @pytest.fixture
    def mock_config(self, tmp_path):
        """Mock 配置，将导出路径指向临时目录"""
        return {
            "export_code_path": str(tmp_path / "code"),
            "export_image_path": str(tmp_path / "images")
        }

    @pytest.fixture
    def service(self, mock_config):
        return FileService(mock_config)

    def test_http_image_download(self, service):
        """
        🧪 测试 HTTP 图片下载与缓存
        """
        # 构造假消息
        msgs = [{
            "segments": [{"type": "image", "content": "http://example.com/pic.png"}]
        }]
        
        fake_content = b"fake_image_data"
        
        # [Fix] 同时 Mock os.makedirs，防止它内部调用 exists 消耗 side_effect
        with patch("requests.get") as mock_get, \
             patch("builtins.open", new_callable=mock_open) as mock_file, \
             patch("os.makedirs") as mock_makedirs, \
             patch("os.path.exists", side_effect=[False, True]): 
             # 预期调用顺序：
             # 1. process_images -> exists(file) -> False (触发下载)
             # 2. process_images -> exists(file) -> True (触发替换)
            
            # 配置 Mock 响应
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = fake_content
            mock_get.return_value = mock_response
            
            # 执行
            processed = service.process_images(msgs)
            
            # 验证 1: 是否发起了下载请求
            mock_get.assert_called_once_with("http://example.com/pic.png", timeout=10)
            
            # 验证 2: 是否写入了文件
            mock_file.assert_called()
            handle = mock_file()
            handle.write.assert_called_with(fake_content)
            
            # 验证 3: URL 是否被替换为 served://
            new_content = processed[0]['segments'][0]['content']
            assert new_content.startswith("served://")
            assert new_content.endswith(".png")
            print(f"✅ 图片下载与路径替换验证通过: {new_content}")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])