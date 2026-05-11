# filename: tests/build_golden_set.py
"""
黄金测试集构建工具
用法: python tests/build_golden_set.py
"""
import os, sys, time, json, tempfile, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.knowledge.service import KnowledgeServiceV2

NL = chr(10)

# ========== 候选 Query ==========
# 覆盖: worker/agent/docker/file/tool_router/driver/knowledge/skills/self_update
CANDIDATE_QUERIES = [
    # Worker 相关
    "worker 线程处理 AI 回复消息",
    "代码块执行和结果收集",
    "worker 后台任务队列处理",

    # Agent 相关
    "agent 工具调用和函数路由",
    "AI 对话上下文构建",

    # Docker 相关
    "Docker 沙盒执行 Python 代码",
    "容器超时控制和资源限制",

    # 文件服务
    "文件保存到暂存区",
    "代码审查对比新旧文件",

    # 工具路由
    "工具路由兜底降级机制",
    "技能匹配和分发",

    # Driver 相关
    "浏览器页面元素交互点击",
    "HTML 解析提取页面结构",

    # Knowledge 相关
    "AST 智能分块 Python 代码",
    "向量检索和语义搜索",
    "检索结果重排序打分",

    # Skills 相关
    "技能注册和加载机制",
    "技能执行沙盒隔离",

    # 其他
    "自动更新版本检查",
    "上下文打包压缩发送",
]


def scan_py(root):
    results = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith((".", "__")) and d not in ("venv", ".venv", "export")]
        for f in files:
            if f.endswith(".py"):
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                results.append((rel, full))
    return results


def main():
    print("=" * 70)
    print("  黄金测试集构建工具")
    print("=" * 70)
    print()

    # 1. 索引
    db_path = tempfile.mkdtemp(prefix="golden_")
    svc = KnowledgeServiceV2(db_path=db_path)

    files = scan_py(os.path.join(ROOT, "app"))
    print(f"索引 {len(files)} 个文件...")
    t0 = time.time()
    for rel, full in files:
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                svc.index_file(rel, fh.read())
        except Exception as e:
            print(f"  跳过 {rel}: {e}")
    elapsed = time.time() - t0
    stats = svc.get_stats()
    tc = stats.get("total_chunks", 0)
    em = stats.get("embedding_mode", "?")
    print(f"索引完成: {tc} chunks, {elapsed:.1f}s, embedding={em}")
    print()

    # 2. 跑候选 query
    results = []
    for i, query in enumerate(CANDIDATE_QUERIES, 1):
        svc.cache._cache.clear()  # 清缓存
        t0 = time.time()
        raw = svc.search(query, top_k=3)
        latency = (time.time() - t0) * 1000

        print(f"--- Q{i:02d}: {query} ({latency:.0f}ms) ---")
        # 解析结果中的文件名
        lines = raw.strip().split(NL)
        for line in lines:
            line = line.strip()
            if line and not line.startswith("---") and not line.startswith("RAG"):
                print(f"  {line}")
        print()

        results.append({
            "query": query,
            "raw_result": raw,
            "latency_ms": round(latency, 1),
        })

    # 3. 保存原始结果
    out_path = os.path.join(ROOT, "tests", "golden_candidates.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"原始结果已保存: {out_path}")

    # 清理
    shutil.rmtree(db_path, ignore_errors=True)

    print()
    print("=" * 70)
    print("  请检查以上结果，标注每个 query 的正确答案")
    print("  然后把标注结果发给我，我来生成黄金测试集")
    print("=" * 70)


if __name__ == "__main__":
    main()