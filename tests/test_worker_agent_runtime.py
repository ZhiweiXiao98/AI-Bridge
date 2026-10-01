"""Pi worker lifecycle and ownership checks, without any provider or Docker calls."""
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from app.core.agent_runtime import AgentEvent, AgentRequest, PiRuntime
from app.core.conversation_store import ConversationStore
from app.core.project_context import ProjectContext
from app.core.worker_modules.worker_agent_runtime import WorkerAgentRuntimeBridge
from tests.helpers import RecordingSignal


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr('app.core.project_context.APP_ROOT', str(tmp_path))
    context = ProjectContext()
    monkeypatch.setattr(ProjectContext, 'get', classmethod(lambda cls: context))
    store = ConversationStore(str(tmp_path / 'conversations'))
    conv_id = store.create('Pi test', system_prompt='session-specific system', runtime='pi')
    source = SimpleNamespace(conv_store=store,
                             get_history_as_messages_for=lambda _: store.get_display_messages(conv_id),
                             get_context_status=lambda _: {}, get_conversations=store.list_conversations)
    worker = SimpleNamespace(api_source=source, _api_streaming=True,
                             safe_emit_status=lambda _: None, _update_ai_state=lambda _: None)
    for name in ('agent_runtime_options', 'agent_runtime_approval', 'api_stream_chunk', 'api_stream_status',
                 'api_round_state', 'messages', 'context_status', 'sessions'):
        setattr(worker, name + '_signal', RecordingSignal())
    bridge = WorkerAgentRuntimeBridge(worker)
    req = AgentRequest(conv_id, 'r1', str(tmp_path), str(tmp_path / 'sessions'), 'test', 'fake', message='hello')
    context.acquire_runtime_lease(str(tmp_path), req.request_id)
    target = {'target_client_id': 'device', 'target_username': 'alice', 'target_group': 'admin'}
    bridge._active = {'conversation_id': conv_id, 'request_id': req.request_id, 'client_id': 'device',
                      'username': 'alice', 'target': target, 'project_root': str(tmp_path), 'state': 'starting'}
    return bridge, worker, store, context, req


class FakeRuntime:
    def __init__(self, events=()):
        self.events = events
        self.closed = self.cancelled = False
        self.approvals = []

    def run(self, *_):
        yield from self.events

    def close(self):
        self.closed = True

    def cancel(self):
        self.cancelled = True

    def approve(self, call_id, approved):
        self.approvals.append((call_id, approved))
        return True


def test_projection_failure_always_releases_lease_and_state(harness, monkeypatch):
    bridge, worker, store, context, req = harness
    runtime = FakeRuntime()
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(store, 'get_display_messages', fail)
    bridge._run(req, runtime, lambda *_: {})
    assert runtime.closed
    assert not bridge.is_running and not worker._api_streaming
    assert context._runtime_leases == set()
    terminal = worker.api_stream_status_signal.payloads[-1]
    assert terminal['status'] == 'error'
    assert terminal['target_client_id'] == 'device'
    assert terminal['target_username'] == 'alice'


@pytest.mark.parametrize('terminal', ['completed', 'cancelled', 'failed'])
def test_terminal_events_preserve_request_owner_after_cleanup(harness, terminal):
    bridge, worker, store, context, req = harness
    runtime = FakeRuntime([AgentEvent(terminal, req.conversation_id, req.request_id)])
    bridge._run(req, runtime, lambda *_: {})
    assert runtime.closed and not bridge.is_running
    assert context._runtime_leases == set()
    event = worker.api_stream_status_signal.payloads[-1]
    assert event['target_client_id'] == 'device'
    assert event['target_username'] == 'alice'
    assert event['request_id'] == req.request_id


def test_session_pointer_is_not_saved_until_sdk_creates_file(harness):
    bridge, worker, store, context, req = harness
    nonexistent = str(Path(req.session_dir) / 'not-yet-created.jsonl')
    runtime = FakeRuntime([AgentEvent('started', req.conversation_id, req.request_id, {'session_path': nonexistent}),
                           AgentEvent('cancelled', req.conversation_id, req.request_id, {'session_path': nonexistent})])
    bridge._run(req, runtime, lambda *_: {})
    assert store.get_runtime_session(req.conversation_id)['session_path'] == nonexistent
    assert store.get_runtime_session(req.conversation_id)['pending'] is True


