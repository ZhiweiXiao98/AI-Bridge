import warnings

from app.core.skills.core.file_operations.validators import validate_python_syntax


def test_validate_python_syntax_attributes_invalid_escape_warnings_to_file():
    code = 'pattern = "\\("\nnumber = "\\d+"\n'

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = validate_python_syntax(code, "sample_from_tool.py")

    assert result["ok"] is True
    invalid_escape_warnings = [
        warning
        for warning in caught
        if issubclass(warning.category, SyntaxWarning)
        and "invalid escape sequence" in str(warning.message)
    ]
    assert invalid_escape_warnings
    assert {warning.filename for warning in invalid_escape_warnings} == {"sample_from_tool.py"}
