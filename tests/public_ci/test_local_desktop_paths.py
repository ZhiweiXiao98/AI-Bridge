"""不加载Qt、不连接任何服务的本地启动目录回归。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LocalPathsTests(unittest.TestCase):
    def test_source_startup_uses_private_data_and_readonly_resource_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            script = """
from pathlib import Path
from app.core.local_paths import configure_local_paths, resource_path
home = configure_local_paths()
from app.core.app_constants import APP_ROOT, PROJECT_ROOT
assert Path(APP_ROOT) == home == Path(PROJECT_ROOT) == Path.cwd()
assert resource_path('runtime', 'pi', 'sidecar.mjs').is_file()
assert not resource_path().is_relative_to(home)
assert __import__('os').environ['AI_BRIDGE_LOCAL_MODE'] == '1'
"""
            result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                    env={**os.environ, "AI_BRIDGE_LOCAL_HOME": directory},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_entrypoint_does_not_launch_remote_client_or_auth_server(self):
        source = (ROOT / "boot_local.py").read_text(encoding="utf-8")
        self.assertIn("WorkerThread(startup_mode=args.mode)", source)
        self.assertIn("MainWindow(worker_core=worker", source)
        for forbidden in ("RemoteWorker(", "LoginWindow(", "AUTH_ADMIN_PASSWORD", "import server"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
