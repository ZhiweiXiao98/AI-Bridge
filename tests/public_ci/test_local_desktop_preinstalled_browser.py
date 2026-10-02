"""标准 runner 的预装官方浏览器分支；纯离线，不执行 PowerShell、安装器或 Chrome。"""
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/desktop'))
import local_preinstalled_browser as installed
from local_build import digest


class PreinstalledBrowserTests(unittest.TestCase):
    def test_query_only_uses_selected_system_powershell_modules_without_mutating_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.metadata(root)
            metadata['ok'] = True
            powershell = root / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            powershell.parent.mkdir(parents=True)
            powershell.write_bytes(b'unit-test-placeholder')
            with patch.dict(os.environ, {'SYSTEMROOT': str(root), 'PSModulePath': 'foreign PS7 modules'}, clear=True), \
                    patch.object(installed, 'runner_identity', return_value={'origin': 'github-hosted-runner'}), \
                    patch.object(installed.subprocess, 'run', return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps(metadata), '')) as execute:
                installed.read_preinstalled_chrome()
                self.assertEqual(os.environ['PSModulePath'], 'foreign PS7 modules')
                self.assertEqual(execute.call_args.kwargs['env']['PSModulePath'], str(powershell.parent / 'Modules'))
                self.assertEqual(execute.call_args.args[0][0], str(powershell))
            self.assertIn("[IO.Path]::Combine($PSHOME, 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1')", installed._CHROME_QUERY)
            self.assertLess(installed._CHROME_QUERY.index('Import-Module'), installed._CHROME_QUERY.index('Get-AuthenticodeSignature'))
            failure = json.loads(installed.query_failure_diagnostic({'stage': 'signature_module'}, ''))
            self.assertEqual(failure['stage'], 'signature_module')

    def test_query_failure_diagnostic_is_fixed_and_private_values_are_dropped(self):
        result = json.loads(installed.query_failure_diagnostic(
            {'stage': 'signature', 'error_kind': 'RuntimeException', 'signature_status': 'NotTrusted',
             'registry_found': True, 'file_found': True, 'publisher_matched': False,
             'message': 'private certificate', 'path': 'C:/private/chrome.exe'}, 'private stderr'))
        self.assertEqual(result['stage'], 'signature')
        self.assertEqual(result['signature_status'], 'NotTrusted')
        self.assertFalse(result['publisher_matched'])
        self.assertNotIn('private', json.dumps(result))
        bad = json.loads(installed.query_failure_diagnostic(
            {'stage': ['private'], 'error_kind': 'private', 'signature_status': {'private': True},
             'registry_found': 1, 'file_found': 'yes'}, 'private stderr'))
        self.assertEqual(bad, {'stage': 'powershell_start_or_parse', 'error_kind': 'other', 'signature_status': 'unknown'})

    def test_parse_failure_only_exposes_known_error_class(self):
        result = json.loads(installed.query_failure_diagnostic(None, 'ParserError in C:/private/script.ps1'))
        self.assertEqual(result['error_kind'], 'ParserError')
        self.assertNotIn('private', json.dumps(result))

    def test_browser_preparation_precedes_expensive_freeze(self):
        workflow = (ROOT / '.github/workflows/local-desktop-build.yml').read_text(encoding='utf-8')
        for helper in ('local_browser_fixture.py', 'local_preinstalled_browser.py'):
            self.assertLess(workflow.index('python tools/desktop/' + helper),
                            workflow.index('python tools/desktop/local_build.py'))

    def metadata(self, root):
        chrome = root / 'Program Files/Google/Chrome/Application/chrome.exe'
        chrome.parent.mkdir(parents=True, exist_ok=True)
        chrome.write_bytes(b'unit-test-placeholder-not-executable')
        return {'chrome': str(chrome), 'version': '154.0.8037.58', 'publisher': 'Google LLC',
                'authenticode_status': 'Valid', 'signer_thumbprint': 'A' * 40,
                'program_files': str(root / 'Program Files'), 'program_files_x86': ''}

    def test_only_same_major_minor_build_is_compatible(self):
        self.assertTrue(installed.compatible_build('154.0.8037.58', '154.0.8037.57'))
        for version in ('154.0.8038.57', '155.0.8037.57', '154.1.8037.57', '154.0.8037', ''):
            self.assertFalse(installed.compatible_build(version, '154.0.8037.57'))

    def test_signed_standard_install_metadata_has_no_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self.metadata(Path(directory))
            chrome, public = installed.validate_chrome_metadata(metadata)
            self.assertEqual(chrome, Path(metadata['chrome']).resolve())
            self.assertNotIn(directory, json.dumps(public))
            self.assertEqual(public['version'], '154.0.8037.58')

    def test_wrong_publisher_signature_version_or_location_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self.metadata(Path(directory))
            for field, value in (('publisher', 'Unknown'), ('authenticode_status', 'NotSigned'),
                                 ('signer_thumbprint', ''), ('version', '154'),
                                 ('program_files', directory), ('chrome', 'relative/chrome.exe')):
                with self.subTest(field=field):
                    with self.assertRaises(RuntimeError):
                        installed.validate_chrome_metadata({**metadata, field: value})

    def test_missing_runner_identity_is_rejected_before_query(self):
        with patch.object(installed.sys, 'platform', 'win32'), patch.object(installed, 'test_platform', return_value='win64'):
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
                installed.runner_identity()
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows',
                                         'ImageOS': 'win25-vs2026', 'ImageVersion': '20260925.250.1'}, clear=True):
                self.assertEqual(installed.runner_identity()['origin'], 'github-hosted-runner')

    def test_query_is_fixed_read_only_and_never_changes_permissions(self):
        query = installed._CHROME_QUERY
        self.assertIn('Get-AuthenticodeSignature', query)
        self.assertIn('Get-ItemProperty', query)
        self.assertIn('Google LLC', query)
        for command in ('Set-Acl', 'icacls', 'setup.exe', 'Set-ItemProperty', 'New-ItemProperty', 'Start-Process'):
            self.assertNotIn(command, query)

    def test_prepare_uses_only_fixed_driver_and_never_runs_chrome_or_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chrome, public = installed.validate_chrome_metadata(self.metadata(root))
            source_path = installed.ROOT / 'licenses/local/browser-test-sources.json'
            manifest = json.loads(source_path.read_text(encoding='utf-8'))
            cache = root / 'cache'
            cache.mkdir()
            archive = cache / 'chromedriver-win64.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('chromedriver-win64/chromedriver.exe', b'unit-test-only')
            record = next(x for x in manifest['archives'] if x['platform'] == 'win64' and x['kind'] == 'chromedriver')
            record.update(sha256=digest(archive), size=archive.stat().st_size)
            manifest_path = root / 'licenses/local/browser-test-sources.json'
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            output = root / 'output'
            with patch.object(installed, 'ROOT', root), patch.object(installed, 'read_preinstalled_chrome', return_value=(chrome, public)), \
                    patch.object(installed, 'urlopen', side_effect=AssertionError('离线测试不能联网')), \
                    patch.object(installed.subprocess, 'check_output', return_value='ChromeDriver 154.0.8037.57') as execute, \
                    patch('builtins.print'):
                result = installed.prepare(output, archive_cache=cache)
            self.assertEqual([x['kind'] for x in result['archives']], ['chromedriver'])
            self.assertFalse((output / 'runtime/chrome-win64').exists())
            self.assertEqual(result['browser_version'], '154.0.8037.58')
            self.assertEqual(result['chromedriver_version'], '154.0.8037.57')
            execute.assert_called_once()
            command = execute.call_args.args[0]
            self.assertEqual(command[1:], ['--version'])
            self.assertEqual(Path(command[0]).name, 'chromedriver.exe')

    def test_changed_runtime_metadata_or_bytes_fail_and_public_report_has_no_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.metadata(root)
            chrome, public = installed.validate_chrome_metadata(metadata)
            public.update(origin='github-hosted-runner', image_os='win25-vs2026',
                          image_version='20260925.250.1', image_repository='https://github.com/actions/runner-images')
            manifest_path = installed.ROOT / 'licenses/local/browser-test-sources.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            record = next(x for x in manifest['archives'] if x['platform'] == 'win64' and x['kind'] == 'chromedriver')
            driver = root / 'runtime/chromedriver-win64/chromedriver.exe'
            driver.parent.mkdir(parents=True)
            driver.write_bytes(b'unit-test-fixed-driver')
            runtime = {'source_kind': 'runner-preinstalled-chrome', 'platform': 'win64',
                       'browser_version': '154.0.8037.58', 'chromedriver_version': '154.0.8037.57',
                       'chrome': str(chrome), 'chromedriver': str(driver), 'preinstalled_browser': public,
                       'chrome_executable_sha256': digest(chrome), 'chromedriver_executable_sha256': digest(driver),
                       'archives': [record], 'source_manifest_sha256': digest(manifest_path),
                       'official_manifest_url': manifest['official_manifest_url'], 'not_in_application_bundle': True}
            with patch.object(installed, 'read_preinstalled_chrome', return_value=(chrome, public)):
                report = installed.validate_runtime(runtime, root / 'runtime.json')
                self.assertNotIn(directory, json.dumps(report))
                for field, value in (('browser_version', '154.0.8037.57'), ('chromedriver_version', '154.0.8037.58'),
                                     ('source_kind', 'fixed-cft'), ('archives', []), ('not_in_application_bundle', False),
                                     ('chrome_executable_sha256', 'changed'), ('chromedriver_executable_sha256', 'changed')):
                    with self.subTest(field=field), self.assertRaises(RuntimeError):
                        installed.validate_runtime({**runtime, field: value}, root / 'runtime.json')
                driver.write_bytes(b'changed')
                with self.assertRaises(RuntimeError):
                    installed.validate_runtime(runtime, root / 'runtime.json')


