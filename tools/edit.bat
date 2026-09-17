@echo off
rem Launch the standalone subtitle editor.
rem
rem NOTE: keep this file ASCII-only. cmd parses batch files byte-wise using the
rem console code page, so non-ASCII text here can break parsing mid-file.
chcp 65001 >nul
setlocal

set "HERE=%~dp0"
set "REPO=%HERE%.."

rem Python: CHECKER_PYTHON env var, then this repo's own .venv, then PATH.
rem Do not borrow the Korean corrector's venv. Create .venv with tools\setup-venv.bat.
set "PY=%CHECKER_PYTHON%"
if not defined PY (
  if exist "%REPO%\.venv\Scripts\pythonw.exe" set "PY=%REPO%\.venv\Scripts\pythonw.exe"
)
if not defined PY set "PY=pythonw"

rem The corrector repo itself is still used by the Korean lane (code, not its venv).
if not defined KSC_PATH (
  if exist "%REPO%\..\korean-subtitle-corrector\subtitle_corrector" set "KSC_PATH=%REPO%\..\korean-subtitle-corrector"
)

cd /d "%REPO%"
start "" "%PY%" -m app
