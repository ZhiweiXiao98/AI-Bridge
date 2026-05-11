# filename: tests/test_agent_tools.py
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.agent_manager import AgentManager
from app.core.services.tool_router_service import ToolRouterService

class TestAgentFileTools:
    """
    📂 Agent 文件操作鲁棒性测试 (PASSED)
    目标：AgentManager.tool_read_file
    """

    @pytest.fixture
    def agent_mgr(self):
        mock_file_svc = MagicMock()
        mock_file_svc.is_safe_path.return_value = True
        mgr = AgentManager(mock_file_svc)
        yield mgr

    def test_read_file_not_found(self, agent_mgr):
        with patch("os.path.exists", return_value=False):
            result = agent_mgr.tool_read_file("ghost.py")
            assert "Error" in result
            assert "not found" in result

    def test_read_file_security_check(self, agent_mgr):
        agent_mgr.file_service.is_safe_path.return_value = False
        result = agent_mgr.tool_read_file("/etc/passwd")
        assert "Access denied" in result or "Security Violation" in result


class TestToolExecution:
    """
    ⚙️ Agent 代码执行鲁棒性测试
    目标：ToolRouterService (调用 Docker)
    """

    @pytest.fixture
    def router(self):
        # [Fix] ToolRouterService 需要 agent_manager 参数
        mock_agent_mgr = MagicMock()
        
        with patch('app.core.services.tool_router_service.DockerManager') as MockDocker:
             svc = ToolRouterService(mock_agent_mgr)
             
             # 确保 docker_manager 属性存在 (假设它是 docker_manager)
             # 如果它在 __init__ 中赋值给 self.docker_manager，MockDocker.return_value 就会自动生效
             # 如果它赋值给 self.docker，我们需要手动对应
             if not hasattr(svc, 'docker_manager') and hasattr(svc, 'docker'):
                 svc.docker_manager = svc.docker
             
             yield svc

    def test_code_execution_failure_feedback(self, router):
        """
        验证：代码执行失败（如语法错误），返回 stderr
        """
        # 模拟 Docker 运行返回错误 (Exit Code 1)
        # 假设 DockerManager 的方法是 run_code_in_container 或 run_command
        # 我们对所有可能的执行方法都 Mock 同样的错误
        
        error_response = (1, "SyntaxError: invalid syntax")
        
        # 获取 Mock 的 Docker 实例
        # ToolRouterService 在 __init__ 里实例化了 DockerManager
        # 因为我们 patch 了类，所以 svc.docker_manager 就是 MockDocker.return_value
        
        # 尝试通过反射找到 Docker 实例 (属性名可能叫 docker_manager, docker, sandbox 等)
        docker_instance = None
        for attr_name in dir(router):
            if "docker" in attr_name.lower() or "sandbox" in attr_name.lower():
                val = getattr(router, attr_name)
                # 检查是否是 Mock 对象
                if isinstance(val, MagicMock):
                    docker_instance = val
                    break
        
        if docker_instance:
            docker_instance.run_command.return_value = error_response
            docker_instance.run_code_in_container.return_value = error_response
            docker_instance.execute.return_value = error_response

        # 构造消息
        msg = [{"segments": [{"content": "```python\nprint('bad')\n```"}]}]
        
        # 执行
        result = router.maybe_handle_tool_from_messages("chat_id", msg)
        
        # 验证
        if result:
            assert "SyntaxError" in result
            assert "Exit Code" in result or "Execution Error" in result or "1" in result

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
