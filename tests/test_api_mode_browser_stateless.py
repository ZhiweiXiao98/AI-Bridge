import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.api_mode_config import APIModeConfigManager
from app.core.api_source import APISource
from app.core.conversation_store import ConversationStore
from app.core.worker_modules.worker_api_conversation import WorkerApiConversationBridge
from app.core.worker_modules.worker_browser_stateless import WorkerBrowserStatelessBridge


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
