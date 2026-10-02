"""原生窗口证据门槛；纯字典回归，不操作桌面或截图。"""
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2] / 'tools/desktop'))
import local_smoke


class NativeGuiEvidenceTests(unittest.TestCase):
    def report(self):
        return {**{key: True for key in local_smoke.NATIVE_BOOLEAN_FIELDS}, 'schema_version': 1, 'mode': 'native-gui',
                'fixture': 'isolated-empty-home', 'stage': 'complete', 'qt': '6.11.1',
                'platform_plugin': 'cocoa', 'qt_exception_count': 0, 'startup_ready_ms': 1500,
                'checks': sorted(local_smoke.REQUIRED_NATIVE_CHECKS)}

    def test_exact_native_plugins_and_safe_fields(self):
        for system, plugin in (('darwin', 'cocoa'), ('win32', 'windows')):
            report = {**self.report(), 'platform_plugin': plugin, 'private_path': '/private/screenshot.png',
                      'screenshot_pixels': 'not-public', 'native_handle': 12345}
            report['checks'].append('private extra check')
            with patch.object(local_smoke.sys, 'platform', system):
                result = local_smoke.validate_native_report(report, '6.11.1')
            self.assertEqual(result['platform_plugin'], plugin)
            for field in ('private_path', 'screenshot_pixels', 'native_handle'):
                self.assertNotIn(field, result)
            self.assertNotIn('private extra check', result['checks'])

    def test_offscreen_and_wrong_native_plugin_are_rejected(self):
        for plugin in ('offscreen', 'minimal', 'windows', ''):
            with self.subTest(plugin=plugin), patch.object(local_smoke.sys, 'platform', 'darwin'), self.assertRaises(RuntimeError):
                local_smoke.validate_native_report({**self.report(), 'platform_plugin': plugin}, '6.11.1')

    def test_every_success_boolean_is_required(self):
        with patch.object(local_smoke.sys, 'platform', 'darwin'):
            for field in local_smoke.NATIVE_BOOLEAN_FIELDS:
                for value in (False, None, 1):
                    with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                        local_smoke.validate_native_report({**self.report(), field: value}, '6.11.1')

    def test_exception_stage_version_and_missing_check_fail(self):
        with patch.object(local_smoke.sys, 'platform', 'darwin'):
            for field, value in (('schema_version', 0), ('stage', 'window_ready'), ('qt', '6.10.0'), ('fixture', 'user-home'),
                                 ('qt_exception_count', 1), ('qt_exception_count', False),
                                 ('startup_ready_ms', -1), ('startup_ready_ms', 60001), ('startup_ready_ms', 1.5),
                                 ('checks', [])):
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                    local_smoke.validate_native_report({**self.report(), field: value}, '6.11.1')

    def test_linux_cannot_claim_mac_or_windows_native_acceptance(self):
        with patch.object(local_smoke.sys, 'platform', 'linux'), self.assertRaises(RuntimeError):
            local_smoke.validate_native_report(self.report(), '6.11.1')

    def test_process_timeout_default_remains_compatible(self):
        parameter = inspect.signature(local_smoke.run_application).parameters['timeout_seconds']
        self.assertEqual(parameter.default, 300)
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_native_failure_probe_never_echoes_unknown_values(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            report = {**self.report(), 'stage': 'window_capture', 'qt': '/private/version',
                      'startup_ready_ms': 999999, 'qt_exception_count': True,
                      'platform_plugin': '/private/plugin', 'screenshot_saved': 'private pixels',
                      'unknown': 'secret', 'checks': ['private text', {'private': 'value'}, '原生Qt平台插件']}
            (state / 'local-native-smoke.json').write_text(json.dumps(report), encoding='utf-8')
            safe = local_smoke.native_failure_probe(state)
            self.assertEqual(safe['stage'], 'window_capture')
            self.assertEqual(safe['checks'], ['原生Qt平台插件'])
            for field in ('qt', 'startup_ready_ms', 'qt_exception_count', 'platform_plugin', 'screenshot_saved', 'unknown'):
                self.assertNotIn(field, safe)
            self.assertNotIn('private', json.dumps(safe))
            for stage in ({'private': 'path'}, ['window_ready'], 'window_ready\n/private/extra'):
                report['stage'] = stage
                (state / 'local-native-smoke.json').write_text(json.dumps(report), encoding='utf-8')
                self.assertEqual(local_smoke.native_failure_probe(state)['stage'], 'unknown')

    def test_native_failure_probe_preserves_bounded_actual_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            report = {**self.report(), 'stage': 'screenshot_save', 'screenshot_saved': False, 'passed': False}
            (state / 'local-native-smoke.json').write_text(json.dumps(report), encoding='utf-8')
            safe = local_smoke.native_failure_probe(state)
            self.assertEqual(safe['stage'], 'screenshot_save')
            self.assertEqual(safe['platform_plugin'], 'cocoa')
            self.assertEqual(safe['qt'], '6.11.1')
            self.assertEqual(safe['startup_ready_ms'], 1500)
            self.assertFalse(safe['passed'])
            self.assertFalse(safe['screenshot_saved'])


if __name__ == '__main__':
    unittest.main()
