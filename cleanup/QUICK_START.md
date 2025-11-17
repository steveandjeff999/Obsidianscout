# Quick Start Guide

## 🚀 Running Obsidian Scout

### ✅ CORRECT WAY - Use the Batch File
```
Double-click: START.bat
```
That's it! The batch file handles everything.

### ✅ CORRECT WAY - Use Command Line
```powershell
# 1. Open PowerShell or Command Prompt
# 2. Navigate to the project
cd "C:\path\to\Obsidian-Scout"

# 3. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Run the application
python run.py
```

### ❌ WRONG WAY - Don't Do This!
- ❌ Double-clicking `run.py`
- ❌ Right-click → "Open with Python"
- ❌ Dragging `run.py` onto Python icon

**Why?** These methods use the wrong directory and won't work!

---

## 🔧 First Time Setup

Before running for the first time:

```powershell
# 1. Open PowerShell in the project directory
# 2. Create virtual environment (if .venv doesn't exist)
python -m venv .venv

# 3. Activate it
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt

# 5. Run the app
python run.py
```

---

## 🔑 Default Login

**First login credentials:**
- Username: `superadmin`
- Password: `password`
- Team: `0`

⚠️ **Change the password immediately after first login!**

---

## ❗ Troubleshooting "Access Denied" Error

If you see: `[WinError 5] Access is denied: 'instance'`

**Quick Fixes:**
1. Use `START.bat` instead of double-clicking Python files
2. Move project out of OneDrive to `C:\ObsidianScout`
3. Right-click project folder → Properties → Uncheck "Read-only"

**Still not working?**
Run the diagnostic test:
```powershell
python test_directory_fix.py
```

---

## 📍 Where Is My Data?

### Normal Operation (No Errors)
Data is stored in:
```
C:\path\to\Obsidian-Scout\instance\
├── scouting.db    (main database)
├── users.db       (user accounts)
├── pages.db       (custom pages)
├── misc.db        (notifications)
└── uploads\       (uploaded files)
```

### Fallback Mode (If Permission Error)
Data is stored in:
```
C:\Users\<YourName>\AppData\Local\Temp\obsidian_scout_instance\
```
The app tells you which location it's using when it starts.

---

## 🌐 Accessing the App

After starting, open your browser and go to:
- **HTTP:** `http://localhost:8080`
- **HTTPS:** `https://localhost:8080` (if SSL is enabled)

---

## 🆘 Getting Help

1. Check `HOW_TO_RUN.md` for detailed instructions
2. Check `FIXING_ACCESS_DENIED.md` for troubleshooting
3. Run `test_directory_fix.py` to diagnose issues
4. Look at the startup diagnostic output from `run.py`

---

## 🎯 Quick Checklist

Before reporting issues, verify:
- [ ] Using `START.bat` or command line (not double-click)
- [ ] In the correct directory (`cd` to project folder)
- [ ] Virtual environment is activated (see `(.venv)` in prompt)
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Not running from OneDrive (or OneDrive sync is paused)
- [ ] Project folder is not read-only

---

## 💡 Pro Tips

- **Bookmark the app:** Once running, bookmark `http://localhost:8080` in your browser
- **Keep it running:** The app stays running until you close the terminal window
- **Multiple users:** Each user needs their own login (create in admin panel)
- **Mobile access:** On the same network, use `http://[your-ip]:8080`

---

**Last Updated:** 2024
**App Version:** Obsidian Scout 2026
