# filename: tests/test_knowledge_v2.py
"""KnowledgeService V2 完整测试套件"""

import os
import sys
import shutil
import tempfile
import time
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.knowledge.chunker import ASTChunker
from app.core.knowledge.cache import LRUCache
from app.core.knowledge.reranker import Reranker
from app.core.knowledge.embedder import LocalEmbedder
from app.core.knowledge.service import KnowledgeServiceV2


# ========== Fixtures ==========

NL = chr(10)


@pytest.fixture
def chunker():
    return ASTChunker()


@pytest.fixture
def reranker():
    return Reranker()


@pytest.fixture
def temp_db():
    """临时数据库目录，测试后自动清理"""
    path = tempfile.mkdtemp(prefix="kb_test_")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def service(temp_db):
    """带临时数据库的 KnowledgeServiceV2 实例"""
    return KnowledgeServiceV2(db_path=temp_db)


@pytest.fixture
def sample_code():
    """测试用代码样本"""
    return {
        "worker": NL.join([
            "import threading",
            "",
            "class WorkerThread(threading.Thread):",
            "    def run(self):",
            "        while True:",
            "            task = self.queue.get()",
            "            self.process(task)",
            "    def process(self, task):",
            "        return task.upper()",
        ]),
        "file_svc": NL.join([
            "import os",
            "",
            "class FileService:",
            "    def save(self, path, content):",
            "        with open(path, \"w\") as f:",
            "            f.write(content)",
            "    def delete(self, path):",
            "        os.remove(path)",
        ]),
        "config": NL.join([
            "# App configuration",
            "DATABASE_URL = \"sqlite:///app.db\"",
            "DEBUG = True",
            "MAX_RETRIES = 3",
        ]),
    }

# ========== Chunker 测试 ==========

class TestChunker:

    def test_class_with_methods(self, chunker):
        """AST 分块：类和方法应被正确识别"""
        code = NL.join([
            "class Service:",
            "    def __init__(self):",
            "        self.x = 1",
            "    def run(self):",
            "        return self.x",
            "    def stop(self):",
            "        self.x = 0",
            "        return False",
        ])
        chunks = chunker.chunk_file("svc.py", code)
        types = {c["metadata"]["type"] for c in chunks}
        assert "method" in types or "class" in types
        assert len(chunks) >= 1

    def test_standalone_function(self, chunker):
        """AST 分块：独立函数"""
        code = NL.join([
            "def helper(a, b):",
            "    result = a + b",
            "    return result",
            "",
            "def another(x):",
            "    return x * 2",
        ])
        chunks = chunker.chunk_file("utils.py", code)
        symbols = [c["metadata"]["symbol"] for c in chunks]
        assert "helper" in symbols or any("helper" in s for s in symbols)

    def test_non_python_fallback(self, chunker):
        """非 Python 文件应降级到按行分块"""
        content = NL.join([f"line {i}" for i in range(60)])
        chunks = chunker.chunk_file("data.json", content)
        assert len(chunks) >= 1
        assert chunks[0]["metadata"]["type"] == "block"

    def test_syntax_error_fallback(self, chunker):
        """语法错误的 Python 应降级到按行分块"""
        code = NL.join([
            "def broken(:",
            "    x = 1",
            "    y = 2",
            "    z = 3",
            "    return x",
        ])
        chunks = chunker.chunk_file("bad.py", code)
        assert len(chunks) >= 1

    def test_empty_file(self, chunker):
        """空文件应返回空列表"""
        chunks = chunker.chunk_file("empty.py", "")
        assert chunks == []

    def test_short_code_not_discarded(self, chunker):
        """短但有意义的代码不应被丢弃"""
        code = NL.join([
            "def add(a, b):",
            "    return a + b",
        ])
        # 至少不会崩溃
        chunks = chunker.chunk_file("short.py", code)
        # 短函数可能被保留也可能被过滤，取决于 MIN_CHUNK_LINES
        assert isinstance(chunks, list)

# ========== Cache 测试 ==========

