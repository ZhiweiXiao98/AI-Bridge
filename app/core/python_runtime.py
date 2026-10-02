"""Resolve development-tool Python without ever re-running a frozen app as Python.

The bundled interpreter runs AI-Bridge itself.  Project scripts, pip and pytest
need a separate interpreter selected in the execution-environment menu, via
AI_BRIDGE_PYTHON, or provided by a project's virtual environment.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


class PythonRuntimeUnavailable(RuntimeError):
    """A project needs an external Python interpreter before running tools."""


class FrozenApplicationWriteError(RuntimeError):
    """Source updates cannot replace files inside an installed application."""


def is_frozen_application() -> bool:
    return bool(getattr(sys, "frozen", False))


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def frozen_bundle_roots() -> tuple[Path, ...]:
    if not is_frozen_application():
        return ()
    executable = Path(sys.executable).resolve()
    roots = [executable.parent]
    for parent in executable.parents:
        if parent.suffix.lower() == ".app":
            roots.append(parent)
            break
    extracted = getattr(sys, "_MEIPASS", None)
    if extracted:
        roots.append(Path(extracted))
    return tuple(roots)


def ensure_project_write_allowed(project_root, destination=None) -> None:
    """Protect installed bundles, including symlinked targets, from source OTA."""
    root = Path(project_root).resolve()
    target = Path(destination).resolve() if destination is not None else root
    if not _within(target, root):
        raise FrozenApplicationWriteError("更新目标超出当前项目目录，已取消写入。")
    if any(_within(target, bundle) for bundle in frozen_bundle_roots()):
        raise FrozenApplicationWriteError(
            "不能用源码更新覆盖已打包的应用。请下载并替换完整应用；"
            "要修改项目代码，请先切换到应用安装目录之外的项目。"
        )


def _is_app_executable(path: Path) -> bool:
    executable = Path(sys.executable)
    try:
        if path.samefile(executable):
            return True
    except OSError:
        pass
    return path.resolve() == executable.resolve()


def _validate_python(candidate, project_root: Path, purpose: str) -> str:
    candidate = os.path.expandvars(os.path.expanduser(str(candidate).strip()))
    path = Path(candidate)
    if not path.is_absolute():
        if path.parent != Path("."):
            path = project_root / path
        else:
            path = Path(shutil.which(candidate) or str(project_root / path))
    if is_frozen_application() and (
        _is_app_executable(path)
        or any(_within(path, bundle) for bundle in frozen_bundle_roots())
    ):
        raise PythonRuntimeUnavailable(
            f"{purpose}不能使用 AI-Bridge 应用本身作为 Python。"
            "请在聊天页执行环境菜单中选择外部 Python，"
            "或设置 AI_BRIDGE_PYTHON 为外部解释器的完整路径。"
        )
    if not path.is_file() or (os.name != "nt" and not os.access(path, os.X_OK)):
        raise PythonRuntimeUnavailable(
            f"{purpose}找不到可执行的外部 Python：{path}。"
            "请重新选择 Python 解释器，或修正 AI_BRIDGE_PYTHON。"
        )
    # Preserve a venv's symlink path: resolving it would silently lose the venv.
    return os.path.abspath(path)


def resolve_project_python(project_root=None, configured_python=None,
                           purpose="运行 Python 工具") -> str:
    """Return a Python executable, or an actionable error; never probe the app.

    Explicit configuration is authoritative (an invalid path must not silently
    install packages into some other environment). Source mode retains its
    historical interpreter unless an external interpreter was selected.
    """
    root = Path(project_root or os.getcwd())
    configured = str(configured_python or os.environ.get("AI_BRIDGE_PYTHON", "")).strip()
    if configured:
        return _validate_python(configured, root, purpose)
    if not is_frozen_application():
        return sys.executable
    for directory in (".venv", "venv", "env", ".env"):
        for relative in ("Scripts/python.exe", "bin/python3", "bin/python"):
            candidate = root / directory / relative
            if candidate.is_file():
                return _validate_python(candidate, root, purpose)
    raise PythonRuntimeUnavailable(
        f"{purpose}需要项目的外部 Python 环境。AI-Bridge 已内置运行应用所需的 Python，"
        "但该应用程序不能作为 pip、pytest 或脚本解释器。"
        "请在聊天页执行环境菜单中选择 Python，设置 AI_BRIDGE_PYTHON，"
        "或在当前项目创建 .venv 后重试。"
    )


def python_subprocess_environment() -> dict[str, str]:
    """Do not leak PyInstaller's Python/library search paths to external tools."""
    env = os.environ.copy()
    if is_frozen_application():
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            original = env.pop(key + "_ORIG", None)
            if original is None:
                env.pop(key, None)
            else:
                env[key] = original
    env["PYTHONIOENCODING"] = "utf-8"
    return env
