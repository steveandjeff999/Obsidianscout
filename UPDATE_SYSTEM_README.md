# Update System - Git Repository Required

The application now uses a Git-only update system powered by GitPython, making it work with any Git repository (not just GitHub).

## 🎯 **Overview**

The update system has been simplified to use only Git repositories for updates. This provides:

- **Universal compatibility** with any Git hosting service (GitHub, GitLab, Bitbucket, etc.)
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

### Git Repository
Your application directory must be a Git repository. If it's not already, you can initialize it using the provided script:
```bash
python init_git.py
```

## 📋 **Setup Instructions**

### 1. Initialize Git Repository (if needed)
If your application directory is not already a Git repository:

```bash
python init_git.py
```

This script will:
- Initialize a Git repository in the current directory
- Add all files and create an initial commit
- Optionally set up a remote origin
- Guide you through the configuration process

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

The system works with any Git hosting service:

- **GitHub** (recommended)
- **GitLab**
- **Bitbucket**
- **Gitea**
- **Self-hosted Git servers**
- Any other Git-compatible hosting service

## 🔄 **How Updates Work**

### Version Checking
1. **GitHub repositories**: Fetches `app_config.json` from the raw content URL
2. **Other repositories**: Uses GitPython to fetch and compare commits
3. **Version comparison**: Uses semantic versioning to determine if updates are available

### Update Process
1. **Backup creation** (if enabled)
2. **Branch switching** (if needed)
3. **Git pull** using GitPython
4. **Dependency installation** (`pip install -r requirements.txt`)
5. **Database migrations** (`flask db upgrade`)
6. **Version update** in local `app_config.json`

## 🛠 **Web Interface Features**

### Repository Status
The web interface shows:
- **Git repository status** (is it a valid Git repo?)
- **Current branch** and last commit
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

### Basic Setup
```bash
# 1. Initialize Git repository
python init_git.py

# 2. Configure repository URL in app_config.json
# 3. Use web interface to configure updates
# 4. Check for updates and install
```

### Manual Git Commands
```bash
# Initialize repository manually
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
- **Commit local changes** before running updates
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

## 🔧 **Troubleshooting**

### Common Issues

#### "Not a Git Repository" Error
```bash
# Solution: Initialize Git repository
python init_git.py
```

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

3. **Initialize Git repository** if needed:
   ```bash
   python init_git.py
   ```

4. **Use web interface** to configure and test updates

## 🎉 **Benefits of Git-Only System**

- **Simplified configuration** - no need to choose between multiple update methods
- **Better reliability** - GitPython provides robust Git operations
- **Universal compatibility** - works with any Git hosting service
- **Enhanced monitoring** - detailed repository status and error reporting
- **Automatic conflict resolution** - handles branch switching and merging
- **Professional workflow** - integrates with standard Git practices 