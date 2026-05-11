# Gradle precache script - Chinese mirror acceleration
# Run before build to avoid download stalls

$GRADLE_VERSION = "8.14"
$MIRROR_URL = "https://mirrors.cloud.tencent.com/gradle/gradle-$GRADLE_VERSION-all.zip"
$GRADLE_HOME = "$env:USERPROFILE\.gradle\wrapper\dists\gradle-$GRADLE_VERSION-all"

Write-Host "[precache] Gradle $GRADLE_VERSION" -ForegroundColor Cyan

# Skip if already installed
if (Test-Path "$GRADLE_HOME\gradle-$GRADLE_VERSION") {
    Write-Host "  Already installed, skip." -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $GRADLE_HOME | Out-Null
$ZIP_PATH = "$GRADLE_HOME\gradle-$GRADLE_VERSION-all.zip"

Write-Host "  Downloading from Tencent Cloud mirror..." -ForegroundColor Yellow
Write-Host "  $MIRROR_URL"

try {
    Invoke-WebRequest -Uri $MIRROR_URL -OutFile $ZIP_PATH -UseBasicParsing
    Write-Host "  Download OK" -ForegroundColor Green
} catch {
    Write-Host "  Download FAILED: $_" -ForegroundColor Red
    Write-Host "  Manual download: $MIRROR_URL"
    Write-Host "  Save to: $GRADLE_HOME\"
    exit 1
}

Write-Host "  Extracting..." -ForegroundColor Yellow
Expand-Archive -Path $ZIP_PATH -DestinationPath $GRADLE_HOME -Force
Remove-Item $ZIP_PATH -Force
Write-Host "  Done!" -ForegroundColor Green
