# filename: tests/test_example_code_filter.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.services.tool_router_service import ToolRouterService
from app.core.agent_manager import AgentManager
from app.core.services.file_service import FileService
from app.core.config import ConfigManager


def test_example_code_filter():
    print("\n" + "="*60)
    print("测试：示例代码过滤")
    print("="*60)
    
    config = ConfigManager.load()
    file_service = FileService(config)
    agent = AgentManager(file_service)
    router = ToolRouterService(agent)
    
    # 测试 1：只有示例代码
    print("\n[测试 1] 只有示例代码（应该跳过）")
    code_with_example = 'print("示例代码")'
    test_msg_1 = [{
        "role": "AI",
        "index": 0,
        "segments": [{
            "type": "text",
            "content": f"```python\n# EXAMPLE\n{code_with_example}\n```"
        }]
    }]
    
    result_1 = router.maybe_handle_tool_from_messages("test", test_msg_1, allow=True)
    print("✅ 通过" if result_1 is None else "❌ 失败")
    
    # 测试 2：正常代码
    print("\n[测试 2] 正常代码（应该执行）")
    normal_code = 'print("正常代码")'
    test_msg_2 = [{
        "role": "AI",
        "index": 0,
        "segments": [{
            "type": "text",
            "content": f"```python\n{normal_code}\n```"
        }]
    }]
    
    result_2 = router.maybe_handle_tool_from_messages("test", test_msg_2, allow=True)
    print("✅ 通过" if result_2 else "❌ 失败")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    test_example_code_filter()
