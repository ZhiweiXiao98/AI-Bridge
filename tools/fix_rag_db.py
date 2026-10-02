# filename: tools/fix_rag_db.py
import os
import shutil
import time
import psutil
import sys
import sqlite3

def kill_python_processes():
    print("🔪 [1/4] 正在清理残留的 Python 进程 (防止文件锁定)...")
    current_pid = os.getpid()
    killed_count = 0
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # 跳过自己
            if proc.info['pid'] == current_pid:
                continue
                
            # 检查是否是 Python 进程且涉及本项目
            if 'python' in proc.info['name'].lower():
                cmdline = str(proc.info['cmdline'])
                if 'start_server.py' in cmdline or 'knowledge_service' in cmdline:
                    print(f"   -> 终止进程: {proc.info['name']} (PID: {proc.info['pid']})")
                    proc.kill()
                    killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
    print(f"   => 已清理 {killed_count} 个冲突进程。")
    time.sleep(1) # 等待释放句柄

def nuke_database():
    db_dir = "_knowledge_base"
    print(f"🧨 [2/4] 正在物理粉碎旧数据库: {db_dir}...")
    
    if os.path.exists(db_dir):
        try:
            shutil.rmtree(db_dir)
            print("   => ✅ 删除成功。旧数据已清除。")
        except Exception as e:
            print(f"   => ❌ 删除失败: {e}")
            print("   ⚠️ 致命警告: 如果无法删除，请手动重启电脑或在该目录下运行 'rm -rf _knowledge_base'。")
            sys.exit(1)
    else:
        print("   => 目录不存在，无需删除。")

def rebuild_and_verify():
    print("🏗️ [3/4] 正在初始化全新知识库...")
    try:
        import chromadb
        print(f"   => ChromaDB 版本: {chromadb.__version__}")
        
        # 强制使用新版配置初始化
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path="_knowledge_base",
            settings=Settings(allow_reset=True, anonymized_telemetry=False)
        )
        
        # 创建集合（这会触发 sqlite3 文件的生成）
        collection = client.get_or_create_collection("ai_bridge_v1")
        collection.add(
            documents=["Hello World"],
            metadatas=[{"source": "test"}],
            ids=["id1"]
        )
        print("   => ✅ 写入测试数据成功。")
        return True
    except Exception as e:
        print(f"   => ❌ 重建失败: {e}")
        return False

def verify_schema():
    print("🔍 [4/4] 正在验证数据库 Schema 兼容性...")
    db_path = "_knowledge_base/chroma.sqlite3"
    
    if not os.path.exists(db_path):
        print("   => ❌ 数据库文件未生成！")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 检查是否存在 topic 列 (这是 0.4.x 的特征)
        try:
            cursor.execute("SELECT topic FROM collections LIMIT 1")
            print("   => ✅ Schema 验证通过: 发现 'topic' 列。数据库是新版的。")
        except sqlite3.OperationalError:
            print("   => ❌ Schema 验证失败: 缺少 'topic' 列。数据库依然是旧版的！")
        finally:
            conn.close()
    except Exception as e:
        print(f"   => ❌ 验证出错: {e}")

if __name__ == "__main__":
    print("="*50)
    print("🚑 AI Bridge 知识库急救程序")
    print("="*50)
    
    kill_python_processes()
    nuke_database()
    if rebuild_and_verify():
        verify_schema()
    
    print("="*50)