"""检索质量基准测试

用 CodeSearchNet + 手工补充数据集评估 KnowledgeServiceV2 的检索质量。
默认不随 pytest 运行，需显式指定: pytest -m benchmark -s
"""
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.knowledge.service import KnowledgeServiceV2

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
BASELINE_PATH = Path(__file__).parent / "baseline.json"


def load_dataset():
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_metrics(ranks, total):
    """从排名列表计算 MRR 和 Recall@K"""
    mrr = 0.0
    recall_at = {1: 0, 3: 0, 5: 0}

    for rank in ranks:
        if rank is not None:
            mrr += 1.0 / rank
            for k in recall_at:
                if rank <= k:
                    recall_at[k] += 1

    mrr /= total
    for k in recall_at:
        recall_at[k] /= total

    return {
        "mrr": round(mrr, 4),
        "recall_at_1": round(recall_at[1], 4),
        "recall_at_3": round(recall_at[3], 4),
        "recall_at_5": round(recall_at[5], 4),
    }


@pytest.mark.benchmark
class TestRetrievalQuality:
    """检索质量基准测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """创建临时服务实例并索引数据集"""
        self.dataset = load_dataset()
        db_path = str(tmp_path / "bench.db")
        self.service = KnowledgeServiceV2(db_path=db_path)

        # 索引所有代码片段
        for item in self.dataset:
            ext = {
                "python": ".py", "javascript": ".js",
                "java": ".java", "go": ".go",
                "yaml": ".yaml", "toml": ".toml",
                "markdown": ".md", "dockerfile": ".dockerfile",
                "shell": ".sh",
            }.get(item["language"], ".txt")
            filename = item["id"] + ext
            self.service.index_file(filename, item["code"])

    @staticmethod
    def _parse_search_results(result_str):
        """解析 search() 返回的格式化字符串，提取文件路径列表"""
        paths = []
        for line in result_str.splitlines():
            line = line.strip()
            if line.startswith(">> File:"):
                # 格式: >> File: path | type: symbol (score: 0.85)
                part = line[len(">> File:"):].strip()
                path = part.split("|")[0].strip().split("(")[0].strip()
                paths.append(path)
        return paths

    def _run_benchmark(self, items, top_k=5):
        """对一组 items 跑检索，返回排名列表"""
        ranks = []
        for item in items:
            result_str = self.service.search(item["query"], top_k=top_k)
            paths = self._parse_search_results(result_str)
            rank = None
            target_id = item["id"]
            for i, path in enumerate(paths, 1):
                # 文件名包含 item ID (如 csn_py_001.py)
                if target_id in path:
                    rank = i
                    break
            ranks.append(rank)
        return ranks

    def test_overall_quality(self):
        """整体检索质量"""
        ranks = self._run_benchmark(self.dataset)
        metrics = compute_metrics(ranks, len(self.dataset))

        print()
        print("=" * 50)
        print("  检索质量基准 - 整体")
        print("=" * 50)
        print(f"  数据集: {len(self.dataset)} 条")
        _mrr = metrics["mrr"]
        _r1 = metrics["recall_at_1"]
        _r3 = metrics["recall_at_3"]
        _r5 = metrics["recall_at_5"]
        print(f"  MRR:       {_mrr:.4f}")
        print(f"  Recall@1:  {_r1:.4f}")
        print(f"  Recall@3:  {_r3:.4f}")
        print(f"  Recall@5:  {_r5:.4f}")

        # 基线回归检查
        self._check_regression(metrics)

    def test_by_language(self):
        """分语言检索质量"""
        by_lang = defaultdict(list)
        for item in self.dataset:
            by_lang[item["language"]].append(item)

        print()
        print("=" * 50)
        print("  检索质量基准 - 分语言")
        print("=" * 50)

        all_lang_metrics = {}
        for lang in sorted(by_lang.keys()):
            items = by_lang[lang]
            ranks = self._run_benchmark(items)
            metrics = compute_metrics(ranks, len(items))
            all_lang_metrics[lang] = metrics
            _mrr = metrics["mrr"]
            _r3 = metrics["recall_at_3"]
            _n = len(items)
            print(f"  {lang:12s}  MRR={_mrr:.3f}  R@3={_r3:.3f}  ({_n} 条)")

    def test_by_source(self):
        """CodeSearchNet vs 手工数据对比"""
        csn = [x for x in self.dataset if x["source"] == "CodeSearchNet"]
        manual = [x for x in self.dataset if x["source"] == "manual"]

        print()
        print("=" * 50)
        print("  检索质量基准 - 数据来源")
        print("=" * 50)

        for label, items in [("CodeSearchNet", csn), ("Manual", manual)]:
            ranks = self._run_benchmark(items)
            metrics = compute_metrics(ranks, len(items))
            _mrr = metrics["mrr"]
            _r3 = metrics["recall_at_3"]
            _n = len(items)
            print(f"  {label:15s}  MRR={_mrr:.3f}  R@3={_r3:.3f}  ({_n} 条)")

    def _check_regression(self, current_metrics):
        """与基线对比，检查是否回归"""
        if not BASELINE_PATH.exists():
            print()
            print("  [INFO] 无基线文件，跳过回归检查")
            print("  运行 pytest -m benchmark --update-baseline 生成基线")
            return

        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            baseline = json.load(f)

        base_metrics = baseline.get("metrics", {})
        print()
        print("  --- 基线对比 ---")

        mrr_drop = base_metrics.get("mrr", 0) - current_metrics["mrr"]
        r3_drop = base_metrics.get("recall_at_3", 0) - current_metrics["recall_at_3"]

        _b_mrr = base_metrics.get("mrr", 0)
        _c_mrr = current_metrics["mrr"]
        _b_r3 = base_metrics.get("recall_at_3", 0)
        _c_r3 = current_metrics["recall_at_3"]
        print(f"  MRR:      {_b_mrr:.4f} -> {_c_mrr:.4f}  (delta: {-mrr_drop:+.4f})")
        print(f"  Recall@3: {_b_r3:.4f} -> {_c_r3:.4f}  (delta: {-r3_drop:+.4f})")

        assert mrr_drop <= 0.05, f"MRR 回归超过 5%: {mrr_drop:.4f}"
        assert r3_drop <= 0.10, f"Recall@3 回归超过 10%: {r3_drop:.4f}"
