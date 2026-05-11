# filename: tests/test_update_service.py
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.services.update_service import UpdateService

class TestUpdateService:
    @pytest.fixture
    def service(self):
        config = {"export_code_path": "export/code"}
        file_service = MagicMock()
        file_service.validate_python_code.return_value = (True, None) 
        return UpdateService(config, file_service)

    @pytest.mark.parametrize("path, expected", [
        ("server.py", "CRITICAL"),
        ("requirements.txt", "CRITICAL"),
        ("app/core/config.py", "CRITICAL"),
        
        # [Fix] 核心修正：测试目标必须指向新的 Core 位置
        ("app/core/worker.py", "CRITICAL"),

        # [Test] 验证旧位置（如果残留）不再被视为关键文件
        ("app/ui/worker.py", "CLIENT_ONLY"),

        ("app/ui/pages/chat_page.py", "CLIENT_ONLY"),
        ("app/ui/pages/chat/__init__.py", "CLIENT_ONLY"),
        ("app/ui/pages/chat/page.py", "CLIENT_ONLY"),
        ("app/ui/pages/chat/input_area.py", "CLIENT_ONLY"),
        
        ("app/ui/components/base.py", "CLIENT_ONLY"),
        ("boot_remote.py", "CLIENT_ONLY"),
        ("tests/test_config.py", "SAFE_SCRIPT"),
        
        ("README.md", "SAFE_STATIC"),
    ])
    def test_file_categorization(self, service, path, expected):
        assert service.get_file_category(path) == expected

    @patch("time.sleep")
    @patch("app.core.services.update_service.SelfUpdateManager")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("os.makedirs")
    def test_process_updates_restart_logic(self, mock_makedirs, mock_open, MockUpdateMgr, mock_sleep, service):
        # 模拟 sys.exit 还是 InterruptedError?
        # 代码中使用 while True: sleep(1)，所以 mock_sleep 会抛出异常
        mock_sleep.side_effect = InterruptedError("Simulated Kill")

        file_handle = MagicMock()
        file_handle.read.return_value = "print('New Code')"
        mock_open.return_value.__enter__.return_value = file_handle

        mock_mgr = MockUpdateMgr.return_value
        # 使用 CRITICAL 文件触发重启
        mock_mgr.scan.return_value = [{
            "rel_path": "server.py",
            "staging_path": "/tmp/stage/server.py",
            "status": "overwrite"
        }]
        
        service.mgr = mock_mgr

        with pytest.raises(InterruptedError):
            service.process_updates(
                paths=["server.py"], 
                logger_func=MagicMock(), 
                ota_callback=MagicMock()
            )