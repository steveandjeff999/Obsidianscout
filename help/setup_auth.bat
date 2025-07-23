@echo off
echo ===================================================
echo ObsidianScout Authentication System Setup Guide
echo ===================================================
echo.
echo This script will guide you through setting up the authentication system.
echo.
echo Step 1: Installing dependencies
echo --------------------------------------------------
echo Please make sure you've already installed the required packages:
echo.
echo    pip install -r requirements.txt
echo.
echo Press any key to continue...
pause > nul

echo.
echo Step 2: Initialize the authentication system
echo --------------------------------------------------
echo This step will create the necessary database tables and create the admin user.
echo.
echo Running: python init_auth.py
echo.
echo Username: admin
echo Password: password
echo.
echo Press any key to initialize the authentication system...
pause > nul
python init_auth.py

echo.
echo Step 3: Fixing potential database issues
echo --------------------------------------------------
echo Running email field fix script:
echo.
echo    python fix_emails.py
echo.
echo Press any key to run the fix script...
pause > nul
python fix_emails.py

echo.
echo Step 4: Running the application
echo --------------------------------------------------
echo You can now run the application with:
echo.
echo    python run.py
echo.
echo When you access the application, you'll be asked to login.
echo Use the admin credentials created in the previous step:
echo.
echo Username: admin
echo Password: password
echo.
echo Press any key to launch the application...
pause > nul
python run.py