def test_storage_failure_after_session_started_still_closes_process(harness, monkeypatch, tmp_path):
    bridge, worker, store, context, req = harness
    session = tmp_path / 'session.jsonl'
    session.touch()
    runtime = FakeRuntime([AgentEvent('started', req.conversation_id, req.request_id, {'session_path': str(session)})])
    save = store.save_runtime_projection
    def fail_session(*args, **kwargs):
        if kwargs.get('session'):
            raise OSError('disk full')
        return save(*args, **kwargs)
    monkeypatch.setattr(store, 'save_runtime_projection', fail_session)
    bridge._run(req, runtime, lambda *_: {})
    assert runtime.closed and not bridge.is_running and not worker._api_streaming
    assert context._runtime_leases == set()


def test_controls_require_account_and_device_and_reject_stale_ids(harness):
    bridge, worker, store, context, req = harness
    runtime = FakeRuntime()
    bridge._active['runtime'] = runtime
    for kwargs in ({'client_id': 'device', 'username': 'mallory'},
                   {'client_id': 'other', 'username': 'alice', 'verified_login': True}, {}):
        assert not bridge.approve(req.conversation_id, req.request_id, 't1', True, **kwargs)['ok']
        assert not bridge.cancel(**kwargs)['ok']
        assert not bridge.state(**kwargs)['ok']
    owner = {'client_id': 'device', 'username': 'alice', 'verified_login': True}
    assert not bridge.approve(req.conversation_id, 'stale', 't1', True, **owner)['ok']
    assert not bridge.approve(req.conversation_id, req.request_id, 't1', 'true', **owner)['ok']
    assert bridge.approve(req.conversation_id, req.request_id, 't1', False, **owner)['ok']
    assert bridge.cancel(req.conversation_id, req.request_id, **owner)['ok']
    assert runtime.approvals == [('t1', False)] and runtime.cancelled


def test_remote_start_rejects_legacy_admin_before_profile_or_model_access(harness):
    bridge, *_ = harness
    assert not bridge.start('hello', client_id='device', username='admin', verified_login=False)['ok']


def test_approval_timeout_resolution_clears_pending_and_exposes_state(harness):
    bridge, worker, store, context, req = harness
    bridge._emit(AgentEvent('tool_approval', req.conversation_id, req.request_id,
                           {'call_id': 't1', 'name': 'sandbox', 'arguments': {}}))
    assert bridge._pending['project_root'] == req.project_root
    bridge._emit(AgentEvent('tool_result', req.conversation_id, req.request_id, {'call_id': 't1'}))
    assert bridge._pending is None
    assert bridge.state(client_id='device', username='alice', verified_login=True)['state'] == 'waiting_followup'


def test_project_lease_blocks_switch_until_python_tool_returns(harness, tmp_path):
    bridge, worker, store, context, req = harness
    entered, release = threading.Event(), threading.Event()
    class BlockingRuntime(FakeRuntime):
        def run(self, *_):
            entered.set()
            assert release.wait(5)
            yield AgentEvent('cancelled', req.conversation_id, req.request_id)
    runtime = BlockingRuntime()
    bridge._active['runtime'] = runtime
    thread = threading.Thread(target=bridge._run, args=(req, runtime, lambda *_: {}))
    thread.start()
    assert entered.wait(2)
    bridge.cancel(client_id='device', username='alice', verified_login=True)
    other = tmp_path / 'other'
    other.mkdir()
    try:
        with pytest.raises(RuntimeError, match='Pi'):
            context.switch_to(str(other))
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and runtime.closed and not context._runtime_leases


