"""Offline desktop lifecycle: no Docker daemon, provider, or external Node calls."""
import asyncio
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def docker_harness(tmp_path, monkeypatch):
    from app.core import docker_manager as module
    from app.core.config import ConfigManager
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    monkeypatch.setattr(ConfigManager, "load", lambda: {"sandbox_exec_mode": "docker"})
    monkeypatch.setattr(module.ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(tmp_path)))
    client = Mock()
    container = Mock(status="running", short_id="fixture")
    container.exec_run.return_value = SimpleNamespace(exit_code=0, output=(b"ok", b""))
    client.containers.get.side_effect = module.NotFound("fixture missing")
    client.containers.run.return_value = container
    client.containers.create.return_value = container
    connect = Mock(return_value=client)
    monkeypatch.setattr(module.docker, "from_env", connect)
    return module, connect, client, container


def test_desktop_start_never_connects_pulls_or_creates_docker(docker_harness):
    module, connect, client, _ = docker_harness
    manager = module.DockerManager()
    assert not manager.available and manager.container is None
    connect.assert_not_called()
    client.images.pull.assert_not_called()
    client.containers.run.assert_not_called()
    assert manager.shutdown(1)
    assert manager.shutdown(1)


def test_missing_image_is_actionable_and_never_executes_on_host(docker_harness):
    module, connect, client, _ = docker_harness
    client.images.get.side_effect = module.ImageNotFound("missing")
    manager = module.DockerManager()
    manager._execute_local = Mock()
    code, error = manager.execute_code("print(1)")
    assert code == -1 and manager.image in error and "手动" in error
    assert "不会" in error and manager.exec_mode == "docker"
    connect.assert_called_once_with(timeout=5)
    client.images.pull.assert_not_called()
    client.containers.run.assert_not_called()
    client.containers.create.assert_not_called()
    manager._execute_local.assert_not_called()
    assert manager.shutdown(1)


def test_explicit_tool_initializes_private_container_without_restart(docker_harness):
    module, _, client, container = docker_harness
    from app.core.skills.core.code_execution.skill import CodeExecutionSkill
    manager = module.DockerManager()
    result = CodeExecutionSkill(manager).execute("print(1)")
    assert "ok" in result and manager.available
    args = client.containers.create.call_args.kwargs
    assert args["name"] != module.DockerManager.CONTAINER_NAME
    assert args["restart_policy"] == {"Name": "no"}
    assert args["labels"]["ai-bridge.local-instance"] == manager._instance_id
    assert args["labels"]["ai-bridge.project-root"] == manager.project_root
    client.images.pull.assert_not_called()
    client.containers.run.assert_not_called()
    assert manager.shutdown(1)
    container.stop.assert_called_once()
    container.remove.assert_called_once()
    assert manager.shutdown(1)
    container.remove.assert_called_once()


def test_server_docker_startup_retains_existing_behavior(docker_harness, monkeypatch):
    module, connect, client, container = docker_harness
    monkeypatch.delenv("AI_BRIDGE_LOCAL_MODE")
    client.images.get.side_effect = module.ImageNotFound("missing")
    manager = module.DockerManager()
    connect.assert_called_once_with()
    client.images.pull.assert_called_once_with(manager.image)
    assert client.containers.run.call_args.kwargs["name"] == module.DockerManager.CONTAINER_NAME
    assert client.containers.run.call_args.kwargs["restart_policy"] == {"Name": "always"}
    manager.shutdown()
    container.stop.assert_not_called()


def test_local_docker_refuses_a_foreign_container(docker_harness):
    module, _, client, container = docker_harness
    client.containers.get.side_effect = None
    client.containers.get.return_value = container
    container.labels = {"ai-bridge.local-instance": "someone-else"}
    manager = module.DockerManager()
    assert manager.execute_code("print(1)")[0] == -1
    container.start.assert_not_called()
    container.update.assert_not_called()
    assert manager.shutdown(1)
    container.stop.assert_not_called()
    container.remove.assert_not_called()


def test_docker_image_disappearing_does_not_trigger_sdk_implicit_pull(docker_harness):
    module, _, client, _ = docker_harness
    client.containers.create.side_effect = module.ImageNotFound("removed between check and create")
    manager = module.DockerManager()
    assert manager.execute_code("print(1)")[0] == -1
    client.containers.run.assert_not_called()
    client.images.pull.assert_not_called()
    assert manager.shutdown(1)


