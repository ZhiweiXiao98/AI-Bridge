from app.core.worker_modules.worker_browser_commands import WorkerBrowserCommandBridge


class FakeScheduler:
    def __init__(self):
        self.tasks = []

    def add_task(self, client_id, action, *args, **kwargs):
        self.tasks.append((client_id, action, args, kwargs))


class FakeEngine:
    def get_msg_text(self, msg):
        return msg["text"]


class FakeWorker:
    def __init__(self):
        self.scheduler = FakeScheduler()
        self.engine = FakeEngine()
        self.last_messages_snapshot = [
            {"index": 7, "text": "line one\nline two with enough text to trim"},
        ]


def test_send_text_and_compound_commands_enqueue_scheduler_tasks():
    worker = FakeWorker()
    bridge = WorkerBrowserCommandBridge(worker)

    bridge.send_text("textarea", "hello", client_id="Host", username="Ada")
    bridge.send_compound("hello", ["a.png"], client_id="Host")

    assert worker.scheduler.tasks == [
        ("Host", "real_send_text", ("textarea", "hello"), {"username": "Ada"}),
        ("Host", "compound_send_task", ("hello", ["a.png"]), {}),
    ]


def test_browser_navigation_commands_enqueue_expected_actions():
    worker = FakeWorker()
    bridge = WorkerBrowserCommandBridge(worker)

    bridge.upload_file("a.txt")
    bridge.request_switch_session(2)
    bridge.new_chat()
    bridge.request_wake_up()
    bridge.request_fix_all()

    assert [task[1] for task in worker.scheduler.tasks] == [
        "upload_file_task",
        "switch_session_task",
        "new_chat_task",
        "task_wake_up",
        "task_fix_all",
    ]


def test_run_remote_script_wraps_code_as_python_prompt():
    worker = FakeWorker()
    bridge = WorkerBrowserCommandBridge(worker)

    bridge.run_remote_script("print(1)", client_id="client_1")

    client_id, action, args, kwargs = worker.scheduler.tasks[0]
    assert client_id == "client_1"
    assert action == "real_send_text"
    assert args[0] == "div.aa-chat-input textarea"
    assert "```python\nprint(1)\n```" in args[1]


def test_trigger_manual_toggle_adds_message_fingerprint():
    worker = FakeWorker()
    bridge = WorkerBrowserCommandBridge(worker)

    bridge.trigger_manual_toggle(7, 1, 3, client_id="Host")

    assert worker.scheduler.tasks == [
        (
            "Host",
            "task_manual_toggle",
            (7, 1, 3),
            {"fingerprint": "line oneline two with enough"},
        )
    ]
