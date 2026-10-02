# filename: scripts/git_auto_sync.py
import os
import subprocess
import datetime

def run_cmd(cmd):
    print(f"执行: {cmd}")
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError:
        print(f"❌ 命令失败: {cmd}")

def main():
    print("🚀 开始备份到 GitHub...")
    
    # 1. 自动调用快照生成（可选，如果你希望一键搞定所有）
    # os.system("python dump_code.py") 
    
    # 2. Git 流程
    run_cmd("git add .")
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"Backup: {timestamp}"
    
    # 尝试提交（如果没有变化会提示 nothing to commit，不影响）
    try:
        subprocess.run(f'git commit -m "{msg}"', shell=True, check=True)
    except:
        print("✨ 本地无代码变更")

    # 3. 推送
    print("☁️ 正在上传...")
    run_cmd("git push")
    print("✅ 备份完成！")

if __name__ == "__main__":
    # 确保在项目根目录运行
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
