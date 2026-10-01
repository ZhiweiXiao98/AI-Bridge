import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.api_mode_config import APIModeConfigManager
from app.core.api_source import APISource
from app.core.context_manager import ContextManager
from app.core.conversation_store import ConversationStore
from app.core.worker_modules.worker_api_conversation import WorkerApiConversationBridge
from app.core.worker_modules.worker_browser_stateless import WorkerBrowserStatelessBridge
from app.core.worker_modules.worker_context_workspace import WorkerContextWorkspaceBridge
from app.core.tool_runtime.models import ToolIntent


class _FakeInitConversationStore:
    active_id = None
    context_manager = None

    def list_conversations(self):
        return []

    def switch(self, conv_id):
        self.active_id = conv_id
        return True

    def get_model_usage(self, conv_id):
        return None


def _config_with_browser_profile():
    return {
        "active_profile": "default",
        "profiles": {
            "default": {
                "name": "Default",
                "kind": "api",
                "provider": "openai_compatible",
            },
            "browser_web": {
                "name": "Browser Web",
                "kind": "browser_stateless",
                "provider": "web_ai",
                "timeout_seconds": 180,
            },
        },
        "api_mode_usage": {
            "type": "profile",
            "ref": "browser_web",
        },
    }


def test_api_mode_usage_resolves_browser_stateless_profile_key():
    cfg = APIModeConfigManager._normalize(_config_with_browser_profile())

    assert APIModeConfigManager.get_active_profile_key(cfg) == "browser_web"
    assert APIModeConfigManager.get_active_profile(cfg)["kind"] == "browser_stateless"


def test_api_mode_usage_chain_accepts_list_and_returns_first_profile():
    cfg = _config_with_browser_profile()
    cfg["api_mode_usage"] = {"type": "chain", "ref": "browser_chain"}
    cfg["fallback_chains"] = {"browser_chain": ["browser_web", "default"]}

    assert APIModeConfigManager.get_active_profile_key(cfg) == "browser_web"


def test_apply_profile_runtime_browser_stateless_clears_provider(monkeypatch):
    cfg = APIModeConfigManager._normalize(_config_with_browser_profile())
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: None))

    source = APISource()
    source.llm_provider = object()

    source._apply_profile_runtime("browser_web", persist_active=False)

    assert source.llm_provider is None
    assert source.current_runtime_profile_key == "browser_web"


def test_api_source_initialize_without_provider_credentials_does_not_crash(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "api",
        "profiles": {
            "api": {
                "name": "API",
                "kind": "api",
                "provider": "openai_compatible",
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "api"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))
    monkeypatch.setattr("app.core.api_source.ConversationStore", lambda *args, **kwargs: _FakeInitConversationStore())

    def _raise_missing_credentials(payload):
        raise RuntimeError("Missing credentials")

    monkeypatch.setattr("app.core.api_source.create_provider", _raise_missing_credentials)

    source = APISource()
    source.initialize()

    assert source._initialized is True
    assert source.current_runtime_profile_key == "api"
    assert source.llm_provider is None
    assert "Missing credentials" in source.provider_init_error
    assert source.get_conversations() == []


def test_api_source_reload_runtime_config_rebuilds_provider_after_key_is_saved(monkeypatch):
    cfg = APIModeConfigManager._normalize({
        "active_profile": "api",
        "profiles": {
            "api": {
                "name": "API",
                "kind": "api",
                "provider": "openai_compatible",
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "api"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))
    monkeypatch.setattr("app.core.api_source.ConversationStore", lambda *args, **kwargs: _FakeInitConversationStore())

    created = []

    class _Provider:
        def update_config(self, **kwargs):
            pass

    def _create_provider(payload):
        api_key = payload.get("api", {}).get("api_key", "")
        if not api_key:
            raise RuntimeError("Missing credentials")
        created.append(payload)
        return _Provider()

    monkeypatch.setattr("app.core.api_source.create_provider", _create_provider)

    source = APISource()
    source.initialize()
    assert source.llm_provider is None

    cfg["profiles"]["api"]["api_key"] = "sk-test-placeholder"
    source.reload_runtime_config()

    assert source.llm_provider is not None
    assert source.provider_init_error is None
    assert created[-1]["api"]["api_key"] == "sk-test-placeholder"


def test_set_active_profile_does_not_override_api_mode_usage(monkeypatch):
    cfg = APIModeConfigManager._normalize(_config_with_browser_profile())
    cfg["api_mode_usage"] = {"type": "profile", "ref": "default"}

    saved = {}
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: saved.update(data)))

    APIModeConfigManager.set_active_profile("browser_web")

    assert saved["active_profile"] == "browser_web"
    assert saved["api_mode_usage"] == {"type": "profile", "ref": "default"}


def test_create_browser_profile_does_not_override_api_mode_usage(monkeypatch):
    cfg = APIModeConfigManager._normalize(_config_with_browser_profile())
    cfg["profiles"].pop("browser_web")
    cfg["api_mode_usage"] = {"type": "profile", "ref": "default"}

    saved = {}
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: saved.update(data)))

    APIModeConfigManager.create_browser_stateless_profile("browser_web")

    assert saved["profiles"]["browser_web"]["kind"] == "browser_stateless"
    assert saved["active_profile"] == "browser_web"
    assert saved["api_mode_usage"] == {"type": "profile", "ref": "default"}


