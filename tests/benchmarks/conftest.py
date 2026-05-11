import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.knowledge.service import KnowledgeServiceV2

DATASET_PATH = Path(__file__).parent / "retrieval" / "golden_dataset.json"
BASELINE_PATH = Path(__file__).parent / "retrieval" / "baseline.json"


def load_dataset():
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_metrics(ranks, total):
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


def _parse_search_results(result_str):
    """解析 search() 返回的格式化字符串，提取文件路径列表"""
    paths = []
    for line in result_str.splitlines():
        line = line.strip()
        if line.startswith(">> File:"):
            part = line[len(">> File:"):].strip()
            path = part.split("|")[0].strip().split("(")[0].strip()
            paths.append(path)
    return paths


def pytest_addoption(parser):
    """添加 --update-baseline 命令行选项"""
    try:
        parser.addoption(
            "--update-baseline",
            action="store_true",
            default=False,
            help="更新基线文件"
        )
    except ValueError:
        pass


@pytest.fixture(autouse=True, scope="session")
def update_baseline_if_requested(request):
    """测试结束后，如果指定了 --update-baseline，保存基线"""
    yield
    if not request.config.getoption("--update-baseline", default=False):
        return

    dataset = load_dataset()
    tmp_dir = os.path.join(os.environ.get("TEMP", "/tmp"), "bench_baseline")
    os.makedirs(tmp_dir, exist_ok=True)
    db_path = os.path.join(tmp_dir, "bench.db")

    try:
        svc = KnowledgeServiceV2(db_path=db_path)

        ext_map = {
            "python": ".py", "javascript": ".js",
            "java": ".java", "go": ".go",
            "yaml": ".yaml", "toml": ".toml",
            "markdown": ".md", "dockerfile": ".dockerfile",
            "shell": ".sh",
        }

        for item in dataset:
            ext = ext_map.get(item["language"], ".txt")
            svc.index_file(item["id"] + ext, item["code"])

        ranks = []
        for item in dataset:
            result_str = svc.search(item["query"], top_k=5)
            paths = _parse_search_results(result_str)
            rank = None
            for i, path in enumerate(paths, 1):
                if item["id"] in path:
                    rank = i
                    break
            ranks.append(rank)

        metrics = compute_metrics(ranks, len(dataset))

        # 释放 ChromaDB 连接（Windows 文件锁）
        svc._client = None
        svc._collection = None

    except Exception as e:
        print(f"  [BASELINE ERROR] {e}")
        return

    baseline = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataset_size": len(dataset),
        "metrics": metrics,
    }

    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)

    print()
    _m = metrics["mrr"]
    _r = metrics["recall_at_3"]
    print(f"  [BASELINE] 已保存到 {BASELINE_PATH}")
    print(f"  MRR={_m:.4f}  Recall@3={_r:.4f}")

    # 清理临时目录（忽略 Windows 锁错误）
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass