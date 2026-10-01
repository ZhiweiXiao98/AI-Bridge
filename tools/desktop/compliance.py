"""生成可核验的许可材料与实际冻结产物清单；本工具不批准二进制发行。"""
from __future__ import annotations

import ast
import base64
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from urllib.parse import urlsplit, urlunsplit
import zipfile

NAME = "AI-Bridge-Remote"
NOTICE_DIR = "THIRD_PARTY_NOTICES"
# 仅收集此隔离构建环境中的明确依赖；不复制任意已安装工具或用户文件。
BUILD_DISTRIBUTIONS = {
    "pyside6", "pyside6-addons", "pyside6-essentials", "shiboken6", "requests",
    "tiktoken", "pyyaml", "certifi", "charset-normalizer", "idna", "regex",
    "urllib3", "pyinstaller", "pyinstaller-hooks-contrib", "packaging",
    "setuptools", "altgraph", "pefile", "pywin32-ctypes", "macholib",
}
NOTICE_NAME = re.compile(r"^(licen[cs]e|copying|notice|copyright|authors)(?:\.(?:txt|md|rst|apache|bsd|mit)|-(?:apache|bsd|mit|2\.0))?$", re.I)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PRIVATE_PATH = re.compile(
    r"(^|/)(\.env(?:\..*)?|.*\.(?:db|sqlite|sqlite3|pem|key|p12|pfx)|"
    r"logs?|browser[_-]?profiles?|user[_-]?data|knowledge_bases|chroma(?:db)?|"
    r"credentials\.json|token\.json|config\.json)(/|$)", re.I)


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def json_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_relative(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    return bool(value) and not path.is_absolute() and ".." not in path.parts and ":" not in value


def public_url(value: str) -> str | None:
    """不把安装报告的私有索引、令牌或本地路径带入公开清单。"""
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname not in {"files.pythonhosted.org", "pypi.org"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def install_records(path: Path) -> dict:
    if not path.is_file():
        return {}
    result = {}
    for item in json.loads(path.read_text(encoding="utf-8")).get("install", []):
        info, download = item.get("metadata", {}), item.get("download_info", {})
        name = normalized(info.get("name", ""))
        url = public_url(download.get("url", ""))
        sha = download.get("archive_info", {}).get("hashes", {}).get("sha256", "")
        if name in BUILD_DISTRIBUTIONS and url and SHA256.fullmatch(sha):
            result[name] = {"version": info.get("version"), "url": url,
                            "filename": PurePosixPath(urlsplit(url).path).name, "sha256": sha}
    return result


def distributions() -> dict:
    result = {}
    for dist in metadata.distributions():
        name = normalized(dist.metadata.get("Name", ""))
        if name in BUILD_DISTRIBUTIONS:
            if name in result:
                raise ValueError(f"构建环境出现重复 distribution: {name}")
            result[name] = dist
    return result


def prepare_notices(root: Path, output: Path) -> dict:
    """复制白名单许可文本，不复制 METADATA、源码、pyc 或任意 sbom 文件。"""
    target = output / "generated-notices"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    static = root / "licenses/desktop"
    policy = json.loads((static / "sources.json").read_text(encoding="utf-8"))
    for item in policy["notice_files"]:
        relative = item["path"]
        if not safe_relative(relative) or digest(static / relative) != item["sha256"]:
            raise ValueError("静态许可文件路径或校验和不匹配")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(static / relative, destination)
    shutil.copyfile(static / "sources.json", target / "sources.json")
    wheels = install_records(output / "install-report.json")
    sources = {normalized(item["name"]): item for item in
               json.loads((static / "python-sources.json").read_text(encoding="utf-8"))["records"]}
    records = {}
    for name, dist in sorted(distributions().items()):
        copies = []
        for member in sorted(dist.files or (), key=str):
            if not safe_relative(str(member)) or not NOTICE_NAME.match(member.name):
                continue
            source = Path(dist.locate_file(member))
            if not source.is_file() or source.stat().st_size > 2_000_000:
                continue
            # 明确禁止把名为 licenses 的 Python 包或二进制当作许可证。
            try:
                text = source.read_bytes().decode("utf-8")
            except UnicodeError:
                continue
            if "\x00" in text:
                continue
            relative = f"python/{name}-{dist.version}/{member.as_posix()}"
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copies.append({"path": relative, "sha256": digest(destination)})
        declared = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "未声明"
        record = {"name": dist.metadata["Name"], "version": dist.version,
                  "declared_license": declared, "notice_files": copies,
                  "role": "安装环境候选；实际是否随包分发见 desktop-inventory.json"}
        if name in wheels and wheels[name]["version"] == dist.version:
            record["wheel"] = wheels[name]
        if name in sources and sources[name]["version"] == dist.version:
            record["source"] = sources[name]
        if name in {"pyside6", "pyside6-addons", "pyside6-essentials", "shiboken6"}:
            record["license_route"] = "LGPL-3.0-only；见 Qt 说明；原生第三方组件仍须分别审查"
            record["notice_files"] += [item for item in policy["notice_files"]
                                       if item["path"] in {"LGPL-3.0-only.txt", "GPL-3.0-only.txt",
                                                           "PySide6-6.11.1-README.txt", "README.zh-CN.md"}]
        records[name] = record
    json_write(target / "python-packages.json", records)
    wheel_lines = [f"{name} @ {item['wheel']['url']} --hash=sha256:{item['wheel']['sha256']}"
                   for name, item in sorted(records.items()) if "wheel" in item]
    (target / "requirements-resolved.txt").write_text(
        "# 仅用于生成本清单的同一 OS/架构/Python ABI；缺项时不可宣称完整复现。\n"
        + "\n".join(wheel_lines) + "\n", encoding="utf-8")
    return records


def toc_entries(value):
    """PyInstaller TOC 是 Python 字面量；禁止 eval/执行其中内容。"""
    if isinstance(value, (list, tuple)):
        if (len(value) == 3 and all(isinstance(x, str) for x in value)
                and value[2] in {"PYMODULE", "PYMODULE-1", "PYMODULE-2", "PYSOURCE",
                                 "PYSOURCE-1", "PYSOURCE-2", "BINARY", "EXTENSION", "DATA", "EXECUTABLE"}):
            yield value
        else:
            for child in value:
                yield from toc_entries(child)


def read_toc(path: Path) -> list:
    return list(toc_entries(ast.literal_eval(path.read_text(encoding="utf-8"))))


def provenance_index() -> dict:
    index = {}
    for name, dist in distributions().items():
        for member in dist.files or ():
            if safe_relative(str(member)):
                owner = {"distribution": name, "version": dist.version, "path": member.as_posix()}
                if member.hash and member.hash.mode == "sha256":
                    owner["record_sha256"] = base64.urlsafe_b64decode(member.hash.value + "===").hex()
                index.setdefault(Path(dist.locate_file(member)).resolve(), []).append(owner)
    return index


def provenance(source: str, root: Path, index: dict) -> dict:
    path = Path(source).resolve()
    result = {"source_sha256": digest(path)} if path.is_file() else {}
    if path in index:
        result["owners"] = index[path]
    elif path.is_relative_to(root):
        result["project_path"] = path.relative_to(root).as_posix()
    elif path.is_relative_to(Path(sysconfig.get_path("stdlib")).resolve()) and "site-packages" not in path.parts:
        result["python_stdlib"] = path.relative_to(Path(sysconfig.get_path("stdlib")).resolve()).as_posix()
    else:
        result["unresolved_origin"] = path.name  # 不泄露 runner / 用户绝对路径。
    return result


def native_versions(path: Path) -> dict:
    """记录文件实际暴露的版本；不存在/解析失败不推测为 Qt 或 Python 版本。"""
    suffix = path.suffix.lower()
    if sys.platform == "win32" and suffix in {".exe", ".dll", ".pyd"}:
        try:
            import pefile
            pe = pefile.PE(str(path), fast_load=False)
            result = {}
            if getattr(pe, "VS_FIXEDFILEINFO", None):
                info = pe.VS_FIXEDFILEINFO[0]
                result["pe_file_version"] = ".".join(str(x) for x in (
                    info.FileVersionMS >> 16, info.FileVersionMS & 65535,
                    info.FileVersionLS >> 16, info.FileVersionLS & 65535))
            pe.close()
            return result or {"native_version_status": "PE 无版本资源"}
        except Exception:
            return {"native_version_status": "PE 版本解析失败"}
    if sys.platform == "darwin":
        with path.open("rb") as source:
            data = source.read(4)
        if data in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}:
            run = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, timeout=15)
            dependencies = []
            for line in run.stdout.splitlines()[1:]:
                match = re.match(r"\s*(.*?) \(compatibility version ([^,]+), current version ([^)]+)\)", line)
                if match:
                    name, compatible, current = match.groups()
                    if not name.startswith(("@", "/System/", "/usr/lib/")):
                        name = Path(name).name
                    dependencies.append({"install_name": name, "compatibility_version": compatible,
                                         "current_version": current})
            return {"mach_o_dependencies": dependencies, "native_version_status":
                    "Mach-O load-command 版本；不等于上游源码发行版本"}
    return {}


