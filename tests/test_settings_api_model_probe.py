import os
import sys
from copy import deepcopy

import pytest

pytestmark = pytest.mark.ui

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", reason="PySide6 unavailable", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from app.core.api_mode_config import APIModeConfigManager
from app.ui.components.settings.settings_api import SettingsApiSection


def _app():
    return QApplication.instance() or QApplication(sys.argv)


def test_model_probe_updates_combo_and_persists_options(monkeypatch):
    _app()
    saved = {}
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: saved.update(deepcopy(data))))
    cfg = APIModeConfigManager._normalize({
        "active_profile": "mimo",
        "profiles": {
            "mimo": {
                "name": "mimo",
                "kind": "api",
                "provider": "mimo",
                "base_url": "https://api.xiaomimimo.com/v1",
                "api_key": "sk-test",
                "model": "mimo-v2.5-pro",
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "mimo"},
    })
    section = SettingsApiSection(config={}, api_config=cfg)
    models = ["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"]

    section.on_api_models_probe_result({
        "ok": True,
        "source": "models_endpoint_filtered",
        "endpoint_ok": True,
        "raw_model_count": 10,
        "models": models,
    })

    assert section.api_model_combo.count() == len(models)
    assert [section.api_model_combo.itemText(i) for i in range(section.api_model_combo.count())] == models
    assert section.api_model_combo.currentText() == "mimo-v2.5-pro"
    assert section.api_profile["available_models"]["models"] == models
    assert saved["profiles"]["mimo"]["available_models"]["models"] == models
    assert "已过滤到 5 个聊天模型并更新下拉框" in section.api_models_probe_lbl.text()


def test_refresh_provider_ui_prefers_persisted_probe_models(monkeypatch):
    _app()
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: None))
    cfg = APIModeConfigManager._normalize({
        "active_profile": "mimo",
        "profiles": {
            "mimo": {
                "name": "mimo",
                "kind": "api",
                "provider": "mimo",
                "base_url": "https://api.xiaomimimo.com/v1",
                "model": "mimo-v2.5",
                "available_models": {
                    "provider": "mimo",
                    "models": ["mimo-v2.5-pro", "mimo-v2.5"],
                    "source": "models_endpoint_filtered",
                },
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "mimo"},
    })
    section = SettingsApiSection(config={}, api_config=cfg)

    assert section.api_model_combo.count() == 2
    assert [section.api_model_combo.itemText(i) for i in range(section.api_model_combo.count())] == [
        "mimo-v2.5-pro",
        "mimo-v2.5",
    ]
    assert section.api_model_combo.currentText() == "mimo-v2.5"


def test_mimo_settings_reasoning_keeps_switch_and_hides_effort(monkeypatch):
    _app()
    monkeypatch.setattr(APIModeConfigManager, "save", staticmethod(lambda data: None))
    cfg = APIModeConfigManager._normalize({
        "active_profile": "mimo",
        "profiles": {
            "mimo": {
                "name": "mimo",
                "kind": "api",
                "provider": "mimo",
                "base_url": "https://api.xiaomimimo.com/v1",
                "model": "mimo-v2.5-pro",
                "reasoning": {"enabled": True, "effort": "high"},
            }
        },
        "api_mode_usage": {"type": "profile", "ref": "mimo"},
    })

    section = SettingsApiSection(config={}, api_config=cfg)
    api_config = section.collect_api_config()

    assert section.api_reasoning_cb.isChecked() is True
    assert section.api_reasoning_effort_field.isHidden() is True
    assert api_config["profiles"]["mimo"]["reasoning"] == {"enabled": True, "effort": "medium"}
