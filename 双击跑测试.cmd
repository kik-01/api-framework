@echo off
cd /d "%~dp0"
title API Framework - pytest

set PY="D:\Python\python.exe"
if not exist %PY% set PY=python

echo ============================================================
echo  Running: pytest -v   (api-framework)
echo ============================================================
%PY% -m pytest -v
echo.
echo ------------------------------------------------------------
echo  Expected: 28 passed, 3 xfailed
echo  (3 xfailed = mock service does not persist/validate, by design)
echo ------------------------------------------------------------
pause
