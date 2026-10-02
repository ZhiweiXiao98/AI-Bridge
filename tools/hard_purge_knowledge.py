# filename: tools/hard_purge_knowledge.py
import os
import shutil
import psutil
import time

def kill_process_holding_file(filename):
    print(f"🔍 正在寻找锁定 {filename} 的进程...")
    count = 0
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            # 遍历进程打开的文件句柄
            for item in proc.open_files():
                if filename in item.path:
                    print(f"🛑 发现进程 {proc.info['name']} (PID: {proc.info['pid']}) 占用数据库，正在强制结束...")
                    proc.kill()
                    count += 1
                    break
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return count

def hard_purge():
    db_path = "_knowledge_base"
    db_file = "chroma.sqlite3"
    
    print("="*50)
    print("🧨 AI Bridge 知识库物理爆破程序")
    print("="*50)

    # 1. 尝试杀掉占用进程
    killed = kill_process_holding_file(db_file)
    if killed:
        print(f"✅ 已清理 {killed} 个冲突进程。")
    
    time.sleep(1.5)
    
    # 2. 物理删除目录
    if os.path.exists(db_path):
        print(f"🧨 正在物理删除损坏的数据库目录: {db_path}...")
        try:
            # 递归删除整个目录
            shutil.rmtree(db_path)
            print("✅ 物理爆破成功！环境已彻底清空。")
        except Exception as e:
            print(f"❌ 爆破失败: {e}")
            print("💡 建议：请手动关闭所有 Python 运行窗口和 start_server.py 进程后再试。")
    else:
        print("💡 未发现旧数据库目录，环境已经是纯净的。")

    print("="*50)
    print("🚀 现在你可以重新启动系统或运行测试脚本了。")

if __name__ == "__main__":
    hard_purge()