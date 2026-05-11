# filename: tests/test_parser_merge.py
import pytest
import sys
import os

# 确保路径正确，以便导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.driver.parser import DOMParser

class TestParserMerge:
    """
    🔬 解析器合并逻辑测试 (Parser Merge Logic)
    
    核心原则 (V5.8+):
    1. 相邻的【文本】段落应该合并，以提供流畅的阅读体验。
    2. 相邻的【代码】段落必须保持【独立】，严禁合并。
       原因：AI 可能会连续输出多个文件 (e.g. file_a.py, file_b.py)。
       如果强行合并，Worker 将无法正确分割文件，导致所有代码被写入同一个文件或解析失败。
    """

    def setup_method(self):
        self.parser = DOMParser()

    def test_merge_adjacent_text(self):
        """测试：相邻文本段落应合并"""
        raw_segments = [
            {"type": "text", "content": "Paragraph 1."},
            {"type": "text", "content": "Paragraph 2."},
            {"type": "code", "content": "print('code')"},
            {"type": "text", "content": "Footer."}
        ]
        
        cleaned = self.parser.clean_code_headers(raw_segments)
        
        # 验证结果结构：应合并前两个文本
        assert len(cleaned) == 3 # [Text(1+2), Code, Text]
        
        # 验证合并内容
        assert cleaned[0]['type'] == "text"
        assert "Paragraph 1.Paragraph 2." in cleaned[0]['content']
        
        # 验证后续未受影响
        assert cleaned[1]['type'] == "code"
        assert cleaned[2]['type'] == "text"

    def test_merge_adjacent_code_forbidden(self):
        """
        [Critical] 测试：相邻代码块【严禁】合并
        这是为了支持多文件输出场景 (file_a.py + file_b.py)
        """
        raw_segments = [
            {"type": "code", "content": "# filename: a.py\ndef a(): pass"},
            {"type": "code", "content": "# filename: b.py\ndef b(): pass"}
        ]
        
        cleaned = self.parser.clean_code_headers(raw_segments)
        
        # 预期：保持独立，长度为 2
        assert len(cleaned) == 2, "错误：相邻代码块被意外合并了！这将破坏多文件输出功能。"
        
        # 验证内容完整性
        assert cleaned[0]['type'] == 'code'
        assert cleaned[0]['content'] == "# filename: a.py\ndef a(): pass"
        
        assert cleaned[1]['type'] == 'code'
        assert cleaned[1]['content'] == "# filename: b.py\ndef b(): pass"

    def test_mixed_interleave(self):
        """测试：文本与代码交错时不合并"""
        raw_segments = [
            {"type": "text", "content": "Explanation A"},
            {"type": "code", "content": "print('B')"},
            {"type": "text", "content": "Explanation C"}
        ]
        
        cleaned = self.parser.clean_code_headers(raw_segments)
        
        # 预期：互不干扰，保持原样
        assert len(cleaned) == 3
        assert cleaned[0]['content'] == "Explanation A"
        assert cleaned[1]['content'] == "print('B')"
        assert cleaned[2]['content'] == "Explanation C"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])