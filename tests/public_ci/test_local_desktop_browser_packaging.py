"""浏览器测试归档、冻结自检门槛及失败摘要的离线回归。"""
import json
import io
import os
from pathlib import Path, PureWindowsPath
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/desktop"))
import local_browser_fixture
import local_build
import local_smoke


class BrowserArchiveTests(unittest.TestCase):
    def test_public_binary_staging_uses_normal_creation_mode_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = Path.mkdir
            modes = []
            def capture(path, mode=0o777, *args, **kwargs):
                modes.append(mode)
                return original(path, mode, *args, **kwargs)
            with patch.object(Path, "mkdir", capture):
                with local_browser_fixture.extraction_staging(root) as staging:
                    self.assertEqual(staging.parent, root)
                    self.assertTrue(staging.name.startswith(".browser-extract-"))
                    self.assertTrue(staging.is_dir())
                    (staging / "test.txt").write_text("public", encoding="utf-8")
            self.assertEqual(modes, [0o755])
            self.assertFalse(staging.exists())

    def test_public_binary_staging_cleans_up_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                with local_browser_fixture.extraction_staging(root) as staging:
                    (staging / "partial.txt").write_text("public", encoding="utf-8")
                    raise RuntimeError("模拟解压失败")
            self.assertFalse(staging.exists())

    def test_public_binary_staging_does_not_remove_moved_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with local_browser_fixture.extraction_staging(root) as staging:
                (staging / "test.txt").write_text("public", encoding="utf-8")
                staging.rename(root / "runtime")
            self.assertEqual((root / "runtime/test.txt").read_text(encoding="utf-8"), "public")

    def test_committed_sources_cover_each_target_with_matching_versions(self):
        manifest = json.loads((ROOT / "licenses/local/browser-test-sources.json").read_text(encoding="utf-8"))
        for target in ("mac-arm64", "win64", "linux64"):
            records = local_browser_fixture.selected_sources(manifest, target)
            self.assertEqual({item["kind"] for item in records}, {"chrome", "chromedriver"})
            for record in records:
                self.assertIn('/' + manifest["version"] + '/', record["url"])

    def test_wrong_registry_or_unpinned_archive_rejected(self):
        original = json.loads((ROOT / "licenses/local/browser-test-sources.json").read_text(encoding="utf-8"))
        for field, bad in (("url", "https://attacker.invalid/chrome.zip"), ("sha256", "")):
            manifest = json.loads(json.dumps(original))
            next(item for item in manifest["archives"] if item["platform"] == "win64")[field] = bad
            with self.assertRaises(ValueError):
                local_browser_fixture.selected_sources(manifest, "win64")

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, name in enumerate(("../private.txt", "/outside.txt", "C:outside.txt", "x\\..\\private.txt")):
                archive = root / f"bad{index}.zip"
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr(name, "forbidden")
                with self.assertRaises(ValueError):
                    local_browser_fixture.safe_extract(archive, root / f"out{index}")

    def test_duplicate_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "duplicate.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("a/file", "first")
                z.writestr("a/file", "second")
            with self.assertRaises(ValueError):
                local_browser_fixture.safe_extract(archive, root / "out")

    def test_framework_symlinks_and_permissions_preserved(self):
        if os.name == "nt":
            self.skipTest("macOS framework 链接由 POSIX 目标验证")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "framework.zip"
            with zipfile.ZipFile(archive, "w") as z:
                regular = zipfile.ZipInfo("App/Framework/Versions/154/Resources/file")
                regular.external_attr = (stat.S_IFREG | 0o755) << 16
                z.writestr(regular, b"official")
                for name, target in (("App/Framework/Versions/Current", "154"),
                                     ("App/Framework/Resources", "Versions/Current/Resources")):
                    link = zipfile.ZipInfo(name)
                    link.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(link, target)
            local_browser_fixture.safe_extract(archive, root / "out")
            copied = root / "out/App/Framework/Resources/file"
            self.assertEqual(copied.read_bytes(), b"official")
            self.assertTrue(copied.stat().st_mode & stat.S_IXUSR)

    def test_outside_symlink_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "link.zip"
            with zipfile.ZipFile(archive, "w") as z:
                link = zipfile.ZipInfo("App/link")
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(link, "../../outside")
            with self.assertRaises(ValueError):
                local_browser_fixture.safe_extract(archive, root / "out")


