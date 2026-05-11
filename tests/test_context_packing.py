# filename: tests/test_context_packing.py
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.services.context_pack_service import ContextPackService, PackDef

class TestContextPacking:
    """
    📦 上下文打包逻辑测试
    修正点：传入 Pack Key (str) 而非文件列表
    """
    @pytest.fixture
    def packer(self):
        return ContextPackService()

    def test_pack_context_logic(self, packer):
        # 1. 定义一个测试用的包结构
        test_pack_def = PackDef(
            key="test_pkg",
            title="Test Package",
            description="UT",
            includes=["main.py", "utils.py"],
            excludes=[]
        )
        
        # 2. Mock 依赖方法
        with patch.object(packer, 'get_pack_defs', return_value={"test_pkg": test_pack_def}):
            with patch.object(packer, '_collect_files', return_value=["main.py", "utils.py"]):
                with patch.object(packer, '_read_text', side_effect=lambda f: f"Content of {os.path.basename(f)}"):
                    
                    # 3. 正确调用：传入字符串 Key
                    prompt = packer.build_pack_text("test_pkg")
                    
                    # 4. 验证结果
                    assert "Test Package" in prompt
                    assert "main.py" in prompt
                    assert "Content of main.py" in prompt
                    assert "utils.py" in prompt

if __name__ == "__main__":
    pytest.main([__file__, "-v"])