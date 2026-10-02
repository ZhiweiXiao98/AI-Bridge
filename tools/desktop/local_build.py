"""构建本地完整客户端及审查证据；不上传、签名发行或创建 Release。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
NAME = "AI-Bridge-Local"
NODE_VERSION = "22.23.3"
PI_VERSION = "0.99.1"
# 只读的公开资源逐项列出；绝不复制仓库、config 或用户目录整体。
RESOURCE_FILES = (
    "LICENSE", "app/ui/styles.qss", "config/panel_layout_default.json",
    "assets/icons/chat.png", "assets/icons/draw.png", "assets/icons/music.png",
    "assets/icons/settings.png", "assets/icons/video.png",
    "lib/bindings/utils.js", "lib/tom-select/tom-select.complete.min.js",
    "lib/tom-select/tom-select.css", "lib/vis-9.1.2/vis-network.min.js",
    "lib/vis-9.1.2/vis-network.css",
)
PI_FILES = ("package.json", "package-lock.json", "sidecar.mjs", "protocol.mjs", "pi-session.mjs")
CORE_MODULES = (
    "app.core.worker", "app.core.agent_manager", "app.core.docker_manager",
    "app.core.knowledge.service", "app.core.services.knowledge_service",
    "app.core.services.file_service", "app.core.driver.factory",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "chromadb", "fastembed", "onnxruntime", "docker", "selenium",
)
# 懒加载/插件使用的代码、数据和原生库一并收集，失败不能用排除模块来掩盖。
COLLECT_ALL = (
    "chromadb", "fastembed", "onnxruntime", "tokenizers", "tiktoken_ext",
    "selenium", "webdriver_manager", "docker", "google.genai", "ddgs",
)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def configure_console() -> None:
    """Windows runner 的重定向输出可能默认 cp1252；所有中文 CLI 明确使用 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def public_resources(root: Path = ROOT) -> list[str]:
    """从 Git 跟踪文件中选取所需公开资源，忽略外部插件和本地生成文件。"""
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    selected = set(RESOURCE_FILES)
    for relative in tracked:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Git 资源路径非法")
        if (relative.startswith("app/core/skills/core/") and path.suffix in {".py", ".md"}
                or relative.startswith("plugins/panels/") and path.suffix in {".py", ".md"}
                or relative.startswith("plugins/panels/") and path.name == "plugin.json"
                or relative.startswith("Prompt/") and path.suffix == ".md"
                or relative.startswith("licenses/vendor/") and path.suffix != ".py"):
            selected.add(relative)
    for relative in selected:
        source = root / relative
        if relative not in tracked or not source.is_file() or source.is_symlink():
            raise ValueError(f"必要公开资源不存在、未跟踪或为链接：{relative}")
    return sorted(selected)


def node_target() -> tuple[str, str]:
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "darwin-arm64", "tar.gz"
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "win-x64", "zip"
    # Linux 仅供工程验证，不在默认发行目标之列。
    if sys.platform == "linux" and machine in {"amd64", "x86_64"}:
        return "linux-x64", "tar.gz"
    raise RuntimeError("当前目标不受支持；默认只构建 macOS arm64 与 Windows x64")


def download(url: str, destination: Path) -> None:
    # 所有调用点使用固定官方域和版本；不读取任意 URL/凭证。
    if not url.startswith(f"https://nodejs.org/dist/v{NODE_VERSION}/"):
        raise ValueError("Node 下载必须来自固定版本的官方站点")
    with urlopen(url, timeout=120) as response, destination.open("wb") as output:
        if not response.url.startswith(f"https://nodejs.org/dist/v{NODE_VERSION}/"):
            raise ValueError("Node 下载重定向到了非预期来源")
        shutil.copyfileobj(response, output)


