@echo off
rem netflix en translation — 검사만
rem 자막 파일이나 폴더를 이 파일 위로 끌어다 놓으세요.
set "PLATFORM=netflix"
set "LANG=en"
set "KIND=translation"
set "EXTRA="
call "%~dp0_run.bat" %*