def test_editing_profile_uses_settings_selection_not_runtime_usage():
    cfg = APIModeConfigManager._normalize(_config_with_browser_profile())
    cfg["active_profile"] = "browser_web"
    cfg["api_mode_usage"] = {"type": "profile", "ref": "default"}

    editing_profile = APIModeConfigManager.get_editing_profile(cfg)
    runtime_profile = APIModeConfigManager.get_active_profile(cfg)

    assert editing_profile["kind"] == "browser_stateless"
    assert runtime_profile["kind"] == "api"


def test_conversation_model_usage_overrides_global_usage():
    cfg = APIModeConfigManager._normalize(_config_with_browser_profile())
    cfg["api_mode_usage"] = {"type": "profile", "ref": "default"}

    class FakeConversationStore:
        active_id = "conv_1"

        def get_model_usage(self, conv_id):
            assert conv_id == "conv_1"
            return {"type": "profile", "ref": "browser_web"}

    source = APISource()
    source.config_dict = cfg
    source.conv_store = FakeConversationStore()

    assert source._resolve_profile_key() == "browser_web"


def test_profile_can_send_core_prompt_as_developer_role():
    cfg = {
        "active_profile": "default",
        "profiles": {
            "default": {
                "name": "Default",
                "kind": "api",
                "provider": "openai_compatible",
                "system_prompt_role": "developer",
            },
        },
    }
    source = APISource()
    source.config_dict = APIModeConfigManager._normalize(cfg)

    class FakeConversationStore:
        active_id = "conv_1"

        def get_model_usage(self, conv_id):
            return None

    source.conv_store = FakeConversationStore()
    cm = ContextManager()
    cm.set_system_prompt("核心身份提示词")
    cm.inject_long_term(["长期记忆"])
    cm.add_message("user", "你好")

    messages = source._build_request_messages(cm)

    assert messages[0] == {"role": "developer", "content": "核心身份提示词"}
    assert messages[1]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "你好"}


