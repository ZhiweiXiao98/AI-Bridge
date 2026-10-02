"""Fail closed on final inventory; never edit or delete a bundled file.

Input exclusions are scoped separately in local_hooks. This gate catches a
removed optional family reintroduced by another dependency. Mach-O evidence
is Mac-specific; Windows filename coverage is not a Windows link audit.
"""

from __future__ import annotations

from pathlib import PurePosixPath
import re

OPTIONAL_QT_FAMILIES = (
    "QtGraphs",
    "QtCharts",
    "QtDataVisualization",
    "QtQuick3D",
    "QtQuickTimeline",
    "QtVirtualKeyboard",
)
OPTIONAL_QML_ROOTS = (
    "QtGraphs",
    "QtCharts",
    "QtDataVisualization",
    "QtQuick3D",
    "QtQuick/Timeline",
    "QtQuick/VirtualKeyboard",
)
REQUIRED_QT_LIBRARIES = {
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtQml",
    "QtQuick",
    "QtQuickWidgets",
    "QtWebEngineCore",
    "QtWebEngineWidgets",
    "QtPdf",
    "QtPdfQuick",
}
OPTIONAL_PLUGINS = {
    "platforminputcontexts": {"qtvirtualkeyboardplugin", "qtvirtualkeyboardplugind"},
    "qmltooling": {"qmldbg_quick3dprofiler", "qmldbg_quick3dprofilerd"},
}


def _stem(path: str) -> str:
    name = PurePosixPath(path.replace("\\", "/")).name
    if name.lower().startswith("lib"):
        name = name[3:]
    return name.split(".", 1)[0]


def _qt_library(path: str) -> str | None:
    name = PurePosixPath(path.replace("\\", "/")).name
    if "." in name and not re.search(r"\.(?:dll|pyd|dylib|so(?:\.\d+)*)$", name, re.I):
        return None
    name = _stem(path)
    if name.lower().startswith("qt6"):
        name = "Qt" + name[3:]
    if not re.fullmatch(r"Qt[A-Za-z0-9]+", name, re.I):
        return None
    return next(
        (item for item in REQUIRED_QT_LIBRARIES if item.lower() == name.lower()), name
    )


def _optional_family(name: str | None) -> bool:
    return bool(
        name
        and any(name.lower().startswith(root.lower()) for root in OPTIONAL_QT_FAMILIES)
    )


