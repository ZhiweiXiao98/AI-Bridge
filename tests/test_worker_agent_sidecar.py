import threading
from types import SimpleNamespace

from app.core.worker_modules.worker_agent_sidecar import WorkerAgentSidecarBridge


class FakeScheduler:
    def __init__(self):
        self.tasks = []

    def add_task(self, client_id, action, *args, **kwargs):
        self.tasks.append((client_id, action, args, kwargs))
        return f"task_{len(self.tasks)}"


class FakeAgent:
    def __init__(self, mechanic_idx=None, intent="CHAT"):
        self.mechanic_idx = mechanic_idx
        self.intent = intent

    def get_mechanic_index(self):
        return self.mechanic_idx

    def construct_system_prompt(self, error_report):
        return f"PROMPT::{error_report}"

    def parse_agent_response(self, full_text):
        return self.intent, None


class FakeConnector:
    def __init__(self, busy=False, messages=None):
        self._busy = busy
        self._messages = messages or []

    def is_busy(self):
        return self._busy

    def get_chat_content(self, target_class, auto_wake=False):
        return self._messages, None


class FakeWorker:
    def __init__(self, mechanic_idx=None, busy=False, messages=None, current_physical_index=3):
        self.agent = FakeAgent(mechanic_idx=mechanic_idx)
        self.scheduler = FakeScheduler()
        self.current_physical_index = current_physical_index
        self.current_user = "System"
        self.current_chat_id = "chat_1"
        self.target_class = "aa-chat-message"
        self.connector = FakeConnector(busy=busy, messages=messages)
        self._processed_lock = threading.RLock()
        self._processed_tool_fingerprints = set()
        self._processed_fp_order = []
        self.statuses = []

    def safe_emit_status(self, text):
        self.statuses.append(text)


def test_request_auto_fix_creates_sidecar_when_missing():
    worker = FakeWorker(mechanic_idx=None)
    bridge = WorkerAgentSidecarBridge(worker)

    bridge.request_auto_fix("traceback", client_id="Host", username="Ada")

    assert [task[1] for task in worker.scheduler.tasks] == [
        "new_chat_task",
        "real_send_text",
        "task_agent_loop",
    ]
    assert worker.scheduler.tasks[1][2] == ("div.aa-chat-input textarea", "PROMPT::traceback")
    assert worker.scheduler.tasks[2][2] == (0, 4, 10)
    assert any("侧车会话" in status for status in worker.statuses)


def test_request_auto_fix_switches_to_existing_mechanic():
    worker = FakeWorker(mechanic_idx=2)
    bridge = WorkerAgentSidecarBridge(worker)

    bridge.request_auto_fix("boom", client_id="Host", username="Lin")

    assert worker.scheduler.tasks[0][1:] == ("switch_session_task", (2,), {"username": "Lin"})
    assert worker.scheduler.tasks[1][1] == "real_send_text"
    assert worker.scheduler.tasks[2][1] == "task_agent_loop"
    assert worker.scheduler.tasks[2][2] == (2, 3, 10)


def test_agent_loop_requeues_when_browser_is_busy():
    worker = FakeWorker(busy=True)
    bridge = WorkerAgentSidecarBridge(worker)
    task = SimpleNamespace(client_id="Host", args=(3, 7))

    bridge.execute_agent_loop_task(task)

    assert worker.scheduler.tasks == [
        ("Host", "task_agent_loop", (None, 3, 7), {"username": "System"})
    ]
    assert worker.statuses == ["⏳ Agent 思考中..."]


def test_agent_loop_switches_back_to_mechanic_before_reading():
    worker = FakeWorker(
        mechanic_idx=2,
        busy=False,
        current_physical_index=3,
        messages=[{"segments": [{"type": "text", "content": "done"}]}],
    )
    bridge = WorkerAgentSidecarBridge(worker)
    task = SimpleNamespace(client_id="Host", args=(2, 3, 7))

    bridge.execute_agent_loop_task(task)

    assert worker.scheduler.tasks == [
        ("Host", "switch_session_task", (2,), {"username": "System"}),
        ("Host", "task_agent_loop", (2, 3, 7), {"username": "System"}),
    ]
    assert any("前往侧车会话 #2" in status for status in worker.statuses)
