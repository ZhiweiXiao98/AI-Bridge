from pathlib import Path
from .result_utils import success_result, error_result, confirmation_required_result
from .safety_ops import guard_delete_risk
from .validators import validate_by_extension
from .persist_ops import persist_text_file


def delete_lines(path: str, start_line: int, end_line: int, atomic: bool = True, output_format: str = 'text', confirm_large_delete: bool = False, allow_near_empty_result: bool = False, validate_code: bool = True, knowledge_engine=None):
    p = Path(path)
    if not p.exists():
        return error_result('delete_lines', path, 'File not found', output_format=output_format)
    original = p.read_text(encoding='utf-8', errors='replace')
    lines = original.splitlines()
    total = len(lines)
    if start_line < 1 or end_line < start_line or end_line > total:
        return error_result('delete_lines', path, 'Line range out of bounds', output_format=output_format, StartLine=start_line, EndLine=end_line, TotalLines=total)
    new_lines = lines[:start_line - 1] + lines[end_line:]
    updated = chr(10).join(new_lines)
    if original.endswith(chr(10)):
        updated += chr(10)
    ok, reason, risk = guard_delete_risk(original, updated, confirm_large_delete, allow_near_empty_result)
    if not ok:
        return confirmation_required_result('delete_lines', path, reason, output_format=output_format, BlockedBySafetyGuard=True, StartLine=start_line, EndLine=end_line, **risk)
    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        return error_result('delete_lines', path, 'syntax validation failed', output_format=output_format, StartLine=start_line, EndLine=end_line, **validation, **risk)
    ok2, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok2:
        return error_result('delete_lines', path, 'syntax validation failed', output_format=output_format, StartLine=start_line, EndLine=end_line, **details, **risk)
    return success_result('delete_lines', path, output_format=output_format, StartLine=start_line, EndLine=end_line, Verified=True, Atomic=atomic, ValidateCode=validate_code, **risk)


def replace_lines(path: str, start_line: int, end_line: int, content: str, atomic: bool = True, output_format: str = 'text', confirm_large_delete: bool = False, allow_near_empty_result: bool = False, validate_code: bool = True, knowledge_engine=None):
    p = Path(path)
    if not p.exists():
        return error_result('replace_lines', path, 'File not found', output_format=output_format)
    original = p.read_text(encoding='utf-8', errors='replace')
    lines = original.splitlines()
    total = len(lines)
    if start_line < 1 or end_line < start_line or end_line > total:
        return error_result('replace_lines', path, 'Line range out of bounds', output_format=output_format, StartLine=start_line, EndLine=end_line, TotalLines=total)
    content_lines = content.splitlines()
    new_lines = lines[:start_line - 1] + content_lines + lines[end_line:]
    updated = chr(10).join(new_lines)
    if original.endswith(chr(10)):
        updated += chr(10)
    ok, reason, risk = guard_delete_risk(original, updated, confirm_large_delete, allow_near_empty_result)
    if not ok:
        return confirmation_required_result('replace_lines', path, reason, output_format=output_format, BlockedBySafetyGuard=True, StartLine=start_line, EndLine=end_line, **risk)
    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        return error_result('replace_lines', path, 'syntax validation failed', output_format=output_format, StartLine=start_line, EndLine=end_line, **validation, **risk)
    ok2, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok2:
        return error_result('replace_lines', path, 'syntax validation failed', output_format=output_format, StartLine=start_line, EndLine=end_line, **details, **risk)
    return success_result('replace_lines', path, output_format=output_format, StartLine=start_line, EndLine=end_line, Verified=True, Atomic=atomic, ValidateCode=validate_code, **risk)


def insert_at_line(path: str, line_number: int, content: str, position: str = 'before', atomic: bool = True, output_format: str = 'text', validate_code: bool = True, knowledge_engine=None):
    p = Path(path)
    if not p.exists():
        return error_result('insert_at_line', path, 'File not found', output_format=output_format)
    original = p.read_text(encoding='utf-8', errors='replace')
    lines = original.splitlines()
    total = len(lines)
    if line_number < 1 or line_number > max(1, total):
        return error_result('insert_at_line', path, 'Line number out of bounds', output_format=output_format, LineNumber=line_number, TotalLines=total)
    insert_lines = content.splitlines()
    index = line_number - 1 if position == 'before' else line_number
    new_lines = lines[:index] + insert_lines + lines[index:]
    updated = chr(10).join(new_lines)
    if original.endswith(chr(10)):
        updated += chr(10)
    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        return error_result('insert_at_line', path, 'syntax validation failed', output_format=output_format, LineNumber=line_number, Position=position, **validation)
    ok2, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok2:
        return error_result('insert_at_line', path, 'syntax validation failed', output_format=output_format, LineNumber=line_number, Position=position, **details)
    return success_result('insert_at_line', path, output_format=output_format, LineNumber=line_number, Position=position, Verified=True, Atomic=atomic, ValidateCode=validate_code)
