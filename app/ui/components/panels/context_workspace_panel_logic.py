import logging
import os
import re

from PySide6.QtWidgets import QMessageBox, QFileDialog
from app.core.app_constants import APP_ROOT

from app.core.context_manager import TokenCounter
from app.ui.dialogs.context_snapshot_dialog import ContextSnapshotDialog
from app.ui.dialogs.context_workspace_plan_binding_dialog import ContextWorkspacePlanBindingDialog
from app.ui.dialogs.context_workspace_common_phrases_dialog import ContextWorkspaceCommonPhrasesDialog
from app.core.logging import get_logger

logger = get_logger("app.ui.context_workspace_panel_logic", side="ui")

class ContextWorkspacePanelLogic:
    def __init__(self, panel, worker=None, runtime_log_panel=None, staging_injector=None):
        self.panel = panel
        self.worker = worker
        self.runtime_log_panel = runtime_log_panel
        self.staging_injector = staging_injector
        self._snapshot_dialog = None
        self._snapshot_request_pending = False
        self._token_counter = TokenCounter()

    def bind(self):
        if self.panel is None:
            return
        self.panel.refresh_requested.connect(self._handle_refresh)
        self.panel.request_conversations.connect(self._handle_request_conversations)
        self.panel.save_system_requested.connect(self._handle_save_system)
        self.panel.save_working_requested.connect(self._handle_save_working)
        self.panel.clear_working_requested.connect(self._handle_clear_working)
        self.panel.clear_long_term_requested.connect(self._handle_clear_long_term)
        self.panel.manual_compact_requested.connect(self._handle_manual_compact)
        self.panel.request_snapshot_requested.connect(self._handle_request_snapshot)
        self.panel.manage_plan_binding_requested.connect(self._handle_manage_plan_binding)
        self.panel.open_common_phrases_requested.connect(self._handle_open_common_phrases)
        if hasattr(self.worker, 'context_workspace_signal'):
            self.worker.context_workspace_signal.connect(self.panel.update_payload)
        if hasattr(self.worker, 'api_conversations_signal'):
            self.worker.api_conversations_signal.connect(self.panel.update_conversation_list)
        if hasattr(self.worker, 'context_snapshot_signal'):
            self.worker.context_snapshot_signal.connect(self._handle_snapshot_payload)

    def initialize(self):
        self._handle_request_conversations()
        self._handle_refresh('')

    def _log(self, text):
        if self.runtime_log_panel is not None and hasattr(self.runtime_log_panel, 'append_log'):
            self.runtime_log_panel.append_log(text)

    def _handle_refresh(self, conversation_id=''):
        try:
            if self.worker and hasattr(self.worker, 'get_context_workspace_payload'):
                target_id = conversation_id or None
                self.worker.get_context_workspace_payload(target_id)
                label = target_id or '当前 active API 对话'
                self._log(f'已请求刷新上下文工作台: {label}')
        except Exception as e:
            self._log(f'刷新上下文工作台失败: {e}')

    def _handle_save_system(self, conversation_id, content):
        try:
            if self.worker and hasattr(self.worker, 'update_context_workspace_system_prompt'):
                self.worker.update_context_workspace_system_prompt(content, conversation_id or None)
        except Exception as e:
            self._log(f'保存 System Prompt 失败: {e}')

    def _handle_save_working(self, conversation_id, data):
        try:
            if self.worker and hasattr(self.worker, 'update_context_workspace_working_memory'):
                self.worker.update_context_workspace_working_memory(data, conversation_id or None)
        except Exception as e:
            self._log(f'保存 Working Memory 失败: {e}')

    def _handle_clear_working(self, conversation_id=''):
        try:
            if self.worker and hasattr(self.worker, 'clear_context_workspace_working_memory'):
                self.worker.clear_context_workspace_working_memory(conversation_id or None)
        except Exception as e:
            self._log(f'清空 Working Memory 失败: {e}')

    def _handle_clear_long_term(self, conversation_id=''):
        try:
            if self.worker and hasattr(self.worker, 'clear_context_workspace_long_term'):
                self.worker.clear_context_workspace_long_term(conversation_id or None)
        except Exception as e:
            self._log(f'清空 Long-term 失败: {e}')

    def _handle_manual_compact(self, conversation_id=''):
        try:
            if self.worker and hasattr(self.worker, 'trigger_api_manual_compact'):
                target_id = conversation_id or None
                self.worker.trigger_api_manual_compact(target_id)
                label = target_id or '当前 active API 对话'
                self._log(f'已请求手动压缩上下文: {label}')
        except Exception as e:
            self._log(f'手动压缩上下文失败: {e}')

    def _handle_request_conversations(self):
        try:
            if self.worker and hasattr(self.worker, 'get_api_conversations'):
                self.worker.get_api_conversations()
                self._log('已请求刷新 API 对话列表')
        except Exception as e:
            self._log(f'刷新 API 对话列表失败: {e}')

    def _handle_request_snapshot(self, conversation_id=''):
        try:
            if self.worker and hasattr(self.worker, 'get_last_request_snapshot'):
                target_id = conversation_id or None
                self._snapshot_request_pending = True
                result = self.worker.get_last_request_snapshot(target_id)
                if result:
                    self._snapshot_request_pending = False
                    self._show_snapshot_dialog(result)
                label = target_id or '当前 active API 对话'
                self._log(f'已请求最近请求快照: {label}')
            else:
                QMessageBox.information(self.panel, '提示', '当前 Worker 不支持上下文快照功能。')
        except Exception as e:
            self._snapshot_request_pending = False
            self._log(f'获取最近请求快照失败: {e}')
            QMessageBox.warning(self.panel, '获取失败', str(e))

    def _handle_snapshot_payload(self, payload):
        try:
            if not self._snapshot_request_pending:
                return
            self._snapshot_request_pending = False
            if not isinstance(payload, dict) or not payload:
                QMessageBox.information(
                    self.panel,
                    '暂无快照',
                    '当前目标对话还没有最近一次请求快照。\n请先发送一条消息后再查看。'
                )
                return
            self._show_snapshot_dialog(payload)
        except Exception as e:
            self._log(f'处理上下文快照失败: {e}')
            QMessageBox.warning(self.panel, '显示失败', str(e))

    def _show_snapshot_dialog(self, snapshot):
        if self._snapshot_dialog is not None:
            try:
                self._snapshot_dialog.close()
            except Exception as e:
                logger.warning(e)
        self._snapshot_dialog = ContextSnapshotDialog(snapshot, self.panel)
        self._snapshot_dialog.show()
        self._snapshot_dialog.raise_()
        self._snapshot_dialog.activateWindow()


    def _handle_open_common_phrases(self):
        try:
            dialog = ContextWorkspaceCommonPhrasesDialog(self.panel)
            if not dialog.exec():
                return
            text = str(dialog.selected_phrase_text() or '').strip()
            if not text:
                return
            if callable(self.staging_injector):
                self.staging_injector(text)
                self._log('已将常用语发送到提示词暂存区')
            else:
                QMessageBox.information(self.panel, '提示', '当前无法连接到对话输入区。')
        except Exception as e:
            self._log(f'打开常用语失败: {e}')
            QMessageBox.warning(self.panel, '常用语失败', str(e))

    def _handle_manage_plan_binding(self, conversation_id=''):
        try:
            working = self.panel.get_working_memory_data()
            bound_plan = working.get('bound_plan') if isinstance(working, dict) else {}
            dialog = ContextWorkspacePlanBindingDialog(bound_plan, self.panel)
            if not dialog.exec():
                return
            action = dialog.selected_action()
            if action == 'bind':
                self._bind_plan_for_conversation(conversation_id or None, working)
            elif action == 'unbind':
                self._unbind_plan_for_conversation(conversation_id or None, working)
        except Exception as e:
            self._log(f'处理计划书绑定失败: {e}')
            QMessageBox.warning(self.panel, '计划书绑定失败', str(e))

    def _bind_plan_for_conversation(self, conversation_id=None, working=None):
        path, _ = QFileDialog.getOpenFileName(
            self.panel,
            '选择计划书',
            APP_ROOT,
            '计划书文件 (*.md *.txt);;Markdown (*.md);;Text (*.txt);;所有文件 (*)'
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            raise RuntimeError(f'读取计划书失败: {e}')
        plan_data = self._build_plan_data(path, content)
        next_working = dict(working or {})
        next_working['bound_plan'] = plan_data
        self._handle_save_working(conversation_id or '', next_working)
        self._handle_refresh(conversation_id or '')
        self._log(f'已绑定计划书: {plan_data.get("title") or path}')

    def _unbind_plan_for_conversation(self, conversation_id=None, working=None):
        next_working = dict(working or {})
        if 'bound_plan' not in next_working:
            QMessageBox.information(self.panel, '提示', '当前任务尚未绑定计划书。')
            return
        next_working.pop('bound_plan', None)
        self._handle_save_working(conversation_id or '', next_working)
        self._handle_refresh(conversation_id or '')
        self._log('已解绑当前计划书')

    def _build_plan_data(self, path, content):
        normalized = str(content or '')
        title = self._extract_plan_title(path, normalized)
        token_count = self._token_counter.count(normalized)
        pending, done = self._parse_checklist_items(normalized)
        summary = self._build_plan_summary(title, pending, done, token_count)
        return {
            'path': path,
            'title': title,
            'summary': summary,
            'content': normalized,
            'token_count': token_count,
            'checklist_pending': pending,
            'checklist_done': done,
        }

    def _extract_plan_title(self, path, content):
        for line in str(content or '').splitlines():
            stripped = line.strip()
            if stripped.startswith('#'):
                candidate = stripped.lstrip('#').strip()
                if candidate:
                    return candidate
        return os.path.basename(path)

    def _parse_checklist_items(self, content):
        pending = []
        done = []
        pattern = re.compile(r'^\s*[-*]\s*\[( |x|X)\]\s+(.*)$')
        for line in str(content or '').splitlines():
            match = pattern.match(line)
            if not match:
                continue
            flag = match.group(1)
            text = str(match.group(2) or '').strip()
            if not text:
                continue
            if flag.lower() == 'x':
                done.append(text)
            else:
                pending.append(text)
        return pending, done

    def _build_plan_summary(self, title, pending, done, token_count):
        parts = []
        if title:
            parts.append(f'计划书：{title}')
        parts.append(f'Tokens：{token_count}')
        parts.append(f'待办 {len(pending)} 项')
        parts.append(f'已完成 {len(done)} 项')
        return ' · '.join(parts)