@pytest.mark.parametrize("platform,relative", [("linux", "node/bin/node"), ("darwin", "node/bin/node"), ("win32", "node/node.exe")])
def test_frozen_pi_ignores_path_and_environment_overrides(tmp_path, monkeypatch, platform, relative):
    from app.core.agent_runtime import paths, PiRuntime
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("AI_BRIDGE_BUNDLED_NODE", "/untrusted/node")
    monkeypatch.setenv("PI_SIDECAR_PATH", "/untrusted/sidecar.mjs")
    monkeypatch.setattr(paths.shutil, "which", lambda _: "/untrusted/path/node")
    assert PiRuntime().command == [str(tmp_path / "bundle/runtime" / relative), str(tmp_path / "bundle/runtime/pi/sidecar.mjs")]


def test_source_pi_uses_path_node_and_source_sidecar(monkeypatch):
    from app.core.agent_runtime import paths, PiRuntime
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(paths.shutil, "which", lambda _: "/source/node")
    assert PiRuntime().command == ["/source/node", str(paths.sidecar_path())]
    assert paths.sidecar_path().is_file()


def test_registry_checks_the_same_bundled_node_and_sdk(tmp_path, monkeypatch):
    from app.core.agent_runtime import registry
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    root = tmp_path / "runtime/pi"
    package = root / "node_modules/@earendil-works/pi-coding-agent/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"0.99.1"}')
    (root / "sidecar.mjs").touch()
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="v22.19.0"))
    monkeypatch.setattr(registry.subprocess, "run", run)
    assert registry.runtime_options()[0]["available"]
    assert run.call_args.args[0][0] == str(tmp_path / "runtime/node/bin/node")
    package.unlink()
    assert not registry.runtime_options()[0]["available"]
    assert "重新安装" in registry.runtime_options()[0]["reason"]


