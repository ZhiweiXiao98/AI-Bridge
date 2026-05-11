@echo off
REM Gradle 预下载脚本 — 国内镜像加速
REM 构建前先运行此脚本，避免构建时卡在下载

set GRADLE_VERSION=8.14
set MIRROR_URL=https://mirrors.cloud.tencent.com/gradle/gradle-%GRADLE_VERSION%-all.zip
set GRADLE_HOME=%USERPROFILE%\.gradle\wrapper\dists\gradle-%GRADLE_VERSION%-all

echo [预下载] Gradle %GRADLE_VERSION% 从腾讯云镜像...
echo 目标: %GRADLE_HOME%

REM 如果已经存在则跳过
if exist "%GRADLE_HOME%\gradle-%GRADLE_VERSION%" (
    echo Gradle %GRADLE_VERSION% 已存在，跳过
    goto :download_deps
)

mkdir "%GRADLE_HOME%" 2>nul
echo 下载中: %MIRROR_URL%
powershell -Command "Invoke-WebRequest -Uri '%MIRROR_URL%' -OutFile '%GRADLE_HOME%\gradle-%GRADLE_VERSION%-all.zip'"
if %ERRORLEVEL% NEQ 0 (
    echo 下载失败！请手动下载:
    echo   %MIRROR_URL%
    echo 放到: %GRADLE_HOME%\
    pause
    exit /b 1
)
echo 下载完成，正在解压...
powershell -Command "Expand-Archive -Path '%GRADLE_HOME%\gradle-%GRADLE_VERSION%-all.zip' -DestinationPath '%GRADLE_HOME%'"
echo Gradle %GRADLE_VERSION% 安装完成

:download_deps
echo.
echo [完成] 可以运行 build_android.bat 开始构建了
pause
