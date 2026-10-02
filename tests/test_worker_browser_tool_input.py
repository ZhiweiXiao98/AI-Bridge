from app.core.worker_modules.worker_browser_tool_input import WorkerBrowserToolInputBridge


class FakeWorker:
    pass


def make_bridge():
    return WorkerBrowserToolInputBridge(FakeWorker())


def test_classify_structured_tool_result_as_feedback():
    bridge = make_bridge()
    messages = [{"segments": [{"type": "tool_result", "content": "ok"}]}]

    assert bridge.classify_browser_tool_input(messages, used_structured=True) == "tool_feedback"


def test_classify_structured_tool_call_code_as_tool_call():
    bridge = make_bridge()
    messages = [{"segments": [{"type": "code", "language": "tool_call", "content": "{}"}]}]

    assert bridge.classify_browser_tool_input(messages, used_structured=True) == "tool_call"


def test_classify_structured_plain_code_as_none():
    bridge = make_bridge()
    messages = [{"segments": [{"type": "code", "language": "python", "content": "print(1)"}]}]

    assert bridge.classify_browser_tool_input(messages, used_structured=True) == "none"


def test_classify_fallback_text_as_tool_call_and_feedback():
    bridge = make_bridge()
    fallback_messages = [{"segments": [{"type": "text", "content": "plain"}]}]
    feedback_messages = [{"segments": [{"type": "text", "content": "ignored"}]}]

    assert bridge.classify_browser_tool_input(fallback_messages, fallback_text="run this") == "tool_call"
    assert (
        bridge.classify_browser_tool_input(
            feedback_messages,
            fallback_text="🔧 [工具执行结果]\nok",
        )
        == "tool_feedback"
    )
