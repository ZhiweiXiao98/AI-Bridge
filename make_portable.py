# filename: make_portable.py
import os
import shutil
import sys

def create_dist():
    dist_dir = "AI_Bridge_Client_Portable"
    
    print(f"📦 正在制作绿色免安装包: {dist_dir} ...")
    
    # 1. 清理旧构建
    if os.path.exists(dist_dir): shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)
    
    # 2. 复制核心代码 (保持源码结构，以便热更新覆盖)
    # 我们只需要客户端运行必须的文件
    items_to_copy = [
        "app",              # 核心逻辑
        "assets",           # 图标资源
        "start_client.py",  # 启动入口 (Launcher)
        "boot_remote.py",   # 客户端入口
        "requirements.txt"  # 依赖清单
    ]
    
    for item in items_to_copy:
        src = os.path.join(os.getcwd(), item)
        dst = os.path.join(dist_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
        print(f"   - 复制: {item}")

    # 3. 创建启动脚本 (Windows)
    # 假设用户电脑有 Python，或者您可以放入一个 python-embed 文件夹
    bat_content = """@echo off
title AI Bridge Client
echo [INFO] Starting Remote Client...
python start_client.py
pause
"""
    with open(os.path.join(dist_dir, "启动客户端.bat"), "w", encoding="gbk") as f:
        f.write(bat_content)
        
    print(f"\n✅ 制作完成！")
    print(f"📂 请将文件夹 '{dist_dir}' 复制到目标电脑。")
    print(f"⚠️ 注意：目标电脑需要安装 Python (并运行 pip install -r requirements.txt)")
    print(f"   (或者您可以手动将 Python Embed 版解压放入该目录)")

if __name__ == "__main__":
    create_dist()