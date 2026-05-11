# filename: app/core/knowledge/embedder.py
import time
from typing import List
from app.core.knowledge.config import EMBEDDING_MODEL
from app.core.logging import get_logger
from app.core.debug import probe

logger = get_logger("app.core.knowledge.embedder", side="worker")


class LocalEmbedder:
    """
    本地 Embedding 引擎。
    优先 fastembed（ONNX），模型不可用时降级到 Chroma 内置。
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.model_name = model_name
        self._model = None
        self._use_builtin = False

    def _ensure_model(self):
        """延迟加载模型"""
        if self._model is not None or self._use_builtin:
            return
        t0 = time.time()
        probe("embedder_ensure_model", level="info", side="worker", model=self.model_name)
        try:
            logger.info("加载 Embedding 模型: %s", self.model_name)
            from fastembed import TextEmbedding
            import_elapsed = time.time() - t0
            logger.info("fastembed import 完成 (%.1fms)", import_elapsed * 1000)
            probe("embedder_import_done", level="info", side="worker",
                  elapsed_ms=round(import_elapsed * 1000, 1))

            t1 = time.time()
            self._model = TextEmbedding(model_name=self.model_name)
            init_elapsed = time.time() - t1
            logger.info("Embedding 模型就绪 (%.1fms)", init_elapsed * 1000)
            probe("embedder_init_done", level="info", side="worker",
                  elapsed_ms=round(init_elapsed * 1000, 1))
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning("fastembed 不可用，降级到 Chroma 内置: %s (%.1fms)", e, elapsed * 1000)
            probe("embedder_fallback_builtin", level="warning", side="worker",
                  error=str(e)[:100], elapsed_ms=round(elapsed * 1000, 1))
            self._use_builtin = True

    def warmup(self):
        """预热模型，确保首次工具调用不承担初始化成本"""
        self._ensure_model()
        if self._use_builtin:
            return
        try:
            t0 = time.time()
            _ = list(self._model.embed(["warmup"]))
            elapsed = time.time() - t0
            logger.info("Embedder 预热完成 (%.1fms)", elapsed * 1000)
            probe("embedder_warmup_done", level="info", side="worker",
                  elapsed_ms=round(elapsed * 1000, 1))
        except Exception as e:
            logger.warning("Embedder 预热推理失败: %s", e)
            probe("embedder_warmup_fail", level="warning", side="worker", error=str(e)[:100])

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量生成 embedding，fastembed 不可用时返回 None（让 Chroma 自己算）"""
        self._ensure_model()
        if self._use_builtin:
            return None
        t0 = time.time()
        try:
            embeddings = list(self._model.embed(texts))
            elapsed = time.time() - t0
            probe("embedder_embed_docs", level="debug", side="worker",
                  count=len(texts), elapsed_ms=round(elapsed * 1000, 1))
            return [e.tolist() for e in embeddings]
        except Exception as e:
            elapsed = time.time() - t0
            logger.error("embed_documents 失败: %s (%.1fms)", e, elapsed * 1000)
            probe("embedder_embed_docs_fail", level="error", side="worker",
                  error=str(e)[:100], elapsed_ms=round(elapsed * 1000, 1))
            raise

    def embed_query(self, text: str) -> List[float]:
        """单条查询 embedding，fastembed 不可用时返回 None"""
        self._ensure_model()
        if self._use_builtin:
            return None
        t0 = time.time()
        try:
            embeddings = list(self._model.embed([text]))
            elapsed = time.time() - t0
            probe("embedder_embed_query", level="debug", side="worker",
                  text_len=len(text), elapsed_ms=round(elapsed * 1000, 1))
            return embeddings[0].tolist()
        except Exception as e:
            elapsed = time.time() - t0
            logger.error("embed_query 失败: %s (%.1fms)", e, elapsed * 1000)
            probe("embedder_embed_query_fail", level="error", side="worker",
                  error=str(e)[:100], elapsed_ms=round(elapsed * 1000, 1))
            raise

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def mode(self) -> str:
        if self._model is not None:
            return "fastembed"
        if self._use_builtin:
            return "chroma_builtin"
        return "not_initialized"
