@echo off
rem 공통 실행부. check-*.bat / fix-*.bat 가 KIND·LANG·EXTRA를 정하고 이 파일을 부른다.
rem 자막 파일이나 폴더를 .bat 아이콘 위로 끌어다 놓으면 된다.
chcp 65001 >nul
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "REPO=%HERE%.."

if "%~1"=="" (
  echo.
  echo   자막 파일이나 폴더를 이 파일 위로 끌어다 놓으세요.
  echo.
  pause
  exit /b 1
)

rem 파이썬 찾기: 환경변수 > 한국어 교정기 가상환경 > PATH
set "PY=%CHECKER_PYTHON%"
if not defined PY (
  if exist "%REPO%\..\korean-subtitle-corrector\.venv\Scripts\python.exe" (
    set "PY=%REPO%\..\korean-subtitle-corrector\.venv\Scripts\python.exe"
    if not defined KSC_PATH set "KSC_PATH=%REPO%\..\korean-subtitle-corrector"
  )
)
if not defined PY set "PY=python"

rem 교정기 경로를 알면 한국어 교정 레인도 함께 돌린다.
rem 못 불러오면 검사기가 "건너뜁니다"라고 알리고 규정 검사만 계속한다.
set "KO="
if defined KSC_PATH if /i "%LANG%"=="ko" set "KO=--korean --ksc-path "%KSC_PATH%""

set "REPORT=%~dp1checker-report.txt"

echo.
echo   프로파일: %PLATFORM% %LANG% %KIND%   %EXTRA%
echo   리포트:   %REPORT%
echo.

pushd "%REPO%"
"%PY%" -m checker %* -p %PLATFORM% -l %LANG% -k %KIND% %KO% %EXTRA% > "%REPORT%" 2>&1
set "RC=%ERRORLEVEL%"
popd

type "%REPORT%"

echo.
if "%RC%"=="0" echo   [통과] 위반 없음
if "%RC%"=="1" echo   [위반 있음] 위 내용을 확인하세요
if "%RC%"=="2" echo   [오류] 실행하지 못했습니다
echo.
pause
exit /b %RC%
