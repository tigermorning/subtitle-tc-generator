@echo off
rem Coupang Play Korean SDH - check only
rem Drop subtitle files or a folder onto this icon.
rem ASCII only - see _run.bat for why.
set "PROFILE=rules/coupang/ko-sdh.yaml"
set "PLATFORM="
set "LANG=ko"
set "KIND="
set "EXTRA="
call "%~dp0_run.bat" %*
