# filename: scripts/install_plugin.py
import os
import shutil

def install():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_dir = os.path.join(project_root, "rhino_plugin", "AIBridge")
    
    appdata = os.getenv('APPDATA')
    target_dir = os.path.join(appdata, "McNeel", "Rhinoceros", "8.0", "Plug-ins", "PythonPlugins", "AI Bridge Connector")
    
    print(f"源: {source_dir}")
    print(f"目标: {target_dir}")
    
    # 1. 清理旧版本
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
            print("清理旧版本完成。")
        except Exception as e:
            print(f"⚠️ 清理失败 (可能文件被占用): {e}")
            return

    # 2. 复制文件
    # [关键修复] 我们手动复制，以便重命名入口文件
    os.makedirs(target_dir, exist_ok=True)
    
    # 复制 listener.py
    shutil.copy2(os.path.join(source_dir, "listener.py"), os.path.join(target_dir, "listener.py"))
    
    # [核心修复] 将 __init__.py 重命名为 __plugin__.py
    # Rhino 只认 __plugin__.py
    src_init = os.path.join(source_dir, "__init__.py")
    dst_plugin = os.path.join(target_dir, "__plugin__.py")
    
    if os.path.exists(src_init):
        shutil.copy2(src_init, dst_plugin)
        print("✅ 已修正入口文件: __init__.py -> __plugin__.py")
    else:
        # 如果源文件已经是 __plugin__.py (防止未来修正源文件后出错)
        src_plugin = os.path.join(source_dir, "__plugin__.py")
        if os.path.exists(src_plugin):
            shutil.copy2(src_plugin, dst_plugin)
        else:
            print("❌ 错误: 找不到入口文件 (__init__.py 或 __plugin__.py)")
            return

    # 3. 注入真实监听路径
    watch_path = os.path.join(project_root, "export", "code", "rhino")
    safe_path = watch_path.replace("\\", "\\\\")
    
    listener_file = os.path.join(target_dir, "listener.py")
    with open(listener_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 替换模板路径 (模板: C:\AI_Bridge_Workspace\export\code\rhino)
    # 注意转义
    template_str = r"C:\AI_Bridge_Workspace\export\code\rhino"
    new_content = content.replace(template_str, safe_path)
    
    with open(listener_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print(f"✅ 路径注入完成: {safe_path}")
    print("\n🎉 修复安装完成！")
    print("1. 请彻底重启 Rhino。")
    print("2. 在命令行输入 'AIBridgeStart' 测试，或者去插件列表查看。")

if __name__ == "__main__":
    install()
