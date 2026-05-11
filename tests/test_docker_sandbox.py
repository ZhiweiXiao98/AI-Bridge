# filename: tests/test_docker_sandbox.py
import pytest
from app.core.docker_manager import DockerManager

class TestDockerSandbox:
    
    @pytest.fixture
    def manager(self):
        return DockerManager()

    def test_code_execution_via_base64(self, manager):
        """测试核心：Base64 注入执行"""
        if not manager.container:
            pytest.skip("Container not running")
            
        # 这段代码完全不依赖挂载，直接在内存中传输
        code = "print('I am running inside Docker without mounting!')"
        exit_code, output = manager.execute_code(code)
        
        assert exit_code == 0
        assert "without mounting" in output
