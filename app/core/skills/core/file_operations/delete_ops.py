from pathlib import Path
from .result_utils import success_result, error_result, verify_contains, confirmation_required_result
from .safety_ops import guard_delete_risk
from .validators import validate_by_extension
from .persist_ops import persist_text_file


def delete_text(path: str, target_text: str, count: int = 1, atomic: bool = True, output_format: str = 'text', confirm_large_delete: bool = False, allow_near_empty_result: bool = False, validate_code: bool = True, knowledge_engine=None):
    p = Path(path)
    if not p.exists():
        return error_result('delete_text', path, 'File not found', output_format=output_format)
    original = p.read_text(encoding='utf-8', errors='replace')
    matches = original.count(target_text)
    if matches <= 0:
        return error_result('delete_text', path, 'Target text not found', output_format=output_format, Matches=0)
    updated = original.replace(target_text, '', count)
    ok, reason, risk = guard_delete_risk(original, updated, confirm_large_delete, allow_near_empty_result)
    if not ok:
        return confirmation_required_result('delete_text', path, reason, output_format=output_format, BlockedBySafetyGuard=True, **risk)
    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        return error_result('delete_text', path, 'syntax validation failed', output_format=output_format, **validation, **risk)
    ok2, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok2:
        return error_result('delete_text', path, 'syntax validation failed', output_format=output_format, **details, **risk)
    verified = not verify_contains(path, target_text)
    return success_result('delete_text', path, output_format=output_format, Matches=min(count, matches), Verified=verified, Atomic=atomic, ValidateCode=validate_code, **risk)


def delete_between(path: str, start_anchor: str, end_anchor: str, include_anchors: bool = False, occurrence: int = 1, atomic: bool = True, output_format: str = 'text', confirm_large_delete: bool = False, allow_near_empty_result: bool = False, validate_code: bool = True, knowledge_engine=None):
    p = Path(path)
    if not p.exists():
        return error_result('delete_between', path, 'File not found', output_format=output_format)
    original = p.read_text(encoding='utf-8', errors='replace')
    search_from = 0
    start = -1
    for _ in range(max(1, occurrence)):
        start = original.find(start_anchor, search_from)
        if start < 0:
            return error_result('delete_between', path, 'Start anchor not found', output_format=output_format, StartAnchor=start_anchor)
        search_from = start + len(start_anchor)
    end = original.find(end_anchor, start + len(start_anchor))
    if end < 0:
        return error_result('delete_between', path, 'End anchor not found', output_format=output_format, EndAnchor=end_anchor)
    delete_start = start if include_anchors else start + len(start_anchor)
    delete_end = end + len(end_anchor) if include_anchors else end
    updated = original[:delete_start] + original[delete_end:]
    ok, reason, risk = guard_delete_risk(original, updated, confirm_large_delete, allow_near_empty_result)
    if not ok:
        return confirmation_required_result('delete_between', path, reason, output_format=output_format, BlockedBySafetyGuard=True, **risk)
    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        return error_result('delete_between', path, 'syntax validation failed', output_format=output_format, **validation, **risk)
    ok2, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok2:
        return error_result('delete_between', path, 'syntax validation failed', output_format=output_format, **details, **risk)
    return success_result('delete_between', path, output_format=output_format, Verified=True, Atomic=atomic, ValidateCode=validate_code, IncludeAnchors=include_anchors, Occurrence=occurrence, **risk)


def remove_section(path: str, section_header: str, header_level: int = None, atomic: bool = True, output_format: str = 'text', confirm_large_delete: bool = False, allow_near_empty_result: bool = False, validate_code: bool = True, knowledge_engine=None):
    p = Path(path)
    if not p.exists():
        return error_result('remove_section', path, 'File not found', output_format=output_format)
    original = p.read_text(encoding='utf-8', errors='replace')
    lines = original.splitlines()
    target_idx = None
    level = header_level
    for idx, line in enumerate(lines):
        if line.strip() == section_header.strip():
            target_idx = idx
            if level is None:
                stripped = line.lstrip()
                level = len(stripped) - len(stripped.lstrip('#'))
            break
    if target_idx is None:
        return error_result('remove_section', path, 'Section header not found', output_format=output_format, SectionHeader=section_header)
    end_idx = len(lines)
    for idx in range(target_idx + 1, len(lines)):
        line = lines[idx].lstrip()
        if line.startswith('#'):
            current_level = len(line) - len(line.lstrip('#'))
            if current_level <= level:
                end_idx = idx
                break
    new_lines = lines[:target_idx] + lines[end_idx:]
    updated = chr(10).join(new_lines)
    if original.endswith(chr(10)):
        updated += chr(10)
    ok, reason, risk = guard_delete_risk(original, updated, confirm_large_delete, allow_near_empty_result)
    if not ok:
        return confirmation_required_result('remove_section', path, reason, output_format=output_format, BlockedBySafetyGuard=True, SectionHeader=section_header, **risk)
    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        return error_result('remove_section', path, 'syntax validation failed', output_format=output_format, SectionHeader=section_header, ValidateCode=validate_code, **validation, **risk)
    ok2, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok2:
        return error_result('remove_section', path, 'syntax validation failed', output_format=output_format, SectionHeader=section_header, ValidateCode=validate_code, **details, **risk)
    return success_result('remove_section', path, output_format=output_format, Verified=True, Atomic=atomic, SectionHeader=section_header, ValidateCode=validate_code, **risk)
