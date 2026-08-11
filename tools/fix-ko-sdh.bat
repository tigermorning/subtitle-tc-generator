@echo off
rem Netflix Korean SDH - check and auto-fix
rem Drag subtitle files or a folder onto this icon.
rem ASCII only - see _run.bat for why.
set "PLATFORM=netflix"
set "LANG=ko"
set "KIND=sdh"
set "EXTRA=--fix --fix-timing"
call "%~dp0_run.bat" %*
