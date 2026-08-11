@echo off
rem Netflix Korean SDH (official + practice rules) - check only
rem Drop subtitle files or a folder onto this icon.
rem ASCII only - see _run.bat for why.
set "PROFILE=rules/netflix/ko-sdh-practice.yaml"
set "PLATFORM="
set "LANG=ko"
set "KIND="
set "EXTRA="
call "%~dp0_run.bat" %*
