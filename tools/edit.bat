@echo off
rem Launch the standalone subtitle editor.
rem
rem NOTE: keep this file ASCII-only. cmd parses batch files byte-wise using the
rem console code page, so non-ASCII text here can break parsing mid-file.
chcp 65001 >nul
setlocal

set "HERE=%~dp0"
set "REPO=%HERE%.."

rem Python: CHECKER_PYTHON env var, then the Korean corrector venv next door.
set "PY=%CHECKER_PYTHON%"
if not defined PY (
  if exist "%REPO%\..\korean-subtitle-corrector\.venv\Scripts\pythonw.exe" (
    set "PY=%REPO%\..\korean-subtitle-corrector\.venv\Scripts\pythonw.exe"
    if not defined KSC_PATH set "KSC_PATH=%REPO%\..\korean-subtitle-corrector"
  )
)
if not defined PY set "PY=pythonw"

cd /d "%REPO%"
start "" "%PY%" -m app