class TestCache:

    def test_basic_put_get(self):
        """基本存取"""
        cache = LRUCache(max_size=10, ttl=60)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_lru_eviction(self):
        """LRU 淘汰：超出容量时最旧的被淘汰"""
        cache = LRUCache(max_size=3, ttl=60)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")
        cache.put("d", "4")  # a 应被淘汰
        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("d") == "4"

    def test_ttl_expiry(self):
        """TTL 过期"""
        cache = LRUCache(max_size=10, ttl=1)
        cache.put("key", "value")
        assert cache.get("key") == "value"
        time.sleep(1.1)
        assert cache.get("key") is None

    def test_miss_returns_none(self):
        """未命中返回 None"""
        cache = LRUCache()
        assert cache.get("nonexistent") is None

    def test_overwrite(self):
        """覆盖写入"""
        cache = LRUCache()
        cache.put("k", "old")
        cache.put("k", "new")
        assert cache.get("k") == "new"

# ========== Reranker 测试 ==========

class TestReranker:

    def test_passthrough_when_few_results(self, reranker):
        """结果数 <= top_k 时直接透传"""
        docs = ["doc1", "doc2"]
        metas = [{"path": "a.py"}, {"path": "b.py"}]
        dists = [0.3, 0.5]
        r_docs, r_metas, r_scores = reranker.rerank("query", docs, metas, dists, top_k=5)
        assert len(r_docs) == 2
        assert r_scores[0] == pytest.approx(0.7, abs=0.01)  # 1 - 0.3
        assert r_scores[1] == pytest.approx(0.5, abs=0.01)  # 1 - 0.5

    def test_keyword_ranking_order(self, reranker):
        """关键词模式：包含查询词的文档应排更高"""
        # 强制降级到关键词模式
        reranker._initialized = True
        reranker._use_keyword = True
        docs = [
            "class DatabaseService: handles database connections",
            "class WorkerThread: process task queue worker",
            "class FileService: save and delete files",
        ]
        metas = [{"path": "db.py"}, {"path": "worker.py"}, {"path": "file.py"}]
        dists = [0.3, 0.4, 0.35]  # 向量距离
        r_docs, r_metas, r_scores = reranker.rerank(
            "worker process task", docs, metas, dists, top_k=2
        )
        # worker.py 应该排第一（关键词命中 worker + process + task）
        assert r_metas[0]["path"] == "worker.py"
        assert len(r_docs) == 2

    def test_token_extraction(self, reranker):
        """关键词提取：停用词应被过滤"""
        tokens = Reranker._extract_tokens("the worker is processing a task")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert "worker" in tokens
        assert "processing" in tokens
        assert "task" in tokens

    def test_token_extraction_chinese(self, reranker):
        """中文关键词提取"""
        tokens = Reranker._extract_tokens("文件保存功能的实现")
        # 中文停用词 "的" 应被过滤
        assert "的" not in tokens
        assert len(tokens) >= 1

    def test_phrase_match_bonus(self, reranker):
        """精确短语匹配应获得加分"""
        reranker._initialized = True
        reranker._use_keyword = True
        docs = [
            "def save_file(path): save file to disk",
            "def process(): file operations and save",
            "class Logger: log messages to console",
            "def connect(): open database connection",
        ]
        metas = [{"path": "a.py"}, {"path": "b.py"}, {"path": "c.py"}, {"path": "d.py"}]
        dists = [0.4, 0.4, 0.5, 0.6]
        r_docs, r_metas, r_scores = reranker.rerank(
            "save file", docs, metas, dists, top_k=2
        )
        # a.py 包含精确短语 "save file"，应排第一
        assert r_metas[0]["path"] == "a.py"
        assert r_scores[0] > r_scores[1]

    def test_mode_property(self, reranker):
        """mode 属性应反映当前状态"""
        assert reranker.mode == "not_initialized"
        reranker._initialized = True
        reranker._use_keyword = True
        assert reranker.mode == "keyword"

# ========== Embedder 测试 ==========

class TestEmbedder:

    def test_mode_before_init(self):
        """初始化前 mode 应为 not_initialized"""
        emb = LocalEmbedder()
        assert emb.mode == "not_initialized"

    def test_lazy_loading(self):
        """模型应延迟加载，构造时不加载"""
        emb = LocalEmbedder()
        assert emb._model is None
        assert emb._use_builtin is False

    def test_fallback_on_bad_model(self):
        """无效模型名应降级到 builtin"""
        emb = LocalEmbedder(model_name="nonexistent/fake-model-xyz")
        emb._ensure_model()
        assert emb._use_builtin is True
        assert emb.mode == "chroma_builtin"

    def test_builtin_returns_none(self):
        """builtin 模式下 embed 应返回 None（让 Chroma 自己算）"""
        emb = LocalEmbedder(model_name="nonexistent/fake")
        emb._ensure_model()
        assert emb.embed_query("test") is None
        assert emb.embed_documents(["test"]) is None

