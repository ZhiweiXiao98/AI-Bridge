# filename: app/core/knowledge/service.py
"""KnowledgeService V2 主服务"""

import os
import time
import logging
import hashlib
import sys as _sys
import types as _types
if "posthog" not in _sys.modules:
    _fake = _types.ModuleType("posthog")
    _fake.Posthog = type("Posthog", (), {
        "__init__": lambda self, *a, **kw: None,
        "capture": lambda self, *a, **kw: None,
        "identify": lambda self, *a, **kw: None,
        "flush": lambda self, *a, **kw: None,
        "shutdown": lambda self, *a, **kw: None,
    })
    _fake.capture = lambda *a, **kw: None
    _fake.identify = lambda *a, **kw: None
    _fake.flush = lambda *a, **kw: None
    _fake.shutdown = lambda *a, **kw: None
    _fake.api_key = ""
    _fake.host = ""
    _fake.disabled = True
    _sys.modules["posthog"] = _fake
import os as _os
_os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
import chromadb
from typing import Optional

from app.core.knowledge.config import (
    DB_DIR, COLLECTION_NAME, DEFAULT_TOP_K, RECALL_MULTIPLIER,
    SUPPORTED_EXTENSIONS, IGNORED_DIRS
)
from app.core.knowledge.chunker import ASTChunker
from app.core.knowledge.embedder import LocalEmbedder
from app.core.knowledge.cache import LRUCache
from app.core.knowledge.reranker import Reranker
from app.core.logging import get_logger
from app.core.debug import probe

logger = get_logger("app.core.knowledge.service", side="worker")


