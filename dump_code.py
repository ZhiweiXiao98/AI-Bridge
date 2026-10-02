# filename: dump_code.py
import os
import datetime

# ================= 配置区 =================
TARGETS = [
    # 1. 根目录核心文件 (Entry Points)
    "start_server.py",
    "start_client.py",
    "server.py",
    "boot_remote.py",
    "requirements.txt",
    ".gitignore",
    "pytest.ini",
    "dump_code.py",  # 导出脚本自己
    
    # 2. 文档与日志
    "AI_README.md",
    "AI_JOURNAL.md",
    "docs",
    
    # 3. 核心源码目录 (Recursive Scan)
    "app",              # 包含 core, ui, services, driver, engine
    "tests",            # 包含所有测试用例
    "tools",            # 包含 user_manager 等工具
    "scripts",          # [New] 包含 git_cleanup.py 等运维脚本
    
    # 4. 客户端与插件源码
    "RhinoBIM_Client",  # C# 插件源码
    "rhino",            # Python 监听器脚本
]

# 忽略规则 (文件夹)
IGNORE_DIRS = {
    "__pycache__", "venv", ".venv", ".git", ".idea", ".vscode", 
    "build", "dist", "egg-info", "update_cache", "export", 
    "temp_uploads", "backup", "bin", "obj",
    "Chrome_143_Clean_Data", "chrome_user_data",
    "AI_Bridge_Client_Dist",
}

# 忽略规则 (后缀)
IGNORE_EXTS = {
    ".pyc", ".pyo", ".pyd", ".db", ".sqlite", ".log", 
    ".png", ".jpg", ".jpeg", ".gif", ".exe", ".dll", ".pdb",
    ".tmp", ".suo", ".user", ".spec", ".rhp"
}

# [New] 忽略规则 (特定文件名 - 敏感数据防泄露)
IGNORE_FILES = {
    ".secret.key",
    "config.json",
    "server_config.json",
    "session_states.json",
    "layout.ini",
    "layout copy.ini",
    "user_data.db",
    "crash_log.txt",
    "FULL_PROJECT_CONTEXT.txt", # 防止递归导出自己
    "PROJECT_STRUCTURE_DUMP.json"
}
# =========================================

OUTPUT_FILE = "FULL_PROJECT_CONTEXT.txt"

def is_ignored(path):
    """检查路径是否在黑名单中"""
    filename = os.path.basename(path)
    
    # 1. 检查特定文件名 (精确匹配)
    if filename in IGNORE_FILES: return True
    
    # 2. 检查后缀
    _, ext = os.path.splitext(filename)
    if ext.lower() in IGNORE_EXTS: return True
    
    # 3. 检查路径中的文件夹
    parts = path.split(os.sep)
    for p in parts:
        if p in IGNORE_DIRS: return True
    
    return False

def collect_files():
    """递归收集所有目标文件"""
    final_files = []
    project_root = os.getcwd()
    
    for target in TARGETS:
        # 处理相对路径
        target_path = os.path.join(project_root, target)
        
        if not os.path.exists(target_path):
            if target != "docs":
                print(f"⚠️ [Skip] 路径不存在: {target}")
            continue
            
        if os.path.isfile(target_path):
            if not is_ignored(target_path):
                final_files.append(target_path)
        
        elif os.path.isdir(target_path):
            print(f"📂 扫描目录: {target} ...")
            for root, dirs, files in os.walk(target_path):
                # 过滤黑名单目录 (修改 dirs 列表以剪除遍历分支)
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                
                for file in files:
                    full_path = os.path.join(root, file)
                    if not is_ignored(full_path):
                        final_files.append(full_path)
    
    # 去重并排序
    return sorted(list(set(final_files)))

def dump():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    files = collect_files()
    success_count = 0
    
    print(f"\n📝 准备导出 {len(files)} 个文件...")
    
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
            out.write(f"Snapshot: {timestamp}\n")
            out.write(f"Total Files: {len(files)}\n")
            out.write("="*60 + "\n\n")
            
            for path in files:
                try:
                    # 计算相对路径用于显示
                    rel_path = os.path.relpath(path, os.getcwd()).replace("\\", "/")
                    
                    out.write(f"File: {rel_path}\n")
                    out.write("-" * 40 + "\n")
                    
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        out.write(content + "\n\n")
                    
                    success_count += 1
                except Exception as e:
                    out.write(f"[Error reading file: {e}]\n\n")
                    print(f"❌ 读取失败: {rel_path} ({e})")
                    
    except Exception as main_e:
        print(f"🔥 导出过程发生致命错误: {main_e}")
        return

    print(f"✅ 快照生成完毕！成功: {success_count}/{len(files)}")
    print(f"📄 输出文件: {os.path.abspath(OUTPUT_FILE)}")

if __name__ == "__main__":
    dump()
