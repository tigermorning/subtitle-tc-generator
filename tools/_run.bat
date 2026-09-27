@echo off
rem Shared runner. check-*.bat / fix-*.bat set PLATFORM/LANG/KIND/EXTRA and call this.
rem Drag subtitle files or a folder onto one of those .bat icons.
rem
rem NOTE: keep this file ASCII-only. cmd parses batch files byte-wise using the
rem console code page, so non-ASCII text here can break parsing mid-file
rem (a Korean line at the end swallowed the next "echo" and cmd tried to run
rem the message as a command). All Korean output comes from the Python report,
rem which is UTF-8 and prints correctly under chcp 65001.
chcp 65001 >nul
setlocal

set "HERE=%~dp0"
set "REPO=%HERE%.."

if "%~1"=="" (
  echo.
  echo   Drop subtitle files or a folder onto this .bat icon.
  echo.
  pause
  exit /b 1
)

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
  if not defined KSC_PATH set "KSC_PATH=%KSC_NEW%"
)
if not defined PY if exist "%KSC_OLD%\.venv\Scripts\python.exe" (
  set "PY=%KSC_OLD%\.venv\Scripts\python.exe"
  if not defined KSC_PATH set "KSC_PATH=%KSC_OLD%"
)
if not defined PY set "PY=python"

rem Korean correction lane runs too when the corrector is reachable. If it cannot be
rem loaded the checker says so and keeps going with the rule checks.
rem The Korean correction lane is the point of this tool, so it is ON by default
rem whenever the corrector is reachable. SKIP_KOREAN=1 exists only for quick
rem debugging of the rule checks; there is no .bat for it on purpose.
set "KO="
if not defined SKIP_KOREAN if defined KSC_PATH if /i "%LANG%"=="ko" set "KO=--korean --ksc-path "%KSC_PATH%""

set "REPORT=%~dp1checker-report.txt"

echo.
if defined PROFILE (
  echo   profile: %PROFILE% %EXTRA%
) else (
  echo   profile: %PLATFORM% %LANG% %KIND% %EXTRA%
)
echo   report:  %REPORT%
echo.

rem Do NOT redirect stdout here. The Korean lane takes a minute or two to load its
rem morphological analyzer, and a window with no output is indistinguishable from a
rem hung one. The checker prints progress as it goes and writes the report itself
rem via --report.
pushd "%REPO%"
if defined PROFILE (
  "%PY%" -m checker %* --profile "%REPO%\%PROFILE%" -l %LANG% %KO% %EXTRA% --report "%REPORT%"
) else (
  "%PY%" -m checker %* -p %PLATFORM% -l %LANG% -k %KIND% %KO% %EXTRA% --report "%REPORT%"
)
set "RC=%ERRORLEVEL%"
popd

rem Open the report so the result survives the window closing. The console output
rem scrolls away and users press a key to close it - the file is what remains.
if exist "%REPORT%" start "" "%REPORT%"

echo.
if "%RC%"=="0" echo   [OK] no violations
if "%RC%"=="1" echo   [VIOLATIONS] see the report above
if "%RC%"=="2" echo   [ERROR] could not run
echo.
pause
exit /b %RC%
