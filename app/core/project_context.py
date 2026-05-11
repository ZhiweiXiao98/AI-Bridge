import os
import json
import hashlib
from typing import List

from PySide6.QtCore import QObject, Signal

from app.core.app_constants import APP_ROOT
from app.core.logging import get_logger

logger = get_logger("app.core.project_context", side="core")


class ProjectContext(QObject):
    about_to_switch = Signal(str, str)
    project_switched = Signal(str, str)

    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_root = APP_ROOT
        self.project_root = APP_ROOT
        self.project_name = os.path.basename(APP_ROOT)
        self._recent_projects: List[dict] = []
        self._projects_file = os.path.join(APP_ROOT, "projects.json")

    @classmethod
    def get(cls) -> "ProjectContext":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def initialize(cls) -> "ProjectContext":
        return cls.get()

    def get_project_root(self) -> str:
        return self.project_root

    def get_knowledge_db_path(self) -> str:
        project_hash = self._compute_project_hash(self.project_root)
        return os.path.join(self.app_root, "knowledge_bases", project_hash)

    def get_project_hash(self) -> str:
        return self._compute_project_hash(self.project_root)

    def switch_to(self, new_path: str) -> bool:
        new_path = self._normalize_path(new_path)

        if not os.path.isdir(new_path):
            logger.error(f"[项目切换] 阶段1校验失败: 路径不存在 {new_path}")
            return False
        if new_path == self._normalize_path(self.project_root):
            logger.debug("[项目切换] 目标路径与当前路径相同，跳过")
            return True

        new_db_path = self._compute_db_path(new_path)
        old_project = self.project_root
        logger.info(f"[项目切换] 开始: {old_project} → {new_path} (db={new_db_path})")

        logger.info("[项目切换] 阶段2: 发射 about_to_switch 信号（同步阻塞清理）")
        self.about_to_switch.emit(new_path, new_db_path)

        logger.info("[项目切换] 阶段3: 切换路径 + chdir")
        self.project_root = new_path
        self.project_name = os.path.basename(new_path)
        os.chdir(new_path)

        logger.info("[项目切换] 阶段4: 发射 project_switched 信号（异步状态刷新）")
        self.project_switched.emit(new_path, new_db_path)

        logger.info("[项目切换] 阶段5: 持久化最近项目列表")
        self._add_recent_project(new_path)
        self._save_recent_projects()

        logger.info(f"[项目切换] 完成: {self.project_name} ({new_path})")
        return True

    def restore_last_project(self):
        if not os.path.exists(self._projects_file):
            return
        try:
            with open(self._projects_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._recent_projects = data.get("recent", [])
            last = data.get("last_project")
            if last and os.path.isdir(last) and self._normalize_path(last) != self._normalize_path(self.app_root):
                self.switch_to(last)
        except Exception as e:
            logger.warning(f"恢复上次项目失败: {e}")

    @staticmethod
    def _normalize_path(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def _compute_project_hash(self, path: str) -> str:
        normalized = self._normalize_path(path)
        md5 = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
        name = os.path.basename(path).replace(" ", "_")
        return f"{name}_{md5}"

    def _compute_db_path(self, project_root: str) -> str:
        project_hash = self._compute_project_hash(project_root)
        return os.path.join(self.app_root, "knowledge_bases", project_hash)

    def _add_recent_project(self, path: str):
        normalized = self._normalize_path(path)
        self._recent_projects = [
            item for item in self._recent_projects
            if self._normalize_path(item.get("path", "")) != normalized
        ]
        self._recent_projects.insert(0, {
            "path": path,
            "name": os.path.basename(path),
        })
        self._recent_projects = self._recent_projects[:10]

    def _save_recent_projects(self):
        data = {
            "last_project": self.project_root,
            "recent": self._recent_projects,
        }
        try:
            with open(self._projects_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存项目列表失败: {e}")

    def get_recent_projects(self) -> List[dict]:
        return [
            item for item in self._recent_projects
            if os.path.isdir(item.get("path", ""))
        ]
