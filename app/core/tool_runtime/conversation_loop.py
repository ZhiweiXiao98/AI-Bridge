from typing import Any, Dict, Optional

from app.core.tool_runtime.models import ToolRoundResult
from app.core.tool_runtime.policies import get_default_tool_loop_policy


class ToolConversationLoop:
    def __init__(self, api_source=None, tool_router=None, policy: Optional[Dict[str, Any]] = None):
        self.api_source = api_source
        self.tool_router = tool_router
        self.policy = dict(get_default_tool_loop_policy())
        if isinstance(policy, dict):
            self.policy.update(policy)

    def run_api_loop(self, conversation_id: str = '') -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'executed': False,
            'loop_count': 0,
            'stopped_reason': 'disabled',
            'final_reply': '',
            'msgs': [],
            'tool_rounds': [],
            'selected_protocols': [],
            'ephemeral_messages': [],
            'round_finalized': False,
        }

        auto_followup_enabled = bool(self.policy.get('auto_followup_enabled', True))
        max_rounds = int(self.policy.get('max_followup_rounds', 300) or 0)
        if not auto_followup_enabled:
            result['stopped_reason'] = 'auto_followup_disabled'
            return result
        if not self.api_source or not self.tool_router:
            result['stopped_reason'] = 'runtime_unavailable'
            return result

        active_conv_id = conversation_id or getattr(getattr(self.api_source, 'conv_store', None), 'active_id', '') or 'api_default'
        current_msgs = self.api_source.get_history_as_messages() or []
        final_reply = ''

        if hasattr(self.api_source, 'set_round_state'):
            self.api_source.set_round_state('detecting_tools', conversation_id=active_conv_id)

        for round_index in range(1, max_rounds + 1):
            if hasattr(self.api_source, 'set_round_state'):
                self.api_source.set_round_state('detecting_tools', conversation_id=active_conv_id)

            candidates = []
            selected_candidate = None
            if hasattr(self.tool_router, 'collect_tool_candidates'):
                try:
                    candidates = self.tool_router.collect_tool_candidates(active_conv_id, current_msgs[-1:]) or []
                except Exception:
                    candidates = []
            if hasattr(self.api_source, 'set_tool_candidates'):
                self.api_source.set_tool_candidates(candidates, conversation_id=active_conv_id)
            if candidates and hasattr(self.tool_router, 'select_tool_candidate'):
                try:
                    selected_candidate = self.tool_router.select_tool_candidate(candidates)
                except Exception:
                    selected_candidate = None
            if selected_candidate and hasattr(self.api_source, 'append_snapshot_round'):
                self.api_source.append_snapshot_round(
                    'selected_tool_candidate',
                    {'candidate': selected_candidate},
                    conversation_id=active_conv_id,
                )

            round_result = self._run_single_round(active_conv_id, current_msgs)
            if not round_result.has_any_tool:
                result['stopped_reason'] = 'no_more_tool'
                break

            result['executed'] = True
            result['loop_count'] = round_index
            result['tool_rounds'].append(round_result)
            protocol = getattr(round_result, 'source_protocol', None) or 'tool_runtime'
            result['selected_protocols'].append(protocol)
            if hasattr(self.api_source, 'set_selected_tool_protocol'):
                self.api_source.set_selected_tool_protocol(protocol, conversation_id=active_conv_id)
            if hasattr(self.api_source, 'set_round_state'):
                self.api_source.set_round_state('running_tools', conversation_id=active_conv_id)

            tool_feedback = round_result.combined_feedback or ''
            if hasattr(self.api_source, 'append_snapshot_round'):
                self.api_source.append_snapshot_round(
                    'tool_round',
                    {
                        'tool_result': tool_feedback,
                        'tool_feedback': f'🔧 [工具执行结果]\n{tool_feedback}' if tool_feedback else '',
                    },
                    conversation_id=active_conv_id,
                )

            self._append_tool_feedback(round_result)
            result['ephemeral_messages'].append({
                'kind': 'tool_feedback',
                'protocol': protocol,
                'source_protocol': protocol,
                'content': tool_feedback,
                'ephemeral': True,
                'round_stage': 'running_tools',
            })
            if hasattr(self.api_source, 'append_ephemeral_tool_round'):
                self.api_source.append_ephemeral_tool_round({
                    'protocol': protocol,
                    'source_protocol': protocol,
                    'tool_feedback': tool_feedback,
                    'round_index': round_index,
                    'ephemeral': True,
                    'round_stage': 'running_tools',
                }, conversation_id=active_conv_id)

            if hasattr(self.api_source, 'capture_snapshot_messages'):
                self.api_source.capture_snapshot_messages('post_tool_messages', conversation_id=active_conv_id)

            if hasattr(self.api_source, 'set_round_state'):
                self.api_source.set_round_state('generating_followup', conversation_id=active_conv_id)
            final_reply = self.api_source.continue_assistant_reply_sync() if hasattr(self.api_source, 'continue_assistant_reply_sync') else ''
            if final_reply:
                if hasattr(self.api_source, 'append_snapshot_round'):
                    self.api_source.append_snapshot_round(
                        'assistant_followup',
                        {'assistant_reply': final_reply},
                        conversation_id=active_conv_id,
                    )
                if hasattr(self.api_source, 'set_snapshot_final_reply'):
                    self.api_source.set_snapshot_final_reply(final_reply, conversation_id=active_conv_id)

            current_msgs = self.api_source.get_history_as_messages() or []
            result['msgs'] = current_msgs
            result['loop_count'] = round_index

        else:
            result['stopped_reason'] = 'max_rounds_reached'

        if hasattr(self.api_source, 'set_snapshot_loop_count'):
            self.api_source.set_snapshot_loop_count(result['loop_count'], conversation_id=active_conv_id)
        if hasattr(self.api_source, 'finalize_round_snapshot'):
            self.api_source.finalize_round_snapshot(conversation_id=active_conv_id)
        elif hasattr(self.api_source, 'set_round_state'):
            self.api_source.set_round_state('finalized', conversation_id=active_conv_id)
        result['round_finalized'] = True
        if final_reply:
            result['final_reply'] = final_reply
        return result

    def _run_single_round(self, conversation_id: str, messages: list) -> ToolRoundResult:
        def _on_start(intent, idx):
            if hasattr(self.api_source, 'on_tool_status_event') and self.api_source.on_tool_status_event:
                self.api_source.on_tool_status_event({
                    'type': 'tool_call',
                    'tool_name': intent.name,
                    'tool_call_id': getattr(intent, 'tool_call_id', None),
                    'status': 'running',
                    'conversation_id': conversation_id,
                    'message': f'正在执行 {intent.name}...'
                })

        def _on_end(intent, result, idx):
            if hasattr(self.api_source, 'on_tool_status_event') and self.api_source.on_tool_status_event:
                self.api_source.on_tool_status_event({
                    'type': 'tool_call',
                    'tool_name': intent.name,
                    'tool_call_id': getattr(result, 'tool_call_id', None) or getattr(intent, 'tool_call_id', None),
                    'status': 'completed' if getattr(result, 'success', False) else 'failed',
                    'conversation_id': conversation_id,
                })

        if hasattr(self.tool_router, 'run_tool_round_from_messages'):
            round_result = self.tool_router.run_tool_round_from_messages(
                chat_id=conversation_id,
                messages=messages[-1:],
                allow=True,
                on_intent_start=_on_start,
                on_intent_end=_on_end,
            )
            if round_result and round_result.has_any_tool:
                return round_result

        round_result = self.tool_router.maybe_handle_tool_from_messages(
            chat_id=conversation_id,
            messages=messages[-1:],
            allow=True,
            on_intent_start=_on_start,
            on_intent_end=_on_end,
        )
        if isinstance(round_result, ToolRoundResult):
            return round_result
        return ToolRoundResult(has_any_tool=False, combined_feedback='', source_protocol='')

    def _append_tool_feedback(self, round_result: ToolRoundResult):
        if not round_result.has_any_tool:
            return
        tool_feedback = round_result.combined_feedback
        full_feedback = f'🔧 [工具执行结果]\n{tool_feedback}'

        segments = []
        for intent in getattr(round_result, 'intents', []):
            segments.append({
                'type': 'tool_call',
                'tool_name': intent.name,
                'tool_call_id': getattr(intent, 'tool_call_id', None),
                'block_key': getattr(intent, 'block_key', None),
                'arguments': dict(getattr(intent, 'arguments', {}) or {}),
                'content': dict(getattr(intent, 'arguments', {}) or {}),
            })
        for res in getattr(round_result, 'results', []):
            segments.append({
                'type': 'tool_result',
                'tool_name': res.name,
                'tool_call_id': getattr(res, 'tool_call_id', None),
                'block_key': getattr(res, 'block_key', None),
                'content': res.output or res.error,
                'success': res.success,
            })

        if hasattr(self.api_source, 'append_assistant_message'):
            self.api_source.append_assistant_message(
                full_feedback,
                kind='tool_feedback',
                raw_content=full_feedback,
                meta={
                    'tool_name': 'tool_router',
                    'tool_kind': 'tool_feedback',
                    'success': True,
                    'segments': segments,
                    'ephemeral': True,
                    'round_stage': 'running_tools',
                    'source_protocol': getattr(round_result, 'source_protocol', '') or 'tool_runtime',
                },
                visible_in_context=True,
                compactible=True,
            )
        else:
            self.api_source._get_cm().add_message('assistant', full_feedback)
            self.api_source.conv_store.save_current()
            self.api_source.conv_store.save_current()
