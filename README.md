# Obsidian Scout

A comprehensive FRC (FIRST Robotics Competition) scouting platform with real-time data collection, analytics, and team collaboration features.

## 🚀 Quick Start

### Running the Application

**The easiest way to run Obsidian Scout:**
batch
Double-click: START.bat


This automatically handles virtual environment setup and starts the server.

**Or use the command line:**

powershell
# Navigate to the project directory
cd "path\to\Obsidian-Scout"

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run the application
python run.py


**Access the app at:** `http://localhost:8080`

### ⚠️ Important: Don't Double-Click run.py!

**DO NOT** double-click `run.py` or use "Open with Python" from File Explorer.
This causes permission errors. Always use `START.bat` or the command line method above.

## 📋 First Time Setup

1. **Install Python 3.12+** from [python.org](https://www.python.org/downloads/)
   - Make sure to check "Add Python to PATH" during installation

2. **Download/Clone this repository**

3. **Run START.bat** - It will automatically:
   - Create the virtual environment
   - Install all dependencies
   - Start the application

**Manual Setup (if needed):**
powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py


## 🔑 Default Credentials

On first run, use these credentials:
- **Username:** `superadmin`
- **Password:** `password`
- **Team:** `0`

⚠️ **Change the password immediately after first login!**

## 🛠️ Features

- **Match Scouting**: Real-time data collection during matches
- **Pit Scouting**: Detailed team information and robot capabilities
- **Analytics Dashboard**: Comprehensive statistics and visualizations
- **Team Comparison**: Compare multiple teams side-by-side
- **Alliance Selection**: Tools for strategic alliance selection
- **Match Predictions**: AI-powered match outcome predictions
- **Mobile Support**: Responsive design for tablets and phones
- **Offline Mode**: Continue scouting even without internet
- **Multi-Team Support**: Support for multiple scouting teams
- **Real-Time Sync**: Automatic data synchronization
- **Custom Reports**: Generate custom analytics reports
- **Export Data**: Export to CSV, Excel, JSON formats

## 📱 Mobile Access

To access from other devices on your network:

1. Find your computer's IP address:
   powershell ipconfig
   
   Look for "IPv4 Address" (e.g., 192.168.1.100)

2. On other device, open browser and go to:

   https://[your-ip]:8080

   Example: `https://192.168.1.100:8080`




### Virtual Environment Issues

If the virtual environment doesn't activate:
```powershell
# Allow PowerShell scripts
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Then try again
.\.venv\Scripts\Activate.ps1
```

### Port Already in Use

If port 8080 is already in use, edit `run.py` and change the port:
python
port = int(os.environ.get('PORT', 8080))  # Change 8080 to another port


### Database Locked

If you see "database is locked" errors:
1. Make sure OneDrive sync is paused
2. Move the project to a local folder (not in OneDrive/Dropbox)
3. Restart the application



## 🗂️ Project Structure

```
Obsidian-Scout/
├── app/                    # Main application code
│   ├── routes/            # Web routes and views
│   ├── models.py          # Database models
│   ├── utils/             # Utility functions
│   └── static/            # CSS, JavaScript, images
├── instance/              # Database files (created on first run)
│   ├── scouting.db       # Main database
│   ├── users.db          # User accounts
│   └── uploads/          # Uploaded files
├── START.bat             # Easy launcher for Windows
├── run.py                # Main application entry point
├── requirements.txt      # Python dependencies
└── app_config.json       # Configuration file
```

## 🔐 Security Notes

- **Change default password** immediately after first login
- **Use HTTPS** for production deployments
- **Regular backups** of the instance/ folder
- **Firewall rules** if exposing to internet
- **Strong passwords** for all user accounts

## 🌐 API Access

Obsidian Scout includes a REST API for external integrations:

- **Mobile API**: `/mobile/api/v1/...`
- **Sync API**: `/sync/api/...`
- **Real-time API**: `/realtime/...`

See API documentation in `docs/` folder for details.

## 🎯 Configuration

Main configuration file: `app_config.json`

Key settings:
- **JWT_SECRET_KEY**: Secret for authentication tokens
- **VAPID_PRIVATE_KEY**: For push notifications
- **API Keys**: FRC API and The Blue Alliance credentials

Edit these before deploying to production!

## 🐛 Known Issues

1. **OneDrive Sync**: May cause database locking issues
   - **Solution**: Move project to local folder or pause sync

2. **Windows Defender**: May slow down database operations
   - **Solution**: Add exception for project folder

3. **File Explorer Launch**: Double-clicking run.py causes permission errors
   - **Solution**: Use START.bat instead

## 🤝 Contributing

This is a private/team project. For issues or suggestions, contact the development team.

## 📄 License

Copyright © 2024-2026 Obsidian Scout Development Team

## 🆘 Getting Help

1. **Check documentation** in this folder
2. **Run diagnostics**: `python test_directory_fix.py`
3. **Review startup output** for error messages
4. **Check the logs** in the terminal window
5. **Contact team admin** for access issues

## 🔄 Updates

To update the application:

1. **Backup your data** (copy the `instance/` folder)
2. **Download new version** from repository
3. **Replace files** (keep your `instance/` and `app_config.json`)
4. **Run START.bat** to apply updates

## ⚡ Performance Tips

- **Close unused tabs** in the web interface
- **Regular database maintenance** (backup and optimize)
- **Limit concurrent users** during competitions
- **Use local installation** (not on network drive)
- **Disable antivirus scanning** for project folder (if safe)

## 📊 Data Management

**Backup Your Data:**
The `instance/` folder contains all your scouting data. Back it up regularly:
```powershell
# Create backup
xcopy instance instance_backup /E /I /Y
```

**Export Data:**
Use the web interface: Data → Export → Choose format (CSV/Excel/JSON)

**Reset Database:**
To start fresh, delete the `instance/` folder. It will be recreated on next run.

---

**Version:** 2026 Season
**Last Updated:** November 2025

For more help, see the documentation files or run `python test_directory_fix.py` for diagnostics.
