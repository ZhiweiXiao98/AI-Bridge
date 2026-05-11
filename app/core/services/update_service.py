# filename: app/core/services/update_service.py
import os
import shutil
import time
from app.core.self_update import SelfUpdateManager
from app.core.project_context import ProjectContext

MAGIC_CMD_RESTART_SERVER = "::MAGIC_CMD_RESTART_SERVER::"

class UpdateService:
    def __init__(self, config, file_service):
        self.config = config
        self.file_service = file_service
        self.mgr = SelfUpdateManager()

    def scan(self):
        changes = self.mgr.scan()
        for c in changes:
            c['rel_path'] = c['rel_path'].replace('\\', '/')
        return changes

    def get_file_category(self, file_path):
        p = file_path.replace('\\', '/')
        
        # 1. 纯静态资源/文档 -> 绝对无需重启
        if p.startswith("docs/") or p.endswith(".md"):
            return "SAFE_STATIC"

        # 2. 测试代码与工具脚本 -> 绝对无需重启
        if p.startswith("tests/") or p.startswith("tools/") or p.startswith("scripts/"):
            return "SAFE_SCRIPT"
            
        # 3. 根目录下的辅助工具 -> 无需重启
        if p in ["dump_code.py", "print_tree.py", "pytest.ini", ".gitignore"]:
            return "SAFE_SCRIPT"

        # [Fix] 核心修正：Worker 位置已变更，必须优先判定为 CRITICAL
        if p == "app/core/worker.py": 
            return "CRITICAL"

        # 4. 客户端独有代码 -> 仅客户端更新，服务端不重启
        if p.startswith("app/ui/") or p in ["boot_remote.py", "start_client.py"]: 
            return "CLIENT_ONLY"
        
        if p.startswith("RhinoBIM_Client/"):
            return "CLIENT_ONLY"

        # 5. 核心架构 -> 必须重启
        if p in ["server.py", "start_server.py", "requirements.txt", "config.json", "server_config.json"]:
            return "CRITICAL"
            
        if p.startswith("app/core/"):
            return "CRITICAL"
            
        return "UNKNOWN"

    def apply_hot_patch(self, cache_dir):
        try:
            project_root = ProjectContext.get().get_project_root()
            for root, dirs, files in os.walk(cache_dir):
                for file in files:
                    src = os.path.join(root, file)
                    rel = os.path.relpath(src, cache_dir)
                    dest = os.path.join(project_root, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
            shutil.rmtree(cache_dir)
            return True, "静态文件已热应用"
        except Exception as e:
            return False, f"热补丁失败: {e}"

    def process_updates(self, paths, logger_func, ota_callback):
        changes = self.mgr.scan()
        cache_root = "update_cache"
        if not os.path.exists(cache_root): os.makedirs(cache_root)
        
        staged_count = 0
        sync_data = {} 
        needs_restart = False
        
        normalized_target_paths = [p.replace('\\', '/') for p in paths]
        NO_RESTART_EXTS = {'.md', '.txt', '.json', '.yaml', '.yml', '.html', '.css', '.js', '.png', '.jpg', '.ini'}

        for change in changes:
            normalized_rel = change['rel_path'].replace('\\', '/')
            if normalized_rel not in normalized_target_paths: continue
            
            with open(change['staging_path'], 'r', encoding='utf-8') as f: content = f.read()
            
            # [Validation] 语法检查
            if normalized_rel.endswith(".py"):
                valid, err = self.file_service.validate_python_code(content)
                if not valid:
                    print(f"❌ [UpdateService] 残缺拦截: {normalized_rel} -> {err}")
                    logger_func(f"⚠️ 跳过残缺文件: {os.path.basename(normalized_rel)}")
                    continue

            # [Core Feature] 自动拉黑机制 (Lock-on-Apply)
            # 一旦我们决定应用此代码，就立即将其哈希加入黑名单
            # 防止其他会话中的相同代码（或旧版本回响）再次触发更新提示
            self.file_service.add_ignored_content(normalized_rel, content)
            print(f"🔒 [AutoLock] 已锁定应用后的代码指纹: {normalized_rel}")

            full_cache_path = os.path.join(cache_root, change['rel_path'])
            os.makedirs(os.path.dirname(full_cache_path), exist_ok=True)
            
            try:
                with open(full_cache_path, 'w', encoding='utf-8') as f: f.write(content)
                sync_data[normalized_rel] = content
                staged_count += 1
                
                filename = os.path.basename(normalized_rel)
                _, ext = os.path.splitext(filename)
                
                category = self.get_file_category(normalized_rel)
                
                if category in ["SAFE_STATIC", "SAFE_SCRIPT"]:
                    print(f"ℹ️ [HotUpdate] 豁免重启 ({category}): {normalized_rel}")
                elif category == "CLIENT_ONLY":
                    print(f"ℹ️ [HotUpdate] 仅客户端更新: {normalized_rel}")
                elif category == "CRITICAL" or category == "UNKNOWN":
                    print(f"⚡ [Update] 触发服务端重启: {normalized_rel} ({category})")
                    needs_restart = True
                elif ext.lower() in NO_RESTART_EXTS:
                    print(f"ℹ️ [HotUpdate] 静态资源: {normalized_rel}")
                else:
                    print(f"⚡ [Update] 默认重启策略: {normalized_rel}")
                    needs_restart = True
                    
            except Exception as e:
                print(f"Failed to stage {change['rel_path']}: {e}")

        if sync_data:
            logger_func(f"📡 [OTA] 广播 {len(sync_data)} 个文件...")
            ota_callback(sync_data)
            time.sleep(2.0)

        if needs_restart:
            logger_func(f"⚡ [Server] 核心代码变更，呼叫启动器重启...")
            print(MAGIC_CMD_RESTART_SERVER, flush=True)
            while True: time.sleep(1) 
        else:
            if staged_count > 0:
                logger_func(f"✅ [Server] 热更新完成 (无需重启)")
                self.apply_hot_patch(cache_root)
            else:
                logger_func("⚠️ [Server] 无需更新")
        
        return needs_restart

    def pack_client_code(self):
        project_root = ProjectContext.get().get_project_root()
        sync_data = {}
        INCLUDE_DIRS = ["app", "rhino", "RhinoBIM_Client", "tools"]
        INCLUDE_FILES = ["boot_remote.py", "start_client.py", "requirements.txt", "README.md", "AI_README.md"]
        IGNORE_DIRS = ["__pycache__", "update_cache", "export", "backup", "temp_uploads", "venv", ".venv", ".git", ".idea", ".vscode"]
        IGNORE_EXTS = [".pyc", ".pyo", ".pyd", ".db", ".log", ".tmp"]

        for filename in INCLUDE_FILES:
            path = os.path.join(project_root, filename)
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        sync_data[filename] = f.read()
                except: pass

        for dirname in INCLUDE_DIRS:
            dir_path = os.path.join(project_root, dirname)
            if not os.path.exists(dir_path): continue
            
            for root, dirs, files in os.walk(dir_path):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for file in files:
                    if any(file.endswith(ext) for ext in IGNORE_EXTS): continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, project_root).replace('\\', '/')
                    if any(f"/{ig}/" in f"/{rel_path}/" for ig in IGNORE_DIRS): continue
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            sync_data[rel_path] = f.read()
                    except: pass
        return sync_data