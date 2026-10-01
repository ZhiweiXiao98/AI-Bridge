from app.core.api_mode_config import TOOL_PROTOCOL_MARKDOWN, TOOL_PROTOCOL_NATIVE
from app.core.prompt_runtime.prompt_assembler import build_final_system_prompt
from app.core.prompt_runtime.skills_prompt_loader import build_skills_prompt


def test_native_skills_prompt_does_not_teach_markdown_tool_call_fence():
    prompt = build_skills_prompt(tool_protocol=TOOL_PROTOCOL_NATIVE)

    assert "```tool_call" not in prompt
    assert "native API tool calls" in prompt


def test_markdown_skills_prompt_keeps_tool_call_fence():
    prompt = build_skills_prompt(tool_protocol=TOOL_PROTOCOL_MARKDOWN)

    assert "```tool_call" in prompt


def test_native_final_prompt_replaces_forced_tool_call_sections():
    payload = build_final_system_prompt(tool_protocol=TOOL_PROTOCOL_NATIVE)
    final_prompt = payload["final_system_prompt"]

    assert "所有工具调用必须严格使用以下格式" not in final_prompt
    assert "所有工具必须使用以下格式调用" not in final_prompt
    assert "优先使用原生 tool calls" in final_prompt
