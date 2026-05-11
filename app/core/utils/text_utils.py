import logging

from app.core.logging import get_logger

logger = get_logger("app.core.text_utils", side="core")


def is_test_log(text):
    s = (text or '').strip()
    return (
        s.startswith('[测试日志]') or s.startswith('[TestLog]')
        or 'test session starts' in s
        or 'collecting' in s or 'collected ' in s
        or 'tests/' in s
        or ' PASSED' in s or ' FAILED' in s
        or 'short test summary info' in s
        or 'Coverage HTML written' in s or 'Coverage JSON written' in s
        or 'coverage:' in s
    )