class BrowserSmokeEvidenceTests(unittest.TestCase):
    def test_windows_redirected_console_accepts_chinese(self):
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="cp1252")
        stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with patch.object(local_build.sys, "stdout", stdout), patch.object(local_build.sys, "stderr", stderr):
            local_build.configure_console()
            print("构建成功")
            stdout.flush()
            self.assertEqual(buffer.getvalue().decode("utf-8").strip(), "构建成功")

    def report(self):
        return {"mode": "local-browser", "fixture": "loopback-html", "real_site_visited": False,
                "browser_version": "154.0.8037.57", "chromedriver_version": "154.0.8037.57", "qt": "6.11.1",
                "checks": sorted(local_smoke.REQUIRED_BROWSER_CHECKS), "stream_snapshot_count": 3,
                "browser_process_restart": True, "application_process_restart": False,
                "browser_restart_method": "owned-graceful-reconnect", "crash_recovery_tested": False,
                "same_profile_history_restored": True, "cancelled_queue_sent": False,
                "request_count": 4, "response_count": 2, "private_profile": "/private/state"}

    def test_browser_restart_not_relabelled_as_application_restart(self):
        safe = local_smoke.validate_browser_report(self.report(), {"version": "154.0.8037.57"})
        self.assertTrue(safe["browser_process_restart"])
        self.assertFalse(safe["application_process_restart"])
        self.assertEqual(safe["browser_restart_method"], "owned-graceful-reconnect")
        self.assertFalse(safe["crash_recovery_tested"])
        self.assertNotIn("private_profile", safe)

    def test_browser_evidence_requires_exact_capabilities_and_real_checks(self):
        for field, bad in (("browser_version", "154.0.8037.58"), ("chromedriver_version", "153.0.0.0"),
                           ("fixture", "real-user-site"), ("real_site_visited", True), ("checks", []),
                           ("stream_snapshot_count", 1), ("cancelled_queue_sent", True),
                           ("same_profile_history_restored", False), ("application_process_restart", True),
                           ("browser_restart_method", "forced-kill"), ("crash_recovery_tested", True),
                           ("browser_restart_method", None), ("crash_recovery_tested", None),
                           ("request_count", 3)):
            report = self.report()
            report[field] = bad
            with self.assertRaises(RuntimeError):
                local_smoke.validate_browser_report(report, {"version": "154.0.8037.57"})

    def test_failed_windowed_run_has_sanitized_diagnostic_before_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "local-startup.log").write_text(
                f'private chat content\nTraceback (most recent call last):\n  File "{state}/private/module.py", line 9\n'
                'RuntimeError: local-fixture-not-a-secret api_key=secret\n', encoding="utf-8")
            summary = local_smoke.failure_diagnostic(state / "outer.log", state)
            self.assertIn("RuntimeError", summary)
            self.assertNotIn("private chat content", summary)
            self.assertNotIn(str(state), summary)
            self.assertNotIn("local-fixture-not-a-secret", summary)
            self.assertNotIn("api_key=secret", summary)

    def test_traceback_stops_at_exception_before_buffered_startup_output(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            log = state / "outer.log"
            log.write_text('Traceback (most recent call last):\n  File "module.py", line 4\n'
                           '    raise RuntimeError("测试失败")\nRuntimeError: 测试失败\n'
                           '[PluginLoader] private startup data\nERROR: unrelated later data\n', encoding="utf-8")
            summary = local_smoke.failure_diagnostic(log, state)
            self.assertIn("RuntimeError: 测试失败", summary)
            self.assertNotIn("private startup data", summary)
            self.assertNotIn("unrelated later data", summary)

    def test_windows_literal_and_repr_paths_are_both_redacted(self):
        windows_root = PureWindowsPath(r"D:\a\private-repo")
        windows_home = PureWindowsPath(r"C:\Users\private-runner")
        paths = [str(windows_root / "build"), str(windows_home / "AppData" / "Local" / "Temp")]
        message = "ERROR: " + " | ".join(paths) + " | " + repr(paths)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            log = state / "outer.log"
            log.write_text(message, encoding="utf-8")
            with patch.object(local_smoke, "ROOT", windows_root), patch.object(Path, "home", return_value=windows_home):
                summary = local_smoke.failure_diagnostic(log, state)
                report = local_smoke.safe_failure_report("测试", RuntimeError(message), windows_root / "build")
        for text in (summary, report["summary"]):
            self.assertNotIn("private-repo", text)
            self.assertNotIn("private-runner", text)
            self.assertNotIn("D:", text)
            self.assertNotIn("C:", text)

    def test_failure_json_is_not_stale_success_or_raw_user_state(self):
        report = local_smoke.safe_failure_report("API首次完整运行", RuntimeError(
            "failed /tmp/ai-bridge-local-smoke-xyz/config.json api_key=secret"), Path("/tmp/build"))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_type"], "RuntimeError")
        self.assertFalse(report["binary_distribution_approved"])
        self.assertNotIn("/tmp/", report["summary"])
        self.assertNotIn("api_key=secret", report["summary"])
        self.assertEqual(set(report), {"schema_version", "status", "stage", "error_type", "summary",
                                       "binary_distribution_approved", "verification_limit"})

    def test_only_browser_probe_reads_sanitized_chrome_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "logs").mkdir()
            (state / "logs/chrome-startup.log").write_text(
                f"normal page content\n[ERROR:startup] failed {state}/browser-profile api_key=secret\n", encoding="utf-8")
            api = local_smoke.failure_diagnostic(state / "local-smoke.log", state)
            self.assertNotIn("chrome-startup.log", api)
            browser = local_smoke.failure_diagnostic(state / "local-browser-smoke.log", state)
            self.assertIn("[ERROR:startup]", browser)
            self.assertNotIn("normal page content", browser)
            self.assertNotIn(str(state), browser)
            self.assertNotIn("api_key=secret", browser)


if __name__ == "__main__":
    unittest.main()