def test_prepare_browser_stateless_request_context_uses_api_context_layers():
    source = APISource()
    source._initialized = True
    calls = []

    class FakeConversationStore:
        active_id = "conv_1"

    source.conv_store = FakeConversationStore()
    source._refresh_context_manager_system_prompt = lambda conversation_id=None: calls.append(("system", conversation_id))
    source._inject_journal_long_term = lambda conversation_id=None: calls.append(("journal", conversation_id))
    source._maybe_compact_context = lambda conversation_id=None: calls.append(("compact", conversation_id))
    source.build_current_request_messages = lambda conversation_id=None: [
        {"role": "system", "content": "系统层"},
        {"role": "user", "content": "用户消息"},
    ]
    source.get_context_status = lambda conversation_id=None: {"conversation_id": conversation_id, "total_used": 10}

    payload = source.prepare_browser_stateless_request_context(conversation_id="conv_1")

    assert calls == [("system", "conv_1"), ("journal", "conv_1"), ("compact", "conv_1")]
    assert payload["conversation_id"] == "conv_1"
    assert payload["messages"][0]["content"] == "系统层"
    assert payload["context_status"]["total_used"] == 10


def test_conversation_model_usage_persists(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path))
    conv_id = store.create("profile-bound")

    ok = store.set_model_usage(conv_id, {"type": "profile", "ref": "browser_web"})

    assert ok is True
    assert store.get_model_usage(conv_id) == {"type": "profile", "ref": "browser_web"}

    reloaded = ConversationStore(storage_dir=str(tmp_path))
    assert reloaded.get_model_usage(conv_id) == {"type": "profile", "ref": "browser_web"}


def test_conversation_model_usage_persists_runtime_overrides(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path))
    conv_id = store.create("profile-bound")
    usage = {
        "type": "profile",
        "ref": "api",
        "model": "mimo-v2.5-pro",
        "reasoning": {"enabled": True, "effort": "high"},
    }

    ok = store.set_model_usage(conv_id, usage)

    assert ok is True
    assert store.get_model_usage(conv_id) == usage

    reloaded = ConversationStore(storage_dir=str(tmp_path))
    assert reloaded.get_model_usage(conv_id) == usage


def test_global_conversation_store_keeps_index_when_project_switches(tmp_path):
    storage_dir = tmp_path / "global_conversations"
    project_b = tmp_path / "project_b"
    project_b.mkdir()
    store = ConversationStore(storage_dir=str(storage_dir))
    conv_id = store.create("multi-project")
    original_dir = store.storage_dir

    store.on_project_switched(str(project_b), str(tmp_path / "knowledge_b"))

    assert store.storage_dir == original_dir
    assert store.active_id == conv_id
    assert [c["id"] for c in store.list_conversations()] == [conv_id]


def test_api_history_messages_preserve_reasoning_segments(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path))
    store.create("reasoning")
    segments = [
        {"type": "thinking", "content": "先分析"},
        {"type": "text", "content": "结论"},
    ]
    store.context_manager.add_structured_message(
        "assistant",
        "结论",
        segments=segments,
        raw_content="结论",
        meta={"reasoning_content": "先分析"},
        source_mode="api",
    )

    source = APISource.__new__(APISource)
    source._initialized = True
    source.conv_store = store

    messages = source.get_history_as_messages()

    assert messages[-1]["segments"] == segments
    assert messages[-1]["segments"][0]["type"] == "thinking"


def test_conversation_request_snapshot_persists_across_reload_and_save(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path))
    conv_id = store.create("snapshot")
    snapshot = {
        "conversation_id": conv_id,
        "timestamp": 1234.0,
        "model": "mimo-v2.5-pro",
        "profile_key": "mimo",
        "system_blocks": {},
        "final_messages": [{"role": "user", "content": "hello"}],
        "response": "world",
    }

    assert store.set_last_request_snapshot(conv_id, snapshot) is True
    store.context_manager.add_structured_message("user", "hello", source_mode="api")
    store.save_current()

    reloaded = ConversationStore(storage_dir=str(tmp_path))
    loaded = reloaded.get_last_request_snapshot(conv_id)

    assert loaded["conversation_id"] == conv_id
    assert loaded["response"] == "world"
    assert loaded["final_messages"][0]["content"] == "hello"


