from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "tools/desktop/local_hooks"


def fake_qt(info, collect):
    module = types.ModuleType("PyInstaller.utils.hooks.qt")
    module.pyside6_library_info = info
    module.add_qt6_dependencies = collect
    return patch.dict(sys.modules, {"PyInstaller.utils.hooks.qt": module})


class InputHooks(unittest.TestCase):
    def test_gui_excludes_virtual_keyboard_only_before_native_probe(self):
        probes = []

        def validate(source):
            probes.append(source)
            return True, None

        info = types.SimpleNamespace(_validate_plugin_dependencies=validate)
        removed = [
            "/qt/plugins/platforminputcontexts/" + name
            for name in (
                "qtvirtualkeyboardplugin.dll",
                "qtvirtualkeyboardplugind.dll",
                "libqtvirtualkeyboardplugin.so",
                "libqtvirtualkeyboardplugin.dylib",
            )
        ]
        retained = [
            "/qt/" + path
            for path in (
                "plugins/imageformats/qpdf.dll",
                "plugins/imageformats/libqpdf.dylib",
                "plugins/imageformats/libqpdf.so",
                "plugins/imageformats/qjpeg.dll",
                "plugins/platforms/libqcocoa.dylib",
                "plugins/platforms/qwindows.dll",
                "plugins/platforminputcontexts/libibusplatforminputcontextplugin.so",
                "plugins/platforminputcontexts/libcomposeplatforminputcontextplugin.so",
                "lib/QtVirtualKeyboard",
                "lib/QtPdf",
                "lib/QtQuick",
                "lib/QtQml",
                "lib/QtWebEngineCore",
                "plugins/other/libqtvirtualkeyboardplugin.dylib",
            )
        ]
        hidden = ["PySide6.QtCore", "PySide6.QtPdf"]
        datas = [("qtwebengine_resources.pak", "resources")]

        def collect(_):
            return (
                hidden,
                [
                    (p, "plugins")
                    for p in removed + retained
                    if info._validate_plugin_dependencies(p)[0]
                ],
                datas,
            )

        with fake_qt(info, collect):
            result = runpy.run_path(str(HOOKS / "hook-PySide6.QtGui.py"))
        self.assertEqual([x[0] for x in result["binaries"]], retained)
        self.assertEqual(probes, retained)
        self.assertIs(result["hiddenimports"], hidden)
        self.assertIs(result["datas"], datas)
        self.assertIs(info._validate_plugin_dependencies, validate)

    def test_qml_exact_six_trees_and_profiler_only_before_dependency_processing(self):
        removed = [
            "QtGraphs",
            "QtCharts",
            "QtDataVisualization",
            "QtQuick3D",
            "QtQuick3D.Helpers",
            "QtQuick.Timeline",
            "QtQuick.Timeline.BlendTrees",
            "QtQuick.VirtualKeyboard",
            "QtQuick.VirtualKeyboard.Plugins.Pinyin",
        ]
        retained = [
            "QtQml",
            "QtQuick",
            "QtQuick.Controls",
            "QtQuick.Pdf",
            "QtWebEngine",
            "QtQuick.Window",
            "QtQuick3DExtra",
            "QtQuick.TimelineExtra",
            "QtGraphsExtra",
        ]
        profiler = [
            "/qt/plugins/qmltooling/" + name
            for name in (
                "qmldbg_quick3dprofiler.dll",
                "qmldbg_quick3dprofilerd.dll",
                "libqmldbg_quick3dprofiler.so",
                "libqmldbg_quick3dprofiler.dylib",
            )
        ]
        keep_plugins = [
            "/qt/plugins/qmltooling/libqmldbg_profiler.dylib",
            "/qt/plugins/qmltooling/libqmldbg_debugger.dylib",
            "/qt/plugins/other/libqmldbg_quick3dprofiler.dylib",
        ]
        probes = []
        processed = []

        def validate(source):
            probes.append(source)
            return True, None

        def process(path):
            processed.append(path.read_text(encoding="utf-8").split()[1])
            return [(str(path.with_name("plugin.dylib")), "qml")], [(str(path), "qml")]

        info = types.SimpleNamespace(
            _validate_plugin_dependencies=validate, _process_qml_plugin=process
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for i, module in enumerate(removed + retained):
                path = Path(directory) / str(i) / "qmldir"
                path.parent.mkdir()
                path.write_text("module " + module + "\n", encoding="utf-8")
                paths.append(path)

            def collect_qml():
                binaries = []
                datas = []
                for path in paths:
                    b, d = info._process_qml_plugin(path)
                    binaries += b
                    datas += d
                return binaries, datas

            info.collect_qtqml_files = collect_qml

            def collect(_):
                return (
                    ["PySide6.QtCore"],
                    [
                        (p, "qmltooling")
                        for p in profiler + keep_plugins
                        if info._validate_plugin_dependencies(p)[0]
                    ],
                    [("qtdeclarative.qm", "translations")],
                )

            with fake_qt(info, collect):
                result = runpy.run_path(str(HOOKS / "hook-PySide6.QtQml.py"))
        self.assertEqual(processed, retained)
        self.assertEqual(probes, keep_plugins)
        self.assertEqual(len(result["binaries"]), len(keep_plugins) + len(retained))
        self.assertEqual(len(result["datas"]), 1 + len(retained))
        self.assertEqual(result["hiddenimports"], ["PySide6.QtCore"])
        self.assertIs(info._validate_plugin_dependencies, validate)
        self.assertIs(info._process_qml_plugin, process)

    def test_collectors_restore_after_exception(self):
        for module in ("QtGui", "QtQml"):

            def validate(_):
                return True, None

            def process(_):
                return [], []

            info = types.SimpleNamespace(
                _validate_plugin_dependencies=validate, _process_qml_plugin=process
            )

            def fail(_):
                raise RuntimeError("fail closed")

            with (
                fake_qt(info, fail),
                self.assertRaisesRegex(RuntimeError, "fail closed"),
            ):
                runpy.run_path(str(HOOKS / f"hook-PySide6.{module}.py"))
            self.assertIs(info._validate_plugin_dependencies, validate)
            self.assertIs(info._process_qml_plugin, process)

    def test_recipe_uses_independent_hooks_without_excluding_core(self):
        build = runpy.run_path(str(REPO / "tools/desktop/local_build.py"))
        command = build["command"](Path("not-built"))
        self.assertEqual(command.count("--additional-hooks-dir"), 1)
        index = command.index("--additional-hooks-dir")
        self.assertEqual(command[index + 1], str(HOOKS))
        self.assertNotIn(str(REPO / "tools/desktop/hooks"), command)
        excluded = {
            command[i + 1]
            for i, part in enumerate(command[:-1])
            if part == "--exclude-module"
        }
        self.assertEqual(excluded, {"PyQt5", "PyQt6", "PySide2"})
        self.assertNotIn("PySide6", build["COLLECT_ALL"])
        for module in (
            "PySide6.QtWebEngineCore",
            "PySide6.QtWebEngineWidgets",
            "chromadb",
            "fastembed",
            "onnxruntime",
            "docker",
            "selenium",
        ):
            self.assertIn(module, build["CORE_MODULES"])
            self.assertNotIn(module, excluded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
