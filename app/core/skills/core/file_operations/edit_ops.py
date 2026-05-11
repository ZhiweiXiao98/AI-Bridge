from pathlib import Path
from .result_utils import success_result, error_result, verify_contains, confirmation_required_result
from .validators import validate_by_extension
from .structural_guard import assess_python_structural_anchor_risk
from .persist_ops import persist_text_file
from .safety_ops import guard_delete_risk


def find_anchor_positions(text: str, anchor_text: str):
    positions = []
    start = 0
    while True:
        idx = text.find(anchor_text, start)
        if idx < 0:
            break
        positions.append(idx)
        start = idx + len(anchor_text)
    return positions


def replace_in_file(path: str, old_text: str, new_text: str, count: int = 1, atomic: bool = True, output_format: str = 'text', validate_code: bool = True, knowledge_engine=None):
    p = Path(path)
    if not p.exists():
        return error_result('replace_in_file', path, 'File not found', output_format=output_format)
    text = p.read_text(encoding='utf-8', errors='replace')
    occurrences = text.count(old_text)
    if occurrences <= 0:
        return error_result('replace_in_file', path, 'Target text not found', output_format=output_format, Replacements=0)
    updated = text.replace(old_text, new_text, count)
    ok_guard, reason, risk = guard_delete_risk(text, updated, confirm_large_delete=False, allow_near_empty_result=False)
    if not ok_guard:
        return confirmation_required_result('replace_in_file', path, reason, output_format=output_format, Replacements=0, BlockedBySafetyGuard=True, TotalMatches=occurrences, **risk)
    ok, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=validate_code, knowledge_engine=knowledge_engine)
    if not ok:
        return error_result('replace_in_file', path, 'syntax validation failed', output_format=output_format, Replacements=0, **details, **risk)
    verified = verify_contains(path, new_text[: min(len(new_text), 120)]) if new_text else True
    return success_result('replace_in_file', path, output_format=output_format, Replacements=min(count, occurrences), Verified=verified, Atomic=atomic, TotalMatches=occurrences, ValidateCode=validate_code, **risk)


def insert_after(path: str, anchor_text: str, content: str, occurrence: int = 1, strict_anchor: bool = False, atomic: bool = True, output_format: str = 'text', validate_code: bool = True, knowledge_engine=None):
    import logging
    logger = logging.getLogger("FileOpsInsertDebug")

    p = Path(path)
    if not p.exists():
        return error_result('insert_after', path, 'File not found', output_format=output_format)
    text = p.read_text(encoding='utf-8', errors='replace')
    positions = find_anchor_positions(text, anchor_text)
    if not positions:
        return error_result('insert_after', path, 'Anchor not found', output_format=output_format, Anchor=anchor_text)
    if strict_anchor and len(positions) > 1 and occurrence == 1:
        return error_result('insert_after', path, 'Anchor matched multiple times; specify occurrence', output_format=output_format, Anchor=anchor_text, TotalMatches=len(positions))
    if occurrence < 1 or occurrence > len(positions):
        return error_result('insert_after', path, 'Occurrence out of range', output_format=output_format, Anchor=anchor_text, TotalMatches=len(positions), RequestedOccurrence=occurrence)

    start = positions[occurrence - 1]
    insert_at = start + len(anchor_text)
    structural = assess_python_structural_anchor_risk(path, text, start, content, position='after')
    if structural.get('blocked'):
        logger.warning(f"[Debug][InsertAfter] Structural anchor blocked on {path}: {structural.get('reason')}")
        return error_result('insert_after', path, structural.get('reason', 'structural anchor blocked'), output_format=output_format, Anchor=anchor_text, Occurrence=occurrence, TotalMatches=len(positions), ValidateCode=validate_code, **structural)

    line_end = text.find(chr(10), insert_at)
    if line_end < 0:
        line_end = len(text)
    insert_at = line_end

    insert_content = content
    if insert_at < len(text) and text[insert_at] == chr(10):
        insert_at += 1
    if content and content[0] not in (chr(10), chr(13)):
        insert_content = chr(10) + content

    updated = text[:insert_at] + insert_content + text[insert_at:]

    logger.info(f"[Debug][InsertAfter] Inserting into {path} at position {insert_at}, content length {len(insert_content)}")
    logger.debug(f"[Debug][InsertAfter] Insert content preview:\n{insert_content[:500]}")

    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        logger.error(f"[Debug][InsertAfter] Syntax validation failed on {path}: {validation}")
        return error_result('insert_after', path, 'syntax validation failed', output_format=output_format, Anchor=anchor_text, Occurrence=occurrence, TotalMatches=len(positions), ValidateCode=validate_code, **validation)
    ok, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok:
        logger.error(f"[Debug][InsertAfter] Persist failed on {path}: {details}")
        return error_result('insert_after', path, 'syntax validation failed', output_format=output_format, Anchor=anchor_text, Occurrence=occurrence, TotalMatches=len(positions), ValidateCode=validate_code, **details)

    try:
        actual_content = p.read_text(encoding='utf-8')
        if actual_content != updated:
            logger.error(f"[Debug][InsertAfter] Post insert content mismatch detected on {path}")
            logger.debug(f"[Debug][InsertAfter] Actual content length {len(actual_content)}, expected {len(updated)}")
        else:
            logger.info(f"[Debug][InsertAfter] Insert verified for {path}")
    except Exception as e:
        logger.error(f"[Debug][InsertAfter] Error reading back {path} post insert: {e}")

    verified = verify_contains(path, content[: min(len(content), 120)]) if content else True
    extra = {}
    if structural.get('risk'):
        extra.update(structural)
    return success_result('insert_after', path, output_format=output_format, AnchorFound=True, Verified=verified, Occurrence=occurrence, TotalMatches=len(positions), Atomic=atomic, ValidateCode=validate_code, **extra)


