@echo off
rem Netflix Korean subtitles - check and auto-fix
rem Drag subtitle files or a folder onto this icon.
rem ASCII only - see _run.bat for why.
set "PLATFORM=netflix"
set "LANG=ko"
set "KIND=translation"
set "EXTRA=--fix --fix-timing"
call "%~dp0_run.bat" %*
