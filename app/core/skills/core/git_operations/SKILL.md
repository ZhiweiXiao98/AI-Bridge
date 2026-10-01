---
name: git_operations
display_name: Git & GitHub 操作
category: vcs
scenario: 需要查看代码变更、提交代码、管理分支、操作 GitHub issue 时
version: 1.0.0
author: System
dangerous: true
enabled: true
summary: >
  提供完整的 Git 本地操作和 GitHub issue 管理。
  只读操作（无需确认）：git_status、git_diff、git_log、git_branch(list)、gh_issue_list/view。
  写操作（需 confirm=true）：git_add、git_commit、git_push、git_pull、git_branch(create/switch/delete)、
  git_worktree、gh_issue_create/edit/comment。
  始终推送到新分支，不直接推 main/master。
  调用格式：tool_call { "name": "git_operations", "arguments": { "operation": "操作名", ...参数 } }
---

# Git & GitHub 操作

## 技能描述

提供完整的 Git 本地操作和 GitHub issue 管理能力，涵盖：

- 查看工作区状态、diff、提交历史
- 暂存、提交、推送、拉取代码
- 分支管理（列出/创建/切换/删除）
- Worktree 管理（列出/新增/删除）
- GitHub issue 查看与修改（依赖 `gh` CLI）

## ⚠️ 危险操作确认机制

以下操作**必须传入 `confirm=True`** 才会执行，否则只返回操作描述让你二次确认：

| 操作 | 说明 |
|------|------|
| `git_commit` | 提交到本地仓库 |
| `git_push` | 推送到远程 |
| `git_pull` | 拉取并合并远程代码 |
| `git_branch` action=delete | 删除本地分支 |
| `git_worktree` action=remove | 删除 worktree |
| `gh_issue_create` | 创建 issue |
| `gh_issue_edit` | 修改 issue |
| `gh_issue_comment` | 添加评论 |

## 参数说明

**公共参数**
- `operation` (str, 必需): 操作名称，见下方支持的操作列表
- `confirm` (bool, 可选): 危险操作二次确认，默认 False

**git_diff 专用**
- `path` (str, 可选): 指定文件路径
- `cached` (bool, 可选): 查看已暂存的 diff，默认 False
- `commit` (str, 可选): 查看指定 commit 的 diff，支持 hash 或 HEAD~1 等写法
- `commit_to` (str, 可选): 与 commit 配合，查看两个 commit 之间的 diff
- `stat_only` (bool, 可选): 只返回 --stat 文件摘要，不展开全文，默认 False

**git_log 专用**
- `limit` (int, 可选): 返回条数，默认 20
- `path` (str, 可选): 只看指定文件的历史
- `oneline` (bool, 可选): 单行紧凑格式，默认 True

**git_add 专用**
- `paths` (list, 可选): 要暂存的文件列表，不传则 `git add .`

**git_commit 专用**
- `message` (str, 必需): commit message

**git_push 专用**
- `remote` (str, 可选): 远程名称，默认 origin
- `branch` (str, 可选): 指定推送分支
- `set_upstream` (bool, 可选): 是否绑定上游，默认 False

**git_pull 专用**
- `remote` (str, 可选): 远程名称，默认 origin
- `branch` (str, 可选): 指定拉取分支
- `rebase` (bool, 可选): 使用 --rebase，默认 False

**git_branch 专用**
- `action` (str, 可选): list / create / switch / delete，默认 list
- `name` (str, create/switch/delete 必需): 分支名
- `target` (str, 可选): 创建分支时的基准 commit/分支
- `remote_flag` (bool, 可选): list 时是否包含远程分支，默认 False

**git_worktree 专用**
- `action` (str, 可选): list / add / remove，默认 list
- `name` (str, add/remove 必需): worktree 名称，实际路径为 `<项目根>/.worktrees/<name>`
- `branch` (str, 可选): 关联分支
- `new_branch` (bool, 可选): add 时同时新建同名分支，默认 False

> worktree 默认存放在项目根目录 `.worktrees/` 下，该目录会自动加入 `.gitignore`。

**gh issue 专用**
- `number` (int, view/edit/comment 必需): issue 编号
- `state` (str, 可选): open / closed / all，默认 open
- `assignee` (str, 可选): 负责人 login，`@me` 表示自己
- `label` (str, 可选): 标签名
- `search` (str, 可选): 关键词搜索
- `title` (str, 可选): issue 标题
- `body` (str, 可选): issue body 或评论内容
- `add_label` (str, 可选): edit 时添加标签
- `remove_label` (str, 可选): edit 时移除标签

## 支持的操作列表

### 只读操作（无需确认）

```
git_status       查看工作区状态
git_diff         查看 diff
git_log          查看提交历史
git_branch       列出分支（action=list）
git_worktree     列出 worktree（action=list）
gh_issue_list    列出 issues
gh_issue_view    查看 issue 详情
```

### 写操作（需要 confirm=True）

```
git_add          暂存文件（不需要确认，属于预备操作）
git_commit       提交代码
git_push         推送代码
git_pull         拉取代码
git_branch       创建/切换/删除分支
git_worktree     新增/删除 worktree
gh_issue_create  创建 issue
gh_issue_edit    修改 issue
gh_issue_comment 添加评论
```

> 注意：`git_add` 不需要确认，因为暂存操作随时可以撤销（git restore --staged）。

## 使用示例

```
# 查看状态和变更
git_operations(operation='git_status')
git_operations(operation='git_diff', stat_only=True)
git_operations(operation='git_diff', path='app/core/worker.py')
git_operations(operation='git_diff', commit='HEAD~1')
git_operations(operation='git_log', limit=10)

# 提交流程
git_operations(operation='git_add', paths=['app/core/worker.py', 'app/core/agent_manager.py'])
git_operations(operation='git_commit', message='fix: 修复登录超时问题', confirm=True)
git_operations(operation='git_push', confirm=True)

# 拉取
git_operations(operation='git_pull', confirm=True)
git_operations(operation='git_pull', rebase=True, confirm=True)

# 分支操作
git_operations(operation='git_branch', action='list', remote_flag=True)
git_operations(operation='git_branch', action='create', name='feature/dark-mode')
git_operations(operation='git_branch', action='switch', name='main')
git_operations(operation='git_branch', action='delete', name='old-feature', confirm=True)

# Worktree
git_operations(operation='git_worktree', action='list')
git_operations(operation='git_worktree', action='add', name='hotfix', branch='main', confirm=True)
git_operations(operation='git_worktree', action='add', name='exp', new_branch=True, confirm=True)
git_operations(operation='git_worktree', action='remove', name='hotfix', confirm=True)

# GitHub issue
git_operations(operation='gh_issue_list', state='open', limit=10)
git_operations(operation='gh_issue_list', assignee='@me')
git_operations(operation='gh_issue_list', search='登录 bug')
git_operations(operation='gh_issue_view', number=42)
git_operations(operation='gh_issue_create', title='Bug: 登录页面崩溃', body='复现步骤：...', confirm=True)
git_operations(operation='gh_issue_edit', number=42, state='closed', confirm=True)
git_operations(operation='gh_issue_edit', number=42, add_label='bug', confirm=True)
git_operations(operation='gh_issue_comment', number=42, body='已在 PR #88 中修复', confirm=True)
```

## 依赖说明

- **Git**：所有 `git_*` 操作均依赖本地安装的 `git` 命令
- **GitHub CLI (`gh`)**：所有 `gh_*` 操作依赖 `gh` CLI，需提前执行 `gh auth login` 完成认证
