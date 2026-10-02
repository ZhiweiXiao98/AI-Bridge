"""Owner-input proposal: omit only the unused Qt virtual-keyboard entry point.

Keep qpdf: the app's QImage paths can decode PDF without a QtPdf Python import.
Do not alter linked libraries or the remaining QtGui platform/input plugins.
"""

from pathlib import Path
from unittest.mock import patch

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

_OPTIONAL_INPUTS = {
    "qtvirtualkeyboardplugin.dll",
    "qtvirtualkeyboardplugind.dll",
    "libqtvirtualkeyboardplugin.so",
    "libqtvirtualkeyboardplugin.dylib",
}
_validate = pyside6_library_info._validate_plugin_dependencies


def _validate_owner_input(source):
    path = Path(source)
    if (
        path.parent.name == "platforminputcontexts"
        and path.name.lower() in _OPTIONAL_INPUTS
    ):
        return False, "Unused owner-scope Qt virtual-keyboard plugin input"
    return _validate(source)


with patch.object(
    pyside6_library_info, "_validate_plugin_dependencies", _validate_owner_input
):
    hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
