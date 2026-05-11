# filename: app/core/knowledge/chunker.py
import ast
import logging
from typing import List, Dict
from app.core.knowledge.config import MAX_CHUNK_LINES, MIN_CHUNK_LINES, FALLBACK_CHUNK_SIZE
from app.core.logging import get_logger

logger = get_logger("app.core.knowledge.chunker", side="worker")


class ASTChunker:
    """基于 AST 的代码分块器"""

    def chunk_file(self, file_path: str, content: str) -> List[Dict]:
        """
        将文件内容分块。
        Python 文件用 AST 解析，其他文件按行数切分。
        返回: [{id, content, metadata}, ...]
        """
        if file_path.endswith(".py"):
            chunks = self._chunk_python(file_path, content)
            if chunks:
                return chunks
        return self._chunk_by_lines(file_path, content)

    def _chunk_python(self, file_path: str, content: str) -> List[Dict]:
        """用 AST 解析 Python 文件，按函数/类边界分块"""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            logger.debug(f"AST 解析失败，fallback: {file_path}")
            return []

        lines = content.splitlines()
        chunks = []
        used_lines = set()

        # 提取文件头部（imports + 模块级代码）
        header_end = 0
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                break
            if hasattr(node, "end_lineno"):
                header_end = node.end_lineno

        if header_end > 0:
            header = self._join_lines(lines, 0, header_end)
            if len(header.splitlines()) >= MIN_CHUNK_LINES:
                chunks.append(self._make_chunk(
                    file_path, "header", header,
                    chunk_type="header"
                ))
                used_lines.update(range(0, header_end))

        # 提取顶层函数和类
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunk = self._extract_node(lines, node, file_path, "function")
                if chunk:
                    chunks.append(chunk)
                    used_lines.update(range(node.lineno - 1, node.end_lineno))

            elif isinstance(node, ast.ClassDef):
                # 类本身作为一个 chunk（包含类定义和 docstring）
                class_chunks = self._extract_class(lines, node, file_path)
                for c in class_chunks:
                    chunks.append(c)
                    start = node.lineno - 1
                    end = node.end_lineno
                    used_lines.update(range(start, end))

        # 收集未被覆盖的散落代码
        orphan_lines = []
        for i, line in enumerate(lines):
            if i not in used_lines and line.strip():
                orphan_lines.append(line)
        if len(orphan_lines) >= MIN_CHUNK_LINES:
            orphan_text = NL_CHAR.join(orphan_lines)
            chunks.append(self._make_chunk(
                file_path, "orphan", orphan_text,
                chunk_type="orphan"
            ))

        # 去重：property getter/setter 会产生同名 ID
        seen_ids = {}
        for chunk in chunks:
            cid = chunk["id"]
            if cid in seen_ids:
                seen_ids[cid] += 1
                chunk["id"] = f"{cid}_{seen_ids[cid]}"
            else:
                seen_ids[cid] = 1

        return chunks

    def _extract_node(self, lines, node, file_path, node_type):
        """提取单个函数节点"""
        start = node.lineno - 1
        end = node.end_lineno
        text = self._join_lines(lines, start, end)
        if len(text.splitlines()) < MIN_CHUNK_LINES:
            return None
        # 超长函数截断
        if len(text.splitlines()) > MAX_CHUNK_LINES:
            text = self._join_lines(lines, start, start + MAX_CHUNK_LINES)
        return self._make_chunk(file_path, node.name, text,
                                chunk_type=node_type, symbol=node.name)

    def _extract_class(self, lines, node, file_path):
        """提取类：类签名 + 每个方法单独分块"""
        chunks = []
        # 类签名（到第一个方法之前）
        class_start = node.lineno - 1
        first_method_line = None
        methods = []

        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if first_method_line is None:
                    first_method_line = child.lineno - 1
                methods.append(child)

        # 类头部（签名 + 类变量 + docstring）
        header_end = first_method_line if first_method_line else node.end_lineno
        header_text = self._join_lines(lines, class_start, header_end)
        if len(header_text.splitlines()) >= MIN_CHUNK_LINES:
            chunks.append(self._make_chunk(
                file_path, f"{node.name}.__class__", header_text,
                chunk_type="class", symbol=node.name
            ))

        # 每个方法单独分块
        for method in methods:
            chunk = self._extract_node(lines, method, file_path, "method")
            if chunk:
                chunk["metadata"]["class"] = node.name
                chunk["metadata"]["symbol"] = f"{node.name}.{method.name}"
                chunk["id"] = f"{file_path}#{node.name}.{method.name}"
                chunks.append(chunk)

        return chunks

    def _chunk_by_lines(self, file_path: str, content: str) -> List[Dict]:
        """Fallback：按固定行数切分"""
        lines = content.splitlines()
        chunks = []
        for i in range(0, len(lines), FALLBACK_CHUNK_SIZE):
            chunk_lines = lines[i:i + FALLBACK_CHUNK_SIZE]
            text = NL_CHAR.join(chunk_lines)
            if len(chunk_lines) < MIN_CHUNK_LINES:
                continue
            chunks.append(self._make_chunk(
                file_path, f"chunk_{i}", text,
                chunk_type="block"
            ))
        return chunks

    @staticmethod
    def _join_lines(lines, start, end):
        return NL_CHAR.join(lines[start:end])

    @staticmethod
    def _make_chunk(file_path, name, content, chunk_type="unknown", symbol=None):
        return {
            "id": f"{file_path}#{name}",
            "content": f"File: {file_path}{NL_CHAR}{content}",
            "metadata": {
                "path": file_path,
                "type": chunk_type,
                "symbol": symbol or name,
            }
        }


# 换行符常量（避免转义问题）
NL_CHAR = chr(10)