"""本地完整包的逐文件来源与许可证据；不使用远程客户端的缩减依赖白名单。"""
from __future__ import annotations

import base64
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import sys
import sysconfig
from urllib.parse import urlsplit
import zipfile

from compliance import archives, native_versions, read_toc, safe_relative
from local_build import CORE_MODULES, NAME, digest, write_json

LICENSE_NAME = re.compile(r"^(licen[cs]e|copying|notice|copyright|authors)(?:[._-].*)?$", re.I)
PRIVATE_BASENAME = re.compile(
    r"^(?:\.env(?:\..*)?|\.secret\.key|.*\.(?:db|sqlite|sqlite3|p12|pfx)|"
    r"credentials\.json|token\.json|config\.json|server_config\.json|session_states\.json)$", re.I)


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_distributions() -> dict:
    result = {}
    for dist in metadata.distributions():
        name = normalized(dist.metadata.get("Name", ""))
        if name == "pip":
            continue  # 构建安装器，不在冻结运行时中。
        if not name or name in result:
            raise ValueError("构建环境存在缺名或重复 distribution，请使用全新隔离 venv")
        result[name] = dist
    return result


def install_records(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("缺少本次安装报告；不得将日常 Python 环境当作可审核构建输入")
    records = {}
    for item in json.loads(path.read_text(encoding="utf-8")).get("install", []):
        info = item.get("metadata", {})
        download = item.get("download_info", {})
        url = download.get("url", "")
        parsed = urlsplit(url)
        sha = download.get("archive_info", {}).get("hashes", {}).get("sha256", "")
        if (parsed.scheme != "https" or parsed.hostname not in {"pypi.org", "files.pythonhosted.org"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not re.fullmatch(r"[0-9a-f]{64}", sha)):
            raise ValueError("安装报告存在非官方/含凭证来源或缺少 SHA-256；原始报告不可上传")
        records[normalized(info["name"])] = {"version": info["version"], "url": url,
                                              "sha256": sha, "filename": PurePosixPath(parsed.path).name}
    return records


def copy_text(source: Path, target: Path) -> bool:
    if not source.is_file() or source.stat().st_size > 10_000_000:
        return False
    try:
        data = source.read_bytes()
        if b"\x00" in data:
            return False
        data.decode("utf-8")
    except UnicodeError:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return True


def prepare_notices(root: Path, output: Path, node: dict, pi: dict) -> dict:
    target = output / "generated-notices"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    wheels = install_records(output / "install-report.json")
    candidates = installed_distributions()
    records = {}
    for name, dist in sorted(candidates.items()):
        if name not in wheels or wheels[name]["version"] != dist.version:
            raise ValueError(f"当前隔离环境与安装报告不符或缺少来源：{name}")
        copies = []
        declared_files = set(dist.metadata.get_all("License-File") or [])
        for member in sorted(dist.files or (), key=str):
            relative = str(member).replace("\\", "/")
            if not safe_relative(relative):
                continue
            if not (LICENSE_NAME.match(member.name) or relative in declared_files
                    or any(part.lower() in {"licenses", "licences"} for part in member.parts)
                    and member.suffix.lower() in {".txt", ".md", ".rst", ".html", ""}):
                continue
            destination = target / "python" / f"{name}-{dist.version}" / relative
            if copy_text(Path(dist.locate_file(member)), destination):
                copies.append({"path": destination.relative_to(target).as_posix(), "sha256": digest(destination)})
        records[name] = {"name": dist.metadata["Name"], "version": dist.version,
                         "declared_license": dist.metadata.get("License-Expression") or dist.metadata.get("License") or "未声明",
                         "notice_files": copies, "wheel": wheels[name],
                         "scope": "完整构建环境候选；是否实际随包分发由 TOC/PYZ 证据决定"}
    # 静态材料是既有 Qt/Python 的来源线索；本地完整 QtWebEngine 不能照搬远程履约结论。
    static = root / "licenses/desktop"
    policy = json.loads((static / "sources.json").read_text(encoding="utf-8"))
    for item in policy["notice_files"]:
        relative = item["path"]
        if not safe_relative(relative) or digest(static / relative) != item["sha256"]:
            raise ValueError("继承的 Qt/Python 许可材料完整性校验失败")
        destination = target / "qt-python-reference" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(static / relative, destination)
    for name in ("sources.json", "python-sources.json"):
        shutil.copyfile(static / name, target / "qt-python-reference" / name)
    shutil.copytree(root / "licenses/vendor", target / "vendored-assets", ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    shutil.copyfile(output / "resources/runtime/node/LICENSE", target / "Node-LICENSE.txt")
    npm_records = []
    pi_root = output / "resources/runtime/pi"
    for package in pi["packages"]:
        record = dict(package)
        package_root = pi_root / package["path"]
        copies = []
        for current, directories, files in os.walk(package_root):
            directories[:] = [name for name in directories if name != "node_modules"]
            for filename in files:
                if not LICENSE_NAME.match(filename):
                    continue
                source = Path(current) / filename
                relative = source.relative_to(package_root).as_posix()
                destination = target / "npm" / package["path"] / relative
                if copy_text(source, destination):
                    copies.append({"path": destination.relative_to(target).as_posix(), "sha256": digest(destination)})
        record["notice_files"] = copies
        npm_records.append(record)
    write_json(target / "python-packages.json", records)
    write_json(target / "npm-packages.json", npm_records)
    write_json(target / "node-source.json", node)
    (target / "requirements-resolved.txt").write_text(
        "# 本次目标平台/架构/ABI的完整安装集合，不能跨平台混用。\n" + "\n".join(
            f"{name} @ {item['wheel']['url']} --hash=sha256:{item['wheel']['sha256']}"
            for name, item in sorted(records.items())) + "\n", encoding="utf-8")
    (target / "完整本地包审查说明.txt").write_text(
        "此目录是许可审查材料，不是发行许可批准。\n"
        "本包包含本地 Worker、QtWebEngine/Chromium、Selenium、Docker SDK、Chroma/ONNX RAG、Pi SDK 与 Node。\n"
        "npm/轮子顶层许可证不能代替内嵌原生组件逐项许可和对应源码核验。\n"
        "QtPdf/QtVirtualKeyboard 等可能进入完整 Qt 依赖图，必须依据实际库存选择合规路线，不得套用远程包的排除结论。\n"
        "浏览器自动化仍需用户自己的浏览器，Docker 执行仍需用户自己的 Docker 引擎，RAG 模型首次使用可能联网下载。\n",
        encoding="utf-8")
    return {"python": records, "npm": npm_records}


def provenance_index(distributions: dict) -> dict:
    result = {}
    for name, dist in distributions.items():
        for member in dist.files or ():
            if not safe_relative(str(member)):
                continue
            owner = {"distribution": name, "version": dist.version, "path": member.as_posix()}
            if member.hash and member.hash.mode == "sha256":
                owner["record_sha256"] = base64.urlsafe_b64decode(member.hash.value + "===").hex()
            result.setdefault(Path(dist.locate_file(member)).resolve(), []).append(owner)
    return result


def provenance(source: str, root: Path, output: Path, index: dict, pi: dict) -> dict:
    path = Path(source).resolve()
    result = {"source_sha256": digest(path)} if path.is_file() else {}
    stage = output / "resources"
    if path in index:
        result["owners"] = index[path]
    elif path.is_relative_to(stage):
        relative = path.relative_to(stage).as_posix()
        result["staged_path"] = relative
        if relative.startswith("runtime/pi/node_modules/"):
            npm_path = relative[len("runtime/pi/"):]
            candidates = [item for item in pi["packages"] if npm_path.startswith(item["path"] + "/")]
            if candidates:
                owner = max(candidates, key=lambda item: len(item["path"]))
                result["npm_owner"] = {key: owner[key] for key in ("path", "name", "version", "integrity")}
            elif not ("/.bin/" in relative or relative.endswith("/.package-lock.json")):
                result["unresolved_origin"] = "npm 锁不能映射的安装文件"
        elif relative.startswith("runtime/node/"):
            result["node_official_archive"] = True
        else:
            result["project_resource"] = True
    elif path.is_relative_to(output / "generated-notices"):
        result["generated_notice"] = True
    elif path.is_relative_to(root) and not path.is_relative_to(output):
        result["project_path"] = path.relative_to(root).as_posix()
    elif path.is_relative_to(Path(sysconfig.get_path("stdlib")).resolve()) and "site-packages" not in path.parts:
        result["python_stdlib"] = path.relative_to(Path(sysconfig.get_path("stdlib"))).as_posix()
    else:
        result["unresolved_origin"] = path.name
    return result


def bundle_roots(output: Path) -> list[tuple[Path, Path]]:
    dist = output / "dist"
    bundles = [(dist / NAME, dist / NAME / (NAME + (".exe" if sys.platform == "win32" else "")))]
    if sys.platform == "darwin":
        bundles.append((dist / f"{NAME}.app", dist / f"{NAME}.app/Contents/MacOS/{NAME}"))
    return bundles


def verify_bundle_data(bundle: Path, output: Path) -> None:
    roots = [bundle / "_internal", bundle / "Contents/Resources", bundle / "Contents/Frameworks"]
    for original_root, prefix in ((output / "resources", ""), (output / "generated-notices", "THIRD_PARTY_NOTICES")):
        for original in original_root.rglob("*"):
            if not original.is_file():
                continue
            relative = Path(prefix) / original.relative_to(original_root)
            if not any((base / relative).is_file() and digest(base / relative) == digest(original) for base in roots):
                # macOS PyInstaller 可能修补并重签原生文件；其来源另由 TOC 和前后哈希跟踪。
                binary = original.read_bytes()[:4]
                if sys.platform == "darwin" and binary in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"}:
                    if any((base / relative).is_file() for base in roots):
                        continue
                raise ValueError(f"包内必要资源/许可文本缺失或被改写：{relative}")


def privacy_findings(files: list[dict]) -> list[str]:
    """私密数据禁令针对仓库/用户数据；经 RECORD/锁归属确认的包内同名资源不是用户配置。"""
    result = []
    for record in files:
        path = record["path"]
        sensitive = PRIVATE_BASENAME.match(PurePosixPath(path).name)
        sensitive = sensitive or any(part.lower() in {"chrome_user_data", "browser_profiles", "_knowledge_base", "_knowledge_base_v2"}
                                     for part in PurePosixPath(path).parts)
        if not sensitive or record.get("generated_notice") or "THIRD_PARTY_NOTICES/" in path:
            continue
        if record.get("npm_owner"):
            continue  # 来源是刚刚 npm ci 的受锁定上游树，而非任何用户目录。
        if any(owner.get("record_sha256") == record.get("source_sha256") for owner in record.get("owners", [])):
            continue
        result.append(path)
    return result


def native_toc_index(entries: list[tuple[str, str]]) -> dict:
    """按文件名缩小候选集合；仍保留后续完整路径后缀与最长匹配规则。"""
    result = {}
    for name, source in entries:
        result.setdefault(PurePosixPath(name).name, []).append((name, source))
    return result


def collect_inventory(root: Path, output: Path, prepared: dict, resources: list, node: dict, pi: dict) -> dict:
    work = output / "work" / NAME
    index = provenance_index(installed_distributions())
    entries = read_toc(work / "Analysis-00.toc") + read_toc(work / "COLLECT-00.toc")
    pure = {name: source for name, source, kind in read_toc(work / "PYZ-00.toc")}
    native = [(name.replace("\\", "/"), source) for name, source, kind in entries if kind in {"BINARY", "EXTENSION", "DATA"}]
    native_index = native_toc_index(native)
    bundles = []
    for bundle, executable in bundle_roots(output):
        verify_bundle_data(bundle, output)
        bundles.append({"path": bundle.relative_to(output / "dist").as_posix(), **archives(executable)})
    if any(item["pyz_modules"] != bundles[0]["pyz_modules"] for item in bundles[1:]):
        raise ValueError("同次构建的 app 和 onedir 模块集合不一致")
    modules = [{"module": name, **(provenance(pure[name], root, output, index, pi) if name in pure else {"unresolved_origin": name})}
               for name in bundles[0]["pyz_modules"]]
    files = []
    zip_members = []
    for path in sorted((output / "dist").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output / "dist").as_posix()
        record = {"path": relative, "size": path.stat().st_size, "sha256": digest(path)}
        matches = [(name, source) for name, source in native_index.get(path.name, ()) if relative.endswith("/" + name)]
        if matches:
            length = max(len(name) for name, _ in matches)
            sources = {source for name, source in matches if len(name) == length}
            if len(sources) == 1:
                record.update(provenance(sources.pop(), root, output, index, pi))
            else:
                record["unresolved_origin"] = "TOC 多个来源冲突"
        elif path.name not in {NAME, NAME + ".exe", "Info.plist", "PkgInfo"}:
            record["unresolved_origin"] = path.name
        record.update(native_versions(path))
        files.append(record)
        if path.name == "base_library.zip":
            with zipfile.ZipFile(path) as archive:
                zip_members.append({"path": relative, "members": sorted(archive.namelist()), "sha256": digest(path)})
    findings = privacy_findings(files)
    if findings:
        raise ValueError("产物含禁用的运行状态/敏感数据路径；请本地检查，禁止上传清单或文件")
    missing = [name for name in CORE_MODULES if name not in bundles[0]["pyz_modules"]
               and not any(name.replace(".", "/") in item["path"] or name.split(".")[-1] in PurePosixPath(item["path"]).name for item in files)]
    if missing:
        raise ValueError("本地核心缺失，不能降级为远程包：" + ", ".join(missing))
    shipped = {"pyinstaller"}
    for item in modules + files:
        shipped.update(owner["distribution"] for owner in item.get("owners", []))
    actual = [prepared["python"][name] for name in sorted(shipped) if name in prepared["python"]]
    unresolved = [item.get("path", item.get("module")) for item in modules + files if "unresolved_origin" in item]
    blockers = [
        "二进制发行未授权；仅允许上传指定审查 JSON，禁止上传 dist、node_modules、wheel 或源码归档",
        "QtWebEngine/Chromium 及完整 Qt 原生组件、QtPdf/QtVirtualKeyboard 的许可证路线、内嵌第三方和对应源码尚须逐项核验",
        "Node/V8/OpenSSL/libuv、ONNX Runtime、tokenizers、Chroma、Pi 内嵌包的原生组件及模型许可仍须独立审查",
        "Qt/PySide/Shiboken 在 Windows x64 与 macOS arm64 的可观察原生库替换及完整重新组合未验收",
        "模型不随包预置；首次下载对应的模型许可证/联网同意不能由软件许可证声明替代",
        "未完成系统签名/公证、最终归档隐私检查、全功能目标平台实机验收与对应源码留存",
    ]
    missing_python = [item["name"] for item in actual if not item["notice_files"]]
    missing_npm = [item["name"] for item in prepared["npm"] if not item["notice_files"]]
    if missing_python:
        blockers.append("缺少包内 Python 许可文本：" + ", ".join(missing_python))
    if missing_npm:
        blockers.append("缺少包内 npm 许可文本：" + ", ".join(missing_npm))
    if unresolved:
        blockers.append("存在无法唯一映射的原生/生成文件来源，须逐项核验")
    if platform.python_version() != "3.12.10":
        blockers.append("当前 CPython 版本与已有 3.12.10 许可材料不同，须取得实际版本材料")
    from PySide6.QtCore import QLibraryInfo, qVersion
    sha = os.environ.get("GITHUB_SHA", "")
    recipes = ["boot_local.py", "requirements-desktop-local-build.txt", "tools/desktop/local_build.py",
               "tools/desktop/local_compliance.py", "tools/desktop/local_runtime_hook.py", "tools/desktop/local_smoke.py",
               ".github/workflows/local-desktop-build.yml", "runtime/pi/package-lock.json",
               "licenses/local/node-sources.json", "licenses/local/npm-integrity.json"]
    return {"schema_version": 1, "name": NAME, "entry_point": "boot_local.py",
            "source_commit": sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None,
            "platform": sys.platform, "architecture": platform.machine(), "binary_distribution_approved": False,
            "runtime_build_environment": {"python": platform.python_version(), "qt": qVersion(), "qt_build": QLibraryInfo.build()},
            "repository_resources": resources, "node": node, "pi": pi,
            "dependencies": actual, "npm_dependencies": prepared["npm"],
            "not_shipped_environment_packages": sorted(set(prepared["python"]) - shipped),
            "bundles": bundles, "pyz_modules": modules, "files": files, "base_library_archives": zip_members,
            "core_modules_missing": missing, "privacy_path_findings": findings,
            "unresolved_origins": unresolved, "release_blockers": blockers,
            "recipe_sha256": {name: digest(root / name) for name in recipes},
            "verification_limits": ["TOC 与 RECORD 提供输入来源；签名/修补后的输出另存 SHA-256",
                                    "包顶层许可声明不证明所有内嵌原生组件或模型已合规",
                                    "路径扫描不能代替完整内容/恶意依赖审计"]}
