# 在任意工作目录运行远程协议回归；可传入其它 pytest 目标。
param(
    [switch]$InstallDependencies,
    [string[]]$TestPaths = @('tests/test_remote_protocol.py')
)

$ErrorActionPreference = 'Stop'
$utf8Bootstrap = Join-Path $PSScriptRoot 'scripts/Use-ProjectUtf8.ps1'
if (Test-Path -LiteralPath $utf8Bootstrap) {
    . $utf8Bootstrap -Quiet
}
$pythonExe = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw '未找到项目虚拟环境，请先在仓库根目录运行：py -m venv .venv'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    if ($InstallDependencies) {
        Write-Host '安装项目依赖...'
        & $pythonExe -X utf8 -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Write-Host "运行测试：$($TestPaths -join ', ')"
    & $pythonExe -X utf8 -m pytest @TestPaths -q
    $checkExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $checkExitCode