def insert_before(path: str, anchor_text: str, content: str, occurrence: int = 1, strict_anchor: bool = False, atomic: bool = True, output_format: str = 'text', validate_code: bool = True, knowledge_engine=None):
    import logging
    logger = logging.getLogger("FileOpsInsertDebug")
    
    p = Path(path)
    if not p.exists():
        return error_result('insert_before', path, 'File not found', output_format=output_format)
    text = p.read_text(encoding='utf-8', errors='replace')
    positions = find_anchor_positions(text, anchor_text)
    if not positions:
        return error_result('insert_before', path, 'Anchor not found', output_format=output_format, Anchor=anchor_text)
    if strict_anchor and len(positions) > 1 and occurrence == 1:
        return error_result('insert_before', path, 'Anchor matched multiple times; specify occurrence', output_format=output_format, Anchor=anchor_text, TotalMatches=len(positions))
    if occurrence < 1 or occurrence > len(positions):
        return error_result('insert_before', path, 'Occurrence out of range', output_format=output_format, Anchor=anchor_text, TotalMatches=len(positions), RequestedOccurrence=occurrence)
    insert_at = positions[occurrence - 1]
    structural = assess_python_structural_anchor_risk(path, text, insert_at, content, position='before')
    
    # Find start of line containing anchor
    line_start = text.rfind(chr(10), 0, insert_at)
    if line_start >= 0:
        insert_at = line_start + 1
    else:
        insert_at = 0
    
    # Auto-insert newline if needed
    insert_content = content
    if insert_at > 0 and text[insert_at - 1] != chr(10):
        insert_content = chr(10) + content
    if content and content[-1] != chr(10):
        insert_content = insert_content + chr(10)
    
    updated = text[:insert_at] + insert_content + text[insert_at:]
    
    logger.info(f"[Debug][InsertBefore] Inserting into {path} at position {insert_at}, content length {len(insert_content)}")
    logger.debug(f"[Debug][InsertBefore] Insert content preview:\n{insert_content[:500]}")
    
    validation = validate_by_extension(path, updated, validate_code=validate_code)
    if not validation.get('ok'):
        details = {}
        if structural.get('risk'):
            details.update(structural)
        details.update(validation)
        logger.error(f"[Debug][InsertBefore] Syntax validation failed on {path}: {validation}")
        return error_result('insert_before', path, 'syntax validation failed', output_format=output_format, Anchor=anchor_text, Occurrence=occurrence, TotalMatches=len(positions), ValidateCode=validate_code, **details)
    ok, details = persist_text_file(path, updated, create_dirs=False, atomic=atomic, validate_code=False, knowledge_engine=knowledge_engine)
    if not ok:
        logger.error(f"[Debug][InsertBefore] Persist failed on {path}: {details}")
        return error_result('insert_before', path, 'syntax validation failed', output_format=output_format, Anchor=anchor_text, Occurrence=occurrence, TotalMatches=len(positions), ValidateCode=validate_code, **details)
    
    # 写入后读取文件对比
    try:
        actual_content = p.read_text(encoding='utf-8')
        if actual_content != updated:
            logger.error(f"[Debug][InsertBefore] Post insert content mismatch detected on {path}")
            logger.debug(f"[Debug][InsertBefore] Actual content length {len(actual_content)}, expected {len(updated)}")
        else:
            logger.info(f"[Debug][InsertBefore] Insert verified for {path}")
    except Exception as e:
        logger.error(f"[Debug][InsertBefore] Error reading back {path} post insert: {e}")
    
    verified = verify_contains(path, content[: min(len(content), 120)]) if content else True
    extra = {}
    if structural.get('risk'):
        extra.update(structural)
    return success_result('insert_before', path, output_format=output_format, AnchorFound=True, Verified=verified, Occurrence=occurrence, TotalMatches=len(positions), Atomic=atomic, ValidateCode=validate_code, **extra)
