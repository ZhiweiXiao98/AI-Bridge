"""Dependency-free safety contracts; frozen UI smoke runs separately in CI."""
import ast
import importlib.util
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("desktop_build", ROOT / "tools/desktop/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def isolated_method(relative, name):
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    method.decorator_list = []
    namespace = {"sys": sys}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(relative), "exec"), namespace)
    return namespace[name]


class DesktopPackagingTests(unittest.TestCase):
    def test_native_inventory_blocks_unused_qt_components(self):
        paths = [
            "PySide6/Qt/lib/libQt6VirtualKeyboard.so.6",
            "PySide6/Qt/bin/Qt6Pdf.dll",
            "PySide6/Qt/lib/QtQml.framework/Versions/A/QtQml",
            "PySide6/Qt/lib/QtQuick.framework/QtQuick",
            "PySide6/Qt/plugins/imageformats/qpdf.dll",
        ]
        self.assertEqual(build.unexpected_native_files([{"path": p} for p in paths]), paths)
        self.assertEqual(build.unexpected_native_files([
            {"path": "PySide6/QtCore.abi3.so"},
            {"path": "PySide6/Qt/lib/QtWidgets.framework/QtWidgets"},
            {"path": "PySide6/Qt/plugins/platforms/qwindows.dll"},
        ]), [])

    def test_qt_hook_removes_optional_plugin_inputs_only(self):
        plugins = [
            ("/qt/plugins/qpdf.dll", "imageformats"),
            ("/qt/plugins/libqpdf.dylib", "imageformats"),
            ("/qt/plugins/qtvirtualkeyboardplugin.dll", "platforminputcontexts"),
            ("/qt/plugins/libqtvirtualkeyboardplugin.so", "platforminputcontexts"),
            ("/qt/plugins/qjpeg.dll", "imageformats"),
            ("/qt/plugins/qcocoa.dylib", "platforms"),
        ]
        fake = types.ModuleType("PyInstaller.utils.hooks.qt")
        fake.add_qt6_dependencies = lambda _: ([], plugins, [])
        with patch.dict(sys.modules, {"PyInstaller.utils.hooks.qt": fake}):
            data = runpy.run_path(str(ROOT / "tools/desktop/hooks/hook-PySide6.QtGui.py"))
        self.assertEqual(data["binaries"], plugins[-2:])
        self.assertIn("--additional-hooks-dir", build.command(ROOT / "build/test"))

    def test_entry_point_is_remote_client(self):
        command = build.command(ROOT / "build/test")
        self.assertEqual(command[-1], str(ROOT / "boot_remote.py"))
        self.assertNotIn(str(ROOT / "start_client.py"), command)
        self.assertIn("--onedir", command)
        self.assertNotIn("--onefile", command)

    def test_payload_is_license_only(self):
        self.assertEqual(build.REPOSITORY_DATA, ("LICENSE",))
        command = build.command(ROOT / "build/test")
        self.assertEqual(command.count("--add-data"), 1)
        self.assertNotIn("--collect-all", command)

    def test_only_current_qt_binding_installed(self):
        text = (ROOT / "requirements-desktop-build.txt").read_text(encoding="utf-8")
        self.assertIn("PySide6==", text)
        self.assertNotIn("PyQt6", text)
        self.assertIn("PySide6", (ROOT / "requirements_client.txt").read_text(encoding="utf-8"))

    def test_standard_runners_and_no_binary_upload(self):
        workflow = (ROOT / ".github/workflows/desktop-build.yml").read_text(encoding="utf-8")
        self.assertIn("os: [windows-latest, macos-latest, macos-15-intel]", workflow)
        self.assertIn("name: 桌面远程客户端构建", workflow)
        self.assertIn("name: 未签名远程客户端 / ${{ matrix.os }}", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("path: build/desktop/review/desktop-inventory.json", workflow)
        self.assertNotIn("path: build/desktop/dist", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("pull_request_target", workflow)

    def test_runtime_hook_uses_writable_state(self):
        constants = types.ModuleType("app.core.app_constants")
        core = types.ModuleType("app.core")
        core.app_constants = constants
        app = types.ModuleType("app")
        app.core = core
        modules = {"app": app, "app.core": core, "app.core.app_constants": constants}
        cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                home = (Path(temporary) / "client-state").resolve()
                with patch.dict(sys.modules, modules), patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"AI_BRIDGE_CLIENT_HOME": str(home)}):
                    runpy.run_path(str(ROOT / "tools/desktop/runtime_hook.py"))
                    self.assertEqual(Path.cwd(), home)
                    self.assertEqual(constants.APP_ROOT, str(home))
                    self.assertEqual(constants.PROJECT_ROOT, str(home))
                os.chdir(cwd)
        finally:
            os.chdir(cwd)

    def test_source_runtime_hook_does_not_change_cwd(self):
        cwd = Path.cwd()
        with patch.object(sys, "frozen", False, create=True):
            runpy.run_path(str(ROOT / "tools/desktop/runtime_hook.py"))
        self.assertEqual(Path.cwd(), cwd)

    def test_frozen_ota_methods_do_not_download_or_write(self):
        for name in ("request_latest_code", "_process_ota_pull", "_process_ota_payload"):
            with self.subTest(name=name), patch.object(sys, "frozen", True, create=True):
                method = isolated_method("app/core/remote_worker.py", name)
                worker = types.SimpleNamespace(status_signal=Mock())
                method(worker, {"config.json": "must not write"}) if name.endswith("payload") else method(worker)
                worker.status_signal.emit.assert_called_once()

    def test_frozen_local_tests_finish_without_launching_python(self):
        method = isolated_method("app/ui/pages/console_page.py", "run")
        worker = types.SimpleNamespace(log_signal=Mock(), finished_signal=Mock())
        with patch.object(sys, "frozen", True, create=True):
            method(worker)
        worker.finished_signal.emit.assert_called_once()

    def test_context_scanner_does_not_import_server_rag(self):
        text = (ROOT / "app/core/services/context_scanner.py").read_text(encoding="utf-8")
        self.assertNotIn("FileService", text)
        self.assertIn("UpdateService.get_file_category(rel_path)", text)
        classify = isolated_method("app/core/services/update_service.py", "get_file_category")
        self.assertEqual(classify("app/ui/main_window.py"), "CLIENT_ONLY")
        self.assertEqual(classify("app/core/worker.py"), "CRITICAL")
        self.assertEqual(classify("docs/test.md"), "SAFE_STATIC")

    def test_missing_decorative_icons_keep_text_labels(self):
        text = (ROOT / "app/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("btn.setText(text)", text)
        self.assertIn("elif os.path.exists(icon_path):", text)


if __name__ == "__main__":
    unittest.main()
