def _line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _non_empty_line_count(text: str) -> int:
    if not text:
        return 0
    return sum(1 for line in text.splitlines() if line.strip())


def _non_whitespace_chars(text: str) -> int:
    if not text:
        return 0
    return sum(1 for ch in text if not ch.isspace())


def assess_delete_risk(original_text: str, new_text: str) -> dict:
    original_lines = _line_count(original_text)
    remaining_lines = _line_count(new_text)
    deleted_lines = max(0, original_lines - remaining_lines)
    deleted_ratio = (deleted_lines / original_lines) if original_lines > 0 else 0.0

    original_non_empty = _non_empty_line_count(original_text)
    remaining_non_empty = _non_empty_line_count(new_text)
    non_empty_ratio = (remaining_non_empty / original_non_empty) if original_non_empty > 0 else 1.0

    original_non_ws = _non_whitespace_chars(original_text)
    remaining_non_ws = _non_whitespace_chars(new_text)
    non_ws_ratio = (remaining_non_ws / original_non_ws) if original_non_ws > 0 else 1.0

    whitespace_only_result = bool(new_text) and not new_text.strip()
    content_collapse = False

    if original_lines <= 2:
        near_empty = remaining_lines == 0
        large_delete = deleted_ratio > 0.8 and deleted_lines > 0
        extreme_delete = remaining_lines == 0
    elif original_lines <= 10:
        near_empty = remaining_lines <= 1
        large_delete = deleted_ratio > 0.6 or deleted_lines >= 4
        extreme_delete = deleted_ratio > 0.85 or remaining_lines == 0
    elif original_lines <= 50:
        near_empty = remaining_lines <= 3 or (remaining_lines / max(1, original_lines) < 0.15)
        large_delete = deleted_ratio > 0.4 or deleted_lines >= 15
        extreme_delete = deleted_ratio > 0.85 or remaining_lines <= 2
    else:
        near_empty = remaining_lines < 20 or (remaining_lines / max(1, original_lines) < 0.2)
        large_delete = deleted_ratio > 0.3 or deleted_lines > 80 or remaining_lines < 20
        extreme_delete = deleted_ratio > 0.8 or remaining_lines <= 5

    if whitespace_only_result:
        content_collapse = True
    elif original_non_empty >= 20 and remaining_non_empty <= max(3, int(original_non_empty * 0.1)):
        content_collapse = True
    elif original_non_ws >= 200 and remaining_non_ws <= max(20, int(original_non_ws * 0.1)):
        content_collapse = True
    elif original_lines >= 200 and (non_empty_ratio < 0.15 or non_ws_ratio < 0.1):
        content_collapse = True

    risk_level = 'low'
    if large_delete or content_collapse:
        risk_level = 'high'
    if extreme_delete or whitespace_only_result:
        risk_level = 'critical'

    return {
        'OriginalLines': original_lines,
        'RemainingLines': remaining_lines,
        'DeletedLines': deleted_lines,
        'DeletedRatio': round(deleted_ratio, 4),
        'OriginalNonEmptyLines': original_non_empty,
        'RemainingNonEmptyLines': remaining_non_empty,
        'NonEmptyRetentionRatio': round(non_empty_ratio, 4),
        'OriginalNonWhitespaceChars': original_non_ws,
        'RemainingNonWhitespaceChars': remaining_non_ws,
        'NonWhitespaceRetentionRatio': round(non_ws_ratio, 4),
        'NearEmptyAfterDelete': near_empty,
        'IsLargeDelete': large_delete,
        'IsExtremeDelete': extreme_delete,
        'WhitespaceOnlyResult': whitespace_only_result,
        'ContentCollapseDetected': content_collapse,
        'RiskLevel': risk_level,
    }


def guard_delete_risk(original_text: str, new_text: str, confirm_large_delete: bool = False, allow_near_empty_result: bool = False):
    risk = assess_delete_risk(original_text, new_text)
    if risk['ContentCollapseDetected'] and not confirm_large_delete:
        return False, 'Content collapse blocked', risk
    if risk['IsLargeDelete'] and not confirm_large_delete:
        return False, 'High-risk delete', risk
    if risk['NearEmptyAfterDelete'] and not allow_near_empty_result:
        return False, 'Near-empty result blocked', risk
    if risk['WhitespaceOnlyResult'] and not allow_near_empty_result:
        return False, 'Whitespace-only result blocked', risk
    return True, None, risk