def test_conversation_request_snapshot_serializes_tool_candidates(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path))
    conv_id = store.create("snapshot-tools")

    ok = store.set_last_request_snapshot(
        conv_id,
        {
            "conversation_id": conv_id,
            "timestamp": 1235.0,
            "tool_candidates": [ToolIntent(kind="skill", name="echo", arguments={"text": "hi"})],
        },
    )

    assert ok is True
    loaded = ConversationStore(storage_dir=str(tmp_path)).get_last_request_snapshot(conv_id)
    assert loaded["tool_candidates"][0]["name"] == "echo"
    assert loaded["tool_candidates"][0]["arguments"] == {"text": "hi"}


def test_api_source_reads_persisted_snapshot_when_memory_empty(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path))
    conv_id = store.create("snapshot")
    store.set_last_request_snapshot(
        conv_id,
        {
            "conversation_id": conv_id,
            "timestamp": 1236.0,
            "model": "gpt-test",
            "system_blocks": {},
            "final_messages": [{"role": "user", "content": "persisted"}],
            "response": "ok",
        },
    )
    source = APISource.__new__(APISource)
    source.conv_store = store
    source._last_request_snapshot = None

    snap = source.get_last_request_snapshot(conversation_id=conv_id)

    assert snap["response"] == "ok"
    assert source._last_request_snapshot["conversation_id"] == conv_id


def test_api_source_falls_back_to_latest_snapshot_for_empty_target(tmp_path):
    store = ConversationStore(storage_dir=str(tmp_path))
    older_id = store.create("older")
    store.set_last_request_snapshot(older_id, {"conversation_id": older_id, "timestamp": 10.0, "response": "older"})
    latest_id = store.create("latest")
    store.set_last_request_snapshot(latest_id, {"conversation_id": latest_id, "timestamp": 20.0, "response": "latest"})
    empty_id = store.create("empty")
    source = APISource.__new__(APISource)
    source.conv_store = store
    source._last_request_snapshot = None

    snap = source.get_last_request_snapshot(conversation_id=empty_id)

    assert snap["conversation_id"] == latest_id
    assert snap["response"] == "latest"


def test_context_workspace_snapshot_request_initializes_api_source():
    class FakeSignal:
        def __init__(self):
            self.payloads = []

        def emit(self, payload):
            self.payloads.append(payload)

    class FakeApiSource:
        def get_last_request_snapshot(self, conversation_id=None):
            return {
                "conversation_id": conversation_id or "active",
                "timestamp": 1237.0,
                "response": "loaded",
            }

    class FakeWorker:
        def __init__(self):
            self.api_source = None
            self.context_snapshot_signal = FakeSignal()
            self.initialized = False

        def _init_api_source(self):
            self.initialized = True
            self.api_source = FakeApiSource()

    worker = FakeWorker()
    bridge = WorkerContextWorkspaceBridge(worker)

    snap = bridge.get_last_request_snapshot(conversation_id="conv_1")

    assert worker.initialized is True
    assert snap["response"] == "loaded"
    assert worker.context_snapshot_signal.payloads[-1]["conversation_id"] == "conv_1"


def test_worker_api_conversation_bridge_sets_profile_usage():
    class FakeSignal:
        def __init__(self):
            self.payloads = []

        def emit(self, payload):
            self.payloads.append(payload)

    class FakeApiSource:
        def __init__(self):
            self.calls = []

        def set_conversation_model_usage(self, conv_id, usage):
            self.calls.append((conv_id, usage))
            return True

        def get_conversations(self):
            return [{"id": "conv_1", "model_usage": {"type": "profile", "ref": "browser_web"}}]

        def get_context_status(self, conversation_id=None):
            return {
                "conversation_id": conversation_id,
                "conversation_model_usage": {"type": "profile", "ref": "browser_web"},
            }

    class FakeWorker:
        def __init__(self):
            self.api_source = FakeApiSource()
            self.sessions_signal = FakeSignal()
            self.context_status_signal = FakeSignal()
            self.statuses = []

        def _init_api_source(self):
            pass

        def safe_emit_status(self, text):
            self.statuses.append(text)

    worker = FakeWorker()
    bridge = WorkerApiConversationBridge(worker)

    ok = bridge.set_model_usage("conv_1", {"type": "profile", "ref": "browser_web"})

    assert ok is True
    assert worker.api_source.calls == [("conv_1", {"type": "profile", "ref": "browser_web"})]
    assert worker.sessions_signal.payloads
    assert worker.context_status_signal.payloads[-1]["conversation_id"] == "conv_1"
    assert "browser_web" in worker.statuses[-1]


