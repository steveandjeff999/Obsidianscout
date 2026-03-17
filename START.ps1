# Obsidian Scout Launcher - Cross-Platform (Windows/Linux)

if ($IsWindows) {
    $Host.UI.RawUI.WindowTitle = "Obsidian Scout"
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Obsidian Scout Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath
Write-Host "Working directory: $PWD" -ForegroundColor Yellow

# Detect OS-specific paths and names
if ($IsWindows) {
    $venvBinPath = Join-Path $scriptPath ".venv\Scripts"
    $pyName = "python.exe"
} else {
    $venvBinPath = Join-Path $scriptPath ".venv/bin"
    $pyName = "python3"
}

$venvPython = Join-Path $venvBinPath $pyName
$venvActivate = Join-Path $venvBinPath "Activate.ps1"
$pipExe = Join-Path $venvBinPath "pip"

# 1. Check if virtual environment exists
if (-not (Test-Path $venvActivate)) {
    Write-Host "WARNING: Virtual environment not found!" -ForegroundColor Yellow
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    
    # Use system python to create the venv initially
    $systemPy = if ($IsWindows) { "python" } else { "python3" }
    & $systemPy -m venv .venv
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        if ($env:TERM -or $IsWindows) { Read-Host "Press Enter to exit" }
        exit 1
    }
}

# 2. Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
try {
    . $venvActivate
    Write-Host "Activated: $env:VIRTUAL_ENV" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: Failed to activate virtual environment" -ForegroundColor Red
    if ($env:TERM -or $IsWindows) { Read-Host "Press Enter to exit" }
    exit 1
}

# 3. Check Requirements Hash
$hashFile = Join-Path $scriptPath ".venv/requirements.hash"
$reqFile = Join-Path $scriptPath "requirements.txt"
$reqHash = (Get-FileHash $reqFile -Algorithm MD5).Hash

$oldHash = ""
if (Test-Path $hashFile) {
    $oldHash = (Get-Content $hashFile -Raw).Trim()
}

if ($reqHash -ne $oldHash) {
    Write-Host "requirements.txt changed - updating dependencies..." -ForegroundColor Yellow
    & $pipExe install -r $reqFile
    if ($LASTEXITCODE -eq 0) { $reqHash | Set-Content $hashFile }
}

# 4. Run the application using the VENV python specifically
$runPy = Join-Path $scriptPath "run.py"
Write-Host "Starting Obsidian Scout..." -ForegroundColor Cyan
Write-Host "Access at: http://localhost:8080" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

try {
    & $venvPython $runPy
}
catch {
    Write-Host "Application crashed or failed to start." -ForegroundColor Red
}

if ($env:TERM -or $IsWindows) {
    Write-Host ""
    Read-Host "Press Enter to exit"
}