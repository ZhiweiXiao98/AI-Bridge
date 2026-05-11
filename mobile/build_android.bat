@echo off
REM AI Bridge Mobile — Android APK 构建脚本 (国内加速版)
REM 前置条件: 已安装依赖 (pip install -r requirements.txt)

echo [AI Bridge Mobile] 开始构建 Android APK...

cd /d "%~dp0"

REM 清理上次失败的构建缓存
echo 清理旧缓存...
if exist "build\flutter\build" rmdir /s /q "build\flutter\build"

REM 应用国内镜像配置
echo 应用阿里云 Gradle 镜像...
mkdir "%USERPROFILE%\.gradle\init.d" 2>nul
echo allprojects { repositories { maven { url "https://maven.aliyun.com/repository/google" }; maven { url "https://maven.aliyun.com/repository/public" }; google(); mavenCentral() } } > "%USERPROFILE%\.gradle\init.d\repos.gradle"

REM 构建 APK
echo 开始打包...
flet build apk --project "AI Bridge" --org com.aibridge --product "AI Bridge Mobile"

echo.
echo 构建完成！APK 位于 build/apk/ 目录
pause
