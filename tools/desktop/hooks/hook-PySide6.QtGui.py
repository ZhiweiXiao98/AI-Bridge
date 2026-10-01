"""Keep unused GPL-option Qt plugins out before native dependency traversal."""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# These optional QtGui plugins drag in QtPdf and QtVirtualKeyboard (and QML/
# Quick) although this Widgets-only remote client imports none of those APIs.
# This filters plugin INPUTS, not libraries after linking; missing dependencies
# are not papered over by deleting arbitrary binaries from the finished app.
binaries = [
    (source, destination)
    for source, destination in binaries
    if not Path(source).name.lower().startswith(("qpdf.", "libqpdf.",
                                                 "qtvirtualkeyboardplugin.",
                                                 "libqtvirtualkeyboardplugin."))
]
