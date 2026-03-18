@echo off
REM Obsidian Scout Launcher
REM This batch file ensures the application runs with the correct directory and virtual environment

title Obsidian Scout

echo ========================================
echo Obsidian Scout Launcher
echo ========================================
echo.

REM Change to the script's directory
cd /d "%~dp0"
echo Working directory: %CD%
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo.
    echo Please install Python 3.8 or higher from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo WARNING: Virtual environment not found!
    echo.
    echo Creating virtual environment...
    python -m venv .venv
    
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    
    echo Virtual environment created successfully
    echo.
    echo Installing dependencies...
    .venv\Scripts\pip.exe install -r requirements.txt
    
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
    
    echo Dependencies installed successfully
    echo.
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

echo Virtual environment activated: %VIRTUAL_ENV%
echo.

REM Check if required files exist
if not exist "run.py" (
    echo ERROR: run.py not found!
    echo Make sure you're in the correct directory.
    echo.
    pause
    exit /b 1
)

REM Run the application
echo Starting Obsidian Scout...
echo.
echo You can access the application at:
echo   - http://localhost:8080
echo   - https://localhost:8080 (if SSL enabled)
echo.
echo Press Ctrl+C to stop the server
echo ========================================
echo.

python run.py

REM If python exits, pause so user can see any errors
if errorlevel 1 (
    echo.
    echo ========================================
    echo Application exited with an error
    echo ========================================
    echo.
    echo Check the error messages above for details
    echo Common fixes:
    echo   1. Make sure all dependencies are installed
    echo   2. Check FIXING_ACCESS_DENIED.md for permission issues
    echo   3. Try running test_directory_fix.py to diagnose
)

echo.
pause
