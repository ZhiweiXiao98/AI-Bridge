import re
from pathlib import Path


_BLOCK_HEADER_RE = re.compile(
    r'^\s*(class\s+\w+.*:|def\s+\w+\s*\(.*\)\s*:|if\s+.*:|elif\s+.*:|else\s*:|try\s*:|except\b.*:|finally\s*:|with\s+.*:|for\s+.*:|while\s+.*:)\s*$',
    re.IGNORECASE,
)

_TOP_LEVEL_INSERT_RE = re.compile(r'^(class\s+\w+|def\s+\w+\s*\(|@\w+|from\s+\S+\s+import\s+|import\s+\S+)')


def _line_start(text: str, index: int) -> int:
    prev_newline = text.rfind(chr(10), 0, index)
    return 0 if prev_newline < 0 else prev_newline + 1


def _line_end(text: str, index: int) -> int:
    next_newline = text.find(chr(10), index)
    return len(text) if next_newline < 0 else next_newline


def _get_line_at(text: str, index: int) -> str:
    start = _line_start(text, index)
    end = _line_end(text, index)
    return text[start:end]


def _first_non_empty_line(text: str) -> str:
    for line in (text or '').splitlines():
        if line.strip():
            return line
    return ''


def assess_python_structural_anchor_risk(path: str, original_text: str, anchor_index: int, content: str, position: str) -> dict:
    suffix = Path(path).suffix.lower()
    if suffix != '.py':
        return {'blocked': False, 'risk': False}

    anchor_line = _get_line_at(original_text, anchor_index)
    if not _BLOCK_HEADER_RE.match(anchor_line.strip()):
        return {'blocked': False, 'risk': False}

    first_line = _first_non_empty_line(content)
    if not first_line:
        return {
            'blocked': False,
            'risk': True,
            'reason': 'Python structural anchor risk',
            'AnchorLine': anchor_line,
            'FirstContentLine': first_line,
            'StructuralAnchorRisk': True,
            'Position': position,
        }

    has_indent = first_line[:1].isspace()
    looks_top_level = bool(_TOP_LEVEL_INSERT_RE.match(first_line.strip()))

    blocked = (position == 'after') and (not has_indent) and looks_top_level
    reason = 'High-risk structural insert after Python block header' if blocked else 'Python structural anchor risk'
    suggestion = '建议改用 insert_before 下一个顶级定义，或使用 replace_between / insert_at_line。'
    return {
        'blocked': blocked,
        'risk': True,
        'reason': reason,
        'AnchorLine': anchor_line,
        'FirstContentLine': first_line,
        'StructuralAnchorRisk': True,
        'LooksTopLevelInsert': looks_top_level,
        'HasIndent': has_indent,
        'Position': position,
        'Suggestion': suggestion,
    }
