# Presentation helpers: 将原始 payload 转换为面板可直接渲染的数据。

import json
from datetime import datetime


class ContextWorkspacePanelPresenter:
    @staticmethod
    def _format_ts(value) -> str:
        try:
            ts = float(value or 0)
            if ts <= 0:
                return '-'
            return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return '-'

    @staticmethod
    def _build_history_preview_text(items: list) -> str:
        lines = []
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            role = str(item.get('role', '-') or '-')
            kind = str(item.get('kind', 'text') or 'text')
            content = str(item.get('content', '') or '').strip().replace(chr(10), ' ')
            if len(content) > 140:
                content = content[:140] + '...'
            lines.append(f'[{role}/{kind}] {content}')
        return chr(10).join(lines)

    @staticmethod
    def _truncate(text: str, limit: int = 90) -> str:
        text = str(text or '').strip().replace(chr(10), ' ')
        if len(text) <= limit:
            return text
        return text[:limit] + '...'

    @staticmethod
    def build_view_model(payload: dict) -> dict:
        payload = payload or {}
        system = payload.get('system', {}) or {}
        usage = payload.get('usage', {}) or {}
        working = payload.get('working_memory', {}) or {}
        long_term = payload.get('long_term', {}) or {}
        ctx_cfg = payload.get('context_config', {}) or {}
        compact = payload.get('compact', {}) or {}

        title = payload.get('conversation_title', '未命名对话')
        conv_id = payload.get('conversation_id', '-')
        runtime_profile = payload.get('runtime_profile_key', '-')
        mode = payload.get('mode', '-')
        configured_profile = payload.get('configured_profile_key', '-')
        meta_text = f'目标: {title} | ID: {conv_id} | 配置: {configured_profile} -> {runtime_profile} | 模式: {mode}'

        blocks = system.get('blocks', []) or []
        source_lines = [
            f"是否注入技能说明: {system.get('inject_skills_prompt', False)}",
            f"最终 System Tokens: {system.get('final_tokens', 0)} / Budget: {system.get('system_budget', 8000)} / Over: {system.get('over_budget', False)}",
        ]
        block_lines = []
        if blocks:
            source_lines.append('')
            source_lines.append('--- Prompt Blocks ---')
            for block in blocks:
                label = block.get('label', block.get('name', 'unknown'))
                enabled = block.get('enabled', False)
                tokens = block.get('tokens', 0)
                content = str(block.get('content', '') or '').strip()
                source_lines.append(f'[{label}] enabled={enabled} | tokens={tokens}')
                block_lines.extend([
                    f'=== {label} ===',
                    f'enabled: {enabled}',
                    f'tokens: {tokens}',
                    content if content else '(empty)',
                    '',
                ])

        fragments = long_term.get('fragments', []) or []
        sep = chr(10) + chr(10) + ('-' * 40) + chr(10) + chr(10)

        runtime_lines = [
            f"当前配置: {payload.get('configured_profile_key', '-')}",
            f"实际运行配置: {payload.get('runtime_profile_key', '-')}",
            f"最大上下文容量: {ctx_cfg.get('max_window_tokens', 128000)}",
            f"System Prompt 预算: {ctx_cfg.get('system_budget', 8000)}",
            f"历史轮数上限: {ctx_cfg.get('max_history_turns', 50)}",
            f"短期上下文预算: {ctx_cfg.get('short_term_budget', 80000)}",
            f"输出预留: {ctx_cfg.get('output_reserve', 16000)}",
            f"历史预览条数: {len(payload.get('history_preview', []))}",
        ]

        compact_lines = [
            f"压缩次数: {compact.get('compact_count', 0)}",
            f"最近压缩时间: {ContextWorkspacePanelPresenter._format_ts(compact.get('last_compacted_at', 0))}",
            f"最近触发原因: {compact.get('last_trigger', '') or '-'}",
            f"连续失败次数: {compact.get('consecutive_failures', 0)}",
            f"最近保留原文数: {compact.get('recent_preserved_count', 0)}",
            f"禁用直到手动恢复: {'是' if compact.get('disabled_until_manual_retry', False) else '否'}",
        ]

        summary_preview = str(compact.get('last_summary_preview', '') or '').strip()
        if not summary_preview:
            summary_preview = '暂无 compact summary 预览。'

        history_preview_text = ContextWorkspacePanelPresenter._build_history_preview_text(payload.get('history_preview', []))
        if not history_preview_text:
            history_preview_text = '暂无 history 预览。'

        system_edit_text = system.get('conversation_system_prompt', '')
        system_final_text = system.get('final_system_prompt', '')
        working_text = json.dumps(working, ensure_ascii=False, indent=2)
        long_term_text = sep.join(fragments) if fragments else ''

        current_goal = str(working.get('current_goal', '') or '').strip()
        current_step = str(working.get('current_step', '') or '').strip()
        current_files = working.get('current_files', []) or []
        recent_tool_results = working.get('recent_tool_results', []) or []
        failure_reason = str(working.get('failure_reason', '') or '').strip()
        bound_plan = working.get('bound_plan', {}) or {}
        bound_plan_title = str(bound_plan.get('title', '') or '').strip()
        bound_plan_path = str(bound_plan.get('path', '') or '').strip()
        bound_plan_tokens = int(bound_plan.get('token_count', 0) or 0)
        checklist_pending = bound_plan.get('checklist_pending', []) or []
        checklist_done = bound_plan.get('checklist_done', []) or []

        total_used = int(usage.get('total_used', 0) or 0)
        total_budget = int(usage.get('total_budget', 0) or 0)
        utilization = usage.get('utilization', 0)
        history_turns = int(usage.get('history_turns', 0) or 0)
        system_empty = not bool(system_edit_text.strip())
        long_term_empty = len(fragments) == 0
        compact_count = int(compact.get('compact_count', 0) or 0)
        compact_disabled = bool(compact.get('disabled_until_manual_retry', False))

        return {
            'meta_text': meta_text,
            'payload_conversation_id': (payload.get('conversation_id') or '').strip(),
            'title_text': str(title or '未命名对话'),
            'conv_id_text': str(conv_id or '-'),
            'profile_text': f"{configured_profile} → {runtime_profile}",
            'mode_text': str(mode or '-'),
            'follow_hint_text': '跟随当前 API 对话' if payload.get('conversation_id') else '可手动锁定指定对话',
            'system_source_text': chr(10).join(source_lines),
            'system_blocks_text': chr(10).join(block_lines).strip(),
            'system_edit_text': system_edit_text,
            'system_final_text': system_final_text,
            'working_text': working_text,
            'long_term_count': len(fragments),
            'long_term_text': long_term_text,
            'usage': usage,
            'runtime_text': chr(10).join(runtime_lines),
            'compact_text': chr(10).join(compact_lines),
            'compact_summary_text': summary_preview,
            'history_preview_text': history_preview_text,
            'system_status_text': '已配置' if not system_empty else '未设置',
            'system_summary_text': (
                f"来源 {len(blocks)} 项 · 最终 {system.get('final_tokens', 0)} tokens · "
                f"技能提示 {'已注入' if system.get('inject_skills_prompt', False) else '未注入'}"
            ),
            'system_preview_text': ContextWorkspacePanelPresenter._truncate(system_edit_text or system_final_text or '暂无系统说明', 96),
            'task_status_text': '进行中' if working else '空闲',
            'task_summary_text': (
                f"目标：{ContextWorkspacePanelPresenter._truncate(current_goal or '暂无', 40)}\n"
                f"步骤：{ContextWorkspacePanelPresenter._truncate(current_step or '暂无', 40)}"
                + (f"\n计划书：{ContextWorkspacePanelPresenter._truncate(bound_plan_title or '已绑定', 40)}" if (bound_plan_title or bound_plan_path) else '')
            ),
            'task_meta_text': (
                f"相关文件 {len(current_files)} 个 · 工具结果 {len(recent_tool_results)} 条"
                + (f" · 失败：{ContextWorkspacePanelPresenter._truncate(failure_reason, 20)}" if failure_reason else '')
                + (f" · 计划书 {bound_plan_tokens:,} tokens" if bound_plan_tokens > 0 else '')
                + (f" · 待办 {len(checklist_pending)} 项" if (bound_plan_title or bound_plan_path) else '')
                + (f" · 已完成 {len(checklist_done)} 项" if (bound_plan_title or bound_plan_path) else '')
            ),
            'long_term_status_text': '已加载' if not long_term_empty else '空',
            'long_term_summary_text': f"记忆片段 {len(fragments)} 条",
            'long_term_preview_text': ContextWorkspacePanelPresenter._truncate(fragments[0] if fragments else '暂无长期记忆内容', 96),
            'capacity_status_text': (
                '紧张' if float(utilization or 0) >= 85 else '注意' if float(utilization or 0) >= 60 else '健康'
            ),
            'capacity_summary_text': f"{utilization}% · {total_used:,} / {total_budget:,} · {history_turns} turns",
            'capacity_preview_text': f"输出预留 {ctx_cfg.get('output_reserve', 16000)} tokens",
            'compact_status_text': '已禁用' if compact_disabled else '正常',
            'compact_summary_line_text': f"压缩 {compact_count} 次 · 最近 {ContextWorkspacePanelPresenter._format_ts(compact.get('last_compacted_at', 0))}",
            'compact_preview_text': ContextWorkspacePanelPresenter._truncate(summary_preview, 96),
        }
