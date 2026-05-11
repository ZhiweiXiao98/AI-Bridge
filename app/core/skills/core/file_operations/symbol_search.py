import ast
from pathlib import Path


def search_symbols(path: str, output_format: str = "text") -> str | dict:
    """
    搜索文件内的所有符号定义（函数、类、方法、Markdown 标题等）。
    
    参数：
    - path: 文件路径
    - output_format: 返回格式，"text" 或 "json"
    
    返回：
    - 根据文件类型返回结构化的符号信息
    """
    p = Path(path)
    if not p.exists():
        return {"error": "File not found", "path": path} if output_format == "json" else f"❌ Error: File '{path}' not found."
    
    suffix = p.suffix.lower()
    text = p.read_text(encoding="utf-8", errors="replace")
    
    if suffix == ".py":
        return _search_python_symbols(path, text, output_format)
    elif suffix == ".md":
        return _search_markdown_symbols(path, text, output_format)
    else:
        return {"error": "Unsupported file type", "path": path, "suffix": suffix} if output_format == "json" else f"❌ Error: Unsupported file type '{suffix}' for symbol search."


def _search_python_symbols(path: str, text: str, output_format: str) -> str | dict:
    """
    搜索 Python 文件中的类、函数、方法。
    """
    result = {
        "path": path,
        "type": "python",
        "classes": [],
        "functions": [],
        "total_classes": 0,
        "total_functions": 0,
        "total_methods": 0,
    }
    
    try:
        tree = ast.parse(text)
    except Exception as e:
        result["error"] = f"Failed to parse Python file: {str(e)}"
        if output_format == "json":
            return result
        return f"❌ Error: Failed to parse Python file '{path}': {str(e)}"
    
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        "name": item.name,
                        "start_line": getattr(item, "lineno", None),
                        "end_line": getattr(item, "end_lineno", None),
                        "async": isinstance(item, ast.AsyncFunctionDef),
                    })
            
            bases = []
            for base in node.bases:
                try:
                    bases.append(ast.unparse(base) if hasattr(ast, "unparse") else type(base).__name__)
                except Exception:
                    bases.append(type(base).__name__)
            
            result["classes"].append({
                "name": node.name,
                "start_line": getattr(node, "lineno", None),
                "end_line": getattr(node, "end_lineno", None),
                "bases": bases,
                "methods": methods,
            })
            result["total_classes"] += 1
            result["total_methods"] += len(methods)
        
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append({
                "name": node.name,
                "start_line": getattr(node, "lineno", None),
                "end_line": getattr(node, "end_lineno", None),
                "async": isinstance(node, ast.AsyncFunctionDef),
            })
            result["total_functions"] += 1
    
    if output_format == "json":
        return result
    
    return _format_python_symbols_text(result)


def _search_markdown_symbols(path: str, text: str, output_format: str) -> str | dict:
    """
    搜索 Markdown 文件中的标题。
    """
    result = {
        "path": path,
        "type": "markdown",
        "headings": [],
        "total_headings": 0,
    }
    
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        
        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break
        
        title = stripped[level:].strip()
        if title:
            result["headings"].append({
                "level": level,
                "title": title,
                "line": idx,
            })
            result["total_headings"] += 1
    
    if output_format == "json":
        return result
    
    return _format_markdown_symbols_text(result)


def _format_python_symbols_text(result: dict) -> str:
    """
    将 Python 符号搜索结果格式化为文本。
    """
    lines = [
        f"📄 File: {result['path']}",
        f"Type: Python",
        f"Total Classes: {result['total_classes']}",
        f"Total Functions: {result['total_functions']}",
        f"Total Methods: {result['total_methods']}",
        "",
    ]
    
    if result["functions"]:
        lines.append("Functions:")
        for func in result["functions"]:
            async_marker = " [async]" if func.get("async") else ""
            lines.append(f"  - {func['name']} (lines {func['start_line']}-{func['end_line']}){async_marker}")
        lines.append("")
    
    if result["classes"]:
        lines.append("Classes:")
        for cls in result["classes"]:
            bases_str = f", bases: {', '.join(cls['bases'])}" if cls.get("bases") else ""
            lines.append(f"  - {cls['name']} (lines {cls['start_line']}-{cls['end_line']}){bases_str}")
            if cls.get("methods"):
                lines.append("    Methods:")
                for method in cls["methods"]:
                    async_marker = " [async]" if method.get("async") else ""
                    lines.append(f"      * {method['name']} (lines {method['start_line']}-{method['end_line']}){async_marker}")
            lines.append("")
    
    return chr(10).join(lines)


def _format_markdown_symbols_text(result: dict) -> str:
    """
    将 Markdown 符号搜索结果格式化为文本。
    """
    lines = [
        f"📄 File: {result['path']}",
        f"Type: Markdown",
        f"Total Headings: {result['total_headings']}",
        "",
    ]
    
    if result["headings"]:
        lines.append("Headings:")
        for heading in result["headings"]:
            indent = "  " * (heading["level"] - 1)
            marker = "#" * heading["level"]
            lines.append(f"{indent}- {marker} {heading['title']} (line {heading['line']})")
    
    return chr(10).join(lines)
