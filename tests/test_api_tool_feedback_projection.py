from app.core.api_source import APISource
from app.core.context_manager import ContextManager
from app.ui.pages.chat.page import ChatPage


def test_tool_feedback_keeps_internal_role():
    cm = ContextManager()
    cm.add_structured_message("assistant", "I will call a tool.")
    cm.add_structured_message(
        "tool_feedback",
        "🔧 [工具执行结果]\nread_file: ok",
        kind="tool_feedback",
        meta={"ephemeral": True, "tool_kind": "tool_feedback"},
    )

    messages = cm.build_messages()

    assert messages[-1]["role"] == "tool_feedback"
    assert messages[-1]["kind"] == "tool_feedback"
    assert "工具执行结果" in messages[-1]["content"]


def test_api_projection_does_not_use_user_or_assistant_for_tool_feedback():
    source = APISource.__new__(APISource)

    projected = source._project_messages_for_chat_api([
        {"role": "tool_feedback", "kind": "tool_feedback", "content": "read_file: ok"}
    ])

    assert projected == [{"role": "system", "content": "[工具回流]\nread_file: ok"}]


def test_api_ephemeral_tool_feedback_is_hidden_from_rendered_messages():
    page = ChatPage.__new__(ChatPage)

    assert page._is_ephemeral_api_tool_feedback(
        {
            "kind": "tool_feedback",
            "meta": {"ephemeral": True, "tool_kind": "tool_feedback"},
        }
    )
    assert not page._is_ephemeral_api_tool_feedback(
        {
            "kind": "text",
            "meta": {"ephemeral": True},
        }
    )


def test_api_signal_message_backfills_tool_call_id_for_tool_cards():
    source = APISource.__new__(APISource)
    source.conv_store = type("ConvStore", (), {"active_id": "conv_1"})()

    msg = source.build_message_for_signal(
        role="assistant",
        content='```tool_call\n{"name":"file_operations","arguments":{"operation":"read_file","path":"README.md"}}\n```',
        index=1,
    )

    tool_segments = [
        seg for seg in msg["segments"]
        if seg.get("type") == "code" and seg.get("language") == "tool_call"
    ]
    assert tool_segments
    assert tool_segments[0]["tool_call_id"].startswith("toolcall_")
