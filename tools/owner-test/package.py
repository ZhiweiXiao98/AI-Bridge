"""Make and validate a private macOS owner-test DMG from the pinned source build.

Does not grant release approval or upload files. No signing key is used.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

SOURCE_COMMIT = "415309cd195973fa495efecff4a7a0dcb3d56f02"
NAME = "AI-Bridge-Remote"
ARCHIVE_NAME = "AI-Bridge-Remote-macOS-ARM64-owner-test.dmg"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bundle_manifest(root):
    """Reject broken/escaping links and record all regular bytes plus link targets."""
    resolved = root.resolve()
    manifest = {}
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(resolved):
                raise ValueError("Application link escapes the bundle: " + relative)
            manifest[relative] = {"link": os.readlink(path)}
        elif path.is_file():
            size = path.stat().st_size
            total += size
            if total > 2_000_000_000 or len(manifest) > 10000:
                raise ValueError("Unexpected application size or file count")
            manifest[relative] = {"sha256": sha256(path), "mode": path.stat().st_mode & 0o777, "size": size}
        elif not path.is_dir():
            raise ValueError("Unexpected special file: " + relative)
    return manifest


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("This owner test is only for a native macOS ARM64 runner")
    root = Path.cwd().resolve()
    commit = run("git", "rev-parse", "HEAD", capture_output=True, text=True).stdout.strip()
    if commit != SOURCE_COMMIT:
        raise ValueError("Source commit differs from the reviewed owner-test commit")
    sys.path.insert(0, str(root / "tools/desktop"))
    from compliance import verify_notices
    build = root / "build/desktop"
    inventory = json.loads((build / "review/desktop-inventory.json").read_text(encoding="utf-8"))
    if inventory["source_commit"] != SOURCE_COMMIT or inventory["architecture"] != "arm64":
        raise ValueError("Inventory source/architecture mismatch")
    if inventory["binary_distribution_approved"] is not False:
        raise ValueError("Public binary gate must remain closed")
    if inventory["privacy_path_findings"] or inventory["blocked_native_components"]:
        raise ValueError("Bundle scope/privacy gate failed")
    if not inventory.get("frozen_runtime_probe"):
        raise ValueError("Frozen application smoke evidence is missing")
    app = build / "dist" / (NAME + ".app")
    baseline = bundle_manifest(app)
    # Every shipped regular file must match the just-built inventory.
    indexed = {entry["path"]: entry for entry in inventory["files"]}
    for relative, entry in baseline.items():
        if "sha256" in entry:
            expected = indexed.get(NAME + ".app/" + relative)
            if not expected or expected["sha256"] != entry["sha256"]:
                raise ValueError("App byte not matched by current inventory: " + relative)
    verify_notices(app, build / "generated-notices")
    executable = app / "Contents/MacOS" / NAME
    arches = run("lipo", "-archs", str(executable), capture_output=True, text=True).stdout.strip()
    if arches != "arm64":
        raise ValueError("Executable is not exclusively ARM64")
    run("codesign", "--verify", "--deep", "--strict", str(app))
    out = root / "build/owner-test"
    out.mkdir(parents=True, exist_ok=False)
    staging = out / "staging"
    staging.mkdir()
    run("ditto", str(app), str(staging / app.name))
    if bundle_manifest(staging / app.name) != baseline:
        raise ValueError("Staging changed the application")
    (staging / "Applications").symlink_to("/Applications")
    (staging / "安装说明.txt").write_text(
        "AI-Bridge Remote · Mac Apple Silicon 本机测试版\n\n"
        "仅供 Apple Silicon (M 系列) Mac 安装测试；尚未验证各个 macOS 版本的兼容性。\n"
        "将 AI-Bridge-Remote.app 拖到 Applications，再从应用程序中打开。\n"
        "此包为你的安装测试准备，尚未通过公开二进制分发审查。\n"
        "应用仅作本地 ad-hoc 签名，没有 Apple Developer ID 签名或公证，macOS 可能拦截。\n"
        "若系统拦截，请先核对来源和 SHA-256；需要手动允许时由你在系统设置中决定。\n"
        "本包不含已登录账号、API 密钥、浏览器资料、服务端或你的运行时数据。\n"
        "这是远程客户端，使用时需要你的服务器地址和账号。\n"
        "启动测试只覆盖离线登录窗口；实际服务器连接和账号登录尚需你测试。\n\n"
        "源码版本：" + SOURCE_COMMIT + "\n"
        "同版本应用源码见 AI-Bridge-source.tar；重建说明见其中 docs/DESKTOP_REBUILD.md。\n"
        "第三方许可和对应源码信息见应用包 Contents/Resources/THIRD_PARTY_NOTICES。\n"
        "这不改变第三方许可证赋予你的权利，也不代表公开分发已获得许可核验。\n",
        encoding="utf-8")
    run("git", "archive", "--format=tar", "--output=" + str(staging / "AI-Bridge-source.tar"), SOURCE_COMMIT)
    # Evidence is included privately with the exact program, not published separately.
    (staging / "desktop-inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    dmg = out / ARCHIVE_NAME
    run("hdiutil", "create", "-volname", "AI-Bridge Remote Test", "-srcfolder", str(staging), "-ov", "-format", "ULMO", str(dmg))
    run("hdiutil", "verify", str(dmg))
    mount = out / "mounted"
    mount.mkdir()
    run("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg))
    try:
        restored = mount / app.name
        if bundle_manifest(restored) != baseline:
            raise ValueError("Final DMG changed application bytes, modes, or symlinks")
        run("codesign", "--verify", "--deep", "--strict", str(restored))
        verify_notices(restored, build / "generated-notices")
        with tempfile.TemporaryDirectory(prefix="ai-bridge-owner-smoke-") as state:
            env = os.environ.copy()
            env.update(AI_BRIDGE_CLIENT_HOME=state, QT_QPA_PLATFORM="offscreen")
            run(str(restored / "Contents/MacOS" / NAME), "--desktop-smoke-test", cwd=state, env=env, timeout=90)
            if (Path(state) / "desktop-smoke-ok.txt").read_text(encoding="utf-8") != "login-window-ok\n":
                raise ValueError("Mounted image login smoke failed")
            runtime = json.loads((Path(state) / "desktop-runtime.json").read_text(encoding="utf-8"))
            if runtime != inventory["frozen_runtime_probe"]:
                raise ValueError("Mounted image runtime differs from tested app")
    finally:
        run("hdiutil", "detach", str(mount))
    print("Validated owner-test DMG bytes: " + str(dmg.stat().st_size))
    if dmg.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Validated DMG still exceeds the 32 MiB packaging target")
    print("Validated owner-test DMG SHA256: " + sha256(dmg))


if __name__ == "__main__":
    main()
