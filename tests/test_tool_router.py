# filename: tests/test_tool_router.py
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# 路径注入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.services.tool_router_service import ToolRouterService

class TestToolRouter:
    @pytest.fixture
    def mock_agent(self):
        return MagicMock()

    @pytest.fixture
    def mock_docker(self):
        # 创建一个 Mock 对象来模拟 DockerManager
        m = MagicMock()
        # 确保 execute_code 返回默认成功值
        m.execute_code.return_value = (0, "Mock Output")
        return m

    @pytest.fixture
    def router(self, mock_agent, mock_docker):
        # 核心：Mock 掉 DockerManager 的实例化，确保 router 使用我们的 mock_docker
        with patch('app.core.services.tool_router_service.DockerManager', return_value=mock_docker):
            service = ToolRouterService(mock_agent)
            # 双重保险：强制替换实例属性
            service.docker = mock_docker 
            return service

    def test_extract_code_block_standard(self, router):
        """测试标准 Markdown 提取"""
        code_with_marker = "# EXEC\nprint('Hello')"
        code_without_marker = "print('Hello')"  # 执行时 # EXEC 会被移除
        
        msgs = [{
            "role": "AI",
            "segments": [{"type": "text", "content": f"Here is code:\n```python\n{code_with_marker}\n```"}]
        }]
        
        result = router.maybe_handle_tool_from_messages("chat_1", msgs)
        
        assert result is not None, "Standard extraction failed"
        assert "Mock Output" in result
        # 验证执行的代码（不包含 # EXEC 标记）
        router.docker.execute_code.assert_called_with(code_without_marker)

    def test_extract_code_block_robustness(self, router):
        """测试 Markdown 代码块中带 # EXEC 标记的提取"""
        code_without_marker = "import os\nprint(os.getcwd())"
        markdown_text = "```python\n# EXEC\nimport os\nprint(os.getcwd())\n```"
        
        msgs = [{
            "role": "AI",
            "segments": [{"type": "text", "content": markdown_text}]
        }]
        
        result = router.maybe_handle_tool_from_messages("chat_2", msgs)
        
        assert result is not None, "Code block extraction failed"
        router.docker.execute_code.assert_called_with(code_without_marker)

    def test_gatekeeper_blocks_invalid_syntax(self, router):
        """测试语法守门员拦截无效代码"""
        invalid_code = "def broken_function(:" # 语法错误
        msgs = [{
            "role": "AI",
            "segments": [{"type": "text", "content": f"```python\n{invalid_code}\n```"}]
        }]
        
        result = router.maybe_handle_tool_from_messages("chat_3", msgs)
        
        # 应该返回 None，且不调用 Docker
        assert result is None
        router.docker.execute_code.assert_not_called()

    def test_idempotency(self, router):
        """测试幂等性 (去重)"""
        # 1. 构造一条非常标准的合法的消息
        # 注意：确保换行符清晰，匹配正则 r"```python.*?\n(.*?)\n```"
        code_with_marker = "# EXEC\nprint('Idempotency Test')"
        code_without_marker = "print('Idempotency Test')"
        content = f"Sure, here is the code:\n```python\n{code_with_marker}\n```"
        
        msgs = [{
            "role": "AI",
            "segments": [{"type": "text", "content": content}]
        }]
        
        # 2. 第一次调用
        print(f"\n[Test] Calling 1st time with: {content!r}")
        res1 = router.maybe_handle_tool_from_messages("chat_idempotency", msgs)
        
        # 诊断断言
        assert res1 is not None, "First call failed to execute (Result is None)"
        assert router.docker.execute_code.call_count == 1, "First call did not trigger Docker"
        # 验证执行的代码不包含 # EXEC
        router.docker.execute_code.assert_called_with(code_without_marker)

        # 3. 第二次调用 (完全相同的消息)
        print("[Test] Calling 2nd time (should be ignored)")
        res2 = router.maybe_handle_tool_from_messages("chat_idempotency", msgs)
        
        # 4. 验证：应该返回 None (被去重拦截)，且 Docker 调用次数保持为 1
        assert res2 is None, "Second call was not deduplicated"
        assert router.docker.execute_code.call_count == 1, "Docker was called again!"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])