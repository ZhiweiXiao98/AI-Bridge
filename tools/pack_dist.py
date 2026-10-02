# filename: tools/pack_dist.py
import os
import shutil
import sys

def ignore_patterns(path, names):
    # 过滤掉不需要的垃圾文件
    return [n for n in names if n in [
        '__pycache__', 'venv', '.venv', '.git', '.idea', '.vscode', 
        'update_cache', 'export', 'backup', 'temp_uploads', # [Fix] 增加 temp_uploads 排除
        'crash_log.txt', 'user_data.db', 'session_states.json', 'layout.ini'
    ] or n.endswith('.pyc') or n.endswith('.spec')]

def create_client_dist():
    dist_name = "AI_Bridge_Client_Dist"
    
    # 1. 清理旧包
    if os.path.exists(dist_name):
        print(f"🧹 清理旧目录: {dist_name}...")
        shutil.rmtree(dist_name)
    os.makedirs(dist_name)
    
    print(f"📦 开始构建绿色客户端包 -> {dist_name}/")

    # 2. 复制核心文件
    items = [
        ("app", "app"),
        ("assets", "assets"),
        # [New] 加入 Rhino C# 插件源码，确保客户端开发环境完整
        ("RhinoBIM_Client", "RhinoBIM_Client"), 
        ("start_client.py", "start_client.py"),
        ("boot_remote.py", "boot_remote.py"),
        ("requirements.txt", "requirements.txt"),
        ("AI_README.md", "README.md"),
    ]

    for src, dst in items:
        src_path = os.path.join(os.getcwd(), src)
        dst_path = os.path.join(dist_name, dst)
        
        if not os.path.exists(src_path):
            if "assets" in src or "Rhino" in src: # 允许部分非关键资源缺失
                print(f"⚠️ 提示: 可选资源未找到: {src}")
            else:
                print(f"❌ 警告: 核心文件缺失: {src}")
            continue
            
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, ignore=ignore_patterns)
        else:
            shutil.copy2(src_path, dst_path)
        print(f"   - Copied: {src}")

    # 3. 生成一键启动脚本 (Windows Bat)
    bat_content = r"""@echo off
setlocal
title AI Bridge Client (Portable)

REM 检测是否存在嵌入式 Python
if exist "python_env\python.exe" (
    set "PY_EXE=python_env\python.exe"
    echo [INFO] Using Embedded Python...
) else (
    set "PY_EXE=python"
    echo [INFO] Using System Python...
)

echo [INFO] Starting Launcher...
"%PY_EXE%" start_client.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Startup failed. Please check if Python is installed or 'python_env' exists.
    pause
)
"""
    with open(os.path.join(dist_name, "🚀启动客户端.bat"), "w", encoding="gbk") as f:
        f.write(bat_content)

    print("\n✅ 打包完成！")
    print("="*50)
    print(f"📂 发布包位置: {os.path.abspath(dist_name)}")
    print("="*50)
    print("📋 部署指南 (如何在另一台电脑运行):")
    print("1. 将整个文件夹复制到目标电脑。")
    print("2. 环境准备 (二选一):")
    print("   A. [推荐] 在目标电脑安装 Python 3.12，并运行 'pip install -r requirements.txt'")
    print("   B. [便携] 下载 Python Embed 包，解压到本文件夹下的 'python_env' 目录，并把依赖库复制进去。")
    print("3. 双击 '🚀启动客户端.bat' 即可。")
    print("="*50)

if __name__ == "__main__":
    create_client_dist()