# filename: app/core/skills/core/git_operations/git_ops.py
# Git 本地操作实现：状态/diff/log/add/commit/push/pull/branch/worktree
import os
import subprocess
from pathlib import Path


def _run_git(repo_path: str, args: list) -> tuple[bool, str]:
    """统一 git 命令执行入口"""
    try:
        git_args = ["-c", "core.quotepath=false"] + args
        result = subprocess.run(
            ["git"] + git_args,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode == 0, result.stdout.strip()
    except FileNotFoundError:
        return False, "❌ 未找到 git 命令，请先安装 Git。"
    except Exception as e:
        return False, f"❌ 执行出错: {e}"


# ── Group 1：只读状态与 diff ────────────────────────────────────────────────

def git_status(repo_path: str) -> dict:
    """获取工作区状态（porcelain + branch 信息）"""
    ok, out = _run_git(repo_path, ["status", "-sb"])
    return {"ok": ok, "output": out}


def git_diff(repo_path: str, path: str = None, cached: bool = False,
             commit: str = None, commit_to: str = None,
             stat_only: bool = False) -> dict:
    """
    查看 diff。
    - path: 指定文件，None 则全部
    - cached: True 则看已暂存的 diff
    - commit: 查看某个 commit 的 diff（可传 hash 或 HEAD~1 等）
    - commit_to: 与 commit 配合，查看两个 commit 之间的 diff
    - stat_only: True 则只返回 --stat 摘要，不展开全文
    """
    args = ["diff"]
    if stat_only:
        args.append("--stat")
    if cached:
        args.append("--cached")
    if commit and commit_to:
        args += [commit, commit_to]
    elif commit:
        args.append(commit)
    if path:
        args += ["--", path]
    ok, out = _run_git(repo_path, args)
    return {"ok": ok, "output": out or "（无差异）"}


def git_log(repo_path: str, limit: int = 20, path: str = None,
            oneline: bool = True) -> dict:
    """查看提交历史"""
    fmt = "%h  %ad  %an  %s" if oneline else "%H%n作者: %an <%ae>%n时间: %ad%n%n    %s%n"
    args = ["log", f"-n{int(limit)}", f"--pretty=format:{fmt}", "--date=short"]
    if path:
        args += ["--", path]
    ok, out = _run_git(repo_path, args)
    return {"ok": ok, "output": out or "（暂无提交记录）"}


# ── Group 2：提交与推送（写操作，调用方需已通过确认） ──────────────────────

def git_add(repo_path: str, paths: list = None) -> dict:
    """
    暂存文件。
    - paths: 文件列表，None 或空列表则 git add .
    """
    targets = paths if paths else ["."]
    args = ["add"] + targets
    ok, out = _run_git(repo_path, args)
    return {"ok": ok, "output": out or "✅ 已暂存"}


def git_commit(repo_path: str, message: str) -> dict:
    """提交，需要 message。"""
    if not message or not message.strip():
        return {"ok": False, "output": "❌ commit message 不能为空"}
    ok, out = _run_git(repo_path, ["commit", "-m", message.strip()])
    return {"ok": ok, "output": out}


def git_push(repo_path: str, remote: str = "origin",
             branch: str = None, set_upstream: bool = False) -> dict:
    """推送到远程。set_upstream=True 时自动绑定上游。"""
    args = ["push"]
    if set_upstream:
        args.append("--set-upstream")
    args.append(remote)
    if branch:
        args.append(branch)
    ok, out = _run_git(repo_path, args)
    return {"ok": ok, "output": out}


def git_pull(repo_path: str, remote: str = "origin",
             branch: str = None, rebase: bool = False) -> dict:
    """拉取远程。rebase=True 时使用 --rebase。"""
    args = ["pull"]
    if rebase:
        args.append("--rebase")
    args.append(remote)
    if branch:
        args.append(branch)
    ok, out = _run_git(repo_path, args)
    return {"ok": ok, "output": out}


# ── Group 3：分支与 worktree ─────────────────────────────────────────────────

def git_branch(repo_path: str, action: str = "list",
               name: str = None, target: str = None,
               remote: bool = False) -> dict:
    """
    分支操作。
    - action: list / create / switch / delete
    - name: 分支名（create/switch/delete 必填）
    - target: 基于哪个分支/commit 创建（create 可选，默认当前 HEAD）
    - remote: list 时是否包含远程分支
    """
    if action == "list":
        args = ["branch", "-vv"]
        if remote:
            args = ["branch", "-avv"]
        ok, out = _run_git(repo_path, args)
        return {"ok": ok, "output": out or "（无分支）"}

    if not name:
        return {"ok": False, "output": "❌ 操作需要提供分支名 name"}

    if action == "create":
        args = ["checkout", "-b", name]
        if target:
            args.append(target)
        ok, out = _run_git(repo_path, args)
        return {"ok": ok, "output": out}

    if action == "switch":
        ok, out = _run_git(repo_path, ["checkout", name])
        return {"ok": ok, "output": out}

    if action == "delete":
        # 调用方已通过确认才会进到这里
        ok, out = _run_git(repo_path, ["branch", "-d", name])
        if not ok:
            # 尝试强删（已由调用方确认）
            ok, out = _run_git(repo_path, ["branch", "-D", name])
        return {"ok": ok, "output": out}

    return {"ok": False, "output": f"❌ 未知 action: {action}"}


def git_worktree(repo_path: str, action: str = "list",
                 name: str = None, branch: str = None,
                 new_branch: bool = False) -> dict:
    """
    worktree 操作。
    - action: list / add / remove
    - name: worktree 名称（add/remove 必填），路径为 <repo_root>/.worktrees/<name>
    - branch: 关联的分支（add 时指定）
    - new_branch: add 时是否同时新建同名分支（-b）
    """
    worktrees_root = str(Path(repo_path) / ".worktrees")

    if action == "list":
        ok, out = _run_git(repo_path, ["worktree", "list", "--porcelain"])
        return {"ok": ok, "output": out or "（无 worktree）"}

    if not name:
        return {"ok": False, "output": "❌ 操作需要提供 worktree 名称 name"}

    wt_path = str(Path(worktrees_root) / name)

    if action == "add":
        # 确保 .worktrees 目录存在
        Path(worktrees_root).mkdir(parents=True, exist_ok=True)
        # 把 .worktrees 加入 .gitignore
        _ensure_gitignore(repo_path, ".worktrees/")
        args = ["worktree", "add"]
        if new_branch:
            args += ["-b", branch or name]
        args.append(wt_path)
        if branch and not new_branch:
            args.append(branch)
        ok, out = _run_git(repo_path, args)
        return {"ok": ok, "output": out, "path": wt_path}

    if action == "remove":
        # 调用方已通过确认才会进到这里
        ok, out = _run_git(repo_path, ["worktree", "remove", wt_path])
        return {"ok": ok, "output": out}

    return {"ok": False, "output": f"❌ 未知 action: {action}"}


def _ensure_gitignore(repo_path: str, pattern: str):
    """确保 .gitignore 中包含指定 pattern（幂等）"""
    gitignore = Path(repo_path) / ".gitignore"
    existing = ""
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8", errors="replace")
    for line in existing.splitlines():
        if line.strip() == pattern.strip():
            return  # 已存在，无需添加
    if existing and not existing.endswith("\n"):
        existing += "\n"
    existing += pattern.strip() + "\n"
    gitignore.write_text(existing, encoding="utf-8")
