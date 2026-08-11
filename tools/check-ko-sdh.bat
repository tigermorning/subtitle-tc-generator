@echo off
rem Netflix Korean SDH - check only
rem Drag subtitle files or a folder onto this icon.
rem ASCII only - see _run.bat for why.
set "PLATFORM=netflix"
set "LANG=ko"
set "KIND=sdh"
set "EXTRA="
call "%~dp0_run.bat" %*
