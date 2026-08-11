@echo off
rem Netflix Korean subtitles - check + timecode convergence + spotting
rem Drop a subtitle file here. The video with the same name next to it is
rem picked up automatically. Requires ffmpeg on PATH (or FFMPEG_PATH).
rem ASCII only - see _run.bat for why.
set "PLATFORM=netflix"
set "LANG=ko"
set "KIND=translation"
set "EXTRA=--fix-timing --spot"
call "%~dp0_run.bat" %*
