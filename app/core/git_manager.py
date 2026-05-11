import logging
# filename: app/core/git_manager.py
import subprocess
import os
from pathlib import Path
from app.core.logging import get_logger
from app.core.project_context import ProjectContext

logger = get_logger("app.core.git_manager", side="worker")


class GitManager:
    def __init__(self, repo_path=None):
        self.repo_path = repo_path or ProjectContext.get().get_project_root()

    def run_git(self, args):
        """执行 git 命令并返回结果"""
        try:
            # 添加 -c core.quotepath=false 以正确显示中文文件名
            # Git 默认会将非 ASCII 字符转义为八进制序列，导致中文文件名显示为 \xxx\xxx
            git_args = ["-c", "core.quotepath=false"] + args
            result = subprocess.run(
                ["git"] + git_args,
                cwd=self.repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore',
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0, result.stdout
        except FileNotFoundError:
            return False, "❌ 未找到 git 命令，请先安装 Git。"
        except Exception as e:
            return False, f"❌ 执行出错: {str(e)}"

    def get_status(self):
        if not os.path.exists(os.path.join(self.repo_path, ".git")):
            return "⚠️ 尚未初始化 Git 仓库"
        ok, out = self.run_git(["status", "-s"])
        return out if ok else "无法获取状态"

    def _normalize_rel_path(self, rel_path):
        return str(rel_path or "").strip().replace(chr(92), "/")

    def _read_worktree_file(self, rel_path):
        abs_path = Path(self.repo_path) / Path(rel_path)
        if not abs_path.exists() or not abs_path.is_file():
            return ""
        return abs_path.read_text(encoding="utf-8", errors="replace")

    def _read_head_file(self, rel_path):
        ok, out = self.run_git(["show", f"HEAD:{rel_path}"])
        return out if ok else None

    def _parse_status_kind(self, index_status, worktree_status):
        pair = f"{index_status}{worktree_status}"
        if pair == "??":
            return "untracked"
        if "R" in pair:
            return "renamed"
        if "D" in pair:
            return "deleted"
        if "A" in pair:
            return "added"
        if "M" in pair:
            return "modified"
        return "unknown"

    def get_changed_files(self):
        """获取当前工作区中参与本次提交的变更文件（规范化为 / 分隔）"""
        ok, out = self.run_git(["status", "--porcelain"])
        if not ok:
            return []

        changed_files = []
        seen = set()
        for raw in str(out or "").splitlines():
            line = raw.rstrip()
            if not line:
                continue

            path_part = line[3:] if len(line) > 3 else ""
            if not path_part:
                continue

            if " -> " in path_part:
                old_path, new_path = path_part.split(" -> ", 1)
                candidates = [old_path, new_path]
            else:
                candidates = [path_part]

            for item in candidates:
                rel = self._normalize_rel_path(item)
                if rel and rel not in seen:
                    seen.add(rel)
                    changed_files.append(rel)

        return changed_files

    def get_working_tree_changes(self):
        """返回结构化的当前工作区变更列表"""
        ok, out = self.run_git(["status", "--porcelain"])
        if not ok:
            return []

        items = []
        for raw in str(out or "").splitlines():
            line = raw.rstrip(chr(10)).rstrip(chr(13))
            if not line:
                continue

            raw_status = line[:2] if len(line) >= 2 else "  "
            index_status = raw_status[0]
            worktree_status = raw_status[1]
            path_part = line[3:] if len(line) > 3 else ""
            old_path = None
            new_path = None
            rel_path = self._normalize_rel_path(path_part)

            if " -> " in path_part:
                old_path_raw, new_path_raw = path_part.split(" -> ", 1)
                old_path = self._normalize_rel_path(old_path_raw)
                new_path = self._normalize_rel_path(new_path_raw)
                rel_path = new_path or old_path

            kind = self._parse_status_kind(index_status, worktree_status)
            items.append({
                "path": rel_path,
                "old_path": old_path,
                "new_path": new_path,
                "raw_status": raw_status,
                "index_status": index_status,
                "worktree_status": worktree_status,
                "kind": kind,
                "display": f"{raw_status} {rel_path}".strip(),
            })

        return items

    def get_commit_history(self, limit=30):
        """返回最近提交历史"""
        ok, out = self.run_git([
            "log",
            f"-n{int(limit)}",
            "--pretty=format:%H%x09%h%x09%an%x09%ad%x09%s",
            "--date=iso",
        ])
        if not ok:
            return []

        items = []
        for raw in str(out or "").splitlines():
            parts = raw.split(chr(9), 4)
            if len(parts) != 5:
                continue
            full_hash, short_hash, author, date_text, message = parts
            items.append({
                "hash": full_hash,
                "short_hash": short_hash,
                "author": author,
                "date": date_text,
                "message": message,
            })
        return items

    def get_repo_summary(self):
        """返回仓库摘要信息"""
        summary = {
            "branch": "",
            "ahead": 0,
            "behind": 0,
            "change_count": 0,
            "has_uncommitted": False,
            "status_text": "",
            "is_repo": os.path.exists(os.path.join(self.repo_path, ".git")),
            "repo_path": self.repo_path,
            "upstream": "",
            "has_origin": False,
            "origin_url": "",
        }
        if not summary["is_repo"]:
            summary["status_text"] = "⚠️ 尚未初始化 Git 仓库"
            return summary

        ok, out = self.run_git(["status", "-sb"])
        if not ok:
            summary["status_text"] = "无法获取仓库状态"
            return summary

        lines = [line for line in str(out or "").splitlines() if line.strip()]
        if lines:
            first = lines[0].strip()
            summary["status_text"] = first
            if first.startswith("## "):
                branch_part = first[3:]
                branch_name = branch_part.split("...")[0].strip()
                summary["branch"] = branch_name
                if "..." in branch_part:
                    upstream_part = branch_part.split("...", 1)[1].strip()
                    if " [" in upstream_part:
                        upstream_part = upstream_part.split(" [", 1)[0].strip()
                    summary["upstream"] = upstream_part
                if "[" in first and "]" in first:
                    tail = first[first.find("[") + 1:first.find("]")]
                    for piece in tail.split(","):
                        item = piece.strip()
                        if item.startswith("ahead "):
                            try:
                                summary["ahead"] = int(item.replace("ahead ", "").strip())
                            except Exception as e:
                                logger.warning(e)
                        elif item.startswith("behind "):
                            try:
                                summary["behind"] = int(item.replace("behind ", "").strip())
                            except Exception as e:
                                logger.warning(e)

        remotes = self.get_remotes()
        origin_url = remotes.get("origin", "")
        summary["has_origin"] = bool(origin_url)
        summary["origin_url"] = origin_url

        changes = self.get_working_tree_changes()
        summary["change_count"] = len(changes)
        summary["has_uncommitted"] = bool(changes)
        return summary

    def get_workbench_state(self, limit=30):
        """聚合返回 Git 工作台所需的数据"""
        return {
            "summary": self.get_repo_summary(),
            "changes": self.get_working_tree_changes(),
            "history": self.get_commit_history(limit=limit),
        }


    def is_git_repo(self):
        return os.path.exists(os.path.join(self.repo_path, ".git"))

    def get_current_branch(self):
        if not self.is_git_repo():
            return ""
        ok, out = self.run_git(["branch", "--show-current"])
        if not ok:
            return ""
        return str(out or "").strip()

    def get_remotes(self):
        remotes = {}
        if not self.is_git_repo():
            return remotes
        ok, out = self.run_git(["remote", "-v"])
        if not ok:
            return remotes
        for raw in str(out or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            name = parts[0].strip()
            url = parts[1].strip()
            if name and url and name not in remotes:
                remotes[name] = url
        return remotes

    def get_user_config(self):
        result = {
            "name": "",
            "email": "",
        }
        ok, out = self.run_git(["config", "--get", "user.name"])
        if ok:
            result["name"] = str(out or "").strip()
        ok, out = self.run_git(["config", "--get", "user.email"])
        if ok:
            result["email"] = str(out or "").strip()
        return result

    def get_git_version(self):
        ok, out = self.run_git(["--version"])
        return str(out or "").strip() if ok else ""

    def detect_remote_type(self, url):
        s = str(url or "").strip().lower()
        if not s:
            return ""
        if s.startswith("git@") or s.startswith("ssh://"):
            return "ssh"
        if s.startswith("http://") or s.startswith("https://"):
            return "https"
        return "unknown"

    def get_git_config_snapshot(self):
        summary = self.get_repo_summary()
        remotes = self.get_remotes()
        user = self.get_user_config()
        origin_url = remotes.get("origin", "")
        return {
            "repo_path": self.repo_path,
            "is_repo": self.is_git_repo(),
            "git_version": self.get_git_version(),
            "branch": summary.get("branch", ""),
            "upstream": summary.get("upstream", ""),
            "has_origin": bool(origin_url),
            "origin_url": origin_url,
            "origin_type": self.detect_remote_type(origin_url),
            "remotes": remotes,
            "user_name": user.get("name", ""),
            "user_email": user.get("email", ""),
            "status_text": summary.get("status_text", ""),
            "ahead": summary.get("ahead", 0),
            "behind": summary.get("behind", 0),
        }

    def init_repo(self):
        logs = []
        if self.is_git_repo():
            logs.append("ℹ️ 当前目录已经是 Git 仓库")
            return True, "\n".join(logs)
        logs.append("🔹 执行: git init")
        ok, out = self.run_git(["init"])
        logs.append(out)
        return ok, "\n".join(logs)

    def set_user_config(self, name, email):
        logs = []
        clean_name = str(name or "").strip()
        clean_email = str(email or "").strip()
        if not clean_name:
            return False, "⚠️ user.name 不能为空"
        if not clean_email:
            return False, "⚠️ user.email 不能为空"
        logs.append(f"🔹 执行: git config user.name \"{clean_name}\"")
        ok, out = self.run_git(["config", "user.name", clean_name])
        logs.append(out)
        if not ok:
            return False, "\n".join(logs)
        logs.append(f"🔹 执行: git config user.email \"{clean_email}\"")
        ok, out = self.run_git(["config", "user.email", clean_email])
        logs.append(out)
        return ok, "\n".join(logs)

    def set_remote(self, name, url):
        logs = []
        remote_name = str(name or "origin").strip() or "origin"
        remote_url = str(url or "").strip()
        if not self.is_git_repo():
            return False, "⚠️ 尚未初始化 Git 仓库"
        if not remote_url:
            return False, "⚠️ Remote URL 不能为空"
        remotes = self.get_remotes()
        if remote_name in remotes:
            logs.append(f"🔹 执行: git remote set-url {remote_name} {remote_url}")
            ok, out = self.run_git(["remote", "set-url", remote_name, remote_url])
        else:
            logs.append(f"🔹 执行: git remote add {remote_name} {remote_url}")
            ok, out = self.run_git(["remote", "add", remote_name, remote_url])
        logs.append(out)
        return ok, "\n".join(logs)

    def set_upstream_to_origin_current_branch(self):
        logs = []
        if not self.is_git_repo():
            return False, "⚠️ 尚未初始化 Git 仓库"
        branch = self.get_current_branch()
        if not branch:
            return False, "⚠️ 当前分支为空，无法绑定 upstream"
        remotes = self.get_remotes()
        if "origin" not in remotes:
            return False, "⚠️ 未检测到 origin，请先在 Git 配置中设置远程仓库地址"
        logs.append(f"🔹 执行: git push --set-upstream origin {branch}")
        ok, out = self.run_git(["push", "--set-upstream", "origin", branch])
        logs.append(out)
        if not ok:
            low_out = str(out or "").lower()
            if "denied" in low_out or "permission" in low_out or "authentication" in low_out:
                logs.append("❌ 绑定失败：认证不足。HTTPS 请检查 PAT(repo) 权限；SSH 请检查公钥是否已添加到 GitHub。")
        return ok, "\n".join(logs)

    def run_connectivity_checks(self):
        checks = []

        git_version = self.get_git_version()
        checks.append({
            "key": "git_available",
            "label": "Git 环境",
            "ok": bool(git_version),
            "detail": git_version or "未检测到 git 命令",
        })

        is_repo = self.is_git_repo()
        checks.append({
            "key": "is_repo",
            "label": "Git 仓库",
            "ok": is_repo,
            "detail": "已检测到 .git 目录" if is_repo else "当前目录不是 Git 仓库",
        })

        remotes = self.get_remotes()
        origin_url = remotes.get("origin", "")
        checks.append({
            "key": "origin_remote",
            "label": "origin 远程",
            "ok": bool(origin_url),
            "detail": origin_url or "未配置 origin",
        })

        branch = self.get_current_branch()
        summary = self.get_repo_summary()
        upstream = summary.get("upstream", "")
        checks.append({
            "key": "upstream",
            "label": "上游分支",
            "ok": bool(upstream),
            "detail": upstream or f"当前分支 {branch or '--'} 未绑定 upstream",
        })

        origin_type = self.detect_remote_type(origin_url)
        checks.append({
            "key": "origin_type",
            "label": "认证方式",
            "ok": bool(origin_type),
            "detail": origin_type.upper() if origin_type else "未识别",
        })

        ssh_ok = False
        ssh_detail = "未执行 SSH 检测"
        try:
            result = subprocess.run(
                ["ssh", "-T", "git@github.com"],
                cwd=self.repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=15,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            output = str(result.stdout or "").strip()
            low_output = output.lower()
            if "successfully authenticated" in low_output or "you've successfully authenticated" in low_output:
                ssh_ok = True
            ssh_detail = output or f"ssh 返回码: {result.returncode}"
        except FileNotFoundError:
            ssh_detail = "未找到 ssh 命令"
        except subprocess.TimeoutExpired:
            ssh_detail = "SSH 检测超时，请检查网络或代理"
        except Exception as e:
            ssh_detail = f"SSH 检测失败: {e}"

        checks.append({
            "key": "ssh_github",
            "label": "SSH 到 GitHub",
            "ok": ssh_ok,
            "detail": ssh_detail,
        })

        return {
            "checks": checks,
            "repo_path": self.repo_path,
            "origin_url": origin_url,
            "origin_type": origin_type,
            "branch": branch,
            "upstream": upstream,
        }
    def get_file_diff_content(self, rel_path, kind=None):
        """返回文件 diff 预览所需的 old/new 内容"""
        rel_path = self._normalize_rel_path(rel_path)
        if not rel_path:
            return {
                "path": "",
                "kind": kind or "unknown",
                "old_text": None,
                "new_text": "",
                "exists": False,
            }

        if not kind:
            for item in self.get_working_tree_changes():
                if item.get("path") == rel_path:
                    kind = item.get("kind") or kind
                    break
        kind = kind or "modified"

        old_text = self._read_head_file(rel_path)
        new_text = self._read_worktree_file(rel_path)
        abs_path = Path(self.repo_path) / Path(rel_path)
        exists = abs_path.exists()

        if kind == "untracked" or kind == "added":
            old_text = None
        elif kind == "deleted":
            new_text = ""

        return {
            "path": rel_path,
            "kind": kind,
            "old_text": old_text,
            "new_text": new_text,
            "exists": exists,
        }

    def push_only(self):
        """仅执行 git push，不创建新的提交"""
        logs = []
        if not os.path.exists(os.path.join(self.repo_path, ".git")):
            return False, "⚠️ 尚未初始化 Git 仓库"

        logs.append("🔹 执行: git push")
        ok, out = self.run_git(["push"])
        logs.append(out)

        if not ok:
            low_out = str(out or "").lower()
            if "no upstream" in low_out or "configured" in low_out:
                logs.append("⚠️ 推送失败：当前分支未配置上游分支。")
                logs.append("💡 请手动执行: git push --set-upstream origin master (或 main)")
            elif "denied" in low_out or "permission" in low_out:
                logs.append("❌ 推送失败：GitHub 权限不足 (请检查 Token 或 SSH Key)。")
            return False, "\n".join(logs)

        return True, "\n".join(logs)

    def backup(self, message):
        logs = []
        changed_files = []

        if not os.path.exists(os.path.join(self.repo_path, ".git")):
            logs.append("⚠️ 未检测到 .git 文件夹，正在初始化...")
            ok, out = self.run_git(["init"])
            if not ok:
                return False, "❌ 初始化失败:\n" + out, changed_files

        changed_files = self.get_changed_files()

        logs.append("🔹 执行: git add .")
        ok, out = self.run_git(["add", "."])
        if not ok:
            return False, "\n".join(logs) + "\n" + out, changed_files

        changed_files = self.get_changed_files()

        logs.append(f"🔹 执行: git commit -m '{message}'")
        ok, out = self.run_git(["commit", "-m", message])
        logs.append(out)

        if not ok and "nothing to commit" not in out and "无文件要提交" not in out:
            return False, "\n".join(logs), changed_files

        logs.append("🔹 执行: git push")
        ok, out = self.run_git(["push"])
        logs.append(out)

        if not ok:
            low_out = out.lower()
            if "no upstream" in low_out or "configured" in low_out:
                logs.append("\n✅ 本地备份已完成！(代码已安全)")
                logs.append("⚠️ 推送失败：因为你的旧 .git 里可能没有配置远程地址，或者分支名不匹配。")
                logs.append("💡 请手动执行: git push --set-upstream origin master (或 main)")
                return False, "\n".join(logs), changed_files
            elif "denied" in low_out or "permission" in low_out:
                logs.append("\n✅ 本地备份已完成！")
                logs.append("❌ 推送失败：GitHub 权限不足 (请检查 Token 或 SSH Key)。")
                return False, "\n".join(logs), changed_files

            return False, "\n".join(logs), changed_files

        return True, "\n".join(logs), changed_files

    def read_gitignore(self):
        gitignore_path = Path(self.repo_path) / ".gitignore"
        if not gitignore_path.exists():
            return ""
        return gitignore_path.read_text(encoding="utf-8", errors="replace")

    def write_gitignore(self, content):
        gitignore_path = Path(self.repo_path) / ".gitignore"
        if not content.endswith("\n"):
            content += "\n"
        gitignore_path.write_text(content, encoding="utf-8")
        return True, "✅ .gitignore 已保存"

    def add_to_gitignore(self, pattern):
        gitignore_path = Path(self.repo_path) / ".gitignore"
        pattern = str(pattern or "").strip().replace("\\", "/")
        if not pattern:
            return False, "⚠️ 忽略规则不能为空"
        existing = ""
        if gitignore_path.exists():
            existing = gitignore_path.read_text(encoding="utf-8", errors="replace")
        for line in existing.splitlines():
            if line.strip() == pattern:
                return False, f"ℹ️ {pattern} 已存在于 .gitignore"
        if not existing.endswith("\n") and existing:
            existing += "\n"
        existing += pattern + "\n"
        gitignore_path.write_text(existing, encoding="utf-8")
        return True, f"✅ 已将 {pattern} 添加到 .gitignore"

    def remove_from_tracking(self, rel_path):
        rel_path = self._normalize_rel_path(rel_path)
        if not rel_path:
            return False, "⚠️ 文件路径不能为空"
        ok, out = self.run_git(["rm", "--cached", rel_path])
        if not ok:
            return False, f"❌ 移除跟踪失败: {out}"
        return True, f"✅ 已从 Git 跟踪中移除: {rel_path}"
