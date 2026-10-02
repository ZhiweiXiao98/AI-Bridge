# filename: tools/test_single_file_knowledge_update.py
import sys
import time
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.services.knowledge_service import knowledge_engine


def main():
    rel_path = "docs/KNOWLEDGE_SINGLE_FILE_UPDATE_BENCH.md"
    abs_path = PROJECT_ROOT / rel_path

    sentinel = f"KNOWLEDGE_SINGLE_FILE_UPDATE_SENTINEL_{int(time.time())}"
    content = (
        "# Knowledge Single File Update Bench\n\n"
        "本文件用于测试单文件写入后知识库增量更新耗时。\n\n"
        f"sentinel: {sentinel}\n"
    )

    try:
        print(f"[1/5] 写入文件: {rel_path}")
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        print("[OK] 文件写入完成")

        print(f"[2/5] 开始更新知识库: {rel_path}")
        t0 = time.perf_counter()
        knowledge_engine.update_file_index(rel_path, content)
        elapsed = time.perf_counter() - t0
        print(f"[OK] update_file_index 完成，耗时: {elapsed:.3f}s")

        print("[3/5] 获取知识库状态")
        try:
            stats = knowledge_engine.get_stats()
            print(f"[INFO] stats = {stats}")
        except Exception as e:
            print(f"[WARN] get_stats failed: {e}")

        print(f"[4/5] 立即查询 sentinel: {sentinel}")
        try:
            result = knowledge_engine.search_context(sentinel, top_k=5)
            print("[INFO] search result:")
            print(result)
        except Exception as e:
            print(f"[WARN] search_context failed: {e}")

    finally:
        print(f"[5/5] 清理测试文件与测试索引: {rel_path}")
        try:
            if abs_path.exists():
                abs_path.unlink()
                print("[OK] 测试文件已删除")
        except Exception as e:
            print(f"[WARN] 删除测试文件失败: {e}")

        try:
            if hasattr(knowledge_engine, "delete_paths"):
                knowledge_engine.delete_paths([rel_path])
                print("[OK] 测试索引已删除")
            else:
                print("[WARN] knowledge_engine 不支持 delete_paths，测试索引可能残留")
        except Exception as e:
            print(f"[WARN] 删除测试索引失败: {e}")


if __name__ == "__main__":
    main()