def test_pi_shutdown_interrupts_missing_init_ack_and_is_idempotent(tmp_path):
    from app.core.agent_runtime import AgentRequest, PiRuntime
    script = tmp_path / "stalled.py"
    script.write_text("import time\ntime.sleep(60)\n")
    runtime = PiRuntime([sys.executable, str(script)])
    request = AgentRequest("c", "r", str(tmp_path), str(tmp_path / "sessions"), "fake", "fake")
    events = []
    thread = threading.Thread(target=lambda: events.extend(runtime.run(request, lambda *_: {})), daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while runtime._process is None or runtime._process.process is None:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    process = runtime._process.process
    before = time.monotonic()
    runtime.shutdown(timeout=0.5)
    thread.join(1)
    assert time.monotonic() - before < 1.5
    assert not thread.is_alive() and process.poll() is not None
    assert events[-1].kind == "cancelled"
    assert runtime.shutdown(0.1)
    assert list(runtime.run(request, lambda *_: {}))[-1].kind == "cancelled"


def test_pi_abort_overtaking_delayed_prompt_never_sends_that_prompt(tmp_path):
    from app.core.agent_runtime import AgentRequest, PiRuntime
    script = tmp_path / "ordered-sidecar.py"
    wire_log = tmp_path / "wire.log"
    script.write_text(
        "import json, pathlib, sys\n"
        f"wire = pathlib.Path({str(wire_log)!r})\n"
        "for line in sys.stdin:\n"
        " command = json.loads(line)\n"
        " with wire.open('a') as out: out.write(command['type'] + '\\n')\n"
        " data = {}\n"
        " if command['type'] == 'init':\n"
        "  session = pathlib.Path(command['session']['dir']) / 'session.jsonl'\n"
        "  session.touch()\n"
        "  data = {'sessionFile': str(session)}\n"
        " print(json.dumps({'type':'response', 'id':command['id'], 'success':True, 'data':data}), flush=True)\n"
    )
    entered, release = threading.Event(), threading.Event()
    class DelayedFirstWriter:
        def __init__(self):
            self.real_lock = threading.Lock()
            self.first = True
        def __enter__(self):
            if self.first:
                self.first = False
                entered.set()
                assert release.wait(3)
            self.real_lock.acquire()
        def __exit__(self, *_):
            self.real_lock.release()
    runtime = PiRuntime([sys.executable, str(script)])
    request = AgentRequest("c", "r", str(tmp_path), str(tmp_path / "sessions"), "fake", "fake")
    events = []
    def run():
        for event in runtime.run(request, lambda *_: {}):
            events.append(event)
            if event.kind == "started":
                runtime._process._write_lock = DelayedFirstWriter()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        runtime.cancel()  # This abort deliberately overtakes the paused prompt.
        assert wire_log.read_text().splitlines() == ["init", "abort"]
        release.set()
        thread.join(2)
        assert not thread.is_alive()
        assert events[-1].kind == "cancelled"
        assert wire_log.read_text().splitlines() == ["init", "abort"]
    finally:
        release.set()
        runtime.shutdown(1)
        thread.join(1)


def test_legacy_shutdown_cancels_provider_wait_and_rejects_restart():
    from app.core.api.api_stream_handler import APIStreamHandler
    from app.core.api.api_stream_models import StreamStatus
    entered, finished = threading.Event(), threading.Event()
    class Source:
        async def send_message_stream(self, *args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
                yield "not emitted"
            finally:
                finished.set()
    handler = APIStreamHandler(Source())
    handler.start_stream("offline")
    assert entered.wait(2)
    assert handler.shutdown(1)
    assert finished.is_set() and handler.state.status == StreamStatus.CANCELLED
    old_thread = handler._thread
    handler.start_stream("rejected")
    assert handler._thread is old_thread and handler.shutdown(0)


def test_knowledge_shutdown_cancels_queued_futures_without_abandoning_active_task():
    from app.core.knowledge.executor import KnowledgeExecutor
    entered, release = threading.Event(), threading.Event()
    def search(*_):
        entered.set()
        assert release.wait(3)
        return "done"
    executor = KnowledgeExecutor(SimpleNamespace(_search_impl=search))
    executor.start()
    active = executor.submit_search("first")
    assert entered.wait(1)
    queued = executor.submit_search("second")
    try:
        before = time.monotonic()
        assert not executor.stop(0.03)
        assert time.monotonic() - before < 0.3
        assert queued.cancelled() and executor.submit_warmup().cancelled()
        assert active.running()
    finally:
        release.set()
        assert executor.stop(1)
    assert active.result() == "done" and executor.stop(0)


def test_worker_shutdown_is_bounded_idempotent_and_keeps_active_tools_alive(monkeypatch):
    from PySide6.QtCore import QThread
    from app.core.worker import WorkerThread
    from app.core.services import knowledge_service
    class Component:
        def __init__(self): self.calls = []
        def shutdown(self, timeout=0):
            self.calls.append(timeout)
            return True
    class StoppingWorker(WorkerThread):
        def run(self):
            while self.running:
                self.msleep(5)
    worker = StoppingWorker.__new__(StoppingWorker)
    QThread.__init__(worker)
    worker._shutdown_lock = threading.Lock()
    worker._shutdown_started = worker._shutdown_complete = False
    worker.running = True
    worker.start()
    names = ("agent_runtime_bridge", "stream_bridge", "subagent_bridge", "knowledge_service", "docker_manager")
    for name in names:
        setattr(worker, name, Component())
    global_knowledge = Component()
    monkeypatch.setattr(knowledge_service, "knowledge_engine", global_knowledge)
    worker.executor = ThreadPoolExecutor(max_workers=1)
    release, entered = threading.Event(), threading.Event()
    def tool():
        entered.set()
        release.wait(3)
    active = worker.executor.submit(tool)
    assert entered.wait(1)
    pending = worker.executor.submit(lambda: pytest.fail("queued work ran during shutdown"))
    try:
        before = time.monotonic()
        assert not worker.shutdown(0.04)
        assert time.monotonic() - before < 0.4
        assert not worker.running and pending.cancelled() and not active.done()
        assert all(getattr(worker, name).calls[0] == 0 for name in names)
        assert global_knowledge.calls
    finally:
        release.set()
        assert worker.stop_worker(1)
    counts = [len(getattr(worker, name).calls) for name in names]
    assert worker.shutdown(0)
    assert [len(getattr(worker, name).calls) for name in names] == counts
    assert not worker.isRunning()


def _window_close_harness():
    # Exercise the real method without constructing the entire UI/plugin tree.
    source = Path(__file__).resolve().parents[1] / "app/ui/main_window.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    window = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    close = next(n for n in window.body if isinstance(n, ast.FunctionDef) and n.name == "closeEvent")
    class Base:
        def closeEvent(self, event):
            event.accept()
    app = Mock()
    timers = []
    namespace = {"Base": Base, "theme_manager": Mock(), "logger": Mock(), "os": __import__("os"),
                 "QApplication": SimpleNamespace(instance=lambda: app),
                 "QTimer": SimpleNamespace(singleShot=lambda delay, callback: timers.append(callback))}
    cls = ast.ClassDef(name="MainWindow", bases=[ast.Name(id="Base", ctx=ast.Load())],
                       keywords=[], body=[close], decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(source), "exec"), namespace)
    instance = namespace["MainWindow"]()
    instance.save_layout = Mock()
    instance.apply_theme = Mock()
    instance.statusBar = Mock(return_value=Mock())
    return instance, app, timers


def test_remote_window_close_never_calls_shutdown_rpc(monkeypatch):
    monkeypatch.delenv("AI_BRIDGE_LOCAL_MODE", raising=False)
    window, _, timers = _window_close_harness()
    looked_up = []
    class Remote:
        def stop_worker(self): pass
        def isRunning(self): return False
        def __getattr__(self, name):
            looked_up.append(name)
            return Mock()
    window.worker = Remote()
    window._is_remote = lambda: True
    event = Mock()
    window.closeEvent(event)
    assert looked_up == [] and not timers
    event.accept.assert_called_once()


def test_local_close_waits_for_shutdown_before_accepting_restart(monkeypatch):
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    window, app, timers = _window_close_harness()
    window.worker = SimpleNamespace(shutdown=Mock(side_effect=[False, True]))
    window._is_remote = lambda: False
    window._local_exit_code = 42
    event = Mock()
    window.closeEvent(event)
    event.ignore.assert_called_once()
    event.accept.assert_not_called()
    app.exit.assert_not_called()
    assert len(timers) == 1
    window.closeEvent(event)
    event.accept.assert_called_once()
    app.exit.assert_called_once_with(42)


def test_browser_shutdown_stops_only_owned_chromedriver_service():
    from app.core.driver.connection import ConnectionManager
    connection = ConnectionManager(9527)
    driver = Mock()
    service = Mock()
    connection.driver = driver
    connection._service = service
    assert connection.shutdown(1)
    assert connection.shutdown(0)
    service.stop.assert_called_once()
    driver.quit.assert_not_called()
    driver.close.assert_not_called()
    assert connection.driver is None
    assert not connection.connect()[0]


def test_browser_shutdown_remains_bounded_for_stuck_driver_service():
    from app.core.driver.connection import ConnectionManager
    connection = ConnectionManager(9527)
    release = threading.Event()
    connection._service = SimpleNamespace(stop=lambda: release.wait(3))
    try:
        before = time.monotonic()
        assert not connection.shutdown(0.02)
        assert time.monotonic() - before < 0.3
    finally:
        release.set()
        assert connection.shutdown(1)


def test_browser_shutdown_includes_previous_connection_attempt_services():
    from app.core.driver.connection import ConnectionManager
    connection = ConnectionManager(9527)
    first, second = Mock(), Mock()
    connection._owned_services = [first, second]
    connection._service = second
    assert connection.shutdown(1)
    first.stop.assert_called_once()
    second.stop.assert_called_once()


@pytest.mark.parametrize("stop_explicitly", [True, False])
def test_local_test_runner_is_background_and_owns_child_cancellation(tmp_path, monkeypatch, stop_explicitly):
    import subprocess
    import psutil
    from app.core.worker_modules import worker_test_runner as module
    from tests.helpers import RecordingSignal
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    monkeypatch.setattr(module.ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(tmp_path)))
    original_popen = subprocess.Popen
    marker = tmp_path / "started"
    script = ("import pathlib, subprocess, sys, time\n"
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
              f"pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n"
              "print('started', flush=True)\ntime.sleep(60)\n")
    def launch(_command, **kwargs):
        return original_popen([sys.executable, "-u", "-c", script], **kwargs)
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    executor = ThreadPoolExecutor(max_workers=1)
    worker = SimpleNamespace(config={"test_timeout_seconds": 10 if stop_explicitly else 1}, executor=executor,
                             safe_emit_status=Mock(), test_result_signal=RecordingSignal())
    bridge = module.WorkerTestRunnerBridge(worker)
    try:
        before = time.monotonic()
        future = bridge.run_remote_tests()
        assert time.monotonic() - before < 0.3
        deadline = time.monotonic() + 2
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        child_pid = int(marker.read_text())
        if stop_explicitly:
            before = time.monotonic()
            bridge.shutdown(0.02)
            assert time.monotonic() - before < 0.3
        future.result(timeout=4)
        assert bridge.shutdown(2)
        assert worker.test_result_signal.items[-1]["failed"] >= 1
        assert "超时" in worker.test_result_signal.items[-1]["full_log"]
        assert bridge.run_remote_tests() is None
        assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    finally:
        bridge.shutdown(2)
        executor.shutdown(wait=True, cancel_futures=True)
