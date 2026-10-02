"""Offline regression coverage for bundled-app subprocess safety."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import python_runtime as runtime


def make_executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("external interpreter placeholder", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    app = make_executable(tmp_path / "AI-Bridge.app" / "Contents" / "MacOS" / "AI-Bridge")
    extracted = tmp_path / "AI-Bridge.app" / "Contents" / "Frameworks"
    extracted.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app))
    monkeypatch.setattr(sys, "_MEIPASS", str(extracted), raising=False)
    monkeypatch.delenv("AI_BRIDGE_PYTHON", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    return SimpleNamespace(app=app, extracted=extracted, project=project)


def test_source_defaults_to_current_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("AI_BRIDGE_PYTHON", raising=False)
    assert runtime.resolve_project_python(tmp_path) == sys.executable


def test_frozen_missing_python_is_actionable_and_never_probed(frozen, monkeypatch):
    probe = Mock(side_effect=AssertionError("must not launch app"))
    monkeypatch.setattr("subprocess.run", probe)
    with pytest.raises(runtime.PythonRuntimeUnavailable, match="AI_BRIDGE_PYTHON"):
        runtime.resolve_project_python(frozen.project, purpose="运行 pytest")
    probe.assert_not_called()


def test_frozen_explicit_app_is_rejected(frozen):
    with pytest.raises(runtime.PythonRuntimeUnavailable, match="应用本身"):
        runtime.resolve_project_python(frozen.project, frozen.app)


def test_frozen_alias_of_app_is_rejected(frozen):
    alias = frozen.project / "python"
    alias.symlink_to(frozen.app)
    with pytest.raises(runtime.PythonRuntimeUnavailable, match="应用本身"):
        runtime.resolve_project_python(frozen.project, alias)


def test_frozen_bundled_binary_is_rejected(frozen):
    binary = make_executable(frozen.extracted / "python")
    with pytest.raises(runtime.PythonRuntimeUnavailable, match="应用本身"):
        runtime.resolve_project_python(frozen.project, binary)


def test_frozen_external_interpreter_with_spaces(frozen):
    python = make_executable(frozen.project / "Python Tools" / "python")
    assert runtime.resolve_project_python(frozen.project, python) == str(python)


def test_frozen_venv_preserves_symlink_not_base_python(frozen, tmp_path):
    python = make_executable(tmp_path / "external" / "python")
    venv = frozen.project / ".venv" / "bin" / "python3"
    venv.parent.mkdir(parents=True)
    venv.symlink_to(python)
    assert runtime.resolve_project_python(frozen.project) == str(venv)


def test_frozen_windows_project_venv(frozen):
    python = make_executable(frozen.project / ".venv" / "Scripts" / "python.exe")
    assert runtime.resolve_project_python(frozen.project) == str(python)


def test_environment_interpreter_is_supported(frozen, monkeypatch):
    python = make_executable(frozen.project / "external" / "python")
    monkeypatch.setenv("AI_BRIDGE_PYTHON", str(python))
    assert runtime.resolve_project_python(frozen.project) == str(python)


def test_invalid_explicit_path_does_not_fall_back_to_venv(frozen):
    make_executable(frozen.project / ".venv" / "bin" / "python")
    with pytest.raises(runtime.PythonRuntimeUnavailable, match="找不到"):
        runtime.resolve_project_python(frozen.project, "missing/python")


def test_project_relative_interpreter(frozen):
    python = make_executable(frozen.project / "tools" / "python")
    assert runtime.resolve_project_python(frozen.project, "tools/python") == str(python)


def test_frozen_environment_restores_library_paths(frozen, monkeypatch):
    monkeypatch.setenv("PYTHONHOME", "bundle")
    monkeypatch.setenv("PYTHONPATH", "bundle")
    monkeypatch.setenv("LD_LIBRARY_PATH", "bundle")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "system")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "bundle")
    monkeypatch.delenv("DYLD_LIBRARY_PATH_ORIG", raising=False)
    env = runtime.python_subprocess_environment()
    assert "PYTHONHOME" not in env
    assert "PYTHONPATH" not in env
    assert env["LD_LIBRARY_PATH"] == "system"
    assert "LD_LIBRARY_PATH_ORIG" not in env
    assert "DYLD_LIBRARY_PATH" not in env
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_frozen_bundle_writes_rejected(frozen):
    with pytest.raises(runtime.FrozenApplicationWriteError, match="完整应用"):
        runtime.ensure_project_write_allowed(frozen.app.parent)
    with pytest.raises(runtime.FrozenApplicationWriteError):
        runtime.ensure_project_write_allowed(frozen.extracted)


def test_external_project_writes_allowed(frozen):
    runtime.ensure_project_write_allowed(frozen.project, frozen.project / "app" / "core.py")


def test_symlinked_bundle_destination_rejected(frozen):
    alias = frozen.project / "linked"
    alias.symlink_to(frozen.extracted, target_is_directory=True)
    with pytest.raises(runtime.FrozenApplicationWriteError):
        runtime.ensure_project_write_allowed(frozen.project, alias / "core.py")


def test_path_traversal_rejected(frozen):
    with pytest.raises(runtime.FrozenApplicationWriteError, match="超出"):
        runtime.ensure_project_write_allowed(frozen.project, frozen.project / ".." / "escape.py")


def test_frozen_pip_does_not_spawn_app(frozen, monkeypatch):
    from app.core.skills.core.env_operations import env_ops
    from app.core.config import ConfigManager
    from app.core.project_context import ProjectContext
    monkeypatch.setattr(ConfigManager, "load", lambda: {})
    monkeypatch.setattr(ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(frozen.project)))
    launch = Mock()
    monkeypatch.setattr(env_ops.subprocess, "run", launch)
    ok, message = env_ops._run_pip("list")
    assert not ok
    assert "外部 Python" in message
    launch.assert_not_called()


def test_frozen_pip_uses_selected_external_environment(frozen, monkeypatch):
    from app.core.skills.core.env_operations import env_ops
    from app.core.config import ConfigManager
    from app.core.project_context import ProjectContext
    python = make_executable(frozen.project / "selected" / "python")
    monkeypatch.setattr(ConfigManager, "load", lambda: {"sandbox_local_python": str(python)})
    monkeypatch.setattr(ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(frozen.project)))
    launch = Mock(return_value=SimpleNamespace(returncode=0, stdout="done", stderr=""))
    monkeypatch.setattr(env_ops.subprocess, "run", launch)
    assert env_ops._run_pip("install", "example") == (True, "done")
    assert launch.call_args.args[0] == [str(python), "-m", "pip", "install", "example"]
    assert launch.call_args.kwargs["cwd"] == str(frozen.project)


def test_frozen_worker_pytest_does_not_spawn_app(frozen, monkeypatch):
    from app.core.worker_modules import worker_test_runner
    from tests.helpers import RecordingSignal
    monkeypatch.setattr(worker_test_runner.ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(frozen.project)))
    launch = Mock()
    monkeypatch.setattr(worker_test_runner.subprocess, "Popen", launch)
    worker = SimpleNamespace(config={}, safe_emit_status=Mock(), test_result_signal=RecordingSignal())
    worker_test_runner.WorkerTestRunnerBridge(worker).run_tests_bg("Host")
    launch.assert_not_called()
    assert worker.test_result_signal.items[0]["failed"] == 1
    assert "外部 Python" in worker.test_result_signal.items[0]["full_log"]


def test_frozen_self_update_never_writes_bundle(frozen, monkeypatch):
    from app.core.self_update import SelfUpdateManager
    from app.core.config import ConfigManager
    monkeypatch.setattr(ConfigManager, "load", lambda: {})
    manager = SelfUpdateManager(project_root=str(frozen.extracted), staging_dir=str(frozen.project))
    manager.scan = Mock(side_effect=AssertionError("must reject before scan/copy"))
    with pytest.raises(runtime.FrozenApplicationWriteError, match="完整应用"):
        manager.apply()


@pytest.mark.parametrize("frozen_mode", [True, False])
def test_local_updates_apply_project_files_without_server_restart(frozen, monkeypatch, frozen_mode):
    from app.core.services.update_service import UpdateService
    from app.core.project_context import ProjectContext
    from app.core.config import ConfigManager
    monkeypatch.setattr(sys, "frozen", frozen_mode, raising=False)
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    monkeypatch.setattr(ConfigManager, "load", lambda: {})
    monkeypatch.setattr(ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(frozen.project)))
    stage = frozen.project / "staging.py"
    stage.write_text("print('updated')", encoding="utf-8")
    file_service = SimpleNamespace(validate_python_code=lambda *_: (True, ""), add_ignored_content=Mock())
    service = UpdateService({}, file_service)
    service.mgr.scan = lambda: [{"rel_path": "app/core/new.py", "staging_path": str(stage)}]
    ota = Mock()
    log = Mock()
    sleep = Mock(side_effect=AssertionError("local app must never wait for server supervisor"))
    monkeypatch.setattr("app.core.services.update_service.time.sleep", sleep)
    assert service.process_updates(["app/core/new.py"], log, ota) is False
    assert (frozen.project / "app" / "core" / "new.py").read_text() == "print('updated')"
    ota.assert_not_called()
    sleep.assert_not_called()


def test_update_service_rejects_bundle_before_staging(frozen, monkeypatch):
    from app.core.services.update_service import UpdateService
    from app.core.project_context import ProjectContext
    from app.core.config import ConfigManager
    monkeypatch.setattr(ConfigManager, "load", lambda: {})
    monkeypatch.setattr(ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(frozen.extracted)))
    service = UpdateService({}, Mock())
    service.mgr.scan = Mock(side_effect=AssertionError("must not scan/write bundle"))
    log = Mock()
    assert service.process_updates(["app/core/new.py"], log, Mock()) is False
    assert "完整应用" in log.call_args.args[0]
    assert not (frozen.extracted / "update_cache").exists()


def test_frozen_snapshot_does_not_spawn_app(frozen, monkeypatch):
    from app.core.worker_modules import worker_code_workspace
    from tests.helpers import RecordingSignal
    (frozen.project / "dump_code.py").write_text("# project snapshot tool", encoding="utf-8")
    monkeypatch.setattr(worker_code_workspace.ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(frozen.project)))
    launch = Mock()
    monkeypatch.setattr(worker_code_workspace.subprocess, "run", launch)
    worker = SimpleNamespace(config={}, safe_emit_status=Mock(), snapshot_ready_signal=RecordingSignal())
    worker_code_workspace.WorkerCodeWorkspaceBridge(worker).request_generate_snapshot()
    launch.assert_not_called()
    assert "外部 Python" in worker.safe_emit_status.call_args.args[0]
    assert not worker.snapshot_ready_signal.items


def test_frozen_agent_verification_does_not_spawn_app(frozen, monkeypatch):
    from app.core.agent_manager import AgentManager
    agent = AgentManager.__new__(AgentManager)
    agent.config = {}
    agent.file_service = SimpleNamespace(project_root=str(frozen.project))
    launch = Mock()
    monkeypatch.setattr("app.core.agent_manager.subprocess.run", launch)
    ok, message = agent._run_verification_test()
    assert not ok
    assert "外部 Python" in message
    launch.assert_not_called()


def isolated_ui_method(relative, method_name, **globals_):
    """Exercise UI routing without a platform plugin or constructing WebEngine."""
    source = Path(__file__).resolve().parents[1] / relative
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == method_name)
    namespace = {"sys": sys, **globals_}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[method_name]


def test_frozen_console_reports_missing_python_and_finishes(frozen):
    launch = Mock()
    run = isolated_ui_method(
        "app/ui/pages/console_page.py", "run",
        ProjectContext=SimpleNamespace(get=lambda: SimpleNamespace(get_project_root=lambda: str(frozen.project))),
        ConfigManager=SimpleNamespace(load=lambda: {}),
        resolve_project_python=runtime.resolve_project_python,
        subprocess=SimpleNamespace(Popen=launch),
    )
    runner = SimpleNamespace(log_signal=Mock(), finished_signal=Mock())
    run(runner)
    launch.assert_not_called()
    runner.finished_signal.emit.assert_called_once()
    assert "AI_BRIDGE_PYTHON" in runner.finished_signal.emit.call_args.args[0]


def test_frozen_restart_uses_orderly_close_without_forced_exit(frozen):
    exit_now = Mock(side_effect=AssertionError("must not force exit"))
    restart = isolated_ui_method(
        "app/ui/main_window.py", "handle_restart_request",
        RESTART_EXIT_CODE=42, os=SimpleNamespace(_exit=exit_now),
    )
    window = SimpleNamespace(save_layout=Mock(), _is_remote=lambda: False, chat_page=SimpleNamespace(log_status=Mock()), close=Mock(return_value=False))
    restart(window, False)
    assert window._local_exit_code == 42
    window.close.assert_called_once()
    exit_now.assert_not_called()


def test_frozen_update_explains_whole_application_replacement(frozen):
    dialog = SimpleNamespace(information=Mock())
    restart = isolated_ui_method("app/ui/main_window.py", "handle_restart_request", QMessageBox=dialog)
    window = SimpleNamespace(save_layout=Mock(), _is_remote=lambda: False, chat_page=SimpleNamespace(log_status=Mock()), close=Mock())
    restart(window, True)
    window.close.assert_not_called()
    dialog.information.assert_called_once()
    assert "替换完整应用" in dialog.information.call_args.args[2]


def test_local_code_review_routes_scan_and_apply_to_worker():
    worker = SimpleNamespace(do_server_scan=Mock(), do_server_apply=Mock())
    window = SimpleNamespace(_is_remote=lambda: False, worker=worker)
    scan = isolated_ui_method("app/ui/main_window.py", "handle_scan_request")
    apply = isolated_ui_method("app/ui/main_window.py", "handle_apply_request")
    scan(window)
    apply(window, ["demo.py"])
    worker.do_server_scan.assert_called_once()
    worker.do_server_apply.assert_called_once_with(["demo.py"])


def test_source_local_restart_uses_orderly_close(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    restart = isolated_ui_method(
        "app/ui/main_window.py", "handle_restart_request",
        RESTART_EXIT_CODE=42, os=SimpleNamespace(environ={"AI_BRIDGE_LOCAL_MODE": "1"}),
    )
    window = SimpleNamespace(save_layout=Mock(), _is_remote=lambda: False, chat_page=SimpleNamespace(log_status=Mock()), close=Mock())
    restart(window, False)
    assert window._local_exit_code == 42
    window.close.assert_called_once()


def test_frozen_python_menu_never_probes_app_alias(frozen, monkeypatch):
    from app.ui.pages.chat import status_bar
    alias = frozen.project / ".venv" / "bin" / "python"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(frozen.app)
    monkeypatch.setattr(status_bar.ProjectContext, "get", lambda: SimpleNamespace(get_project_root=lambda: str(frozen.project)))
    monkeypatch.setattr(status_bar.shutil, "which", lambda *_: str(frozen.app))
    probe = Mock(side_effect=AssertionError("must not probe frozen app"))
    monkeypatch.setattr(status_bar.subprocess, "check_output", probe)
    assert status_bar._SandboxMixin._detect_local_pythons(SimpleNamespace()) == []
    probe.assert_not_called()
