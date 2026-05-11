from typing import List, Callable, Optional
from uuid import uuid4

from app.core.tool_runtime.models import ToolIntent, ToolExecutionResult, ToolRoundResult
from app.core.tool_runtime.task_meta import build_tool_task_meta_from_intent


class ToolRuntimeExecutor:
    def __init__(self, skills_manager=None, docker_manager=None):
        self.skills_manager = skills_manager
        self.docker_manager = docker_manager

    def _ensure_tool_call_id(self, intent: ToolIntent) -> str:
        if intent.tool_call_id:
            return str(intent.tool_call_id)
        intent.tool_call_id = f"toolcall_{uuid4().hex[:8]}"
        return intent.tool_call_id

    def execute_intents(
        self,
        intents: List[ToolIntent],
        on_intent_start: Optional[Callable[[ToolIntent, int], None]] = None,
        on_intent_end: Optional[Callable[[ToolIntent, ToolExecutionResult, int], None]] = None
    ) -> ToolRoundResult:
        results: List[ToolExecutionResult] = []
        for idx, intent in enumerate(intents, 1):
            self._ensure_tool_call_id(intent)
            if on_intent_start:
                on_intent_start(intent, idx)
            res = self.execute_intent(intent, index=idx)
            if on_intent_end:
                on_intent_end(intent, res, idx)
            results.append(res)

        feedback_parts = [r.display_text for r in results if r.display_text]
        return ToolRoundResult(
            intents=intents,
            results=results,
            has_any_tool=bool(intents),
            combined_feedback='\n\n'.join(feedback_parts),
        )

    def execute_intent(self, intent: ToolIntent, index: int = 1) -> ToolExecutionResult:
        self._ensure_tool_call_id(intent)
        if intent.kind == 'skill_call':
            return self._execute_skill_call(intent, index=index)
        if intent.kind == 'exec_code':
            return self._execute_exec_code(intent, index=index)
        return ToolExecutionResult(
            success=False,
            kind=intent.kind,
            name=intent.name,
            error=f'Unsupported intent kind: {intent.kind}',
            conversation_id=intent.conversation_id,
            display_text=f'❌ [工具调用 {index}] Unsupported intent kind: {intent.kind}',
            tool_call_id=intent.tool_call_id,
            block_key=intent.block_key,
        )

    def _execute_skill_call(self, intent: ToolIntent, index: int = 1) -> ToolExecutionResult:
        if not self.skills_manager:
            return ToolExecutionResult(
                success=False,
                kind=intent.kind,
                name=intent.name,
                error='SkillsManager unavailable',
                conversation_id=intent.conversation_id,
                display_text=f'❌ [工具调用 {index}] {intent.name} 失败: SkillsManager unavailable',
                tool_call_id=intent.tool_call_id,
                block_key=intent.block_key,
            )
        try:
            skill_kwargs = dict(intent.arguments or {})
            skill_kwargs.setdefault('_tool_task_meta', build_tool_task_meta_from_intent(intent))
            success, result, error = self.skills_manager.execute_skill(intent.name, **skill_kwargs)
            if success:
                text = f'🔧 [工具调用 {index}] {intent.name}\n{result}'
                return ToolExecutionResult(
                    True,
                    intent.kind,
                    intent.name,
                    output=str(result),
                    conversation_id=intent.conversation_id,
                    display_text=text,
                    tool_call_id=intent.tool_call_id,
                    block_key=intent.block_key,
                )
            text = f'❌ [工具调用 {index}] {intent.name} 失败: {error}'
            return ToolExecutionResult(
                False,
                intent.kind,
                intent.name,
                error=str(error),
                conversation_id=intent.conversation_id,
                display_text=text,
                tool_call_id=intent.tool_call_id,
                block_key=intent.block_key,
            )
        except Exception as e:
            text = f'❌ [工具调用 {index}] {intent.name} 异常: {e}'
            return ToolExecutionResult(
                False,
                intent.kind,
                intent.name,
                error=str(e),
                conversation_id=intent.conversation_id,
                display_text=text,
                tool_call_id=intent.tool_call_id,
                block_key=intent.block_key,
            )

    def _execute_exec_code(self, intent: ToolIntent, index: int = 1) -> ToolExecutionResult:
        if not self.docker_manager:
            return ToolExecutionResult(
                success=False,
                kind=intent.kind,
                name=intent.name or 'code_execution',
                error='DockerManager unavailable',
                conversation_id=intent.conversation_id,
                display_text=f'❌ [代码块 {index}] 执行失败: DockerManager unavailable',
                tool_call_id=intent.tool_call_id,
                block_key=intent.block_key,
            )
        try:
            exit_code, output = self.docker_manager.execute_code(intent.code)
            if exit_code == 0:
                text = f'🖥️ [代码块 {index} 输出]\n{output}' if str(output).strip() else f'✅ 代码块 {index} 执行成功 (无输出)'
                return ToolExecutionResult(
                    True,
                    intent.kind,
                    intent.name or 'code_execution',
                    output=str(output),
                    conversation_id=intent.conversation_id,
                    display_text=text,
                    tool_call_id=intent.tool_call_id,
                    block_key=intent.block_key,
                )
            text = f'❌ [代码块 {index}] 执行错误 (Exit {exit_code}):\n{output}'
            return ToolExecutionResult(
                False,
                intent.kind,
                intent.name or 'code_execution',
                error=str(output),
                conversation_id=intent.conversation_id,
                display_text=text,
                tool_call_id=intent.tool_call_id,
                block_key=intent.block_key,
            )
        except Exception as e:
            text = f'❌ [代码块 {index}] 执行异常: {e}'
            return ToolExecutionResult(
                False,
                intent.kind,
                intent.name or 'code_execution',
                error=str(e),
                conversation_id=intent.conversation_id,
                display_text=text,
                tool_call_id=intent.tool_call_id,
                block_key=intent.block_key,
            )
