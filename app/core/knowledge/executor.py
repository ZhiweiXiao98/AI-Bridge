# filename: app/core/knowledge/executor.py
import threading
import time
from uuid import uuid4
from concurrent.futures import Future
from queue import Queue
from app.core.logging import get_logger
from app.core.debug import probe
from app.core.tool_runtime.task_meta import ToolTaskMeta

logger = get_logger("app.core.knowledge.executor", side="worker")


class KnowledgeExecutor:
    """
    固定单线程执行器，所有知识检索操作串行化。
    避免任意线程直接调用 Chroma/fastembed/reranker，
    防止多线程并发导致的 native runtime 冲突。
    """

    def __init__(self, service):
        self._service = service
        self._queue = Queue()
        self._thread = None
        self._stopping = False
        self._current_task = None
        self._current_task_started_at = 0.0
        self._on_task_state_change = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="knowledge_executor")
        self._thread.start()
        logger.info("KnowledgeExecutor 已启动")

    def stop(self):
        self._stopping = True
        self._queue.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("KnowledgeExecutor 已停止")


    def _new_task_id(self) -> str:
        return f"ktask_{uuid4().hex[:8]}"

    def get_current_task_snapshot(self) -> dict:
        payload = dict(self._current_task or {})
        if payload and self._current_task_started_at:
            payload['started_at'] = self._current_task_started_at
            payload['elapsed_ms'] = round(max(0.0, time.time() - self._current_task_started_at) * 1000, 1)
        return payload

    def _emit_task_state_change(self, state: str):
        callback = getattr(self, '_on_task_state_change', None)
        if not callable(callback):
            return
        try:
            callback({
                'source': 'knowledge_executor',
                'state': state,
                'snapshot': self.get_current_task_snapshot(),
            })
        except Exception as e:
            logger.warning("KnowledgeExecutor 状态回调失败: %s", e)

    def _set_current_task(self, task_payload: dict | None):
        self._current_task = dict(task_payload or {}) if task_payload else None
        self._current_task_started_at = time.time() if task_payload else 0.0
        if task_payload:
            self._emit_task_state_change('running')

    def _clear_current_task(self):
        had_task = bool(self._current_task)
        if had_task:
            self._emit_task_state_change('finished')
        self._current_task = None
        self._current_task_started_at = 0.0
        if had_task:
            self._emit_task_state_change('idle')
    def submit_search(self, query: str, top_k: int = 5, task_meta: ToolTaskMeta | None = None) -> Future:
        future = Future()
        self._queue.put(("search", future, query, top_k, task_meta))
        return future

    def submit_index(self, file_path: str, content: str) -> Future:
        future = Future()
        self._queue.put(("index", future, file_path, content))
        return future

    def submit_warmup(self) -> Future:
        future = Future()
        self._queue.put(("warmup", future))
        return future

    def _run(self):
        while not self._stopping:
            try:
                item = self._queue.get(timeout=1.0)
                if item is None:
                    break
                op, future, *args = item
                try:
                    result = self._execute(op, *args)
                    future.set_result(result)
                except Exception as e:
                    future.set_exception(e)
                finally:
                    self._clear_current_task()
            except Exception:
                continue

    def _execute(self, op, *args):
        t0 = time.time()
        if op == "search":
            query, top_k, task_meta = args
            task_id = self._new_task_id()
            self._set_current_task({
                'task_id': task_id,
                'kind': 'search',
                'tool_call_id': getattr(task_meta, 'tool_call_id', ''),
                'tool_name': getattr(task_meta, 'tool_name', 'knowledge_search') or 'knowledge_search',
                'conversation_id': getattr(task_meta, 'conversation_id', ''),
                'query_preview': str(query or '')[:80],
            })
            result = self._service._search_impl(query, top_k)
            elapsed = time.time() - t0
            probe("knowledge_executor_search", level="debug", side="worker",
                  elapsed_ms=round(elapsed * 1000, 1),
                  task_id=task_id,
                  tool_call_id=getattr(task_meta, 'tool_call_id', ''),
                  conversation_id=getattr(task_meta, 'conversation_id', ''))
            return result
        elif op == "index":
            file_path, content = args
            self._service._index_file_impl(file_path, content)
            elapsed = time.time() - t0
            probe("knowledge_executor_index", level="debug", side="worker",
                  elapsed_ms=round(elapsed * 1000, 1))
        elif op == "warmup":
            self._service.warmup()
            elapsed = time.time() - t0
            logger.info("KnowledgeExecutor warmup 完成 (%.1fms)", elapsed * 1000)
        else:
            logger.warning("KnowledgeExecutor 未知操作: %s", op)
