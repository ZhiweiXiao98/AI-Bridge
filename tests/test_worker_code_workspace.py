from app.core.worker_modules import worker_code_workspace
from app.core.worker_modules.worker_code_workspace import WorkerCodeWorkspaceBridge
from tests.helpers import RecordingLock, RecordingSignal


class FakeUpdateService:
    def __init__(self):
        self.scanned = [{"rel_path": "app/demo.py"}]
        self.applied = None

    def scan(self):
        return self.scanned

    def process_updates(self, paths, status_callback, ota_callback):
        self.applied = (paths, status_callback, ota_callback)

    def pack_client_code(self):
        return {"app/demo.py": "print(1)"}


class FakeFileService:
    def __init__(self):
        self.ignored = []
        self.removed = []
        self.saved = []

    def add_ignored_content(self, filename, content):
        self.ignored.append((filename, content))
        return True, "ignored"

    def remove_ignored_content(self, content):
        self.removed.append(content)
        return True, "restored"

    def save_code(self, filename, content):
        self.saved.append((filename, content))


class FakeWorker:
    def __init__(self, staging_dir):
        self.config = {"export_code_path": str(staging_dir)}
        self.file_service = FakeFileService()
        self.update_service = FakeUpdateService()
        self.rpc_lock = RecordingLock()
        self.update_list_signal = RecordingSignal()
        self.ota_sync_signal = RecordingSignal()
        self.file_preview_signal = RecordingSignal()
        self.snapshot_ready_signal = RecordingSignal()
        self.statuses = []
        self.last_messages_snapshot = [{"index": 1, "text": "hello"}]
        self.processed_batches = []

    def safe_emit_status(self, text):
        self.statuses.append(text)

    def process_batch(self, messages):
        self.processed_batches.append(messages)


def test_scan_and_apply_use_rpc_lock_and_existing_signals(tmp_path):
    worker = FakeWorker(tmp_path)
    bridge = WorkerCodeWorkspaceBridge(worker)

    bridge.do_server_scan()
    bridge.do_server_apply(["app/demo.py"])

    assert worker.update_list_signal.items == [[{"rel_path": "app/demo.py"}]]
    assert worker.update_service.applied[0] == ["app/demo.py"]
    assert worker.update_service.applied[1] == worker.safe_emit_status
    assert worker.update_service.applied[2] == worker.ota_sync_signal.emit
    assert worker.rpc_lock.unlock_count == 2


def test_staging_preview_reads_new_and_old_content(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    project_root = tmp_path / "project"
    staging_dir.mkdir()
    (staging_dir / "app").mkdir()
    (staging_dir / "app" / "demo.py").write_text("new", encoding="utf-8")
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "demo.py").write_text("old", encoding="utf-8")

    class FakeProjectContext:
        @staticmethod
        def get():
            return FakeProjectContext()

        def get_project_root(self):
            return str(project_root)

    monkeypatch.setattr(worker_code_workspace, "ProjectContext", FakeProjectContext)
    worker = FakeWorker(staging_dir)

    WorkerCodeWorkspaceBridge(worker).get_staging_file_content("app/demo.py", client_id="Host")

    assert worker.file_preview_signal.items == [
        {
            "target_client_id": "Host",
            "rel_path": "app/demo.py",
            "content": "new",
            "old_content": "old",
        }
    ]


def test_ignore_unignore_save_sync_and_clear_cache(tmp_path):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    (staging_dir / "keep.py").write_text("x", encoding="utf-8")
    (staging_dir / "nested").mkdir()
    (staging_dir / "nested" / "file.py").write_text("y", encoding="utf-8")
    worker = FakeWorker(staging_dir)
    bridge = WorkerCodeWorkspaceBridge(worker)

    bridge.do_ignore_block("demo.py", "print(1)")
    bridge.do_unignore_block("demo.py", "print(1)")
    bridge.manual_save("demo.py", "print(2)")
    bridge.handle_sync_request(client_id="Remote")
    bridge.do_server_clear_cache()

    assert worker.file_service.ignored == [("demo.py", "print(1)")]
    assert worker.file_service.removed == ["print(1)"]
    assert worker.processed_batches == [worker.last_messages_snapshot]
    assert worker.file_service.saved == [("demo.py", "print(2)")]
    assert worker.ota_sync_signal.items == [{"app/demo.py": "print(1)"}]
    assert not any(staging_dir.iterdir())
    assert any("服务端暂存区已清空" in status for status in worker.statuses)
