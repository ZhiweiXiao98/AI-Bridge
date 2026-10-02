"""取得固定官方 CfT 浏览器/驱动，只供 CI 自检，不进入 AI Bridge 发行包。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

from local_build import ROOT, configure_console, digest, write_json


def test_platform() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "mac-arm64"
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "win64"
    if sys.platform == "linux" and machine in {"amd64", "x86_64"}:
        return "linux64"
    raise RuntimeError("浏览器自检仅支持 macOS arm64、Windows x64 与 Linux x64 工程验证")


def selected_sources(manifest: dict, target: str) -> list[dict]:
    version = manifest.get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ValueError("CfT 固定版本格式非法")
    records = [entry for entry in manifest["archives"] if entry["platform"] == target]
    if len(records) != 2 or {entry["kind"] for entry in records} != {"chrome", "chromedriver"}:
        raise ValueError("目标平台缺少唯一的 Chrome/ChromeDriver 固定归档")
    for entry in records:
        expected = f"https://storage.googleapis.com/chrome-for-testing-public/{version}/{target}/{entry['kind']}-{target}.zip"
        if entry["url"] != expected or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            raise ValueError("CfT 来源或校验值不匹配固定官方记录")
    return records


def safe_extract(archive: Path, destination: Path) -> None:
    """保留 macOS framework 相对链接与执行权限；拒绝穿越、外部链接及特殊文件。"""
    root = destination.resolve()
    links = []
    with zipfile.ZipFile(archive) as zipped:
        if sum(info.file_size for info in zipped.infolist()) > 3_000_000_000:
            raise ValueError("CfT 解压大小超出测试上限")
        for info in zipped.infolist():
            relative = PurePosixPath(info.filename)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in info.filename
                    or ":" in info.filename or not relative.parts):
                raise ValueError("浏览器归档包含非法路径")
            target = root.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError("浏览器归档路径越界")
            mode = info.external_attr >> 16
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if stat.S_ISLNK(mode):
                link = zipped.read(info).decode("utf-8")
                if PurePosixPath(link).is_absolute() or "\\" in link or ":" in link:
                    raise ValueError("浏览器归档包含非法链接")
                if not (target.parent / link).resolve().is_relative_to(root):
                    raise ValueError("浏览器归档链接越界")
                links.append((target, link))
                continue
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise ValueError("浏览器归档包含特殊文件")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError("浏览器归档目标重复")
            with zipped.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            if os.name != "nt":
                target.chmod((mode & 0o777) or 0o644)
        # 先写普通文件，再建立链接，避免通过先前链接写入归档外部。
        for target, link in links:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError("浏览器链接目标重复")
            target.symlink_to(link)
        for target, _ in links:
            if not target.resolve().is_relative_to(root) or not target.exists():
                raise ValueError("浏览器归档最终链接缺失或越界")


def executable_paths(runtime: Path, target: str) -> tuple[Path, Path]:
    if target == "mac-arm64":
        return (runtime / "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                runtime / "chromedriver-mac-arm64/chromedriver")
    if target == "win64":
        return runtime / "chrome-win64/chrome.exe", runtime / "chromedriver-win64/chromedriver.exe"
    return runtime / "chrome-linux64/chrome", runtime / "chromedriver-linux64/chromedriver"


def prepare(output: Path, *, archive_cache: Path | None = None) -> dict:
    manifest_path = ROOT / "licenses/local/browser-test-sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = test_platform()
    records = selected_sources(manifest, target)
    output.mkdir(parents=True, exist_ok=True)
    archives = output / "archives"
    archives.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".browser-extract-", dir=output) as temporary:
        staging = Path(temporary)
        for entry in records:
            filename = f"{entry['kind']}-{target}.zip"
            archive = archives / filename
            if not archive.is_file() or digest(archive) != entry["sha256"]:
                cached = archive_cache / filename if archive_cache else None
                if cached and cached.is_file() and digest(cached) == entry["sha256"]:
                    shutil.copyfile(cached, archive)
                else:
                    with urlopen(entry["url"], timeout=240) as response, archive.open("wb") as destination:
                        if response.url != entry["url"]:
                            raise ValueError("CfT 下载发生非预期重定向")
                        shutil.copyfileobj(response, destination)
            if digest(archive) != entry["sha256"] or archive.stat().st_size != entry["size"]:
                raise ValueError("官方浏览器测试归档 SHA-256/大小与固定记录不一致")
            safe_extract(archive, staging)
        runtime = output / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        shutil.move(str(staging), runtime)
    chrome, driver = executable_paths(runtime, target)
    if not chrome.is_file() or not driver.is_file():
        raise ValueError("官方归档没有产生预期浏览器或驱动")
    driver_output = subprocess.check_output([str(driver), "--version"], text=True, encoding="utf-8", timeout=30)
    if driver_output.split()[1] != manifest["version"]:
        raise ValueError("实际 ChromeDriver 版本与固定版本不同")
    result = {"schema_version": 1, "version": manifest["version"], "platform": target,
              "chrome": str(chrome.resolve()), "chromedriver": str(driver.resolve()),
              "chrome_executable_sha256": digest(chrome), "chromedriver_executable_sha256": digest(driver),
              "archives": records, "source_manifest_sha256": digest(manifest_path),
              "official_manifest_url": manifest["official_manifest_url"],
              "runtime_browser_version_status": "必须由实际 WebDriver capabilities 验证，下载成功不是运行成功",
              "not_in_application_bundle": True}
    write_json(output / "runtime.json", result)
    print("已准备固定官方浏览器/驱动测试夹具；未运行浏览器，未加入应用分发包")
    return result


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/local-desktop/browser-test")
    parser.add_argument("--archive-cache", type=Path, help="可复用已取得的归档；仍强制核验固定哈希")
    args = parser.parse_args()
    prepare(args.output.resolve(), archive_cache=args.archive_cache)


if __name__ == "__main__":
    main()
