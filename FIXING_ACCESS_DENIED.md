# Fixing "Access Denied" Errors When Running from File Explorer

## The Problem

When you download the repo from GitHub as a ZIP, unzip it, and try to run `run.py` by double-clicking or using "Open with Python", you may encounter:

```
[WinError 5] Access is denied: 'instance'
```

## Why This Happens

1. **Wrong Working Directory**: When you double-click a Python file, Windows runs it from a system directory, not the project directory
2. **OneDrive Sync Issues**: If the project is in OneDrive, the folder may be locked during sync
3. **ZIP Extraction Permissions**: Files extracted from ZIP archives sometimes have restricted permissions
4. **No Virtual Environment**: Double-clicking uses your system Python, not the project's virtual environment with all dependencies

## The Solution

### Quick Fix: Use the Batch File
**Simply double-click `START.bat`** - This file handles everything automatically:
- Sets the correct working directory
- Activates the virtual environment
- Runs the application
- Shows any errors

### Manual Fix: Use Command Line

1. **Open PowerShell or Command Prompt**

2. **Navigate to the project directory:**
   ```powershell
   cd "C:\Users\steve\OneDrive\Scout2026stuff\Release\OBSIDIAN-Scout Current\Obsidian-Scout"
   ```

3. **Activate the virtual environment:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   
   If you get an execution policy error, run:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

4. **Run the application:**
   ```powershell
   python run.py
   ```

### If Still Getting Permission Errors

1. **Move the Project Out of OneDrive**
   - Copy the entire folder to `C:\Projects\Obsidian-Scout`
   - OneDrive can cause file locking issues

2. **Check Folder Permissions**
   - Right-click the project folder
   - Properties → Security tab
   - Ensure your user account has "Full control"

3. **Unblock ZIP Files** (Windows security feature)
   - Right-click the project folder
   - Properties → General tab
   - If there's an "Unblock" checkbox, check it and apply

4. **Run as Administrator** (last resort)
   - Right-click `START.bat`
   - "Run as administrator"

## What the Fix Does

The updated code now:

1. **Checks Directory on Startup**: Shows diagnostic information about the working directory and permissions
2. **Changes to Script Directory**: Automatically changes to the correct directory
3. **Fallback Instance Path**: If it can't create the `instance` folder in the project directory, it creates it in your Windows temp folder
4. **Better Error Messages**: Shows helpful messages instead of just crashing

## Automatic Fallback

If the application can't create the `instance` directory in the project folder, it will automatically use:
```
C:\Users\<YourUsername>\AppData\Local\Temp\obsidian_scout_instance
```

This means the app will still work, but your database will be in a different location.

## Best Practice for Distribution

If you're distributing this app to other users:

1. **Use the batch file**: Tell them to run `START.bat` instead of double-clicking Python files
2. **Include setup instructions**: Point them to `HOW_TO_RUN.md`
3. **Don't run from OneDrive**: Recommend installing to a local directory like `C:\ObsidianScout`

## Verifying It Works

When you run `run.py` (via batch file or command line), you should see:

```
=== Startup Diagnostics ===
Current working directory: C:\...\Obsidian-Scout
Script directory: C:\...\Obsidian-Scout
Python executable: C:\...\Obsidian-Scout\.venv\Scripts\python.exe
Instance path: C:\...\Obsidian-Scout\instance
Instance directory exists: True
Instance directory is writable: True
===========================
```

If the instance directory doesn't exist or isn't writable, you'll see a fallback message.
