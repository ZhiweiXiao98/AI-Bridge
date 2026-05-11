# filename: app/ui/components/panels/git_control_panel_presenter.py
# Presentation helpers: 将 Git 原始 payload 转换为配置对话框可直接渲染的数据。


class GitControlPanelPresenter:
    @staticmethod
    def _normalize_origin_type(origin_type: str, origin_url: str) -> str:
        origin_type = str(origin_type or '').strip().upper()
        origin_url = str(origin_url or '').strip()
        if origin_type:
            return origin_type
        if not origin_url:
            return '未配置'
        if origin_url.startswith('git@') or origin_url.startswith('ssh://'):
            return 'SSH'
        if origin_url.startswith('http://') or origin_url.startswith('https://'):
            return 'HTTPS'
        return '未识别'

    @staticmethod
    def build_snapshot_view_model(payload: dict) -> dict:
        payload = payload or {}
        is_repo = bool(payload.get('is_repo'))
        branch = str(payload.get('branch', '--') or '--')
        upstream = str(payload.get('upstream', '') or '')
        origin_url = str(payload.get('origin_url', '') or '')
        origin_type = GitControlPanelPresenter._normalize_origin_type(payload.get('origin_type', ''), origin_url)
        git_version = str(payload.get('git_version', '未检测到 Git') or '未检测到 Git')
        repo_path = str(payload.get('repo_path', '--') or '--')
        ahead = int(payload.get('ahead', 0) or 0)
        behind = int(payload.get('behind', 0) or 0)
        user_name = str(payload.get('user_name', '') or '')
        user_email = str(payload.get('user_email', '') or '')

        return {
            'repo_status': '已初始化' if is_repo else '未初始化',
            'branch': branch,
            'upstream': upstream or '未绑定',
            'remote': origin_type,
            'sync': f'↑{ahead} ↓{behind}',
            'git_version': git_version,
            'repo_path': repo_path,
            'origin_url': origin_url,
            'user_name': user_name,
            'user_email': user_email,
            'raw_payload': payload,
        }

    @staticmethod
    def build_checks_text(payload: dict) -> str:
        payload = payload or {}
        lines = []
        for item in payload.get('checks', []) or []:
            ok = bool(item.get('ok'))
            icon = '✅' if ok else '❌'
            label = str(item.get('label', '检查项') or '检查项')
            detail = str(item.get('detail', '') or '').strip()
            lines.append(f'{icon} {label}')
            if detail:
                lines.append(f'    {detail}')
        return '\n'.join(lines).strip() or '暂无检测结果'

    @staticmethod
    def build_setup_guidance(snapshot_vm: dict, checks_payload: dict) -> dict:
        snapshot_vm = snapshot_vm or {}
        checks_payload = checks_payload or {}

        repo_status = str(snapshot_vm.get('repo_status', '未初始化') or '未初始化')
        branch = str(snapshot_vm.get('branch', '--') or '--')
        upstream = str(snapshot_vm.get('upstream', '未绑定') or '未绑定')
        remote = str(snapshot_vm.get('remote', '未配置') or '未配置')
        origin_url = str(snapshot_vm.get('origin_url', '') or '')
        user_name = str(snapshot_vm.get('user_name', '') or '').strip()
        user_email = str(snapshot_vm.get('user_email', '') or '').strip()
        git_version = str(snapshot_vm.get('git_version', '未检测到 Git') or '未检测到 Git')

        checks = checks_payload.get('checks', []) or []
        ssh_failed = False
        https_failed = False
        for item in checks:
            label = str(item.get('label', '') or '')
            ok = bool(item.get('ok'))
            if 'SSH' in label and not ok:
                ssh_failed = True
            if 'HTTPS' in label and not ok:
                https_failed = True

        next_action = 'run_checks'
        status_level = 'info'
        headline = '建议先运行检测，确认当前 Git 配置状态'
        description = '如果你是第一次在这台设备上使用 Git，建议按提示逐步完成配置。'
        tips = []

        if '未检测到' in git_version:
            status_level = 'warning'
            headline = '当前设备似乎未正确安装 Git'
            description = '请先安装 Git，再回来执行仓库初始化和远程配置。'
            next_action = 'refresh'
            tips = [
                '安装 Git 后请点击“刷新状态”重新读取版本信息。',
                '若版本仍为空，请检查 Git 是否加入系统 PATH。',
            ]
        elif repo_status != '已初始化':
            status_level = 'warning'
            headline = '当前目录尚未初始化 Git 仓库'
            description = '建议先点击“初始化仓库”，再配置身份、远程和上游分支。'
            next_action = 'init_repo'
            tips = [
                '初始化仓库只需执行一次。',
                '初始化后通常会生成 main 或 master 分支。',
            ]
        elif not user_name or not user_email:
            status_level = 'warning'
            headline = 'Git 身份未配置完整'
            description = '请填写用户名和邮箱，便于后续提交记录归属到正确身份。'
            next_action = 'save_user'
            tips = [
                '用户名会显示在提交记录中。',
                '邮箱建议与 GitHub 绑定邮箱保持一致。',
            ]
        elif not origin_url:
            status_level = 'warning'
            headline = '尚未配置远程仓库 origin'
            description = '请输入仓库地址并点击“设置 origin”，这样当前项目才能连接到远程仓库。'
            next_action = 'set_remote'
            tips = [
                '新手建议优先使用 HTTPS 地址。',
                '设置 origin 后，通常还需要绑定 upstream。',
            ]
        elif upstream == '未绑定':
            status_level = 'warning'
            headline = f'当前分支 {branch} 尚未绑定 upstream'
            description = '建议点击“绑定 upstream”，后续 push / pull 会更顺畅。'
            next_action = 'set_upstream'
            tips = [
                'upstream 用于建立本地分支与远程分支的追踪关系。',
                '绑定后通常可以直接执行 push，而无需每次指定分支。',
            ]
        else:
            status_level = 'success'
            headline = '当前 Git 基础配置已完成'
            description = '你已经具备常规提交、备份和推送所需的基础配置。'
            next_action = 'run_checks'
            tips = [
                '如果你刚换了设备，建议再运行一次检测确认认证方式可用。',
            ]

        if remote == 'HTTPS':
            tips.append('当前远程使用 HTTPS。若 SSH 检测失败，通常不影响当前工作流。')
            tips.append('使用 HTTPS 推送到 GitHub 时，通常需要使用 PAT 而不是账户密码。')
            if ssh_failed and status_level == 'success':
                description = '当前使用 HTTPS，SSH 检测失败不会影响当前推送流程。'
        elif remote == 'SSH':
            tips.append('当前远程使用 SSH。请确保当前设备已生成 SSH key 并添加到 GitHub。')
            tips.append('若 SSH 连通性异常，可尝试配置 ssh.github.com:443。')
            if ssh_failed:
                status_level = 'warning'
                headline = '当前远程使用 SSH，但 SSH 连通性异常'
                description = '请检查 SSH key、公钥上传情况，或尝试 443 端口回退配置。'
                next_action = 'run_checks'
        elif remote == '未配置':
            tips.append('尚未设置远程仓库时，可以先完成仓库初始化和身份配置。')
        else:
            tips.append('如果远程类型无法识别，建议检查 origin URL 格式是否正确。')

        if https_failed and remote == 'HTTPS':
            status_level = 'warning'
            headline = '当前远程使用 HTTPS，但 HTTPS 连通性存在异常'
            description = '请检查网络、代理或 GitHub 认证信息（PAT）是否正确。'
            next_action = 'run_checks'

        tooltips = {
            'repo': '显示当前目录是否已初始化为 Git 仓库。若未初始化，请先点击“初始化仓库”。',
            'branch': '显示当前检出的分支名称。首次初始化后通常为 main 或 master。',
            'upstream': '上游分支用于建立本地分支与远程分支的追踪关系。绑定后可直接 push / pull。',
            'remote': '显示当前 origin 使用的是 HTTPS 还是 SSH。新手建议优先使用 HTTPS。',
            'sync': '↑ 表示本地领先远程的提交数，↓ 表示本地落后远程的提交数。',
            'git': '显示当前设备上的 Git 版本。若为空或未检测到，请检查 Git 是否已正确安装。',
            'user_name': '用于写入 git config user.name。提交记录会显示这个名字。',
            'user_email': '用于写入 git config user.email。建议与 GitHub 绑定邮箱一致。',
            'origin_url': '请输入仓库地址。支持 HTTPS 和 SSH 两种格式。新手建议优先使用 HTTPS。',
            'init_repo': '当当前目录还没有 .git 时使用。通常只需执行一次。',
            'save_user': '保存当前设备上的 Git 用户名与邮箱配置。',
            'set_remote': '把当前项目连接到远程仓库地址。通常使用远程名 origin。',
            'set_upstream': '把当前分支与 origin 上对应分支建立追踪关系，便于后续直接 push。',
            'refresh': '重新读取当前仓库状态、远程信息和身份配置。',
            'run_checks': '检查 Git 环境、origin、upstream 以及 HTTPS/SSH 连通性。',
            'checks_output': '这里显示详细检查结果。若当前远程使用 HTTPS，则 SSH 失败通常不影响推送。',
            'recommended_action': '根据当前状态，自动推荐下一步最适合执行的操作。',
        }

        return {
            'status_level': status_level,
            'headline': headline,
            'description': description,
            'next_action': next_action,
            'next_action_text': {
                'init_repo': '推荐：初始化仓库',
                'save_user': '推荐：保存身份',
                'set_remote': '推荐：设置 origin',
                'set_upstream': '推荐：绑定 upstream',
                'refresh': '推荐：刷新状态',
                'run_checks': '推荐：运行检测',
            }.get(next_action, '推荐：运行检测'),
            'tips': tips[:4],
            'tooltips': tooltips,
        }
