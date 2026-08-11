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

rem Python: CHECKER_PYTHON env var, then the Korean corrector venv next door, then PATH.
set "PY=%CHECKER_PYTHON%"
if not defined PY (
  if exist "%REPO%\..\korean-subtitle-corrector\.venv\Scripts\python.exe" (
    set "PY=%REPO%\..\korean-subtitle-corrector\.venv\Scripts\python.exe"
    if not defined KSC_PATH set "KSC_PATH=%REPO%\..\korean-subtitle-corrector"
  )
)
if not defined PY set "PY=python"

rem Korean correction lane runs too when the corrector is reachable. If it cannot be
rem loaded the checker says so and keeps going with the rule checks.
set "KO="
if defined KSC_PATH if /i "%LANG%"=="ko" set "KO=--korean --ksc-path "%KSC_PATH%""

set "REPORT=%~dp1checker-report.txt"

echo.
echo   profile: %PLATFORM% %LANG% %KIND% %EXTRA%
echo   report:  %REPORT%
echo.

pushd "%REPO%"
"%PY%" -m checker %* -p %PLATFORM% -l %LANG% -k %KIND% %KO% %EXTRA% > "%REPORT%" 2>&1
set "RC=%ERRORLEVEL%"
popd

type "%REPORT%"

echo.
if "%RC%"=="0" echo   [OK] no violations
if "%RC%"=="1" echo   [VIOLATIONS] see the report above
if "%RC%"=="2" echo   [ERROR] could not run
echo.
pause
exit /b %RC%