def prepare_node(output: Path) -> dict:
    """仅提取官方 Node 可执行文件和许可文本，不带入全局 npm 或用户配置。"""
    target, extension = node_target()
    stem = f"node-v{NODE_VERSION}-{target}"
    filename = f"{stem}.{extension}"
    downloads = output / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / filename
    checksums = downloads / "SHASUMS256.txt"
    base = f"https://nodejs.org/dist/v{NODE_VERSION}/"
    download(base + "SHASUMS256.txt", checksums)
    matches = [line.split()[0] for line in checksums.read_text(encoding="utf-8").splitlines()
               if len(line.split()) == 2 and line.split()[1] == filename]
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0]):
        raise ValueError("官方 Node 校验清单缺少唯一目标项")
    if not archive.is_file() or digest(archive) != matches[0]:
        download(base + filename, archive)
    if digest(archive) != matches[0]:
        raise ValueError("Node 归档 SHA-256 与官方清单不符")
    locked = json.loads((ROOT / "licenses/local/node-sources.json").read_text(encoding="utf-8"))
    if locked["version"] != NODE_VERSION or locked["archives"][filename]["sha256"] != matches[0]:
        raise ValueError("Node 当前官方清单与已提交的固定哈希不符，必须停止并审查")
    node = output / "resources/runtime/node"
    node.mkdir(parents=True, exist_ok=True)
    binary_relative = "node.exe" if target.startswith("win") else "bin/node"
    for member in (binary_relative, "LICENSE"):
        destination = node / member
        destination.parent.mkdir(parents=True, exist_ok=True)
        archive_member = f"{stem}/{member}"
        if extension == "zip":
            with zipfile.ZipFile(archive) as source:
                data = source.read(archive_member)
        else:
            with tarfile.open(archive, "r:gz") as source:
                info = source.getmember(archive_member)
                if not info.isfile():
                    raise ValueError("Node 必要文件不是普通文件")
                handle = source.extractfile(info)
                if handle is None:
                    raise ValueError("Node 文件不可读取")
                data = handle.read()
        destination.write_bytes(data)
    executable = node / binary_relative
    executable.chmod(0o755)
    observed = subprocess.check_output([str(executable), "--version"], text=True, timeout=20).strip()
    if observed != "v" + NODE_VERSION:
        raise ValueError("随包 Node 的实际版本不符")
    npm_prefix = "node_modules/npm" if target.startswith("win") else "lib/node_modules/npm"
    archive_prefix = f"{stem}/{npm_prefix}/"
    npm_root = output / "build-tools/npm"
    if npm_root.exists():
        shutil.rmtree(npm_root)
    if extension == "zip":
        with zipfile.ZipFile(archive) as source:
            members = [(item.filename, source.read(item)) for item in source.infolist()
                       if item.filename.startswith(archive_prefix) and not item.is_dir()]
    else:
        with tarfile.open(archive, "r:gz") as source:
            members = []
            for item in source.getmembers():
                if item.name.startswith(archive_prefix) and item.isfile():
                    handle = source.extractfile(item)
                    if handle is not None:
                        members.append((item.name, handle.read()))
    for path, data in members:
        relative = PurePosixPath(path[len(archive_prefix):])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("官方 npm 归档含非法路径")
        destination = npm_root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    npm_version = subprocess.check_output([str(executable), str(npm_root / "bin/npm-cli.js"), "--version"], text=True, timeout=30).strip()
    return {"version": NODE_VERSION, "target": target, "archive_url": base + filename,
            "archive_sha256": matches[0], "checksums_url": base + "SHASUMS256.txt",
            "checksums_sha256": digest(checksums), "executable": f"runtime/node/{binary_relative}",
            "executable_sha256": digest(executable), "license_sha256": digest(node / "LICENSE"),
            "build_only_npm_version": npm_version,
            "source_url": base + f"node-v{NODE_VERSION}.tar.gz",
            "source_sha256": locked["archives"][f"node-v{NODE_VERSION}.tar.gz"]["sha256"],
            "verification_limit": "已与官方 HTTPS 校验清单比对；尚未核验发行者签名及内嵌组件对应源码"}


