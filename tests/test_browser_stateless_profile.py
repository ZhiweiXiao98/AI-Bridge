import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.worker_modules.browser_stateless_profile import (
    BrowserPromptEnvelope,
    ContextCompiler,
    ModelRequest,
    ResponseNormalizer,
    StatelessBrowserProfileAdapter,
)
from app.core.app_constants import UPSTREAM_AI_URL


class FakeConnector:
    def __init__(self):
        self.calls = []
        self.reset_ok = True
        self.switch_ok = True
        self.raw_text = ""

    def open_conversation_url(self, conversation_url, timeout=20):
        self.calls.append(("open", conversation_url, timeout))
        if not self.switch_ok:
            return False, {"stage": "switching_conversation", "error_code": "conversation_switch_failed"}
        return True, {"stage": "switching_conversation", "conversation_url": conversation_url}

    def open_conversation_target(self, conversation_url="", conversation_name="", timeout=20):
        target = conversation_url or conversation_name
        self.calls.append(("open", target, timeout))
        if not self.switch_ok:
            return False, {"stage": "switching_conversation", "error_code": "conversation_switch_failed"}
        return True, {
            "stage": "switching_conversation",
            "conversation_url": conversation_url,
            "conversation_name": conversation_name,
        }

    def clear_conversation(self, timeout=10):
        self.calls.append(("clear", timeout))
        return self.reset_ok, {"stage": "resetting"}

    def send_message(self, selector, prompt):
        self.calls.append(("send", selector, prompt))
        return True, "sent"

    def wait_until_idle(self, timeout=180):
        self.calls.append(("wait", timeout))
        return True, {"stage": "waiting"}

    def extract_latest_ai_response(self, request_id=None):
        self.calls.append(("extract", request_id))
        text = self.raw_text or f'```json\n{{"request_id":"{request_id}","answer":"ok"}}\n```'
        if request_id and request_id not in text:
            return False, {"error_code": "request_id_mismatch"}
        return True, {"raw_text": text, "dom_nodes": 1}


class RecordingCompiler:
    def __init__(self):
        self.messages = None
        self.context_bundle = None

    def compile(self, request):
        self.messages = request.messages
        self.context_bundle = request.context_bundle
        return "compiled"


def test_reset_failure_does_not_send_prompt():
    connector = FakeConnector()
    connector.reset_ok = False
    adapter = StatelessBrowserProfileAdapter(
        connector,
        conversation_url=f"{UPSTREAM_AI_URL}/chat#550028",
        timeout_seconds=30,
    )

    response = adapter.invoke(ModelRequest(request_id="req_reset", messages=[{"role": "user", "content": "A"}]))

    assert response.finish_reason == "failed"
    assert response.diagnostics["error_code"] == "reset_failed"
    assert [c[0] for c in connector.calls] == ["open", "clear"]


def test_missing_conversation_url_does_not_clear_current_chat():
    connector = FakeConnector()
    adapter = StatelessBrowserProfileAdapter(connector, timeout_seconds=30)

    response = adapter.invoke(ModelRequest(request_id="req_no_url", messages=[{"role": "user", "content": "A"}]))

    assert response.finish_reason == "failed"
    assert response.diagnostics["error_code"] == "conversation_target_required"
    assert connector.calls == []


def test_conversation_url_switches_before_clear():
    connector = FakeConnector()
    adapter = StatelessBrowserProfileAdapter(
        connector,
        conversation_url=f"{UPSTREAM_AI_URL}/chat#550028",
        timeout_seconds=30,
    )

    response = adapter.invoke(ModelRequest(request_id="req_url", messages=[{"role": "user", "content": "A"}]))

    assert response.finish_reason == "succeeded"
    assert [c[0] for c in connector.calls[:2]] == ["open", "clear"]
    assert connector.calls[0][1] == f"{UPSTREAM_AI_URL}/chat#550028"


def test_conversation_switch_failure_does_not_clear_current_chat():
    connector = FakeConnector()
    connector.switch_ok = False
    adapter = StatelessBrowserProfileAdapter(
        connector,
        conversation_url=f"{UPSTREAM_AI_URL}/chat#missing",
        timeout_seconds=30,
    )

    response = adapter.invoke(ModelRequest(request_id="req_url_fail", messages=[{"role": "user", "content": "A"}]))

    assert response.finish_reason == "failed"
    assert response.diagnostics["error_code"] == "conversation_switch_failed"
    assert [c[0] for c in connector.calls] == ["open"]


