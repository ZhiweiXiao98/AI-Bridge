# filename: tools/visualize_architecture.py
import os
import ast
import networkx as nx
from pyvis.network import Network
import webbrowser
import sys
from collections import Counter

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORE_DIRS = {'.git', '__pycache__', 'venv', '.venv', 'tests', 'tools', 'scaffold', 'docs', 'htmlcov', 'backup', 'export', 'rhino'}
IGNORE_FILES = {'__init__.py'}

def get_imports(file_path):
    imports = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imports.append(n.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split('.')[0])
    except: pass
    return imports

def build_graph():
    G = nx.DiGraph()
    py_files = {} 
    filenames = []
    
    print(f"🔍 正在扫描星系: {PROJECT_ROOT}")
    
    # 第一遍扫描：收集所有文件名以检测重名
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            if file.endswith(".py") and file not in IGNORE_FILES:
                filenames.append(file)
    
    name_counts = Counter(filenames)
    
    # 第二遍扫描：构建节点
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            if file.endswith(".py") and file not in IGNORE_FILES:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, PROJECT_ROOT).replace("\\", "/")
                
                # 🎨 优化分组逻辑 (更宽松的匹配)
                group = "Other"
                if "app/core" in rel_path: group = "Core"      # 核心大脑 (红)
                elif "app/ui" in rel_path: group = "UI"        # 用户界面 (蓝)
                elif "driver" in rel_path: group = "Driver"    # 浏览器驱动 (绿)
                elif "server" in file or "start_" in file: group = "Entry" # 启动入口 (黄)
                
                # 🏷️ 智能标签逻辑
                # 如果文件名重复，显示为 "父目录/文件名"，否则只显示 "文件名"
                if name_counts[file] > 1:
                    parent_dir = os.path.basename(os.path.dirname(full_path))
                    label_name = f"{parent_dir}/{file}"
                else:
                    label_name = file

                # 计算文件大小 (KB)
                kb_size = os.path.getsize(full_path) / 1024
                title_info = f"Path: {rel_path}\nSize: {kb_size:.1f} KB\nGroup: {group}"
                
                # 根据文件大小微调节点尺寸 (越大越重要)
                base_size = 20
                if group == "Core": base_size = 25
                elif group == "Entry": base_size = 35
                final_size = base_size + min(10, kb_size / 5) # 封顶加10
                
                G.add_node(rel_path, label=label_name, title=title_info, group=group, value=final_size)
                py_files[rel_path] = full_path

    # 建立连线
    for node_id, full_path in py_files.items():
        imports = get_imports(full_path)
        for imp in imports:
            for target_id in py_files.keys():
                if target_id == node_id: continue
                # 模糊匹配增强
                target_mod = target_id.replace("/", ".").replace(".py", "")
                target_name = os.path.basename(target_id).replace(".py", "")
                
                # 如果 import 的名字出现在了路径中
                if imp == target_name or f".{imp}" in target_mod:
                    # 降低连线透明度
                    G.add_edge(node_id, target_id)

    return G

def generate_html():
    G = build_graph()
    if G.number_of_nodes() == 0: return

    net = Network(height="95vh", width="100%", bgcolor="#0f172a", font_color="#e2e8f0")
    net.from_nx(G)
    
    options = {
        "nodes": {
            "borderWidth": 0,
            "borderWidthSelected": 2,
            "opacity": 1,
            "font": {"size": 14, "face": "Consolas", "background": "rgba(0,0,0,0.5)", "color": "#fff"},
            "shadow": {"enabled": True, "color": "rgba(0,0,0,0.5)", "size": 10, "x": 5, "y": 5}
        },
        "edges": {
            "color": {"color": "rgba(255,255,255,0.15)", "highlight": "#facc15"}, # 连线更隐蔽
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.5}},
            "smooth": {"type": "continuous"}
        },
        "groups": {
            "Core":   {"color": {"background": "#ef4444", "border": "#b91c1c"}, "shape": "dot"}, 
            "UI":     {"color": {"background": "#3b82f6", "border": "#1d4ed8"}, "shape": "dot"}, 
            "Driver": {"color": {"background": "#10b981", "border": "#047857"}, "shape": "dot"}, 
            "Entry":  {"color": {"background": "#f59e0b", "border": "#b45309"}, "shape": "star"}, 
            "Other":  {"color": {"background": "#64748b", "border": "#475569"}, "shape": "dot"}  
        },
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -80, # 稍微减小斥力，让结构紧凑一点点
                "centralGravity": 0.01,
                "springLength": 100,
                "springConstant": 0.08,
                "damping": 0.4
            },
            "minVelocity": 0.75,
            "solver": "forceAtlas2Based"
        },
        "interaction": {
            "hover": True,
            "navigationButtons": True,
            "keyboard": True
        },
        "configure": {
            "enabled": True,
            "filter": "physics"
        }
    }
    
    net.set_options(str(options).replace("'", '"').replace("True", "true").replace("False", "false"))
    
    output_path = os.path.join(PROJECT_ROOT, "architecture_map.html")
    net.save_graph(output_path)
    print(f"🚀 V3 智能版星系图已生成: {output_path}")
    webbrowser.open("file:///" + output_path.replace("\\", "/"))

if __name__ == "__main__":
    generate_html()