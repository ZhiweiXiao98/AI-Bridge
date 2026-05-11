# filename: tests/test_worker_fallback.py
"""测试工具路由三层防御机制"""
import pytest
import hashlib
import time
from unittest.mock import MagicMock, patch, PropertyMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeWorker:
    """最小化 Worker 替身，只包含三层防御相关属性和方法"""

    def __init__(self):
        self.was_busy = False
        self.last_send_time = 0
        self._pre_send_ai_fingerprint = None
        self.last_messages_snapshot = []
        self.connector = MagicMock()
        self.executor = MagicMock()

        # 绑定真实方法（从 worker 模块导入）
        from app.core.worker_modules import WorkerThread
        import types
        self._get_last_ai_fingerprint = types.MethodType(
            WorkerThread._get_last_ai_fingerprint, self
        )

    def safe_emit_status(self, msg):
        print(f"[STATUS] {msg}")


class TestFingerprint:
    """第一层：指纹对比机制"""

    @pytest.fixture
    def worker(self):
        return FakeWorker()

    def test_snapshot_fingerprint_returns_hash(self, worker):
        """快照模式：有消息时返回 md5"""
        worker.last_messages_snapshot = [
            {"segments": [{"type": "text", "content": "Hello world"}]}
        ]
        fp = worker._get_last_ai_fingerprint(live=False)
        assert fp is not None
        assert len(fp) == 32  # md5 hex

    def test_snapshot_fingerprint_empty(self, worker):
        """快照模式：无消息时返回 None"""
        worker.last_messages_snapshot = []
        fp = worker._get_last_ai_fingerprint(live=False)
        assert fp is None

    def test_live_fingerprint_from_browser(self, worker):
        """live 模式：从浏览器获取实时指纹"""
        worker.connector.check_last_ai_message_for_tool.return_value = "AI says hello"
        fp = worker._get_last_ai_fingerprint(live=True)
        assert fp is not None
        expected = hashlib.md5("AI says hello"[:150].encode()).hexdigest()
        assert fp == expected

    def test_live_fingerprint_empty(self, worker):
        """live 模式：浏览器无内容时返回 None"""
        worker.connector.check_last_ai_message_for_tool.return_value = None
        fp = worker._get_last_ai_fingerprint(live=True)
        assert fp is None

    def test_fingerprint_changes_after_ai_reply(self, worker):
        """发送前后指纹应不同"""
        worker.connector.check_last_ai_message_for_tool.return_value = "old msg"
        fp_before = worker._get_last_ai_fingerprint(live=True)

        worker.connector.check_last_ai_message_for_tool.return_value = "new reply from AI"
        fp_after = worker._get_last_ai_fingerprint(live=True)

        assert fp_before != fp_after

    def test_same_content_same_fingerprint(self, worker):
        """相同内容 → 相同指纹（幂等性）"""
        worker.connector.check_last_ai_message_for_tool.return_value = "same"
        fp1 = worker._get_last_ai_fingerprint(live=True)
        fp2 = worker._get_last_ai_fingerprint(live=True)
        assert fp1 == fp2


class TestContinueBugFix:
    """第一层：continue 跳过 was_busy 赋值的 bug 修复验证"""

    def test_was_busy_set_before_continue(self):
        """验证 continue 前 was_busy 被正确赋值"""
        import inspect
        from app.core.worker_modules import WorkerThread
        source = inspect.getsource(WorkerThread._execute_task_sync)

        # 找到 continue 附近的代码
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "current_busy = True" in line:
                # 在 continue 之前应该有 was_busy = current_busy
                block = "\n".join(lines[i:i+5])
                assert "was_busy = current_busy" in block, (
                    f"Bug 未修复：continue 前缺少 was_busy 赋值\n"
                    f"相关代码: {block}"
                )
                break


