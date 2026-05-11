# filename: app/core/agent_manager.py
import os
import sys
import shutil
import re
import subprocess
import time
from app.core.config import ConfigManager
# [RAG 注入]
from app.core.services.knowledge_service import knowledge_engine

from app.core.skills import SkillsManager

class AgentManager:
    def __init__(self, file_service, docker_manager=None, knowledge_service=None):
        # 存储依赖
        self.docker_manager = docker_manager
        self.knowledge_service = knowledge_service

        self.config = ConfigManager.load()
        self.file_service = file_service
        self.session_roles = {}
        self.safety_backups = {}
        
        self.path_redirects = {
            "app/ui/worker.py": "app/core/worker.py",
            "app/ui/error_reporter.py": "app/core/utils/error_reporter.py"
        }
        

        # Skills 系统
        self.skills_manager = SkillsManager()
        
        # 存储依赖供 Skills 使用
        self.docker_manager = docker_manager
        self.knowledge_service = knowledge_service
        
        # 扫描并加载所有 Skills
        core_count, extended_count, external_count = self.skills_manager.scan_all_skills()
        print(f"📚 [Skills] 已加载: {core_count} 核心 + {extended_count} 扩展 + {external_count} 外部")
        
        # 初始化 Skill 实例（传入依赖）
        file_skill = self.skills_manager.get_skill_instance('file_operations')
        if file_skill:
            file_skill.file_service = self.file_service
        
        code_skill = self.skills_manager.get_skill_instance('code_execution')
        if code_skill:
            code_skill.docker = self.docker_manager
        
        knowledge_skill = self.skills_manager.get_skill_instance('knowledge_search')
        if knowledge_skill:
            knowledge_skill.knowledge_engine = self.knowledge_service


    def reload_skill(self, name: str):
        '''重新加载单个 Skill，并补齐依赖注入'''
        success, message = self.skills_manager.reload_skill(name)
        if not success:
            return False, message

        skill = self.skills_manager.get_skill_instance(name)
        if not skill:
            return False, f"Skill '{name}' 重载后实例不存在"

        if name == 'file_operations':
            skill.file_service = self.file_service
        elif name == 'code_execution':
            if hasattr(skill, 'docker'):
                skill.docker = self.docker_manager
            if hasattr(skill, 'docker_manager'):
                skill.docker_manager = self.docker_manager
        elif name == 'knowledge_search':
            skill.knowledge_engine = self.knowledge_service

        return True, message

    def set_role(self, index, role):
        keys_to_remove = [k for k, v in self.session_roles.items() if v == role]
        for k in keys_to_remove:
            if role: del self.session_roles[k]
        if role: self.session_roles[index] = role
        else: 
            if index in self.session_roles: del self.session_roles[index]
            
    def get_mechanic_index(self):
        for idx, role in self.session_roles.items():
            if role == "mechanic": return idx
        return None

    def shift_roles_for_new_chat(self):
        new_roles = {k+1: v for k, v in self.session_roles.items()}
        self.session_roles = new_roles
        self.session_roles[0] = "mechanic"

    def _resolve_legacy_path(self, path):
        clean_path = path.replace("\\", "/")
        if clean_path in self.path_redirects:
            new_path = self.path_redirects[clean_path]
            print(f"🔄 [Agent] 路径重定向: {clean_path} -> {new_path}")
            return new_path
        
        if clean_path.endswith("worker.py") and "app/core" not in clean_path:
            return "app/core/worker.py"
            
        return path

    def tool_read_file(self, path, max_lines=1000):
        '''读取文件内容（通过 Skills 系统）'''
        success, result, error = self.skills_manager.execute_skill(
            'file_operations', operation='read_file', path=path, max_lines=max_lines
       )
        if success:
            return result
        
        # 降级：如果 Skill 不可用，使用原有逻辑
        return self._legacy_read_file(path, max_lines)
    
    def _legacy_read_file(self, path, max_lines=1000):
        '''原有的读取文件逻辑（降级方案）'''
        path = path.replace('"', '').replace("'", "").strip()
        path = self._resolve_legacy_path(path)
        
        if not self.file_service.is_safe_path(path):
             return f"❌ Error: Access denied to '{path}'. Security Violation."

        if not os.path.exists(path): 
            return f"❌ Error: File '{path}' not found."
            
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            lines = content.splitlines()
            total_lines = len(lines)
            
            safe_content = content.replace("```", "'''")
            
            if total_lines > max_lines:
                preview = "\n".join(lines[:max_lines])
                return (f"📄 File: {path} (Showing first {max_lines} of {total_lines} lines)\n"
                        f"⚠️ Content truncated to prevent token overflow.\n"
                        f"```python\n{preview}\n```\n"
                        f"💡 Hint: This file is too large. Read specific parts if needed.")
            
            ext = os.path.splitext(path)[1]
            lang = "python" if ext == ".py" else "text"
            
            hint = (
                f"\n💡 To modify this file, output a code block with:\n"
                f"# filename: {path}\n"
                f"... (full content) ..."
            )
            
            return (f"📄 File: {path} ({total_lines} lines)\n"
                    f"```{lang}\n{safe_content}\n```"
                    f"{hint}")
                    
        except Exception as e: return f"❌ Error reading file: {e}"

    def tool_list_files(self, directory="."):
        '''列出目录文件（通过 Skills 系统）'''
        success, result, error = self.skills_manager.execute_skill(
            'file_operations', operation='list_files', path=directory
        )
        if success:
            return result
        
        # 降级：如果 Skill 不可用，使用原有逻辑
        return self._legacy_list_files(directory)
    
    def _legacy_list_files(self, directory="."):
        '''原有的列出文件逻辑（降级方案）'''
        try:
            if not directory or directory.strip() == "": directory = "."
            
            if not self.file_service.is_safe_path(directory):
                return f"❌ Error: Access denied to '{directory}'."
                
            if not os.path.exists(directory):
                return f"❌ Error: Directory '{directory}' not found."

            items = os.listdir(directory)
            files = []
            dirs = []
            
            IGNORE_MARKERS = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', 'update_cache', 'htmlcov', '.pytest_cache', '_knowledge_base'}

            for item in items:
                if item in IGNORE_MARKERS: continue
                
                full_path = os.path.join(directory, item)
                if os.path.isdir(full_path):
                    dirs.append(f"📂 {item}/")
                else:
                    files.append(f"📄 {item}")
            
            dirs.sort()
            files.sort()
            
            display_dir = "Root" if directory == "." else directory
            output = [f"📂 Listing of '{display_dir}':"]
            
            if dirs:
                output.append("\n[Directories]")
                output.extend(dirs)
            if files:
                output.append("\n[Files]")
                output.extend(files)
            
            if directory == "." and "app" in [d.strip("📂 /") for d in dirs]:
                output.append("\n💡 Hint: Use [TOOL: list_files path=\"app/core\"] to explore subfolders.")
                
            return "\n".join(output)
            
        except Exception as e: return f"❌ Error listing files: {e}"

    def tool_search_knowledge(self, query):
        '''知识检索（通过 Skills 系统）'''
        success, result, error = self.skills_manager.execute_skill(
            'knowledge_search', query=query
        )
        if success:
            return result
        
        # 降级：如果 Skill 不可用，使用原有逻辑
        return self._legacy_search_knowledge(query)
    
    def _legacy_search_knowledge(self, query):
        '''原有的知识检索逻辑（降级方案）'''
        """
        [New Tool] 允许 AI 在 2 万行代码库中进行语义搜针
        """
        print(f"🔍 [Agent] 正在语义检索: {query}")
        return knowledge_engine.search_context(query, top_k=5)

    def _run_verification_test(self):
        cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                timeout=60
            )
            return proc.returncode == 0, proc.stdout + "\n" + proc.stderr
        except subprocess.TimeoutExpired:
            return False, "❌ Test Execution Timed Out (60s)"
        except Exception as e: return False, f"❌ Test Execution Failed: {str(e)}"

    def safe_apply_and_test(self, code_segments):
        changed_files = []
        targets = {}
        for seg in code_segments:
            if seg['type'] != 'code': continue
            name = None
            for line in seg['content'].split('\n')[:5]:
                m = re.search(r"^(?:#|//|<!--)\s*filename\s*[:]?\s*(.+?)(?:-->)?$", line.strip(), re.IGNORECASE)
                if m: 
                    potential_name = m.group(1).strip()
                    if re.match(r'^[\w\-. /\\_]+$', potential_name):
                        name = potential_name
                        break
            
            if name: 
                real_name = self._resolve_legacy_path(name)
                # [修正] 保持物理写入路径正确，不通过 replace 猜测，直接映射
                targets[real_name] = seg['content']

        if not targets: return False, [], "No valid code blocks found."

        for f in targets.keys():
            if not self.file_service.is_safe_path(f):
                 return False, [], f"❌ Security Error: Cannot write to '{f}' outside project root."
                 
            abs_p = os.path.abspath(f)
            if os.path.exists(abs_p):
                bak = abs_p + ".bak"
                shutil.copy2(abs_p, bak)
                self.safety_backups[f] = bak
        
        try:
            for name, content in targets.items():
                success, msg = self.file_service.save_code(name, content)
                if not success:
                    raise Exception(f"Failed to save {name}: {msg}")
                    
                changed_files.append(name)
        except Exception as e:
            self.rollback_changes()
            return False, [], f"Write Error: {e}"

        success, log = self._run_verification_test()

        if success:
            self.confirm_changes()
            return True, changed_files, log
        else:
            self.rollback_changes()
            return False, [], log

    def rollback_changes(self):
        restored = []
        for file_path, bak_path in self.safety_backups.items():
            try:
                if os.path.exists(bak_path):
                    for i in range(3):
                        try:
                            shutil.move(bak_path, os.path.abspath(file_path))
                            restored.append(file_path)
                            break
                        except PermissionError:
                            time.sleep(0.5)
            except Exception as e:
                print(f"🔥 [CRITICAL] Rollback Failed for {file_path}: {e}")
        self.safety_backups.clear()
        return restored

    def confirm_changes(self):
        for _, bak_path in self.safety_backups.items():
            try:
                if os.path.exists(bak_path): os.remove(bak_path)
            except: pass
        self.safety_backups.clear()

    def parse_agent_response(self, full_text):
        if "[TOOL:" in full_text:
            m = re.search(r'\[TOOL:\s*(\w+)\s*(.*?)\]', full_text, re.IGNORECASE | re.DOTALL)
            if m:
                return "TOOL", {"name": m.group(1).lower(), "args": m.group(2)}
        
        if "filename" in full_text and "```" in full_text:
            return "CODE", None
            
        return "CHAT", None

    def construct_system_prompt(self, error_report):
        project_map = self.file_service.generate_project_map()
        return f"""【⚠️ SYSTEM ALERT】
{error_report}

【🗺️ Project Context】
{project_map}

【🧑‍💻 Autonomous Developer Protocol】
You are managing a massive codebase (20,000+ lines). 
Do NOT guess module relationships. Use RAG SEARCH if you are unsure.

**Available TOOLS:**
1. `[TOOL: search_knowledge query="..."]` : Semantic search to find relevant functions/logic.
2. `[TOOL: read_file path="..."]` : Read the full source of a specific file.
3. `[TOOL: list_files directory="..."]` : Explore the file structure.
4. Output Code Block : Fixed code with `# filename: ...` (Standard Overwrite).

**Protocol:**
- If the error is about a module you don't know, use `search_knowledge` FIRST.
- I will auto-verify your fix with pytest.
"""