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
set "MINPY=3.10"
set "PY="
set "PYARG=%~1"
set "CAND="

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


rem ------------------------------------------------------------
rem  Find an interpreter. Order matters: the py launcher knows
rem  every installed runtime even when PATH is bare, so it goes
rem  first; then PATH; then the registry (python.org always
rem  writes it); then the two default install directories.
rem ------------------------------------------------------------
:find_py
rem Never let the launcher pop the Store on an unknown version.
set "PYLAUNCHER_ALLOW_INSTALL=0"

rem 0) Explicit override: install.cmd "C:\path\to\python.exe"
if defined PYARG (
  set CAND="%PYARG%"
  call :try
  if defined PY goto :find_done
)

rem 1) py launcher: knows runtimes that are not on PATH.
set "CAND=py -3.13" & call :try
set "CAND=py -3.12" & call :try
set "CAND=py -3.11" & call :try
set "CAND=py -3.10" & call :try
set "CAND=py -3"    & call :try

rem 2) plain PATH lookup
set "CAND=python"  & call :try
set "CAND=python3" & call :try

rem 3) where installers record things
if defined PY goto :find_done
call :scan_registry
if defined PY goto :find_done
call :scan_dirs
:find_done
exit /b 0

:try
rem Two things here are load-bearing:
rem   * the -c script is written inline (not via a variable): a variable that
rem     fails to expand turns this into a bare `py -3.13`, i.e. an interactive
rem     REPL that waits forever - exactly the 10-minute hang we saw.
rem   * `<nul` means even a bare interpreter sees EOF and exits instead of
rem     waiting for input.
if defined PY exit /b 0
%CAND% -c "import sys;raise SystemExit(0 if sys.version_info >= (3,10) else 1)" <nul >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%CAND%"
exit /b 0

:scan_registry
rem python.org (and most installers) record every interpreter here.
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Python\PythonCore" /s /v ExecutablePath 2^>nul ^| findstr /i "ExecutablePath"') do (
  set CAND="%%b"
  call :try
)
if defined PY exit /b 0
for /f "tokens=2,*" %%a in ('reg query "HKLM\Software\Python\PythonCore" /s /v ExecutablePath 2^>nul ^| findstr /i "ExecutablePath"') do (
  set CAND="%%b"
  call :try
)
exit /b 0

:scan_dirs
rem Per-user installs land under %LOCALAPPDATA%\Programs\Python,
rem all-users installs under C:\Program Files - neither needs PATH.
rem uv / conda / scoop matter too: their pythons are often on PATH only in
rem one shell, and the py launcher cannot select them by version.
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
  set CAND="%%~fd\python.exe"
  call :try
)
if defined PY exit /b 0
for /d %%d in ("%ProgramFiles%\Python3*") do (
  set CAND="%%~fd\python.exe"
  call :try
)
if defined PY exit /b 0
for /d %%d in ("%APPDATA%\uv\python\cpython-3*") do (
  set CAND="%%~fd\python.exe"
  call :try
)
if defined PY exit /b 0
for /d %%d in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%USERPROFILE%\scoop\apps\python\current") do (
  set CAND="%%~fd\python.exe"
  call :try
)
if defined PY exit /b 0
for %%d in ("%USERPROFILE%\.local\bin\python.exe") do (
  if exist "%%~fd" (
    set CAND="%%~fd"
    call :try
  )
)
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
echo   [!] No Python %MINPY%+ found on this machine.
echo.
echo   What I tried: py -3.13 / -3.12 / -3.11 / -3.10 / -3, python, python3,
echo                 the registry, and the usual install folders (python.org,
echo                 uv, conda, scoop).
echo.
echo   What is actually on this machine (paste this whole block back
echo   if you think Python IS installed):
echo.
echo   ---- cut here ----
where python 2>nul
where py 2>nul
python -V 2>nul
py -0p 2>nul
echo   ---- cut here ----
echo.
echo   1. The download page is opening: install Python %MINPY% or newer,
echo      and TICK "Add python.exe to PATH" during install.
echo   2. Then double-click this file again.
echo.
echo   Already have Python %MINPY%+ but this still says "not found"?
echo   Point at it directly, e.g.:
echo       install.cmd "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
echo.
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
