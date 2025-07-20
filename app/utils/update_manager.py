import json
import os
import requests
import zipfile
import shutil
import tempfile
from datetime import datetime
from packaging import version
import logging
import subprocess
import platform
import sys

logger = logging.getLogger(__name__)

class UpdateManager:
    def __init__(self, config_file='app_config.json'):
        self.config_file = config_file
        # Always use the root directory for app_config.json
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), config_file)
        self.config = self.load_config()
    
    def load_config(self):
        """Load the app configuration from JSON file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            else:
                # Create default config if it doesn't exist
                default_config = {
                    "version": "1.0.0.0",
                    "last_updated": None,
                    "repository_url": "",
                    "branch": "main",
                    "update_method": "direct_download",  # git, direct_download, manual
                    "download_url": "https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip",
                    "backup_enabled": True
                }
                self.save_config(default_config)
                return default_config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {
                "version": "1.0.0.0",
                "last_updated": None,
                "repository_url": "",
                "branch": "main",
                "update_method": "direct_download",
                "download_url": "https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip",
                "backup_enabled": True
            }
    
    def save_config(self, config=None):
        """Save the app configuration to JSON file"""
        try:
            config_to_save = config if config else self.config
            with open(self.config_path, 'w') as f:
                json.dump(config_to_save, f, indent=4)
            if not config:
                self.config = config_to_save
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def get_current_version(self):
        """Get the current application version"""
        return self.config.get('version', '1.0.0.0')
    
    def set_current_version(self, new_version):
        """Set the current application version"""
        self.config['version'] = new_version
        self.config['last_updated'] = datetime.now().isoformat()
        self.save_config()
    
    def check_for_updates(self):
        """Check for available updates using the configured method"""
        update_method = self.config.get('update_method', 'git')
        
        if update_method == 'git':
            return self.check_for_updates_git()
        elif update_method == 'direct_download':
            return self.check_for_updates_direct()
        elif update_method == 'manual':
            return self.check_for_updates_manual()
        else:
            return False, f"Unknown update method: {update_method}"
    
    def check_for_updates_git(self):
        """Check for updates using Git repository"""
        try:
            repo_url = self.config.get('repository_url', '')
            branch = self.config.get('branch', 'main')
            if not repo_url:
                return False, "Repository URL not configured"
            
            # Extract owner and repo from GitHub URL
            if 'github.com' in repo_url:
                repo_url = repo_url.replace('.git', '')
                if repo_url.endswith('/'):
                    repo_url = repo_url[:-1]
                
                parts = repo_url.split('/')
                if len(parts) >= 2:
                    owner = parts[-2]
                    repo = parts[-1]
                else:
                    return False, "Invalid GitHub URL format"
                
                # Get app_config.json from GitHub raw content
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/app_config.json"
                logger.info(f"Checking for updates at: {raw_url}")
                
                try:
                    response = requests.get(raw_url, timeout=10)
                    
                    if response.status_code == 200:
                        remote_config = response.json()
                        remote_version = remote_config.get('version', '0.0.0.0')
                        
                        current_version = self.get_current_version()
                        
                        # Compare versions using semantic versioning
                        try:
                            if version.parse(remote_version) > version.parse(current_version):
                                return True, f"Update available: {remote_version}"
                            else:
                                return False, f"No updates available (latest: {remote_version})"
                        except Exception as ve:
                            logger.error(f"Version comparison error: {ve}")
                            return False, f"Error comparing versions: {str(ve)}"
                    elif response.status_code == 404:
                        return False, "app_config.json not found in GitHub repository."
                    else:
                        return False, f"GitHub API error: {response.status_code}"
                except requests.exceptions.RequestException as e:
                    logger.error(f"Network error checking GitHub: {e}")
                    return False, f"Network error: {str(e)}"
            else:
                return False, "Not a GitHub repository"
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            return False, f"Error checking for updates: {str(e)}"
    
    def check_for_updates_direct(self):
        """Check for updates using direct download URL"""
        try:
            download_url = self.config.get('download_url', '')
            if not download_url:
                return False, "Download URL not configured"
            
            # Handle GitHub ZIP URLs - convert to raw content URL for app_config.json
            if 'github.com' in download_url and '/archive/' in download_url:
                # Convert GitHub ZIP URL to raw content URL
                # From: https://github.com/user/repo/archive/refs/heads/main.zip
                # To: https://raw.githubusercontent.com/user/repo/main/app_config.json
                parts = download_url.split('/')
                if len(parts) >= 3:
                    owner = parts[3]
                    repo = parts[4]
                    config_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/app_config.json"
                else:
                    return False, "Invalid GitHub ZIP URL format"
            else:
                # Try to download the app_config.json from the download URL
                config_url = download_url.replace('.zip', '/app_config.json')
                if not config_url.endswith('app_config.json'):
                    config_url = download_url + '/app_config.json'
            
            try:
                response = requests.get(config_url, timeout=10)
                
                if response.status_code == 200:
                    remote_config = response.json()
                    remote_version = remote_config.get('version', '0.0.0.0')
                    
                    current_version = self.get_current_version()
                    
                    # Compare versions using semantic versioning
                    try:
                        if version.parse(remote_version) > version.parse(current_version):
                            return True, f"Update available: {remote_version}"
                        else:
                            return False, f"No updates available (latest: {remote_version})"
                    except Exception as ve:
                        logger.error(f"Version comparison error: {ve}")
                        return False, f"Error comparing versions: {str(ve)}"
                else:
                    return False, f"Could not fetch version info: {response.status_code}"
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error checking direct download: {e}")
                return False, f"Network error: {str(e)}"
        except Exception as e:
            logger.error(f"Error checking for direct updates: {e}")
            return False, f"Error checking for direct updates: {str(e)}"
    
    def check_for_updates_manual(self):
        """Check for updates in manual update folder"""
        try:
            manual_update_dir = os.path.join(os.path.dirname(self.config_path), 'manual_updates')
            if not os.path.exists(manual_update_dir):
                return False, "Manual updates directory not found"
            
            # Look for app_config.json in manual updates directory
            manual_config_path = os.path.join(manual_update_dir, 'app_config.json')
            if not os.path.exists(manual_config_path):
                return False, "No manual update files found"
            
            with open(manual_config_path, 'r') as f:
                remote_config = json.load(f)
            
            remote_version = remote_config.get('version', '0.0.0.0')
            current_version = self.get_current_version()
            
            # Compare versions using semantic versioning
            try:
                if version.parse(remote_version) > version.parse(current_version):
                    return True, f"Manual update available: {remote_version}"
                else:
                    return False, f"No manual updates available (latest: {remote_version})"
            except Exception as ve:
                logger.error(f"Version comparison error: {ve}")
                return False, f"Error comparing versions: {str(ve)}"
        except Exception as e:
            logger.error(f"Error checking for manual updates: {e}")
            return False, f"Error checking for manual updates: {str(e)}"
    
    def get_latest_version(self):
        """Get the latest version using the configured method"""
        update_method = self.config.get('update_method', 'git')
        
        if update_method == 'git':
            return self.get_latest_version_git()
        elif update_method == 'direct_download':
            return self.get_latest_version_direct()
        elif update_method == 'manual':
            return self.get_latest_version_manual()
        else:
            return None
    
    def get_latest_version_git(self):
        """Get the latest version from Git repository"""
        try:
            repo_url = self.config.get('repository_url', '')
            branch = self.config.get('branch', 'main')
            if not repo_url or 'github.com' not in repo_url:
                return None
            
            repo_url = repo_url.replace('.git', '')
            if repo_url.endswith('/'):
                repo_url = repo_url[:-1]
            
            parts = repo_url.split('/')
            if len(parts) >= 2:
                owner = parts[-2]
                repo = parts[-1]
                
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/app_config.json"
                response = requests.get(raw_url, timeout=10)
                
                if response.status_code == 200:
                    remote_config = response.json()
                    return remote_config.get('version', None)
        except Exception as e:
            logger.error(f"Error getting latest version from GitHub: {e}")
        
        return None
    
    def get_latest_version_direct(self):
        """Get the latest version from direct download URL"""
        try:
            download_url = self.config.get('download_url', '')
            if not download_url:
                return None
            
            # Handle GitHub ZIP URLs - convert to raw content URL for app_config.json
            if 'github.com' in download_url and '/archive/' in download_url:
                # Convert GitHub ZIP URL to raw content URL
                # From: https://github.com/user/repo/archive/refs/heads/main.zip
                # To: https://raw.githubusercontent.com/user/repo/main/app_config.json
                parts = download_url.split('/')
                if len(parts) >= 3:
                    owner = parts[3]
                    repo = parts[4]
                    config_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/app_config.json"
                else:
                    return None
            else:
                config_url = download_url.replace('.zip', '/app_config.json')
                if not config_url.endswith('app_config.json'):
                    config_url = download_url + '/app_config.json'
            
            response = requests.get(config_url, timeout=10)
            
            if response.status_code == 200:
                remote_config = response.json()
                return remote_config.get('version', None)
        except Exception as e:
            logger.error(f"Error getting latest version from direct download: {e}")
        
        return None
    
    def get_latest_version_manual(self):
        """Get the latest version from manual update folder"""
        try:
            manual_update_dir = os.path.join(os.path.dirname(self.config_path), 'manual_updates')
            manual_config_path = os.path.join(manual_update_dir, 'app_config.json')
            
            if os.path.exists(manual_config_path):
                with open(manual_config_path, 'r') as f:
                    remote_config = json.load(f)
                return remote_config.get('version', None)
        except Exception as e:
            logger.error(f"Error getting latest version from manual updates: {e}")
        
        return None
    
    def perform_update(self):
        """Perform the update using the configured method"""
        update_method = self.config.get('update_method', 'git')
        
        if update_method == 'git':
            return self.perform_git_update()
        elif update_method == 'direct_download':
            return self.perform_direct_update()
        elif update_method == 'manual':
            return self.perform_manual_update()
        else:
            return False, f"Unknown update method: {update_method}"
    
    def perform_git_update(self):
        """Perform Git-based update"""
        try:
            # Check if this is a Git repository
            result = subprocess.run(['git', 'status'], capture_output=True, text=True)
            if result.returncode != 0:
                return False, "This directory is not a Git repository"
            
            # Pull latest changes
            result = subprocess.run(['git', 'pull'], capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Git pull failed: {result.stderr}"
            
            # Install dependencies
            result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Failed to install dependencies: {result.stderr}"
            
            # Run database migrations
            result = subprocess.run(['flask', 'db', 'upgrade'], capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Database migration failed: {result.stderr}"
            
            return True, "Git update completed successfully"
        except Exception as e:
            return False, f"Git update failed: {str(e)}"
    
    def perform_direct_update(self):
        """Perform direct download update"""
        try:
            download_url = self.config.get('download_url', '')
            if not download_url:
                return False, "Download URL not configured"
            
            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                # Download the file
                response = requests.get(download_url, stream=True)
                if response.status_code != 200:
                    return False, f"Failed to download update: {response.status_code}"
                
                # Save to temporary file
                zip_path = os.path.join(temp_dir, 'update.zip')
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Extract the zip file
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Find the extracted directory
                extracted_dirs = [d for d in os.listdir(temp_dir) if os.path.isdir(os.path.join(temp_dir, d)) and d != '__pycache__']
                if not extracted_dirs:
                    return False, "No valid directory found in downloaded file"
                
                extracted_dir = os.path.join(temp_dir, extracted_dirs[0])
                
                # For GitHub ZIP files, the content is in a subdirectory with the repo name
                # Check if we need to go deeper into the directory structure
                if 'Obsidianscout' in extracted_dirs[0]:
                    # This is a GitHub ZIP file, the actual content is inside the repo-named directory
                    extracted_dir = os.path.join(temp_dir, extracted_dirs[0])
                else:
                    # Regular ZIP file structure
                    extracted_dir = os.path.join(temp_dir, extracted_dirs[0])
                
                # Create backup if enabled
                if self.config.get('backup_enabled', True):
                    self.create_backup()
                
                # Copy files to application directory
                app_root = os.path.dirname(self.config_path)
                self.copy_directory(extracted_dir, app_root)
                
                # Install dependencies
                result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], 
                                      capture_output=True, text=True)
                if result.returncode != 0:
                    return False, f"Failed to install dependencies: {result.stderr}"
                
                # Run database migrations
                result = subprocess.run(['flask', 'db', 'upgrade'], capture_output=True, text=True)
                if result.returncode != 0:
                    return False, f"Database migration failed: {result.stderr}"
                
                return True, "Direct download update completed successfully"
        except Exception as e:
            return False, f"Direct download update failed: {str(e)}"
    
    def perform_manual_update(self):
        """Perform manual update from manual_updates directory"""
        try:
            manual_update_dir = os.path.join(os.path.dirname(self.config_path), 'manual_updates')
            if not os.path.exists(manual_update_dir):
                return False, "Manual updates directory not found"
            
            # Create backup if enabled
            if self.config.get('backup_enabled', True):
                self.create_backup()
            
            # Copy files from manual updates directory
            app_root = os.path.dirname(self.config_path)
            self.copy_directory(manual_update_dir, app_root)
            
            # Install dependencies
            result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Failed to install dependencies: {result.stderr}"
            
            # Run database migrations
            result = subprocess.run(['flask', 'db', 'upgrade'], capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Database migration failed: {result.stderr}"
            
            return True, "Manual update completed successfully"
        except Exception as e:
            return False, f"Manual update failed: {str(e)}"
    
    def create_backup(self):
        """Create a backup of the current application"""
        try:
            app_root = os.path.dirname(self.config_path)
            backup_dir = os.path.join(app_root, 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"backup_{timestamp}"
            backup_path = os.path.join(backup_dir, backup_name)
            
            # Copy application files to backup directory
            shutil.copytree(app_root, backup_path, ignore=shutil.ignore_patterns(
                'backups', '__pycache__', '*.pyc', 'instance', '.git'
            ))
            
            return True, f"Backup created: {backup_path}"
        except Exception as e:
            return False, f"Backup failed: {str(e)}"
    
    def copy_directory(self, src, dst):
        """Copy directory contents, overwriting existing files"""
        try:
            for item in os.listdir(src):
                src_path = os.path.join(src, item)
                dst_path = os.path.join(dst, item)
                
                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)
            
            return True
        except Exception as e:
            raise Exception(f"Failed to copy directory: {str(e)}")
    
    def set_update_method(self, method, **kwargs):
        """Set the update method and related configuration"""
        self.config['update_method'] = method
        
        if method == 'git':
            self.config['repository_url'] = kwargs.get('repository_url', '')
            self.config['branch'] = kwargs.get('branch', 'main')
        elif method == 'direct_download':
            self.config['download_url'] = kwargs.get('download_url', '')
        elif method == 'manual':
            # No additional config needed for manual updates
            pass
        
        self.config['backup_enabled'] = kwargs.get('backup_enabled', True)
        self.save_config()
    
    def get_update_method_info(self):
        """Get information about the current update method"""
        method = self.config.get('update_method', 'git')
        
        if method == 'git':
            return {
                'method': 'git',
                'repository_url': self.config.get('repository_url', ''),
                'branch': self.config.get('branch', 'main'),
                'description': 'Updates from Git repository'
            }
        elif method == 'direct_download':
            return {
                'method': 'direct_download',
                'download_url': self.config.get('download_url', ''),
                'description': 'Updates from direct download URL'
            }
        elif method == 'manual':
            return {
                'method': 'manual',
                'manual_dir': os.path.join(os.path.dirname(self.config_path), 'manual_updates'),
                'description': 'Updates from manual_updates directory'
            }
        else:
            return {
                'method': 'unknown',
                'description': 'Unknown update method'
            } 