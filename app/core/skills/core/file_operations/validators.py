import ast
import json
import logging
import os
import py_compile
import tempfile
from pathlib import Path


def validate_python_syntax(content: str) -> dict:
    logger = logging.getLogger("FileOpsValidateDebug")

    logger.debug(f"[Debug][ValidatePython] Validating Python content, length={len(content)}")
    logger.debug(f"[Debug][ValidatePython] Content preview:\n{content[:500]}")

    try:
        ast.parse(content)
    except SyntaxError as e:
        logger.warning(f"[Debug][ValidatePython] ast.parse failed: {e}")
        return {
            'ok': False,
            'language': 'python',
            'line': getattr(e, 'lineno', None),
            'column': getattr(e, 'offset', None),
            'error': str(e),
        }

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8') as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            temp_path = tmp_file.name
        py_compile.compile(temp_path, doraise=True)
        logger.info("[Debug][ValidatePython] Python syntax validation passed")
        return {'ok': True, 'language': 'python'}
    except py_compile.PyCompileError as py_err:
        logger.error(f"[Debug][ValidatePython] py_compile error: {py_err.msg}")
        return {
            'ok': False,
            'language': 'python',
            'error': py_err.msg,
            'temp_path': temp_path,
        }
    except Exception as ex:
        logger.error(f"[Debug][ValidatePython] py_compile unexpected error: {ex}")
        return {'ok': False, 'language': 'python', 'error': str(ex), 'temp_path': temp_path}
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.warning(e)


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
        return validate_python_syntax(content)
    if suffix == '.json':
        return validate_json_syntax(content)
    if suffix == '.toml':
        return validate_toml_syntax(content)
    return {'ok': True, 'language': None, 'skipped': True}
