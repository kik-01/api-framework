@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Allure Report

if not exist "reports\html\index.html" (
    echo [!] Report not found. Run this first:
    echo     D://Python//python.exe -m pytest --alluredir=./reports/allure
    echo     D://allure//bin//allure.bat generate ./reports/allure -o ./reports/html --clean
    pause
    exit /b 1
)

echo Opening Allure report in browser...
echo Close this window to stop the local server.
echo.
start "" "D://allure//bin//allure.bat" open "reports\html"
timeout /t 3 >nul
exit
