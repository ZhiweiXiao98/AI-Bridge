# filename: tools/test_rag_query.py
import sys
import os
import logging

# 确保导入路径
sys.path.append(os.getcwd())

# 禁用冗余日志，只看搜索结果
logging.getLogger("chromadb").setLevel(logging.ERROR)

try:
    from app.core.services.knowledge_service import knowledge_engine
except ImportError:
    print("❌ 导入失败，请检查路径。")
    sys.exit(1)

def main():
    print("\n" + "="*50)
    print("🔍 AI Bridge 语义检索压力测试")
    print("="*50)

    # 测试用例：问一个关于具体业务逻辑的问题
    query = "软件是如何处理文件保存和语法检查的？"
    print(f"🤔 提问: {query}")
    
    context = knowledge_engine.search_context(query, top_k=3)
    print(context)

    print("\n" + "="*50)
    print("✅ 测试完成。如果上方出现了 file_service.py 或类似的逻辑块，说明 RAG 运行完美。")

if __name__ == "__main__":
    main()