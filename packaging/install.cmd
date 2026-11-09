@echo off
rem ============================================================
rem  campus-auth installer - ALL TEXT HERE IS ASCII ON PURPOSE.
rem  cmd.exe reads .cmd files with the OEM code page, so UTF-8
rem  Chinese would turn into garbage. All Chinese comes from
rem  `campus-auth setup` (Python) and the .txt files next to us.
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title campus-auth setup

set "PYZ=%~dp0campus-auth.pyz"
set "SUMS=%~dp0SHA256SUMS"
set "PY="

echo.
echo   campus-auth setup
echo   ----------------------------------------------------
echo.

call :find_py
if not defined PY goto :no_python

if not exist "%PYZ%" goto :no_pyz
if exist "%SUMS%" (
  call :verify
  if errorlevel 1 goto :bad_sum
) else (
  echo   [!] SHA256SUMS missing - continuing without a check.
)

echo   Python: %PY%
echo.
rem A second run keeps the account and only re-asks the password,
rem so double-clicking twice must not dead-end on "already exists".
if exist "%APPDATA%\campus-auth\config.toml" (
  %PY% "%PYZ%" setup --force
) else (
  %PY% "%PYZ%" setup
)
if errorlevel 1 goto :failed

echo.
echo   Done. You can close this window, or run again later.
echo.
pause
exit /b 0


:find_py
rem Prefer the py launcher, then plain python; both must be 3.11+.
where py >nul 2>nul
if errorlevel 1 goto :try_python
py -3 -c "import sys;raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
if errorlevel 1 goto :try_python
set "PY=py -3"
exit /b 0

:try_python
where python >nul 2>nul
if errorlevel 1 exit /b 0
python -c "import sys;raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=python"
exit /b 0


:verify
set "WANT="
for /f "tokens=1" %%a in ('findstr /i "campus-auth.pyz" "%SUMS%"') do set "WANT=%%a"
if not defined WANT exit /b 1
set "GOT="
for /f "skip=1 tokens=*" %%a in ('certutil -hashfile "%PYZ%" SHA256') do (
  if not defined GOT set "GOT=%%a"
)
if not defined GOT exit /b 1
set "GOT=%GOT: =%"
if /i "%GOT%"=="%WANT%" (
  echo   [ok] SHA256 verified.
  exit /b 0
)
exit /b 1


:no_python
echo   [!] Python 3.11+ not found on this machine.
echo.
echo       1. The page is opening: download Python, and TICK
echo          "Add python.exe to PATH" during install.
echo       2. Then double-click this file again.
echo.
echo       (Chinese guide: install-guide is opening too.)
start "" notepad "%~dp0install-guide.txt"
start "" https://www.python.org/downloads/
pause
exit /b 3


:no_pyz
echo   [!] campus-auth.pyz not found next to this file.
echo       Unzip the whole folder first, then run this file again.
pause
exit /b 2


:bad_sum
echo   [!] SHA256 mismatch: the .pyz was changed or truncated.
echo       Download the folder again, or continue by unpacking manually.
pause
exit /b 4


:failed
echo.
echo   [!] setup exited with an error. Scroll up for the reason.
echo       Log a bug with: campus-auth --version, and `campus-auth doctor`.
pause
exit /b 1
