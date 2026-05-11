# filename: tests/test_agent_manager.py
import pytest
import os
import sys
import shutil
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.agent_manager import AgentManager
from app.core.services.file_service import FileService

class TestAgentManager:
    
    @pytest.fixture
    def env(self, tmp_path):
        project_root = tmp_path
        
        # [Fix] 关键修改：在测试中，将导出路径直接设为根目录
        # 这样 Agent 修改代码时，会直接覆盖“源码”，方便断言检查
        mock_config = {
            "export_code_path": str(project_root), 
            "export_image_path": str(project_root / "images"),
            "ignored_files": ""
        }
        
        with patch("app.core.services.file_service.ConfigManager.load", return_value=mock_config):
            real_file_service = FileService(mock_config)
            # 锁定安全根目录
            real_file_service.project_root = str(project_root.resolve())
            
            agent = AgentManager(real_file_service)
            
            # 创建基础文件
            (project_root / "config.py").write_text("ver=1", encoding="utf-8")
            
            old_cwd = os.getcwd()
            os.chdir(project_root)
            
            yield {"agent": agent, "root": project_root, "fs": real_file_service}
            
            os.chdir(old_cwd)

    def test_parse_tool_read(self, env):
        agent = env["agent"]
        text = 'Check [TOOL: read_file path="config.py"]'
        intent, data = agent.parse_agent_response(text)
        assert intent == "TOOL"
        assert data["name"] == "read_file"

    def test_parse_code_block(self, env):
        agent = env["agent"]
        text = "# filename: test.py\n```python\nprint(1)\n```"
        intent, data = agent.parse_agent_response(text)
        assert intent == "CODE"

    def test_path_redirection_logic(self, env):
        agent = env["agent"]
        assert agent._resolve_legacy_path("app/ui/worker.py") == "app/core/worker.py"
        assert agent._resolve_legacy_path("server.py") == "server.py"

    def test_tool_read_file_safety(self, env):
        agent = env["agent"]
        root = env["root"]
        
        # 正常读取
        res = agent.tool_read_file("config.py")
        assert "ver=1" in res
        
        # 越权读取
        res_denied = agent.tool_read_file("../secret.txt")
        assert "Security" in res_denied or "Access denied" in res_denied
        
        # 纠偏读取 (模拟文件存在)
        target_dir = root / "app" / "core"
        os.makedirs(target_dir, exist_ok=True)
        (target_dir / "worker.py").write_text("worker_content", encoding="utf-8")
        
        res_legacy = agent.tool_read_file("app/ui/worker.py")
        assert "worker_content" in res_legacy
        assert "app/core/worker.py" in res_legacy

    @patch("app.core.agent_manager.subprocess.run")
    def test_safe_apply_rollback_on_failure(self, mock_run, env):
        agent = env["agent"]
        root = env["root"]
        
        target_file = root / "worker.py"
        target_file.write_text("original_code", encoding="utf-8")
        
        # 模拟测试失败
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "Failed"
        mock_run.return_value = mock_proc
        
        segments = [{"type": "code", "content": "# filename: worker.py\nbroken_code"}]
        success, changed, log = agent.safe_apply_and_test(segments)
        
        # 验证：操作失败，且文件被回滚
        assert success is False
        assert target_file.read_text(encoding="utf-8") == "original_code"
        assert not os.path.exists("worker.py.bak")

    @patch("app.core.agent_manager.subprocess.run")
    def test_safe_apply_commit_on_success(self, mock_run, env):
        agent = env["agent"]
        root = env["root"]
        
        # 1. 准备文件
        target_dir = root / "app" / "core"
        os.makedirs(target_dir, exist_ok=True)
        target_file = target_dir / "worker.py"
        target_file.write_text("original_code", encoding="utf-8")
        
        # 2. 模拟测试成功
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc
        
        # 3. 执行修改
        # 这里的 filename 包含路径，且 env 配置了 export_path=root
        # 所以 save_code 会直接覆盖 root/app/core/worker.py
        input_content = "# filename: app/core/worker.py\nnew_code"
        segments = [{"type": "code", "content": input_content}]
        
        success, changed, log = agent.safe_apply_and_test(segments)
        
        # 4. 验证
        assert success is True
        assert "app/core/worker.py" in changed
        
        # 现在这个断言应该能通过了
        assert target_file.read_text(encoding="utf-8") == input_content
        assert not os.path.exists(str(target_file) + ".bak")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])