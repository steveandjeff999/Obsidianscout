# Git-Only Update System

The application now uses a Git-only update system powered by GitPython, making it work with any Git repository (not just GitHub). The system automatically handles Git repository initialization and falls back to direct download when Git is not installed.

## 🎯 **Overview**

The update system has been simplified to use Git repositories for updates with automatic fallback. This provides:

- **Universal compatibility** with any Git hosting service (GitHub, GitLab, Bitbucket, etc.)
- **Automatic Git initialization** - no manual setup required
- **Fallback to direct download** when Git is not installed
- **Reliable updates** using GitPython instead of subprocess calls
- **Better error handling** and status reporting
- **Automatic branch switching** and conflict resolution
- **Repository status monitoring** in the web interface

## 🔧 **Requirements**

### Python Dependencies
The system requires GitPython to be installed:
```bash
pip install GitPython==3.1.44
```

### Git Installation (Optional)
- **With Git**: Full Git functionality with automatic repository initialization
- **Without Git**: Falls back to direct download from GitHub (GitHub repositories only)

## 📋 **Setup Instructions**

### 1. Automatic Setup (Recommended)
The system will automatically:
- Initialize a Git repository if one doesn't exist
- Set up remote origin from your configuration
- Handle updates using Git or direct download as appropriate

### 2. Configure Repository URL
Update your `app_config.json` file with your repository information:

```json
{
    "version": "1.0.0.8",
    "last_updated": "2025-07-08T19:07:00",
    "repository_url": "https://github.com/steveandjeff999/Obsidianscout.git",
    "branch": "main",
    "backup_enabled": true
}
```

### 3. Web Interface Configuration
1. Go to **Admin Settings** → **Application Update**
2. Click **"Configure"** button
3. Enter your repository URL and branch
4. Enable/disable backup creation
5. Save configuration

## 🌐 **Supported Git Hosting Services**

### With Git Installed
- **GitHub** (recommended)
- **GitLab**
- **Bitbucket**
- **Gitea**
- **Self-hosted Git servers**
- Any other Git-compatible hosting service

### Without Git Installed (Direct Download)
- **GitHub** repositories only
- Downloads ZIP files directly from GitHub
- Extracts and installs updates

## 🔄 **How Updates Work**

### With Git Installed
1. **Automatic repository initialization** (if needed)
2. **Backup creation** (if enabled)
3. **Branch switching** (if needed)
4. **Git pull** using GitPython
5. **Dependency installation** (`pip install -r requirements.txt`)
6. **Database migrations** (`flask db upgrade`)
7. **Version update** in local `app_config.json`

### Without Git Installed (Direct Download)
1. **Backup creation** (if enabled)
2. **Download ZIP** from GitHub repository
3. **Extract files** to temporary directory
4. **Copy files** to application directory
5. **Dependency installation** (`pip install -r requirements.txt`)
6. **Database migrations** (`flask db upgrade`)
7. **Version update** in local `app_config.json`

### Version Checking
1. **GitHub repositories**: Fetches `app_config.json` from the raw content URL
2. **Other repositories**: Uses GitPython to fetch and compare commits
3. **Version comparison**: Uses semantic versioning to determine if updates are available

## 🛠 **Web Interface Features**

### Repository Status
The web interface shows:
- **Git installation status** (installed/not installed)
- **Git repository status** (is it a valid Git repo?)
- **Current branch** and last commit (if Git repo)
- **Working directory status** (clean/dirty)
- **Remote URLs** configured

### Configuration
- **Repository URL** configuration
- **Branch selection**
- **Backup settings**
- **Real-time status updates**

### Update Console
- **Real-time output** streaming
- **Colored status messages**
- **Error reporting**
- **Progress tracking**

## 🔒 **Security Features**

### Automatic Backups
- Creates timestamped backups before updates
- Configurable via web interface
- Stored in `backups/` directory

### Version Validation
- Compares version numbers before updating
- Prevents downgrades unless explicitly configured
- Validates file integrity

## 🚀 **Usage Examples**

### Basic Setup (Automatic)
```bash
# 1. Configure repository URL in app_config.json
# 2. Use web interface to configure updates
# 3. Check for updates and install
# 4. System automatically handles Git setup
```

### Manual Git Commands (Optional)
```bash
# Initialize repository manually (if desired)
git init
git add .
git commit -m "Initial commit"

# Add remote origin
git remote add origin https://github.com/steveandjeff999/Obsidianscout.git

# Push to remote
git push -u origin main
```

## ⚠️ **Important Notes**

### Before Updating
- **Commit local changes** before running updates (if using Git)
- **Backup your data** (database, config files, custom modifications)
- **Test in development** environment first

### Repository Requirements
- **app_config.json** must exist in the root of your repository
- **requirements.txt** must be present for dependency updates
- **Database migrations** should be included if schema changes are made

### Error Handling
- **Network issues** are handled gracefully
- **Merge conflicts** will prevent updates (resolve manually)
- **Permission issues** are reported clearly
- **Invalid repositories** are detected and reported
- **Git not installed** automatically falls back to direct download

## 🔧 **Troubleshooting**

### Common Issues

#### "Git is not installed" Warning
- **Solution**: Install Git for better performance
- **Alternative**: System will use direct download automatically

#### "Repository URL not configured" Error
```json
// Update app_config.json
{
    "repository_url": "https://github.com/steveandjeff999/Obsidianscout.git"
}
```

#### "Git pull failed" Error
- Check network connectivity
- Verify repository URL is correct
- Ensure you have proper permissions
- Check for merge conflicts

#### "Failed to install dependencies" Error
- Verify `requirements.txt` exists
- Check Python environment
- Ensure pip is available

### Debug Information
The web interface provides detailed error messages and console output to help diagnose issues.

## 📝 **Migration from Old System**

If you're migrating from the previous multi-method update system:

1. **Remove old configuration** from `app_config.json`:
   ```json
   // Remove these fields:
   "update_method": "direct_download",
   "download_url": "..."
   ```

2. **Add Git configuration**:
   ```json
   {
       "repository_url": "https://github.com/steveandjeff999/Obsidianscout.git",
       "branch": "main",
       "backup_enabled": true
   }
   ```

3. **Use web interface** to configure and test updates
4. **System automatically handles** Git repository initialization

## 🎉 **Benefits of Enhanced Git System**

- **Zero setup required** - automatically initializes Git repositories
- **Fallback support** - works without Git installed
- **Simplified configuration** - no need to choose between multiple update methods
- **Better reliability** - GitPython provides robust Git operations
- **Universal compatibility** - works with any Git hosting service
- **Enhanced monitoring** - detailed repository status and error reporting
- **Automatic conflict resolution** - handles branch switching and merging
- **Professional workflow** - integrates with standard Git practices 