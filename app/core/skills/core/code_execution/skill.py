# filename: app/core/skills/core/code_execution/skill.py
from typing import Any
from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter


class CodeExecutionSkill(BaseSkill):
    '''代码执行 Skill'''
    
    def __init__(self, docker_manager=None):
        super().__init__()
        self.docker = docker_manager
    
    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="code_execution",
            display_name="代码执行",
            category="code",
            description="在 Docker 沙盒中安全执行 Python 代码",
            scenario="需要验证代码逻辑、测试功能、诊断问题时",
            version="1.0.0",
            author="System",
            parameters=[
                SkillParameter(
                    name="code",
                    type="str",
                    required=True,
                    description="要执行的 Python 代码"
                ),
                SkillParameter(
                    name="timeout",
                    type="int",
                    required=False,
                    description="超时时间（秒）",
                    default=60
                ),
                SkillParameter(
                    name="skip_validation",
                    type="bool",
                    required=False,
                    description="是否跳过代码验证",
                    default=False
                )
            ],
            examples=[
                "code_execution(code='print(2+2)')",
                "code_execution(code='import os; print(os.getcwd())', timeout=30)"
            ],
            dangerous=True
        )
    

    def _get_parameters_schema(self) -> dict:
        """代码执行的参数定义"""
        return {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码"
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认 60 秒",
                "default": 60
            },
            "skip_validation": {
                "type": "boolean",
                "description": "是否跳过安全验证，默认 False",
                "default": False
            }
        }
    
    def _get_required_parameters(self) -> list:
        """必需参数"""
        return ["code"]

    def execute(self, code: str, timeout: int = 60, skip_validation: bool = False, **kwargs) -> Any:
        """
        执行 Python 代码
        
        ⚠️ 重要：调用此方法前，确保代码块已添加 # EXEC 标记
        
        Args:
            code: Python 代码（必须以 # EXEC 开头）
            timeout: 超时时间（秒）
            skip_validation: 跳过安全验证
        
        Returns:
            执行结果字符串
        """
        if not self.docker:
            return "❌ Error: Docker 环境不可用"
        
        if not self.docker.available:
            return "❌ Error: Docker 未连接"
        
        try:
            exit_code, output = self.docker.execute_code(
                code=code,
                timeout=timeout,
                skip_validation=skip_validation
            )
            
            if exit_code == 0:
                if not output.strip():
                    return "✅ 代码执行成功（无输出）"
                else:
                    return f"🖥️ 执行输出:\n{output}"
            else:
                return f"❌ 执行错误 (Exit Code {exit_code}):\n{output}"
        
        except Exception as e:
            return f"❌ 执行异常: {str(e)}"


__skill__ = CodeExecutionSkill
