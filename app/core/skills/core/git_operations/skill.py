# filename: app/core/skills/core/git_operations/skill.py
# Git & GitHub 操作 Skill 入口，负责参数 dispatch 和危险操作二次确认
from typing import Any
from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter
from app.core.project_context import ProjectContext
from .git_ops import (
    git_status, git_diff, git_log,
    git_add, git_commit, git_push, git_pull,
    git_branch, git_worktree,
)
from .gh_ops import (
    gh_issue_list, gh_issue_view,
    gh_issue_create, gh_issue_edit, gh_issue_comment,
)


# 需要 confirm=True 才能执行的操作
_DANGEROUS_OPS = {
    "git_commit",
    "git_push",
    "git_pull",
    "git_branch_delete",    # git_branch action=delete
    "git_worktree_remove",  # git_worktree action=remove
    "gh_issue_create",
    "gh_issue_edit",
    "gh_issue_comment",
}

# 危险操作的友好描述，用于未确认时的提示
_DANGEROUS_DESC = {
    "git_commit":          "提交代码到本地仓库（git commit）",
    "git_push":            "推送代码到远程仓库（git push）",
    "git_pull":            "从远程拉取并合并代码到本地（git pull）",
    "git_branch_delete":   "删除本地分支（git branch -d/-D）",
    "git_worktree_remove": "删除 worktree（git worktree remove）",
    "gh_issue_create":     "在 GitHub 上创建新 issue",
    "gh_issue_edit":       "修改 GitHub issue 的内容/状态/标签/负责人",
    "gh_issue_comment":    "在 GitHub issue 下添加评论",
}


def _danger_key(operation: str, **kwargs) -> str:
    """把 operation + 关键参数映射为危险操作 key"""
    if operation == "git_branch" and kwargs.get("action") == "delete":
        return "git_branch_delete"
    if operation == "git_worktree" and kwargs.get("action") == "remove":
        return "git_worktree_remove"
    return operation


def _confirm_required(op_key: str, **kwargs) -> dict:
    """返回二次确认提示，告知 AI 将要执行的操作内容"""
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


