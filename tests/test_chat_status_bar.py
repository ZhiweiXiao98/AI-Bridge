import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", reason="PySide6 unavailable", exc_type=ImportError)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.core.api_mode_config import APIModeConfigManager
from app.ui.pages.chat.api_session_list import APISessionList
from app.ui.pages.chat.status_bar import ApiModelUsageBar, BrowserProjectBar


def _app():
    return QApplication.instance() or QApplication(sys.argv)


def test_api_model_usage_bar_exposes_conversation_model_and_reasoning(monkeypatch):
    _app()
    cfg = APIModeConfigManager._normalize({
        "active_profile": "api",
        "profiles": {
            "api": {
                "name": "API",
                "kind": "api",
                "provider": "openai_compatible",
                "model": "o3-mini",
                "base_url": "https://api.openai.com/v1",
                "supports_reasoning": True,
                "reasoning": {"enabled": False, "effort": "medium"},
                "available_models": {
                    "models": ["o3-mini", "o3", "gpt-4o"],
                    "source": "models_endpoint_filtered",
                },
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "api"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))

    bar = ApiModelUsageBar()
    emitted = []
    bar.usage_changed.connect(lambda usage: emitted.append(usage))

    bar.set_conversation("conv_1", {
        "type": "profile",
        "ref": "api",
        "model": "o3",
        "reasoning": {"enabled": True, "effort": "high"},
    })

    assert bar.model_combo.currentData() == "o3"
    assert [bar.model_combo.itemData(i) for i in range(bar.model_combo.count())] == [
        "",
        "o3-mini",
        "o3",
        "gpt-4o",
    ]
    assert bar.reasoning_check.isChecked() is True
    assert bar.effort_combo.currentData() == "high"

    bar.model_combo.setCurrentIndex(bar.model_combo.findData("o3-mini"))

    assert emitted[-1]["model"] == "o3-mini"
    assert emitted[-1]["reasoning"] == {"enabled": True, "effort": "high"}


def test_api_model_usage_bar_hides_effort_for_mimo_switch_reasoning(monkeypatch):
    _app()
    cfg = APIModeConfigManager._normalize({
        "active_profile": "mimo",
        "profiles": {
            "mimo": {
                "name": "MiMo",
                "kind": "api",
                "provider": "mimo",
                "model": "mimo-v2.5-pro",
                "base_url": "https://api.xiaomimimo.com/v1",
                "reasoning": {"enabled": False, "effort": "medium"},
                "available_models": {
                    "models": ["mimo-v2.5-pro", "mimo-v2.5"],
                    "source": "models_endpoint_filtered",
                },
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "mimo"},
    })
    monkeypatch.setattr(APIModeConfigManager, "load", staticmethod(lambda: cfg))

    bar = ApiModelUsageBar()
    bar.set_conversation("conv_1", {
        "type": "profile",
        "ref": "mimo",
        "model": "mimo-v2.5",
        "reasoning": {"enabled": True, "effort": "high"},
    })

    assert bar.model_combo.currentData() == "mimo-v2.5"
    assert bar.reasoning_check.isChecked() is True
    assert bar.effort_combo.isHidden() is True
    assert bar._current_usage_from_controls()["reasoning"] == {"enabled": True, "effort": "medium"}


def test_api_session_list_groups_conversations_by_project():
    _app()
    widget = APISessionList()

    widget.update_sessions([
        {
            "id": "conv_a",
            "title": "A",
            "date": "06-20 10:00",
            "project_name": "Project A",
            "project_root": "D:/ProjectA",
        },
        {
            "id": "conv_b",
            "title": "B",
            "date": "06-20 11:00",
            "project_name": "Project B",
            "project_root": "D:/ProjectB",
        },
    ])

    assert widget.status_label.text() == "2 个对话 · 2 个项目"
    assert widget.list_widget.count() == 4
    assert widget.list_widget.item(0).data(Qt.ItemDataRole.UserRole) == ""
    assert widget.list_widget.item(1).data(Qt.ItemDataRole.UserRole) == "conv_a"
    assert widget.list_widget.item(2).data(Qt.ItemDataRole.UserRole) == ""
    assert widget.list_widget.item(3).data(Qt.ItemDataRole.UserRole) == "conv_b"


def test_bottom_project_bar_switches_project_and_emits_signal(tmp_path):
    _app()

    class FakeProjectContext:
        def __init__(self):
            self.project_name = "Before"
            self.root = "D:/Before"
            self.calls = []

        def get_project_root(self):
            return self.root

        def get_recent_projects(self):
            return []

        def switch_to(self, path):
            self.calls.append(path)
            self.root = path
            self.project_name = os.path.basename(path)
            return True

    fake_ctx = FakeProjectContext()
    bar = BrowserProjectBar()
    bar._project_ctx = fake_ctx
    emitted = []
    logs = []
    bar.project_changed.connect(lambda path: emitted.append(path))
    bar.log_message.connect(lambda text: logs.append(text))

    bar._switch_project_path(str(tmp_path))

    assert fake_ctx.calls == [str(tmp_path)]
    assert emitted == [str(tmp_path)]
    assert "项目已切换" in logs[-1]
    assert bar.project_value_label.text() == f"{tmp_path.name} ▾"
