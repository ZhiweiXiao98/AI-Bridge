# filename: app/ui/components/panels/git_config_dialog.py
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QFrame, QSizePolicy, QGridLayout
)


class GitConfigDialog(QDialog):
    request_refresh = Signal()
    request_init_repo = Signal()
    request_save_user = Signal(str, str)
    request_set_remote = Signal(str, str)
    request_set_upstream = Signal()
    request_run_checks = Signal()
    request_recommended_action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot_payload = {}
        self._checks_payload = {}
        self._busy_states = {
            'snapshot': False,
            'checks': False,
            'action': False,
        }
        self.setWindowTitle('Git 配置与诊断')
        self.resize(720, 560)
        self.setMinimumSize(520, 420)
        self._build_ui()
        self._apply_styles()
        self._refresh_busy_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = QLabel('Git 控制台')
        self.title_label.setObjectName('GitTitleLabel')
        self.subtitle_label = QLabel('紧凑配置 · 远程绑定 · 连通性诊断')
        self.subtitle_label.setObjectName('GitSubtitleLabel')
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        header.addLayout(title_box)
        header.addStretch()
        self.busy_badge = QLabel('空闲')
        self.busy_badge.setObjectName('GitBusyBadge')
        header.addWidget(self.busy_badge, alignment=Qt.AlignTop)
        root.addLayout(header)

        self.summary_card = QFrame()
        self.summary_card.setObjectName('GitSummaryCard')
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(2)
        self.summary_headline = QLabel('建议先运行检测，确认当前 Git 配置状态')
        self.summary_headline.setObjectName('GitSummaryHeadline')
        self.summary_desc = QLabel('如果你是第一次在这台设备上使用 Git，建议按提示逐步完成配置。')
        self.summary_desc.setObjectName('GitSummaryDesc')
        self.summary_desc.setWordWrap(True)
        summary_layout.addWidget(self.summary_headline)
        summary_layout.addWidget(self.summary_desc)
        root.addWidget(self.summary_card)

        cards = QGridLayout()
        cards.setHorizontalSpacing(8)
        cards.setVerticalSpacing(8)
        root.addLayout(cards)

        self.card_repo = self._create_stat_card('仓库', '--')
        self.card_branch = self._create_stat_card('分支', '--')
        self.card_upstream = self._create_stat_card('上游', '--')
        self.card_remote = self._create_stat_card('远程', '--')
        self.card_sync = self._create_stat_card('同步', '↑0 ↓0')
        self.card_git = self._create_stat_card('Git', '--')

        cards.addWidget(self.card_repo['frame'], 0, 0)
        cards.addWidget(self.card_branch['frame'], 0, 1)
        cards.addWidget(self.card_upstream['frame'], 0, 2)
        cards.addWidget(self.card_remote['frame'], 1, 0)
        cards.addWidget(self.card_sync['frame'], 1, 1)
        cards.addWidget(self.card_git['frame'], 1, 2)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        root.addLayout(content_row, 1)

        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        content_row.addLayout(left_col, 1)

        identity_card, identity_layout = self._create_content_card('身份配置')
        identity_layout.addWidget(self._make_field_label('Git 用户名'))
        self.input_user_name = QLineEdit()
        self.input_user_name.setPlaceholderText('例如：ZhiweiXiao98')
        identity_layout.addWidget(self.input_user_name)
        identity_layout.addWidget(self._make_field_label('Git 邮箱'))
        self.input_user_email = QLineEdit()
        self.input_user_email.setPlaceholderText('例如：name@example.com')
        identity_layout.addWidget(self.input_user_email)
        self.btn_save_user = QPushButton('保存身份')
        self.btn_save_user.clicked.connect(self._emit_save_user)
        identity_layout.addWidget(self.btn_save_user)
        left_col.addWidget(identity_card)

        remote_card, remote_layout = self._create_content_card('远程仓库')
        remote_layout.addWidget(self._make_field_label('origin URL'))
        self.input_origin_url = QLineEdit()
        self.input_origin_url.setPlaceholderText('https://github.com/owner/repo.git 或 git@github.com:owner/repo.git')
        remote_layout.addWidget(self.input_origin_url)

        remote_btn_row_1 = QHBoxLayout()
        remote_btn_row_1.setSpacing(8)
        self.btn_set_remote = QPushButton('设置 origin')
        self.btn_set_remote.clicked.connect(self._emit_set_remote)
        self.btn_set_upstream = QPushButton('绑定 upstream')
        self.btn_set_upstream.clicked.connect(self.request_set_upstream.emit)
        remote_btn_row_1.addWidget(self.btn_set_remote)
        remote_btn_row_1.addWidget(self.btn_set_upstream)
        remote_layout.addLayout(remote_btn_row_1)

        remote_btn_row_2 = QHBoxLayout()
        remote_btn_row_2.setSpacing(8)
        self.btn_init_repo = QPushButton('初始化仓库')
        self.btn_init_repo.clicked.connect(self.request_init_repo.emit)
        self.btn_refresh = QPushButton('刷新状态')
        self.btn_refresh.clicked.connect(self.request_refresh.emit)
        remote_btn_row_2.addWidget(self.btn_init_repo)
        remote_btn_row_2.addWidget(self.btn_refresh)
        remote_layout.addLayout(remote_btn_row_2)
        left_col.addWidget(remote_card)

        self.repo_path_label = QLabel('仓库路径：--')
        self.repo_path_label.setObjectName('GitMetaLabel')
        self.repo_path_label.setWordWrap(True)
        self.repo_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left_col.addWidget(self.repo_path_label)

        right_col = QVBoxLayout()
        right_col.setSpacing(10)
        content_row.addLayout(right_col, 1)

        check_card, check_layout = self._create_content_card('连接诊断')
        check_top = QHBoxLayout()
        self.btn_run_checks = QPushButton('运行检测')
        self.btn_run_checks.clicked.connect(self.request_run_checks.emit)
        check_top.addWidget(self.btn_run_checks)
        check_top.addStretch()
        check_layout.addLayout(check_top)
        self.checks_output = QTextEdit()
        self.checks_output.setReadOnly(True)
        self.checks_output.setPlaceholderText('点击“运行检测”查看 HTTPS / SSH / upstream 状态')
        self.checks_output.setMinimumHeight(220)
        check_layout.addWidget(self.checks_output)
        right_col.addWidget(check_card, 1)

        tip_card, tip_layout = self._create_content_card('快速提示')
        tip_layout.setSpacing(6)
        self.tip_label = QLabel(
            '• 建议先点击“刷新状态”读取当前仓库信息\n'
            '• 新手建议优先使用 HTTPS 远程地址\n'
            '• 当前面板会根据状态给出下一步推荐动作'
        )
        self.tip_label.setObjectName('GitTipLabel')
        self.tip_label.setWordWrap(True)
        tip_layout.addWidget(self.tip_label)
        right_col.addWidget(tip_card)

        footer = QHBoxLayout()
        footer.addStretch()
        self.btn_recommended = QPushButton('推荐：运行检测')
        self.btn_recommended.clicked.connect(self._emit_recommended_action)
        footer.addWidget(self.btn_recommended)
        self.btn_close = QPushButton('关闭')
        self.btn_close.clicked.connect(self.accept)
        footer.addWidget(self.btn_close)
        root.addLayout(footer)

        self._apply_tooltips({})

    def _create_content_card(self, title):
        frame = QFrame()
        frame.setObjectName('GitCard')
        outer_layout = QVBoxLayout(frame)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        title_label = QLabel(title)
        title_label.setObjectName('GitCardTitle')
        title_label.setContentsMargins(12, 10, 12, 0)
        outer_layout.addWidget(title_label)

        body = QFrame()
        body.setObjectName('GitCardBody')
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(8)
        outer_layout.addWidget(body)

        return frame, body_layout

    def _create_stat_card(self, title, value):
        frame = QFrame()
        frame.setObjectName('GitStatCard')
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName('GitStatTitle')
        value_label = QLabel(value)
        value_label.setObjectName('GitStatValue')
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return {'frame': frame, 'title': title_label, 'value': value_label}

    def _make_field_label(self, text):
        label = QLabel(text)
        label.setObjectName('GitFieldLabel')
        return label

    def _apply_styles(self):
        self.setStyleSheet("""
            QDialog {
                background: #08111f;
                color: #E5EEF9;
            }
            QLabel {
                color: #E5EEF9;
            }
            QLabel#GitTitleLabel {
                font-size: 22px;
                font-weight: 700;
                color: #F8FBFF;
            }
            QLabel#GitSubtitleLabel {
                font-size: 12px;
                color: #8CA3C4;
            }
            QLabel#GitBusyBadge {
                background: rgba(37, 99, 235, 0.18);
                color: #9CC3FF;
                border: 1px solid rgba(59, 130, 246, 0.40);
                border-radius: 12px;
                padding: 5px 10px;
                font-weight: 600;
            }
            QFrame#GitSummaryCard {
                background: rgba(29, 78, 216, 0.12);
                border: 1px solid rgba(59, 130, 246, 0.35);
                border-radius: 12px;
            }
            QLabel#GitSummaryHeadline {
                color: #F8FBFF;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#GitSummaryDesc {
                color: #A9BDD8;
                font-size: 11px;
            }
            QFrame#GitCard, QFrame#GitStatCard {
                background: #0F1B2D;
                border: 1px solid #1F314A;
                border-radius: 12px;
            }
            QLabel#GitCardTitle, QLabel#GitStatTitle {
                color: #8CA3C4;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#GitStatValue {
                color: #F8FBFF;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#GitFieldLabel {
                color: #9FB2CC;
                font-size: 11px;
            }
            QLabel#GitMetaLabel, QLabel#GitTipLabel {
                color: #A9BDD8;
                font-size: 11px;
            }
            QLineEdit, QTextEdit {
                background: #132238;
                color: #F8FBFF;
                border: 1px solid #29415F;
                border-radius: 8px;
                padding: 8px 10px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #3B82F6;
            }
            QPushButton {
                background: #1D4ED8;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                min-height: 34px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #2563EB;
            }
            QPushButton:disabled {
                background: #334155;
                color: #CBD5E1;
            }
        """)

    def _emit_save_user(self):
        self.request_save_user.emit(
            self.input_user_name.text().strip(),
            self.input_user_email.text().strip(),
        )

    def _emit_set_remote(self):
        self.request_set_remote.emit('origin', self.input_origin_url.text().strip())


    def _emit_recommended_action(self):
        action = self.btn_recommended.property('recommended_action') or 'run_checks'
        self.request_recommended_action.emit(str(action))

    def set_guidance(self, guidance: dict):
        guidance = guidance or {}
        self.summary_headline.setText(str(guidance.get('headline', '建议先运行检测，确认当前 Git 配置状态') or '建议先运行检测，确认当前 Git 配置状态'))
        self.summary_desc.setText(str(guidance.get('description', '如果你是第一次在这台设备上使用 Git，建议按提示逐步完成配置。') or '如果你是第一次在这台设备上使用 Git，建议按提示逐步完成配置。'))
        tips = guidance.get('tips', []) or []
        if tips:
            self.tip_label.setText('\n'.join([f'• {str(item)}' for item in tips if str(item).strip()]))
        self.btn_recommended.setText(str(guidance.get('next_action_text', '推荐：运行检测') or '推荐：运行检测'))
        self.btn_recommended.setProperty('recommended_action', str(guidance.get('next_action', 'run_checks') or 'run_checks'))
        self._apply_tooltips(guidance.get('tooltips', {}) or {})

    def _apply_tooltips(self, tooltips: dict):
        tooltips = tooltips or {}
        self.card_repo['frame'].setToolTip(tooltips.get('repo', ''))
        self.card_branch['frame'].setToolTip(tooltips.get('branch', ''))
        self.card_upstream['frame'].setToolTip(tooltips.get('upstream', ''))
        self.card_remote['frame'].setToolTip(tooltips.get('remote', ''))
        self.card_sync['frame'].setToolTip(tooltips.get('sync', ''))
        self.card_git['frame'].setToolTip(tooltips.get('git', ''))
        self.input_user_name.setToolTip(tooltips.get('user_name', ''))
        self.input_user_email.setToolTip(tooltips.get('user_email', ''))
        self.input_origin_url.setToolTip(tooltips.get('origin_url', ''))
        self.btn_init_repo.setToolTip(tooltips.get('init_repo', ''))
        self.btn_save_user.setToolTip(tooltips.get('save_user', ''))
        self.btn_set_remote.setToolTip(tooltips.get('set_remote', ''))
        self.btn_set_upstream.setToolTip(tooltips.get('set_upstream', ''))
        self.btn_refresh.setToolTip(tooltips.get('refresh', ''))
        self.btn_run_checks.setToolTip(tooltips.get('run_checks', ''))
        self.btn_recommended.setToolTip(tooltips.get('recommended_action', ''))
        self.checks_output.setToolTip(tooltips.get('checks_output', ''))
    def set_snapshot_view_model(self, vm: dict):
        vm = vm or {}
        self.card_repo['value'].setText(str(vm.get('repo_status', '--') or '--'))
        self.card_branch['value'].setText(str(vm.get('branch', '--') or '--'))
        self.card_upstream['value'].setText(str(vm.get('upstream', '--') or '--'))
        self.card_remote['value'].setText(str(vm.get('remote', '--') or '--'))
        self.card_sync['value'].setText(str(vm.get('sync', '↑0 ↓0') or '↑0 ↓0'))
        self.card_git['value'].setText(str(vm.get('git_version', '--') or '--'))
        self.repo_path_label.setText(f"仓库路径：{str(vm.get('repo_path', '--') or '--')}")
        self.input_user_name.setText(str(vm.get('user_name', '') or ''))
        self.input_user_email.setText(str(vm.get('user_email', '') or ''))
        if not self.input_origin_url.text().strip():
            self.input_origin_url.setText(str(vm.get('origin_url', '') or ''))
        self._snapshot_payload = dict(vm.get('raw_payload', {}) or {})

    def set_checks_text(self, text: str):
        self.checks_output.setPlainText(str(text or '暂无检测结果'))

    def set_busy_state(self, key: str, busy: bool):
        if key not in self._busy_states:
            return
        self._busy_states[key] = bool(busy)
        self._refresh_busy_ui()

    def clear_busy_states(self):
        for key in list(self._busy_states.keys()):
            self._busy_states[key] = False
        self._refresh_busy_ui()

    def _refresh_busy_ui(self):
        snapshot_busy = self._busy_states.get('snapshot', False)
        checks_busy = self._busy_states.get('checks', False)
        action_busy = self._busy_states.get('action', False)
        any_busy = snapshot_busy or checks_busy or action_busy
        if action_busy:
            badge_text = '执行中'
        elif checks_busy:
            badge_text = '检测中'
        elif snapshot_busy:
            badge_text = '刷新中'
        else:
            badge_text = '空闲'
        self.busy_badge.setText(badge_text)
        self.btn_save_user.setEnabled(not any_busy)
        self.btn_set_remote.setEnabled(not any_busy)
        self.btn_set_upstream.setEnabled(not any_busy)
        self.btn_init_repo.setEnabled(not any_busy)
        self.btn_refresh.setEnabled(not any_busy)
        self.btn_run_checks.setEnabled(not any_busy)
        self.btn_recommended.setEnabled(not any_busy)
