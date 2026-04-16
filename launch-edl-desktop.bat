@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m desktop_app
) else (
    python -m desktop_app
)

if not %errorlevel%==0 (
    echo.
    echo EDL desktop tool exited with an error.
    pause
)
endlocal
