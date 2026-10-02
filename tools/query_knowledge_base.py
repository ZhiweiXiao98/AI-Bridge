# filename: tools/query_knowledge_base.py
import sys
import os
import time

# 强制路径对齐
sys.path.append(os.getcwd())

def query_kb():
    question = "AI Bridge 的核心架构设计是什么？"
    if len(sys.argv) > 1:
        question = sys.argv[1]
        
    print(f"❓ [Query] {question}")
    print("-" * 50)
    
    try:
        from app.core.services.knowledge_service import knowledge_engine
        
        start = time.time()
        # 调用 search_context
        res = knowledge_engine.search_context(question, top_k=2)
        
        print(res)
        print("-" * 50)
        print(f"⏱️ 耗时: {time.time() - start:.3f}s")
        
    except Exception as e:
        print(f"❌ 查询失败: {e}")

if __name__ == "__main__":
    query_kb()
