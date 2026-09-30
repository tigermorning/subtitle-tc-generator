@echo off
rem Launch the standalone subtitle editor.
rem
rem NOTE: keep this file ASCII-only. cmd parses batch files byte-wise using the
rem console code page, so non-ASCII text here can break parsing mid-file.
chcp 65001 >nul
setlocal

set "HERE=%~dp0"
set "REPO=%HERE%.."

rem Python with PySide6: CHECKER_PYTHON, then PYSIDE_PYTHON, then the Korean corrector
rem venv (current layout ..\..\korean-subtitle-corrector-project\korean-subtitle-corrector,
rem then the old sibling layout ..\korean-subtitle-corrector), then PATH.
rem The corrector folder moved once and a single hard-coded path silently fell back to
rem a python without PySide6, so every known layout is checked.
set "PY=%CHECKER_PYTHON%"
if not defined PY if defined PYSIDE_PYTHON if exist "%PYSIDE_PYTHON%" (
  for %%D in ("%PYSIDE_PYTHON%") do if exist "%%~dpDpythonw.exe" (set "PY=%%~dpDpythonw.exe") else (set "PY=%PYSIDE_PYTHON%")
)
if defined PYSIDE_PYTHON if not exist "%PYSIDE_PYTHON%" echo   PYSIDE_PYTHON=%PYSIDE_PYTHON% does not exist - looking elsewhere.
set "KSC_NEW=%REPO%\..\..\korean-subtitle-corrector-project\korean-subtitle-corrector"
set "KSC_OLD=%REPO%\..\korean-subtitle-corrector"
if not defined PY if exist "%KSC_NEW%\.venv\Scripts\pythonw.exe" (
  set "PY=%KSC_NEW%\.venv\Scripts\pythonw.exe"
  if not defined KSC_PATH set "KSC_PATH=%KSC_NEW%"
)
if not defined PY if exist "%KSC_OLD%\.venv\Scripts\pythonw.exe" (
  set "PY=%KSC_OLD%\.venv\Scripts\pythonw.exe"
  if not defined KSC_PATH set "KSC_PATH=%KSC_OLD%"
)
if not defined PY set "PY=pythonw"

cd /d "%REPO%"
start "" "%PY%" -m app