def forbidden_input_path(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if _optional_family(_qt_library(path)):
        return True
    if any(
        part.lower().endswith(".framework") and _optional_family(part[:-10])
        for part in parts
    ):
        return True
    for index, part in enumerate(parts):
        if part.lower() == "qml":
            tail = "/".join(parts[index + 1 :]).lower()
            if any(
                tail == root.lower() or tail.startswith(root.lower() + "/")
                for root in OPTIONAL_QML_ROOTS
            ):
                return True
    return len(parts) >= 2 and _stem(path).lower() in OPTIONAL_PLUGINS.get(
        parts[-2].lower(), ()
    )


def inspect_qt_inventory(inventory: dict, required_core: tuple[str, ...]) -> dict:
    """Validate actual inventory records for every generated bundle, not a allowlist projection."""
    violations = []
    records = inventory.get("files")
    bundles = inventory.get("bundles")
    platform = inventory.get("platform")
    name = inventory.get("name")
    if (
        not isinstance(records, list)
        or not records
        or not isinstance(bundles, list)
        or not bundles
    ):
        violations.append("Missing nonempty final files/bundles inventory")
        records, bundles = [], []
    if inventory.get("core_modules_missing") != []:
        violations.append("Core-module inventory is missing or reports a missing core")
    if platform not in {"darwin", "win32", "linux"} or name != "AI-Bridge-Local":
        violations.append("Unexpected platform or bundle identity")
    paths = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            violations.append("Malformed file inventory record")
            continue
        path = record["path"]
        parts = PurePosixPath(path).parts
        if not parts or path.startswith("/") or ".." in parts or "\\" in path:
            violations.append("Invalid relative inventory path")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
            violations.append("Missing file hash: " + path)
        paths.append(path)
        if forbidden_input_path(path):
            violations.append("Optional Qt input/framework reappeared: " + path)
        dependencies = record.get("mach_o_dependencies", [])
        if not isinstance(dependencies, list):
            violations.append("Malformed Mach-O dependencies: " + path)
            continue
        for dependency in dependencies:
            if not isinstance(dependency, dict) or not isinstance(
                dependency.get("install_name"), str
            ):
                violations.append("Malformed Mach-O dependency: " + path)
                continue
            if _optional_family(_qt_library(dependency["install_name"])):
                violations.append(
                    "Native dependency still targets optional Qt family: "
                    + path
                    + " -> "
                    + dependency["install_name"]
                )
    bundle_paths = []
    for bundle in bundles:
        if (
            not isinstance(bundle, dict)
            or not isinstance(bundle.get("path"), str)
            or not isinstance(bundle.get("pyz_modules"), list)
        ):
            violations.append("Malformed bundle/module inventory")
            continue
        if not all(isinstance(module, str) for module in bundle["pyz_modules"]):
            violations.append("Malformed PYZ module names")
            continue
        for module in bundle["pyz_modules"]:
            if module.startswith("PySide6.") and _optional_family(module.split(".")[1]):
                violations.append("Optional Qt Python module reappeared: " + module)
        bundle_path = bundle["path"]
        if bundle_path not in {"AI-Bridge-Local", "AI-Bridge-Local.app"}:
            violations.append("Unexpected bundle path: " + bundle_path)
            continue
        bundle_paths.append(bundle_path)
        prefix = bundle_path + "/"
        scoped = [
            r
            for r in records
            if isinstance(r, dict)
            and isinstance(r.get("path"), str)
            and r["path"].startswith(prefix)
        ]
        scoped_paths = [r["path"] for r in scoped]
        libraries = {_qt_library(p) for p in scoped_paths}
        for library in sorted(REQUIRED_QT_LIBRARIES - libraries):
            violations.append(
                "Required Qt library missing in " + bundle_path + ": " + library
            )
        for module in required_core:
            module_path = "/" + module.replace(".", "/") + "."
            if module not in bundle["pyz_modules"] and not any(
                module_path in p and re.search(r"\.(?:pyd|so|dylib)$", p)
                for p in scoped_paths
            ):
                violations.append(
                    "Required core missing in " + bundle_path + ": " + module
                )
        requirements = {
            "qpdf image decoder": lambda p: (
                PurePosixPath(p).parent.name == "imageformats"
                and _stem(p) == "qpdf"
                and bool(re.search(r"\.(?:dll|dylib|so)$", p))
            ),
            "Pdf QML module": lambda p: p.endswith("/qml/QtQuick/Pdf/qmldir"),
            "Pdf QML plugin": lambda p: (
                "/qml/QtQuick/Pdf/" in p
                and _stem(p) == "pdfquickplugin"
                and bool(re.search(r"\.(?:dll|dylib|so)$", p))
            ),
            "WebEngine helper": lambda p: (
                PurePosixPath(p).name
                in {"QtWebEngineProcess", "QtWebEngineProcess.exe"}
            ),
            "WebEngine resources": lambda p: (
                PurePosixPath(p).name == "qtwebengine_resources.pak"
            ),
        }
        for label, predicate in requirements.items():
            if not any(predicate(p) for p in scoped_paths):
                violations.append("Required " + label + " missing in " + bundle_path)
        if platform == "darwin":
            covered = {
                _qt_library(r["path"])
                for r in scoped
                if isinstance(r.get("mach_o_dependencies"), list)
                and r["mach_o_dependencies"]
            }
            for library in sorted(REQUIRED_QT_LIBRARIES - covered):
                violations.append(
                    "Missing recorded Mach-O evidence in "
                    + bundle_path
                    + ": "
                    + library
                )
    expected_bundles = (
        {"AI-Bridge-Local", "AI-Bridge-Local.app"}
        if platform == "darwin"
        else {"AI-Bridge-Local"}
    )
    if set(bundle_paths) != expected_bundles or len(bundle_paths) != len(
        set(bundle_paths)
    ):
        violations.append("Missing, duplicate or unexpected final bundle scope")
    if any(not any(p.startswith(b + "/") for b in bundle_paths) for p in paths):
        violations.append("File inventory contains paths outside declared bundles")
    return {
        "schema_version": 1,
        "passed": not violations,
        "violations": sorted(set(violations)),
        "checked_bundles": bundle_paths,
        "optional_framework_families": list(OPTIONAL_QT_FAMILIES),
        "optional_qml_roots": list(OPTIONAL_QML_ROOTS),
        "required_qt_libraries": sorted(REQUIRED_QT_LIBRARIES),
        "native_dependency_evidence": "recorded Mach-O edges"
        if platform == "darwin"
        else "not a target-platform native dependency audit",
        "runtime_acceptance_required": True,
        "license_clearance": False,
    }


def require_qt_inventory(inventory: dict, required_core: tuple[str, ...]) -> None:
    report = inspect_qt_inventory(inventory, required_core)
    inventory["qt_input_policy"] = report
    if not report["passed"]:
        raise RuntimeError(
            "Final Qt inventory policy failed; do not delete output files to repair it: "
            + "; ".join(report["violations"][:12])
        )