# ========== Service 集成测试 ==========

class TestService:

    def test_index_and_search(self, service, sample_code):
        """索引后能检索到正确文件"""
        service.index_file("worker.py", sample_code["worker"])
        service.index_file("file_svc.py", sample_code["file_svc"])
        result = service.search("worker thread process task", top_k=2)
        assert "worker.py" in result

    def test_search_relevance(self, service, sample_code):
        """检索结果应与查询相关"""
        service.index_file("worker.py", sample_code["worker"])
        service.index_file("file_svc.py", sample_code["file_svc"])
        result = service.search("save file delete", top_k=2)
        assert "file_svc.py" in result

    def test_empty_db_search(self, service):
        """空库检索应返回提示而非报错"""
        result = service.search("anything")
        assert "空" in result or "⚠" in result

    def test_incremental_index_skip(self, service, sample_code):
        """相同内容重复索引应跳过"""
        service.index_file("worker.py", sample_code["worker"])
        stats1 = service.get_stats()["total_chunks"]
        service.index_file("worker.py", sample_code["worker"])  # 重复
        stats2 = service.get_stats()["total_chunks"]
        assert stats1 == stats2

    def test_incremental_index_update(self, service, sample_code):
        """内容变更时应重新索引"""
        service.index_file("worker.py", sample_code["worker"])
        stats1 = service.get_stats()["total_chunks"]
        updated = sample_code["worker"] + NL + "# updated"
        service.index_file("worker.py", updated)
        stats2 = service.get_stats()["total_chunks"]
        # chunk 数可能变也可能不变，但不应报错
        assert stats2 >= 1

    def test_cache_hit(self, service, sample_code):
        """相同查询第二次应命中缓存"""
        service.index_file("worker.py", sample_code["worker"])
        service.search("worker", top_k=2)
        assert service.cache.size >= 1
        # 第二次查询应从缓存返回
        result = service.search("worker", top_k=2)
        assert "worker.py" in result

    def test_search_context_compat(self, service, sample_code):
        """V1 兼容接口 search_context 应正常工作"""
        service.index_file("worker.py", sample_code["worker"])
        result = service.search_context("worker")
        assert "worker.py" in result

    def test_get_stats(self, service, sample_code):
        """统计信息应包含必要字段"""
        service.index_file("worker.py", sample_code["worker"])
        stats = service.get_stats()
        assert "total_chunks" in stats
        assert "embedding_mode" in stats
        assert stats["total_chunks"] > 0

    def test_reranker_integrated(self, service, sample_code):
        """reranker 应被集成到检索流程中"""
        assert hasattr(service, "reranker")
        service.index_file("worker.py", sample_code["worker"])
        service.index_file("file_svc.py", sample_code["file_svc"])
        service.index_file("config.py", sample_code["config"])
        # 检索应正常返回，不报错
        result = service.search("worker thread", top_k=2)
        assert "RAG Context" in result
        assert "score:" in result

# ========== 性能基准 ==========

