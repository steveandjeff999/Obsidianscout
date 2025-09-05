@echo off
echo Starting ObsidianScout in production mode...
echo.

REM Change to the directory where the batch file is located
cd /d "%~dp0"

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python and try again
    pause
    exit /b 1
)

REM Check if run.py exists
if not exist "run.py" (
    echo ERROR: run.py not found in current directory
    echo Please make sure you're in the correct directory
    pause
    exit /b 1
)

echo Starting server with production settings...
echo Press Ctrl+C to stop the server
echo.

REM Run the Flask application
python run.py

REM If the script exits, show a message
echo.
echo Server has stopped.
pause