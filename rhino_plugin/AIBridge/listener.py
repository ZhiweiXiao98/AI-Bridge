# filename: rhino_plugin/AIBridge/listener.py
# -*- coding: utf-8 -*-
import Rhino
import scriptcontext as sc
import os
import sys
import time
import io

# 占位符，安装时会被替换为真实路径
WATCH_DIR_TEMPLATE = r"C:\AI_Bridge_Workspace\export\code\rhino"

if "AI_BRIDGE_FILE_TIMES" not in sc.sticky:
    sc.sticky["AI_BRIDGE_FILE_TIMES"] = {}

def run_script_safe(filepath):
    try:
        filename = os.path.basename(filepath)
        Rhino.RhinoApp.WriteLine("▶ 执行: {}".format(filename))
        
        # 尝试注入项目根目录 (根据导出路径反推)
        # 假设 filepath 是 .../export/code/rhino/xxx.py
        # 向上找 3 层就是 Project Root
        try:
            current_root = os.path.dirname(os.path.dirname(os.path.dirname(filepath)))
            if current_root not in sys.path: sys.path.append(current_root)
        except: pass
        
        with io.open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
            
        script_scope = {"__file__": filepath, "__name__": "__main__"}
        exec(code, script_scope)
        Rhino.RhinoApp.WriteLine("✅ 成功")
    except Exception as e:
        Rhino.RhinoApp.WriteLine("❌ 错误: {}".format(e))

def check_updates(sender, e):
    try:
        if "AI_BRIDGE_LAST_CHECK" in sc.sticky:
            if time.time() - sc.sticky["AI_BRIDGE_LAST_CHECK"] < 1.0:
                return
        sc.sticky["AI_BRIDGE_LAST_CHECK"] = time.time()

        # 使用 sticky 里的路径，因为模块重载时全局变量可能会丢，但 sticky 不会
        watch_dir = sc.sticky.get("AI_BRIDGE_WATCH_PATH", WATCH_DIR_TEMPLATE)
        
        if not os.path.exists(watch_dir): return

        file_times = sc.sticky["AI_BRIDGE_FILE_TIMES"]
        
        for filename in os.listdir(watch_dir):
            if not filename.endswith(".py"): continue
            
            filepath = os.path.join(watch_dir, filename)
            try:
                mtime = os.path.getmtime(filepath)
                if filename not in file_times or mtime > file_times[filename]:
                    file_times[filename] = mtime
                    # 避免初始化时运行，仅在后续运行
                    # 这里为了保险，可以加个判断：如果是第一次加载插件且文件已存在，不运行
                    # 但简单起见，我们允许它运行，或者依靠安装后的初次状态
                    Rhino.RhinoApp.WriteLine("🔄 检测到变动: {}".format(filename))
                    run_script_safe(filepath)
            except: pass
    except: pass

def start_polling():
    # 将路径存入 sticky，方便跨重载读取
    sc.sticky["AI_BRIDGE_WATCH_PATH"] = WATCH_DIR_TEMPLATE
    
    Rhino.RhinoApp.Idle -= check_updates
    Rhino.RhinoApp.Idle += check_updates
    
    # 初始化文件时间，防止启动时爆发运行
    if os.path.exists(WATCH_DIR_TEMPLATE):
        init_times = {}
        for filename in os.listdir(WATCH_DIR_TEMPLATE):
            if filename.endswith(".py"):
                try:
                    init_times[filename] = os.path.getmtime(os.path.join(WATCH_DIR_TEMPLATE, filename))
                except: pass
        sc.sticky["AI_BRIDGE_FILE_TIMES"] = init_times
    
    Rhino.RhinoApp.WriteLine("🚀 AI Bridge 轮询服务已启动")
    Rhino.RhinoApp.WriteLine("📂 监控: {}".format(WATCH_DIR_TEMPLATE))
