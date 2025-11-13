@echo off
REM Obsidian Scout Launcher
REM This batch file ensures the application runs with the correct directory and virtual environment

echo ========================================
echo Obsidian Scout Launcher
echo ========================================
echo.

REM Change to the script's directory
cd /d "%~dp0"
echo Working directory: %CD%
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run setup first or create the virtual environment:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Check if activation was successful
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

echo Virtual environment activated
echo.

REM Run the application
echo Starting Obsidian Scout...
echo.
python run.py

REM If python exits, pause so user can see any errors
if errorlevel 1 (
    echo.
    echo ========================================
    echo Application exited with an error
    echo ========================================
)

echo.
pause
