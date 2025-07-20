# Update System - No Git Repository Required

The application now supports multiple update methods, allowing you to update without requiring a Git repository.

## 🎯 **Update Methods**

### 1. **Git Repository** (Original Method)
- Updates from a Git repository (GitHub, GitLab, etc.)
- Requires the application to be a Git repository
- Pulls latest changes and updates dependencies

### 2. **Direct Download** (New Method)
- Downloads updates from a direct URL
- No Git repository required
- Downloads ZIP files and extracts them
- Perfect for hosting updates on any web server

### 3. **Manual Updates** (New Method)
- Updates from a local `manual_updates` directory
- No internet connection required
- Place update files in the directory and run update
- Ideal for air-gapped environments

## 🔧 **Configuration**

### Default Configuration
The application is now configured to use **Direct Download** as the default update method, pointing to the GitHub repository ZIP file.

### Web Interface
1. Go to **Admin Settings** → **Application Update**
2. Click **"Change Method"** button
3. Select your preferred update method
4. Configure method-specific settings
5. Save configuration

### Manual Configuration
Edit `app_config.json` in the root directory:

```json
{
  "version": "1.0.0.8",
  "update_method": "direct_download",
  "backup_enabled": true,
  "download_url": "https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip",
  "repository_url": "https://github.com/steveandjeff999/Obsidianscout.git",
  "branch": "main"
}
```

## 📁 **Manual Updates Setup**

### Directory Structure
Create a `manual_updates` directory in your application root:

```
5454Scout2026/
├── manual_updates/
│   ├── app/
│   ├── config/
│   ├── requirements.txt
│   ├── app_config.json
│   └── ... (other files)
├── app/
├── config/
└── ... (existing files)
```

### How to Use Manual Updates
1. **Download** the latest version files
2. **Extract** them to the `manual_updates` directory
3. **Run** the update from the web interface
4. The system will copy files and update dependencies

## 🌐 **Direct Download Setup**

### Server Requirements
- Web server hosting ZIP files
- `app_config.json` accessible via HTTP
- ZIP file containing the complete application

### URL Structure
- **ZIP file**: `https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip`
- **Config file**: `https://raw.githubusercontent.com/steveandjeff999/Obsidianscout/main/app_config.json`

### Configuration
```json
{
  "update_method": "direct_download",
  "download_url": "https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip"
}
```

### GitHub Integration
The system automatically handles GitHub ZIP URLs by:
- Converting ZIP URLs to raw content URLs for version checking
- Properly extracting GitHub repository structure
- Supporting both GitHub ZIP downloads and raw content access

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

### Manual Updates (Recommended for Non-Git Users)
1. **Download** latest version from releases
2. **Extract** to `manual_updates/` directory
3. **Configure** update method to "Manual"
4. **Run** update from web interface

### Direct Download (Default)
1. **System** is pre-configured with GitHub ZIP URL
2. **No configuration** required for GitHub updates
3. **Automatic** version checking and updates
4. **Run** update from web interface

### Git Repository (Original)
1. **Initialize** Git repository
2. **Configure** repository URL
3. **Set** update method to "Git"
4. **Run** update from web interface

## 🔧 **Troubleshooting**

### Common Issues

**"Manual updates directory not found"**
- Create `manual_updates` directory in application root
- Ensure proper file structure

**"Download failed"**
- Check download URL is accessible
- Verify ZIP file format
- Check network connectivity

**"Backup failed"**
- Ensure write permissions in application directory
- Check available disk space

### Logs
Update logs are displayed in real-time in the web interface console.

## 📋 **Migration from Git-Only System**

If you were previously using Git-only updates:

1. **Backup** your current configuration
2. **Choose** your preferred update method
3. **Configure** the new method settings
4. **Test** with a small update first
5. **Switch** to the new method permanently

## 🎉 **Benefits**

✅ **No Git repository required** for most methods  
✅ **Multiple update options** for different environments  
✅ **Automatic backups** before updates  
✅ **Web-based configuration** interface  
✅ **Real-time update progress** monitoring  
✅ **Version validation** and comparison  
✅ **Air-gapped environment** support  
✅ **Simple file-based updates**  

The new update system provides flexibility for different deployment scenarios while maintaining the reliability and safety of the original Git-based system. 