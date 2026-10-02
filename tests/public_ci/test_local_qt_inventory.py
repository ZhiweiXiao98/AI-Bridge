"""Cross-platform inventory naming contracts; not a Windows native link proof."""

import ast
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "local_qt_policy", ROOT / "tools/desktop/local_qt_policy.py"
)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)
CORE = (
    "app.core.worker",
    "chromadb",
    "fastembed",
    "onnxruntime",
    "docker",
    "selenium",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
)


def fixture(platform="darwin"):
    roots = (
        ["AI-Bridge-Local", "AI-Bridge-Local.app"]
        if platform == "darwin"
        else ["AI-Bridge-Local"]
    )
    records = []
    for root in roots:
        for library in sorted(policy.REQUIRED_QT_LIBRARIES):
            name = library if platform == "darwin" else "Qt6" + library[2:] + ".dll"
            records.append(
                {
                    "path": root + "/_internal/" + name,
                    "size": 50,
                    "sha256": "a" * 64,
                    "mach_o_dependencies": [{"install_name": "@rpath/QtCore"}],
                }
                if platform == "darwin"
                else {
                    "path": root + "/_internal/" + name,
                    "size": 50,
                    "sha256": "a" * 64,
                }
            )
        for path in (
            "PySide6/Qt/plugins/imageformats/libqpdf.dylib",
            "PySide6/Qt/qml/QtQuick/Pdf/qmldir",
            "PySide6/Qt/qml/QtQuick/Pdf/libpdfquickplugin.dylib",
            "QtWebEngineProcess",
            "resources/qtwebengine_resources.pak",
        ):
            if platform == "win32":
                path = path.replace("libqpdf.dylib", "qpdf.dll").replace(
                    "libpdfquickplugin.dylib", "pdfquickplugin.dll"
                )
                if path == "QtWebEngineProcess":
                    path += ".exe"
            records.append(
                {"path": root + "/_internal/" + path, "size": 50, "sha256": "b" * 64}
            )
    return {
        "name": "AI-Bridge-Local",
        "platform": platform,
        "core_modules_missing": [],
        "files": records,
        "bundles": [{"path": root, "pyz_modules": list(CORE)} for root in roots],
    }


