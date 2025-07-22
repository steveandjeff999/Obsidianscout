# Version Management System

This application includes an automated version management system that tracks the current version and can check for updates.

## Configuration

The version information is stored in `app_config.json` at the root of the project:

```json
{
    "version": "1.0.0.0",
    "last_updated": "2025-07-08T19:07:00",
    "repository_url": "https://github.com/yourusername/your-repo.git",
    "branch": "main"
}
```

### Configuration Options

- **version**: Your current application version (semantic versioning)
- **last_updated**: ISO timestamp of last update
- **repository_url**: GitHub repository URL for checking releases
- **branch**: Git branch (used for future features)

## How It Works

This system uses the `app_config.json` file on GitHub for version management:

1. **Your local version** stays exactly as you set it in your local `app_config.json` (e.g., `1.0.0.0`)
2. The system checks the **remote `app_config.json`** file on GitHub for its version field
3. **Version comparison** uses the `packaging` library for accurate semantic version comparison
4. **Automatic updates** download and install when a higher version is found

### Managing Version on GitHub

To enable version checking:

1. Update the `app_config.json` file on GitHub with a higher version number
2. Push the changes to the branch specified in your local config (default: `main`)
3. The system will compare version numbers directly from this file

The system will automatically detect when `1.0.0.1` > `1.0.0.0` and offer to update.

## Usage

### Setting the Current Version

To update the current version manually:

1. Edit `app_config.json` and change the `version` field
2. Or use the admin interface after a successful update

### Checking for Updates

The system uses a simple and reliable approach:

1. **Direct File Comparison**: 
   - Fetches the `app_config.json` file directly from your GitHub repository
   - Compares the version field with your local version
   - Uses semantic versioning for accurate comparison (1.0.0.1 > 1.0.0.0)

2. **No Commit or Release Tracking**:
   - Does not track individual commits or GitHub releases
   - Only compares version numbers from the config files
   - Clean and predictable update behavior

### Admin Interface

Access the update interface at `/admin/update`:

- View current version information
- Check for available updates automatically
- See update status (up to date / update available)
- Perform updates with real-time console output
- **Automatic version updating** after successful updates

### Automatic Features

- **Single Config File**: All version information stored in one `app_config.json` file
- **Direct Version Comparison**: Compares versions between local and remote config files
- **Simplified Version Management**: Single version field eliminates confusion
- **Reliable Updates**: Simple version comparison ensures predictable update behavior

### API Endpoints

- `GET /admin/update` - Update page with version info
- `POST /admin/update/check` - Check for updates
- `POST /admin/update/version` - Update version after successful update
- `GET/POST /admin/update/run` - Run update process

## Version Format

Use semantic versioning (semver) format: `MAJOR.MINOR.PATCH`

Examples:
- `1.0.0` - Initial release
- `1.0.1` - Patch update
- `1.1.0` - Minor update with new features
- `2.0.0` - Major update with breaking changes
