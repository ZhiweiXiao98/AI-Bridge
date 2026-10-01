"""Code-block fallback execution tests for ToolRouterService."""

import ast
import contextlib
import io
from types import SimpleNamespace

import pytest

from app.core.services.tool_router_service import ToolRouterService


class FakeDockerManager:
    def __init__(self):
        self.calls = []

    def execute_code(self, code):
        self.calls.append(code)
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return 1, f"SyntaxError: {exc}"

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(code, {})
        return 0, output.getvalue()


@pytest.fixture
def docker_manager():
    return FakeDockerManager()


@pytest.fixture
def router(docker_manager):
    agent = SimpleNamespace(docker_manager=docker_manager, knowledge_service=None)
    return ToolRouterService(agent_manager=agent)


def _text(result):
    assert result is not None
    return result.combined_feedback


class TestCodeBlockExecution:
    def test_sequential_execution_order(self, router):
        content = """
第一个代码块：
```python
# EXEC
print("步骤1")
```

第二个代码块：
```python
# EXEC
print("步骤2")
```

第三个代码块：
```python
# EXEC
print("步骤3")
```
"""
        messages = [{"role": "AI", "segments": [{"type": "text", "content": content}]}]

        result_text = _text(router.maybe_handle_tool_from_messages("test_chat", messages))

        assert "步骤1" in result_text
        assert "步骤2" in result_text
        assert "步骤3" in result_text
        assert result_text.index("步骤1") < result_text.index("步骤2") < result_text.index("步骤3")

    def test_syntax_validation_filter(self, router):
        content = """
```python
# EXEC
print("missing quote
```

```python
# EXEC
print("valid code")
```
"""
        messages = [{"role": "AI", "segments": [{"type": "text", "content": content}]}]

        result_text = _text(router.maybe_handle_tool_from_messages("test_chat", messages))

        assert "valid code" in result_text
        assert "missing quote" not in result_text

    def test_filename_protocol_filter(self, router):
        content = """
```python
# EXEC
# filename: config.py
CONFIG = {"key": "value"}
```

```python
# EXEC
print("executable")
```
"""
        messages = [{"role": "AI", "segments": [{"type": "text", "content": content}]}]

        result_text = _text(router.maybe_handle_tool_from_messages("test_chat", messages))

        assert "executable" in result_text
        assert "CONFIG" not in result_text

    def test_mixed_blocks(self, router):
        content = """
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
"""
        messages = [{"role": "AI", "segments": [{"type": "text", "content": content}]}]

        result_text = _text(router.maybe_handle_tool_from_messages("test_chat", messages))

        assert "任务1" in result_text
        assert "任务2" in result_text
        assert result_text.index("任务1") < result_text.index("任务2")
        assert "broken" not in result_text
        assert "DATA" not in result_text
