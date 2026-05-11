# filename: app/core/services/tool_router_service.py

import re
import json
import hashlib
import logging
import time
from typing import Optional, List

from app.core.docker_manager import DockerManager
from app.core.skills import SkillsManager
from app.core.tool_runtime.segment_parser import ToolSegmentParser
from app.core.tool_runtime.executor import ToolRuntimeExecutor
from app.core.tool_runtime.models import ToolExecutionResult, ToolIntent, ToolRoundResult
from app.core.logging import get_logger

logger = get_logger("app.core.tool_router_service", side="worker")


class ToolRouterService:
    """
    工具路由服务
    支持两种模式：
    1. 代码块自动执行（向后兼容）
    2. Function Calling（标准化工具调用）
    """

    CODE_BLOCK_PATTERN = re.compile(
        r"```(?:python|py)\s*\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE
    )

    def __init__(self, agent_manager, max_seen: int = 200):
        self.agent = agent_manager
        self._seen_set = set()
        self.max_seen = max_seen
        self.docker = getattr(agent_manager, 'docker_manager', None) or DockerManager()
        self.skills_manager = SkillsManager(
            docker_manager=self.docker,
            knowledge_engine=getattr(agent_manager, 'knowledge_service', None)
        )
        self.skills_manager.scan_all_skills()
        self.runtime_executor = ToolRuntimeExecutor(
            skills_manager=self.skills_manager,
            docker_manager=self.docker,
        )

    def run_tool_round_from_messages(
        self,
        chat_id: str,
        messages: list,
        allow: bool = True,
        on_intent_start=None,
        on_intent_end=None,
    ):
        if not allow:
            return ToolRoundResult(has_any_tool=False, combined_feedback='')

        _t0 = time.time()
        intents = ToolSegmentParser.parse_messages(
            messages,
            conversation_id=chat_id,
            source='tool_router',
        )
        logger.info("[工具路由] 段解析器完成 | 耗时=%.1fs | 意图数=%s",
                     time.time() - _t0, len(intents) if intents else 0)
        if intents:
            round_result = self.runtime_executor.execute_intents(
                intents,
                on_intent_start=on_intent_start,
                on_intent_end=on_intent_end
            )
            executed = any(r.kind == 'exec_code' for r in round_result.results)
            if executed and hasattr(self.agent, 'worker') and hasattr(self.agent.worker, 'code_execution_completed'):
                self.agent.worker.code_execution_completed.emit()
            return round_result

        return ToolRoundResult(has_any_tool=False, combined_feedback='')

    def maybe_handle_tool_from_messages(
        self,
        chat_id: str,
        messages: list,
        allow: bool = True,
        on_intent_start=None,
        on_intent_end=None,
    ) -> Optional[ToolRoundResult]:
        """
        处理消息中的工具调用。
        新主链：segments -> ToolIntent -> Executor。
        旧方法保留为兼容层，但默认优先走统一 runtime。
        """
        logger.debug(f"[ToolRouter] 处理消息，数量: {len(messages)}")

        round_result = self.run_tool_round_from_messages(
            chat_id=chat_id,
            messages=messages,
            allow=allow,
            on_intent_start=on_intent_start,
            on_intent_end=on_intent_end,
        )
        if round_result and round_result.has_any_tool:
            return round_result

        raw_text = self._extract_raw_text(messages)
        if not raw_text:
            return None

        logger.warning("[工具路由] 结构化识别未命中，进入兼容链 | 原文长度=%s", len(raw_text))

        fallback_rounds: List[ToolRoundResult] = []
        _t0 = time.time()
        tool_result = self._handle_function_calling(chat_id, raw_text)
        logger.info("[工具路由] 函数调用识别完成 | 耗时=%.1fs | 命中=%s",
                     time.time() - _t0, bool(tool_result and tool_result.has_any_tool))
        if tool_result and tool_result.has_any_tool:
            fallback_rounds.append(tool_result)
        _t1 = time.time()
        code_result = self._handle_code_blocks(chat_id, messages)
        logger.info("[工具路由] 代码块识别完成 | 耗时=%.1fs | 命中=%s",
                     time.time() - _t1, bool(code_result and code_result.has_any_tool))
        if code_result and code_result.has_any_tool:
            fallback_rounds.append(code_result)
        if not fallback_rounds:
            return None

        merged_intents: List[ToolIntent] = []
        merged_results: List[ToolExecutionResult] = []
        feedback_chunks: List[str] = []
        protocols: List[str] = []
        for rr in fallback_rounds:
            merged_intents.extend(list(rr.intents or []))
            merged_results.extend(list(rr.results or []))
            if rr.combined_feedback:
                feedback_chunks.append(str(rr.combined_feedback))
            if rr.source_protocol:
                protocols.append(str(rr.source_protocol))

        combined = "\n\n".join([chunk for chunk in feedback_chunks if chunk.strip()])
        if combined:
            combined = f"🔧 [工具执行结果]{chr(10)}{chr(10)}{combined}"

        return ToolRoundResult(
            intents=merged_intents,
            results=merged_results,
            has_any_tool=bool(merged_intents or merged_results),
            combined_feedback=combined,
            source_protocol='browser_fallback_mixed' if len(set(protocols)) > 1 else (protocols[0] if protocols else 'browser_fallback'),
        )

    def _extract_raw_text(self, messages: list) -> Optional[str]:
        """提取消息的原始文本，兼容新 segments 结构。"""
        try:
            chunks = []
            for msg in messages or []:
                for seg in msg.get('segments', []) or []:
                    if seg.get('type') == 'code':
                        chunks.append(str(seg.get('raw_content', seg.get('content', '')) or ''))
                    else:
                        chunks.append(str(seg.get('content', '') or ''))
            merged = '\n'.join([c for c in chunks if c and c.strip()])
            return merged or None
        except Exception as e:
            logger.error(f"提取文本失败: {e}")
        return None

    def _handle_function_calling(self, chat_id: str, raw_text: str) -> Optional[ToolRoundResult]:
        """处理 Function Calling 格式的工具调用"""
        code_blocks = re.findall(r"```\w*\s*\n(.*?)\n```", raw_text, re.DOTALL)

        intents: List[ToolIntent] = []
        for block in code_blocks:
            block_pos = raw_text.find(block)
            if block_pos == -1:
                continue
            prefix = raw_text[max(0, block_pos - 100):block_pos]
            if 'tool_call' not in prefix.lower():
                continue

            try:
                parsed = json.loads(block.strip())
                if isinstance(parsed, dict) and 'name' in parsed and 'arguments' in parsed:
                    intents.append(ToolIntent(
                        kind='skill_call',
                        name=str(parsed.get('name') or ''),
                        arguments=parsed.get('arguments', {}) or {},
                        source='browser_fallback_function_calling',
                        conversation_id=chat_id,
                        raw_block=block.strip(),
                    ))
            except Exception as e:
                logger.warning(f"JSON 解析失败: {e}")

        if not intents:
            return None

        for intent in intents:
            logger.info(f"[ToolRouter] fallback 工具调用接纳: {intent.name}")
            if intent.name == 'knowledge_search':
                self._log_knowledge_health()

        round_result = self.runtime_executor.execute_intents(intents)
        round_result.source_protocol = 'browser_fallback_function_calling'
        return round_result

    def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """执行指定的工具"""
        try:
            if tool_name == "knowledge_search":
                self._log_knowledge_health()
            success, result, error = self.skills_manager.execute_skill(tool_name, **arguments)
            if success:
                return str(result)
            return f"❌ {error}"
        except Exception as e:
            logger.error(f"[ToolRouter] 工具执行异常: {e}", exc_info=True)
            return f"❌ 执行异常: {str(e)}"

    def _log_knowledge_health(self):
        ks = getattr(self.agent, 'knowledge_service', None)
        if not ks:
            return
        v2 = getattr(ks, '_v2', None)
        if not v2:
            return
        health = v2.get_health()
        logger.info("[ToolRouter] knowledge_search 健康状态: state=%s path=%s embedder=%s reranker=%s failures=%d",
                    health.get("state"), health.get("active_path"),
                    health.get("embedding_mode"), health.get("reranker_mode"),
                    health.get("consecutive_failures", 0))

    def _handle_code_blocks(self, chat_id: str, messages: list) -> Optional[ToolRoundResult]:
        """处理代码块执行（向后兼容）"""
        code_blocks = self._extract_all_code_blocks(messages)
        if not code_blocks:
            return None

        logger.info(f"[ToolRouter] 发现 {len(code_blocks)} 个代码块")

        intents: List[ToolIntent] = []
        for code in code_blocks:
            if len(code) < 5:
                continue

            fingerprint = hashlib.md5(code.encode()).hexdigest()
            key = f"{chat_id}|{fingerprint}"
            if key in self._seen_set:
                continue
            self._seen_set.add(key)

            intents.append(ToolIntent(
                kind='exec_code',
                name='code_execution',
                code=code,
                source='browser_fallback_exec_code',
                conversation_id=chat_id,
                raw_block=code,
            ))

        if not intents:
            return None

        round_result = self.runtime_executor.execute_intents(intents)
        round_result.source_protocol = 'browser_fallback_exec_code'
        executed = any(r.kind == 'exec_code' for r in round_result.results)
        if executed and hasattr(self.agent, 'worker') and hasattr(self.agent.worker, 'code_execution_completed'):
            self.agent.worker.code_execution_completed.emit()
        return round_result

    def _extract_all_code_blocks(self, messages: list) -> List[str]:
        """
        智能提取：遍历所有代码块，收集所有不带 filename 标记的代码块
        """
        code_blocks = []

        for msg in reversed(messages or []):
            if msg.get("role") != "AI":
                continue

            segments = msg.get("segments", [])
            full_text = "\n".join([str(s.get("content", "")) for s in segments if s.get("type") == "text"]).strip()
            matches = list(self.CODE_BLOCK_PATTERN.finditer(full_text))

            for m in matches:
                block_content = m.group(1).strip()
                first_line = block_content.split('\n')[0].strip().upper()
                exec_markers = ['# EXEC', '# RUN', '# EXECUTE']
                has_exec_marker = any(marker in first_line for marker in exec_markers)

                if has_exec_marker:
                    clean_content = '\n'.join(block_content.split('\n')[1:]).strip()
                    if not re.match(r"^\s*(#|//|<!--)\s*filename\s*:", clean_content, re.IGNORECASE):
                        if len(clean_content) >= 10:
                            logger.debug(f"[ToolRouter] 收集可执行块 (长度: {len(clean_content)})")
                            code_blocks.append(clean_content)

        logger.debug(f"[ToolRouter] 总共收集到 {len(code_blocks)} 个有效代码块")
        return code_blocks
