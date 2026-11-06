@echo off
chcp 65001 >nul
cd /d "%~dp0"
title API Framework - pytest

rem 按优先级找一个「装了 pytest」的 Python：py 启动器 → D:\Python → PATH 里的 python
set "PY="
for %%p in ("py" "D:\Python\python.exe" "python") do (
    if not defined PY (
        %%~p -m pytest --version >nul 2>&1 && set "PY=%%~p"
    )
)

if not defined PY (
    echo.
    echo  [!] 没有找到装了 pytest 的 Python。
    echo      先装依赖：py -m pip install -r requirements.txt
    echo      或看自检报告：py check_env.py
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo  Python : %PY%
echo  Running: %PY% -m pytest --alluredir=reports/allure --clean-alluredir
echo ============================================================
rem 跑测试的同时产出 Allure 原始结果，双击看报告.cmd 才有新数据可看
%PY% -m pytest --alluredir=reports/allure --clean-alluredir
echo.
echo ------------------------------------------------------------
echo  Expected: 28 passed, 3 xfailed
echo  (3 xfailed = mock service does not validate/persist, by design)
echo  Allure 原始结果: reports\allure
echo ------------------------------------------------------------
pause
