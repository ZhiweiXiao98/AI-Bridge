import os
import re
import yaml
from typing import Dict, Any, Optional, Tuple
from pathlib import Path


class SkillLoader:
    '''Skill 加载器，负责解析 SKILL.md 文件'''
    
    @staticmethod
    def load_skill_md(skill_path: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        '''
        加载并解析 SKILL.md 文件
        
        Args:
            skill_path: Skill 文件夹路径
            
        Returns:
            (success, skill_data, error_message)
        '''
        skill_md_path = os.path.join(skill_path, 'SKILL.md')
        
        if not os.path.exists(skill_md_path):
            return False, None, f"未找到 SKILL.md 文件: {skill_md_path}"
        
        try:
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析 YAML Front Matter
            metadata, body = SkillLoader._parse_front_matter(content)
            
            if not metadata:
                return False, None, "SKILL.md 缺少元数据（YAML Front Matter）"
            
            # 验证必需字段
            required_fields = ['name', 'category', 'version', 'author', 'scenario']
            for field in required_fields:
                if field not in metadata:
                    return False, None, f"元数据缺少必需字段: {field}"
            
            # 构建完整的 Skill 数据
            skill_data = {
                'metadata': metadata,
                'content': body,
                'path': skill_path,
                'has_code': os.path.exists(os.path.join(skill_path, 'skill.py'))
            }
            
            return True, skill_data, ""
            
        except Exception as e:
            return False, None, f"解析 SKILL.md 失败: {str(e)}"
    
    @staticmethod
    def _parse_front_matter(content: str) -> Tuple[Optional[Dict], str]:
        '''
        解析 YAML Front Matter
        
        Returns:
            (metadata_dict, body_content)
        '''
        # 匹配 YAML Front Matter: ---\n...\n---
        pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(pattern, content, re.DOTALL)
        
        if not match:
            return None, content
        
        yaml_content = match.group(1)
        body = match.group(2)
        
        try:
            metadata = yaml.safe_load(yaml_content)
            return metadata, body
        except yaml.YAMLError as e:
            print(f"⚠️ YAML 解析错误: {e}")
            return None, content
