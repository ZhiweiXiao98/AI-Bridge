# filename: tools/check_env_status.py
import sys
import os
import platform

def check():
    print(f"✅ Python Version: {platform.python_version()}")
    print(f"✅ System: {platform.system()} {platform.release()}")
    print(f"✅ CWD: {os.getcwd()}")
    
    # 检查关键目录
    required_dirs = ["app/core", "app/ui", "docs", "tools"]
    for d in required_dirs:
        if os.path.exists(d):
            print(f"✅ Dir Found: {d}")
        else:
            print(f"❌ Dir Missing: {d}")

    # 检查 RAG 服务
    try:
        sys.path.append(os.getcwd())
        from app.core.services.knowledge_service import knowledge_engine
        print("✅ RAG KnowledgeService: Importable")
    except ImportError as e:
        print(f"❌ RAG KnowledgeService: Import Failed ({e})")
    except Exception as e:
        print(f"⚠️ RAG KnowledgeService: Warning ({e})")

if __name__ == "__main__":
    check()