# filename: tests/test_interaction_core.py
import pytest
from unittest.mock import MagicMock, call, patch
import sys
import os

# 路径注入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.driver.interaction import InteractionManager, STATE_COLLAPSED, LUCIDE_COLLAPSED, LUCIDE_EXPANDED

class TestInteractionCore:
    """
    🛡️ 交互核心逻辑测试 (V5: 覆盖定向修复与中断机制)
    """

    @pytest.fixture
    def mock_driver(self):
        driver = MagicMock()
        return driver

    @pytest.fixture
    def manager(self, mock_driver):
        return InteractionManager(mock_driver)

    def test_fast_expand_logic(self, manager):
        """测试: 全局快速展开"""
        manager.driver.execute_script.return_value = {"found": 10, "clicked": 5, "skipped": 5}
        count = manager.fast_expand_all()
        
        manager.driver.execute_script.assert_called_once()
        args = manager.driver.execute_script.call_args[0][0]
        # 旧版 FontAwesome 选择器
        assert STATE_COLLAPSED in args
        # 新版 Lucide 选择器
        assert LUCIDE_COLLAPSED in args
        assert count == 5

    @patch('time.sleep')
    def test_scroll_traverse_variable_speed(self, mock_sleep, manager):
        """测试: 变速巡航 (参数: 0.05 / 0.01)"""
        manager.driver.execute_script.side_effect = [
            3000, # total_height
            False, {'total': 3000, 'top': 600}, # Loop 1: Normal
            True,  {'total': 3000, 'top': 750}, # Loop 2: Code
            False, None # End
        ]
        
        with patch.object(manager, 'fast_expand_all', return_value=0):
            manager.scroll_traverse()
        
        calls = mock_sleep.call_args_list
        assert call(0.05) in calls # Slow Wait
        assert call(0.01) in calls # Fast Wait
        print("\n✅ 极速微步逻辑验证通过")

    def test_scan_and_fix_last_message(self, manager):
        """测试: 定向修复最后一条消息 (新功能)"""
        # 模拟 JS 执行序列:
        # 1. expand_last -> 返回点击了 2 个按钮
        # 2. measure -> 返回需要滚动 (start=100, end=400)
        # 3. scrollTo(start)
        # 4. scrollTo(step 1) -> 100+400=500 > 400, 循环结束
        # 5. scrollTo(bottom)

        manager.driver.execute_script.side_effect = [
            2, # expand result
            {'start': 100, 'end': 400, 'need_scroll': True}, # measure result
            None, # jump start
            None, # scroll step 1
            None  # align bottom
        ]

        manager.scan_and_fix_last_message()

        # 验证调用次数: expand(1) + measure(1) + scrollTo_start(1) + scroll_step(1) + scrollTo_bottom(1) = 5
        assert manager.driver.execute_script.call_count == 5
        print("\n✅ 定向修复逻辑验证通过")

    def test_scroll_traverse_interrupt(self, manager):
        """测试: 滚动中断机制 (新功能)"""
        # 模拟 total_height 获取成功
        manager.driver.execute_script.return_value = 3000
        
        # 定义一个模拟的中断信号 (返回 True 表示有新任务)
        stop_signal = MagicMock(return_value=True)
        
        manager.scroll_traverse(interrupt_check=stop_signal)
        
        # 验证:
        # 1. 获取高度 (init) 执行了
        # 2. 循环内第一件事是检查中断，既然中断为 True，就不应该执行 js_check_view
        # 所以 execute_script 应该只被调用 1 次 (js_reset)
        assert manager.driver.execute_script.call_count == 1
        
        # 3. 中断检查函数应该被调用
        assert stop_signal.called
        print("\n✅ 滚动中断机制验证通过 (立即刹车)")

    def test_fast_expand_lucide_selectors(self, manager):
        """测试: 快速展开的 JS 注入包含 Lucide 选择器"""
        manager.driver.execute_script.return_value = {"found": 3, "clicked": 3, "skipped": 0}
        count = manager.fast_expand_all()

        js_code = manager.driver.execute_script.call_args[0][0]
        # 确保新版 Lucide class 名出现在注入的 JS 中
        assert "lucide-maximize-2" in js_code, "JS 中缺少 lucide-maximize-2 选择器"
        # 同时保留旧版 FontAwesome 兼容
        assert "down-left-and-up-right-to-center" in js_code, "JS 中缺少旧版 FontAwesome 选择器"
        assert count == 3
        print("\n✅ Lucide 选择器注入验证通过")

    def test_scan_fix_lucide_selectors(self, manager):
        """测试: 定向修复的 JS 注入包含 Lucide 选择器"""
        manager.driver.execute_script.side_effect = [
            1,  # expand result (找到1个收缩块)
            {'need_scroll': False},  # measure result
        ]

        manager.scan_and_fix_last_message()

        # 第一个 execute_script 调用就是 expand JS
        js_code = manager.driver.execute_script.call_args_list[0][0][0]
        assert "lucide-maximize-2" in js_code, "scan_and_fix JS 中缺少 lucide-maximize-2"
        assert "down-left-and-up-right-to-center" in js_code, "scan_and_fix JS 中缺少旧版选择器"
        print("\n✅ 定向修复 Lucide 选择器验证通过")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])