"""Offline protocol fixtures: no model, credentials, network or Docker required."""
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from app.core.agent_runtime import AgentRequest, PiRuntime, SafeToolBridge
from app.core.agent_runtime.transport import JsonlProcess, ProtocolError


@pytest.fixture
def sidecar(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_text('''import json, sys, pathlib
request = None
count = 0
def emit(obj):
 print(json.dumps(obj), flush=True)
def event(kind, **kw):
 emit({"type":"event", "requestId":request, "event":{"type":kind, **kw}})
for line in sys.stdin:
 c=json.loads(line); kind=c["type"]; data={}
 if kind=="init":
  session=c["session"]
  path=pathlib.Path(session.get("path") or pathlib.Path(session["dir"])/"session.jsonl")
  path.touch()
  data={"sessionFile":str(path)}
 emit({"type":"response","id":c["id"],"command":kind,"success":True,"data":data})
 if kind=="prompt":
  request=c["id"]
  if c["message"]=="crash": sys.exit(3)
  if c["message"]=="tool":
   emit({"type":"tool_call","requestId":request,"callId":"t1","name":"sandbox","arguments":{"code":"print(1)"}})
  elif c["message"]=="wait": pass
  else:
   event("message_update",assistantMessageEvent={"type":"text_delta","delta":"hello"})
   event("agent_end")
   event("auto_compaction_start")
   event("auto_compaction_end")
   event("message_end",message={"role":"assistant","content":[{"type":"text","text":"hello"}]})
   event("agent_settled")
 elif kind=="tool_result":
  count+=1
  if count==1:
   emit({"type":"tool_call","requestId":request,"callId":"t1","name":"sandbox","arguments":{"code":"print(1)"}})
  else: event("agent_settled")
 elif kind=="abort": event("agent_settled")
''')
    return [sys.executable, str(path)]


def request(tmp_path, message="hello"):
    return AgentRequest("conversation", "request", str(tmp_path), str(tmp_path / "sessions"),
                        "test", "fake", message=message,
                        tools=[{"name": "sandbox", "parameters": {"type": "object"}}])


def test_settled_not_agent_end_and_resume(tmp_path, sidecar):
    runtime = PiRuntime(sidecar)
    events = list(runtime.run(request(tmp_path), lambda *_: {}))
    assert events[-1].kind == "completed"
    assert "auto_compaction_end" in [e.payload.get("event_type") for e in events]
    assert events[-1].payload["text"] == "hello"
    session = runtime.session_path
    pid = runtime._process.process.pid
    assert Path(session).exists()
    assert list(runtime.run(request(tmp_path), lambda *_: {}))[-1].kind == "completed"
    assert runtime._process.process.pid == pid
    runtime.close()
    restored = PiRuntime(sidecar)
    req = request(tmp_path)
    object.__setattr__(req, "session_path", session)
    assert list(restored.run(req, lambda *_: {}))[-1].kind == "completed"
    assert restored.session_path == session
    restored.close()


def test_tool_requires_approval_and_executes_once(tmp_path, sidecar):
    runtime = PiRuntime(sidecar)
    calls, events = [], []
    def tool(*args):
        calls.append(args)
        return {"content": [{"type": "text", "text": "ok"}]}
    for event in runtime.run(request(tmp_path, "tool"), tool):
        events.append(event)
        if event.kind == "tool_approval":
            assert not calls
            assert runtime.approve("t1", True)
            assert not runtime.approve("t1", True)
    assert len(calls) == 1
    assert events[-1].kind == "completed"
    runtime.close()


def test_tool_denied_by_default(tmp_path, sidecar):
    runtime = PiRuntime(sidecar, approval_timeout=0.01)
    calls = []
    events = list(runtime.run(request(tmp_path, "tool"), lambda *a: calls.append(a)))
    assert not calls
    assert events[-1].kind == "completed"
    assert next(e for e in events if e.kind == "tool_result").payload["result"]["isError"]
    runtime.close()


def test_cancel_and_unexpected_exit(tmp_path, sidecar):
    runtime = PiRuntime(sidecar)
    events = []
    ready = threading.Event()
    def run():
        for item in runtime.run(request(tmp_path, "wait"), lambda *_: {}):
            events.append(item)
            if item.kind == "started": ready.set()
    thread = threading.Thread(target=run)
    thread.start()
    assert ready.wait(3)
    # Wait for prompt ACK before abort so the fixture has an active request.
    import time
    time.sleep(0.05)
    runtime.cancel()
    thread.join(3)
    assert not thread.is_alive()
    assert events[-1].kind == "cancelled"
    assert list(runtime.run(request(tmp_path, "crash"), lambda *_: {}))[-1].kind == "failed"
    assert list(runtime.run(request(tmp_path), lambda *_: {}))[-1].kind == "completed"
    runtime.close()


def test_invalid_session_path_and_environment_isolation(tmp_path, sidecar, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    runtime = PiRuntime(sidecar)
    req = request(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.touch()
    object.__setattr__(req, "session_path", str(outside))
    assert list(runtime.run(req, lambda *_: {}))[-1].kind == "failed"
    assert runtime._process is None


def test_safe_tool_bridge_allowlist_metadata_and_duplicate(tmp_path):
    calls = []
    def execute(intent):
        calls.append(intent)
        return SimpleNamespace(success=True, output="ok", error="")
    bridge = SafeToolBridge(SimpleNamespace(execute_intent=execute), [{"name": "sandbox"}], tmp_path, "c")
    assert bridge("bash", {}, "x")["isError"]
    assert bridge("sandbox", {"_tool_task_meta": {}}, "x")["isError"]
    assert not bridge("sandbox", {"code": "x"}, "x")["isError"]
    bridge("sandbox", {"code": "x"}, "x")
    assert len(calls) == 1
    assert calls[0].tool_call_id == "x"
    assert calls[0].conversation_id == "c"
    with pytest.raises(RuntimeError): bridge("sandbox", {"code": "y"}, "x")


def test_transport_malformed_and_bounded_output(tmp_path):
    script = tmp_path / "bad.py"
    script.write_text('print("not json", flush=True)')
    process = JsonlProcess([sys.executable, str(script)], tmp_path, tmp_path / "home")
    process.start()
    with pytest.raises(ProtocolError):
        while process.next_event() is None: pass
    process.close()


def test_cancel_while_approval_never_executes_tool(tmp_path, sidecar):
    runtime = PiRuntime(sidecar)
    calls = []
    events = []
    for item in runtime.run(request(tmp_path, "tool"), lambda *args: calls.append(args)):
        events.append(item)
        if item.kind == "tool_approval":
            runtime.cancel()
            assert not runtime.approve("t1", True)
    assert not calls
    assert events[-1].kind == "cancelled"
    runtime.close()


def test_cancel_before_prompt_ack_does_not_start_model(tmp_path, sidecar):
    runtime = PiRuntime(sidecar)
    events = []
    for item in runtime.run(request(tmp_path), lambda *_: {}):
        events.append(item)
        if item.kind == "started": runtime.cancel()
    assert [e.kind for e in events] == ["started", "cancelled"]
    runtime.close()


def test_transport_rejects_queue_overflow_and_does_not_inherit_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-do-not-inherit")
    monkeypatch.setenv("NODE_OPTIONS", "fixture-do-not-inherit")
    script = tmp_path / "env.py"
    script.write_text('import os, json, sys\n'
                      'assert "OPENAI_API_KEY" not in os.environ\n'
                      'assert "NODE_OPTIONS" not in os.environ\n'
                      'assert os.getcwd() == sys.argv[1]\n'
                      'for i in range(50): print(json.dumps({"type":"event"}), flush=True)\n')
    process = JsonlProcess([sys.executable, str(script), str(tmp_path)], tmp_path, tmp_path / "home", queue_size=1)
    process.start()
    import time
    time.sleep(0.1)
    assert process._failure is not None
    assert "overflow" in str(process._failure)
    process.close()


@pytest.fixture
def real_sidecar(tmp_path):
    import shutil
    root = Path(__file__).resolve().parents[1] / 'runtime' / 'pi'
    if not shutil.which('node') or not (root / 'node_modules' / '@earendil-works' / 'pi-coding-agent').exists():
        pytest.skip('Pinned Node SDK is installed and exercised in the dedicated pi-contract CI job')
    return [shutil.which('node'), str(root / 'test' / 'fixture-sidecar.mjs')]


def real_request(tmp_path, message):
    from dataclasses import replace
    return replace(request(tmp_path, message), provider='fixture-provider', model='fixture-model',
                   api_key='offline-fixture-value', base_url='https://example.invalid/v1',
                   tools=[{'name': 'bridge_echo', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}}}])


def test_python_real_sdk_tool_round_and_process_restart_resume(tmp_path, real_sidecar):
    from dataclasses import replace
    runtime = PiRuntime(real_sidecar)
    events, calls = [], []
    def tool(*args):
        calls.append(args)
        return {'content': [{'type': 'text', 'text': 'python host result'}], 'isError': True}
    try:
        for item in runtime.run(real_request(tmp_path, 'test:tool'), tool):
            events.append(item)
            if item.kind == 'tool_approval':
                assert not calls
                assert runtime.approve(item.payload['call_id'], True)
        assert len(calls) == 1 and events[-1].kind == 'completed'
        path = runtime.session_path
        history = Path(path).read_text()
        assert 'python host result' in history and '"isError":true' in history
        assert 'offline-fixture-value' not in history
    finally:
        runtime.close()
    restored = PiRuntime(real_sidecar)
    try:
        req = replace(real_request(tmp_path, 'test:resume'), session_path=path)
        result = list(restored.run(req, lambda *_: {}))
        assert result[-1].kind == 'completed'
        assert '2 user messages' in result[-1].payload['text']
    finally:
        restored.close()


def test_python_real_sdk_provider_failure_is_not_completion(tmp_path, real_sidecar):
    runtime = PiRuntime(real_sidecar)
    try:
        events = list(runtime.run(real_request(tmp_path, 'test:error'), lambda *_: {}))
        assert events[-1].kind == 'failed'
        assert events[-1].payload['error']
    finally:
        runtime.close()


def test_python_real_sdk_cancel_before_prompt_pending_session_can_restart(tmp_path, real_sidecar):
    from dataclasses import replace
    runtime = PiRuntime(real_sidecar)
    try:
        events = []
        for item in runtime.run(real_request(tmp_path, 'test:resume'), lambda *_: {}):
            events.append(item)
            if item.kind == 'started':
                runtime.cancel()
        assert events[-1].kind == 'cancelled'
        pending = runtime.session_path
        assert not Path(pending).exists()
    finally:
        runtime.close()
    restored = PiRuntime(real_sidecar)
    try:
        req = replace(real_request(tmp_path, 'test:resume'), session_path=pending, session_pending=True)
        events = list(restored.run(req, lambda *_: {}))
        assert events[-1].kind == 'completed'
        assert '1 user messages' in events[-1].payload['text']
    finally:
        restored.close()


def test_cancel_on_tool_started_prevents_host_entry(tmp_path, sidecar):
    runtime = PiRuntime(sidecar)
    calls, events = [], []
    try:
        for event in runtime.run(request(tmp_path, 'tool'), lambda *args: calls.append(args)):
            events.append(event)
            if event.kind == 'tool_approval':
                runtime.approve(event.payload['call_id'], True)
            if event.kind == 'tool_started':
                runtime.cancel()
        assert not calls
        assert events[-1].kind == 'cancelled'
    finally:
        runtime.close()


def test_pipe_write_timeout_is_bounded_when_child_stops_reading(tmp_path):
    import time
    process = JsonlProcess([sys.executable, '-c', 'import time; time.sleep(30)'], tmp_path,
                           tmp_path / 'home', ack_timeout=0.1)
    process.start()
    before = time.monotonic()
    try:
        with pytest.raises(ProtocolError, match='write timed out'):
            process.send('prompt', message='x' * 200000)
        assert time.monotonic() - before < 3
    finally:
        process.close()


@pytest.mark.parametrize('version,available', [('v20.19.0', False), ('v22.18.0', False), ('v22.19.0', True), ('v24.0.0', True)])
def test_registry_checks_minimum_node_version(monkeypatch, version, available):
    from app.core.agent_runtime import registry
    monkeypatch.setattr(registry.shutil, 'which', lambda _: '/fixture/node')
    monkeypatch.setattr(registry.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=version))
    monkeypatch.setattr(Path, 'read_text', lambda *a, **kw: '{"version":"0.99.1"}')
    monkeypatch.setattr(Path, 'is_file', lambda *_: True)
    assert registry.runtime_options()[0]['available'] is available
