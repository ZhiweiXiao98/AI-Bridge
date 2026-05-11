import ast
import datetime as _dt
import logging
import os
from pathlib import Path

from .path_utils import IGNORE_MARKERS
from .result_utils import error_result, success_result, summarize_text

logger = logging.getLogger("read_ops")


def _format_numbered_lines(lines: list[str], start_line: int = 1) -> str:
    numbered = []
    for idx, line in enumerate(lines, start=start_line):
        numbered.append(f"{idx:>4} | {line}")
    return chr(10).join(numbered)


def _count_python_symbols(text: str) -> dict:
    result = {
        "classes": [],
        "functions": [],
        "imports": [],
        "total_classes": 0,
        "total_functions": 0,
        "total_methods": 0,
        "total_imports": 0,
    }
    try:
        tree = ast.parse(text)
    except Exception:
        return result



def _extract_markdown_structure(text: str) -> dict:
    """
    提取 Markdown 文件的结构信息。
    """
    result = {
        'headings': [],
        'total_headings': 0,
    }
    
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped.startswith('#'):
            continue
        
        level = 0
        for ch in stripped:
            if ch == '#':
                level += 1
            else:
                break
        
        title = stripped[level:].strip()
        if title:
            result['headings'].append({
                'level': level,
                'title': title,
                'line': idx,
            })
            result['total_headings'] += 1
    
    return result

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(
                        {
                            "name": item.name,
                            "line": getattr(item, "lineno", None),
                            "async": isinstance(item, ast.AsyncFunctionDef),
                        }
                    )
            result["classes"].append(
                {
                    "name": node.name,
                    "line": getattr(node, "lineno", None),
                    "end_line": getattr(node, "end_lineno", None),
                    "bases": [
                        ast.unparse(base) if hasattr(ast, "unparse") else type(base).__name__
                        for base in node.bases
                    ],
                    "methods": methods,
                }
            )
            result["total_classes"] += 1
            result["total_methods"] += len(methods)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append(
                {
                    "name": node.name,
                    "line": getattr(node, "lineno", None),
                    "end_line": getattr(node, "end_lineno", None),
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
            result["total_functions"] += 1
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({"module": alias.name, "line": getattr(node, "lineno", None)})
                result["total_imports"] += 1
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported = ", ".join(alias.name for alias in node.names)
            result["imports"].append({"module": f"from {mod} import {imported}", "line": getattr(node, "lineno", None)})
            result["total_imports"] += 1

    return result


def _count_markdown_headings(text: str) -> dict:
    headings = []
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
            headings.append({"level": level, "title": title, "line": idx})
    return {
        "headings": headings,
        "total_headings": len(headings),
    }


def _safe_structure_overview(path: str, text: str) -> dict:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return _count_python_symbols(text)
    if suffix == ".md":
        return _count_markdown_headings(text)
    return {}


def read_file(path: str, max_lines: int = 1000) -> str:
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    lines = content.splitlines()
    total_lines = len(lines)
    if total_lines > max_lines:
        preview = _format_numbered_lines(lines[:max_lines], start_line=1)
        return (
            f"📄 File: {path} (Showing first {max_lines} of {total_lines} lines)" + chr(10) +
            "⚠️ Content truncated" + chr(10) +
            "Content with line numbers:" + chr(10) +
            preview + chr(10) +
            "💡 Hint: File is large, read specific parts if needed."
        )
    body = _format_numbered_lines(lines, start_line=1)
    return f"📄 File: {path} ({total_lines} lines)" + chr(10) + "Content with line numbers:" + chr(10) + body


def read_lines(path: str, start_line: int = 1, end_line: int = 1) -> str:
    if start_line < 1 or end_line < 1:
        return f"❌ Error: start_line 和 end_line 必须 >= 1"
    if end_line < start_line:
        return f"❌ Error: end_line 必须 >= start_line"

    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    lines = content.splitlines()
    total_lines = len(lines)

    if total_lines == 0:
        return f"📄 File: {path} (0 lines)" + chr(10) + "Content with line numbers:"

    actual_start = min(start_line, total_lines)
    actual_end = min(end_line, total_lines)
    selected = lines[actual_start - 1:actual_end]
    body = _format_numbered_lines(selected, start_line=actual_start)

    return (
        f"📄 File: {path} (Lines {actual_start}-{actual_end} of {total_lines})" + chr(10) +
        "Content with line numbers:" + chr(10) +
        body
    )


def list_files(directory: str) -> str:
    items = os.listdir(directory)
    files = []
    dirs = []
    for item in items:
        if item in IGNORE_MARKERS:
            continue
        full_path = os.path.join(directory, item)
        if os.path.isdir(full_path):
            dirs.append(f"📂 {item}/")
        else:
            files.append(f"📄 {item}")
    dirs.sort()
    files.sort()
    display_dir = 'Root' if directory == '.' else directory
    output = [f"📂 Listing of '{display_dir}':"]
    if dirs:
        output.append('')
        output.append('[Directories]')
        output.extend(dirs)
    if files:
        output.append('')
        output.append('[Files]')
        output.extend(files)
    if directory == '.' and any(x == '📂 app/' for x in dirs):
        output.append('')
        output.append("💡 Hint: Use list_files(path='app/core') to explore subfolders.")
    return chr(10).join(output)


def file_exists(path: str, output_format: str = 'text'):
    exists = os.path.exists(path)
    return success_result('file_exists', path, output_format=output_format, Exists=exists)


def _safe_structure_overview(path: str, text: str) -> dict:
    """
    安全地提取文件结构概览，支持 Python 和 Markdown 文件。
    """
    suffix = Path(path).suffix.lower()
    
    if suffix == '.py':
        return _extract_python_structure(text)
    elif suffix == '.md':
        return _extract_markdown_structure(text)
    else:
        return {}


def _extract_python_structure(text: str) -> dict:
    """
    提取 Python 文件的结构信息。
    """
    result = {
        'classes': [],
        'functions': [],
        'imports': [],
        'total_classes': 0,
        'total_functions': 0,
        'total_methods': 0,
        'total_imports': 0,
    }
    
    try:
        tree = ast.parse(text)
    except Exception:
        return result
    
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = []
            for base in node.bases:
                try:
                    bases.append(ast.unparse(base) if hasattr(ast, 'unparse') else type(base).__name__)
                except Exception:
                    bases.append(type(base).__name__)
            
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        'name': item.name,
                        'line': getattr(item, 'lineno', None),
                        'end_line': getattr(item, 'end_lineno', None),
                    })
            
            result['classes'].append({
                'name': node.name,
                'line': getattr(node, 'lineno', None),
                'end_line': getattr(node, 'end_lineno', None),
                'bases': bases,
                'methods': methods,
            })
            result['total_classes'] += 1
            result['total_methods'] += len(methods)
        
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result['functions'].append({
                'name': node.name,
                'line': getattr(node, 'lineno', None),
                'end_line': getattr(node, 'end_lineno', None),
                'async': isinstance(node, ast.AsyncFunctionDef),
            })
            result['total_functions'] += 1
        
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result['imports'].append({
                    'module': alias.name,
                    'line': getattr(node, 'lineno', None),
                })
                result['total_imports'] += 1
        
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            imported = ', '.join(alias.name for alias in node.names)
            result['imports'].append({
                'module': f"from {mod} import {imported}",
                'line': getattr(node, 'lineno', None),
            })
            result['total_imports'] += 1
    
    return result


