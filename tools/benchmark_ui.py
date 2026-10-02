"""
Benchmark UI - 检索质量基准测试仪表盘

启动方式: streamlit run tools/benchmark_ui.py
开发期工具，上线前移除。
"""
import json
import os
import sys
import time
import tempfile
from pathlib import Path
from collections import defaultdict

import streamlit as st

# ── 路径设置 ──
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.knowledge.service import KnowledgeServiceV2

DATASET_PATH = ROOT / "tests" / "benchmarks" / "retrieval" / "golden_dataset.json"
BASELINE_PATH = ROOT / "tests" / "benchmarks" / "retrieval" / "baseline.json"


# ── 工具函数 ──

def load_dataset():
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_search_results(result_str):
    """解析 search() 返回的格式化字符串"""
    paths = []
    for line in result_str.splitlines():
        line = line.strip()
        if line.startswith(">> File:"):
            part = line[len(">> File:"):].strip()
            path = part.split("|")[0].strip().split("(")[0].strip()
            paths.append(path)
    return paths


def compute_metrics(ranks, total):
    if total == 0:
        return {"mrr": 0, "recall_at_1": 0, "recall_at_3": 0, "recall_at_5": 0}
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


def load_baseline():
    if BASELINE_PATH.exists():
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def run_benchmark(dataset, top_k, progress_cb=None):
    """跑完整基准，返回 (ranks, details, metrics_by_lang, elapsed)"""
    tmp_dir = tempfile.mkdtemp(prefix="bench_ui_")
    db_path = os.path.join(tmp_dir, "bench.db")
    svc = KnowledgeServiceV2(db_path=db_path)

    ext_map = {
        "python": ".py", "javascript": ".js",
        "java": ".java", "go": ".go",
        "yaml": ".yaml", "toml": ".toml",
        "markdown": ".md", "dockerfile": ".dockerfile",
        "shell": ".sh",
    }

    # 索引
    t0 = time.time()
    for i, item in enumerate(dataset):
        ext = ext_map.get(item["language"], ".txt")
        svc.index_file(item["id"] + ext, item["code"])
        if progress_cb:
            progress_cb((i + 1) / (len(dataset) * 2))

    # 检索
    details = []
    for i, item in enumerate(dataset):
        t_search = time.time()
        result_str = svc.search(item["query"], top_k=top_k)
        latency = time.time() - t_search
        paths = parse_search_results(result_str)

        rank = None
        for j, path in enumerate(paths, 1):
            if item["id"] in path:
                rank = j
                break

        details.append({
            "id": item["id"],
            "language": item["language"],
            "source": item["source"],
            "query": item["query"],
            "rank": rank,
            "latency_ms": round(latency * 1000, 1),
            "top_results": paths[:top_k],
        })

        if progress_cb:
            progress_cb((len(dataset) + i + 1) / (len(dataset) * 2))

    elapsed = time.time() - t0

    # 释放连接
    svc._client = None
    svc._collection = None

    # 整体指标
    ranks = [d["rank"] for d in details]
    overall = compute_metrics(ranks, len(dataset))

    # 分语言指标
    by_lang = defaultdict(list)
    for d in details:
        by_lang[d["language"]].append(d["rank"])
    lang_metrics = {}
    for lang, lang_ranks in sorted(by_lang.items()):
        lang_metrics[lang] = compute_metrics(lang_ranks, len(lang_ranks))
        lang_metrics[lang]["count"] = len(lang_ranks)

    return {
        "overall": overall,
        "by_language": lang_metrics,
        "details": details,
        "elapsed": round(elapsed, 2),
        "dataset_size": len(dataset),
    }

