# filename: tests/test_state_service.py
import pytest
import os
import json
import time
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.services.state_service import StateService

class TestStateService:
    """
    🕰️ 状态管理测试 (逻辑校准版)
    """

    @pytest.fixture
    def state_svc(self, tmp_path):
        state_file = tmp_path / "ai_bridge_state.json"
        with patch("app.core.services.state_service.STATE_FILE", str(state_file)):
            svc = StateService()
            yield svc

    def test_initial_state(self, state_svc):
        chat_id = "chat_test_001"
        session = state_svc.get_session(chat_id)
        assert session.user_turn_count == 0
        assert session.snapshot_bubble == 0

    def test_update_user_turn(self, state_svc):
        chat_id = "chat_test_002"
        state_svc.update_user_turn(chat_id, 5, ["msg"])
        session = state_svc.get_session(chat_id)
        assert session.user_turn_count == 5

    def test_manual_correction(self, state_svc):
        """验证手动校准逻辑"""
        chat_id = "chat_test_003"
        # [Fix] 逻辑确认：set_manual_bubble_count(100) -> user_turn_count = 50 (100 // 2)
        state_svc.set_manual_bubble_count(chat_id, 100)
        session = state_svc.get_session(chat_id)
        assert session.user_turn_count == 50

    def test_snapshot_logic(self, state_svc):
        chat_id = "chat_test_004"
        state_svc.set_snapshot(chat_id, 50)
        session = state_svc.get_session(chat_id)
        assert session.snapshot_bubble == 50

    def test_should_emit_sync(self, state_svc):
        """验证同步触发与防抖逻辑"""
        chat_id = "chat_test_005"
        
        # 初始状态
        # [Fix] should_emit_sync 返回 (needs_sync, snapshot_bubble)
        
        # 第一次调用 (0 -> 10): 应该同步
        sync, snap = state_svc.should_emit_sync(chat_id, 10)
        assert sync is True
        
        # 第二次调用 (10 -> 10): 值未变且时间极短，不应同步 (防抖)
        sync, snap = state_svc.should_emit_sync(chat_id, 10)
        assert sync is False
        
        # 第三次调用 (10 -> 11): 值变化，应该同步
        sync, snap = state_svc.should_emit_sync(chat_id, 11)
        assert sync is True
        
        # 第四次调用 (11 -> 11, force=True): 强制同步
        sync, snap = state_svc.should_emit_sync(chat_id, 11, force=True)
        assert sync is True

    def test_persistence(self, state_svc):
        chat_id = "chat_test_persistence"
        state_svc.update_user_turn(chat_id, 99, ["data"])
        
        new_svc = StateService()
        session = new_svc.get_session(chat_id)
        assert session.user_turn_count == 99

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
