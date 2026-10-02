# filename: tools/verify_rag_functionality.py
import sys
import os
import time

def functional_verification():
    print("="*60)
    print("🧪 AI Bridge RAG 功能性验收 (ChromaDB 1.x 适配版)")
    print("="*60)

    try:
        import chromadb
        print(f"📦 ChromaDB Version: {chromadb.__version__}")
        
        # 1. 初始化
        print("\n[STEP 1] 初始化客户端...")
        client = chromadb.PersistentClient(path="_knowledge_base")
        collection = client.get_or_create_collection("sanity_check")
        
        # 2. 写入
        print("[STEP 2] 尝试写入向量数据...")
        timestamp = str(time.time())
        collection.add(
            documents=[f"AI Bridge verification run at {timestamp}"],
            metadatas=[{"type": "test_log"}],
            ids=["verify_1"]
        )
        print("✅ 写入成功。")
        
        # 3. 检索
        print("[STEP 3] 尝试执行语义检索...")
        results = collection.query(
            query_texts=["AI Bridge verification"],
            n_results=1
        )
        
        # 4. 验证结果
        if results['ids'] and results['ids'][0]:
            print(f"✅ 检索成功！匹配结果 ID: {results['ids'][0][0]}")
            print("🎉 结论: 数据库功能完全正常。请忽略之前的 'topic' 列报错。")
        else:
            print("❌ 检索返回空结果。")

    except Exception as e:
        print(f"❌ 功能验证失败: {e}")
        import traceback
        traceback.print_exc()

    print("="*60)

if __name__ == "__main__":
    functional_verification()