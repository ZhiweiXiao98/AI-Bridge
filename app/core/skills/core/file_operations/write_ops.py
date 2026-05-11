from pathlib import Path
from .path_utils import ensure_parent_dir
from .result_utils import success_result, error_result, summarize_text, verify_contains, confirmation_required_result
from .persist_ops import persist_text_file
from .safety_ops import guard_delete_risk


def write_file(path: str, content: str, create_dirs: bool = True, overwrite: bool = True, atomic: bool = True, output_format: str = 'text', validate_code: bool = True, knowledge_engine=None):
    import logging
    logger = logging.getLogger("FileOpsWriteDebug")

    p = Path(path)
    if p.exists() and not overwrite:
        return error_result('write_file', path, 'File exists and overwrite is False', output_format=output_format)

    if p.exists():
        existing = p.read_text(encoding='utf-8', errors='replace')
        ok_guard, reason, risk = guard_delete_risk(existing, content, confirm_large_delete=False, allow_near_empty_result=False)
        if not ok_guard:
            logger.warning(f"[Debug][WriteFile] Blocked by safety guard on {path}: {reason} | risk={risk}")
            return confirmation_required_result('write_file', path, reason, output_format=output_format, BlockedBySafetyGuard=True, Overwrite=overwrite, **risk)

    logger.info(f"[Debug][WriteFile] Writing to {path} with content length {len(content)}")
    logger.debug(f"[Debug][WriteFile] Write content preview:\n{content[:500]}")

    ok, details = persist_text_file(path, content, create_dirs=create_dirs, atomic=atomic, validate_code=validate_code, knowledge_engine=knowledge_engine)
    if not ok:
        logger.error(f"[Debug][WriteFile] Syntax validation failed on {path}: {details}")
        return error_result('write_file', path, 'syntax validation failed', output_format=output_format, **details)

    try:
        actual_content = p.read_text(encoding='utf-8')
        if actual_content != content:
            logger.error(f"[Debug][WriteFile] Post write content mismatch detected on {path}")
            logger.debug(f"[Debug][WriteFile] Actual content preview:\n{actual_content[:500]}")
        else:
            logger.info(f"[Debug][WriteFile] Write verified for {path}")
    except Exception as e:
        logger.error(f"[Debug][WriteFile] Error reading back {path} post write: {e}")

    meta = summarize_text(content)
    verified = verify_contains(path, content[: min(len(content), 120)]) if content else True
    return success_result('write_file', path, output_format=output_format, Bytes=meta['Bytes'], Lines=meta['Lines'], Verified=verified, Atomic=atomic, ValidateCode=validate_code)


def append_file(path: str, content: str, ensure_newline: bool = True, create_dirs: bool = True, output_format: str = 'text', allow_duplicate_append: bool = False, atomic: bool = True, validate_code: bool = True, knowledge_engine=None):
    import logging
    logger = logging.getLogger("FileOpsAppendDebug")

    p = Path(path)
    if create_dirs:
        ensure_parent_dir(path)

    existing = ''
    if p.exists():
        existing = p.read_text(encoding='utf-8', errors='replace')
        if content and (content in existing) and not allow_duplicate_append:
            return error_result(
                'append_file',
                path,
                'Identical content already exists in file; append blocked by duplicate guard. Pass allow_duplicate_append=True to force append.',
                output_format=output_format,
            )

    prefix = ''
    if existing and ensure_newline and not existing.endswith(chr(10)):
        prefix = chr(10)
    append_text = prefix + content
    final_text = existing + append_text

    logger.info(f"[Debug][AppendFile] Appending to {path}, append_text length {len(append_text)}, final_text length {len(final_text)}")
    logger.debug(f"[Debug][AppendFile] Append content preview:\n{append_text[:500]}")

    ok, details = persist_text_file(path, final_text, create_dirs=create_dirs, atomic=atomic, validate_code=validate_code, knowledge_engine=knowledge_engine)
    if not ok:
        logger.error(f"[Debug][AppendFile] Syntax validation failed on {path}: {details}")
        return error_result('append_file', path, 'syntax validation failed', output_format=output_format, **details)

    try:
        actual_content = p.read_text(encoding='utf-8')
        if actual_content != final_text:
            logger.error(f"[Debug][AppendFile] Post append content mismatch detected on {path}")
            logger.debug(f"[Debug][AppendFile] Actual content length {len(actual_content)}, expected {len(final_text)}")
        else:
            logger.info(f"[Debug][AppendFile] Append verified for {path}")
    except Exception as e:
        logger.error(f"[Debug][AppendFile] Error reading back {path} post append: {e}")

    verified = verify_contains(path, content[: min(len(content), 120)]) if content else True
    meta = summarize_text(append_text)
    return success_result('append_file', path, output_format=output_format, Bytes=meta['Bytes'], Lines=meta['Lines'], Verified=verified, DuplicateGuardTriggered=False, AllowDuplicateAppend=allow_duplicate_append, Atomic=atomic, ValidateCode=validate_code)
