import os

from app.core.project_context import ProjectContext


def project_path(path: str) -> str:
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(ProjectContext.get().get_project_root(), path))


def project_config_path(config: dict, key: str, default: str) -> str:
    return project_path(config.get(key, default))
