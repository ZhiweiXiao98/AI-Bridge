# filename: scripts/git_cleanup.py
import subprocess
import os

def run_git(args):
    """执行 git 命令并打印结果"""
    cmd = ["git"] + args
    print(f"执行: {' '.join(cmd)}")
    try:
        # 使用 shell=True 兼容 Windows，并忽略错误（防止因文件本就不存在而中断）
        subprocess.run(cmd, shell=True, check=False)
    except Exception as e:
        print(f"❌ 错误: {e}")

def main():
    print("🧹 开始清理 Git 污染文件 (仅从版本控制移除，保留本地文件)...")
    print("="*60)

    # 1. 核心垃圾名单 (根据您的 .gitignore 定制)
    targets = [
        "Chrome_143_Clean_Data",  # 巨大的 Chrome 数据
        "chrome_user_data",
        "__pycache__",
        "venv", ".venv",
        
        # 敏感数据
        "user_data.db",
        "config.json",
        "server_config.json",
        "session_states.json",
        ".secret.key",
        
        # 临时文件
        "layout.ini",
        "layout copy.ini",
        "crash_log.txt",
        "FULL_PROJECT_CONTEXT.txt",
        "PROJECT_STRUCTURE_DUMP.json",
        
        # 废弃文件
        "app/ui/pages/chat_page.py",
        "launcher.py"
    ]

    # 2. 执行移除
    for target in targets:
        if os.path.exists(target):
            # --cached 表示只删索引，不删磁盘文件
            run_git(["rm", "-r", "--cached", target])
        else:
            print(f"ℹ️ 跳过: {target} (本地不存在)")

    print("\n" + "="*60)
    print("✅ 清理指令已执行。接下来提交变更...")
    
    # 3. 提交并推送
    # 注意：这需要您配置好 Git 身份
    if input("❓ 是否立即执行 Commit 和 Push? (y/n): ").lower() == 'y':
        run_git(["commit", "-m", "🧹 Cleanup: Remove accidentally committed junk files"])
        run_git(["push"])
        print("\n🎉 云端仓库已清理干净！")
    else:
        print("\n请手动执行: git commit -m 'Cleanup' && git push")

if __name__ == "__main__":
    main()
