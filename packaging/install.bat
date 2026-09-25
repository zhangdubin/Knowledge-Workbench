@echo off
REM ============================================================
REM  KB Workbench - one-click offline installer (Windows)
REM  This is just a launcher; the real work is in install.ps1
REM ============================================================
chcp 65001 >nul 2>&1
setlocal
pushd "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo.
  echo [X] PowerShell not found. Windows 7+ should have it.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%

popd
echo.
if not "%RC%"=="0" (
  echo [X] Install failed with exit code %RC%
) else (
  echo [OK] Done.
)
echo.
pause
exit /b %RC%
