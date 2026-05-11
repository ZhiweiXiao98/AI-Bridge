import os
import sys
import importlib.util
import logging
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from app.core.skills.base import BaseSkill, SkillMetadata
from app.core.skills.loader import SkillLoader
from app.core.logging import get_logger

logger = get_logger("app.core.skills.manager", side="worker")

class SkillsManager:
    '''Skills 管理器，负责扫描、加载、管理所有 Skills'''
    
    def __init__(self, skills_root: str = "app/core/skills", docker_manager=None, knowledge_engine=None):
        self.skills_root = skills_root
        self.docker_manager = docker_manager  # 保存 docker_manager
        self.knowledge_engine = knowledge_engine  # 保存 knowledge_engine
        self.config_file: Optional[str] = None                # 配置文件路径
        self.core_skills: Dict[str, Dict[str, Any]] = {}      # 核心 Skills
        self.extended_skills: Dict[str, Dict[str, Any]] = {}  # 扩展 Skills
        self.external_skills: Dict[str, Dict[str, Any]] = {}  # 外部 Skills
        self.skill_instances: Dict[str, BaseSkill] = {}       # Skill 实例（如果有 skill.py）
        self._skills: Dict[str, Dict[str, Any]] = {}          # 所有 Skills 的统一视图
        
    def scan_all_skills(self) -> Tuple[int, int, int]:
        '''
        扫描所有 Skills
        
        Returns:
            (core_count, extended_count, external_count)
        '''
        core_count = self._scan_directory(
            os.path.join(self.skills_root, 'core'),
            self.core_skills
        )
        
        extended_count = self._scan_directory(
            os.path.join(self.skills_root, 'extended'),
            self.extended_skills
        )
        
        external_count = self._scan_directory(
            os.path.join(self.skills_root, 'external'),
            self.external_skills
        )
        

        # 更新统一视图
        self._skills = {}
        self._skills.update(self.core_skills)
        self._skills.update(self.extended_skills)
        self._skills.update(self.external_skills)

        # 自动加载配置
        self.load_config()

        return core_count, extended_count, external_count
    
    def _scan_directory(self, directory: str, target_dict: Dict) -> int:
        '''扫描指定目录下的所有 Skills'''
        if not os.path.exists(directory):
            return 0
        
        count = 0
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            
            # 跳过非目录和特殊文件
            if not os.path.isdir(item_path):
                continue
            if item.startswith('.') or item.startswith('__'):
                continue
            
            # 加载 Skill
            success, skill_data, error = SkillLoader.load_skill_md(item_path)
            
            if success:
                skill_name = skill_data['metadata']['name']
                target_dict[skill_name] = skill_data
                
                # 如果有 skill.py，尝试加载
                if skill_data['has_code']:
                    self._load_skill_code(skill_name, item_path)
                
                count += 1
            else:
                print(f"⚠️ 加载 Skill 失败: {item_path} - {error}")
        
        return count
    
    def _load_skill_code(self, skill_name: str, skill_path: str):
        '''动态加载 skill.py 文件（支持相对导入）'''
        skill_py_path = os.path.join(skill_path, 'skill.py')

        try:
            # 确保 skill 目录的父目录在 sys.path 中
            parent_dir = os.path.dirname(skill_path)
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

            # 用包路径作为模块名，支持相对导入
            package_name = os.path.basename(skill_path)
            module_name = f"{package_name}.skill"
            spec = importlib.util.spec_from_file_location(
                module_name,
                skill_py_path,
                submodule_search_locations=[skill_path]
            )
            module = importlib.util.module_from_spec(spec)
            module.__package__ = package_name
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            # 查找 BaseSkill 的子类
            # 查找 BaseSkill 的子类
            if hasattr(module, '__skill__'):
                skill_class = module.__skill__
                # 如果是 code_execution，传入 docker_manager
                # 根据 skill 类型传入不同的依赖
                if skill_name == "code_execution" and self.docker_manager:
                    self.skill_instances[skill_name] = skill_class(docker_manager=self.docker_manager)
                elif skill_name == "knowledge_search" and self.knowledge_engine:
                    self.skill_instances[skill_name] = skill_class(knowledge_engine=self.knowledge_engine)
                elif skill_name == "file_operations":
                    self.skill_instances[skill_name] = skill_class()
                else:
                    self.skill_instances[skill_name] = skill_class()
            else:
                print(f"⚠️ {skill_py_path} 未导出 __skill__")
                
        except Exception as e:
            print(f"⚠️ 加载 skill.py 失败: {skill_py_path} - {e}")
    
    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        '''获取指定 Skill 的数据'''
        # 按优先级查找：core > extended > external
        if name in self.core_skills:
            return self.core_skills[name]
        if name in self.extended_skills:
            return self.extended_skills[name]
        if name in self.external_skills:
            return self.external_skills[name]
        return None
    
    def get_skill_instance(self, name: str) -> Optional[BaseSkill]:
        '''获取 Skill 实例（如果有 skill.py）'''
        return self.skill_instances.get(name)

    def reload_skill(self, name: str) -> Tuple[bool, str]:
        '''重新加载单个 Skill 的代码与实例'''
        skill_data = self.get_skill(name)
        if not skill_data:
            return False, f"Skill '{name}' 不存在"

        base_dir = None
        if name in self.core_skills:
            base_dir = os.path.join(self.skills_root, 'core')
        elif name in self.extended_skills:
            base_dir = os.path.join(self.skills_root, 'extended')
        elif name in self.external_skills:
            base_dir = os.path.join(self.skills_root, 'external')

        if not base_dir:
            return False, f"Skill '{name}' 的目录无法确定"

        skill_path = os.path.join(base_dir, name)
        if not os.path.isdir(skill_path):
            return False, f"Skill 目录不存在: {skill_path}"

        try:
            self.skill_instances.pop(name, None)
            self._load_skill_code(name, skill_path)
            if name not in self.skill_instances:
                return False, f"Skill '{name}' 重新加载失败，未生成实例"
            return True, f"Skill '{name}' 已重新加载"
        except Exception as e:
            return False, f"Skill '{name}' 重新加载失败: {e}"
    
    def list_all_skills(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        '''
        列出所有 Skills
        
        Args:
            category: 可选，按分类筛选
            
        Returns:
            Skills 列表
        '''
        all_skills = []
        
        for skills_dict in [self.core_skills, self.extended_skills, self.external_skills]:
            for name, skill_data in skills_dict.items():
                metadata = skill_data['metadata']
                
                if category and metadata.get('category') != category:
                    continue
                
                all_skills.append({
                    'id': metadata['name'],  # id 和 name 相同
                    'name': metadata['name'],
                    'display_name': metadata.get('display_name', metadata['name']),
                    'category': metadata['category'],
                    'description': metadata.get('description', ''),
                    'version': metadata['version'],
                    'dangerous': metadata.get('dangerous', False),
                    'enabled': metadata.get('enabled', True),
                    'has_code': skill_data['has_code']
                })
        
        return all_skills
    

    def toggle_skill(self, skill_name: str, enabled: bool) -> bool:
        """
        启用或禁用指定的 Skill
        
        Args:
            skill_name: Skill 名称
            enabled: True 启用，False 禁用
            
        Returns:
            bool: 操作是否成功
        """
        # 在所有 skills 字典中查找并修改
        found = False
        
        for skills_dict in [self.core_skills, self.extended_skills, self.external_skills]:
            if skill_name in skills_dict:
                skills_dict[skill_name]['metadata']['enabled'] = enabled
                found = True
                break
        
        if not found:
            print(f"❌ Skill '{skill_name}' 不存在")
            return False
        
        # 同步到 _skills
        if skill_name in self._skills:
            self._skills[skill_name]['metadata']['enabled'] = enabled
        
        status = "启用" if enabled else "禁用"
        print(f"✅ 已{status} Skill: {skill_name}")
        
        return True


    def get_all_tool_definitions(self) -> list:
        """
        获取所有启用的 Skills 的工具定义
        
        Returns:
            list: 工具定义列表，符合 OpenAI/Anthropic Function Calling 格式
        """
        tools = []
        
        # 收集所有启用的 skills
        all_skills = []
        all_skills.extend(self.core_skills.values())
        all_skills.extend(self.extended_skills.values())
        all_skills.extend(self.external_skills.values())
        
        for skill_data in all_skills:
            metadata = skill_data.get('metadata', {})
            if not metadata.get('enabled', True):
                continue
            
            skill_name = metadata.get('name')
            instance = self.get_skill_instance(skill_name)
            
            if instance:
                try:
                    tool_def = instance.get_tool_definition()
                    tools.append(tool_def)
                except Exception as e:
                    logger.warning(f"获取 {skill_name} 工具定义失败: {e}")
        
        return tools


    def _format_skill_section(self, skill_data: dict) -> str:
        """格式化单个 Skill 的描述"""
        metadata = skill_data.get('metadata', {})
        content = skill_data.get('content', '')
        
        section = f"### {metadata.get('display_name', 'Unknown')}\n\n"
        section += f"**Name**: {metadata.get('name', 'unknown')}\n"
        section += f"**Category**: {metadata.get('category', 'unknown')}\n"
        section += f"**Scenario**: {metadata.get('scenario', 'N/A')}\n\n"
        section += content + "\n\n---\n\n"
        
        return section
    def generate_system_prompt(self) -> str:
        """生成系统提示词"""
        prompt = "# Available Skills\n\n"
        prompt += "You have access to the following skills. Use them when appropriate.\n\n"
        
        # Function Calling 使用说明
        prompt += "## How to Use Skills\n\n"
        prompt += "To use a skill, output a tool call in the following format:\n\n"
        prompt += "```tool_call\n"
        prompt += "{\n"
        prompt += '  "name": "skill_name",\n'
        prompt += '  "arguments": {"param1": "value1"}\n'
        prompt += "}\n"
        prompt += "```\n\n"
        prompt += "**Important:** Use exact skill names and provide all required parameters.\n\n"
        prompt += "## Available Skills\n\n"
        
        # Core Skills
        if self.core_skills:
            prompt += "## Core Skills (Always Available)\n\n"
            for skill_data in self.core_skills.values():
                prompt += self._format_skill_section(skill_data)
        
        # Extended Skills
        if self.extended_skills:
            prompt += "## Extended Skills\n\n"
            for skill_data in self.extended_skills.values():
                prompt += self._format_skill_section(skill_data)
        
        # External Skills
        if self.external_skills:
            prompt += "## External Skills\n\n"
            for skill_data in self.external_skills.values():
                prompt += self._format_skill_section(skill_data)
        
        return prompt

    
    def _generate_skills_section(self, skills_dict: Dict) -> str:
        '''生成 Skills 部分的提示词'''
        section = ""
        
        for name, skill_data in skills_dict.items():
            metadata = skill_data['metadata']
            content = skill_data['content']
            
            section += f"### {metadata.get('display_name', name)}\n\n"
            section += f"**Name**: {name}\n"
            section += f"**Category**: {metadata['category']}\n"
            section += f"**Scenario**: {metadata['scenario']}\n\n"
            section += content
            section += "\n\n---\n\n"
        
        return section
    
    def execute_skill(self, name: str, **kwargs) -> Tuple[bool, Any, str]:
        '''
        执行 Skill
        
        Returns:
            (success, result, error_message)
        '''
        skill_data = self.get_skill(name)
        if not skill_data:
            return False, None, f"Skill '{name}' 不存在"
        
        metadata = skill_data.get('metadata', {})
        if not metadata.get('enabled', True):
            return False, None, f"Skill '{name}' 已被禁用"
        
        skill_instance = self.get_skill_instance(name)
        if not skill_instance:
            return False, None, f"Skill '{name}' 没有可执行代码"
        
        # 验证参数
        is_valid, error = skill_instance.validate(**kwargs)
        if not is_valid:
            return False, None, error
        
        # 执行
        try:
            result = skill_instance.execute(**kwargs)
            return True, result, ""
        except Exception as e:
            return False, None, f"执行失败: {str(e)}"
    
    def get_categories(self) -> List[str]:
        '''获取所有分类'''
        categories = set()
        
        for skills_dict in [self.core_skills, self.extended_skills, self.external_skills]:
            for skill_data in skills_dict.values():
                categories.add(skill_data['metadata']['category'])
        
        return sorted(list(categories))


    def save_config(self) -> bool:
        """
        保存 Skills 配置到文件
        
        Returns:
            bool: 保存是否成功
        """
        if not self.config_file:
            print("⚠️ 未设置配置文件路径")
            return False
        
        import json
        
        config = {
            'skills': {}
        }
        
        # 收集所有 skills 的状态
        for skills_dict in [self.core_skills, self.extended_skills, self.external_skills]:
            for name, skill_data in skills_dict.items():
                config['skills'][name] = {
                    'enabled': skill_data['metadata'].get('enabled', True)
                }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            print(f"✅ 配置已保存到: {self.config_file}")
            return True
        except Exception as e:
            print(f"❌ 保存配置失败: {e}")
            return False
    
    def load_config(self) -> bool:
        """
        从文件加载 Skills 配置
        
        Returns:
            bool: 加载是否成功
        """
        if not self.config_file:
            return False
        
        import json
        import os
        
        if not os.path.exists(self.config_file):
            return False
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 应用配置
            loaded_count = 0
            for skill_name, skill_config in config.get('skills', {}).items():
                enabled = skill_config.get('enabled', True)
                if self.toggle_skill(skill_name, enabled):
                    loaded_count += 1
            
            print(f"✅ 配置已加载: {self.config_file} ({loaded_count} 个 skills)")
            return True
        except Exception as e:
            print(f"❌ 加载配置失败: {e}")
            return False