def test_pi_history_remains_projection_and_legacy_is_unchanged(harness):
    _, _, store, _, req = harness
    assert store.context_manager is None
    assert store.get_runtime_system_prompt(req.conversation_id) == 'session-specific system'
    with pytest.raises(RuntimeError):
        store.build_context_manager_for(req.conversation_id)
    with pytest.raises(RuntimeError):
        store.set_conversation_system_prompt(req.conversation_id, 'mutate')
    legacy = store.create('legacy')
    assert store.get_runtime(legacy) == 'legacy'
    assert store.context_manager is not None
    assert store.switch(req.conversation_id) and store.context_manager is None
    assert store.get_runtime_system_prompt(req.conversation_id) == 'session-specific system'


def test_cancel_before_runtime_generator_enters_never_starts_process(tmp_path):
    runtime = PiRuntime(['must-never-start'])
    req = AgentRequest('c', 'r', str(tmp_path), str(tmp_path / 's'), 'fake', 'fake')
    runtime.cancel()
    assert [e.kind for e in runtime.run(req, lambda *_: {})] == ['cancelled']
    assert runtime._process is None


def test_projection_writes_are_atomic_and_preserve_mapping_on_failure(harness, monkeypatch):
    bridge, worker, store, context, req = harness
    store.save_runtime_projection(req.conversation_id, session={'session_path': 'kept.jsonl'})
    previous = store._conv_path(req.conversation_id).read_bytes()
    def fail_replace(*_):
        raise OSError('disk full')
    monkeypatch.setattr('app.core.conversation_store.os.replace', fail_replace)
    with pytest.raises(OSError):
        store.save_runtime_projection(req.conversation_id, messages=[{'role': 'user', 'content': 'new'}])
    assert store._conv_path(req.conversation_id).read_bytes() == previous
    assert store.get_runtime_session(req.conversation_id)['session_path'] == 'kept.jsonl'
    assert not list(store.storage_dir.glob('*.tmp'))


def test_corrupt_pi_mapping_is_not_replaced_by_empty_history(harness):
    _, _, store, _, req = harness
    path = store._conv_path(req.conversation_id)
    path.write_text('{incomplete')
    with pytest.raises(OSError, match='preserved'):
        store.save_runtime_projection(req.conversation_id, messages=[])
    assert path.read_text() == '{incomplete'


def test_concurrent_model_metadata_and_projection_preserve_session(harness):
    _, _, store, _, req = harness
    store.save_runtime_projection(req.conversation_id, session={'session_path': 'kept.jsonl'})
    failures = []
    def writer():
        try:
            for i in range(20):
                store.save_runtime_projection(req.conversation_id, messages=[{'role': 'user', 'content': str(i)}])
        except Exception as exc:
            failures.append(exc)
    thread = threading.Thread(target=writer)
    thread.start()
    for _ in range(20):
        assert store.set_model_usage(req.conversation_id, {'type': 'profile', 'ref': 'chosen'})
    thread.join(5)
    assert not failures and not thread.is_alive()
    assert store.get_runtime_session(req.conversation_id)['session_path'] == 'kept.jsonl'
    assert store.get_display_messages(req.conversation_id)[0]['content'] == '19'
    assert store.get_model_usage(req.conversation_id)['ref'] == 'chosen'


def test_delete_pi_session_archives_authoritative_history(harness):
    _, _, store, _, req = harness
    runtime_dir = store.storage_dir / 'runtime_sessions' / req.conversation_id
    runtime_dir.mkdir(parents=True)
    (runtime_dir / 'history.jsonl').write_text('native session history')
    assert store.delete(req.conversation_id)
    assert not runtime_dir.exists()
    archived = list((store.storage_dir / 'runtime_sessions' / '.trash').iterdir())
    assert len(archived) == 1
    assert (archived[0] / 'history.jsonl').read_text() == 'native session history'
    assert (archived[0] / 'conversation.json').exists()


