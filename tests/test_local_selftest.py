"""仅验证自检控制逻辑；不启动应用、模型、浏览器或网络。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.local_selftest import wait_for


def test_early_runtime_failure_is_not_hidden_as_approval_timeout():
    app = SimpleNamespace(processEvents=Mock())
    predicate = Mock(return_value=False)
    with pytest.raises(RuntimeError, match="sidecar exited"):
        wait_for(app, predicate, "approval", timeout=30, failure_reason=lambda: "sidecar exited")
    app.processEvents.assert_called_once()
    predicate.assert_not_called()


def test_success_without_failure_reason_preserves_existing_behavior():
    app = SimpleNamespace(processEvents=Mock())
    wait_for(app, lambda: True, "ready", failure_reason=lambda: None)
    app.processEvents.assert_called_once()


def test_timeout_keeps_its_safe_stage_diagnostic():
    app = SimpleNamespace(processEvents=Mock())
    with pytest.raises(RuntimeError, match="browser not started"):
        wait_for(app, lambda: False, "browser ready", timeout=0,
                 timeout_detail=lambda: "browser not started")
