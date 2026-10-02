# Use-ProjectUtf8.ps1 - normalize PowerShell, Python, and child process output to UTF-8.

[CmdletBinding()]
param(
    [switch]$Quiet
)

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$script:OutputEncoding = $Utf8NoBom
$global:OutputEncoding = $Utf8NoBom
$PSDefaultParameterValues["*:Encoding"] = "utf8"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:LANG = "zh_CN.UTF-8"
$env:LC_ALL = "zh_CN.UTF-8"

try {
    & $env:ComSpec /d /c "chcp 65001 >nul 2>nul" | Out-Null
} catch {
    if (-not $Quiet) {
        Write-Warning "Unable to switch console code page to UTF-8: $($_.Exception.Message)"
    }
}

if (-not $Quiet) {
    Write-Host "PowerShell UTF-8 mode enabled for Data-Bridge." -ForegroundColor Green
}
