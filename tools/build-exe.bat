@echo off
rem Build the standalone executable.
rem
rem NOTE: keep this file ASCII-only. cmd parses batch files byte-wise using the
rem console code page, so non-ASCII text here can break parsing mid-file.
chcp 65001 >nul
setlocal

set "HERE=%~dp0"
set "REPO=%HERE%.."
cd /d "%REPO%"

set "PY=%CHECKER_PYTHON%"
if not defined PY (
  if exist "%REPO%\..\korean-subtitle-corrector\.venv\Scripts\python.exe" (
    set "PY=%REPO%\..\korean-subtitle-corrector\.venv\Scripts\python.exe"
  )
)
if not defined PY set "PY=python"

if not exist "bin\libmpv-2.dll" (
  echo.
  echo   bin\libmpv-2.dll is missing - video playback needs it.
  echo   Download mpv-dev from:
  echo     https://github.com/shinchiro/mpv-winbuild-cmake/releases
  echo   Extract libmpv-2.dll into the bin folder, then run this again.
  echo.
  pause
  exit /b 1
)

"%PY%" -m PyInstaller --noconfirm --distpath dist --workpath .tmp\build "자막편집기.spec"
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo   Done: dist\자막편집기\자막편집기.exe
echo.
pause
