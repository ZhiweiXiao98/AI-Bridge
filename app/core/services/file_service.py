# filename: app/core/services/file_service.py
import os
import base64
import hashlib
import requests
import ast
import json
import pathlib
from app.core.config import ConfigManager
from app.core.project_context import ProjectContext
from app.core.logging import get_logger
# [RAG 注入]
from app.core.services.knowledge_service import knowledge_engine

logger = get_logger("app.core.services.file_service", side="worker")

IGNORED_BLOCKS_FILE = "ignored_blocks.json"

class FileService:
    def __init__(self, config_ref=None):
        self.config = config_ref if config_ref is not None else ConfigManager.load()
        self.project_root = ProjectContext.get().get_project_root()
        self.saved_hashes = {}
        self.ignored_content_hashes = set() 
        
        # [New] 用于记录已经报过错的残缺代码指纹，防止刷屏
        self._failed_hashes = set()
        
        self._ensure_dirs()
        self._load_ignored_blocks() 

    def on_project_switched(self, new_root: str, new_db_path: str):
        old_root = self.project_root
        self.project_root = new_root
        self.saved_hashes.clear()
        self._failed_hashes.clear()
        self._ensure_dirs()
        self._load_ignored_blocks()
        logger.info("[FileService] 项目路径已切换: %s → %s", old_root, new_root)

    def is_safe_path(self, path: str) -> bool:
        """
        🛡️ 核心防御：路径沙箱检查
        确保所有文件操作都在项目根目录下，禁止 ../ 穿越
        """
        try:
            # 1. 解析绝对路径
            abs_path = os.path.abspath(os.path.join(self.project_root, path))
            
            # 2. 检查公共前缀 (防止穿越)
            return os.path.commonpath([self.project_root, abs_path]) == self.project_root
        except Exception:
            return False

    def _ensure_dirs(self):
        code_dir = self.config.get("export_code_path", "export/code")
        img_dir = self.config.get("export_image_path", "export/images")
        os.makedirs(code_dir, exist_ok=True)
        os.makedirs(img_dir, exist_ok=True)
        return code_dir, img_dir

    def _load_ignored_blocks(self):
        if os.path.exists(IGNORED_BLOCKS_FILE):
            try:
                with open(IGNORED_BLOCKS_FILE, 'r', encoding='utf-8') as f:
                    self.ignored_content_hashes = set(json.load(f))
            except: pass

    def _save_ignored_blocks(self):
        try:
            with open(IGNORED_BLOCKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(self.ignored_content_hashes), f)
        except Exception as e:
            print(f"❌ Failed to save ignore list: {e}")

    def add_ignored_content(self, filename, content):
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        if content_hash in self.ignored_content_hashes:
            return True, "已存在于黑名单"
            
        self.ignored_content_hashes.add(content_hash)
        self._save_ignored_blocks()

        code_dir, _ = self._ensure_dirs()
        full_path = os.path.join(code_dir, filename)
        
        msg = "该代码版本已加入指纹黑名单"
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    existing_content = f.read()
                
                if hashlib.md5(existing_content.encode('utf-8')).hexdigest() == content_hash:
                    os.remove(full_path)
                    msg = "已删除暂存文件并永久屏蔽该版本"
            except: pass
            
        return True, msg

    def remove_ignored_content(self, content):
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        if content_hash in self.ignored_content_hashes:
            self.ignored_content_hashes.remove(content_hash)
            self._save_ignored_blocks()
            return True, "✅ 已从黑名单中移除，下次扫描将重新出现"
        return False, "⚠️ 该内容不在黑名单中"

    def is_content_ignored(self, content):
        h = hashlib.md5(content.encode('utf-8')).hexdigest()
        return h in self.ignored_content_hashes

    def process_images(self, messages):
        _, img_dir = self._ensure_dirs()
        for msg in messages:
            for seg in msg.get('segments', []):
                if seg['type'] == 'code':
                    content = seg.get('content', '')
                    if self.is_content_ignored(content):
                        seg['is_ignored'] = True
                
                elif seg['type'] == 'image':
                    content = seg.get('content', '')
                    if content.startswith('data:image'):
                        try:
                            header, encoded = content.split(",", 1)
                            ext = "png" if "png" in header else "jpg"
                            img_hash = hashlib.md5(encoded.encode('ascii')).hexdigest()
                            filename = f"{img_hash}.{ext}"
                            file_path = os.path.join(img_dir, filename)
                            if not os.path.exists(file_path):
                                with open(file_path, "wb") as f: f.write(base64.b64decode(encoded))
                            seg['content'] = f"served://{filename}"; seg['is_local'] = True
                        except Exception as e: print(f"❌ Base64 图片处理失败: {e}")
                    elif content.startswith('http'):
                        try:
                            img_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
                            ext = "png"
                            filename = f"{img_hash}.{ext}"
                            file_path = os.path.join(img_dir, filename)
                            if not os.path.exists(file_path):
                                resp = requests.get(content, timeout=10)
                                if resp.status_code == 200:
                                    with open(file_path, "wb") as f: f.write(resp.content)
                            if os.path.exists(file_path):
                                seg['content'] = f"served://{filename}"; seg['is_local'] = True
                        except: pass
        return messages

    def validate_python_code(self, content):
        try:
            ast.parse(content)
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError: line {e.lineno}"
        except Exception as e:
            return False, str(e)

    def generate_project_map(self):
        """生成项目树结构（用于 System Prompt）"""
        lines = []
        ignore_dirs = {'.git', '__pycache__', 'node_modules', '.idea', '.vscode', '_knowledge_base_v2'}
        ignore_exts = {'.pyc', '.pyo', '.db', '.sqlite3'}
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            rel_root = os.path.relpath(root, self.project_root)
            if rel_root == '.':
                rel_root = ''
            level = rel_root.count(os.sep) + 1 if rel_root else 0
            indent = '  ' * level
            dirname = os.path.basename(root) if rel_root else os.path.basename(self.project_root)
            lines.append(f"{indent}{dirname}/")
            sub_indent = '  ' * (level + 1)
            for f in sorted(files):
                if any(f.endswith(ext) for ext in ignore_exts):
                    continue
                lines.append(f"{sub_indent}{f}")
            if level >= 3:
                dirs[:] = []
        return '\n'.join(lines[:200])

    def save_code(self, name, content):
        # [Security] 路径沙箱检查：防止 AI 读写项目目录外的文件
        if not self.is_safe_path(name):
             return False, f"❌ Security Error: Path '{name}' is outside project root."

        if self.is_content_ignored(content):
            return False, "Ignored by content hash"

        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # 如果这个指纹之前失败过，且内容没变，直接跳过，不再报错
        if content_hash in self._failed_hashes:
            return False, None 

        if self.saved_hashes.get(name) == content_hash: return False, None

        code_dir, _ = self._ensure_dirs()
        full_path = os.path.join(code_dir, name)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        if name == "AI_JOURNAL.md":
            mode = "a" if os.path.exists(full_path) else "w"
            if mode == "a":
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        if content.strip() in f.read(): return False, None
                except: pass
            with open(full_path, mode, encoding='utf-8') as f:
                f.write("\n\n" + content.strip() if mode == "a" else content)
            return True, "Journal Updated"

        if name.endswith(".py"):
            is_valid, err = self.validate_python_code(content)
            if not is_valid:
                # [Mod] 报警抑制：仅在第一次遇到此错误时打印，之后静默
                print(f"⚠️ [FileService] 拦截到残缺代码 {name}: {err} (Added to suppression list)")
                self._failed_hashes.add(content_hash)
                return False, f"❌ 代码残缺 ({err})，已丢弃"

        tmp = full_path + ".tmp"
        try:
            with open(tmp, "w", encoding='utf-8') as f: f.write(content)
            if os.path.exists(full_path): os.remove(full_path)
            os.rename(tmp, full_path)
            
            # [RAG 实时同步] 仅在保存成功后进行物理增量索引
            knowledge_engine.update_file_index(name, content)
            
            self.saved_hashes[name] = content_hash
            # 如果曾经失败过，现在成功了，从失败名单移除
            if content_hash in self._failed_hashes:
                self._failed_hashes.remove(content_hash)
            return True, f"Saved: {name}"
        except Exception as e:
            return False, str(e)