class KnowledgeServiceV2:
    """
    V2 知识检索服务。
    AST 智能分块 + 本地 Embedding + LRU 缓存。
    支持 fastembed（优先）和 Chroma 内置 embedding（降级）。
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"

    PATH_FASTEMBED_CHROMA_RERANKER = "fastembed_chroma_reranker"
    PATH_FASTEMBED_CHROMA_KEYWORD = "fastembed_chroma_keyword"
    PATH_CHROMA_BUILTIN_KEYWORD = "chroma_builtin_keyword"
    PATH_ERROR_ONLY = "error_only"

    def __init__(self, db_path: str = DB_DIR):
        self.db_path = db_path
        self.chunker = ASTChunker()
        self.embedder = LocalEmbedder()
        self.cache = LRUCache()
        self.reranker = Reranker()
        self._client = None
        self._collection = None
        self._file_hashes = {}
        self._health_state = self.HEALTHY
        self._active_path = self.PATH_FASTEMBED_CHROMA_RERANKER
        self._last_error = ""
        self._last_stage = ""
        self._last_success_at = 0.0
        self._last_failure_at = 0.0
        self._consecutive_failures = 0
        self._on_health_change = None
        self._executor = None
        self._use_executor = False

    def on_project_switched(self, new_root: str, new_db_path: str):
        old_db_path = self.db_path
        if self._client:
            try:
                self._client = None
            except Exception:
                pass
        self._collection = None
        self._file_hashes.clear()
        self.cache.clear()
        self.db_path = new_db_path
        if not os.path.exists(new_db_path) or not os.listdir(new_db_path):
            logger.info("[KnowledgeService] 向量库为空，将触发全量索引: %s", new_root)
            self._trigger_reindex(new_root)
        logger.info("[KnowledgeService] 向量库路径已切换: %s → %s", old_db_path, new_db_path)

    def _trigger_reindex(self, project_root: str):
        try:
            from app.core.knowledge.reindexer import reindex_project
            reindex_project(project_root, self)
        except Exception as e:
            logger.warning("[KnowledgeService] 全量索引触发失败: %s", e)

    def get_health(self) -> dict:
        current_path = self._determine_active_path()
        return {
            "state": self._health_state,
            "active_path": current_path,
            "last_error": self._last_error,
            "last_stage": self._last_stage,
            "last_success_at": self._last_success_at,
            "last_failure_at": self._last_failure_at,
            "consecutive_failures": self._consecutive_failures,
            "embedding_mode": self.embedder.mode,
            "reranker_mode": self.reranker.mode,
        }

    def _record_stage(self, stage: str):
        self._last_stage = stage
        probe("knowledge_search_stage", level="debug", side="worker",
              stage=stage, health=self._health_state, path=self._active_path)

    def _record_success(self, stage: str, elapsed: float):
        self._last_stage = stage
        self._last_success_at = time.time()
        self._consecutive_failures = 0
        if self._health_state != self.HEALTHY:
            logger.info("知识检索恢复健康，从 %s 回升到 healthy", self._health_state)
        self._health_state = self.HEALTHY
        probe("knowledge_search_stage_ok", level="debug", side="worker",
              stage=stage, elapsed_ms=round(elapsed * 1000, 1))
        self._notify_health_change()

    def _record_failure(self, stage: str, error: str):
        self._last_stage = stage
        self._last_error = str(error)[:200]
        self._last_failure_at = time.time()
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._health_state = self.FAILED
        else:
            self._health_state = self.DEGRADED
        probe("knowledge_search_stage_fail", level="warning", side="worker",
              stage=stage, error=str(error)[:100], health=self._health_state)
        self._notify_health_change()

    def _notify_health_change(self):
        if self._on_health_change:
            try:
                self._on_health_change(self.get_health())
            except Exception:
                pass

    # ========== 连接管理 ==========

    def _ensure_connection(self):
        """延迟初始化 Chroma 连接（精细插桩版）"""
        if self._client is not None:
            return
        t0 = time.time()
        stage = "start"
        self._record_stage("ensure_connection")
        try:
            logger.info("[Chroma] ensure_connection BEGIN | db_path=%s", self.db_path)

            stage = "mkdir"
            logger.info("[Chroma] mkdir BEGIN | db_path=%s", self.db_path)
            os.makedirs(self.db_path, exist_ok=True)
            logger.info("[Chroma] mkdir END | exists=%s", os.path.exists(self.db_path))

            stage = "persistent_client"
            logger.info("[Chroma] PersistentClient BEGIN | path=%s", self.db_path)
            self._client = chromadb.PersistentClient(path=self.db_path)
            logger.info("[Chroma] PersistentClient END | client=%s", type(self._client).__name__)

            stage = "get_or_create_collection"
            logger.info("[Chroma] get_or_create_collection BEGIN | name=%s", COLLECTION_NAME)
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("[Chroma] get_or_create_collection END | collection=%s", type(self._collection).__name__)

            stage = "peek"
            logger.info("[Chroma] peek BEGIN (替代 count，避免 native crash)")
            peek_result = self._collection.peek(limit=1)
            count = self._collection.count()
            logger.info("[Chroma] peek+count END | count=%s", count)

            elapsed = time.time() - t0
            logger.info("[Chroma] ensure_connection SUCCESS | %d chunks, embedding: %s (%.1fms)",
                        count, self.embedder.mode, elapsed * 1000)
            self._record_success("ensure_connection", elapsed)
        except Exception as e:
            elapsed = time.time() - t0
            logger.exception("[Chroma] ensure_connection FAIL | stage=%s | error=%s", stage, e)
            msg = str(e).lower()
            self._record_failure("ensure_connection", str(e))
            if "no such column" in msg or "malformed" in msg or "corrupt" in msg:
                logger.warning("数据库损坏，自动重建: %s", e)
                self._rebuild_db()
            else:
                logger.error("知识库连接失败: stage=%s (%.1fms)", stage, elapsed * 1000)
                raise

    def _rebuild_db(self):
        """重建数据库"""
        import shutil
        self._client = None
        self._collection = None
        try:
            if os.path.exists(self.db_path):
                logger.info("[Chroma] rebuild: 删除旧目录 BEGIN | db_path=%s", self.db_path)
                shutil.rmtree(self.db_path)
                logger.info("[Chroma] rebuild: 删除旧目录 END")
            logger.info("[Chroma] rebuild: mkdir BEGIN")
            os.makedirs(self.db_path, exist_ok=True)
            logger.info("[Chroma] rebuild: mkdir END")
            logger.info("[Chroma] rebuild: PersistentClient BEGIN")
            self._client = chromadb.PersistentClient(path=self.db_path)
            logger.info("[Chroma] rebuild: PersistentClient END | client=%s", type(self._client).__name__)
            logger.info("[Chroma] rebuild: get_or_create_collection BEGIN")
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("[Chroma] rebuild: get_or_create_collection END")
            logger.info("[Chroma] rebuild SUCCESS")
        except Exception as e:
            logger.exception("[Chroma] rebuild FAIL | error=%s", e)

    # ========== 索引 ==========

    def index_file(self, file_path: str, content: str):
        """索引单个文件（增量）"""
        if self._use_executor and self._executor:
            future = self._executor.submit_index(file_path, content)
            try:
                return future.result(timeout=120)
            except Exception as e:
                logger.error("索引执行超时或异常: %s | path=%s", e, file_path)
                return
        return self._index_file_impl(file_path, content)

    def _index_file_impl(self, file_path: str, content: str):
        content_hash = hashlib.md5(content.encode()).hexdigest()
        if self._file_hashes.get(file_path) == content_hash:
            logger.info("KnowledgeIndex 跳过更新: content hash unchanged | path=%s", file_path)
            return

        try:
            logger.info("KnowledgeIndex 开始索引: %s", file_path)
            self._ensure_connection()
            if self._collection is None:
                logger.warning("KnowledgeIndex 跳过索引: collection unavailable | path=%s", file_path)
                return

            self._delete_file_chunks(file_path)
            chunks = self.chunker.chunk_file(file_path, content)
            if not chunks:
                logger.info("KnowledgeIndex 跳过索引: no chunks generated | path=%s", file_path)
                return

            ids = [c["id"] for c in chunks]
            texts = [c["content"] for c in chunks]
            metas = [c["metadata"] for c in chunks]

            embeddings = self.embedder.embed_documents(texts)
            if embeddings is not None:
                self._collection.upsert(
                    ids=ids, documents=texts,
                    embeddings=embeddings, metadatas=metas
                )
            else:
                self._collection.upsert(
                    ids=ids, documents=texts, metadatas=metas
                )

            self._file_hashes[file_path] = content_hash
            self.cache.invalidate()
            logger.info("KnowledgeIndex 索引完成: %s (%d chunks)", file_path, len(chunks))
        except Exception as e:
            logger.exception("KnowledgeIndex 索引失败: %s | error=%s", file_path, e)

    def _delete_file_chunks(self, file_path: str):
        """删除某文件的所有 chunks"""
        try:
            self._collection.delete(where={"path": file_path})
        except Exception:
            pass

    def list_indexed_paths(self) -> list[str]:
        """列出知识库中所有已索引的文件路径（去重后）"""
        self._ensure_connection()
        if self._collection is None or self._collection.count() == 0:
            return []
        try:
            results = self._collection.get(include=["metadatas"])
            metas = results.get("metadatas") or []
            paths = set()
            for meta in metas:
                if isinstance(meta, dict):
                    path = meta.get("path")
                    if path:
                        paths.add(str(path).replace(chr(92), '/'))
            return sorted(paths)
        except Exception as e:
            logger.error("获取已索引路径失败: %s", e)
            return []

    def delete_paths(self, paths: list[str]) -> int:
        """按文件路径批量删除 chunks，兼容历史正反斜杠路径，返回处理的路径数"""
        self._ensure_connection()
        if self._collection is None or not paths:
            return 0
        processed = 0
        for path in paths:
            try:
                raw = str(path)
                slash = raw.replace(chr(92), '/')
                backslash = slash.replace('/', chr(92))
                candidates = []
                for item in (raw, slash, backslash):
                    if item and item not in candidates:
                        candidates.append(item)
                for candidate in candidates:
                    self._collection.delete(where={"path": candidate})
                processed += 1
            except Exception as e:
                logger.warning("删除索引路径失败 %s: %s", path, e)
        if processed:
            self.cache.invalidate()
        return processed

    def rebuild_index(self, root_dir: str = "."):
        """全量重建索引"""
        logger.info("全量重建索引: %s", root_dir)
        file_count = 0

        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            for fname in filenames:
                ext = os.path.splitext(fname)[1]
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                fpath = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(fpath, root_dir)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    self.index_file(rel_path, content)
                    file_count += 1
                except Exception as e:
                    logger.warning("跳过 %s: %s", rel_path, e)

        chunk_count = self._collection.count() if self._collection else 0
        logger.info("索引完成: %d 文件, %d chunks", file_count, chunk_count)
        return file_count, chunk_count

    # ========== 检索 ==========

    def search(self, query: str, top_k: int = DEFAULT_TOP_K, task_meta=None) -> str:
        """语义检索（带阶段插桩与健康状态管理）"""
        if self._use_executor and self._executor:
            future = self._executor.submit_search(query, top_k, task_meta=task_meta)
            try:
                return future.result(timeout=90)
            except Exception as e:
                self._record_failure("executor_search", str(e))
                return f"❌ 检索执行超时或异常: {str(e)}"
        return self._search_impl(query, top_k)

    def _search_impl(self, query: str, top_k: int = DEFAULT_TOP_K) -> str:
        t0_total = time.time()
        query_len = len(query)

        self._active_path = self._determine_active_path()

        probe("knowledge_search_entry", level="info", side="worker",
              query_len=query_len, top_k=top_k, health=self._health_state,
              path=self._active_path, embedder=self.embedder.mode, reranker=self.reranker.mode)

        # --- Stage: cache ---
        cache_key = f"{query}::{top_k}"
        t0 = time.time()
        self._record_stage("cache_get")
        cached = self.cache.get(cache_key)
        if cached is not None:
            self._record_success("cache_get", time.time() - t0)
            probe("knowledge_search_cache_hit", level="info", side="worker")
            return cached
        self._record_success("cache_get", time.time() - t0)

        try:
            # --- Stage: ensure_connection ---
            t0 = time.time()
            self._record_stage("ensure_connection")
            self._ensure_connection()
            self._record_success("ensure_connection", time.time() - t0)

            if self._collection is None:
                self._record_failure("ensure_connection", "collection is None after init")
                return "⚠️ 知识库连接失败，请检查日志。"

            # --- Stage: collection.count ---
            t0 = time.time()
            self._record_stage("collection_count")
            total_count = self._collection.count()
            self._record_success("collection_count", time.time() - t0)

            if total_count == 0:
                return "⚠️ 知识库为空，请先索引代码。"

            recall_n = min(top_k * RECALL_MULTIPLIER, total_count)

            # --- Stage: embed_query ---
            t0 = time.time()
            self._record_stage("embed_query")
            query_embedding = self.embedder.embed_query(query)
            embed_elapsed = time.time() - t0
            self._record_success("embed_query", embed_elapsed)
            self._active_path = self._determine_active_path()
            probe("knowledge_search_embed_done", level="info", side="worker",
                  mode=self.embedder.mode, elapsed_ms=round(embed_elapsed * 1000, 1),
                  path=self._active_path)

            # --- Stage: collection.query ---
            t0 = time.time()
            self._record_stage("collection_query")
            if query_embedding is not None:
                results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=recall_n,
                    include=["documents", "metadatas", "distances"]
                )
            else:
                results = self._collection.query(
                    query_texts=[query],
                    n_results=recall_n,
                    include=["documents", "metadatas", "distances"]
                )
            query_elapsed = time.time() - t0
            self._record_success("collection_query", query_elapsed)
            probe("knowledge_search_query_done", level="info", side="worker",
                  recall_n=recall_n, result_count=len(results.get("documents", [[]])[0]),
                  elapsed_ms=round(query_elapsed * 1000, 1))

            if not results["documents"] or not results["documents"][0]:
                return "⚠️ 未检索到相关内容。"

            raw_docs = results["documents"][0]
            raw_metas = results["metadatas"][0]
            raw_dists = results["distances"][0]

            # --- Stage: rerank ---
            t0 = time.time()
            self._record_stage("rerank")
            docs, metas, scores = self.reranker.rerank(
                query, raw_docs, raw_metas, raw_dists, top_k
            )
            rerank_elapsed = time.time() - t0
            self._record_success("rerank", rerank_elapsed)
            self._active_path = self._determine_active_path()
            probe("knowledge_search_rerank_done", level="info", side="worker",
                  reranker_mode=self.reranker.mode, top_k=top_k,
                  elapsed_ms=round(rerank_elapsed * 1000, 1),
                  path=self._active_path)

            # --- Stage: format ---
            nl = chr(10)
            context = f"{nl}--- [🧠 RAG Context] ---{nl}"
            for doc, meta, score in zip(docs, metas, scores):
                symbol = meta.get("symbol", "")
                path = meta.get("path", "")
                ctype = meta.get("type", "")
                context += f"{nl}>> File: {path}"
                if symbol:
                    context += f" | {ctype}: {symbol}"
                context += f" (score: {score:.2f}){nl}"
                context += f"{doc}{nl}"

            # --- Stage: cache_put ---
            t0 = time.time()
            self._record_stage("cache_put")
            self.cache.put(cache_key, context)
            self._record_success("cache_put", time.time() - t0)

            total_elapsed = time.time() - t0_total
            self._active_path = self._determine_active_path()
            probe("knowledge_search_complete", level="info", side="worker",
                  total_ms=round(total_elapsed * 1000, 1),
                  path=self._active_path, result_count=len(docs))

            return context

        except Exception as e:
            total_elapsed = time.time() - t0_total
            import traceback
            tb = traceback.format_exc()
            self._record_failure(self._last_stage or "unknown", str(e))
            logger.error("检索失败: %s (%.1fms) stage=%s", e, total_elapsed * 1000, self._last_stage)
            logger.debug(tb)
            return f"❌ 检索错误: {str(e)}"

    def _determine_active_path(self) -> str:
        if self.embedder.mode == "fastembed" and self.reranker.mode == "cross_encoder":
            return self.PATH_FASTEMBED_CHROMA_RERANKER
        if self.embedder.mode == "fastembed" and self.reranker.mode == "keyword":
            return self.PATH_FASTEMBED_CHROMA_KEYWORD
        if self.embedder.mode == "chroma_builtin":
            return self.PATH_CHROMA_BUILTIN_KEYWORD
        return self.PATH_ERROR_ONLY

    def try_recover_main_path(self) -> dict:
        """尝试恢复主路径组件（fastembed + cross-encoder）"""
        old_path = self._active_path
        old_embedder = self.embedder.mode
        old_reranker = self.reranker.mode

        if self.embedder._use_builtin:
            self.embedder._use_builtin = False
            self.embedder._model = None
            try:
                self.embedder._ensure_model()
                if self.embedder._model is not None:
                    logger.info("Embedder 恢复到 fastembed 模式")
                else:
                    self.embedder._use_builtin = True
            except Exception as e:
                logger.warning("Embedder 恢复失败: %s", e)
                self.embedder._use_builtin = True

        if self.reranker._use_keyword and self.reranker._initialized:
            self.reranker._initialized = False
            self.reranker._use_keyword = False
            self.reranker._model = None
            try:
                self.reranker._ensure_model()
                if self.reranker._model is not None:
                    logger.info("Reranker 恢复到 cross_encoder 模式")
                else:
                    self.reranker._use_keyword = True
                    self.reranker._initialized = True
            except Exception as e:
                logger.warning("Reranker 恢复失败: %s", e)
                self.reranker._use_keyword = True
                self.reranker._initialized = True

        self._active_path = self._determine_active_path()
        recovered = self._active_path != old_path
        if recovered:
            logger.info("知识检索路径恢复: %s -> %s (embedder: %s->%s, reranker: %s->%s)",
                       old_path, self._active_path,
                       old_embedder, self.embedder.mode,
                       old_reranker, self.reranker.mode)
            self._health_state = self.HEALTHY
            self._consecutive_failures = 0
        return {
            "recovered": recovered,
            "old_path": old_path,
            "new_path": self._active_path,
            "embedder_mode": self.embedder.mode,
            "reranker_mode": self.reranker.mode,
        }

    # ========== 执行器 ==========

    def start_executor(self):
        """启动固定执行线程，所有知识操作串行化"""
        if self._use_executor:
            return
        from app.core.knowledge.executor import KnowledgeExecutor
        self._executor = KnowledgeExecutor(self)
        self._executor.start()
        self._use_executor = True
        logger.info("KnowledgeExecutor 已启动，知识操作将串行化执行")

    def stop_executor(self):
        """停止固定执行线程"""
        if self._executor:
            self._executor.stop()
            self._use_executor = False

    WARMUP_PHASE_CHROMA = "chroma"
    WARMUP_PHASE_EMBEDDER = "embedder"
    WARMUP_PHASE_RERANKER = "reranker"

    _WARMUP_AUTO_PHASES = [WARMUP_PHASE_CHROMA]

    # ========== 预热 ==========

    def warmup(self, phases=None):
        """
        分阶段预热懒加载组件。
        phases: 预热阶段列表，默认只自动执行 chroma 阶段。
        可选值: ["chroma", "embedder", "reranker"] 或 "all"
        """
        if phases == "all":
            phases = [self.WARMUP_PHASE_CHROMA, self.WARMUP_PHASE_EMBEDDER, self.WARMUP_PHASE_RERANKER]
        if phases is None:
            phases = self._WARMUP_AUTO_PHASES

        logger.info("[Warmup] 开始分阶段预热，计划阶段: %s", phases)
        t0 = time.time()

        if self.WARMUP_PHASE_CHROMA in phases:
            logger.info("[Warmup] === 阶段1: Chroma _ensure_connection BEGIN ===")
            try:
                self._record_stage("warmup_chroma")
                self._ensure_connection()
                logger.info("[Warmup] === 阶段1: Chroma _ensure_connection END (成功) ===")
            except Exception as e:
                logger.warning("[Warmup] === 阶段1: Chroma _ensure_connection END (失败: %s) ===", e)
                self._record_failure("warmup_chroma", str(e))

        if self.WARMUP_PHASE_EMBEDDER in phases:
            logger.info("[Warmup] === 阶段2: Embedder TextEmbedding 初始化 BEGIN ===")
            try:
                self._record_stage("warmup_embedder")
                t1 = time.time()
                self.embedder.warmup()
                logger.info("[Warmup] === 阶段2: Embedder TextEmbedding 初始化 END (成功, %.1fms) ===",
                           (time.time() - t1) * 1000)
                self._record_success("warmup_embedder", time.time() - t1)
            except Exception as e:
                logger.warning("[Warmup] === 阶段2: Embedder TextEmbedding 初始化 END (失败: %s) ===", e)
                self._record_failure("warmup_embedder", str(e))

        if self.WARMUP_PHASE_RERANKER in phases:
            logger.info("[Warmup] === 阶段3: Reranker TextCrossEncoder 初始化 BEGIN ===")
            try:
                self._record_stage("warmup_reranker")
                t1 = time.time()
                self.reranker.warmup()
                logger.info("[Warmup] === 阶段3: Reranker TextCrossEncoder 初始化 END (成功, %.1fms) ===",
                           (time.time() - t1) * 1000)
                self._record_success("warmup_reranker", time.time() - t1)
            except Exception as e:
                logger.warning("[Warmup] === 阶段3: Reranker TextCrossEncoder 初始化 END (失败: %s) ===", e)
                self._record_failure("warmup_reranker", str(e))

        total = time.time() - t0
        logger.info("[Warmup] 分阶段预热完成 (%.1fms), phases=%s, embedder=%s, reranker=%s",
                    total * 1000, phases, self.embedder.mode, self.reranker.mode)
        self._active_path = self._determine_active_path()

    # ========== V1 兼容接口 ==========

    def search_context(self, query: str, top_k: int = DEFAULT_TOP_K) -> str:
        return self.search(query, top_k)

    def update_file_index(self, file_path: str, content: str):
        return self.index_file(file_path, content)

    # ========== 状态 ==========

    def get_stats(self) -> dict:
        self._ensure_connection()
        stats = {
            "total_chunks": self._collection.count() if self._collection else 0,
            "indexed_files": len(self._file_hashes),
            "cache_size": self.cache.size,
            "db_path": self.db_path,
            "embedding_mode": self.embedder.mode,
            "reranker_mode": self.reranker.mode,
            "active_path": self._active_path,
            "health_state": self._health_state,
        }
        return stats
