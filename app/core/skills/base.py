# filename: app/core/skills/base.py
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod


@dataclass
class SkillParameter:
    '''Skill 参数定义'''
    name: str
    type: str
    required: bool
    description: str
    default: Any = None


@dataclass
class SkillMetadata:
    '''Skill 元数据'''
    name: str                           # 技能名称（唯一标识）
    display_name: str                   # 显示名称
    category: str                       # 分类（file/code/network/system）
    description: str                    # 功能描述
    scenario: str                       # 适用场景
    version: str                        # 版本号
    author: str                         # 作者
    parameters: List[SkillParameter] = field(default_factory=list)  # 参数列表
    examples: List[str] = field(default_factory=list)               # 使用示例
    dangerous: bool = False             # 是否危险操作
    enabled: bool = True                # 是否启用
    
    def to_dict(self) -> Dict[str, Any]:
        '''转换为字典'''
        return {
            'name': self.name,
            'display_name': self.display_name,
            'category': self.category,
            'description': self.description,
            'scenario': self.scenario,
            'version': self.version,
            'author': self.author,
            'parameters': [
                {
                    'name': p.name,
                    'type': p.type,
                    'required': p.required,
                    'description': p.description,
                    'default': p.default
                }
                for p in self.parameters
            ],
            'examples': self.examples,
            'dangerous': self.dangerous,
            'enabled': self.enabled
        }


class BaseSkill(ABC):
    '''Skill 基类'''
    
    def __init__(self):
        self._metadata: Optional[SkillMetadata] = None
    
    @property
    @abstractmethod
    def metadata(self) -> SkillMetadata:
        '''返回 Skill 元数据'''
        pass
    
    def validate(self, **kwargs) -> tuple[bool, str]:
        '''
        验证参数
        
        Returns:
            (is_valid, error_message)
        '''
        meta = self.metadata
        
        # 检查必需参数
        for param in meta.parameters:
            if param.required and param.name not in kwargs:
                return False, f"缺少必需参数: {param.name}"
        
        return True, ""
    
    def get_tool_definition(self) -> dict:
        """
        返回工具的 JSON Schema 定义（OpenAI/Anthropic 格式）
        
        Returns:
            dict: 工具定义，包含 name, description, parameters
        """
        metadata = self.metadata
        
        return {
            "type": "function",
            "function": {
                "name": metadata.name,
                "description": metadata.description,
                "parameters": {
                    "type": "object",
                    "properties": self._get_parameters_schema(),
                    "required": self._get_required_parameters()
                }
            }
        }
    
    def _get_parameters_schema(self) -> dict:
        """
        子类应该重写此方法，返回参数的 JSON Schema
        
        Returns:
            dict: 参数定义
        """
        return {}
    
    def _get_required_parameters(self) -> list:
        """
        子类应该重写此方法，返回必需参数列表
        
        Returns:
            list: 必需参数名称列表
        """
        return []

    def execute(self, **kwargs) -> Any:
        '''
        执行 Skill
        
        Returns:
            执行结果
        '''
        pass
    
    def get_help(self) -> str:
        '''获取帮助信息'''
        meta = self.metadata
        help_text = f"# {meta.display_name}\n\n"
        help_text += f"{meta.description}\n\n"
        help_text += f"**分类**: {meta.category}\n"
        help_text += f"**适用场景**: {meta.scenario}\n\n"
        
        if meta.parameters:
            help_text += "## 参数\n\n"
            for param in meta.parameters:
                required = "必需" if param.required else "可选"
                default = f" (默认: {param.default})" if param.default is not None else ""
                help_text += f"- **{param.name}** ({param.type}, {required}){default}: {param.description}\n"
        
        if meta.examples:
            help_text += "\n## 示例\n\n"
            for example in meta.examples:
                help_text += f"- {example}\n"
        
        if meta.dangerous:
            help_text += "\n⚠️ **警告**: 这是危险操作，请谨慎使用\n"
        
        return help_text
