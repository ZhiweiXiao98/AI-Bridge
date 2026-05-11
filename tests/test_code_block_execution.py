# filename: tests/test_code_block_execution.py
"""
测试代码块执行功能
- 顺序执行
- 语法过滤  
- 文件名协议过滤
"""
import pytest
from app.core.services.tool_router_service import ToolRouterService

class TestCodeBlockExecution:
    """测试代码块执行的核心功能"""
    
    def test_sequential_execution_order(self):
        """测试代码块按顺序执行"""
        # 构造包含3个代码块的消息
        code1 = 'print("步骤1")'
        code2 = 'print("步骤2")'
        code3 = 'print("步骤3")'
        
        content = f'''
第一个代码块：
```python
# EXEC
{code1}
```

第二个代码块：
```python
# EXEC
{code2}
```

第三个代码块：
```python
# EXEC
{code3}
```
'''
        
        messages = [{
            "role": "AI",
            "segments": [{"type": "text", "content": content}]
        }]
        
        router = ToolRouterService(agent_manager=None)
        result = router.maybe_handle_tool_from_messages("test_chat", messages)
        
        # 验证结果包含3个代码块的输出，且顺序正确
        assert result is not None
        assert "步骤1" in result
        assert "步骤2" in result
        assert "步骤3" in result
        assert result.index("步骤1") < result.index("步骤2") < result.index("步骤3")
    
    def test_syntax_validation_filter(self):
        """测试非法语法代码块被过滤"""
        invalid_code = 'print("missing quote'
        valid_code = 'print("valid code")'
        
        content = f'''
```python
# EXEC
{invalid_code}
```

```python
# EXEC
{valid_code}
```
'''
        
        messages = [{
            "role": "AI",
            "segments": [{"type": "text", "content": content}]
        }]
        
        router = ToolRouterService(agent_manager=None)
        result = router.maybe_handle_tool_from_messages("test_chat", messages)
        
        # 只有合法代码被执行
        assert "valid code" in result
        assert "missing quote" not in result
    
    def test_filename_protocol_filter(self):
        """测试文件名协议代码块被过滤"""
        file_code = '# filename: config.py\\nCONFIG = {"key": "value"}'
        exec_code = 'print("executable")'
        
        content = f'''
```python
# EXEC
{file_code}
```

```python
# EXEC
{exec_code}
```
'''
        
        messages = [{
            "role": "AI",
            "segments": [{"type": "text", "content": content}]
        }]
        
        router = ToolRouterService(agent_manager=None)
        result = router.maybe_handle_tool_from_messages("test_chat", messages)
        
        # 文件名协议代码块被跳过
        assert "executable" in result
        assert "CONFIG" not in result
    
    def test_mixed_blocks(self):
        """测试混合场景：正常+非法+文件名+正常"""
        content = '''
```python
# EXEC
print("任务1")
```

```python
# EXEC
def broken(
```

```python
# EXEC
# filename: test.py
DATA = 123
```

```python
# EXEC
print("任务2")
```
'''
        
        messages = [{
            "role": "AI",
            "segments": [{"type": "text", "content": content}]
        }]
        
        router = ToolRouterService(agent_manager=None)
        result = router.maybe_handle_tool_from_messages("test_chat", messages)
        
        # 只有2个正常代码块被执行
        assert "任务1" in result
        assert "任务2" in result
        assert result.index("任务1") < result.index("任务2")
        assert "broken" not in result
        assert "DATA" not in result