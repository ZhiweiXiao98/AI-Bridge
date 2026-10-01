from types import SimpleNamespace

import pytest

from app.core.api_source import APISource
from app.core.api_mode_config import TOOL_PROTOCOL_NATIVE
from app.core.context_manager import ContextConfig
from app.core.conversation_store import ConversationStore
from app.core.llm_provider import APIProvider, ProviderConfig
from app.core.tool_runtime.executor import ToolRuntimeExecutor


def test_api_provider_chat_with_tools_normalizes_tool_calls():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(model="test-model", temperature=0, max_output_tokens=128)
    captured = {}
    message = SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                type="function",
                function=SimpleNamespace(name="echo", arguments='{"text":"hi"}'),
            )
        ],
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
    )

    def _create(**kwargs):
        captured.update(kwargs)
        return response

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )

    result = provider.chat_with_tools(
        [{"role": "user", "content": "call echo"}],
        [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}],
    )

    assert captured["tools"][0]["function"]["name"] == "echo"
    assert captured["tool_choice"] == "auto"
    assert result["tool_calls"][0]["id"] == "call_1"
    assert result["tool_calls"][0]["function"]["arguments"] == '{"text":"hi"}'


@pytest.mark.asyncio
async def test_api_provider_stream_chat_with_tools_accumulates_tool_call_deltas():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(model="test-model", temperature=0, max_output_tokens=128)
    captured = {}
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="准备", tool_calls=[]))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(
                index=0,
                id="call_1",
                type="function",
                function=SimpleNamespace(name="echo", arguments=""),
            )],
        ))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(
                index=0,
                id=None,
                type=None,
                function=SimpleNamespace(name="", arguments='{"text"'),
            )],
        ))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(
                index=0,
                id=None,
                type=None,
                function=SimpleNamespace(name="", arguments=':"hi"}'),
            )],
        ))]),
    ]

    def _create(**kwargs):
        captured.update(kwargs)
        return iter(chunks)

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )

    events = []
    async for event in provider.stream_chat_with_tools(
        [{"role": "user", "content": "call echo"}],
        [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}],
    ):
        events.append(event)

    assert captured["tools"][0]["function"]["name"] == "echo"
    assert captured["stream"] is True
    assert events[0] == {"type": "content_delta", "content": "准备"}
    assert events[-1]["type"] == "message_end"
    assert events[-1]["content"] == "准备"
    assert events[-1]["tool_calls"][0]["id"] == "call_1"
    assert events[-1]["tool_calls"][0]["function"]["arguments"] == '{"text":"hi"}'


@pytest.mark.asyncio
async def test_api_provider_stream_chat_events_emits_reasoning_delta():
    provider = APIProvider.__new__(APIProvider)
    provider.config = ProviderConfig(model="test-model", temperature=0, max_output_tokens=128)
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(reasoning_content="先分析", content=None))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(reasoning_content="再判断", content=None))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(reasoning_content=None, content="结论"))]),
    ]

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: iter(chunks)))
    )

    events = []
    async for event in provider.stream_chat_events([{"role": "user", "content": "hi"}]):
        events.append(event)

    assert events == [
        {"type": "thinking_delta", "content": "先分析", "reasoning_content": "先分析"},
        {"type": "thinking_delta", "content": "再判断", "reasoning_content": "再判断"},
        {"type": "content_delta", "content": "结论"},
    ]


class _FakeNativeProvider:
    def __init__(self):
        self.calls = []
        self._responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_echo",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"text":"hi"}'},
                    }
                ],
            },
            {"content": "done", "tool_calls": []},
        ]

    def chat_with_tools(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        return self._responses.pop(0)


class _FakeSkillsManager:
    def get_all_tool_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo text",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            }
        ]

    def execute_skill(self, name, **kwargs):
        return True, f"echo:{kwargs.get('text', '')}", ""


class _FakeToolRouter:
    def __init__(self):
        self.skills_manager = _FakeSkillsManager()
        self.runtime_executor = ToolRuntimeExecutor(skills_manager=self.skills_manager)


