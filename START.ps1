# Obsidian Scout Launcher (PowerShell)
# This script ensures the application runs with the correct directory and virtual environment

$Host.UI.RawUI.WindowTitle = "Obsidian Scout"

Write-Host "========================================"  -ForegroundColor Cyan
Write-Host "Obsidian Scout Launcher" -ForegroundColor Cyan
Write-Host "========================================"  -ForegroundColor Cyan
Write-Host ""

# Change to the script's directory
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath
Write-Host "Working directory: $PWD" -ForegroundColor Yellow
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found"
    }
    Write-Host "Python found: $pythonVersion" -ForegroundColor Green
    Write-Host ""
}
catch {
    Write-Host "ERROR: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Python 3.8 or higher from:" -ForegroundColor Yellow
    Write-Host "https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Make sure to check 'Add Python to PATH' during installation" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if virtual environment exists
$venvPath = Join-Path $scriptPath ".venv"
$venvActivate = Join-Path $venvPath "Scripts\Activate.ps1"

if (-not (Test-Path $venvActivate)) {
    Write-Host "WARNING: Virtual environment not found!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    
    python -m venv .venv
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    Write-Host "Virtual environment created successfully" -ForegroundColor Green
    Write-Host ""
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    
    & "$venvPath\Scripts\pip.exe" install -r requirements.txt
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install dependencies" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    Write-Host "Dependencies installed successfully" -ForegroundColor Green
    Write-Host ""
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan

try {
    & $venvActivate
    Write-Host "Virtual environment activated: $env:VIRTUAL_ENV" -ForegroundColor Green
    Write-Host ""
}
catch {
    Write-Host "ERROR: Failed to activate virtual environment" -ForegroundColor Red
    Write-Host "Try running: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if required files exist
$runPy = Join-Path $scriptPath "run.py"
if (-not (Test-Path $runPy)) {
    Write-Host "ERROR: run.py not found!" -ForegroundColor Red
    Write-Host "Make sure you're in the correct directory." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Run the application
Write-Host "Starting Obsidian Scout..." -ForegroundColor Cyan
Write-Host ""
Write-Host "You can access the application at:" -ForegroundColor Green
Write-Host "  - http://localhost:8080" -ForegroundColor Cyan
Write-Host "  - https://localhost:8080 (if SSL enabled)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

try {
    python run.py
}
catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "Application exited with an error" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check the error messages above for details" -ForegroundColor Yellow
    Write-Host "Common fixes:" -ForegroundColor Cyan
    Write-Host "  1. Make sure all dependencies are installed" -ForegroundColor White
    Write-Host "  2. Check FIXING_ACCESS_DENIED.md for permission issues" -ForegroundColor White
    Write-Host "  3. Try running test_directory_fix.py to diagnose" -ForegroundColor White
}

Write-Host ""
Read-Host "Press Enter to exit"
