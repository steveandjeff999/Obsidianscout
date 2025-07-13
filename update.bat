@echo off
echo Starting update process...
echo =======================

echo Checking if this is a Git repository...
git status >nul 2>&1
if %errorlevel% neq 0 (
    echo Warning: This directory is not a Git repository.
    echo Skipping Git pull step.
    echo If you want Git updates, initialize this as a Git repository first.
) else (
    echo Pulling latest code from Git repository...
    git pull
)

echo Installing/updating Python dependencies...
pip install -r requirements.txt

echo Running database migrations...
flask db upgrade

echo Update completed successfully!
echo =======================
echo A server restart is required to apply all changes.
