"""完整本地 Mac 本人测试 DMG 草案；固定审批占位未替换前拒绝运行。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys

SOURCE_COMMIT = 'd51dc1ef827912d84b90fee77ff84d6369588cc5'
MATERIALS_MANIFEST_SHA256 = 'c2f6a21e3bb435146b99be80977e9a93131e1e690628de7eef245bcff150f1ea'
EXPECTED_DEPENDENCIES_SHA256 = '5f882be5295f9c7f5b0a7a6b5429e81e47db0b7f84ca0ef4beb47552220a6f79'
NAME = 'AI-Bridge-Local'
ARCHIVE_NAME = 'AI-Bridge-Local-macOS-ARM64-owner-test.dmg'
MAX_APP_BYTES = 4 * 1024**3
MAX_APP_ENTRIES = 60000
MAX_DMG_BYTES = 3 * 1024**3


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*arguments, **kwargs):
    return subprocess.run(arguments, check=True, **kwargs)


def bundle_manifest(root: Path):
    """lstat 区分实际 regular 字节与内部相对链接，不把链接目标重复计费。"""
    if root.is_symlink() or not root.is_dir():
        raise ValueError('应用根必须是真实目录')
    resolved = root.resolve()
    entries, regular_bytes, regular_count = {}, 0, 0
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        entry = {'mode': stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            link = os.readlink(path)
            if Path(link).is_absolute() or not path.resolve(strict=True).is_relative_to(resolved):
                raise ValueError('应用链接不是可重定位的内部相对链接')
            entry.update(kind='link', target=link)
        elif stat.S_ISREG(info.st_mode):
            regular_count += 1
            regular_bytes += info.st_size
            entry.update(kind='regular', size=info.st_size, sha256=digest(path))
        elif stat.S_ISDIR(info.st_mode):
            entry.update(kind='directory')
        else:
            raise ValueError('应用包含特殊文件')
        entries[relative] = entry
        if len(entries) > MAX_APP_ENTRIES or regular_bytes > MAX_APP_BYTES:
            raise ValueError('应用真实文件数量或字节超出已审核上限')
    return {'entries': entries, 'regular_file_count': regular_count, 'regular_bytes': regular_bytes}


def sidecar_manifest(stage: Path):
    result = {}
    for path in sorted(stage.rglob('*')):
        relative = path.relative_to(stage)
        if relative.parts[0] == NAME + '.app':
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            if relative.as_posix() != 'Applications' or os.readlink(path) != '/Applications':
                raise ValueError('磁盘映像侧文件含非预期链接')
            result[relative.as_posix()] = {'kind': 'link', 'target': '/Applications'}
        elif stat.S_ISREG(info.st_mode):
            result[relative.as_posix()] = {'kind': 'regular', 'size': info.st_size,
                                         'mode': stat.S_IMODE(info.st_mode), 'sha256': digest(path)}
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('磁盘映像侧文件包含特殊文件')
    return result


def require_materials(path: Path, source_commit: str):
    if not re.fullmatch(r'[0-9a-f]{64}', MATERIALS_MANIFEST_SHA256) or digest(path) != MATERIALS_MANIFEST_SHA256:
        raise ValueError('许可/源码材料审查清单未绑定，不能生成 owner 测试包')
    review = json.loads(path.read_text(encoding='utf-8'))
    if (review.get('schema_version') != 1 or review.get('source_commit') != source_commit or review.get('owner_test_materials_approved') is not True
            or review.get('source_replacement_review_approved') is not True
            or review.get('unresolved_materials') != [] or review.get('review_id') in (None, '', 'TBD')
            or not isinstance(review.get('review_id'), str) or not review.get('additional_materials')):
        raise ValueError('许可、对应源码或替换验证仍有未决项；加密不豁免这些条件')
    for record in review.get('additional_materials', []):
        relative = Path(record['path'])
        material = path.parent / relative
        if relative.is_absolute() or '..' in relative.parts or material.is_symlink() or not material.is_file():
            raise ValueError('审批材料路径无效')
        if not material.resolve().is_relative_to(path.parent.resolve()) or digest(material) != record['sha256']:
            raise ValueError('审批材料缺失或字节变化')
    return review


def dependency_identity(inventory):
    """绑定获批材料对应的全部安装wheel及实际Node/Pi包，拒绝解析器漂移。"""
    wheels = []
    for record in inventory['dependencies']:
        wheel = record['wheel']
        if (record['version'] != wheel['version'] or not wheel['filename'].endswith('.whl')
                or not re.fullmatch('[0-9a-f]{64}', wheel['sha256'])):
            raise ValueError('构建wheel缺少精确版本、文件名或SHA-256')
        wheels.append({key: record[key] for key in ('name', 'version')} |
                      {key: wheel[key] for key in ('filename', 'sha256')})
    if len({item['name'] for item in wheels}) != len(wheels):
        raise ValueError('重复Python dependency名称')
    npm = [{key: item[key] for key in ('path', 'name', 'version', 'integrity')}
           for item in inventory['npm_dependencies']]
    if len({item['path'] for item in npm}) != len(npm):
        raise ValueError('重复npm dependency路径')
    return {'schema_version': 1, 'source_commit': inventory['source_commit'],
            'platform': inventory['platform'], 'architecture': inventory['architecture'],
            'python_wheels': sorted(wheels, key=lambda item: item['name']),
            'node': {key: inventory['node'][key] for key in (
                'version', 'target', 'archive_sha256', 'executable_sha256', 'license_sha256')},
            'pi_version': inventory['pi']['version'], 'pi_lock_sha256': inventory['pi']['lock_sha256'],
            'npm_packages': sorted(npm, key=lambda item: item['path'])}


def require_dependency_identity(inventory):
    path = Path(__file__).with_name('expected-dependencies.json')
    if path.is_symlink() or digest(path) != EXPECTED_DEPENDENCIES_SHA256:
        raise ValueError('获批依赖范围manifest缺失或hash变化')
    expected = json.loads(path.read_text(encoding='utf-8'))
    if dependency_identity(inventory) != expected:
        raise ValueError('重建依赖wheel/Node/Pi范围偏离本次绑定的获批材料；不得自动扩大或替换')


def require_new_chat_probe(probe):
    """r2 必须实际跑过浏览器侧栏图标新建并清除空会话残留的固定自检。"""
    checks = probe.get('browser_probe', {}).get('checks')
    if not isinstance(checks, list) or '浏览器侧栏图标新建会话' not in checks:
        raise ValueError('r2 缺少真实浏览器侧栏新建空会话验收')


def check_inventory(inventory, baseline):
    if (inventory.get('source_commit') != SOURCE_COMMIT or inventory.get('platform') != 'darwin'
            or inventory.get('architecture') != 'arm64' or inventory.get('binary_distribution_approved') is not False
            or inventory.get('privacy_path_findings') != [] or inventory.get('core_modules_missing') != []):
        raise ValueError('精确源码、架构、隐私或核心库存不符合 owner 范围')
    probe = inventory.get('frozen_runtime_probe', {})
    if (probe.get('status') != 'passed' or probe.get('external_model_calls') is not False
            or probe.get('host_python_node_removed_from_path') is not True
            or probe.get('native_gui_probe', {}).get('passed') is not True
            or probe.get('browser_probe', {}).get('same_profile_history_restored') is not True):
        raise ValueError('缺少实际冻结 API、浏览器或原生窗口验收')
    require_new_chat_probe(probe)
    policy = inventory.get('qt_input_policy', {})
    if (policy.get('passed') is not True or policy.get('violations') != []
            or policy.get('license_clearance') is not False):
        raise ValueError('最终 Qt 输入范围与保留能力策略未通过')
    native = probe['native_gui_probe']
    if (native.get('platform_plugin') != 'cocoa' or native.get('qt_exception_count') != 0
            or any(native.get(key) is not True for key in (
                'pdf_qimage_decoded', 'pdf_fixture_pixels_verified',
                'webengine_local_preview_loaded', 'webengine_marker_verified',
                'webengine_preview_disposed'))):
        raise ValueError('实际 PDF、WebEngine 与原生 Cocoa 保留能力未通过')
    cleanup = [probe.get('process_cleanup_probe', {}).get(name, {})
               for name in ('first_process', 'second_process')]
    cleanup += [probe['browser_probe'].get('process_cleanup_probe', {}),
                native.get('process_cleanup_probe', {})]
    if any(item.get('all_observed_descendants_exited') is not True for item in cleanup):
        raise ValueError('冻结功能验收未证明其所有受观察子进程退出')
    indexed = {entry['path']: entry for entry in inventory['files']}
    if len(indexed) != len(inventory['files']):
        raise ValueError('最终库存含重复路径')
    for relative, entry in baseline['entries'].items():
        if entry['kind'] == 'regular':
            expected = indexed.get(NAME + '.app/' + relative)
            if not expected or (expected['sha256'], expected['size']) != (entry['sha256'], entry['size']):
                raise ValueError('应用 regular 文件与本轮库存不同')



def deployment_metadata(app: Path):
    """仅记录实际构建目标元数据，不把SDK或Qt支持范围冒充整包最低OS。"""
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    result = {'architecture': 'arm64',
              'tested_macos_version': run('sw_vers', '-productVersion', capture_output=True, text=True).stdout.strip(),
              'tested_macos_build': run('sw_vers', '-buildVersion', capture_output=True, text=True).stdout.strip(),
              'plist_minimum_system_version': info.get('LSMinimumSystemVersion'),
              'whole_application_minimum_os_verified': False}
    targets = {'launcher': app / 'Contents/MacOS' / NAME,
               'qtcore': app / 'Contents/Frameworks/PySide6/Qt/lib/QtCore.framework/Versions/A/QtCore'}
    for label, path in targets.items():
        value = run('otool', '-l', str(path), capture_output=True, text=True).stdout
        result[label + '_macho_minos'] = sorted(set(re.findall(r'^\s*minos\s+([0-9.]+)\s*$', value, re.M)))
    return result

def main():
    if not re.fullmatch(r'[0-9a-f]{40}', SOURCE_COMMIT):
        raise SystemExit('尚未绑定真实通过验收并获批的源码 SHA')
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('仅可在原生 Mac ARM64 构建机执行')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--materials', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    commit = run('git', 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()
    if commit != SOURCE_COMMIT:
        raise ValueError('构建源码与固定 owner 范围不符')
    run('git', 'diff', '--exit-code', 'HEAD', '--')
    materials = require_materials(args.materials.resolve(), commit)
    sys.path.insert(0, str(root / 'tools/desktop'))
    from local_compliance import verify_bundle_data
    from local_smoke import run_checks
    from local_qt_policy import inspect_qt_inventory
    from local_build import CORE_MODULES
    build = root / 'build/local-desktop'
    inventory = json.loads((build / 'review/local-desktop-inventory.json').read_text(encoding='utf-8'))
    app = build / 'dist' / (NAME + '.app')
    baseline = bundle_manifest(app)
    check_inventory(inventory, baseline)
    require_dependency_identity(inventory)
    if inspect_qt_inventory(inventory, CORE_MODULES) != inventory['qt_input_policy']:
        raise ValueError('最终 Qt 策略结论与重新计算的实际库存不一致')
    verify_bundle_data(app, build)
    executable = app / 'Contents/MacOS' / NAME
    arches = run('lipo', '-archs', str(executable), capture_output=True, text=True).stdout.strip()
    if arches != 'arm64':
        raise ValueError('应用启动器不是纯 ARM64')
    run('codesign', '--verify', '--deep', '--strict', str(app))
    signature = run('codesign', '-d', '--verbose=4', str(app), capture_output=True, text=True).stderr
    if 'Signature=adhoc' not in signature:
        raise ValueError('当前仅批准明确披露的 ad-hoc 测试签名路线')
    output = root / 'build/owner-local-test'
    output.mkdir(parents=True, exist_ok=False)
    stage = output / 'staging'
    stage.mkdir()
    run('ditto', str(app), str(stage / app.name))
    if bundle_manifest(stage / app.name) != baseline:
        raise ValueError('复制改变应用 regular 字节、权限或内部链接')
    (stage / 'Applications').symlink_to('/Applications')
    run('git', 'archive', '--format=tar', '--output=' + str(stage / 'AI-Bridge-source.tar'), SOURCE_COMMIT)
    approved = stage / 'APPROVED_SOURCE_AND_LICENSE_MATERIALS'
    approved.mkdir()
    for record in materials.get('additional_materials', []):
        target = approved / record['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.materials.resolve().parent / record['path'], target)
    shutil.copyfile(args.materials, approved / 'materials-review.json')
    (stage / 'local-desktop-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    (stage / '安装与验收边界.txt').write_text(
        'AI-Bridge Local · Mac Apple Silicon 本人测试版\n\n'
        '本次交付用途为本人测试；许可证赋予接收者的权利不受限制。\n应用使用 ad-hoc 签名，无 Developer ID 签名或 Apple 公证。\n'
        '下载后的 macOS 可能阻止启动；请自行核对来源和 SHA-256，并由你决定系统提示。\n'
        '将 AI-Bridge-Local.app 拖到 Applications。核心自带 Python/Node/Pi。\n'
        '浏览器模式需要已安装的官方 Chrome、匹配驱动及你自行在专用窗口登录。\n'
        '无账号、API密钥、真实会话、浏览器资料、付费模型或RAG模型权重。\n'
        '测试只用本机模拟模型/网页；真实站点适配、收费API、崩溃恢复未声称通过。\n'
        '同版本应用源码和独立批准的许可/对应源码材料随包，不限制许可证赋予你的权利。\n'
        '公开二进制发行仍未批准。加密仅保护交付，不代表许可结论。\n'
        '源码SHA：' + SOURCE_COMMIT + '\n', encoding='utf-8')
    (stage / '构建平台与兼容性.json').write_text(
        json.dumps(deployment_metadata(app), ensure_ascii=False, indent=2), encoding='utf-8')
    sidecars = sidecar_manifest(stage)
    dmg = output / ARCHIVE_NAME
    run('hdiutil', 'create', '-volname', 'AI-Bridge Local Owner Test', '-srcfolder', str(stage), '-format', 'ULMO', str(dmg))
    if not 0 < dmg.stat().st_size <= MAX_DMG_BYTES:
        raise ValueError('最终 DMG 超过3GiB上限；不得静默扩大交付范围')
    run('hdiutil', 'verify', str(dmg))
    mount = output / 'mounted'
    mount.mkdir()
    run('hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(dmg))
    try:
        restored = mount / app.name
        if sidecar_manifest(mount) != sidecars:
            raise ValueError('最终DMG改变同版本源码、许可材料或安装说明')
        if bundle_manifest(restored) != baseline:
            raise ValueError('最终只读 DMG 改变应用字节、mode或链接')
        run('codesign', '--verify', '--deep', '--strict', str(restored))
        verify_bundle_data(restored, build)
        # 本参数须先经独立源码审查；不复制或mock任何功能检查。
        run_checks(build, argparse.Namespace(api_only=False, browser_fixture=build / 'browser-test/runtime.json'),
                   {'stage': '只读挂载DMG完整自检'}, executable_override=restored / 'Contents/MacOS' / NAME)
        final_probe = json.loads((build / 'review/local-smoke.json').read_text(encoding='utf-8'))
        if final_probe.get('status') != 'passed' or final_probe.get('native_gui_probe', {}).get('passed') is not True:
            raise ValueError('最终DMG缺完整功能和原生窗口成功证据')
        require_new_chat_probe(final_probe)
    finally:
        run('hdiutil', 'detach', str(mount))
    validation = {'schema_version': 1, 'source_commit': SOURCE_COMMIT, 'filename': ARCHIVE_NAME,
                  'archive_sha256': digest(dmg), 'archive_size': dmg.stat().st_size,
                  'app_regular_file_count': baseline['regular_file_count'], 'app_regular_bytes': baseline['regular_bytes'],
                  'byte_mode_link_roundtrip': True, 'mounted_full_smoke_passed': True, 'mounted_native_gui_passed': True,
                  'materials_manifest_sha256': MATERIALS_MANIFEST_SHA256,
                  'developer_id_signed': False, 'notarized': False, 'binary_distribution_approved': False}
    (output / 'owner-package-validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(validation, ensure_ascii=False))


if __name__ == '__main__':
    main()
