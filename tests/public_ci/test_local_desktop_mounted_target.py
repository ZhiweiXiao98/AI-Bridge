"""挂载目标只改启动位置，不执行任何fixture文件。"""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.append(str(Path(__file__).resolve().parents[2] / 'tools/desktop'))
import local_smoke


class MountedTargetTests(unittest.TestCase):
    def fixture(self, root):
        build=root/'build';target=root/'mounted/AI-Bridge-Local.app/Contents/MacOS/AI-Bridge-Local'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'public fake launcher: not executable')
        inventory={'files':[{'path':'AI-Bridge-Local.app/Contents/MacOS/AI-Bridge-Local',
                             'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}]}
        return build,target,inventory

    def test_bound_shaped_regular_target_is_selected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local_smoke.sys,'platform','darwin'):
            build,target,inventory=self.fixture(Path(directory))
            self.assertEqual(local_smoke.smoke_executable(build,inventory,target),target.resolve())
            self.assertEqual(local_smoke.smoke_executable(build,inventory),local_smoke.executable_path(build))

    def test_relative_missing_wrong_shape_and_wrong_bytes_fail(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local_smoke.sys,'platform','darwin'):
            build,target,inventory=self.fixture(Path(directory))
            wrong=target.parent/'other';wrong.write_bytes(target.read_bytes())
            for candidate in (Path('relative/AI-Bridge-Local'),target.parent/'missing',wrong):
                with self.subTest(candidate=str(candidate)),self.assertRaises(RuntimeError):
                    local_smoke.smoke_executable(build,inventory,candidate)
            target.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):local_smoke.smoke_executable(build,inventory,target)

    def test_missing_inventory_binding_fails(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local_smoke.sys,'platform','darwin'):
            build,target,_=self.fixture(Path(directory))
            with self.assertRaises(RuntimeError):local_smoke.smoke_executable(build,{'files':[]},target)

    @unittest.skipIf(sys.platform=='win32','无需权限创建POSIX链接的离线测试')
    def test_launcher_and_application_symlinks_fail(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local_smoke.sys,'platform','darwin'):
            root=Path(directory);build,target,inventory=self.fixture(root)
            data=target.read_bytes();target.unlink();backing=target.parent/'backing';backing.write_bytes(data)
            target.symlink_to('backing')
            with self.assertRaises(RuntimeError):local_smoke.smoke_executable(build,inventory,target)
            target.unlink();target.write_bytes(data)
            alias=root/'alias';alias.mkdir();(alias/'AI-Bridge-Local.app').symlink_to(target.parents[2],target_is_directory=True)
            with self.assertRaises(RuntimeError):local_smoke.smoke_executable(build,inventory,alias/'AI-Bridge-Local.app/Contents/MacOS/AI-Bridge-Local')


if __name__=='__main__':unittest.main()