# ── 页面配置 ──
st.set_page_config(
    page_title="Benchmark Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("📊 检索质量基准测试")


# ── 侧边栏 ──
with st.sidebar:
    st.header("⚙️ 参数")
    top_k = st.slider("Top K", min_value=1, max_value=10, value=5)

    dataset = load_dataset()
    all_langs = sorted(set(item["language"] for item in dataset))
    selected_langs = st.multiselect(
        "语言过滤",
        options=all_langs,
        default=all_langs,
    )

    st.divider()
    run_btn = st.button("🚀 运行基准测试", type="primary", use_container_width=True)

    st.divider()
    st.caption(f"数据集: {len(dataset)} 条")
    baseline = load_baseline()
    if baseline:
        st.caption("基线: " + baseline["timestamp"])
    else:
        st.caption("基线: 无")

# ── 主区域 ──
if run_btn:
    dataset = load_dataset()

    # 语言过滤
    if selected_langs:
        dataset = [d for d in dataset if d["language"] in selected_langs]

    if not dataset:
        st.error("过滤后数据集为空，请调整语言选择")
        st.stop()

    st.info(f"数据集: {len(dataset)} 条 | top_k={top_k}")
    progress = st.progress(0, text="正在运行基准测试...")

    result = run_benchmark(dataset, top_k, progress_cb=lambda p: progress.progress(p, text=f"进度 {p:.0%}"))
    progress.empty()

    # 存入 session
    st.session_state["result"] = result


# ── 展示结果 ──
if "result" in st.session_state:
    result = st.session_state["result"]
    overall = result["overall"]
    baseline = load_baseline()

    # --- 整体指标卡片 ---
    st.subheader("整体指标")
    c1, c2, c3, c4, c5 = st.columns(5)

    def _delta(key):
        if baseline and "metrics" in baseline:
            old = baseline["metrics"].get(key, 0)
            diff = overall[key] - old
            if abs(diff) > 0.0001:
                return f"{diff:+.4f}"
        return None

    c1.metric("MRR", "{:.4f}".format(overall["mrr"]), _delta("mrr"))
    c2.metric("Recall@1", "{:.4f}".format(overall["recall_at_1"]), _delta("recall_at_1"))
    c3.metric("Recall@3", "{:.4f}".format(overall["recall_at_3"]), _delta("recall_at_3"))
    c4.metric("Recall@5", "{:.4f}".format(overall["recall_at_5"]), _delta("recall_at_5"))
    c5.metric("耗时", "{}s".format(result["elapsed"]), "{} 条".format(result["dataset_size"]))

    if baseline:
        ts = baseline.get("timestamp", "未知")
        st.caption(f"基线时间: {ts}")

    st.divider()

    # --- 分语言柱状图 ---
    st.subheader("分语言指标")

    lang_data = result["by_language"]
    if lang_data:
        import pandas as pd

        rows = []
        for lang, m in lang_data.items():
            rows.append({
                "语言": lang,
                "MRR": m["mrr"],
                "Recall@1": m["recall_at_1"],
                "Recall@3": m["recall_at_3"],
                "Recall@5": m["recall_at_5"],
                "样本数": m["count"],
            })
        df_lang = pd.DataFrame(rows).set_index("语言")

        col_chart, col_table = st.columns([2, 1])
        with col_chart:
            st.bar_chart(df_lang[["MRR", "Recall@3", "Recall@5"]])
        with col_table:
            st.dataframe(df_lang, use_container_width=True)

    st.divider()

    # --- 失败 case 详情 ---
    st.subheader("失败 / 低排名 Case")

    details = result["details"]
    failed = [d for d in details if d["rank"] is None or d["rank"] > 3]

    if not failed:
        st.success("所有 case 均在 Top 3 命中 🎉")
    else:
        import pandas as pd

        fail_rows = []
        for d in failed:
            rank_str = str(d["rank"]) if d["rank"] else "未命中"
            fail_rows.append({
                "ID": d["id"],
                "语言": d["language"],
                "排名": rank_str,
                "延迟(ms)": d["latency_ms"],
                "查询": d["query"][:60],
            })
        df_fail = pd.DataFrame(fail_rows)
        st.dataframe(df_fail, use_container_width=True, hide_index=True)

        # 展开详情
        with st.expander(f"查看全部 {len(failed)} 条失败详情"):
            for d in failed:
                rank_str = str(d["rank"]) if d["rank"] else "未命中"
                st.markdown("**{}** ({}) — 排名: {}".format(d["id"], d["language"], rank_str))
                st.text("Query: " + d["query"])
                if d["top_results"]:
                    st.text("Top results: " + ", ".join(d["top_results"]))
                st.markdown("---")

    st.divider()

    # --- 延迟分布 ---
    st.subheader("检索延迟分布")
    import pandas as pd
    latencies = [d["latency_ms"] for d in details]
    df_lat = pd.DataFrame({"延迟(ms)": latencies})

    col_hist, col_stats = st.columns([2, 1])
    with col_hist:
        st.bar_chart(df_lat["延迟(ms)"].value_counts().sort_index())
    with col_stats:
        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        min_lat = min(latencies)
        p95_idx = int(len(latencies) * 0.95)
        p95 = sorted(latencies)[min(p95_idx, len(latencies) - 1)]
        st.metric("平均延迟", f"{avg_lat:.1f} ms")
        st.metric("P95 延迟", f"{p95:.1f} ms")
        st.metric("最大延迟", f"{max_lat:.1f} ms")
        st.metric("最小延迟", f"{min_lat:.1f} ms")

    st.divider()

    # --- 保存基线 / 导出 ---
    st.subheader("操作")
    col_save, col_export = st.columns(2)

    with col_save:
        if st.button("💾 保存为新基线"):
            new_baseline = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "dataset_size": result["dataset_size"],
                "metrics": result["overall"],
            }
            with open(BASELINE_PATH, "w", encoding="utf-8") as f:
                json.dump(new_baseline, f, indent=2, ensure_ascii=False)
            st.success(f"基线已保存到 {BASELINE_PATH}")

    with col_export:
        report = json.dumps(result, indent=2, ensure_ascii=False, default=str)
        st.download_button(
            label="📥 导出完整报告 (JSON)",
            data=report,
            file_name=f'benchmark_{time.strftime("%Y%m%d_%H%M%S")}.json',
            mime="application/json",
        )


# ── 空状态 ──
if "result" not in st.session_state:
    st.info("👈 点击侧边栏 **运行基准测试** 开始")
