"""Owner-input proposal: omit reviewed optional Qt features before collection.

Keep QtQml/Quick/WebEngine/Pdf and all unrelated QML input modules. The six
module families have no application use or retained native/QML incoming edge
in the reviewed macOS artifact. Re-audit those assertions after each build.
"""

from pathlib import Path
from unittest.mock import patch

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

_OPTIONAL_MODULES = (
    "QtGraphs",
    "QtCharts",
    "QtDataVisualization",
    "QtQuick3D",
    "QtQuick.Timeline",
    "QtQuick.VirtualKeyboard",
)
_OPTIONAL_PROFILERS = {
    "qmldbg_quick3dprofiler.dll",
    "qmldbg_quick3dprofilerd.dll",
    "libqmldbg_quick3dprofiler.so",
    "libqmldbg_quick3dprofiler.dylib",
}
_validate = pyside6_library_info._validate_plugin_dependencies
_process_qml_plugin = pyside6_library_info._process_qml_plugin


def _validate_owner_input(source):
    path = Path(source)
    if path.parent.name == "qmltooling" and path.name.lower() in _OPTIONAL_PROFILERS:
        return False, "Unused QtQuick3D profiler plugin input"
    return _validate(source)


def _process_owner_qml_input(qmldir_file):
    for line in qmldir_file.read_text(encoding="utf-8").splitlines():
        fields = line.strip().split()
        if len(fields) == 2 and fields[0] == "module":
            module = fields[1]
            if any(
                module == root or module.startswith(root + ".")
                for root in _OPTIONAL_MODULES
            ):
                return [], []
            break
    return _process_qml_plugin(qmldir_file)


# Both the qmltooling profiler and the QML URI trees are independent inputs.
# Scope the interception to this hook and restore the shared collector on exit.
with (
    patch.object(
        pyside6_library_info, "_validate_plugin_dependencies", _validate_owner_input
    ),
    patch.object(pyside6_library_info, "_process_qml_plugin", _process_owner_qml_input),
):
    hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
    qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
binaries += qml_binaries
datas += qml_datas
