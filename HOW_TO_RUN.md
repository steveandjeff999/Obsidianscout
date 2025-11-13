# How to Run Obsidian Scout

## Recommended Method (IDE or Command Line)

### Option 1: Using Command Prompt or PowerShell
1. Open Command Prompt or PowerShell
2. Navigate to the project directory:
   ```
   cd "c:\Users\steve\OneDrive\Scout2026stuff\Release\OBSIDIAN-Scout Current\Obsidian-Scout"
   ```
3. Activate the virtual environment:
   ```
   .venv\Scripts\activate
   ```
4. Run the application:
   ```
   python run.py
   ```

### Option 2: Using an IDE (VS Code, PyCharm, etc.)
1. Open the project folder in your IDE
2. Select the Python interpreter from `.venv\Scripts\python.exe`
3. Run `run.py` using the IDE's run button or debugger

## Why "Open with Python" May Not Work

When you right-click `run.py` and choose "Open with Python" in Windows Explorer:

1. **Wrong Working Directory**: Python runs with the wrong current directory, causing path issues
2. **Permission Issues**: The script may not have permissions to create the `instance` folder
3. **No Virtual Environment**: It uses your system Python instead of the project's virtual environment

## Troubleshooting Permission Errors

If you see `[WinError 5] Access is denied: 'instance'`:

1. **Check Folder Permissions**: Ensure the project folder is not read-only
   - Right-click the project folder → Properties → Uncheck "Read-only"
   - Apply to all subfolders

2. **Run from Command Line**: Always run from within the project directory:
   ```
   cd "path\to\Obsidian-Scout"
   python run.py
   ```

3. **Check OneDrive Sync**: OneDrive can sometimes lock files
   - Try pausing OneDrive sync temporarily
   - Or move the project to a local folder (not in OneDrive)

4. **Use Alternative Instance Path**: The application now automatically falls back to using your temp directory if it can't create the instance folder in the project directory

## First Time Setup

1. Ensure Python 3.8+ is installed
2. Create virtual environment (if not exists):
   ```
   python -m venv .venv
   ```
3. Activate virtual environment:
   ```
   .venv\Scripts\activate
   ```
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Run the application:
   ```
   python run.py
   ```

## Default Login Credentials

After first run, use these credentials:
- **Username**: superadmin
- **Password**: password
- **Team Number**: 0

**Important**: Change the password after first login!

## Need Help?

Check the diagnostic output when running `run.py` - it shows:
- Current working directory
- Instance path location
- Permission status
- Any errors encountered
