from app.core.worker_modules.worker_browser_message_sync import WorkerBrowserMessageSyncBridge
from tests.helpers import RecordingSignal


class FakeStateService:
    def should_emit_sync(self, chat_id, bubble_count, force=False):
        assert chat_id == "chat_1"
        assert bubble_count == 5
        assert force is True
        return True, 2


class FakeWorker:
    def __init__(self):
        self.current_chat_id = "chat_1"
        self.current_bubble_count = 5
        self.state_service = FakeStateService()
        self.state_sync_signal = RecordingSignal()
        self.context_health_signal = RecordingSignal()


def test_check_and_emit_sync_projects_state_and_health():
    worker = FakeWorker()
    bridge = WorkerBrowserMessageSyncBridge(worker)

    bridge.check_and_emit_sync(force=True)

    assert worker.state_sync_signal.payloads == [(5, 2)]
    assert worker.context_health_signal.payloads == [(5, 3)]


def test_prescan_tool_call_ids_writes_missing_id():
    worker = FakeWorker()
    bridge = WorkerBrowserMessageSyncBridge(worker)
    raw_msgs = [
        {
            "role": "AI",
            "segments": [
                {
                    "type": "code",
                    "language": "tool_call",
                    "content": '{"name":"run_remote_script","arguments":{"code":"print(1)"}}',
                    "block_key": "block_1",
                }
            ],
        }
    ]

    bridge.prescan_tool_call_ids(raw_msgs)

    segment = raw_msgs[0]["segments"][0]
    assert segment["tool_call_id"].startswith("toolcall_")


def test_prescan_tool_call_id_is_stable_when_block_content_changes():
    worker = FakeWorker()
    bridge = WorkerBrowserMessageSyncBridge(worker)
    first = {
        "role": "AI",
        "segments": [
            {
                "type": "code",
                "language": "tool_call",
                "content": '{"name":"run_remote_script","arguments":{"code":"print(1)"}}',
                "block_key": "ai_msg_1:0",
            }
        ],
    }
    second = {
        "role": "AI",
        "segments": [
            {
                "type": "code",
                "language": "tool_call",
                "content": '{"name":"run_remote_script","arguments":{"code":"print(2)"}}',
                "block_key": "ai_msg_1:0",
            }
        ],
    }

    bridge.prescan_tool_call_ids([first])
    bridge.prescan_tool_call_ids([second])

    assert first["segments"][0]["tool_call_id"] == second["segments"][0]["tool_call_id"]