class _FakeStreamNativeProvider:
    def __init__(self):
        self.calls = []
        self.close_count = 0
        self._responses = [
            [
                {
                    "type": "message_end",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_echo",
                            "type": "function",
                            "function": {"name": "echo", "arguments": '{"text":"hi"}'},
                        }
                    ],
                },
            ],
            [
                {"type": "content_delta", "content": "done"},
                {"type": "message_end", "content": "done", "tool_calls": []},
            ],
        ]

    async def stream_chat_with_tools(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        try:
            for event in self._responses.pop(0):
                yield event
        finally:
            self.close_count += 1


def _make_source(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path), config=ContextConfig())
    store.create("native-tools-test")

    source = APISource.__new__(APISource)
    source.config_path = None
    source.config_dict = {
        "active_profile": "api",
        "profiles": {
            "api": {
                "kind": "api",
                "provider": "openai_compatible",
                "model": "test-model",
                "system_prompt_role": "system",
                "supports_tools": True,
                "tool_capability": {
                    "status": "supported",
                    "protocol": TOOL_PROTOCOL_NATIVE,
                },
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "api"},
        "conversation_defaults": {"system": {}, "context": {}},
        "agent": {"allow_tools": ["echo"], "max_steps": 4},
    }
    source.conv_store = store
    source.llm_provider = _FakeNativeProvider()
    source.last_fallback_event = None
    source.current_runtime_profile_key = "api"
    source._initialized = True
    source._last_request_snapshot = None
    source.on_tool_status_event = None
    source._refresh_context_manager_system_prompt = lambda conversation_id=None: {}
    source._maybe_compact_context = lambda *args, **kwargs: {}
    source._auto_title = lambda text: None
    source._inject_journal_long_term = lambda conversation_id=None: None
    source._capture_request_snapshot = lambda messages, conversation_id=None: None
    return source


def test_api_source_sync_native_tool_round_executes_and_follows_up(tmp_path):
    source = _make_source(tmp_path)
    router = _FakeToolRouter()

    reply = source.send_message_sync("use echo", tool_router=router)

    assert reply == "done"
    assert len(source.llm_provider.calls) == 2
    assert source.llm_provider.calls[0]["tools"][0]["function"]["name"] == "echo"
    followup_messages = source.llm_provider.calls[1]["messages"]
    assert followup_messages[-2]["role"] == "assistant"
    assert followup_messages[-2]["tool_calls"][0]["id"] == "call_echo"
    assert followup_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call_echo",
        "content": "echo:hi",
    }

    history = source.conv_store.context_manager.get_history()
    assert [msg["role"] for msg in history] == ["user", "assistant", "tool_feedback", "assistant"]
    tool_feedback = history[2]
    assert tool_feedback["kind"] == "tool_feedback"
    assert tool_feedback["segments"][1]["type"] == "tool_result"
    assert tool_feedback["segments"][1]["tool_call_id"] == "call_echo"


@pytest.mark.asyncio
async def test_api_source_stream_native_tool_round_executes_and_follows_up(tmp_path):
    source = _make_source(tmp_path)
    source.llm_provider = _FakeStreamNativeProvider()
    router = _FakeToolRouter()

    chunks = []
    async for chunk in source.send_message_stream("use echo", tool_router=router):
        chunks.append(chunk)

    assert "".join(chunks) == "done"
    assert len(source.llm_provider.calls) == 2
    assert source.llm_provider.close_count == 2
    assert source.llm_provider.calls[0]["tools"][0]["function"]["name"] == "echo"
    followup_messages = source.llm_provider.calls[1]["messages"]
    assert followup_messages[-2]["role"] == "assistant"
    assert followup_messages[-2]["tool_calls"][0]["id"] == "call_echo"
    assert followup_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call_echo",
        "content": "echo:hi",
    }

    history = source.conv_store.context_manager.get_history()
    assert [msg["role"] for msg in history] == ["user", "assistant", "tool_feedback", "assistant"]
    assert history[-1]["content"] == "done"