class BrowserSourceRoutingTests(unittest.TestCase):
    def report(self):
        import local_smoke
        return {'mode': 'local-browser', 'fixture': 'loopback-html', 'real_site_visited': False,
                'browser_version': '154.0.8037.58', 'chromedriver_version': '154.0.8037.57', 'qt': '6.11.1',
                'checks': sorted(local_smoke.REQUIRED_BROWSER_CHECKS), 'stream_snapshot_count': 3,
                'browser_process_restart': True, 'application_process_restart': False,
                'browser_restart_method': 'owned-graceful-reconnect', 'crash_recovery_tested': False,
                'same_profile_history_restored': True, 'cancelled_queue_sent': False,
                'request_count': 4, 'response_count': 2}

    def test_preinstalled_full_versions_are_separate_and_exact(self):
        import local_smoke
        fixture = {'source_kind': 'runner-preinstalled-chrome', 'browser_version': '154.0.8037.58',
                   'chromedriver_version': '154.0.8037.57'}
        report = self.report()
        self.assertEqual(local_smoke.validate_browser_report(report, fixture)['browser_version'], '154.0.8037.58')
        for field in ('browser_version', 'chromedriver_version'):
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                local_smoke.validate_browser_report({**report, field: '154.0.8037.59'}, fixture)
        with self.assertRaises(RuntimeError):
            local_smoke.validate_browser_report(report, {**fixture, 'browser_version': '154.0.8038.58'})

    def test_original_cft_source_still_requires_identical_full_versions(self):
        import local_smoke
        with self.assertRaises(RuntimeError):
            local_smoke.validate_browser_report(self.report(), {'version': '154.0.8037.57'})
        report = {**self.report(), 'browser_version': '154.0.8037.57'}
        local_smoke.validate_browser_report(report, {'version': '154.0.8037.57'})
        with self.assertRaises(RuntimeError):
            local_smoke.validate_browser_report(report, {'source_kind': 'unknown', 'version': '154.0.8037.57'})

    def test_preinstalled_runtime_routes_only_to_explicit_readonly_verifier(self):
        import local_smoke
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runtime.json'
            runtime = {'source_kind': 'runner-preinstalled-chrome'}
            path.write_text(json.dumps(runtime), encoding='utf-8')
            with patch.object(installed, 'validate_runtime', return_value={'verified': True}) as validate:
                self.assertEqual(local_smoke.read_browser_fixture(path), (runtime, {'verified': True}))
                validate.assert_called_once_with(runtime, path)
            path.write_text(json.dumps({'source_kind': 'unknown'}), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                local_smoke.read_browser_fixture(path)


if __name__ == '__main__':
    unittest.main()
