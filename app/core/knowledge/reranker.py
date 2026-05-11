# filename: app/core/knowledge/reranker.py
import re
import time
from typing import List, Dict, Optional, Tuple

from app.core.knowledge.config import RERANK_MODEL, RERANK_ENABLED
from app.core.logging import get_logger
from app.core.debug import probe

logger = get_logger("app.core.knowledge.reranker", side="worker")


class Reranker:
    """
    精排器。优先 fastembed cross-encoder，不可用时降级到关键词匹配。
    """

    def __init__(self):
        self._model = None
        self._use_keyword = False
        self._initialized = False

    def _ensure_model(self):
        """延迟加载 cross-encoder"""
        if self._initialized:
            return
        self._initialized = True

        if not RERANK_ENABLED:
            self._use_keyword = True
            logger.info("重排序已禁用，使用关键词降级")
            probe("reranker_disabled", level="info", side="worker")
            return

        t0 = time.time()
        probe("reranker_ensure_model", level="info", side="worker", model=RERANK_MODEL)
        try:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
                import_path = "fastembed.rerank.cross_encoder.TextCrossEncoder"
            except Exception:
                from fastembed import TextCrossEncoder
                import_path = "fastembed.TextCrossEncoder"
            import_elapsed = time.time() - t0
            logger.info("加载 Rerank 模型: %s via %s (%.1fms)", RERANK_MODEL, import_path, import_elapsed * 1000)
            probe("reranker_import_done", level="info", side="worker",
                  import_path=import_path, elapsed_ms=round(import_elapsed * 1000, 1))

            t1 = time.time()
            self._model = TextCrossEncoder(model_name=RERANK_MODEL)
            init_elapsed = time.time() - t1
            logger.info("Rerank 模型就绪 (%.1fms)", init_elapsed * 1000)
            probe("reranker_init_done", level="info", side="worker",
                  elapsed_ms=round(init_elapsed * 1000, 1))
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning("cross-encoder 不可用，降级到关键词重排: %s (%.1fms)", e, elapsed * 1000)
            probe("reranker_fallback_keyword", level="warning", side="worker",
                  error=str(e)[:100], elapsed_ms=round(elapsed * 1000, 1))
            self._use_keyword = True

    def warmup(self):
        """预热模型，确保首次工具调用不承担初始化成本"""
        self._ensure_model()
        if self._model is None:
            return
        try:
            t0 = time.time()
            _ = list(self._model.rerank("warmup", ["test document"]))
            elapsed = time.time() - t0
            logger.info("Reranker 预热完成 (%.1fms)", elapsed * 1000)
            probe("reranker_warmup_done", level="info", side="worker",
                  elapsed_ms=round(elapsed * 1000, 1))
        except Exception as e:
            logger.warning("Reranker 预热推理失败: %s", e)
            probe("reranker_warmup_fail", level="warning", side="worker", error=str(e)[:100])

    def rerank(
        self,
        query: str,
        documents: List[str],
        metadatas: List[dict],
        distances: List[float],
        top_k: int
    ) -> Tuple[List[str], List[dict], List[float]]:
        """
        对粗排结果精排，返回 top_k 个结果。

        Returns:
            (documents, metadatas, scores) 精排后的三元组
        """
        if len(documents) <= top_k:
            scores = [max(0, 1 - d) for d in distances]
            return documents, metadatas, scores

        self._ensure_model()

        if self._model is not None:
            scores = self._cross_encoder_score(query, documents)
        else:
            scores = self._keyword_score(query, documents, distances)

        ranked = sorted(
            zip(documents, metadatas, scores),
            key=lambda x: x[2],
            reverse=True
        )

        docs = [r[0] for r in ranked[:top_k]]
        metas = [r[1] for r in ranked[:top_k]]
        final_scores = [r[2] for r in ranked[:top_k]]

        return docs, metas, final_scores

    def _cross_encoder_score(self, query: str, documents: List[str]) -> List[float]:
        """用 cross-encoder 计算 query-document 相关性分数"""
        t0 = time.time()
        try:
            scores = list(self._model.rerank(query, documents))
            elapsed = time.time() - t0
            if scores and hasattr(scores[0], "score"):
                score_map = {r.index: r.score for r in scores}
                result = [score_map.get(i, 0.0) for i in range(len(documents))]
            elif scores and isinstance(scores[0], (int, float)):
                result = [float(s) for s in scores]
            else:
                logger.warning("未知 rerank 返回格式: %s", type(scores[0]) if scores else None)
                probe("reranker_unknown_format", level="warning", side="worker",
                      score_type=str(type(scores[0])) if scores else "empty")
                result = [0.5] * len(documents)
            probe("reranker_cross_encoder_done", level="debug", side="worker",
                  doc_count=len(documents), elapsed_ms=round(elapsed * 1000, 1))
            return result
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning("cross-encoder 评分失败，降级到关键词: %s (%.1fms)", e, elapsed * 1000)
            probe("reranker_cross_encoder_fail", level="warning", side="worker",
                  error=str(e)[:100], elapsed_ms=round(elapsed * 1000, 1))
            return self._keyword_score(query, documents, [0.5] * len(documents))

    def _keyword_score(
        self, query: str, documents: List[str], distances: List[float]
    ) -> List[float]:
        """
        关键词重排：结合向量距离 + 关键词命中率。
        不需要额外模型，作为 cross-encoder 的降级方案。
        """
        probe("reranker_keyword_fallback", level="info", side="worker",
              doc_count=len(documents))
        tokens = self._extract_tokens(query)
        if not tokens:
            return [max(0, 1 - d) for d in distances]

        scores = []
        for i, doc in enumerate(documents):
            doc_lower = doc.lower()

            vec_score = max(0, 1 - distances[i])
            hits = sum(1 for t in tokens if t in doc_lower)
            keyword_score = hits / len(tokens)
            phrase_score = 1.0 if query.lower() in doc_lower else 0.0

            final = 0.6 * vec_score + 0.25 * keyword_score + 0.15 * phrase_score
            scores.append(round(final, 4))

        return scores

    @staticmethod
    def _extract_tokens(text: str) -> List[str]:
        """提取有意义的关键词 token"""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after",
            "and", "but", "or", "nor", "not", "so", "yet", "both",
            "it", "its", "this", "that", "these", "those", "what",
            "which", "who", "whom", "how", "when", "where", "why",
            "i", "me", "my", "we", "our", "you", "your", "he", "she",
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
            "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
            "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
        }

        tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|[\u4e00-\u9fff]+", text.lower())
        return [t for t in tokens if t not in stop_words and len(t) > 1]

    @property
    def mode(self) -> str:
        if self._model is not None:
            return "cross_encoder"
        if self._use_keyword:
            return "keyword"
        return "not_initialized"
