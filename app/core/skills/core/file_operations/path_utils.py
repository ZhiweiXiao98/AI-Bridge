import os
from pathlib import Path

IGNORE_MARKERS = {
    ".git", "__pycache__", "venv", ".venv", "node_modules",
    "update_cache", "htmlcov", ".pytest_cache", "_knowledge_base"
}


def resolve_legacy_path(path: str, path_redirects: dict) -> str:
    clean_path = str(path or "").replace(chr(92), "/")
    if clean_path in path_redirects:
        return path_redirects[clean_path]
    if clean_path.endswith("worker.py") and "app/core" not in clean_path:
        return "app/core/worker.py"
    return str(path or "")


def sanitize_path(path: str) -> str:
    return str(path or "").replace(chr(34), "").replace(chr(39), "").strip()


def is_path_allowed(path: str, file_service=None) -> bool:
    if not path:
        return False
    if file_service is not None:
        try:
            return bool(file_service.is_safe_path(path))
        except Exception:
            return False
    return True


def ensure_parent_dir(path: str) -> None:
    parent = Path(path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def path_exists(path: str) -> bool:
    return os.path.exists(path)


def make_atomic_temp_path(path: str) -> str:
    return path + '.tmp'


def atomic_write_text(path: str, content: str, encoding: str = 'utf-8') -> None:
    tmp_path = make_atomic_temp_path(path)
    ensure_parent_dir(tmp_path)
    try:
        with open(tmp_path, 'w', encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
