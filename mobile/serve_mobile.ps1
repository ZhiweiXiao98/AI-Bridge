param(
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$Root = Join-Path $PSScriptRoot "web"
if (-not (Test-Path (Join-Path $Root "index.html"))) {
    throw "Missing mobile web app: $Root"
}

Write-Host "[mobile] Serving Data Bridge Mobile PWA" -ForegroundColor Cyan
Write-Host "[mobile] URL: http://localhost:$Port" -ForegroundColor Green
Write-Host "[mobile] LAN: use http://<this-computer-ip>:$Port from your phone" -ForegroundColor Yellow

Push-Location $Root
try {
    & (Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\python.exe") -m http.server $Port
}
finally {
    Pop-Location
}
