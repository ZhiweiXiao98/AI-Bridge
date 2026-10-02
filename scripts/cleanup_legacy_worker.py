# filename: scripts/cleanup_legacy_worker.py
import os
import time

def cleanup():
    # 目标：旧 Worker
    legacy_path = os.path.join("app", "ui", "worker.py")
    
    # 检查新 Worker 是否存在 (安全锁)
    new_path = os.path.join("app", "core", "worker.py")
    
    if not os.path.exists(new_path):
        print(f"❌ 错误：新 Worker ({new_path}) 不存在！操作中止。")
        return

    if os.path.exists(legacy_path):
        try:
            print(f"🗑️ 正在删除旧文件: {legacy_path}")
            os.remove(legacy_path)
            
            # 同时清理可能的编译缓存
            pyc_path = os.path.join("app", "ui", "__pycache__", "worker.cpython-312.pyc") # 根据             Python 版本可能不同
            if os.path.exists(pyc_path):
                os.remove(pyc_path)
            
            print("✅ 清理完成。大脑移植成功。")
        except Exception as e:
            print(f"❌ 删除失败: {e}")
    else:
        print(f"ℹ️ 文件已不存在: {legacy_path}")

if __name__ == "__main__":
    # 稍微延迟一下，确保之前的写入操作完成
    time.sleep(1.0)
    cleanup()