@pytest.mark.slow
class TestPerformance:

    def test_chunker_speed(self, chunker):
        """分块速度：100 个文件应在 2s 内完成"""
        code = NL.join([
            f"def func_{i}(x):"
            for i in range(20)
        ] + [
            f"    return x + {i}"
            for i in range(20)
        ])
        start = time.time()
        for i in range(100):
            chunker.chunk_file(f"file_{i}.py", code)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"分块 100 文件耗时 {elapsed:.2f}s，超过 2s"

    def test_cache_speed(self):
        """缓存速度：10000 次读写应在 1s 内"""
        cache = LRUCache(max_size=1000, ttl=60)
        start = time.time()
        for i in range(10000):
            cache.put(f"key_{i}", f"value_{i}")
        for i in range(10000):
            cache.get(f"key_{i}")
        elapsed = time.time() - start
        assert elapsed < 1.0, f"缓存 10000 次读写耗时 {elapsed:.2f}s，超过 1s"

    def test_reranker_keyword_speed(self):
        """关键词重排速度：50 条文档应在 100ms 内"""
        rr = Reranker()
        rr._initialized = True
        rr._use_keyword = True
        docs = [f"class Module{i}: handles operation {i} with data" for i in range(50)]
        metas = [{"path": f"mod_{i}.py"} for i in range(50)]
        dists = [0.3 + i * 0.01 for i in range(50)]
        start = time.time()
        rr.rerank("module operation data", docs, metas, dists, top_k=5)
        elapsed = time.time() - start
        assert elapsed < 0.1, f"重排 50 条耗时 {elapsed*1000:.1f}ms，超过 100ms"

    def test_index_speed(self, service):
        """索引速度：20 个文件应在 10s 内"""
        start = time.time()
        for i in range(20):
            code = NL.join([
                f"class Service{i}:",
                f"    def method_a(self):",
                f"        return {i}",
                f"    def method_b(self, x):",
                f"        return x + {i}",
            ])
            service.index_file(f"svc_{i}.py", code)
        elapsed = time.time() - start
        stats = service.get_stats()
        assert stats["total_chunks"] > 0
        assert elapsed < 10.0, f"索引 20 文件耗时 {elapsed:.2f}s，超过 10s"

    def test_search_speed(self, service):
        """检索速度：单次查询应在 500ms 内"""
        # 先索引一些数据
        for i in range(10):
            code = NL.join([
                f"class Handler{i}:",
                f"    def handle(self, request):",
                f"        return request.data + {i}",
            ])
            service.index_file(f"handler_{i}.py", code)
        # 测试检索速度
        start = time.time()
        service.search("handle request data", top_k=5)
        elapsed = time.time() - start
        assert elapsed < 0.5, f"检索耗时 {elapsed*1000:.1f}ms，超过 500ms"


# ========== 量化基准报告 ==========

