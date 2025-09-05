@echo off
echo Starting ObsidianScout Server in Terminal Window
echo ================================================
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate" (
    echo ERROR: Virtual environment not found at .venv\Scripts\activate
    echo Please make sure you're in the correct directory and virtual environment is set up.
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate

REM Check if activation was successful
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

REM Set encoding to UTF-8 to handle Unicode characters
chcp 65001 >nul 2>&1

REM Display startup information
echo.
echo Virtual environment activated successfully!
echo Python executable: %cd%\.venv\Scripts\python.exe
echo.
echo Starting ObsidianScout FRC Scouting Platform...
echo Press Ctrl+C to stop the server
echo.

REM Run the server with Python
python run.py

REM Keep window open if server exits unexpectedly
echo.
echo Server has stopped.
pause
