@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m reviewer_app
) else (
    python -m reviewer_app
)

if not %errorlevel%==0 (
    echo.
    echo EDL reviewer tool exited with an error.
    pause
)
endlocal
