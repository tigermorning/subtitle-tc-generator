@echo off
rem Push both repositories (subtitle & TC generator + Korean corrector).
rem Double-click this file, or run it from a terminal.
rem
rem NOTE: keep this file ASCII-only. cmd parses batch files byte-wise using the
rem console code page, so non-ASCII text here can break parsing mid-file.
rem Set DRYRUN to anything to see what would happen without pushing.
chcp 65001 >nul
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "EDITOR=%HERE%.."
set "CORRECTOR=%HERE%..\..\korean-subtitle-corrector"

set "FAILED="
call :push "subtitle-tc-generator" "%EDITOR%"
call :push "korean-subtitle-corrector" "%CORRECTOR%"

echo.
if defined FAILED (
  echo   Some pushes did not finish:!FAILED!
  echo   Read the messages above. A login prompt may be waiting in another window.
) else (
  echo   Done. Both repositories are up to date with their remotes.
)
echo.
pause
exit /b 0


:push
rem %~1 = label, %~2 = path
echo.
echo ============================================================
echo   %~1
echo ============================================================
if not exist "%~2\.git" (
  echo   Not a git repository: %~2
  set "FAILED=!FAILED! %~1"
  goto :eof
)

pushd "%~2"

rem Uncommitted work is not an error, but pushing will not include it.
for /f "delims=" %%D in ('git status --porcelain') do (
  echo   Uncommitted changes are present. They will NOT be pushed:
  git status --short
  echo.
  goto :counted
)
:counted

set "AHEAD="
for /f %%C in ('git rev-list --count @{u}..HEAD 2^>nul') do set "AHEAD=%%C"
if not defined AHEAD (
  echo   No upstream branch is set for this branch.
  echo   Run once:  git push -u origin HEAD
  set "FAILED=!FAILED! %~1"
  popd
  goto :eof
)
if "%AHEAD%"=="0" (
  echo   Nothing to push - already up to date.
  popd
  goto :eof
)

echo   %AHEAD% commit^(s^) to push:
git log --oneline @{u}..HEAD
echo.

rem Any value at all means dry run. Comparing to "1" is too easy to get wrong:
rem `set DRYRUN=1 && push-all.bat` puts a trailing space in the NAME, the compare
rem silently fails, and the "dry" run pushes for real (this happened).
if defined DRYRUN (
  echo   DRYRUN is set - stopping before the actual push.
  popd
  goto :eof
)

git push
if errorlevel 1 (
  echo.
  echo   Push failed for %~1.
  set "FAILED=!FAILED! %~1"
) else (
  echo   Pushed.
)
popd
goto :eof
