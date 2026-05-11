import ast
import logging
import re

from app.core.logging import get_logger

logger = get_logger("app.core.pseudocode_generator", side="worker")

class PseudocodeGenerator:
    """
    🚀 PseudocodeGenerator 3.0 (终极版)
    - 完整支持：f-string, 下标取值, 链式比较
    - 语义兜底：ast.unparse 保证不崩溃
    - 逻辑检测：自动标注嵌套深度和参数风险
    """

    KEYWORDS = {
        'if': '如果', 'else': '否则', 'elif': '或者如果',
        'for': '对于', 'while': '当...时', 'in': '在...中',
        'is': '是', 'not': '不', 'and': '且', 'or': '或',
        'return': '返回', 'def': '定义函数', 'class': '定义类',
        'import': '导入', 'from': '从', 'as': '作为',
        'try': '尝试', 'except': '捕获异常', 'finally': '最终执行',
        'with': '使用', 'None': '空', 'True': '真', 'False': '假',
        'print': '输出', 'len': '长度', 'range': '范围'
    }

    VOCABULARY = {
        'load': '加载', 'save': '保存', 'config': '配置', 'path': '路径',
        'file': '文件', 'data': '数据', 'user': '用户', 'name': '名称',
        'result': '结果', 'status': '状态', 'get': '获取', 'set': '设置',
        'check': '检查', 'update': '更新', 'delete': '删除', 'add': '添加',
        'error': '错误', 'exists': '存在', 'os': '操作系统', 'timeout': '超时'
    }

    def __init__(self):
        self.camel_pattern = re.compile(r'(?<!^)(?=[A-Z])')
        self.current_depth = 0

    def generate(self, source_code):
        """主入口 - 保留首行注释"""
        try:
            # 提取首行注释（如果存在）
            lines = source_code.split('\n')
            header_comments = []
            code_start_idx = 0
            
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('#'):
                    header_comments.append(line)
                    code_start_idx = i + 1
                elif stripped:  # 遇到非空非注释行，停止
                    break
            
            # 解析代码
            tree = ast.parse(source_code)
            pseudo_body = self._visit(tree, 0)
            
            # 如果有首行注释，保留它们
            if header_comments:
                return '\n'.join(header_comments) + '\n' + pseudo_body
            return pseudo_body
            
        except SyntaxError as e:
            return f"❌ 源码语法错误: {e}"
        except Exception as e:
            return f"❌ 解析失败: {e}"
    
    def _visit(self, node, level=0):
        indent = "    " * level
        self.current_depth = level 

        if isinstance(node, ast.Module):
            return "\n".join([self._visit(n, level) for n in node.body])

        if isinstance(node, ast.FunctionDef):
            raw_args = [a.arg for a in node.args.args]
            args = [self.translate_identifier(a) for a in raw_args]
            warning = " [⚠️ 参数过多, 建议重构]" if len(args) > 5 else ""
            header = f"{indent}【定义函数】 {self.translate_identifier(node.name)}{warning} (参数: {', '.join(args)}):"
            body = "\n".join([self._visit(n, level + 1) for n in node.body])
            return f"{header}\n{body}"

        if isinstance(node, ast.If):
            test = self._visit_expr(node.test)
            warning = " [⚠️ 逻辑嵌套过深]" if level > 3 else ""
            header = f"{indent}如果 {test}{warning}:"
            body = "\n".join([self._visit(n, level + 1) for n in node.body])
            result = f"{header}\n{body}"
            if node.orelse:
                if isinstance(node.orelse[0], ast.If):
                    result += f"\n{self._visit(node.orelse[0], level).lstrip()}"
                else:
                    result += f"\n{indent}否则:\n" + "\n".join([self._visit(n, level + 1) for n in node.orelse])
            return result

        if isinstance(node, ast.Assign):
            targets = [self._visit_expr(t) for t in node.targets]
            value = self._visit_expr(node.value)
            return f"{indent}{' = '.join(targets)} = {value}"

        if isinstance(node, ast.For):
            target = self._visit_expr(node.target)
            iter_obj = self._visit_expr(node.iter)
            header = f"{indent}遍历 {iter_obj} 中的每一项给 {target}:"
            body = "\n".join([self._visit(n, level + 1) for n in node.body])
            return f"{header}\n{body}"

        if isinstance(node, ast.Return):
            return f"{indent}返回 {self._visit_expr(node.value)}"

        if isinstance(node, ast.Expr):
            return f"{indent}{self._visit_expr(node.value)}"

        try:
            return f"{indent}{ast.unparse(node)}"
        except Exception as e:
            logger.debug(f"ast.unparse 失败: {e}")
            return f"{indent}# 执行: {type(node).__name__}"

    def _visit_expr(self, node):
        if node is None: return ""
        
        if isinstance(node, ast.Name):
            return self.translate_identifier(node.id)
        if isinstance(node, ast.Constant):
            return self.translate_constant(node.value)
        if isinstance(node, ast.Attribute):
            return f"{self._visit_expr(node.value)}.{self.translate_identifier(node.attr)}"
        if isinstance(node, ast.Call):
            func = self._visit_expr(node.func)
            args = [self._visit_expr(a) for a in node.args]
            kwargs = [f"{k.arg}={self._visit_expr(k.value)}" for k in node.keywords]
            return f"{func}({', '.join(args + kwargs)})"
        
        if isinstance(node, ast.JoinedStr):
            parts = []
            for val in node.values:
                if isinstance(val, ast.FormattedValue):
                    parts.append(f"{{{self._visit_expr(val.value)}}}")
                elif isinstance(val, ast.Constant):
                    parts.append(str(val.value))
            return f'f"{"".join(parts)}"'

        if isinstance(node, ast.Subscript):
            target = self._visit_expr(node.value)
            index = self._visit_expr(node.slice)
            return f"{target}[{index}]"

        if isinstance(node, ast.Compare):
            res = self._visit_expr(node.left)
            for op, comp in zip(node.ops, node.comparators):
                res += f" {self._get_op_symbol(op)} {self._visit_expr(comp)}"
            return res

        if isinstance(node, ast.BoolOp):
            op = f" {self._get_op_symbol(node.op)} "
            return op.join([self._visit_expr(v) for v in node.values])

        try:
            return ast.unparse(node)
        except Exception as e:
            logger.debug(f"expr ast.unparse 失败: {e}")
            return "..."

    def translate_identifier(self, name):
        if not name: return ""
        if name in self.KEYWORDS: return self.KEYWORDS[name]
        parts = self.split_name(name)
        return "".join([self.translate_word(p) for p in parts])

    def translate_word(self, word):
        return self.VOCABULARY.get(word.lower(), word)

    def split_name(self, name):
        parts = name.split('_')
        final_parts = []
        for p in parts:
            if not p: continue
            sub_parts = self.camel_pattern.split(p)
            final_parts.extend([sp for sp in sub_parts if sp])
        return final_parts

    def translate_constant(self, value):
        if isinstance(value, str):
            if not value: return '""'
            parts = re.split(r'([._\-/])', value)
            translated = [self.translate_identifier(p) if p not in '._-/' else p for p in parts]
            return f'"{("".join(translated))}"'
        return str(value)

    def _get_op_symbol(self, op):
        mapping = {
            ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/',
            ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<', ast.LtE: '<=',
            ast.Gt: '>', ast.GtE: '>=', ast.In: '在...中', ast.And: '且', ast.Or: '或'
        }
        return mapping.get(type(op), '?')
