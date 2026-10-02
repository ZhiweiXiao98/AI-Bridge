"""只读使用标准 Windows CI 已安装的官方 Chrome；不运行安装器或改变权限。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.request import urlopen

from local_browser_fixture import extraction_staging, safe_extract, selected_sources, test_platform
from local_build import ROOT, configure_console, digest, write_json


# 所有命令均为固定只读查询；不接受外部 PowerShell 片段或可执行路径。
_CHROME_QUERY = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$stage = 'registry'
$signatureState = 'not_checked'
$registryFound = $false
$fileFound = $false
$publisherMatched = $false
try {
$registry = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe'
$chrome = [string](Get-ItemProperty -LiteralPath $registry).'(default)'
if (-not $chrome) { throw '标准注册表没有已安装 Chrome' }
$registryFound = $true
$stage = 'chrome_file'
$item = Get-Item -LiteralPath $chrome
$fileFound = $true
$stage = 'signature'
$signature = Get-AuthenticodeSignature -LiteralPath $item.FullName
$signatureState = [string]$signature.Status
if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate) { throw 'Chrome 官方签名无效' }
$stage = 'publisher'
$publisher = $signature.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
if ($publisher -ne 'Google LLC') { throw 'Chrome 签名发布者不符合预期' }
$publisherMatched = $true
$stage = 'metadata'
@{
  ok = $true
  chrome = $item.FullName
  version = $item.VersionInfo.ProductVersion
  publisher = $publisher
  authenticode_status = [string]$signature.Status
  signer_thumbprint = $signature.SignerCertificate.Thumbprint
  program_files = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
  program_files_x86 = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
} | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; stage = $stage; error_kind = $_.Exception.GetType().Name;
     signature_status = $signatureState; registry_found = $registryFound;
     file_found = $fileFound; publisher_matched = $publisherMatched } | ConvertTo-Json -Compress
  exit 1
}
'''


def runner_identity() -> dict:
    if sys.platform != 'win32' or test_platform() != 'win64':
        raise RuntimeError('预装 Chrome 自检分支仅支持标准 Windows x64 CI')
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Windows':
        raise RuntimeError('预装 Chrome 自检分支只能在明确的 GitHub Actions Windows runner 中运行')
    image_os, image_version = os.environ.get('ImageOS', ''), os.environ.get('ImageVersion', '')
    if not re.fullmatch(r'win\d{2}(?:-vs\d{4})?', image_os) or not re.fullmatch(r'\d{8}\.\d+\.\d+', image_version):
        raise RuntimeError('缺少可核对的标准 Windows runner 镜像标识')
    return {'origin': 'github-hosted-runner', 'image_os': image_os, 'image_version': image_version,
            'image_repository': 'https://github.com/actions/runner-images'}


def validate_chrome_metadata(metadata: dict) -> tuple[Path, dict]:
    chrome = Path(metadata.get('chrome', ''))
    allowed = [Path(metadata[key]) / 'Google/Chrome/Application/chrome.exe'
               for key in ('program_files', 'program_files_x86') if metadata.get(key)]
    if (not chrome.is_absolute() or not chrome.is_file() or chrome.is_symlink()
            or not any(chrome.resolve() == path.resolve() for path in allowed)):
        raise RuntimeError('CI 预装 Chrome 不在标准系统安装位置')
    version = str(metadata.get('version', ''))
    if (not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', version)
            or metadata.get('publisher') != 'Google LLC' or metadata.get('authenticode_status') != 'Valid'
            or not re.fullmatch(r'[0-9A-Fa-f]{40}', str(metadata.get('signer_thumbprint', '')))):
        raise RuntimeError('CI 预装 Chrome 的完整版本或官方签名证据不符合要求')
    return chrome.resolve(), {key: metadata[key] for key in
                              ('version', 'publisher', 'authenticode_status', 'signer_thumbprint')}


def query_failure_diagnostic(metadata, stderr: str) -> str:
    """只回显固定状态及严格布尔；丢弃 PowerShell 异常正文、路径和证书详情。"""
    metadata = metadata if isinstance(metadata, dict) else {}
    stages = {'registry', 'chrome_file', 'signature', 'publisher', 'metadata'}
    kinds = {'RuntimeException', 'ItemNotFoundException', 'DriveNotFoundException', 'ParameterBindingException',
             'CommandNotFoundException', 'SecurityException', 'IOException'}
    statuses = {'Valid', 'NotSigned', 'UnknownError', 'NotTrusted', 'HashMismatch',
                'NotSupportedFileFormat', 'Incompatible', 'not_checked'}
    result = {}
    for field, allowed, default in (('stage', stages, 'powershell_start_or_parse'),
                                    ('error_kind', kinds, 'other'), ('signature_status', statuses, 'unknown')):
        value = metadata.get(field)
        result[field] = value if isinstance(value, str) and value in allowed else default
    for field in ('registry_found', 'file_found', 'publisher_matched'):
        if type(metadata.get(field)) is bool:
            result[field] = metadata[field]
    # 解析失败时 catch 本身尚未运行；只识别固定类别，不转发 stderr。
    if not metadata:
        for token in ('ParserError', 'ParameterBindingException', 'CommandNotFoundException'):
            if token in stderr:
                result['error_kind'] = token
                break
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


def read_preinstalled_chrome() -> tuple[Path, dict]:
    identity = runner_identity()
    system_root = Path(os.environ.get('SYSTEMROOT', ''))
    powershell = system_root / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    if not system_root.is_absolute() or not powershell.is_file():
        raise RuntimeError('未找到 Windows 自带的只读签名查询工具')
    result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', _CHROME_QUERY],
                            capture_output=True, encoding='utf-8-sig', timeout=40, check=False)
    try:
        metadata = json.loads(result.stdout)
    except (ValueError, TypeError):
        metadata = {}
    if result.returncode or not isinstance(metadata, dict) or metadata.get('ok') is not True:
        raise RuntimeError('只读 Chrome 查询失败：' + query_failure_diagnostic(metadata, result.stderr))
    try:
        chrome, metadata = validate_chrome_metadata(metadata)
    except (ValueError, TypeError, KeyError) as error:
        raise RuntimeError('只读 Chrome 查询未返回有效的版本与签名证据') from error
    return chrome, {**identity, **metadata}


def compatible_build(browser_version: str, driver_version: str) -> bool:
    return (bool(re.fullmatch(r'\d+\.\d+\.\d+\.\d+', browser_version))
            and bool(re.fullmatch(r'\d+\.\d+\.\d+\.\d+', driver_version))
            and browser_version.split('.')[:3] == driver_version.split('.')[:3])


def prepare(output: Path, *, archive_cache: Path | None = None) -> dict:
    chrome, installed = read_preinstalled_chrome()
    manifest_path = ROOT / 'licenses/local/browser-test-sources.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    driver_version = manifest['version']
    if not compatible_build(installed['version'], driver_version):
        raise RuntimeError('CI 已安装 Chrome 与固定官方驱动的 MAJOR.MINOR.BUILD 不兼容；未替换或更新系统浏览器')
    record = next(entry for entry in selected_sources(manifest, 'win64') if entry['kind'] == 'chromedriver')
    output.mkdir(parents=True, exist_ok=True)
    archives = output / 'archives'
    archives.mkdir(exist_ok=True)
    archive = archives / 'chromedriver-win64.zip'
    if not archive.is_file() or digest(archive) != record['sha256']:
        cached = archive_cache / archive.name if archive_cache else None
        if cached and cached.is_file() and digest(cached) == record['sha256']:
            shutil.copyfile(cached, archive)
        else:
            with urlopen(record['url'], timeout=240) as source, archive.open('wb') as destination:
                if source.url != record['url']:
                    raise ValueError('固定官方驱动下载发生非预期重定向')
                shutil.copyfileobj(source, destination)
    if digest(archive) != record['sha256'] or archive.stat().st_size != record['size']:
        raise ValueError('固定官方驱动归档 SHA-256/大小不一致')
    with extraction_staging(output) as staging:
        safe_extract(archive, staging)
        runtime = output / 'runtime'
        if runtime.exists():
            shutil.rmtree(runtime)
        shutil.move(str(staging), runtime)
    driver = runtime / 'chromedriver-win64/chromedriver.exe'
    actual = subprocess.check_output([str(driver), '--version'], text=True, encoding='utf-8', timeout=30)
    if actual.split()[1] != driver_version:
        raise ValueError('实际官方驱动版本不符合固定记录')
    result = {'schema_version': 1, 'source_kind': 'runner-preinstalled-chrome', 'platform': 'win64',
              'browser_version': installed['version'], 'chromedriver_version': driver_version,
              'chrome': str(chrome), 'chromedriver': str(driver.resolve()),
              'chrome_executable_sha256': digest(chrome), 'chromedriver_executable_sha256': digest(driver),
              'archives': [record], 'source_manifest_sha256': digest(manifest_path),
              'official_manifest_url': manifest['official_manifest_url'], 'preinstalled_browser': installed,
              'runtime_browser_version_status': '必须由实际 WebDriver capabilities 再次核验，不代表冒烟通过',
              'not_in_application_bundle': True}
    write_json(output / 'runtime.json', result)
    print('已核验 CI 预装官方 Chrome 和固定匹配驱动；未运行安装器、未修改权限或系统配置')
    return result


def validate_runtime(runtime: dict, path: Path) -> dict:
    """执行冒烟前再次只读验证官方签名/注册表；只返回允许公开的证据。"""
    chrome, installed = read_preinstalled_chrome()
    manifest_path = ROOT / 'licenses/local/browser-test-sources.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    record = next(entry for entry in selected_sources(manifest, 'win64') if entry['kind'] == 'chromedriver')
    driver = Path(runtime.get('chromedriver', ''))
    if (runtime.get('source_kind') != 'runner-preinstalled-chrome' or runtime.get('platform') != 'win64'
            or runtime.get('browser_version') != installed['version'] or runtime.get('preinstalled_browser') != installed
            or runtime.get('chromedriver_version') != manifest['version']
            or not compatible_build(installed['version'], manifest['version'])
            or runtime.get('archives') != [record] or runtime.get('source_manifest_sha256') != digest(manifest_path)
            or runtime.get('official_manifest_url') != manifest['official_manifest_url']
            or runtime.get('not_in_application_bundle') is not True
            or Path(runtime.get('chrome', '')).resolve() != chrome or runtime.get('chrome_executable_sha256') != digest(chrome)
            or not driver.is_absolute() or not driver.is_file()
            or not driver.resolve().is_relative_to((path.parent / 'runtime').resolve())
            or runtime.get('chromedriver_executable_sha256') != digest(driver)):
        raise RuntimeError('CI 预装 Chrome / 固定驱动的来源、签名、版本或字节已改变')
    return {key: runtime[key] for key in ('source_kind', 'platform', 'browser_version', 'chromedriver_version',
             'chrome_executable_sha256', 'chromedriver_executable_sha256', 'archives', 'source_manifest_sha256',
             'official_manifest_url', 'preinstalled_browser', 'not_in_application_bundle')}


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/local-desktop/browser-test')
    parser.add_argument('--archive-cache', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        prepare(output, archive_cache=args.archive_cache)
    except Exception as error:
        from local_smoke import safe_failure_report
        write_json(output.parent / 'review/local-smoke.json',
                   safe_failure_report('预装浏览器只读准备', error, output.parent))
        raise


if __name__ == '__main__':
    main()
