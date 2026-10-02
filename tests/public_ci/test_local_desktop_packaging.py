"""完整本地冻结包的离线安全约束，不需要 Qt、网络或模型服务。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/desktop"))
import local_build
import local_compliance
import local_smoke


class CompleteBuildTests(unittest.TestCase):
    def test_entrypoint_is_local_and_no_core_excluded(self):
        command = local_build.command(Path("/tmp/local-build"))
        self.assertEqual(command[-1], str(ROOT / "boot_local.py"))
        for module in local_build.CORE_MODULES:
            self.assertIn(module, command)
            self.assertNotIn(["--exclude-module", module], [command[i:i + 2] for i in range(len(command))])
        self.assertNotIn("--additional-hooks-dir", command)
        self.assertIn("--collect-submodules", command)
        self.assertIn("app", command)

    def test_resources_include_skills_plugins_and_vendor_notices(self):
        resources = local_build.public_resources()
        for path in ("app/core/skills/core/file_operations/skill.py",
                     "app/core/skills/core/file_operations/SKILL.md",
                     "plugins/panels/skills_panel/plugin.py", "plugins/panels/skills_panel/plugin.json",
                     "config/panel_layout_default.json", "assets/icons/chat.png",
                     "lib/vis-9.1.2/vis-network.min.js", "Prompt/Build_SystemPrompt.md"):
            self.assertIn(path, resources)
        self.assertTrue(any(name.startswith("licenses/vendor/third_party_licenses/") for name in resources))

    def test_resources_never_include_user_configuration(self):
        resources = local_build.public_resources()
        for name in ("config.json", "config/api_mode.json", "config/panel_layout.json", "config/plugins.json",
                     "session_states.json", ".env", ".secret.key", "user_data.db", "chrome_user_data/Default/Cookies"):
            self.assertNotIn(name, resources)
        self.assertFalse(any("skills/external/" in path for path in resources))

    def test_untracked_resource_is_not_picked_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in local_build.RESOURCE_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("public")
            (root / "Prompt").mkdir()
            (root / "Prompt/private.md").write_text("private")
            tracked = "\0".join(local_build.RESOURCE_FILES) + "\0"
            with patch.object(local_build.subprocess, "check_output", return_value=tracked.encode()):
                self.assertNotIn("Prompt/private.md", local_build.public_resources(root))

    def test_resource_symlink_rejected(self):
        if os.name == "nt":
            self.skipTest("Windows 无符号链接权限时由实际 staging 检查覆盖")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target").write_text("private")
            (root / "LICENSE").symlink_to(root / "target")
            with patch.object(local_build, "RESOURCE_FILES", ("LICENSE",)), patch.object(
                    local_build.subprocess, "check_output", return_value=b"LICENSE\0"):
                with self.assertRaises(ValueError):
                    local_build.public_resources(root)

    def test_current_pi_lock_with_verified_supplement(self):
        lock = json.loads((ROOT / "runtime/pi/package-lock.json").read_text(encoding="utf-8"))
        local_build.validate_npm_lock(lock)
        missing = [name for name, item in lock["packages"].items() if name and not item.get("integrity")]
        self.assertEqual(len(missing), 7)

    def test_pi_without_integrity_and_supplement_fails(self):
        lock = json.loads((ROOT / "runtime/pi/package-lock.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            local_build.validate_npm_lock(lock, {})

    def test_pi_wrong_version_fails(self):
        lock = json.loads((ROOT / "runtime/pi/package-lock.json").read_text(encoding="utf-8"))
        lock["packages"]["node_modules/@earendil-works/pi-coding-agent"]["version"] = "0.99.2"
        with self.assertRaises(ValueError):
            local_build.validate_npm_lock(lock)

    def test_pi_nonofficial_registry_fails(self):
        lock = json.loads((ROOT / "runtime/pi/package-lock.json").read_text(encoding="utf-8"))
        lock["packages"]["node_modules/@earendil-works/pi-coding-agent"]["resolved"] = "https://registry.npmjs.org.evil.invalid/pkg"
        with self.assertRaises(ValueError):
            local_build.validate_npm_lock(lock)

    def test_node_target_is_explicit(self):
        with patch.object(local_build.sys, "platform", "darwin"), patch.object(local_build.platform, "machine", return_value="arm64"):
            self.assertEqual(local_build.node_target(), ("darwin-arm64", "tar.gz"))
        with patch.object(local_build.sys, "platform", "win32"), patch.object(local_build.platform, "machine", return_value="AMD64"):
            self.assertEqual(local_build.node_target(), ("win-x64", "zip"))
        with patch.object(local_build.sys, "platform", "darwin"), patch.object(local_build.platform, "machine", return_value="x86_64"):
            with self.assertRaises(RuntimeError):
                local_build.node_target()

    def test_node_sources_are_fixed_and_sufficiently_new(self):
        records = json.loads((ROOT / "licenses/local/node-sources.json").read_text(encoding="utf-8"))
        self.assertEqual(records["version"], local_build.NODE_VERSION)
        self.assertGreaterEqual(tuple(map(int, records["version"].split("."))), (22, 19, 0))
        for name in (f"node-v{local_build.NODE_VERSION}-darwin-arm64.tar.gz", f"node-v{local_build.NODE_VERSION}-win-x64.zip"):
            self.assertRegex(records["archives"][name]["sha256"], r"^[a-f0-9]{64}$")


class ComplianceTests(unittest.TestCase):
    def test_native_toc_index_preserves_exact_suffix_matches(self):
        entries = [("a/pkg/LICENSE", "first"), ("b/pkg/LICENSE", "second"),
                   ("pkg/LICENSE", "short"), ("node/bin/node", "node"),
                   ("a/pkg/LICENSE", "duplicate-origin")]
        indexed = local_compliance.native_toc_index(entries)
        for relative in ("bundle/_internal/a/pkg/LICENSE", "bundle/_internal/b/pkg/LICENSE",
                         "bundle/_internal/node/bin/node", "bundle/missing.dll"):
            expected = [(name, source) for name, source in entries if relative.endswith("/" + name)]
            actual = [(name, source) for name, source in indexed.get(Path(relative).name, ())
                      if relative.endswith("/" + name)]
            self.assertEqual(actual, expected)

    def test_install_report_does_not_use_remote_distribution_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "install.json"
            path.write_text(json.dumps({"install": [{"metadata": {"name": "fastembed", "version": "0.8.0"},
                "download_info": {"url": "https://files.pythonhosted.org/fastembed.whl", "archive_info": {"hashes": {"sha256": "a" * 64}}}}]}))
            self.assertIn("fastembed", local_compliance.install_records(path))

    def test_private_or_unhashed_install_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "install.json"
            for url in ("https://token@files.pythonhosted.org/file.whl", "https://private.example/file.whl",
                        "https://files.pythonhosted.org/file.whl?token=private", "file:///home/user/private.whl"):
                path.write_text(json.dumps({"install": [{"metadata": {"name": "a", "version": "1"},
                    "download_info": {"url": url, "archive_info": {"hashes": {"sha256": "a" * 64}}}}]}))
                with self.assertRaises(ValueError):
                    local_compliance.install_records(path)

    def test_user_state_is_blocked_but_locked_package_resource_is_not(self):
        private = {"path": "AI-Bridge-Local/_internal/config.json", "source_sha256": "x"}
        package = {"path": "AI-Bridge-Local/_internal/runtime/pi/node_modules/pkg/config.json", "npm_owner": {"name": "pkg"}}
        self.assertEqual(local_compliance.privacy_findings([private, package]), [private["path"]])

    def test_distribution_exemption_requires_record_match(self):
        record = {"path": "AI-Bridge-Local/_internal/pkg/config.json", "source_sha256": "abc",
                  "owners": [{"record_sha256": "def"}]}
        self.assertEqual(local_compliance.privacy_findings([record]), [record["path"]])
        record["owners"][0]["record_sha256"] = "abc"
        self.assertEqual(local_compliance.privacy_findings([record]), [])

    def test_binary_is_not_copied_as_license(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "LICENSE"
            source.write_bytes(b"binary\x00data")
            self.assertFalse(local_compliance.copy_text(source, Path(directory) / "notices/LICENSE"))

    def test_workflow_never_uploads_binary_or_log(self):
        workflow = (ROOT / ".github/workflows/local-desktop-build.yml").read_text(encoding="utf-8")
        upload = workflow.split("uses: actions/upload-artifact@", 1)[1]
        self.assertEqual(upload.count(".json"), 3)
        paths = upload.split("path: |", 1)[1].split("if-no-files-found:", 1)[0]
        self.assertEqual([line.strip() for line in paths.splitlines() if line.strip()], [
            "build/local-desktop/review/local-build-inputs.json",
            "build/local-desktop/review/local-desktop-inventory.json",
            "build/local-desktop/review/local-smoke.json",
        ])
        for forbidden in ("dist/", "node_modules", "install-report", "*.zip", "*.exe", "*.log", "runtime.json"):
            self.assertNotIn(forbidden, upload)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("persist-credentials: false", workflow)


class SmokeTests(unittest.TestCase):
    def report(self):
        return {"mode": "local-worker", "remote_server_required": False, "python": "3.12.10", "qt": "6.11.1",
                "node": "v" + local_build.NODE_VERSION, "pi_version": local_build.PI_VERSION,
                "checks": sorted(local_smoke.REQUIRED_CHECKS), "core_imports": sorted(local_smoke.REQUIRED_IMPORTS),
                "provider": "本机fixture", "skills": 7, "plugins": 2, "optional_external_services": {},
                "resource_root": "/private/build/path", "unknown_secret": "do not upload"}

    def test_full_smoke_evidence_required_and_private_fields_removed(self):
        report = self.report()
        safe = local_smoke.validate_report(report, report)
        self.assertNotIn("resource_root", safe)
        self.assertNotIn("unknown_secret", safe)

    def test_import_only_or_remote_smoke_rejected(self):
        for field, replacement in (("checks", []), ("mode", "remote"), ("node", "v24.0.0"),
                                   ("core_imports", []), ("skills", 0), ("remote_server_required", True)):
            report = self.report()
            report[field] = replacement
            with self.assertRaises(RuntimeError):
                local_smoke.validate_report(report, self.report())

    def test_environment_drops_model_secrets_and_host_tools(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "NODE_OPTIONS": "--require=evil", "PYTHONPATH": "/evil"}):
            state = Path(directory)
            env = local_smoke.smoke_environment(state)
            for key in ("OPENAI_API_KEY", "NODE_OPTIONS", "PYTHONPATH"):
                self.assertNotIn(key, env)
            self.assertEqual(env["PATH"], str(state / "empty-path"))
            self.assertEqual(list(state.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
