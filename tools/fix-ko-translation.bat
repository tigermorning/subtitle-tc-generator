@echo off
rem netflix ko translation — 검사 + 자동 교정
rem 자막 파일이나 폴더를 이 파일 위로 끌어다 놓으세요.
set "PLATFORM=netflix"
set "LANG=ko"
set "KIND=translation"
set "EXTRA=--fix"
call "%~dp0_run.bat" %*
