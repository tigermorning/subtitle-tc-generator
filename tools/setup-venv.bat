@echo off
rem Create this repo's own virtual environment (.venv) and install packages.
rem Run once after cloning, and again when requirements change.
rem
rem NOTE: keep this file ASCII-only. cmd parses batch files byte-wise using the
rem console code page, so non-ASCII text here can break parsing mid-file.
rem Why this exists (in Korean): requirements-venv.txt header.
chcp 65001 >nul
setlocal

set "HERE=%~dp0"
set "REPO=%HERE%.."
cd /d "%REPO%"

rem Python for creating the venv: BASE_PYTHON env var, then py launcher 3.14, then PATH.
set "BASE=%BASE_PYTHON%"
if not defined BASE (
  py -3.14 -V >nul 2>&1 && set "BASE=py -3.14"
)
if not defined BASE set "BASE=python"

if not exist ".venv\Scripts\python.exe" (
  echo   creating .venv with %BASE%
  %BASE% -m venv .venv
  if errorlevel 1 goto :fail
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements-venv.txt
if errorlevel 1 goto :fail

rem The Korean lane imports the corrector in-process, so its packages go here too.
rem The list belongs to the corrector repo; read it, do not copy it.
set "KSC=%KSC_PATH%"
if not defined KSC set "KSC=%REPO%\..\korean-subtitle-corrector"
if exist "%KSC%\requirements.txt" (
  ".venv\Scripts\python.exe" -m pip install -r "%KSC%\requirements.txt"
  if errorlevel 1 goto :fail
) else (
  echo   Korean corrector not found at %KSC% - Korean lane packages skipped.
)

echo.
echo   [OK] .venv is ready
exit /b 0

:fail
echo.
echo   [ERROR] setup failed
exit /b 1
