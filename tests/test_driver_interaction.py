# filename: tests/test_driver_interaction.py
import pytest
from unittest.mock import MagicMock, call, ANY
import sys
import os

# 确保路径正确，以便导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.driver.interaction import InteractionManager, STATE_EXPANDED, STATE_COLLAPSED, LUCIDE_EXPANDED, LUCIDE_COLLAPSED
from app.core.app_constants import UPSTREAM_AI_URL

class TestInteractionManager:
    
    @pytest.fixture
    def mock_driver(self):
        """模拟 Selenium WebDriver"""
        driver = MagicMock()
        return driver

    @pytest.fixture
    def manager(self, mock_driver):
        return InteractionManager(mock_driver)

    # === 1. 基础功能测试 ===

    def test_find_elements_wrapper(self, manager, mock_driver):
        """测试 Selenium 包装器"""
        manager.find_elements(".test")
        mock_driver.find_elements.assert_called_with("css selector", ".test")

    def test_send_message_short(self, manager, mock_driver):
        """短文本沿用浏览器模式发送：输入框 send_keys + Enter。"""
        mock_input = MagicMock()
        manager.find_element = MagicMock(return_value=mock_input)
        mock_driver.execute_script.side_effect = [
            {"user_count": 1, "last_user_id": "old"},
            {"user_count": 2, "last_user_id": "new"},
        ]

        ok, msg = manager.send_message("Hello")

        assert ok is True
        assert msg == "发送成功"
        assert mock_input.send_keys.call_count >= 2

    def test_send_message_long(self, manager, mock_driver):
        """测试长文本发送 (React 注入)"""
        mock_input = MagicMock()
        mock_button = MagicMock()
        mock_button.is_displayed.return_value = True
        manager.find_element = MagicMock(return_value=mock_input)
        mock_driver.execute_script.side_effect = [
            {"user_count": 1, "last_user_id": "old"},
            None,
            None,
            {"user_count": 2, "last_user_id": "new"},
        ]
        mock_driver.find_elements.return_value = [mock_button]
        long_text = "A" * 301 # > 300 触发注入
        ok, msg = manager.send_message(long_text)
        assert ok is True
        assert msg == "发送成功"
        # 长文本应该调用 execute_script
        mock_driver.execute_script.assert_any_call(ANY, mock_input, long_text)

    def test_send_message_fails_when_text_only_in_input(self, manager, mock_driver):
        """如果网页没有出现新的用户消息，不能假装发送成功。"""
        mock_input = MagicMock()
        mock_button = MagicMock()
        mock_button.is_displayed.return_value = True
        manager.find_element = MagicMock(return_value=mock_input)
        mock_driver.execute_script.side_effect = [
            {"user_count": 1, "last_user_id": "old"},
            None,
            None,
        ] + [{"user_count": 1, "last_user_id": "old"}] * 20
        mock_driver.find_elements.return_value = [mock_button]

        ok, msg = manager.send_message("消息留在输入框")

        assert ok is False
        assert msg == "send_not_committed"

    def test_open_conversation_url_waits_for_chat_surface(self, manager, mock_driver):
        """配置了网页对话 URL 时，应先进入该对话再清空或发送。"""
        mock_driver.current_url = f"{UPSTREAM_AI_URL}/chat#old"
        mock_driver.current_window_handle = "handle-1"
        mock_driver.find_elements.side_effect = [[], [MagicMock()]]

        ok, info = manager.open_conversation_url(f"{UPSTREAM_AI_URL}/chat#550028", timeout=1)

        assert ok is True
        mock_driver.get.assert_called_once_with(f"{UPSTREAM_AI_URL}/chat#550028")
        assert info["conversation_url"] == f"{UPSTREAM_AI_URL}/chat#550028"

    def test_open_conversation_target_by_name_clicks_sidebar_item(self, manager, mock_driver):
        """浏览器 Profile 常规入口按网页左侧对话名称切换。"""
        mock_driver.current_url = f"{UPSTREAM_AI_URL}/chat#old"
        mock_driver.execute_script.side_effect = [
            True,
            "目标对话\n65\n刚刚",
            [],
        ]
        mock_driver.find_elements.return_value = [MagicMock()]

        ok, info = manager.open_conversation_target(conversation_name="目标对话", timeout=1)

        assert ok is True
        assert info["conversation_name"] == "目标对话"

    def test_switch_to_chat_tab_keeps_target_handle_when_chat_is_empty(self, manager, mock_driver):
        """目标对话为空但有输入框时，不能切回其它有消息的标签页。"""
        manager.target_handle = "target"
        mock_driver.current_window_handle = "target"
        mock_driver.find_elements.side_effect = [[], [MagicMock()]]

        manager.switch_to_chat_tab()

        mock_driver.switch_to.window.assert_not_called()

    # === 2. 状态检测测试 (is_busy) ===

    def test_is_busy_logic(self, manager, mock_driver):
        """
        🧪 验证状态检测逻辑
        这是自动展开功能的基础
        """
        # Case 1: 找到停止按钮 -> Busy
        stop_btn = MagicMock(); stop_btn.is_displayed.return_value = True
        mock_driver.find_elements.return_value = [stop_btn]
        assert manager.is_busy() is True

        # Case 2: 无按钮且内容不增长 -> Not Busy
        mock_driver.find_elements.return_value = []
        # Mock 掉 _is_content_growing 以隔离测试
        manager._is_content_growing = MagicMock(return_value=False)
        assert manager.is_busy() is False

    # === 3. 核心功能测试：manual_toggle_block ===

    def test_fingerprint_speed_optimization(self, manager, mock_driver):
        """
        🧪 性能测试：验证是否使用了 textContent
        目标：确保指纹匹配不会触发昂贵的 .text 渲染
        """
        msg = MagicMock()
        msg.get_attribute.return_value = "Target Code Snippet"
        mock_driver.find_elements.return_value = [msg]
        
        # 为了让函数跑通，Mock 掉后续的 JS 执行
        def side_effect(script, *args):
            if "monaco-editor" in script: return 2000 # 模拟高度
            if "scroll_parent" in script: return {"scroll_parent": {"tag": "DIV"}}
            return None
        mock_driver.execute_script.side_effect = side_effect
        manager._get_valid_code_blocks = MagicMock(return_value=[{'toggle': MagicMock()}])

        # 执行：查找指纹
        manager.manual_toggle_block(0, 0, 1, fingerprint="Target Code")
        
        # 验证：必须调用 get_attribute("textContent")
        msg.get_attribute.assert_called_with("textContent")

    def test_smart_height_polling(self, manager, mock_driver):
        """
        🧪 智能等待测试：验证轮询机制
        目标：确保代码会等待高度变化（展开动画完成）
        """
        mock_driver.find_elements.return_value = [MagicMock()]
        manager._get_valid_code_blocks = MagicMock(return_value=[{'toggle': MagicMock()}])
        
        # 模拟 execute_script 的返回值序列
        # 1. scrollIntoView (None)
        # 2. click (None)
        # 3. 测量高度 (500) -> 失败，继续轮询 (Loop 1)
        # 4. 测量高度 (500) -> 失败，继续轮询 (Loop 2)
        # 5. 测量高度 (2000) -> 成功 > 600，跳出循环 (Loop 3)
        # 6. 容器诊断 (dict)
        # ...
        side_effects = [
            None, # scrollIntoView
            None, # click
            500,  # Loop 1: 未展开
            500,  # Loop 2: 未展开
            2000, # Loop 3: 已展开
            {"scroll_parent": {"tag": "DIV"}}, # Audit
            None, # Scroll Step 1
            None, # Scroll Step 2
            None, # Scroll Step 3
            None  # Align End
        ]
        # 填充足够多的 None 防止 StopIteration
        mock_driver.execute_script.side_effect = side_effects + [None]*50
        
        manager.manual_toggle_block(0, 0, 1)
        
        # 验证 execute_script 被调用的次数
        # 包含 "monaco-editor" 的脚本即为测量高度的脚本
        measure_calls = [c for c in mock_driver.execute_script.call_args_list 
                         if "monaco-editor" in str(c)]
        
        # 应该至少调用了 3 次（前两次 500，第三次 2000）
        assert len(measure_calls) >= 3, "未执行足够次数的高度轮询"

    def test_lucide_state_detection(self, manager, mock_driver):
        """
        🧪 Lucide 选择器测试：验证新版 SVG 图标的状态检测
        """
        # 模拟一个包含 Lucide 展开 (minimize-2) 图标的按钮
        msg = MagicMock()
        mock_driver.find_elements.return_value = [msg]

        toggle_btn = MagicMock()
        # 新版 UI: 按钮内含 lucide-minimize-2 (展开状态)
        toggle_btn.get_attribute.return_value = '<svg class="lucide lucide-minimize-2"></svg>'

        manager._get_valid_code_blocks = MagicMock(return_value=[{'toggle': toggle_btn}])

        def side_effect(script, *args):
            if "monaco-editor" in script: return 2000
            if "scroll_parent" in script: return {"scroll_parent": {"tag": "DIV"}}
            return None
        mock_driver.execute_script.side_effect = side_effect

        # 如果是展开状态，应该先点收缩再点展开 (双击切换)
        manager.manual_toggle_block(0, 0, 1)

        # 验证: 展开状态应该触发两次 click (收缩→展开)
        click_calls = [c for c in mock_driver.execute_script.call_args_list
                       if "arguments[0].click()" in str(c)]
        assert len(click_calls) == 2, f"展开状态应触发2次click，实际{len(click_calls)}次"

    def test_lucide_collapsed_detection(self, manager, mock_driver):
        """
        🧪 Lucide 收缩状态测试：验证 lucide-maximize-2 被识别为收缩
        """
        msg = MagicMock()
        mock_driver.find_elements.return_value = [msg]

        toggle_btn = MagicMock()
        # 新版 UI: 按钮内含 lucide-maximize-2 (收缩状态)
        toggle_btn.get_attribute.return_value = '<svg class="lucide lucide-maximize-2"></svg>'

        manager._get_valid_code_blocks = MagicMock(return_value=[{'toggle': toggle_btn}])

        def side_effect(script, *args):
            if "monaco-editor" in script: return 2000
            if "scroll_parent" in script: return {"scroll_parent": {"tag": "DIV"}}
            return None
        mock_driver.execute_script.side_effect = side_effect

        manager.manual_toggle_block(0, 0, 1)

        # 收缩状态应该只点击1次
        click_calls = [c for c in mock_driver.execute_script.call_args_list
                       if "arguments[0].click()" in str(c)]
        assert len(click_calls) == 1, f"收缩状态应触发1次click，实际{len(click_calls)}次"

    def test_message_delete_requires_confirm(self, manager, mock_driver):
        """消息级删除默认受保护，避免误删网页对话。"""
        ok, msg = manager.click_ai_message_action("delete", message_id="6007369")
        assert ok is False
        assert msg == "delete_requires_confirm"
        mock_driver.execute_script.assert_not_called()

    def test_find_ai_message_copy_button_uses_message_toolbar_path(self, manager, mock_driver):
        """消息级复制按 hover toolbar 的 iconify path 定位，而不是代码块复制按钮。"""
        button = MagicMock()
        mock_driver.execute_script.return_value = button

        found = manager._find_ai_message_action_button("copy", message_id="6007369", timeout=0.1)

        assert found is button
        script = mock_driver.execute_script.call_args.args[0]
        assert "code-block-container" in script
        assert "M216 40v128h-48V88H88V40Z" in script
        assert mock_driver.execute_script.call_args.args[1] == "copy"
        assert mock_driver.execute_script.call_args.args[2] == "6007369"

    def test_wait_for_file_input_uses_fallback_selector(self, manager, mock_driver):
        """附件上传会等待 NaiveUI input 和通用 file input，而不是固定 sleep 后放弃。"""
        file_input = MagicMock()
        mock_driver.find_elements.side_effect = [[], [file_input]]

        found = manager._wait_for_file_input(timeout=0.3)

        assert found is file_input
        
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