class InventoryPolicyTests(unittest.TestCase):
    def test_complete_inventory_passes_without_claiming_license_or_runtime_acceptance(
        self,
    ):
        value = fixture()
        policy.require_qt_inventory(value, CORE)
        result = value["qt_input_policy"]
        self.assertTrue(result["passed"])
        self.assertFalse(result["license_clearance"])
        self.assertTrue(result["runtime_acceptance_required"])

    def test_each_optional_family_reentry_fails(self):
        for family in policy.OPTIONAL_QT_FAMILIES:
            for tail in (
                f"{family}.framework/Versions/A/{family}",
                f"Qt6{family[2:]}.dll",
                f"libQt6{family[2:]}.so.6",
                f"PySide6/{family}.abi3.so",
            ):
                with self.subTest(tail=tail):
                    value = fixture()
                    value["files"].append(
                        {
                            "path": "AI-Bridge-Local.app/Contents/Frameworks/" + tail,
                            "sha256": "c" * 64,
                        }
                    )
                    with self.assertRaisesRegex(RuntimeError, "reappeared"):
                        policy.require_qt_inventory(value, CORE)
                    self.assertFalse(value["qt_input_policy"]["passed"])

    def test_all_optional_qml_trees_and_two_plugin_inputs_fail(self):
        for root in policy.OPTIONAL_QML_ROOTS:
            self.assertTrue(
                policy.forbidden_input_path(
                    "app/PySide6/qml/" + root + "/nested/qmldir"
                )
            )
        for path in (
            "qmltooling/libqmldbg_quick3dprofiler.dylib",
            "qmltooling/qmldbg_quick3dprofilerd.dll",
            "platforminputcontexts/qtvirtualkeyboardplugin.dll",
        ):
            self.assertTrue(policy.forbidden_input_path("app/PySide6/plugins/" + path))
        self.assertTrue(policy.forbidden_input_path("app/pyside6/QT6QUICK3DUTILS.DLL"))

    def test_pdf_and_unrelated_quick_qml_inputs_are_not_forbidden(self):
        for path in (
            "QtPdf.framework/Versions/A/QtPdf",
            "PySide6/QtPdf.abi3.so",
            "Qt6PdfQuick.dll",
            "PySide6/Qt/qml/QtQuick/Pdf/qmldir",
            "imageformats/libqpdf.dylib",
            "QtQuick.framework/Versions/A/QtQuick",
            "libQt6Qml.so.6",
            "QtWebEngineCore",
            "qml/QtQuick/TimelineExtra/qmldir",
            "qml/QtGraphsExtra/qmldir",
            "qmltooling/libqmldbg_profiler.dylib",
        ):
            self.assertFalse(policy.forbidden_input_path("app/" + path), path)

    def test_missing_core_or_each_required_qt_library_fails(self):
        for library in sorted(policy.REQUIRED_QT_LIBRARIES):
            value = fixture()
            value["files"] = [
                r for r in value["files"] if not r["path"].endswith("/" + library)
            ]
            with (
                self.subTest(library=library),
                self.assertRaisesRegex(RuntimeError, "Required Qt library missing"),
            ):
                policy.require_qt_inventory(value, CORE)
        value = fixture()
        value["bundles"][1]["pyz_modules"].remove("chromadb")
        with self.assertRaisesRegex(RuntimeError, "Required core missing"):
            policy.require_qt_inventory(value, CORE)

    def test_missing_pdf_decoder_pdf_qml_helper_or_resources_fails(self):
        for tail in (
            "libqpdf.dylib",
            "Pdf/qmldir",
            "libpdfquickplugin.dylib",
            "QtWebEngineProcess",
            "qtwebengine_resources.pak",
        ):
            value = fixture()
            value["files"] = [r for r in value["files"] if not r["path"].endswith(tail)]
            with (
                self.subTest(tail=tail),
                self.assertRaisesRegex(RuntimeError, "Required .* missing"),
            ):
                policy.require_qt_inventory(value, CORE)

    def test_retained_native_reference_fails_even_if_target_file_is_absent(self):
        value = fixture()
        value["files"][0]["mach_o_dependencies"].append(
            {"install_name": "@rpath/QtQuick3DUtils"}
        )
        with self.assertRaisesRegex(RuntimeError, "Native dependency still targets"):
            policy.require_qt_inventory(value, CORE)

    def test_missing_mac_native_evidence_fails(self):
        value = fixture()
        for row in value["files"]:
            row.pop("mach_o_dependencies", None)
        with self.assertRaisesRegex(RuntimeError, "Missing recorded Mach-O evidence"):
            policy.require_qt_inventory(value, CORE)

    def test_windows_name_checks_do_not_claim_mac_or_windows_native_edge_audit(self):
        value = fixture("win32")
        policy.require_qt_inventory(value, CORE)
        self.assertEqual(
            value["qt_input_policy"]["native_dependency_evidence"],
            "not a target-platform native dependency audit",
        )

    def test_malformed_inventory_and_missing_app_scope_fail_closed(self):
        examples = [{}, fixture(), fixture(), fixture(), fixture()]
        examples[1]["bundles"] = examples[1]["bundles"][:1]
        examples[2]["core_modules_missing"] = ["chromadb"]
        examples[3]["files"][0]["sha256"] = ""
        examples[4]["bundles"][0]["pyz_modules"].append("PySide6.QtGraphs")
        for value in examples:
            with (
                self.subTest(value=value.get("core_modules_missing")),
                self.assertRaises(RuntimeError),
            ):
                policy.require_qt_inventory(value, CORE)

    def test_inspection_does_not_mutate_files_or_inventory(self):
        value = fixture()
        original = copy.deepcopy(value)
        policy.inspect_qt_inventory(value, CORE)
        self.assertEqual(value, original)

    def test_build_gate_saves_rejected_inventory_without_bypassing_failure(self):
        tree = ast.parse((ROOT / "tools/desktop/local_build.py").read_text(encoding="utf-8"))
        nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
            and any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "require_qt_inventory"
                for statement in node.body
                for call in ast.walk(statement)
            )
        ]
        self.assertEqual(len(nodes), 1)
        self.assertFalse(nodes[0].handlers)
        self.assertTrue(
            any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "write_json"
                for statement in nodes[0].finalbody
                for call in ast.walk(statement)
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
