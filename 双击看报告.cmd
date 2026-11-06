@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Allure Report

rem 1) 找 allure：PATH 命令 → D:\allure → 用户目录，换机器不用改脚本
set "ALLURE="
where allure >nul 2>&1 && set "ALLURE=allure"
if not defined ALLURE if exist "D:\allure\bin\allure.bat" set "ALLURE=D:\allure\bin\allure.bat"
if not defined ALLURE if exist "%USERPROFILE%\allure\bin\allure.bat" set "ALLURE=%USERPROFILE%\allure\bin\allure.bat"

if not defined ALLURE (
    echo [!] 没有找到 allure 命令。
    echo     1. 下载 allure 命令行工具并解压到 D:\allure
    echo     2. 或把 allure\bin 加入 PATH
    echo     3. 只想要一份可读报告的话，直接用浏览器打开 reports\html\index.html
    pause
    exit /b 1
)

rem 2) 没有原始结果就先跑测试
if not exist "reports\allure" (
    echo [!] 还没有 Allure 原始结果。先双击「双击跑测试.cmd」再回来。
    pause
    exit /b 1
)

rem 3) 每次都用最新结果重新生成，避免看到的是一周前的旧报告
echo Generating report from reports\allure ...
call "%ALLURE%" generate "reports\allure" -o "reports\html" --clean
if errorlevel 1 (
    echo [!] 生成失败，检查 reports\allure 里是否有 json 结果。
    pause
    exit /b 1
)

echo Opening Allure report in browser...
echo Close this window to stop the local server.
echo.
call "%ALLURE%" open "reports\html"
timeout /t 3 >nul
exit
