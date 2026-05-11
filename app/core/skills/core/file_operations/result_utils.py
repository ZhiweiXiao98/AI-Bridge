import logging
import json
from pathlib import Path
logger = logging.getLogger("result_utils")


def _count_lines(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def build_result(success: bool, operation: str, path: str, message: str, **data) -> dict:
    return {
        'success': success,
        'operation': operation,
        'path': path,
        'message': message,
        'data': data,
    }


def format_result(result: dict, output_format: str = 'text'):
    if str(output_format).lower() == 'json':
        return result
    icon = '✅' if result.get('success') else '❌'
    lines = [f"{icon} {result.get('message')}", f"Path: {result.get('path')}"]
    for key, value in result.get('data', {}).items():
        lines.append(f"{key}: {value}")
    return chr(10).join(lines)


def success_result(operation: str, path: str, output_format: str = 'text', **kwargs):
    return format_result(build_result(True, operation, path, f'{operation} succeeded', **kwargs), output_format)


def error_result(operation: str, path: str, message: str, output_format: str = 'text', **kwargs):
    return format_result(build_result(False, operation, path, f'{operation} failed', Reason=message, **kwargs), output_format)


def confirmation_required_result(operation: str, path: str, message: str, output_format: str = 'text', **kwargs):
    return format_result(
        build_result(False, operation, path, f'{operation} requires confirmation', Reason=message, RequiresConfirmation=True, **kwargs),
        output_format,
    )


def verify_contains(path: str, expected: str) -> bool:
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
        return expected in text
    except Exception:
        return False


def summarize_text(text: str) -> dict:
    return {
        'Bytes': len(text.encode('utf-8')),
        'Lines': _count_lines(text),
    }


def summarize_text(text: str) -> dict:
    return {
        'Bytes': len(text.encode('utf-8')),
        'Lines': _count_lines(text),
    }
