# filename: app/core/self_update.py
import os
import shutil
import hashlib
import subprocess
import sys

class SelfUpdateManager:
    def __init__(self, project_root=None, staging_dir=None):
        from app.core.config import ConfigManager
        self.config = ConfigManager.load()
        
        if project_root:
            self.project_root = project_root
        else:
            from app.core.project_context import ProjectContext
            self.project_root = ProjectContext.get().get_project_root()
        
        # 2. 确定暂存区目录
        if staging_dir:
            self.staging_dir = staging_dir
        else:
            # 默认逻辑：拼接配置中的相对路径
            config_path = self.config.get("export_code_path", "export/code")
            if os.path.isabs(config_path):
                self.staging_dir = config_path
            else:
                self.staging_dir = os.path.join(self.project_root, config_path)

    def _get_file_hash(self, path):
        if not os.path.exists(path): return None
        try:
            # [Fix] 核心修复：使用文本模式读取，而非二进制模式
            # errors='ignore' 防止编码问题导致读取失败
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 1. 统一换行符：强制将 Windows CRLF 转为 Unix LF
            # 这样就能忽略操作系统带来的格式差异
            content = content.replace('\r\n', '\n')
            
            # 2. 去除首尾空白 (防止仅因文件末尾多了一个空行而误判)
            content = content.strip()
            
            # 3. 计算标准化后的哈希
            return hashlib.md5(content.encode('utf-8')).hexdigest()
        except: return None

    def scan(self):
        """扫描暂存区与项目根目录的差异"""
        changes = []
        
        if not os.path.exists(self.staging_dir):
            return changes

        # 允许扫描的文件扩展名白名单 (包含 C#)
        ALLOWED_EXTS = {
            '.py', '.pyw', '.md', '.qss', '.json', '.txt', '.yaml', '.yml',
            '.cs', '.csproj', '.xml', '.sln'
        }
        
        # 明确允许的特殊文件名 (无后缀文件)
        ALLOWED_FILES = {
            '.gitignore', 
            'Dockerfile', 
            'LICENSE'
        }
        
        # 系统级忽略目录 (增加编译垃圾文件夹)
        SYSTEM_IGNORE_DIRS = {
            'rhino', 'ue5', 'blender', 'temp', 
            'obj', 'bin', '.vs', '.idea', '__pycache__', 'venv', '.venv'
        }
        
        # 核心文件白名单
        SYSTEM_FILES_WHITELIST = {
            os.path.join('rhino', 'rhino_listener.py').replace('\\', '/'),
        }

        for root, dirs, files in os.walk(self.staging_dir):
            # 过滤掉忽略目录
            dirs[:] = [d for d in dirs if d not in SYSTEM_IGNORE_DIRS]
            
            for file in files:
                _, ext = os.path.splitext(file)
                
                # 扩展名检查
                is_allowed = (ext.lower() in ALLOWED_EXTS) or (file in ALLOWED_FILES)
                if not is_allowed:
                    continue

                staging_path = os.path.join(root, file)
                rel_path = os.path.relpath(staging_path, self.staging_dir)
                
                # 路径标准化检查
                normalized_rel = rel_path.replace('\\', '/')
                
                # 二次检查：路径中是否包含被忽略的文件夹
                if any(f"/{ig}/" in f"/{normalized_rel}/" for ig in SYSTEM_IGNORE_DIRS):
                    continue

                # 检查白名单：如果是白名单文件，允许穿透忽略规则 (但上面已经过滤了目录遍历，这里主要做逻辑校验)
                is_whitelisted = False
                for wl in SYSTEM_FILES_WHITELIST:
                    if wl in normalized_rel:
                        is_whitelisted = True
                        break
                
                if "RhinoBIM_Client/" in normalized_rel:
                    is_whitelisted = True

                # 如果不是白名单文件，且位于忽略根目录下 (理论上 walk 已经过滤，这是双重保险)
                top_dir = normalized_rel.split('/')[0]
                if not is_whitelisted and top_dir in SYSTEM_IGNORE_DIRS:
                    continue

                target_path = os.path.join(self.project_root, rel_path)

                staging_hash = self._get_file_hash(staging_path)
                target_hash = self._get_file_hash(target_path)

                if target_hash is None:
                    status = "new"
                elif staging_hash != target_hash:
                    status = "overwrite"
                else:
                    status = "same"

                changes.append({
                    "rel_path": rel_path,
                    "status": status,
                    "staging_path": staging_path,
                    "target_path": target_path
                })
        return changes

    def apply(self, rel_paths=None):
        """应用更新：将文件从暂存区复制到项目目录，并根据需要触发编译"""
        changes = self.scan()
        count = 0
        csharp_updated = False # 标记是否更新了 C# 代码

        for change in changes:
            if rel_paths and change['rel_path'] not in rel_paths:
                continue
            
            if change['status'] == "same":
                continue

            # 标记 C# 变更
            if "RhinoBIM_Client" in change['rel_path'] and change['rel_path'].endswith(".cs"):
                csharp_updated = True

            # 确保目标文件夹存在
            os.makedirs(os.path.dirname(change['target_path']), exist_ok=True)
            
            try:
                shutil.copy2(change['staging_path'], change['target_path'])
                count += 1
            except Exception as e:
                print(f"[SelfUpdate] Error copying {change['rel_path']}: {e}")
        
        # === 自动化编译逻辑 ===
        if csharp_updated:
            self._trigger_csharp_build()

        return count

    def _trigger_csharp_build(self):
        """执行 dotnet build"""
        print("🔨 [AutoBuild] 检测到 C# 更新，正在触发编译...")
        client_dir = os.path.join(self.project_root, "RhinoBIM_Client")
        
        if not os.path.exists(client_dir):
            print("❌ [AutoBuild] 找不到 RhinoBIM_Client 目录，跳过编译。")
            return

        try:
            # 调用 dotnet build
            result = subprocess.run(
                ["dotnet", "build"], 
                cwd=client_dir, 
                shell=True,
                check=False 
            )
            
            if result.returncode == 0:
                print("✅ [AutoBuild] 编译成功！请重启 Rhino 加载新插件。")
            else:
                print(f"❌ [AutoBuild] 编译失败 (Code: {result.returncode})。请手动检查错误。")
                
        except Exception as e:
            print(f"💥 [AutoBuild] 执行出错: {e}")