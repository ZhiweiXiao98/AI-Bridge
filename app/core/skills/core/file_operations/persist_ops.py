from pathlib import Path
import logging
from .path_utils import ensure_parent_dir, atomic_write_text
from .validators import validate_by_extension

logger = logging.getLogger("FileOperationsPersist")









def persist_text_file(path: str, content: str, *, create_dirs: bool = True, atomic: bool = True, validate_code: bool = True, knowledge_engine=None):
    import hashlib
    if create_dirs:
        ensure_parent_dir(path)
    
    content_hash_before = hashlib.md5(content.encode('utf-8')).hexdigest()
    logger.debug(f"[Debug][PersistFile] Content hash before validation: {content_hash_before[:16]}... (len={len(content)})")
    
    validation = validate_by_extension(path, content, validate_code=validate_code)
    if not validation.get('ok'):
        logger.error(f"[Debug][PersistFile] Validation failed for {path}: {validation}")
        logger.debug(f"[Debug][PersistFile] Content preview at validation failure:\n{content[:500]}")
        return False, validation
    
    p = Path(path)
    if atomic:
        logger.debug(f"[Debug][PersistFile] Using atomic write for {path}")
        atomic_write_text(path, content)
    else:
        logger.debug(f"[Debug][PersistFile] Using direct write for {path}")
        p.write_text(content, encoding='utf-8')
    
    # 写入后立即读取验证
    try:
        written_content = p.read_text(encoding='utf-8')
        written_hash = hashlib.md5(written_content.encode('utf-8')).hexdigest()
        logger.debug(f"[Debug][PersistFile] Content hash after write: {written_hash[:16]}... (len={len(written_content)})")
        if written_hash != content_hash_before:
            logger.error(f"[Debug][PersistFile] Hash mismatch after write on {path}")
            logger.debug(f"[Debug][PersistFile] Written content preview:\n{written_content[:500]}")
        else:
            logger.info(f"[Debug][PersistFile] Write integrity verified for {path}")
    except Exception as e:
        logger.error(f"[Debug][PersistFile] Error verifying write on {path}: {e}")
    
    return True, {"ok": True, "Atomic": atomic, "ValidateCode": validate_code}
