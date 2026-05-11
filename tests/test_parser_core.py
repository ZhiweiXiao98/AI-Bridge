# filename: tests/test_parser_core.py
import pytest
import sys
import os
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.driver.parser import DOMParser

class TestParserCore:
    def setup_method(self):
        self.parser = DOMParser()

    def test_clean_monaco_structure(self):
        html = """
        <div class="monaco-editor">
            <div class="margin-view-overlays">
                <div class="line-numbers" style="top:0px">1</div>
                <div class="line-numbers" style="top:19px">2</div>
            </div>
            <div class="view-lines">
                <div class="view-line" style="top:0px"><span>import</span><span> os</span></div>
                <div class="view-line" style="top:19px"><span>print("Hello")</span></div>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        target_node = soup.find(class_="view-lines")
        result = self.parser.parse_code_block(target_node)
        expected = 'import os\nprint("Hello")'
        assert result == expected
        print("\n✅ 标准代码块解析通过")

    def test_markstream_monaco_language_detection(self):
        html = """
        <div class="node-slot" data-node-type="code_block">
            <div class="code-block-container" data-markstream-code-block="1">
                <div class="code-block-header">
                    <div class="code-header-title">Python</div>
                    <button aria-label="复制">copy</button>
                </div>
                <div class="code-editor-container" data-mode-id="python">
                    <div class="monaco-editor">
                        <div class="margin-view-overlays">
                            <div style="top:0px"><div class="line-numbers">1</div></div>
                        </div>
                        <div class="view-lines">
                            <div class="view-line" style="top:0px">
                                <span>msg.get(</span><span>"role"</span><span>) == </span><span>"assistant"</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        segments = self.parser.clean_code_headers(self.parser.parse_node(soup.find(class_="node-slot")))

        assert len(segments) == 1
        assert segments[0]['type'] == 'code'
        assert segments[0]['language'] == 'python'
        assert segments[0]['content'] == 'msg.get("role") == "assistant"'
        assert self.parser.parse_node(soup.find(class_="view-lines"))[0]['language'] == 'python'

    def test_transient_markstream_uses_mode_id_language(self):
        html = """
        <div class="node-slot" data-node-type="code_block">
            <div class="code-header-title">JSON</div>
            <div class="code-editor-container" data-mode-id="json">
                <div class="view-lines">
                    <div class="view-line" style="top:0px"><span>{"ok": true}</span></div>
                </div>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        segments, _ = self.parser.parse_browser_transient_message(soup)

        assert len(segments) == 1
        assert segments[0]['type'] == 'code'
        assert segments[0]['language'] == 'json'
        assert segments[0]['content'] == '{"ok": true}'

    def test_markstream_tool_call_language_alias(self):
        html = """
        <div data-node-type="code_block">
            <div class="code-header-title">Tool Call</div>
            <div class="code-editor-container" data-mode-id="tool-call"></div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        assert self.parser._detect_code_placeholder_language(soup.div) == 'tool_call'

    def test_anchor_alignment_logic(self):
        html = """
        <div class="monaco-editor">
            <div class="margin-view-overlays">
                <div style="top:0px"></div>
                <div style="top:20px"></div>
                <div style="top:40px"></div>
            </div>
            <div class="view-lines">
                <div class="view-line" style="top:0px">Line 1</div>
                <div class="view-line" style="top:20px">Line 2</div>
                <div class="view-line" style="top:40px">Line 3</div>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        node = soup.find(class_="view-lines")
        result = self.parser.parse_code_block(node)
        assert result == "Line 1\nLine 2\nLine 3"
        print("✅ 锚点对齐逻辑通过")

    def test_fallback_mode(self):
        html = """
        <pre>
            <code>def test():\n    pass</code>
        </pre>
        """
        soup = BeautifulSoup(html, 'html.parser')
        node = soup.find("pre")
        result = self.parser.parse_node(node)
        assert len(result) == 1
        assert result[0]['type'] == 'code'
        assert "def test" in result[0]['content']
        print("✅ 降级模式通过")

    def test_n_image_structure(self):
        html = """
        <div role="none" class="n-image" style="">
            <img width="200" src="https://example.com/test.png" loading="eager">
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        node = soup.find("div")
        segments = self.parser.parse_node(node)
        assert len(segments) == 1
        assert segments[0]['type'] == 'image'
        assert segments[0]['content'] == 'https://example.com/test.png'
        print("✅ n-image 解析通过")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