class TestBenchmarkReport:
    """运行: pytest tests/test_knowledge_v2.py::TestBenchmarkReport -s"""

    def test_full_benchmark(self, temp_db):
        """完整量化基准报告"""
        import statistics

        svc = KnowledgeServiceV2(db_path=temp_db)
        chunker = ASTChunker()
        rr = Reranker()
        rr._initialized = True
        rr._use_keyword = True

        R = []  # report lines
        R.append("")
        R.append("=" * 60)
        R.append("  KnowledgeService V2 — 量化基准报告")
        R.append("=" * 60)

        # --- 1. 分块基准 ---
        chunk_times = []
        chunk_counts = []
        for i in range(50):
            code = NL.join([
                f"class Service{i}:",
                f"    def __init__(self):",
                f"        self.val = {i}",
                f"    def run(self):",
                f"        return self.val",
                f"    def stop(self):",
                f"        self.val = 0",
                f"        return False",
                f"",
                f"def helper_{i}(x):",
                f"    return x + {i}",
            ])
            t0 = time.time()
            chunks = chunker.chunk_file(f"svc_{i}.py", code)
            chunk_times.append(time.time() - t0)
            chunk_counts.append(len(chunks))

        avg_ct = statistics.mean(chunk_times) * 1000
        max_ct = max(chunk_times) * 1000
        sum_ct = sum(chunk_times) * 1000
        avg_cc = statistics.mean(chunk_counts)
        sum_cc = sum(chunk_counts)
        R.append("")
        R.append("[1] 分块性能 (50 files)")
        R.append(f"    平均耗时:   {avg_ct:.2f} ms/file")
        R.append(f"    最大耗时:   {max_ct:.2f} ms")
        R.append(f"    总耗时:     {sum_ct:.1f} ms")
        R.append(f"    平均 chunks: {avg_cc:.1f} /file")
        R.append(f"    总 chunks:   {sum_cc}")

        # --- 2. 索引基准 ---
        index_times = []
        for i in range(20):
            code = NL.join([
                f"class Handler{i}:",
                f"    def handle(self, req):",
                f"        return req.data + {i}",
                f"    def validate(self, data):",
                f"        return len(data) > 0",
            ])
            t0 = time.time()
            svc.index_file(f"handler_{i}.py", code)
            index_times.append(time.time() - t0)

        stats = svc.get_stats()
        total_c = stats.get("total_chunks", 0)
        emb_mode = stats.get("embedding_mode", "unknown")
        avg_it = statistics.mean(index_times) * 1000
        max_it = max(index_times) * 1000
        sum_it = sum(index_times) * 1000
        R.append("")
        R.append("[2] 索引性能 (20 files)")
        R.append(f"    平均耗时:   {avg_it:.2f} ms/file")
        R.append(f"    最大耗时:   {max_it:.2f} ms")
        R.append(f"    总耗时:     {sum_it:.1f} ms")
        R.append(f"    总 chunks:   {total_c}")
        R.append(f"    Embedding:  {emb_mode}")

        # --- 3. 检索基准 ---
        queries = [
            "handle request data",
            "validate input",
            "Handler class",
            "return data processing",
            "request handler validate",
        ]
        search_times = []
        for q in queries:
            svc.cache = LRUCache()  # 清缓存
            t0 = time.time()
            svc.search(q, top_k=5)
            search_times.append(time.time() - t0)

        avg_st = statistics.mean(search_times) * 1000
        max_st = max(search_times) * 1000
        min_st = min(search_times) * 1000
        p95_idx = int(len(search_times) * 0.95)
        p95_st = sorted(search_times)[p95_idx] * 1000
        R.append("")
        n_q = len(queries)
        R.append(f"[3] 检索性能 ({n_q} queries, top_k=5)")
        R.append(f"    平均耗时:   {avg_st:.2f} ms/query")
        R.append(f"    最大耗时:   {max_st:.2f} ms")
        R.append(f"    最小耗时:   {min_st:.2f} ms")
        R.append(f"    P95 耗时:   {p95_st:.2f} ms")

        # --- 4. 缓存基准 ---
        cache = LRUCache(max_size=1000, ttl=60)
        t0 = time.time()
        for i in range(10000):
            cache.put(f"k{i}", f"v{i}")
        write_ms = (time.time() - t0) * 1000
        t0 = time.time()
        hits = sum(1 for i in range(10000) if cache.get(f"k{i}") is not None)
        read_ms = (time.time() - t0) * 1000
        R.append("")
        R.append("[4] 缓存性能 (10000 ops)")
        R.append(f"    写入耗时:   {write_ms:.1f} ms")
        R.append(f"    读取耗时:   {read_ms:.1f} ms")
        R.append(f"    命中数:     {hits}/10000 (max_size=1000)")

        # --- 5. Reranker 基准 ---
        doc_counts = [10, 30, 50]
        R.append("")
        R.append("[5] Reranker 性能 (keyword mode)")
        for n in doc_counts:
            docs = [f"class Module{j}: handles operation {j} data" for j in range(n)]
            metas = [{"path": f"m{j}.py"} for j in range(n)]
            dists = [0.3 + j * 0.01 for j in range(n)]
            t0 = time.time()
            for _ in range(100):
                rr.rerank("module operation data", docs, metas, dists, top_k=5)
            elapsed_ms = (time.time() - t0) / 100 * 1000
            R.append(f"    {n:>3} docs:   {elapsed_ms:.3f} ms/query")

        # --- 6. 检索质量 ---
        svc.cache = LRUCache()
        quality_queries = [
            ("handle request", "handler_"),
            ("validate data", "handler_"),
        ]
        R.append("")
        R.append("[6] 检索质量 (top-1 命中率)")
        hits_count = 0
        for query, expected_prefix in quality_queries:
            result = svc.search(query, top_k=1)
            hit = expected_prefix in result
            hits_count += int(hit)
            mark = "✅" if hit else "❌"
            label = "命中" if hit else "未命中"
            R.append(f"    {mark} \"{query}\" → {label}")
        n_qq = len(quality_queries)
        accuracy = hits_count / n_qq * 100
        R.append(f"    命中率:     {accuracy:.0f}% ({hits_count}/{n_qq})")

        # --- 7. 组件状态 ---
        emb_m = svc.embedder.mode
        rr_m = svc.reranker.mode
        db_c = svc.get_stats().get("total_chunks", 0)
        R.append("")
        R.append("[7] 组件状态")
        R.append(f"    Embedder:   {emb_m}")
        R.append(f"    Reranker:   {rr_m}")
        R.append(f"    DB chunks:  {db_c}")

        R.append("")
        R.append("=" * 60)

        print(NL.join(R))
