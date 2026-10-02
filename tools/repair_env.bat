@echo off
chcp 65001 >nul
title AI Bridge 环境自动修复工具

echo ===================================================
echo       🛠️ AI Bridge 环境自动修复 (Environment Repair)
echo ===================================================
echo.
echo [1/4] 正在检测旧环境...

if exist ".venv" (
    echo    - 发现旧环境，正在清除 (这可能需要几秒钟)...
    rmdir /s /q ".venv"
    echo    - 旧环境已清除。
) else (
    echo    - 未发现旧环境，准备全新安装。
)

echo.
echo [2/4] 正在创建新环境...
python -m venv .venv
if %errorlevel% neq 0 (
    echo ❌ 创建失败！请检查您是否安装了 Python 3.10+ 并添加到了 PATH。
    pause
    exit /b
)
echo    - 虚拟环境创建成功。

echo.
echo [3/4] 正在激活并升级 Pip...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo    - Pip 升级完成。

echo.
echo [4/4] 正在安装依赖 (requirements.txt)...
echo    - 这可能需要几分钟，取决于网络速度...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

if %errorlevel% neq 0 (
    echo.
    echo ❌ 依赖安装失败！请检查网络或 requirements.txt 文件。
    pause
    exit /b
)

echo.
echo ===================================================
echo ✅ 修复完成！环境已重生。
echo 您现在可以直接运行 start_server.py 了。
echo ===================================================
pause