def validate_npm_lock(lock: dict, supplemental: dict | None = None) -> None:
    packages = lock.get("packages", {})
    if lock.get("lockfileVersion") != 3:
        raise ValueError("Pi 必须使用已提交的 lockfileVersion 3")
    sdk = packages.get("node_modules/@earendil-works/pi-coding-agent", {})
    if sdk.get("version") != PI_VERSION:
        raise ValueError("Pi 版本不得偏离已审查的 0.99.1")
    if supplemental is None:
        supplemental = json.loads((ROOT / "licenses/local/npm-integrity.json").read_text(encoding="utf-8"))["packages"]
    for name, item in packages.items():
        if not name:
            continue
        if (not name.startswith("node_modules/") or ".." in PurePosixPath(name).parts
                or not item.get("resolved", "").startswith("https://registry.npmjs.org/")
                or item.get("integrity") and not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", item["integrity"])):
            raise ValueError("Pi 锁含未允许的路径、来源或非法完整性值")
        if not item.get("integrity"):
            extra = supplemental.get(name, {})
            if (extra.get("version") != item["version"] or extra.get("url") != item["resolved"]
                    or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", extra.get("integrity", ""))):
                raise ValueError("Pi 原锁缺失完整性记录，且无匹配的已提交官方补充记录")


def verify_supplemental_package(output: Path, package_root: Path, record: dict) -> None:
    """原锁遗漏 integrity 的子包逐个验证官方归档与实际安装字节，不修改原锁。"""
    url = record["url"]
    if not url.startswith("https://registry.npmjs.org/"):
        raise ValueError("Pi 补充归档必须来自官方 npm registry")
    destination = output / "downloads" / (record["name"].replace("/", "-").replace("@", "") + ".tgz")
    with urlopen(url, timeout=120) as response:
        if not response.url.startswith("https://registry.npmjs.org/"):
            raise ValueError("Pi 补充归档来源发生非预期重定向")
        data = response.read()
    expected = base64.b64decode(record["integrity"].split("-", 1)[1], validate=True)
    if hashlib.sha512(data).digest() != expected:
        raise ValueError("Pi 补充归档 SHA-512 不符")
    destination.write_bytes(data)
    with tarfile.open(destination, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            parts = PurePosixPath(member.name).parts
            if not member.isfile() or not parts or parts[0] != "package" or ".." in parts:
                raise ValueError("Pi 补充归档含非预期文件类型或路径")
            handle = archive.extractfile(member)
            installed = package_root.joinpath(*parts[1:])
            if handle is None or not installed.is_file() or hashlib.sha256(handle.read()).hexdigest() != digest(installed):
                raise ValueError("Pi 实际安装字节与完整性已固定的官方归档不符")


def prepare_pi(output: Path) -> dict:
    source = ROOT / "runtime/pi"
    pi = output / "resources/runtime/pi"
    pi.mkdir(parents=True, exist_ok=True)
    for name in PI_FILES:
        shutil.copyfile(source / name, pi / name)
    lock = json.loads((pi / "package-lock.json").read_text(encoding="utf-8"))
    supplemental = json.loads((ROOT / "licenses/local/npm-integrity.json").read_text(encoding="utf-8"))["packages"]
    validate_npm_lock(lock, supplemental)
    before = digest(pi / "package-lock.json")
    node = output / "resources/runtime/node" / ("node.exe" if sys.platform == "win32" else "bin/node")
    npm = output / "build-tools/npm/bin/npm-cli.js"
    if not node.is_file() or not npm.is_file():
        raise RuntimeError("缺少经官方归档固定的 Node/npm 构建工具")
    # 依赖脚本不执行；esbuild 使用锁内平台可选二进制。真实 SDK 初始化由冻结 smoke 验证。
    subprocess.run([str(node), str(npm), "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund",
                    "--registry=https://registry.npmjs.org/"], cwd=pi, check=True, timeout=600)
    if digest(pi / "package-lock.json") != before:
        raise RuntimeError("npm ci 修改了提交的依赖锁")
    installed = []
    absent_optional = []
    for path, item in lock["packages"].items():
        if not path:
            continue
        manifest = pi / path / "package.json"
        if not manifest.is_file():
            if item.get("optional") or item.get("dev"):
                absent_optional.append(path)
                continue
            raise RuntimeError(f"Pi 必要依赖缺失：{path}")
        actual = json.loads(manifest.read_text(encoding="utf-8"))
        if actual.get("version") != item["version"]:
            raise RuntimeError(f"Pi 依赖版本与锁不一致：{path}")
        if not item.get("integrity"):
            verify_supplemental_package(output, pi / path, supplemental[path])
        installed.append({"path": path, "name": actual.get("name"), "version": item["version"],
                          "declared_license": item.get("license", "未声明"),
                          "url": item["resolved"], "integrity": item.get("integrity") or supplemental[path]["integrity"],
                          "integrity_source": "package-lock.json" if item.get("integrity") else "已提交官方补充记录，归档与安装字节均验证",
                          "install_script_skipped": bool(item.get("hasInstallScript"))})
    # npm 的相对 .bin 链接仍属精确安装树；禁止链接到安装树之外的文件。
    for path in pi.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(pi.resolve()):
            raise RuntimeError("Pi 安装树含外部符号链接")
    return {"version": PI_VERSION, "lock_sha256": before, "packages": installed,
            "absent_platform_optional_or_dev": absent_optional,
            "install_policy": "npm ci --omit=dev --ignore-scripts；保留完整安装树及相对 .bin 链接"}


def stage_resources(output: Path) -> list[dict]:
    stage = output / "resources"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    records = []
    for name in public_resources():
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
        records.append({"path": name, "sha256": digest(destination)})
    return records


def command(output: Path) -> list[str]:
    result = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
              "--windowed", "--noupx", "--name", NAME, "--distpath", str(output / "dist"),
              "--workpath", str(output / "work"), "--specpath", str(output),
              "--runtime-hook", str(ROOT / "tools/desktop/local_runtime_hook.py"),
              "--collect-submodules", "app", "--recursive-copy-metadata", "chromadb",
              "--recursive-copy-metadata", "fastembed", "--recursive-copy-metadata", "google-genai",
              "--recursive-copy-metadata", "selenium", "--recursive-copy-metadata", "docker",
              "--add-data", f"{output / 'resources'}{os.pathsep}.",
              "--add-data", f"{output / 'generated-notices'}{os.pathsep}THIRD_PARTY_NOTICES"]
    for module in CORE_MODULES:
        result += ["--hidden-import", module]
    for module in COLLECT_ALL:
        result += ["--collect-all", module]
    result += ["--exclude-module", "PyQt5", "--exclude-module", "PyQt6", "--exclude-module", "PySide2"]
    result.append(str(ROOT / "boot_local.py"))
    return result


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/local-desktop")
    parser.add_argument("--print-command", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="仅准备依赖、许可材料和清单，不冻结")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.print_command:
        print(json.dumps(command(output), ensure_ascii=False, indent=2))
        return
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    subprocess.run([sys.executable, str(ROOT / "licenses/vendor/verify_vendored_licenses.py"),
                    "--source-root", str(ROOT)], check=True)
    resources = stage_resources(output)
    node = prepare_node(output)
    pi = prepare_pi(output)
    from local_compliance import prepare_notices, collect_inventory
    candidates = prepare_notices(ROOT, output, node, pi)
    write_json(output / "review/local-build-inputs.json", {
        "schema_version": 1, "binary_distribution_approved": False,
        "repository_resources": resources, "node": node, "pi": pi,
        "requirements_sha256": digest(ROOT / "requirements-desktop-local-build.txt")})
    if args.prepare_only:
        return
    subprocess.run(command(output), cwd=ROOT, check=True)
    inventory = collect_inventory(ROOT, output, candidates, resources, node, pi)
    write_json(output / "review/local-desktop-inventory.json", inventory)
    print("本地完整客户端已构建；二进制发布仍被关闭，须完成独立许可和安全审查")


if __name__ == "__main__":
    main()
