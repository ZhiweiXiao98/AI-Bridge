# filename: app/core/skills/core/git_operations/gh_ops.py
# GitHub CLI 封装：issue 查看与修改操作
import os
import subprocess
import json


def _run_gh(repo_path: str, args: list) -> tuple[bool, str]:
    """统一 gh 命令执行入口"""
    try:
        result = subprocess.run(
            ["gh"] + args,
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
        return False, "❌ 未找到 gh 命令，请先安装 GitHub CLI（https://cli.github.com）并完成 gh auth login。"
    except Exception as e:
        return False, f"❌ 执行出错: {e}"


def _parse_json(raw: str) -> tuple[bool, any]:
    """尝试解析 JSON，失败返回原始文本"""
    try:
        return True, json.loads(raw)
    except Exception:
        return False, raw


# ── 只读操作 ─────────────────────────────────────────────────────────────────

def gh_issue_list(repo_path: str, state: str = "open", limit: int = 20,
                  assignee: str = None, label: str = None,
                  search: str = None) -> dict:
    """
    列出 issues。
    - state: open / closed / all
    - limit: 返回数量上限
    - assignee: 过滤指定负责人（@me 表示自己）
    - label: 过滤标签
    - search: 关键词搜索
    """
    args = ["issue", "list",
            "--state", state,
            "--limit", str(int(limit)),
            "--json", "number,title,state,assignees,labels,createdAt,updatedAt,url"]
    if assignee:
        args += ["--assignee", assignee]
    if label:
        args += ["--label", label]
    if search:
        args += ["--search", search]

    ok, raw = _run_gh(repo_path, args)
    if not ok:
        return {"ok": False, "output": raw}

    parsed_ok, data = _parse_json(raw)
    if not parsed_ok or not isinstance(data, list):
        return {"ok": ok, "output": raw}

    # 格式化为可读文本
    lines = []
    for issue in data:
        num = issue.get("number", "?")
        title = issue.get("title", "")
        state_str = issue.get("state", "")
        assignees = ", ".join(a.get("login", "") for a in issue.get("assignees", []))
        labels = ", ".join(lb.get("name", "") for lb in issue.get("labels", []))
        url = issue.get("url", "")
        parts = [f"#{num}  [{state_str}]  {title}"]
        if assignees:
            parts.append(f"负责人: {assignees}")
        if labels:
            parts.append(f"标签: {labels}")
        parts.append(url)
        lines.append("  ".join(parts))

    return {"ok": True, "output": "\n".join(lines) if lines else "（无匹配 issue）", "data": data}


def gh_issue_view(repo_path: str, number: int) -> dict:
    """
    查看单个 issue 详情，包含 body 和评论。
    - number: issue 编号
    """
    args = ["issue", "view", str(int(number)),
            "--json", "number,title,state,body,assignees,labels,comments,createdAt,updatedAt,url"]
    ok, raw = _run_gh(repo_path, args)
    if not ok:
        return {"ok": False, "output": raw}

    parsed_ok, data = _parse_json(raw)
    if not parsed_ok:
        return {"ok": ok, "output": raw}

    # 格式化为可读文本
    num = data.get("number", number)
    title = data.get("title", "")
    state_str = data.get("state", "")
    url = data.get("url", "")
    body = data.get("body", "") or "（无内容）"
    assignees = ", ".join(a.get("login", "") for a in data.get("assignees", []))
    labels = ", ".join(lb.get("name", "") for lb in data.get("labels", []))
    comments = data.get("comments", [])

    lines = [
        f"Issue #{num}  [{state_str}]  {title}",
        f"URL: {url}",
    ]
    if assignees:
        lines.append(f"负责人: {assignees}")
    if labels:
        lines.append(f"标签: {labels}")
    lines += ["", "--- Body ---", body]

    if comments:
        lines.append("\n--- 评论 ---")
        for c in comments:
            author = c.get("author", {}).get("login", "unknown")
            created = c.get("createdAt", "")
            cbody = c.get("body", "")
            lines.append(f"\n[{author}  {created}]")
            lines.append(cbody)

    return {"ok": True, "output": "\n".join(lines), "data": data}


# ── 写操作（调用方需已通过确认） ─────────────────────────────────────────────

def gh_issue_create(repo_path: str, title: str, body: str = "",
                    assignee: str = None, label: str = None) -> dict:
    """
    创建 issue。
    - title: 标题（必填）
    - body: 正文
    - assignee: 负责人 login
    - label: 标签名
    """
    if not title or not title.strip():
        return {"ok": False, "output": "❌ issue 标题不能为空"}

    args = ["issue", "create", "--title", title.strip()]
    if body and body.strip():
        args += ["--body", body.strip()]
    else:
        args += ["--body", ""]
    if assignee:
        args += ["--assignee", assignee]
    if label:
        args += ["--label", label]

    ok, raw = _run_gh(repo_path, args)
    return {"ok": ok, "output": raw}


def gh_issue_edit(repo_path: str, number: int,
                  title: str = None, body: str = None,
                  state: str = None, assignee: str = None,
                  add_label: str = None, remove_label: str = None) -> dict:
    """
    修改 issue。
    - number: issue 编号（必填）
    - title: 新标题
    - body: 新正文
    - state: open / closed
    - assignee: 设置负责人
    - add_label / remove_label: 添加或移除标签
    """
    args = ["issue", "edit", str(int(number))]
    if title:
        args += ["--title", title.strip()]
    if body is not None:
        args += ["--body", body]
    if state:
        # gh issue edit 不直接支持 state，用 close/reopen
        pass
    if assignee:
        args += ["--add-assignee", assignee]
    if add_label:
        args += ["--add-label", add_label]
    if remove_label:
        args += ["--remove-label", remove_label]

    # 处理 state 变更（close/reopen 是独立命令）
    state_result = None
    if state == "closed":
        ok2, out2 = _run_gh(repo_path, ["issue", "close", str(int(number))])
        state_result = {"action": "close", "ok": ok2, "output": out2}
    elif state == "open":
        ok2, out2 = _run_gh(repo_path, ["issue", "reopen", str(int(number))])
        state_result = {"action": "reopen", "ok": ok2, "output": out2}

    # 如果只改了 state，args 没有额外参数，跳过 edit 调用
    has_edit_args = len(args) > 3  # 超过 ["issue", "edit", "<number>"]
    edit_result = None
    if has_edit_args:
        ok, raw = _run_gh(repo_path, args)
        edit_result = {"ok": ok, "output": raw}

    # 合并输出
    parts = []
    if state_result:
        parts.append(state_result["output"])
    if edit_result:
        parts.append(edit_result["output"])

    overall_ok = (
        (state_result["ok"] if state_result else True) and
        (edit_result["ok"] if edit_result else True)
    )
    return {"ok": overall_ok, "output": "\n".join(parts) or "✅ 已更新"}


def gh_issue_comment(repo_path: str, number: int, body: str) -> dict:
    """
    给 issue 添加评论。
    - number: issue 编号
    - body: 评论内容
    """
    if not body or not body.strip():
        return {"ok": False, "output": "❌ 评论内容不能为空"}
    args = ["issue", "comment", str(int(number)), "--body", body.strip()]
    ok, raw = _run_gh(repo_path, args)
    return {"ok": ok, "output": raw}
