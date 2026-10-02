import ast
import json
import logging
import os
from pathlib import Path


def validate_python_syntax(content: str, filename: str = "<file-ops-validator>") -> dict:
    # 剥掉 BOM，避免 ast.parse 报 invalid non-printable character U+FEFF
    content = content.lstrip("﻿")
    logger = logging.getLogger("FileOpsValidateDebug")

    logger.debug(f"[Debug][ValidatePython] Validating Python content, length={len(content)}")
    logger.debug(f"[Debug][ValidatePython] Content preview:\n{content[:500]}")

    try:
        ast.parse(content, filename=filename)
    except SyntaxError as e:
        logger.warning(f"[Debug][ValidatePython] ast.parse failed: {e}")
        return {
            'ok': False,
            'language': 'python',
            'line': getattr(e, 'lineno', None),
            'column': getattr(e, 'offset', None),
            'error': str(e),
        }

    try:
        compile(content, filename, "exec")
        logger.info("[Debug][ValidatePython] Python syntax validation passed")
        return {'ok': True, 'language': 'python'}
    except SyntaxError as syntax_err:
        logger.error(f"[Debug][ValidatePython] compile error: {syntax_err}")
        return {
            'ok': False,
            'language': 'python',
            'line': getattr(syntax_err, 'lineno', None),
            'column': getattr(syntax_err, 'offset', None),
            'error': str(syntax_err),
        }
    except Exception as ex:
        logger.error(f"[Debug][ValidatePython] compile unexpected error: {ex}")
        return {'ok': False, 'language': 'python', 'error': str(ex)}


def validate_json_syntax(content: str) -> dict:
    try:
        json.loads(content)
        return {'ok': True, 'language': 'json'}
    except Exception as e:
        return {'ok': False, 'language': 'json', 'error': str(e)}


def validate_toml_syntax(content: str) -> dict:
    try:
        import tomllib
        tomllib.loads(content)
        return {'ok': True, 'language': 'toml'}
    except Exception as e:
        return {'ok': False, 'language': 'toml', 'error': str(e)}


def validate_by_extension(path: str, content: str, validate_code: bool = True) -> dict:
    if not validate_code:
        return {'ok': True, 'language': None, 'skipped': True}
    suffix = Path(path).suffix.lower()
    if suffix == '.py':
        return validate_python_syntax(content, path)
    if suffix == '.json':
        return validate_json_syntax(content)
    if suffix == '.toml':
        return validate_toml_syntax(content)
    return {'ok': True, 'language': None, 'skipped': True}