def test_prompt_envelope_requires_request_id_echo():
    req = ModelRequest(request_id="req_123", task_type="unit_test")
    prompt = BrowserPromptEnvelope().build(req, "compiled")

    assert "request_id: req_123" in prompt
    assert "必须回显 request_id: req_123" in prompt
    assert "不要引用或延续网页历史消息" in prompt


def test_context_compiler_formats_api_context_messages_as_markdown():
    req = ModelRequest(
        request_id="req_ctx",
        task_type="chat",
        messages=[
            {"role": "system", "content": "系统提示词"},
            {"role": "system", "content": "[长期记忆]\n项目偏好"},
            {"role": "system", "content": "[工作记忆]当前任务状态:\n{\"step\": \"实现\"}"},
            {"role": "user", "content": "继续"},
        ],
        context_bundle={
            "conversation_id": "conv_1",
            "profile": {"kind": "browser_stateless", "provider": "web_ai"},
            "context_status": {"utilization": 12.5, "total_used": 16000, "total_budget": 128000},
        },
    )

    prompt = ContextCompiler().compile(req)

    assert "conversation_id: conv_1" in prompt
    assert "profile_kind: browser_stateless" in prompt
    assert "context_tokens: 16000/128000" in prompt
    assert "### Message 1 · system" in prompt
    assert "系统提示词" in prompt
    assert "[长期记忆]" in prompt
    assert "[工作记忆]" in prompt
    assert "不要为了迎合系统而强行输出 JSON" in prompt


def test_normalizer_extracts_fenced_json():
    raw = 'prefix\n```json\n{"request_id":"req_1","value":42}\n```\n'
    response = ResponseNormalizer().normalize(
        request=ModelRequest(request_id="req_1"),
        profile_id="browser_web_primary",
        raw_text=raw,
        diagnostics={},
    )

    assert response.parsed == {"request_id": "req_1", "value": 42}


def test_adapter_serializes_invocations():
    connector = FakeConnector()
    adapter = StatelessBrowserProfileAdapter(
        connector,
        conversation_url=f"{UPSTREAM_AI_URL}/chat#550028",
        timeout_seconds=30,
    )
    order = []
    original_clear = connector.clear_conversation

    def slow_clear(timeout=10):
        order.append("clear_start")
        time.sleep(0.02)
        result = original_clear(timeout=timeout)
        order.append("clear_end")
        return result

    connector.clear_conversation = slow_clear

    import threading

    threads = [
        threading.Thread(target=adapter.invoke, args=(ModelRequest(request_id=f"req_{i}"),))
        for i in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert order == ["clear_start", "clear_end", "clear_start", "clear_end"]


def test_adapter_passes_browser_progress_callback():
    class ProgressConnector(FakeConnector):
        def wait_until_idle(self, timeout=180, progress_callback=None):
            self.calls.append(("wait_progress", timeout, bool(progress_callback)))
            if progress_callback:
                progress_callback({
                    "raw_text": "生成中",
                    "message": {
                        "id": "ai_1",
                        "role": "AI",
                        "segments": [{"type": "text", "content": "生成中"}],
                    },
                    "raw_len": 12,
                })
            return True, {"stage": "waiting"}

    progress = []
    connector = ProgressConnector()
    adapter = StatelessBrowserProfileAdapter(
        connector,
        conversation_name="Web_Profile",
        timeout_seconds=30,
        progress_callback=progress.append,
    )

    response = adapter.invoke(ModelRequest(request_id="req_progress"))

    assert response.finish_reason == "succeeded"
    assert any(call[0] == "wait_progress" and call[2] is True for call in connector.calls)
    assert progress and progress[0]["raw_text"] == "生成中"


def test_adapter_passes_full_request_to_compiler():
    connector = FakeConnector()
    compiler = RecordingCompiler()
    adapter = StatelessBrowserProfileAdapter(
        connector,
        conversation_url=f"{UPSTREAM_AI_URL}/chat#550028",
        timeout_seconds=30,
        compiler=compiler,
    )
    messages = [
        {"role": "system", "content": "系统"},
        {"role": "user", "content": "任务"},
    ]
    context_bundle = {
        "conversation_id": "conv_1",
        "context_status": {"utilization": 10},
    }

    response = adapter.invoke(ModelRequest(request_id="req_full", messages=messages, context_bundle=context_bundle))

    assert response.finish_reason == "succeeded"
    assert compiler.messages == messages
    assert compiler.context_bundle == context_bundle
