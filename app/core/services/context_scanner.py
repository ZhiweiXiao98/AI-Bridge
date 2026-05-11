# filename: app/core/services/context_scanner.py
import os
import ast
from app.core.services.update_service import UpdateService
from app.core.services.file_service import FileService
from app.core.config import ConfigManager

class ContextScanner:
    """
    🏗️ 上下文扫描服务 (Backend Logic)
    负责：文件遍历、AST 静态分析、依赖关系构建、Token 估算
    特点：纯逻辑实现，不含任何 UI 代码，适合在子线程运行
    """
    def __init__(self, project_root):
        self.project_root = project_root
        self.config = ConfigManager.load()
        # 实例化 UpdateService 用于判断文件安全等级 (CRITICAL/SAFE)
        self.update_svc = UpdateService(self.config, FileService(self.config))
        
        # 扫描配置
        self.ignore_dirs = {
            '.git', '__pycache__', 'venv', '.venv', 'htmlcov', 'export', 
            'update_cache', 'backup', 'dist', 'bin', 'obj', '.idea', '.vscode',
            'temp_uploads', 'chrome_user_data'
        }
        self.target_exts = ('.py', '.md', '.json', '.cs', '.xml', '.ini', '.qss', '.txt')

    def scan(self, progress_callback=None):
        """
        执行全量扫描
        :param progress_callback: 回调函数，用于汇报进度 (msg)
        :return: (file_list, file_info_cache, dep_graph, rev_dep_graph, stats)
        """
        file_list = []
        file_info_cache = {}
        dep_graph = {}
        rev_dep_graph = {}
        
        total_tokens = 0
        scanned_count = 0

        # --- 阶段 1: 文件系统遍历 ---
        if progress_callback: progress_callback("正在遍历目录结构...")
        
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]
            
            for file in files:
                if not file.endswith(self.target_exts): continue
                if file == "FULL_PROJECT_CONTEXT.txt" or file.startswith("."): continue
                
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.project_root).replace("\\", "/")
                
                # 记录文件基础信息
                file_list.append((rel_path, full_path))
                
                # 初始化信息结构
                info = {
                    "doc": "", 
                    "classes": [], 
                    "funcs": [], 
                    "size": 0, 
                    "token": 0,
                    "category": self.update_svc.get_file_category(rel_path) # 预计算安全等级
                }
                
                # --- 阶段 2: 内容读取与分析 ---
                try:
                    info["size"] = os.path.getsize(full_path)
                    
                    # 避免读取过大的非代码文件
                    if info["size"] < 1024 * 500: # 500KB 限制
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            
                        info["token"] = len(content) // 4
                        total_tokens += info["token"]
                        
                        # 针对 Python 文件的 AST 分析
                        if file.endswith(".py"):
                            self._analyze_python_ast(content, rel_path, info, dep_graph, rev_dep_graph)
                            
                except Exception:
                    pass
                
                file_info_cache[rel_path] = info
                scanned_count += 1
                
                # 每扫描 50 个文件汇报一次，避免 UI 刷新过频
                if progress_callback and scanned_count % 50 == 0:
                    progress_callback(f"已扫描 {scanned_count} 个文件...")

        # 整理统计数据
        stats = {
            "total_files": len(file_list),
            "total_tokens": total_tokens,
            "total_relations": sum(len(v) for v in dep_graph.values())
        }
        
        return file_list, file_info_cache, dep_graph, rev_dep_graph, stats

    def _analyze_python_ast(self, content, rel_path, info, dep_graph, rev_dep_graph):
        """解析 Python AST 提取结构和引用"""
        try:
            tree = ast.parse(content)
            
            # 1. 提取 Docstring
            raw_doc = ast.get_docstring(tree)
            if raw_doc: 
                info["doc"] = raw_doc.strip().split('\n')[0]
            
            # 2. 提取定义
            info["classes"] = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
            info["funcs"] = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
            
            # 3. 提取引用 (Imports)
            if rel_path not in dep_graph: dep_graph[rel_path] = set()
            
            for node in ast.walk(tree):
                target = None
                if isinstance(node, ast.Import):
                    for n in node.names: target = n.name
                elif isinstance(node, ast.ImportFrom):
                    if node.module: target = node.module
                
                if target:
                    # 记录原始导入路径（后续在 UI 层做具体文件匹配会更准，但这里先存原始值或简单处理）
                    # 为了简化，我们在 UI 层加载完毕后再做一次路径匹配，或者在这里做
                    # 这里我们暂存 target，稍后在 scan 结束后统一链接，或者简单处理：
                    pass 
                    # 注：由于这里拿不到所有文件的最终列表（还在遍历中），
                    # 复杂的依赖图构建建议放在 scan 遍历结束后统一处理，
                    # 或者像之前一样只做简单的字符串匹配。
                    # 为了保持逻辑独立，我们将 target 存入 info，由 UI 层构建图谱，或者在这里构建
                    # 鉴于 scan 是线性过程，我们在这里只提取 import 字符串，
                    # 真正的图谱链接逻辑（Dependency Linking）需要知道全局文件列表。
                    
                    # 策略调整：将 import 目标存入临时列表，scan 结束后统一 resolve
                    if "raw_imports" not in info: info["raw_imports"] = set()
                    info["raw_imports"].add(target)

        except Exception:
            pass

    def post_process_dependencies(self, file_list, file_info_cache):
        """
        后处理：根据全局文件列表，解析真实的依赖指向
        这是为了解决 "from app.core import worker" 到底指向哪个文件的问题
        """
        dep_graph = {}
        rev_dep_graph = {}
        
        # 建立快速查找表
        known_paths = set(file_info_cache.keys())
        
        for source_path, info in file_info_cache.items():
            raw_imports = info.get("raw_imports", set())
            if not raw_imports: continue
            
            if source_path not in dep_graph: dep_graph[source_path] = set()
            
            for target in raw_imports:
                target_path_guess = target.replace(".", "/")
                
                # 匹配规则
                candidates = [
                    f"{target_path_guess}.py",
                    f"{target_path_guess}/__init__.py"
                ]
                
                found_match = None
                
                # 1. 精确匹配
                for cand in candidates:
                    # 查找是否有文件以 cand 结尾
                    for kp in known_paths:
                        if kp.endswith(cand):
                            found_match = kp
                            break
                    if found_match: break
                
                # 2. 模糊匹配 (文件名匹配)
                if not found_match and len(target_path_guess) > 3:
                    target_name = os.path.basename(target_path_guess)
                    for kp in known_paths:
                        if os.path.basename(kp).startswith(target_name) and kp != source_path:
                            # 避免匹配到自己
                            found_match = kp
                            break
                
                if found_match and found_match != source_path:
                    dep_graph[source_path].add(found_match)
                    if found_match not in rev_dep_graph: rev_dep_graph[found_match] = set()
                    rev_dep_graph[found_match].add(source_path)
                    
        return dep_graph, rev_dep_graph