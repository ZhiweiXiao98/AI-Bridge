"""无需 Qt 的来源/隐私/许可打包约束测试。"""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("compliance_test_module", ROOT / "tools/desktop/compliance.py")
compliance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compliance)


class ComplianceTests(unittest.TestCase):
    def test_new_text_io_always_declares_encoding(self):
        for relative in ("tools/desktop/compliance.py", "tools/desktop/recombine.py",
                         "tools/desktop/smoke.py", "licenses/vendor/verify_vendored_licenses.py",
                         "tests/public_ci/test_desktop_compliance.py"):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"read_text", "write_text"}):
                    self.assertIn("encoding", [argument.arg for argument in node.keywords],
                                  f"{relative}:{node.lineno}")

    def test_static_license_hashes(self):
        root = ROOT / "licenses/desktop"
        policy = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        for entry in policy["notice_files"]:
            self.assertTrue(compliance.safe_relative(entry["path"]))
            self.assertEqual(compliance.digest(root / entry["path"]), entry["sha256"])
        self.assertEqual(len(policy["components"]), 2)
        for entry in policy["components"]:
            self.assertRegex(entry["published_sha256"], "^[0-9a-f]{64}$")

    def test_only_notice_filenames_not_code(self):
        for name in ("LICENSE", "LICENSE.txt", "COPYING.txt", "NOTICE", "COPYRIGHT", "AUTHORS.txt"):
            self.assertTrue(compliance.NOTICE_NAME.match(name))
        for name in ("licenses.py", "license_checker.py", "_spdx.py", "__init__.py", "METADATA"):
            self.assertFalse(compliance.NOTICE_NAME.match(name))

    def test_path_traversal_rejected(self):
        for value in ("../private.txt", "/etc/password", "C:/private", "a/../../b", "a\\..\\secret"):
            self.assertFalse(compliance.safe_relative(value))
        self.assertTrue(compliance.safe_relative("package.dist-info/licenses/LICENSE"))

    def test_private_index_and_tokens_not_exported(self):
        values = ("https://user:secret@pypi.org/a.whl", "https://files.pythonhosted.org/a?token=secret",
                  "https://internal.example/a.whl", "file:///private/a.whl", "http://pypi.org/a")
        for value in values:
            self.assertIsNone(compliance.public_url(value))
        self.assertEqual(compliance.public_url("https://files.pythonhosted.org/packages/a.whl"),
                         "https://files.pythonhosted.org/packages/a.whl")

    def test_toc_is_data_not_executed(self):
        entries = list(compliance.toc_entries(([('requests', '/venv/requests.py', 'PYMODULE')],
                                               [('lib.dll', '/system/lib.dll', 'BINARY')])))
        self.assertEqual(len(entries), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toc"
            path.write_text("__import__('os').system('false')", encoding="utf-8")
            with self.assertRaises(ValueError):
                compliance.read_toc(path)

    def test_final_bundle_notices_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated, bundle = root / "generated", root / "bundle"
            generated.mkdir()
            (generated / "LICENSE.txt").write_text("verified text", encoding="utf-8")
            with self.assertRaises(ValueError):
                compliance.verify_notices(bundle, generated)
            final = bundle / "_internal/THIRD_PARTY_NOTICES"
            final.mkdir(parents=True)
            (final / "LICENSE.txt").write_text("verified text", encoding="utf-8")
            compliance.verify_notices(bundle, generated)
            (final / "LICENSE.txt").write_text("altered", encoding="utf-8")
            with self.assertRaises(ValueError):
                compliance.verify_notices(bundle, generated)

    def test_generated_texts_do_not_copy_environment_metadata(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(compliance, "distributions", return_value={}):
            output = Path(directory)
            self.assertEqual(compliance.prepare_notices(ROOT, output), {})
            filenames = [p.name for p in (output / "generated-notices").rglob("*")]
            self.assertNotIn("METADATA.txt", filenames)
            self.assertIn("LGPL-3.0-only.txt", filenames)
            self.assertIn("GPL-3.0-only.txt", filenames)

    def test_omitted_source_paths_do_not_leak(self):
        result = compliance.provenance("/private/example-home/secret-lib.so", ROOT, {})
        self.assertEqual(result, {"unresolved_origin": "secret-lib.so"})

    def test_runtime_paths_rejected_not_license_text(self):
        for value in ("app/_internal/.env", "app/logs/debug.log", "app/config.json", "app/user.db"):
            self.assertIsNotNone(compliance.PRIVATE_PATH.search(value))
        self.assertIsNone(compliance.PRIVATE_PATH.search("app/_internal/THIRD_PARTY_NOTICES/NOTICE"))

    def test_ca_bundle_exception_requires_exact_record_hash(self):
        record = {"sha256": "a" * 64, "owners": [{"distribution": "certifi",
                  "path": "certifi/cacert.pem", "record_sha256": "a" * 64}]}
        self.assertTrue(compliance.verified_ca_bundle(record))
        record["sha256"] = "b" * 64
        self.assertFalse(compliance.verified_ca_bundle(record))
        self.assertFalse(compliance.verified_ca_bundle({"path": "private/cacert.pem"}))

    def test_workflow_is_isolated_and_inventory_only(self):
        text = (ROOT / ".github/workflows/desktop-build.yml").read_text(encoding="utf-8")
        self.assertIn("python -m venv .desktop-venv", text)
        self.assertIn("python-version: '3.12.10'", text)
        self.assertIn("--report build/desktop/install-report.json", text)
        self.assertIn("python tools/desktop/recombine.py", text)
        self.assertNotIn("path: build/desktop/dist", text)
        self.assertNotIn("upload-release", text)
        self.assertNotIn("contents: write", text)


if __name__ == "__main__":
    unittest.main()
