# filename: tests/test_self_update.py
import pytest
import os
import sys
from unittest.mock import patch, MagicMock

# 确保路径正确
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.self_update import SelfUpdateManager

class TestSelfUpdateRealWorld:
    """
    🏗️ 自更新系统实战测试 (Integration Test)
    在临时目录中模拟真实的文件读写、哈希比对和覆盖流程。
    """

    @pytest.fixture
    def env(self, tmp_path):
        """
        搭建一个微缩版的项目环境
        tmp_path/
          ├── project/  (模拟项目根目录)
          └── staging/  (模拟 export/code)
        """
        root = tmp_path / "project"
        staging = tmp_path / "staging"
        root.mkdir()
        staging.mkdir()
        
        # 实例化 Manager，注入我们的假路径
        mgr = SelfUpdateManager(project_root=str(root), staging_dir=str(staging))
        return {
            "root": root, 
            "staging": staging, 
            "mgr": mgr
        }

    def test_detect_new_file(self, env):
        """测试 1: 检测新增文件 (New)"""
        # 在暂存区创建一个新文件
        new_file = env["staging"] / "new_feature.py"
        new_file.write_text("print('hello')", encoding='utf-8')
        
        # 扫描
        changes = env["mgr"].scan()
        
        # 验证
        assert len(changes) == 1
        assert changes[0]['status'] == "new"
        assert changes[0]['rel_path'] == "new_feature.py"
        print("\n✅ 新增文件检测通过")

    def test_detect_overwrite_file(self, env):
        """测试 2: 检测内容变更 (Overwrite)"""
        # 根目录有旧版
        target = env["root"] / "config.py"
        target.write_text("ver = 1.0", encoding='utf-8')
        
        # 暂存区有新版
        source = env["staging"] / "config.py"
        source.write_text("ver = 2.0", encoding='utf-8')
        
        # 扫描
        changes = env["mgr"].scan()
        
        # 验证
        assert len(changes) == 1
        assert changes[0]['status'] == "overwrite"
        print("✅ 覆盖更新检测通过")

    def test_ignore_same_content_crlf(self, env):
        """
        测试 3: 换行符标准化 (CRLF vs LF) - 关键！
        Windows (CRLF) 和 Linux (LF) 不应该被视为不同
        """
        # 根目录 (Linux 风格)
        target = env["root"] / "script.py"
        target.write_bytes(b"import os\nprint(1)") # \n
        
        # 暂存区 (Windows 风格)
        source = env["staging"] / "script.py"
        source.write_bytes(b"import os\r\nprint(1)") # \r\n
        
        # 扫描
        changes = env["mgr"].scan()
        
        # 验证: 应该识别为 "same"，即 changes 列表为空或 status 为 same
        # 这里的 scan() 实现是：如果 same 也会加入 list，但 status='same'
        same_files = [c for c in changes if c['status'] == "same"]
        diff_files = [c for c in changes if c['status'] != "same"]
        
        assert len(diff_files) == 0, f"误报了差异: {diff_files}"
        assert len(same_files) == 1
        print("✅ 换行符(CRLF)智能忽略测试通过")

    def test_apply_update_action(self, env):
        """测试 4: 执行更新动作 (Apply)"""
        # 准备场景
        (env["staging"] / "main.py").write_text("v2", encoding='utf-8')
        (env["root"] / "main.py").write_text("v1", encoding='utf-8')
        
        # 执行更新
        count = env["mgr"].apply()
        
        # 验证: 文件是否真的变了？
        updated_content = (env["root"] / "main.py").read_text(encoding='utf-8')
        assert updated_content == "v2"
        assert count == 1
        print("✅ 文件覆盖执行测试通过")

    @patch("subprocess.run")
    def test_trigger_csharp_build(self, mock_run, env):
        """测试 5: C# 代码变动触发编译"""
        # 准备 C# 文件结构
        cs_dir = env["staging"] / "RhinoBIM_Client"
        cs_dir.mkdir()
        (cs_dir / "Plugin.cs").write_text("// new c# code", encoding='utf-8')
        
        # 运行 apply
        env["mgr"].apply()
        
        # 验证: subprocess.run 是否被调用了？
        # 我们检查是否调用了 "dotnet build"
        assert mock_run.called
        args, _ = mock_run.call_args
        assert args[0] == ["dotnet", "build"]
        print("✅ C# 自动编译触发逻辑通过")

    def test_ignore_system_files(self, env):
        """测试 6: 黑名单过滤 (.git, venv)"""
        # 在暂存区创建垃圾文件
        git_dir = env["staging"] / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("secret", encoding='utf-8')
        
        # 创建 pycache
        cache_dir = env["staging"] / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "temp.pyc").write_bytes(b"binary")
        
        # 扫描
        changes = env["mgr"].scan()
        
        # 验证: 这些文件不应该出现在变更列表中
        files = [c['rel_path'] for c in changes]
        assert not any(".git" in f for f in files)
        assert not any("__pycache__" in f for f in files)
        print("✅ 系统文件黑名单过滤通过")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])