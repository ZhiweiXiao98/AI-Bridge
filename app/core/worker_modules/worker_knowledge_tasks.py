import time
from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.worker_knowledge_tasks", side="worker")


class WorkerKnowledgeTaskBridge:
    def __init__(self, knowledge_service=None):
        self.knowledge_service = knowledge_service

    def build_runtime_task_payload(self, snap: dict | None):
        snap = dict(snap or {})
        if not snap.get('task_id'):
            return None
        elapsed_ms = snap.get('elapsed_ms', 0) or 0
        return {
            'id': snap.get('task_id', ''),
            'task_id': snap.get('task_id', ''),
            'action': 'knowledge_search',
            'status': 'running',
            'label': '知识检索',
            'category': 'Knowledge',
            'icon': '🧠',
            'cancellable': False,
            'client_id': snap.get('conversation_id', '') or 'knowledge',
            'tool_call_id': snap.get('tool_call_id', ''),
            'tool_name': snap.get('tool_name', 'knowledge_search') or 'knowledge_search',
            'conversation_id': snap.get('conversation_id', ''),
            'started_at': snap.get('started_at', 0),
            'elapsed_ms': elapsed_ms,
            'elapsed_seconds': int(elapsed_ms / 1000) if elapsed_ms else 0,
            'age': (elapsed_ms / 1000.0) if elapsed_ms else 0,
            'query_preview': snap.get('query_preview', ''),
            'is_knowledge_task': True,
            'runtime_source': 'knowledge_executor',
        }

    def get_panel_snapshot(self, scheduler=None):
        active = None
        queue = []
        if scheduler and hasattr(scheduler, 'get_queue_snapshot'):
            active, queue = scheduler.get_queue_snapshot()

        knowledge_task = self._get_knowledge_task_snapshot()
        if knowledge_task:
            if active:
                queue = [knowledge_task] + list(queue or [])
                logger.info("[KnowledgeTaskBridge] merge into queue | task_id=%s tool_call_id=%s", knowledge_task.get('task_id', ''), knowledge_task.get('tool_call_id', ''))
            else:
                active = knowledge_task
                logger.info("[KnowledgeTaskBridge] set active | task_id=%s tool_call_id=%s", knowledge_task.get('task_id', ''), knowledge_task.get('tool_call_id', ''))
        else:
            logger.debug("[KnowledgeTaskBridge] no active knowledge task")

        return {
            'active': active,
            'queue': list(queue or []),
            'timestamp': time.time(),
        }

    def _get_knowledge_task_snapshot(self):
        if not self.knowledge_service:
            return None
        v2 = getattr(self.knowledge_service, '_v2', None)
        executor = getattr(v2, '_executor', None) if v2 else None
        if not executor or not hasattr(executor, 'get_current_task_snapshot'):
            logger.info("[KnowledgeTaskBridge] executor unavailable")
            return None

        snap = executor.get_current_task_snapshot() or {}
        if not snap.get('task_id'):
            logger.debug("[KnowledgeTaskBridge] executor snapshot empty")
            return None

        return self.build_runtime_task_payload(snap)
