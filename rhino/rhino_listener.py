# filename: rhino/rhino_listener.py
# -*- coding: utf-8 -*-
"""
[极速版 v2.0] 递归轮询监听器
已升级：支持扫描子文件夹（项目制支持）
"""
import scriptcontext as sc
import Rhino
import os
import sys
import time
import io

# === 配置 ===
CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
WATCH_DIR = os.path.join(PROJECT_ROOT, "export", "code", "rhino")

if "AI_BRIDGE_STATE" not in sc.sticky:
    sc.sticky["AI_BRIDGE_STATE"] = {
        "files": {},      # 存储格式: {全路径: mtime}
        "pending": {},    
        "last_check": 0
    }

def run_script_safe(filepath):
    try:
        # 获取相对路径用于显示 (例如: modern_facade/main.py)
        rel_path = filepath.replace(WATCH_DIR, "").lstrip(os.sep)
        
        if PROJECT_ROOT not in sys.path: sys.path.append(PROJECT_ROOT)
        
        if not os.path.exists(filepath): return
        if os.path.getsize(filepath) == 0: return

        for _ in range(3):
            try:
                with io.open(filepath, 'r', encoding='utf-8') as f:
                    user_code = f.read()
                break
            except:
                time.sleep(0.05)
        else:
            return 

        fix_header = """
try:
    import scriptcontext as sc
    import Rhino
    sc.doc = Rhino.RhinoDoc.ActiveDoc
except: pass
"""
        final_code = fix_header + "\n" + user_code
        script_scope = {"__file__": filepath, "__name__": "__main__"}
        
        Rhino.RhinoApp.WriteLine("▶ 执行: {}".format(rel_path))
        exec(final_code, script_scope)
        sc.doc.Views.Redraw()
        
    except Exception as e:
        msg = str(e)
        if "System.IO" not in msg:
            Rhino.RhinoApp.WriteLine("❌ 错误: {}".format(msg))

def check_updates(sender, e):
    try:
        state = sc.sticky["AI_BRIDGE_STATE"]
        now = time.time()

        # 1. 扫描频率：0.2秒一次
        if now - state["last_check"] > 0.2:
            state["last_check"] = now
            if not os.path.exists(WATCH_DIR): return

            # === 核心修改: 使用 os.walk 进行递归扫描 ===
            # 支持项目子文件夹结构
            for root, dirs, files in os.walk(WATCH_DIR):
                for filename in files:
                    if not filename.endswith(".py"): continue
                    
                    filepath = os.path.join(root, filename)
                    
                    try:
                        mtime = os.path.getmtime(filepath)
                        # 使用全路径作为 Key，防止不同项目有同名 main.py 冲突
                        if filepath not in state["files"] or mtime > state["files"][filepath]:
                            state["files"][filepath] = mtime
                            # 只有在非初始化阶段（diff < 2s）才执行，或者是 touch 触发
                            # 这里简化逻辑：只要变动就加入 pending，由 run_script_safe 决定是否执行
                            state["pending"][filepath] = now + 0.1 
                    except: pass

        # 2. 执行阶段
        for filepath in list(state["pending"].keys()):
            trigger_time = state["pending"][filepath]
            if now > trigger_time:
                del state["pending"][filepath] 
                if os.path.exists(filepath):
                    run_script_safe(filepath)

    except: pass

def start_polling():
    Rhino.RhinoApp.Idle -= check_updates
    Rhino.RhinoApp.Idle += check_updates
    
    if not os.path.exists(WATCH_DIR): os.makedirs(WATCH_DIR)
    
    # 初始化状态，避免启动时把所有历史脚本都跑一遍
    state = sc.sticky["AI_BRIDGE_STATE"]
    for root, dirs, files in os.walk(WATCH_DIR):
        for filename in files:
            if filename.endswith(".py"):
                filepath = os.path.join(root, filename)
                try:
                    state["files"][filepath] = os.path.getmtime(filepath)
                except: pass
            
    Rhino.RhinoApp.WriteLine("🚀 AI Bridge 递归监听器 (v2.0) 已启动")
    Rhino.RhinoApp.WriteLine("📂 监控根目录: .../export/code/rhino")

if __name__ == "__main__":
    start_polling()