def stat_file(path: str, output_format: str = 'text'):
    if not os.path.exists(path):
        return error_result('stat_file', path, 'File or directory not found', output_format=output_format)
    stat = os.stat(path)
    modified = _dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')

    info = {
        'Exists': True,
        'IsFile': os.path.isfile(path),
        'IsDir': os.path.isdir(path),
        'SizeBytes': stat.st_size,
        'ModifiedAt': modified,
        'Path': path,
    }

    if os.path.isfile(path):
        text = Path(path).read_text(encoding='utf-8', errors='replace')
        info.update(summarize_text(text))
        info['Suffix'] = Path(path).suffix.lower()
        info['Parent'] = str(Path(path).parent)
        info['Name'] = Path(path).name
        
        structure = _safe_structure_overview(path, text)
        info['StructureOverview'] = structure
        
        is_large = info.get('Lines', 0) > 500
        info['IsLargeFile'] = is_large
        if is_large:
            info['Suggestion'] = 'Large file detected. Use search_symbols for complete structure index.'
    else:
        children = [name for name in os.listdir(path) if name not in IGNORE_MARKERS]
        info['ChildrenCount'] = len(children)
        info['SampleChildren'] = children[:20]

    if output_format == 'json':
        return success_result('stat_file', path, output_format=output_format, **info)
    lines = [
        f"Path: {info['Path']}",
        f"Exists: {info['Exists']}",
        f"Type: {'file' if info['IsFile'] else 'directory'}",
        f"SizeBytes: {info['SizeBytes']}",
        f"ModifiedAt: {info['ModifiedAt']}",
    ]

    if info['IsFile']:
        lines.extend([
            f"Lines: {info.get('Lines', 0)}",
            f"Bytes: {info.get('Bytes', 0)}",
            f"Suffix: {info.get('Suffix', '')}",
            f"Parent: {info.get('Parent', '')}",
        ])
        
        if info.get('IsLargeFile'):
            lines.append(f"⚠️ {info.get('Suggestion', '')}")
            lines.append("")
        
        structure = info.get('StructureOverview') or {}
        
        if 'total_classes' in structure:
            lines.append(f"Total Classes: {structure.get('total_classes', 0)}")
            lines.append(f"Total Functions: {structure.get('total_functions', 0)}")
            lines.append(f"Total Methods: {structure.get('total_methods', 0)}")
            lines.append(f"Total Imports: {structure.get('total_imports', 0)}")
            
            classes = structure.get('classes', [])
            functions = structure.get('functions', [])
            
            if classes:
                lines.append('Classes:')
                display_limit = 3 if info.get('IsLargeFile') else 10
                for item in classes[:display_limit]:
                    bases_str = f" bases={item['bases']}" if item.get('bases') else ''
                    end_line = item.get('end_line', '?')
                    lines.append(f"  - {item['name']} (lines {item['line']}-{end_line}){bases_str}")
                    methods = item.get('methods', [])
                    method_limit = 5 if info.get('IsLargeFile') else 20
                    for method in methods[:method_limit]:
                        m_start = method.get('line', '?')
                        m_end = method.get('end_line', '?')
                        lines.append(f"      * {method['name']} (lines {m_start}-{m_end})")
                    if len(methods) > method_limit:
                        lines.append(f"      ... and {len(methods) - method_limit} more methods")
                if len(classes) > display_limit:
                    lines.append(f"  ... and {len(classes) - display_limit} more classes")
            
            if functions:
                lines.append('TopLevelFunctions:')
                display_limit = 10 if info.get('IsLargeFile') else 50
                for item in functions[:display_limit]:
                    prefix = 'async ' if item.get('async') else ''
                    f_end = item.get('end_line', '?')
                    lines.append(f"  - {prefix}{item['name']} (lines {item['line']}-{f_end})")
                if len(functions) > display_limit:
                    lines.append(f"  ... and {len(functions) - display_limit} more functions")
        
        elif 'total_headings' in structure:
            lines.append(f"Total Headings: {structure.get('total_headings', 0)}")
            headings = structure.get('headings', [])
            if headings:
                lines.append('Headings (first 20):')
                for heading in headings[:20]:
                    indent = "  " * (heading['level'] - 1)
                    marker = "#" * heading['level']
                    lines.append(f"{indent}- {marker} {heading['title']} (line {heading['line']})")
                if len(headings) > 20:
                    lines.append(f"  ... and {len(headings) - 20} more headings")
    else:
        lines.append(f"ChildrenCount: {info.get('ChildrenCount', 0)}")
        samples = info.get('SampleChildren', [])
        if samples:
            lines.append('SampleChildren:')
            for name in samples:
                lines.append(f"  - {name}")

    return chr(10).join(lines)


def read_file_tail(path: str, max_lines: int = 100) -> str:
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    lines = content.splitlines()
    total_lines = len(lines)
    if total_lines <= max_lines:
        body = _format_numbered_lines(lines, start_line=1)
        return f"📄 File: {path} ({total_lines} lines)" + chr(10) + "Content with line numbers:" + chr(10) + body
    start_line = total_lines - max_lines + 1
    tail = _format_numbered_lines(lines[-max_lines:], start_line=start_line)
    return (
        f"📄 File: {path} (Showing last {max_lines} of {total_lines} lines)" + chr(10) +
        "Content with line numbers:" + chr(10) +
        tail
    )
