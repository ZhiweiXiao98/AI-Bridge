import logging
import os
import json
from app.core.logging import get_logger
from app.core.app_constants import APP_ROOT, CHROME_PORT

logger = get_logger("app.core.config", side="core")

CONFIG_PATH = os.path.join(APP_ROOT, "config.json")

DEFAULT_CONFIG = {
    "export_code_path": "export/code",
    "export_image_path": "export/images",
    "chrome_port": CHROME_PORT,
    "chromedriver_path": "",
    "auto_export": True,
    "fix_limit": 5,
    "ignored_files": "",
    "chat_message_load_turns": 20,
    "chat_message_load_step_turns": 10,
    "knowledge_reindex_enabled": True,
    "knowledge_reindex_after_git_push": True,
    "knowledge_reindex_target_exts": ".py\n.md\n.txt\n.json\n.yaml\n.yml\n.toml\n.ini\n.cfg\n.cs",
    "knowledge_reindex_skip_dirs": ".git\n__pycache__\n.venv\nvenv\nnode_modules\n_docker_env\n_knowledge_base\nbackup\ndist\nhtmlcov\nexport\nAI_Bridge_Client_Dist\nChrome_143_Clean_Data\ntemp_uploads\nimages1",
    "knowledge_reindex_include_prefixes": "app/\ntools/\ntests/\ndocs/\nrhino/\nrhino_plugin/\nserver.py\nstart_client.py\nstart_server.py\nboot_remote.py\nREADME.md\nAI_README.md",
    "knowledge_reindex_forced_delete_prefixes": "AI_Bridge_Client_Dist/\nAI_Bridge_Client_Dist\\",
    "knowledge_reindex_only_non_empty": True,
    "knowledge_reindex_delete_stale": True,
    "api_mode_usage": {
        "type": "profile",
        "ref": "default"
    },
    "daemon": {
        "enabled": True,
        "core": {
            "type": "profile",
            "ref": "default"
        },
        "lite": {
            "type": "profile",
            "ref": "default"
        },
        "tasks": {
            "suggest": {
                "enabled": True,
                "max_suggestions": 3
            }
        }
    }
}

class ConfigManager:
    @staticmethod
    def load():
        if not os.path.exists(CONFIG_PATH):
            ConfigManager.save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(data or {})
                return merged
        except Exception:
            return DEFAULT_CONFIG.copy()

    @staticmethod
    def save(config_data):
        os.makedirs(config_data.get("export_code_path", "export/code"), exist_ok=True)
        os.makedirs(config_data.get("export_image_path", "export/images"), exist_ok=True)

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)

config = ConfigManager.load()
