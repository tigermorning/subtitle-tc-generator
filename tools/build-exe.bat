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

rem Python with PySide6: CHECKER_PYTHON, then PYSIDE_PYTHON, then the Korean corrector
rem venv (current layout ..\..\korean-subtitle-corrector-project\korean-subtitle-corrector,
rem then the old sibling layout ..\korean-subtitle-corrector), then PATH.
rem The corrector folder moved once and a single hard-coded path silently fell back to
rem a python without PySide6, so every known layout is checked.
set "PY=%CHECKER_PYTHON%"
if not defined PY if defined PYSIDE_PYTHON if exist "%PYSIDE_PYTHON%" set "PY=%PYSIDE_PYTHON%"
if defined PYSIDE_PYTHON if not exist "%PYSIDE_PYTHON%" echo   PYSIDE_PYTHON=%PYSIDE_PYTHON% does not exist - looking elsewhere.
set "KSC_NEW=%REPO%\..\..\korean-subtitle-corrector-project\korean-subtitle-corrector"
set "KSC_OLD=%REPO%\..\korean-subtitle-corrector"
if not defined PY if exist "%KSC_NEW%\.venv\Scripts\python.exe" (
  set "PY=%KSC_NEW%\.venv\Scripts\python.exe"
)
if not defined PY if exist "%KSC_OLD%\.venv\Scripts\python.exe" (
  set "PY=%KSC_OLD%\.venv\Scripts\python.exe"
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

rem The spec file name is non-ASCII, so it must NOT appear in this file.
rem A single non-ASCII byte shifts cmd's byte-wise parsing and breaks the rest
rem of the script (seen 2026-08-12: the libmpv check exploded into garbage
rem commands). Find it at run time instead.
for %%F in (*.spec) do set "SPEC=%%F"
if not defined SPEC (
  echo No .spec file found in %REPO%.
  pause
  exit /b 1
)

"%PY%" -m PyInstaller --noconfirm --distpath dist --workpath .tmp\build "%SPEC%"
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo   Done. The program is in the dist folder.
echo.
pause
