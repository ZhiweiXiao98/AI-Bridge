# filename: app/core/skills/core/env_operations/env_ops.py
# 环境感知操作：Python 环境信息、包管理、requirements 对比
import sys
import subprocess
import re
from pathlib import Path
from typing import Optional

from app.core.python_runtime import (
    PythonRuntimeUnavailable, resolve_project_python, python_subprocess_environment,
)


def _project_python(purpose):
    from app.core.config import ConfigManager
    from app.core.project_context import ProjectContext
    root = ProjectContext.get().get_project_root()
    configured = ConfigManager.load().get("sandbox_local_python", "")
    return root, resolve_project_python(root, configured, purpose=purpose)


def _run_pip(*args) -> tuple[bool, str]:
    """用项目解释器的 pip 执行命令，绝不将打包应用当成 Python。"""
    try:
        root, python = _project_python("运行 pip")
        result = subprocess.run(
            [python, "-m", "pip"] + list(args),
            capture_output=True,
            text=True,
            timeout=120,
            cwd=root,
            env=python_subprocess_environment(),
        )
        ok = result.returncode == 0
        output = (result.stdout + result.stderr).strip()
        return ok, output
    except subprocess.TimeoutExpired:
        return False, "❌ pip 命令超时（120s）"
    except Exception as e:
        return False, f"❌ pip 执行异常: {e}"


def env_info() -> dict:
    """返回当前 Python 解释器、版本、虚拟环境等基本信息"""
    in_venv = (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )
    lines = [
        f"Python 版本  : {sys.version}",
        f"解释器路径   : {sys.executable}",
        f"虚拟环境     : {'✅ 是' if in_venv else '❌ 否（使用系统 Python）'}",
        f"sys.prefix   : {sys.prefix}",
        f"平台         : {sys.platform}",
    ]
    try:
        root, python = _project_python("项目包管理")
        lines.extend([f"项目目录     : {root}", f"项目解释器   : {python}"])
    except PythonRuntimeUnavailable as exc:
        lines.append(f"项目解释器   : 未配置\n{exc}")
    return {"ok": True, "output": "\n".join(lines)}


def list_packages(search: Optional[str] = None) -> dict:
    """列出已安装的包，支持按包名关键词过滤"""
    ok, raw = _run_pip("list", "--format=columns")
    if not ok:
        return {"ok": False, "output": raw}

    lines = raw.splitlines()
    if search:
        keyword = search.lower()
        # 保留表头（前两行）和匹配行
        header = lines[:2] if len(lines) >= 2 else []
        matched = [l for l in lines[2:] if keyword in l.lower()]
        if not matched:
            return {"ok": True, "output": f"未找到包含 '{search}' 的已安装包。"}
        output = "\n".join(header + matched)
    else:
        output = raw

    return {"ok": True, "output": output}


def check_package(package: str) -> dict:
    """检查单个包是否已安装，返回版本信息"""
    if not package:
        return {"ok": False, "output": "请提供包名。"}
    ok, raw = _run_pip("show", package)
    if not ok:
        return {
            "ok": False,
            "output": f"包 '{package}' 未安装，或名称有误。\n{raw}",
        }
    # 只取关键字段
    keep = {"Name", "Version", "Location", "Requires"}
    lines = []
    for line in raw.splitlines():
        key = line.split(":")[0].strip()
        if key in keep:
            lines.append(line)
    return {"ok": True, "output": "\n".join(lines)}


def check_requirements(req_path: Optional[str] = None) -> dict:
    """
    对比 requirements.txt 与当前环境，列出缺失或版本不符的包。
    req_path 为 None 时自动查找项目根目录的 requirements.txt。
    """
    # 确定 requirements.txt 路径
    if req_path:
        rfile = Path(req_path)
    else:
        try:
            from app.core.project_context import ProjectContext
            root = ProjectContext.get().get_project_root()
            rfile = Path(root) / "requirements.txt"
        except Exception:
            rfile = Path("requirements.txt")

    if not rfile.exists():
        return {"ok": False, "output": f"未找到 requirements 文件：{rfile}"}

    # 读取 requirements.txt，解析包名和版本约束
    req_lines = rfile.read_text(encoding="utf-8").splitlines()
    requirements: list[tuple[str, str]] = []  # (pkg_name, raw_spec)
    for line in req_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 去掉行内注释
        line = line.split("#")[0].strip()
        # 提取包名（忽略 extras 如 [cryptography]）
        m = re.match(r"^([A-Za-z0-9_\-\.]+)", line)
        if m:
            requirements.append((m.group(1).lower(), line))

    if not requirements:
        return {"ok": True, "output": "requirements.txt 为空或无有效内容。"}

    # 获取已安装包列表
    ok, raw = _run_pip("list", "--format=columns")
    if not ok:
        return {"ok": False, "output": f"获取已安装包失败：{raw}"}

    installed: dict[str, str] = {}
    for line in raw.splitlines()[2:]:  # 跳过表头
        parts = line.split()
        if len(parts) >= 2:
            installed[parts[0].lower()] = parts[1]

    # 对比
    missing = []
    present = []
    for pkg_name, spec in requirements:
        # 标准化：连字符和下划线等价
        normalized = pkg_name.replace("-", "_")
        found_key = None
        for k in installed:
            if k == pkg_name or k == normalized or k.replace("-", "_") == normalized:
                found_key = k
                break
        if found_key:
            present.append(f"  ✅ {spec}  （已安装 {installed[found_key]}）")
        else:
            missing.append(f"  ❌ {spec}")

    lines = [f"📄 对比文件：{rfile}", ""]
    if missing:
        lines.append(f"缺失或未安装（共 {len(missing)} 个）：")
        lines.extend(missing)
        lines.append("")
    else:
        lines.append("✅ 所有依赖均已安装。")
        lines.append("")
    lines.append(f"已安装（共 {len(present)} 个）：")
    lines.extend(present)

    return {"ok": True, "missing_count": len(missing), "output": "\n".join(lines)}


def install_package(package: str, version: Optional[str] = None) -> dict:
    """安装指定包，version 可选（如 '>=2.0.0' 或 '==1.9.3'）"""
    if not package:
        return {"ok": False, "output": "请提供要安装的包名。"}
    spec = package if not version else f"{package}{version}"
    ok, raw = _run_pip("install", spec)
    if ok:
        return {"ok": True, "output": f"✅ 安装成功：{spec}\n{raw}"}
    else:
        return {"ok": False, "output": f"❌ 安装失败：{spec}\n{raw}"}