def archives(executable: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader
    reader = CArchiveReader(str(executable))
    pyz = [name for name, entry in reader.toc.items() if entry[-1] == "z"]
    if len(pyz) != 1:
        raise ValueError("冻结执行文件必须恰好包含一个可读 PYZ")
    nested = reader.open_embedded_archive(pyz[0])
    return {"pyz_modules": sorted(nested.toc), "carchive_members": sorted(reader.toc)}


def bundle_roots(output: Path) -> list[tuple[Path, Path]]:
    dist = output / "dist"
    roots = [(dist / NAME, dist / NAME / (NAME + (".exe" if sys.platform == "win32" else "")))]
    if sys.platform == "darwin":
        roots.append((dist / f"{NAME}.app", dist / f"{NAME}.app/Contents/MacOS/{NAME}"))
    return roots


def verify_notices(bundle: Path, generated: Path) -> None:
    # macOS 的 Resources 与 Frameworks symlink 不改变内容，均按实际打包文件验证。
    locations = [bundle / "_internal" / NOTICE_DIR, bundle / "Contents/Resources" / NOTICE_DIR]
    present = [path for path in locations if path.is_dir()]
    if not present:
        raise ValueError("产物中缺少可见的第三方许可证目录")
    for original in generated.rglob("*"):
        if original.is_file():
            relative = original.relative_to(generated)
            if not any((directory / relative).is_file() and digest(directory / relative) == digest(original)
                       for directory in present):
                raise ValueError(f"产物许可文本丢失或被改写: {relative}")



def verified_ca_bundle(record: dict) -> bool:
    """certifi 公共根证书是应用必需数据；仅豁免与安装 RECORD 哈希匹配的确切文件。"""
    return any(owner.get("distribution") == "certifi"
               and owner.get("path") == "certifi/cacert.pem"
               and owner.get("record_sha256") == record.get("sha256")
               and bool(record.get("sha256")) for owner in record.get("owners", []))

def collect_inventory(root: Path, output: Path, prepared: dict) -> dict:
    root = root.resolve()
    work = output / "work" / NAME
    index = provenance_index()
    entries = read_toc(work / "Analysis-00.toc") + read_toc(work / "COLLECT-00.toc")
    pure = {name: source for name, source, kind in read_toc(work / "PYZ-00.toc")}
    native = [(name.replace("\\", "/"), source, kind) for name, source, kind in entries
              if kind in {"BINARY", "EXTENSION", "DATA"}]
    modules = []
    bundle_records = []
    for bundle, executable in bundle_roots(output):
        verify_notices(bundle, output / "generated-notices")
        archive = archives(executable)
        bundle_records.append({"path": bundle.relative_to(output / "dist").as_posix(), **archive})
    if any(x["pyz_modules"] != bundle_records[0]["pyz_modules"] for x in bundle_records[1:]):
        raise ValueError("同一构建的 onedir 与 app PYZ 成员不一致")
    for name in bundle_records[0]["pyz_modules"]:
        origin = provenance(pure[name], root, index) if name in pure else {"unresolved_origin": name}
        modules.append({"module": name, **origin})
    files, zip_members, unresolved = [], [], []
    shipped = {"pyinstaller"}  # 实际冻结引导器和运行时代码，无论是否在 PYZ。
    for item in modules:
        shipped.update(owner["distribution"] for owner in item.get("owners", []))
        if "unresolved_origin" in item:
            unresolved.append("PYZ:" + item["module"])
    for path in sorted((output / "dist").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output / "dist").as_posix()
        record = {"path": relative, "size": path.stat().st_size, "sha256": digest(path)}
        candidates = [(name, source, kind) for name, source, kind in native
                      if relative.endswith("/" + name)]
        if candidates:
            # 选择最长匹配；同一目标若有多个不同源则明确标记冲突。
            length = max(len(item[0]) for item in candidates)
            choices = {source for name, source, kind in candidates if len(name) == length}
            if len(choices) == 1:
                record.update(provenance(choices.pop(), root, index))
                shipped.update(owner["distribution"] for owner in record.get("owners", []))
            else:
                record["unresolved_origin"] = "多个 TOC 来源"
        elif NOTICE_DIR not in relative and path.name != NAME and path.suffix != ".exe":
            record["unresolved_origin"] = path.name
        versions = native_versions(path)
        record.update(versions)
        if "unresolved_origin" in record:
            unresolved.append(relative)
        files.append(record)
        if path.name == "base_library.zip":
            with zipfile.ZipFile(path) as archive:
                zip_members.append({"path": relative, "members": sorted(archive.namelist()),
                                    "sha256": digest(path)})
    findings = [record["path"] for record in files if PRIVATE_PATH.search(record["path"])
                and not verified_ca_bundle(record)]
    findings += ["base_library.zip:" + name for archive in zip_members for name in archive["members"]
                 if PRIVATE_PATH.search(name)]
    if findings:
        raise ValueError("产物含禁用的运行数据/敏感路径；请本地检查，不上传其内容")
    actual = []
    for name in sorted(shipped):
        if name in prepared:
            item = dict(prepared[name])
            item["role"] = "实际文件/PYZ 所属 distribution" if name != "pyinstaller" else "冻结引导器/运行时代码"
            actual.append(item)
        else:
            unresolved.append("distribution:" + name)
    from PySide6.QtCore import QLibraryInfo, qVersion
    issues = ["原生库内嵌第三方组件、Qt 翻译/codec、OpenSSL 两套来源及平台再分发权限仍需逐项核验",
              "Windows x64 / macOS ARM64 / macOS x64 的修改库重新组合测试尚未验收",
              "最终发行归档的隐私/许可复核及源码可取得性仍须确认"]
    missing_notices = [item["name"] for item in actual if not item["notice_files"]]
    missing_wheels = [item["name"] for item in actual if "wheel" not in item]
    if missing_notices:
        issues.append("缺少许可文本: " + ", ".join(missing_notices))
    if missing_wheels:
        issues.append("缺少本次 wheel 下载证明: " + ", ".join(missing_wheels))
    if platform.python_version() != "3.12.10":
        issues.append("当前 Python 与已保留的 3.12.10 源码许可证版本不一致")
    recipe = ["boot_remote.py", "requirements-desktop-build.txt", "tools/desktop/build.py",
              "tools/desktop/compliance.py", "tools/desktop/runtime_hook.py",
              "tools/desktop/hooks/hook-PySide6.QtGui.py", ".github/workflows/desktop-build.yml"]
    source_commit = os.environ.get("GITHUB_SHA", "")
    source_commit = source_commit if re.fullmatch(r"[0-9a-f]{40}", source_commit) else None
    return {"schema_version": 2, "source_commit": source_commit,
            "entry_point": "boot_remote.py", "platform": sys.platform,
            "architecture": platform.machine(), "binary_distribution_approved": False,
            "repository_data": ["LICENSE"], "generated_data": [NOTICE_DIR],
            "runtime_build_environment": {"python": platform.python_version(), "qt": qVersion(),
                                          "qt_build": QLibraryInfo.build()},
            "dependencies": actual, "not_shipped_environment_packages": sorted(set(prepared) - shipped),
            "bundles": bundle_records, "pyz_modules": modules, "base_library_archives": zip_members,
            "files": files, "unresolved_origins": sorted(set(unresolved)),
            "release_blockers": issues, "privacy_path_findings": findings,
            "recipe_sha256": {name: digest(root / name) for name in recipe},
            "verification_limits": ["TOC 提供构建输入来源；签名/修补后的原生输出单独保留哈希",
                                    "wheel 元数据和包许可证不证明所有内嵌 C/C++ 第三方组件已覆盖",
                                    "路径检查及 archive 成员检查不是完整私密数据/安全审计"]}
