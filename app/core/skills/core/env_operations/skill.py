# filename: app/core/skills/core/env_operations/skill.py
# 环境感知 Skill 入口，负责参数 dispatch 和安装操作二次确认
from typing import Any
from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter
from .env_ops import (
    env_info,
    list_packages,
    check_package,
    check_requirements,
    install_package,
)


# 需要 confirm=True 才能执行的操作
_DANGEROUS_OPS = {"install_package"}

_DANGEROUS_DESC = {
    "install_package": "向当前 Python 环境安装包（pip install）",
}


def _confirm_required(op_key: str, **kwargs) -> dict:
    """返回二次确认提示"""
    desc = _DANGEROUS_DESC.get(op_key, op_key)
    detail_parts = []
    for k, v in kwargs.items():
        if k == "confirm" or k.startswith("_"):
            continue
        if v is not None and v != "" and v is not False:
            detail_parts.append(f"{k}={repr(v)}")
    detail = "、".join(detail_parts) if detail_parts else "（无额外参数）"
    return {
        "ok": False,
        "requires_confirm": True,
        "output": (
            f"⚠️ 即将执行危险操作：{desc}\n"
            f"参数：{detail}\n"
            f"请再次调用并传入 confirm=True 以确认执行。"
        ),
    }


class EnvOperationsSkill(BaseSkill):
    """Python 环境感知与包管理 Skill"""

    def __init__(self):
        super().__init__()

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="env_operations",
            display_name="Python 环境感知与包管理",
            category="system",
            description="感知当前 Python 运行环境，查看已安装包，对比 requirements.txt，以及安装缺失依赖。",
            scenario="需要了解当前 Python 环境状态、检查依赖是否安装、安装缺失包时",
            version="1.0.0",
            author="System",
            parameters=[
                SkillParameter(name="operation", type="str",  required=True,  description="操作类型：env_info / list_packages / check_package / check_requirements / install_package"),
                SkillParameter(name="package",   type="str",  required=False, description="包名，check_package / install_package 时使用"),
                SkillParameter(name="version",   type="str",  required=False, description="版本约束，install_package 时可选，如 >=2.0.0"),
                SkillParameter(name="search",    type="str",  required=False, description="关键词过滤，list_packages 时使用"),
                SkillParameter(name="req_path",  type="str",  required=False, description="requirements 文件路径，check_requirements 时可选"),
                SkillParameter(name="confirm",   type="bool", required=False, description="危险操作二次确认，install_package 必须传 true 才会执行", default=False),
            ],
        )

    def execute(self, **kwargs) -> Any:
        operation = str(kwargs.get("operation") or "").strip()
        confirm   = bool(kwargs.get("confirm", False))
        kw_no_op  = {k: v for k, v in kwargs.items() if k != "operation"}

        # 危险操作：未确认则返回提示
        if operation in _DANGEROUS_OPS and not confirm:
            return _confirm_required(operation, **kw_no_op)

        # ── dispatch ─────────────────────────────────────────────────────────

        if operation == "env_info":
            return env_info()

        if operation == "list_packages":
            return list_packages(
                search=kwargs.get("search"),
            )

        if operation == "check_package":
            return check_package(
                package=str(kwargs.get("package") or ""),
            )

        if operation == "check_requirements":
            return check_requirements(
                req_path=kwargs.get("req_path"),
            )

        if operation == "install_package":
            return install_package(
                package=str(kwargs.get("package") or ""),
                version=kwargs.get("version"),
            )

        return {"ok": False, "output": f"未知 operation: {operation}"}


__skill__ = EnvOperationsSkill
