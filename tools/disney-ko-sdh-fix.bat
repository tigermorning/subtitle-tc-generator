@echo off
rem Disney+ Korean SDH - check and fix
rem Drop subtitle files or a folder onto this icon.
rem ASCII only - see _run.bat for why.
set "PROFILE=rules/disney/ko-sdh.yaml"
set "PLATFORM="
set "LANG=ko"
set "KIND="
set "EXTRA=--fix --fix-timing"
call "%~dp0_run.bat" %*