def test_targeted_delivery_requires_verified_owner_and_preserves_reconnect():
    import asyncio
    from app.core.connection_manager import ConnectionManager
    class Socket:
        def __init__(self):
            self.sent = []
        async def accept(self): pass
        async def close(self): pass
        async def send_text(self, payload): self.sent.append(payload)
    async def exercise():
        manager = ConnectionManager()
        old, replacement, legacy = Socket(), Socket(), Socket()
        await manager.connect(old, 'admin', 'device', 'admin', verified_login=True)
        await manager.connect(replacement, 'admin', 'device', 'admin', verified_login=True)
        await manager.disconnect('admin', 'device', old)
        await manager.send_personal_message({'type': 'approval'}, 'admin', 'device', expected_username='admin', expected_verified_login=True)
        assert len(replacement.sent) == 1
        await manager.connect(legacy, 'admin', 'device', 'admin', verified_login=False)
        await manager.send_personal_message({'type': 'approval'}, 'admin', 'device', expected_username='admin', expected_verified_login=True)
        assert legacy.sent == []
        await manager.send_personal_message({'type': 'approval'}, 'admin', 'device', expected_username='someone-else')
        assert legacy.sent == []
    asyncio.run(exercise())


def test_conversation_switch_and_request_admission_share_lifecycle_lock(harness):
    from app.core.worker_modules.worker_api_mode import WorkerApiModeBridge
    bridge, worker, store, context, req = harness
    bridge._active = None
    worker.agent_runtime_bridge = bridge
    entered, release, admitted = threading.Event(), threading.Event(), threading.Event()
    def switch(_):
        entered.set()
        assert release.wait(3)
        return True
    worker.api_source.switch_conversation = switch
    worker.api_source.get_history_as_messages = lambda: []
    worker.api_source.get_context_status = lambda: {}
    mode = WorkerApiModeBridge(worker)
    mutation = threading.Thread(target=mode.api_switch_conversation, args=('next',))
    def admission():
        with bridge._lock:
            bridge._active = {'request_id': 'next'}
            admitted.set()
    mutation.start()
    assert entered.wait(1)
    prompt = threading.Thread(target=admission)
    prompt.start()
    assert not admitted.wait(0.05)
    release.set()
    mutation.join(3)
    prompt.join(3)
    assert admitted.is_set() and not mutation.is_alive()


@pytest.mark.parametrize('provider,url,expected_provider,expected_url', [
    ('mimo', 'https://api.xiaomimimo.com/v1', 'xiaomi', 'https://api.xiaomimimo.com/v1'),
    ('gemini', '', 'google', 'https://generativelanguage.googleapis.com/v1beta'),
    ('gemini', 'https://generativelanguage.googleapis.com', 'google', 'https://generativelanguage.googleapis.com/v1beta'),
    ('openai_compatible', 'https://example.invalid/v1', 'data-bridge', 'https://example.invalid/v1'),
])
def test_start_maps_profile_controls_without_live_provider(harness, monkeypatch, provider, url, expected_provider, expected_url):
    from app.core.worker_modules import worker_agent_runtime as module
    bridge, worker, store, context, req = harness
    bridge._active = None
    worker._api_streaming = False
    worker.tool_router = SimpleNamespace(runtime_executor=None)
    profile = {'provider': provider, 'model': 'fake', 'api_key': 'fixture-only', 'base_url': url,
               'supports_reasoning': True, 'reasoning': {'enabled': True, 'effort': 'high'}, 'max_output_tokens': 1234}
    worker.api_source._resolve_runtime_profile = lambda *a: ('p', profile, None)
    worker.api_source._get_native_tool_definitions = lambda *_: []
    monkeypatch.setattr(module.APIModeConfigManager, 'load', lambda: {'conversation_defaults': {'context': {'max_window_tokens': 32000}}})
    monkeypatch.setattr('app.core.agent_runtime.registry.runtime_options', lambda: [{'id': 'pi', 'available': True}])
    captured = []
    class Runtime(FakeRuntime):
        def run(self, request, _handler):
            captured.append(request)
            yield AgentEvent('completed', request.conversation_id, request.request_id)
    bridge.runtime_factory = Runtime
    result = bridge.start('hello')
    assert result['ok']
    bridge._thread.join(3)
    assert len(captured) == 1
    assert captured[0].provider == expected_provider and captured[0].base_url == expected_url
    assert captured[0].max_tokens == 1234 and captured[0].context_window == 32000
    assert captured[0].thinking_level == 'high'
    assert captured[0].system_prompt == 'session-specific system'
