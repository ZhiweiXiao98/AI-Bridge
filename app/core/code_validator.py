# filename: app/core/code_validator.py
"""
代码静态检查模块
在沙盒执行前分析代码，检测潜在危险操作
"""
import ast
import logging
from typing import Tuple, List
from app.core.logging import get_logger

logger = get_logger("app.core.code_validator", side="worker")

class DangerousOperationDetector(ast.NodeVisitor):
    """检测危险操作的 AST 访问器"""
    
    # 危险的内置函数
    DANGEROUS_BUILTINS = {
        'eval', 'exec', 'compile', '__import__',
        'open',  # 文件操作需要审查
        'input',  # 可能导致阻塞
    }
    
    # 危险的模块
    DANGEROUS_MODULES = {
        'os', 'sys', 'subprocess', 'shutil',
        'socket', 'urllib', 'requests',
        'pickle', 'shelve', 'marshal',
    }
    
    # 允许的安全模块（白名单）
    SAFE_MODULES = {
        'math', 'random', 'datetime', 'time',
        'json', 're', 'collections', 'itertools',
        'functools', 'operator', 'string',
        'numpy', 'pandas', 'matplotlib',
    }
    
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.imports = []
    
    def visit_Import(self, node):
        """检查 import 语句"""
        for alias in node.names:
            module_name = alias.name.split('.')[0]
            self.imports.append(module_name)
            
            if module_name in self.DANGEROUS_MODULES:
                self.warnings.append(
                    f"⚠️ 第 {node.lineno} 行: 导入了潜在危险模块 '{module_name}'"
                )
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node):
        """检查 from ... import 语句"""
        if node.module:
            module_name = node.module.split('.')[0]
            self.imports.append(module_name)
            
            if module_name in self.DANGEROUS_MODULES:
                self.warnings.append(
                    f"⚠️ 第 {node.lineno} 行: 从潜在危险模块 '{module_name}' 导入"
                )
        self.generic_visit(node)
    
    def visit_Call(self, node):
        """检查函数调用"""
        # 检查内置函数调用
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in self.DANGEROUS_BUILTINS:
                if func_name in ('eval', 'exec', 'compile'):
                    self.errors.append(
                        f"❌ 第 {node.lineno} 行: 禁止使用 '{func_name}()'"
                    )
                else:
                    self.warnings.append(
                        f"⚠️ 第 {node.lineno} 行: 使用了 '{func_name}()'，请确保安全"
                    )
        self.generic_visit(node)
    
    def visit_While(self, node):
        """检查 while 循环（可能导致无限循环）"""
        # 检查是否是 while True
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            self.warnings.append(
                f"⚠️ 第 {node.lineno} 行: 发现 'while True' 循环，请确保有退出条件"
            )
        self.generic_visit(node)

class CodeValidator:
    """代码验证器"""
    
    @staticmethod
    def validate(code: str) -> Tuple[bool, List[str], List[str]]:
        """
        验证代码安全性
        
        Args:
            code: 要验证的代码
            
        Returns:
            (is_safe, warnings, errors) 元组
            - is_safe: 是否安全（没有严重错误）
            - warnings: 警告列表
            - errors: 错误列表
        """
        try:
            # 解析代码为 AST
            tree = ast.parse(code)
            
            # 运行检测器
            detector = DangerousOperationDetector()
            detector.visit(tree)
            
            is_safe = len(detector.errors) == 0
            
            return is_safe, detector.warnings, detector.errors
            
        except SyntaxError as e:
            return False, [], [f"❌ 语法错误: {e}"]
        except Exception as e:
            logger.error(f"代码验证失败: {e}")
            return False, [], [f"❌ 验证失败: {e}"]
    
    @staticmethod
    def format_validation_result(warnings: List[str], errors: List[str]) -> str:
        """格式化验证结果"""
        result = []
        
        if errors:
            result.append("🚫 代码包含禁止的操作：")
            for error in errors:
                result.append(f"  {error}")
        
        if warnings:
            result.append("\n⚠️ 代码包含需要注意的操作：")
            for warning in warnings:
                result.append(f"  {warning}")
        
        return "\n".join(result)