class GitOperationsSkill(BaseSkill):
    """Git & GitHub 操作 Skill"""

    def __init__(self, repo_path: str = None):
        super().__init__()
        self.repo_path = repo_path or ProjectContext.get().get_project_root()

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="git_operations",
            display_name="Git & GitHub 操作",
            category="vcs",
            description="查看 git 状态/diff/log、提交推送拉取代码、管理分支与 worktree、查看和修改 GitHub issue",
            scenario="需要查看代码变更、提交代码、管理分支、操作 GitHub issue 时",
            version="1.0.0",
            author="System",
            parameters=[
                SkillParameter(name="operation",    type="str",  required=True,  description="操作名称，见下方支持列表"),
                SkillParameter(name="confirm",      type="bool", required=False, description="危险操作必须传 True 才会执行", default=False),
                # git_diff
                SkillParameter(name="path",         type="str",  required=False, description="文件路径（diff/log/add 等）"),
                SkillParameter(name="cached",       type="bool", required=False, description="git diff 查看已暂存内容",     default=False),
                SkillParameter(name="commit",       type="str",  required=False, description="commit hash 或引用"),
                SkillParameter(name="commit_to",    type="str",  required=False, description="diff 结束 commit"),
                SkillParameter(name="stat_only",    type="bool", required=False, description="diff 只返回 --stat 摘要",    default=False),
                # git_log
                SkillParameter(name="limit",        type="int",  required=False, description="log/issue list 返回数量上限", default=20),
                SkillParameter(name="oneline",      type="bool", required=False, description="log 是否单行显示",           default=True),
                # git_add
                SkillParameter(name="paths",        type="list", required=False, description="git add 的文件列表，空则 add ."),
                # git_commit
                SkillParameter(name="message",      type="str",  required=False, description="commit message"),
                # git_push / git_pull
                SkillParameter(name="remote",       type="str",  required=False, description="远程名称",                  default="origin"),
                SkillParameter(name="branch",       type="str",  required=False, description="分支名"),
                SkillParameter(name="set_upstream", type="bool", required=False, description="push 时绑定上游",            default=False),
                SkillParameter(name="rebase",       type="bool", required=False, description="pull 时使用 --rebase",      default=False),
                # git_branch
                SkillParameter(name="action",       type="str",  required=False, description="list/create/switch/delete（branch/worktree）"),
                SkillParameter(name="name",         type="str",  required=False, description="分支名或 worktree 名称"),
                SkillParameter(name="target",       type="str",  required=False, description="创建分支时的基准"),
                SkillParameter(name="remote_flag",  type="bool", required=False, description="branch list 是否包含远程分支", default=False),
                # git_worktree
                SkillParameter(name="new_branch",   type="bool", required=False, description="worktree add 时是否同时新建分支", default=False),
                # gh issue
                SkillParameter(name="number",       type="int",  required=False, description="issue 编号"),
                SkillParameter(name="state",        type="str",  required=False, description="issue state: open/closed/all", default="open"),
                SkillParameter(name="assignee",     type="str",  required=False, description="issue 负责人 login"),
                SkillParameter(name="label",        type="str",  required=False, description="issue 标签"),
                SkillParameter(name="search",       type="str",  required=False, description="issue 关键词搜索"),
                SkillParameter(name="title",        type="str",  required=False, description="issue 标题"),
                SkillParameter(name="body",         type="str",  required=False, description="issue body 或评论内容"),
                SkillParameter(name="add_label",    type="str",  required=False, description="issue edit 添加标签"),
                SkillParameter(name="remove_label", type="str",  required=False, description="issue edit 移除标签"),
            ],
            examples=[
                "git_operations(operation='git_status')",
                "git_operations(operation='git_diff', stat_only=True)",
                "git_operations(operation='git_diff', path='app/core/worker.py')",
                "git_operations(operation='git_log', limit=10)",
                "git_operations(operation='git_add', paths=['app/core/worker.py'])",
                "git_operations(operation='git_commit', message='fix: 修复登录问题', confirm=True)",
                "git_operations(operation='git_push', confirm=True)",
                "git_operations(operation='git_pull', confirm=True)",
                "git_operations(operation='git_branch', action='list')",
                "git_operations(operation='git_branch', action='create', name='feature/new-ui')",
                "git_operations(operation='git_branch', action='delete', name='old-branch', confirm=True)",
                "git_operations(operation='git_worktree', action='list')",
                "git_operations(operation='git_worktree', action='add', name='hotfix', branch='main', confirm=True)",
                "git_operations(operation='gh_issue_list', state='open', limit=10)",
                "git_operations(operation='gh_issue_view', number=42)",
                "git_operations(operation='gh_issue_create', title='Bug: xxx', body='复现步骤...', confirm=True)",
                "git_operations(operation='gh_issue_edit', number=42, state='closed', confirm=True)",
                "git_operations(operation='gh_issue_comment', number=42, body='已修复，请验证', confirm=True)",
            ],
            dangerous=True,
        )

    def _get_parameters_schema(self) -> dict:
        return {
            "operation":    {"type": "string", "description": "操作名称"},
            "confirm":      {"type": "boolean", "description": "危险操作确认"},
            "path":         {"type": "string"},
            "cached":       {"type": "boolean"},
            "commit":       {"type": "string"},
            "commit_to":    {"type": "string"},
            "stat_only":    {"type": "boolean"},
            "limit":        {"type": "integer"},
            "oneline":      {"type": "boolean"},
            "paths":        {"type": "array", "items": {"type": "string"}},
            "message":      {"type": "string"},
            "remote":       {"type": "string"},
            "branch":       {"type": "string"},
            "set_upstream": {"type": "boolean"},
            "rebase":       {"type": "boolean"},
            "action":       {"type": "string"},
            "name":         {"type": "string"},
            "target":       {"type": "string"},
            "remote_flag":  {"type": "boolean"},
            "new_branch":   {"type": "boolean"},
            "number":       {"type": "integer"},
            "state":        {"type": "string"},
            "assignee":     {"type": "string"},
            "label":        {"type": "string"},
            "search":       {"type": "string"},
            "title":        {"type": "string"},
            "body":         {"type": "string"},
            "add_label":    {"type": "string"},
            "remove_label": {"type": "string"},
        }

    def _get_required_parameters(self) -> list:
        return ["operation"]

    def execute(self, **kwargs) -> Any:
        operation = str(kwargs.get("operation") or "").strip()
        confirm   = bool(kwargs.get("confirm", False))
        rp        = self.repo_path

        # 计算危险操作 key（剔除 operation 本身，避免与函数参数重名冲突）
        kw_no_op = {k: v for k, v in kwargs.items() if k != "operation"}
        danger_key = _danger_key(operation, **kw_no_op)

        # 危险操作：未确认则返回提示
        if danger_key in _DANGEROUS_OPS and not confirm:
            return _confirm_required(danger_key, **{k: v for k, v in kwargs.items() if k != "operation"})

        # ── dispatch ─────────────────────────────────────────────────────────

        if operation == "git_status":
            return git_status(rp)

        if operation == "git_diff":
            return git_diff(
                rp,
                path=kwargs.get("path"),
                cached=bool(kwargs.get("cached", False)),
                commit=kwargs.get("commit"),
                commit_to=kwargs.get("commit_to"),
                stat_only=bool(kwargs.get("stat_only", False)),
            )

        if operation == "git_log":
            return git_log(
                rp,
                limit=int(kwargs.get("limit", 20)),
                path=kwargs.get("path"),
                oneline=bool(kwargs.get("oneline", True)),
            )

        if operation == "git_add":
            return git_add(rp, paths=kwargs.get("paths"))

        if operation == "git_commit":
            return git_commit(rp, message=kwargs.get("message", ""))

        if operation == "git_push":
            return git_push(
                rp,
                remote=kwargs.get("remote", "origin"),
                branch=kwargs.get("branch"),
                set_upstream=bool(kwargs.get("set_upstream", False)),
            )

        if operation == "git_pull":
            return git_pull(
                rp,
                remote=kwargs.get("remote", "origin"),
                branch=kwargs.get("branch"),
                rebase=bool(kwargs.get("rebase", False)),
            )

        if operation == "git_branch":
            return git_branch(
                rp,
                action=kwargs.get("action", "list"),
                name=kwargs.get("name"),
                target=kwargs.get("target"),
                remote=bool(kwargs.get("remote_flag", False)),
            )

        if operation == "git_worktree":
            return git_worktree(
                rp,
                action=kwargs.get("action", "list"),
                name=kwargs.get("name"),
                branch=kwargs.get("branch"),
                new_branch=bool(kwargs.get("new_branch", False)),
            )

        if operation == "gh_issue_list":
            return gh_issue_list(
                rp,
                state=kwargs.get("state", "open"),
                limit=int(kwargs.get("limit", 20)),
                assignee=kwargs.get("assignee"),
                label=kwargs.get("label"),
                search=kwargs.get("search"),
            )

        if operation == "gh_issue_view":
            num = kwargs.get("number")
            if num is None:
                return {"ok": False, "output": "❌ gh_issue_view 需要提供 number"}
            return gh_issue_view(rp, number=int(num))

        if operation == "gh_issue_create":
            return gh_issue_create(
                rp,
                title=kwargs.get("title", ""),
                body=kwargs.get("body", ""),
                assignee=kwargs.get("assignee"),
                label=kwargs.get("label"),
            )

        if operation == "gh_issue_edit":
            num = kwargs.get("number")
            if num is None:
                return {"ok": False, "output": "❌ gh_issue_edit 需要提供 number"}
            return gh_issue_edit(
                rp,
                number=int(num),
                title=kwargs.get("title"),
                body=kwargs.get("body"),
                state=kwargs.get("state"),
                assignee=kwargs.get("assignee"),
                add_label=kwargs.get("add_label"),
                remove_label=kwargs.get("remove_label"),
            )

        if operation == "gh_issue_comment":
            num = kwargs.get("number")
            if num is None:
                return {"ok": False, "output": "❌ gh_issue_comment 需要提供 number"}
            return gh_issue_comment(rp, number=int(num), body=kwargs.get("body", ""))

        return {"ok": False, "output": f"❌ 未知操作: {operation}"}


__skill__ = GitOperationsSkill