def test_worker_api_conversation_bridge_restores_default_usage():
    class FakeSignal:
        def __init__(self):
            self.payloads = []

        def emit(self, payload):
            self.payloads.append(payload)

    class FakeApiSource:
        def __init__(self):
            self.calls = []

        def set_conversation_model_usage(self, conv_id, usage):
            self.calls.append((conv_id, usage))
            return True

        def get_conversations(self):
            return [{"id": "conv_1", "model_usage": None}]

        def get_context_status(self, conversation_id=None):
            return {"conversation_id": conversation_id, "conversation_model_usage": None}

    class FakeWorker:
        def __init__(self):
            self.api_source = FakeApiSource()
            self.sessions_signal = FakeSignal()
            self.context_status_signal = FakeSignal()
            self.statuses = []

        def _init_api_source(self):
            pass

        def safe_emit_status(self, text):
            self.statuses.append(text)

    worker = FakeWorker()
    bridge = WorkerApiConversationBridge(worker)

    ok = bridge.set_model_usage("conv_1", None)

    assert ok is True
    assert worker.api_source.calls == [("conv_1", None)]
    assert worker.context_status_signal.payloads[-1]["conversation_model_usage"] is None
    assert "全局默认" in worker.statuses[-1]


def test_browser_stateless_bridge_emits_transient_reply_without_persisting():
    class FakeSignal:
        def __init__(self):
            self.payloads = []

        def emit(self, payload):
            self.payloads.append(payload)

    class FakeApiSource:
        def __init__(self):
            self.persisted = []

        def get_history_as_messages_for(self, conv_id):
            return [{"id": "user_1", "conversation_id": conv_id, "role": "User", "segments": [{"type": "text", "content": "hi"}], "source": "api"}]

        def build_message_for_signal(self, role, content, index=0, kind="text", meta=None, raw_content="", segments=None):
            return {
                "id": "built",
                "conversation_id": "conv_1",
                "role": "AI" if role == "assistant" else "User",
                "index": index,
                "segments": segments or [{"type": "text", "content": content}],
                "raw_content": raw_content or content,
                "meta": meta or {},
                "source": "api",
            }

        def append_assistant_message(self, *args, **kwargs):
            self.persisted.append((args, kwargs))

    class FakeWorker:
        def __init__(self):
            self.messages_signal = FakeSignal()
            self.api_stream_chunk_signal = FakeSignal()
            self.api_stream_status_signal = FakeSignal()

    api_source = FakeApiSource()
    worker = FakeWorker()
    bridge = WorkerBrowserStatelessBridge(worker)

    bridge._emit_transient_reply(
        api_source,
        "conv_1",
        {
            "raw_text": "生成中",
            "raw_len": 3,
            "message": {
                "id": "ai_1",
                "segments": [{"type": "text", "content": "生成中"}],
            },
        },
        "req_1",
    )

    assert not api_source.persisted
    assert worker.messages_signal.payloads
    assert worker.api_stream_chunk_signal.payloads[-1]["upstream_event"] == "structured"
    transient = worker.messages_signal.payloads[-1][-1]
    assert transient["status"] == "streaming"
    assert transient["meta"]["transient"] is True
