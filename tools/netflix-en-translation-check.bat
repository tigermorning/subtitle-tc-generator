@echo off
rem Netflix English subtitles - check only
rem Drag subtitle files or a folder onto this icon.
rem ASCII only - see _run.bat for why.
set "PLATFORM=netflix"
set "LANG=en"
set "KIND=translation"
set "EXTRA="
call "%~dp0_run.bat" %*