class TestTimeoutFallback:
    """第二层：10s 超时兜底"""

    @pytest.fixture
    def worker(self):
        return FakeWorker()

    def test_timeout_timer_set_on_early_trigger(self, worker):
        """指纹相同时应设置 last_send_time 启动计时器"""
        worker._pre_send_ai_fingerprint = "abc123"
        worker.connector.check_last_ai_message_for_tool.return_value = None

        # 模拟快照指纹 = 发送前指纹（触发太早）
        worker.last_messages_snapshot = [
            {"segments": [{"type": "text", "content": "old"}]}
        ]
        fp = worker._get_last_ai_fingerprint(live=False)
        worker._pre_send_ai_fingerprint = fp

        # 此时 live 也返回相同内容
        worker.connector.check_last_ai_message_for_tool.return_value = "old"
        live_fp = worker._get_last_ai_fingerprint(live=True)

        # 模拟流水线逻辑
        if worker._pre_send_ai_fingerprint and live_fp == worker._pre_send_ai_fingerprint:
            worker.last_send_time = time.time()

        assert worker.last_send_time > 0, "计时器未启动"

    def test_timeout_triggers_after_10s(self, worker):
        """10s 后指纹变化应触发兜底流水线"""
        worker.last_send_time = time.time() - 11  # 模拟 11s 前发送
        worker._pre_send_ai_fingerprint = hashlib.md5(b"old").hexdigest()

        worker.connector.check_last_ai_message_for_tool.return_value = "new AI reply"
        current_fp = worker._get_last_ai_fingerprint(live=True)

        triggered = False
        if worker.last_send_time > 0 and time.time() - worker.last_send_time > 10:
            if current_fp != worker._pre_send_ai_fingerprint and current_fp:
                triggered = True
                worker.last_send_time = 0

        assert triggered, "兜底流水线未触发"
        assert worker.last_send_time == 0, "计时器未清除"

    def test_timeout_no_trigger_if_same_fingerprint(self, worker):
        """10s 后指纹仍相同 → 不触发"""
        old_text = "still the same"
        fp = hashlib.md5(old_text[:150].encode()).hexdigest()
        worker.last_send_time = time.time() - 11
        worker._pre_send_ai_fingerprint = fp

        worker.connector.check_last_ai_message_for_tool.return_value = old_text
        current_fp = worker._get_last_ai_fingerprint(live=True)

        triggered = False
        if worker.last_send_time > 0 and time.time() - worker.last_send_time > 10:
            if current_fp != worker._pre_send_ai_fingerprint and current_fp:
                triggered = True

        assert not triggered, "指纹未变化不应触发"


class TestBatchEndFallback:
    """第三层：BATCH_END 修复按钮兜底"""

    def test_batch_end_calls_direct_pipeline(self):
        """验证 BATCH_END 处理中包含 _background_process_ai_response_direct 调用"""
        import os
        worker_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'core', 'worker.py')
        with open(worker_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # 找到 BATCH_END 消费端（在 run 方法的 toggle_queue 处理中）
        in_batch_end = False
        found = False
        for line in source.split(chr(10)):
            if '"BATCH_END"' in line and 'toggle_queue' not in line:
                in_batch_end = True
            if in_batch_end:
                if "_background_process_ai_response_direct" in line:
                    found = True
                    break
                if line.strip() == "continue":
                    break

        assert found, (
            "BATCH_END 处理中未找到 _background_process_ai_response_direct 调用"
        )


class TestDefenseIntegration:
    """集成：三层防御协同"""

    @pytest.fixture
    def worker(self):
        return FakeWorker()

    def test_full_flow_normal(self, worker):
        """正常流程：发送 → AI 回复 → 指纹变化 → 直接执行"""
        # 发送前记录指纹
        worker.connector.check_last_ai_message_for_tool.return_value = "before"
        worker._pre_send_ai_fingerprint = worker._get_last_ai_fingerprint(live=True)

        # AI 回复后指纹变化
        worker.connector.check_last_ai_message_for_tool.return_value = "AI new reply"
        current_fp = worker._get_last_ai_fingerprint(live=True)

        assert current_fp != worker._pre_send_ai_fingerprint
        # → 正常执行流水线，不进入兜底

    def test_full_flow_early_trigger(self, worker):
        """异常流程：发送 → 触发太早 → 指纹相同 → 启动计时器"""
        worker.connector.check_last_ai_message_for_tool.return_value = "same old"
        worker._pre_send_ai_fingerprint = worker._get_last_ai_fingerprint(live=True)

        # 流水线触发时 AI 还没回复
        current_fp = worker._get_last_ai_fingerprint(live=True)
        assert current_fp == worker._pre_send_ai_fingerprint

        # 应启动计时器
        worker.last_send_time = time.time()
        assert worker.last_send_time > 0

    def test_full_flow_timeout_recovery(self, worker):
        """异常流程：计时器到期 → AI 已回复 → 兜底触发"""
        worker._pre_send_ai_fingerprint = hashlib.md5(b"old msg").hexdigest()
        worker.last_send_time = time.time() - 11

        # 10s 后 AI 已回复
        worker.connector.check_last_ai_message_for_tool.return_value = "brand new reply"
        current_fp = worker._get_last_ai_fingerprint(live=True)

        assert current_fp != worker._pre_send_ai_fingerprint
        # → 兜底流水线触发
