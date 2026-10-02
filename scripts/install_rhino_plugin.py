# filename: scripts/install_rhino_plugin.py
import os
import sys

def generate_install_guide():
    # 获取 rhino_listener.py 的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    listener_path = os.path.join(project_root, "rhino", "rhino_listener.py")
    
    print("\n" + "="*60)
    print("🦏 Rhino 插件安装向导")
    print("="*60)
    
    if not os.path.exists(listener_path):
        print(f"❌ 错误: 找不到文件 {listener_path}")
        return

    # 生成 Rhino 宏命令
    # ! _-RunPythonScript "C:\Path\To\rhino_listener.py"
    cmd = f'! _-RunPythonScript "{listener_path}"'
    
    print("\n请执行以下步骤将 AI Bridge 接入 Rhino：\n")
    print("1. 打开 Rhino")
    print("2. 在 Rhino 命令行输入 'Options' 打开选项")
    print("3. 找到 'General' -> 'Command Lists' (或者 '启动命令')")
    print("4. 添加以下命令：\n")
    print(f"    {cmd}\n")
    print("5. 重启 Rhino")
    print("\n✅ 完成后，Rhino 启动时会自动加载监听器！")
    print("="*60)

if __name__ == "__main__":
    generate_install_guide()
