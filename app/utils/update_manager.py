import json
import os
import requests
import shutil
from datetime import datetime
from packaging import version
import logging
import subprocess
import platform
import sys
import tempfile
import zipfile
from git import Repo, GitCommandError
from git.exc import InvalidGitRepositoryError, NoSuchPathError

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
        """Check for available updates using Git repository or direct download"""
        repo_url = self.config.get('repository_url', '')
        if not repo_url:
            return False, "Repository URL not configured"
        
        # Try Git method first, fall back to direct download if Git is not available
        try:
            return self.check_for_updates_git()
        except Exception as e:
            logger.warning(f"Git update check failed, trying direct download: {e}")
            return self.check_for_updates_direct()
    
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
                # For non-GitHub repositories, try to use GitPython to check remote
                try:
                    app_root = os.path.dirname(self.config_path)
                    repo = Repo(app_root)
                    
                    # Fetch latest changes
                    origin = repo.remotes.origin
                    origin.fetch()
                    
                    # Get the remote branch
                    remote_branch = f"origin/{branch}"
                    if remote_branch in repo.refs:
                        remote_commit = repo.refs[remote_branch].commit
                        local_commit = repo.head.commit
                        
                        if remote_commit.hexsha != local_commit.hexsha:
                            return True, "Update available from remote repository"
                        else:
                            return False, "No updates available (already up to date)"
                    else:
                        return False, f"Remote branch '{branch}' not found"
                except (InvalidGitRepositoryError, NoSuchPathError):
                    return False, "This directory is not a Git repository"
                except Exception as e:
                    logger.error(f"Error checking Git repository: {e}")
                    return False, f"Error checking Git repository: {str(e)}"
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            return False, f"Error checking for updates: {str(e)}"
    
    def check_for_updates_direct(self):
        """Check for updates using direct download from GitHub"""
        try:
            repo_url = self.config.get('repository_url', '')
            branch = self.config.get('branch', 'main')
            if not repo_url:
                return False, "Repository URL not configured"
            
            # Convert Git URL to GitHub raw content URL
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
                logger.info(f"Checking for updates via direct download at: {raw_url}")
                
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
                    else:
                        return False, f"Could not fetch version info: {response.status_code}"
                except requests.exceptions.RequestException as e:
                    logger.error(f"Network error checking direct download: {e}")
                    return False, f"Network error: {str(e)}"
            else:
                return False, "Direct download only supports GitHub repositories"
        except Exception as e:
            logger.error(f"Error checking for direct updates: {e}")
            return False, f"Error checking for direct updates: {str(e)}"
    
    def get_latest_version(self):
        """Get the latest version from Git repository or direct download"""
        try:
            repo_url = self.config.get('repository_url', '')
            branch = self.config.get('branch', 'main')
            if not repo_url:
                return None
            
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
                    return None
                
                # Get app_config.json from GitHub raw content
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/app_config.json"
                
                try:
                    response = requests.get(raw_url, timeout=10)
                    
                    if response.status_code == 200:
                        remote_config = response.json()
                        return remote_config.get('version', '0.0.0.0')
                    else:
                        return None
                except requests.exceptions.RequestException:
                    return None
            else:
                # For non-GitHub repositories, we can't easily get version info
                # without cloning or having the repository already set up
                return None
        except Exception as e:
            logger.error(f"Error getting latest version: {e}")
            return None
    
    def perform_update(self):
        """Always perform update using direct download (ZIP) method, preserving important files."""
        return self.perform_direct_update()

    def cleanup_git_references(self, repo):
        """Clean up problematic Git references that might cause conflicts"""
        try:
            # Check for any problematic references
            problematic_refs = []
            
            # Check if there are any loose references that might conflict
            refs_dir = os.path.join(repo.git_dir, 'refs', 'heads')
            if os.path.exists(refs_dir):
                for ref_file in os.listdir(refs_dir):
                    ref_path = os.path.join(refs_dir, ref_file)
                    if os.path.isfile(ref_path):
                        try:
                            with open(ref_path, 'r') as f:
                                ref_content = f.read().strip()
                                # Check if this is a valid commit hash
                                if len(ref_content) != 40 or not all(c in '0123456789abcdef' for c in ref_content):
                                    problematic_refs.append(ref_file)
                        except:
                            problematic_refs.append(ref_file)
            
            # Clean up problematic references
            for ref in problematic_refs:
                try:
                    if ref in repo.heads:
                        repo.delete_head(ref, force=True)
                    ref_path = os.path.join(refs_dir, ref)
                    if os.path.exists(ref_path):
                        os.remove(ref_path)
                except:
                    pass
            
            if problematic_refs:
                logger.info(f"Cleaned up {len(problematic_refs)} problematic references")
            
            return True
        except Exception as e:
            logger.warning(f"Could not clean up Git references: {e}")
            return False
    
    def force_switch_branch(self, repo, target_branch):
        """Force switch to a branch, handling conflicts by creating a new branch if needed"""
        try:
            current_branch = repo.active_branch.name
            
            # If we're already on the target branch, we're done
            if current_branch == target_branch:
                return True, f"Already on branch '{target_branch}'"
            
            # If target branch exists and we can switch to it, do so
            if target_branch in repo.heads:
                try:
                    repo.heads[target_branch].checkout()
                    return True, f"Switched to existing branch '{target_branch}'"
                except:
                    pass
            
            # If we can't switch normally, try to create a new branch
            try:
                # Create a new branch with a different name to avoid conflicts
                temp_branch = f"{target_branch}_temp_{int(datetime.now().timestamp())}"
                new_branch = repo.create_head(temp_branch)
                new_branch.checkout()
                
                # Now try to rename it to the target branch
                try:
                    # Delete the target branch if it exists
                    if target_branch in repo.heads:
                        repo.delete_head(target_branch, force=True)
                    
                    # Rename our temp branch to the target
                    new_branch.rename(target_branch)
                    return True, f"Created branch '{target_branch}' (resolved conflicts)"
                except:
                    # If rename fails, just stay on the temp branch
                    return True, f"Created temporary branch '{temp_branch}' (could not rename to '{target_branch}')"
                    
            except Exception as e:
                return False, f"Failed to create branch: {str(e)}"
                
        except Exception as e:
            return False, f"Failed to switch branch: {str(e)}"
    
    def safe_create_branch(self, repo, branch_name):
        """Safely create and switch to a branch, handling cases where remote doesn't exist"""
        try:
            # Check if branch already exists locally
            if branch_name in repo.heads:
                # Branch exists, just switch to it
                repo.heads[branch_name].checkout()
                return True, f"Switched to existing branch '{branch_name}'"
            
            # Try to create branch tracking remote
            try:
                if 'origin' in repo.remotes:
                    origin = repo.remotes.origin
                    origin.fetch()
                    
                    remote_branch = f"origin/{branch_name}"
                    if remote_branch in repo.refs:
                        # Create tracking branch
                        new_branch = repo.create_head(branch_name, origin.refs[branch_name])
                        new_branch.checkout()
                        return True, f"Created branch '{branch_name}' tracking remote"
                    else:
                        # Remote branch doesn't exist, create local branch
                        new_branch = repo.create_head(branch_name)
                        new_branch.checkout()
                        return True, f"Created new local branch '{branch_name}' (remote branch doesn't exist yet)"
                else:
                    # No remote, create local branch
                    new_branch = repo.create_head(branch_name)
                    new_branch.checkout()
                    return True, f"Created new local branch '{branch_name}' (no remote configured)"
            except Exception as e:
                # If there's a reference conflict, try to resolve it
                if "does already exist" in str(e):
                    try:
                        # Delete the conflicting reference and recreate
                        repo.delete_head(branch_name, force=True)
                        new_branch = repo.create_head(branch_name)
                        new_branch.checkout()
                        return True, f"Resolved branch conflict and created '{branch_name}'"
                    except Exception as e2:
                        # If that fails, try the force switch method
                        return self.force_switch_branch(repo, branch_name)
                else:
                    # Fallback: create local branch without tracking
                    try:
                        new_branch = repo.create_head(branch_name)
                        new_branch.checkout()
                        return True, f"Created new local branch '{branch_name}' (remote setup failed)"
                    except:
                        # If all else fails, try the force switch method
                        return self.force_switch_branch(repo, branch_name)
                
        except Exception as e:
            return False, f"Failed to create branch '{branch_name}': {str(e)}"
    
    def perform_git_update(self):
        """Perform Git-based update using GitPython"""
        try:
            app_root = os.path.dirname(self.config_path)
            repo_url = self.config.get('repository_url', '')
            target_branch = self.config.get('branch', 'main')

            # Check if this is a Git repository, initialize if not
            try:
                repo = Repo(app_root)
            except (InvalidGitRepositoryError, NoSuchPathError):
                logger.info("Initializing Git repository...")
                success, message = self.initialize_git_repository()
                if not success:
                    return False, f"Failed to initialize Git repository: {message}"
                repo = Repo(app_root)

            # Clean up problematic references
            self.cleanup_git_references(repo)

            # Auto-commit any existing changes before update
            changes_summary = self.get_git_changes_summary()
            if changes_summary != "No uncommitted changes" and changes_summary != "Not a Git repository":
                logger.info(f"Auto-committing changes before update: {changes_summary}")
                success, message = self.auto_commit_changes("Pre-update changes")
                if not success:
                    logger.warning(f"Failed to auto-commit before update: {message}")
                else:
                    logger.info(f"Pre-update commit: {message}")

            # Create backup if enabled
            if self.config.get('backup_enabled', True):
                self.create_backup()

            # Ensure remote 'origin' exists and is correct
            if 'origin' not in [r.name for r in repo.remotes]:
                if repo_url:
                    try:
                        repo.create_remote('origin', repo_url)
                        logger.info(f"Added remote origin: {repo_url}")
                    except Exception as e:
                        logger.warning(f"Failed to add remote origin: {e}")
                else:
                    logger.warning("No repository_url configured to add remote origin.")
            else:
                # Check if URL matches, if not, set it
                try:
                    if repo.remotes.origin.url != repo_url and repo_url:
                        repo.remotes.origin.set_url(repo_url)
                        logger.info(f"Set remote origin URL to: {repo_url}")
                except Exception as e:
                    logger.warning(f"Failed to set remote origin URL: {e}")

            # Get the current branch
            current_branch = repo.active_branch.name

            # If we're not on the target branch, switch to it
            if current_branch != target_branch:
                try:
                    success, message = self.safe_create_branch(repo, target_branch)
                    if not success:
                        return False, message
                    logger.info(message)
                except GitCommandError as e:
                    return False, f"Failed to switch to branch '{target_branch}': {str(e)}"

            # Try to pull latest changes (only if remote exists and is configured)
            try:
                if 'origin' in [r.name for r in repo.remotes]:
                    origin = repo.remotes.origin
                    try:
                        pull_result = origin.pull()
                        logger.info(f"Git pull result: {pull_result}")
                    except GitCommandError as e:
                        logger.error(f"Git pull failed: {e.stderr if hasattr(e, 'stderr') else str(e)}")
                        return False, f"Git pull failed: {e.stderr if hasattr(e, 'stderr') else str(e)}"
                else:
                    logger.warning("No remote origin configured, skipping pull")
            except Exception as e:
                logger.error(f"Unexpected error during git pull: {str(e)}")
                return False, f"Unexpected error during git pull: {str(e)}"

            # Install packages from requirements.txt
            success, message = self.install_requirements()
            if not success:
                return False, message

            # Run database migrations if alembic is available
            try:
                result = subprocess.run(['flask', 'db', 'upgrade'], capture_output=True, text=True, timeout=60)
                if result.returncode != 0:
                    logger.warning(f"Database migration failed (continuing anyway): {result.stderr}")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                logger.warning("Database migration skipped (alembic not available)")

            # Auto-commit any changes after update
            changes_summary = self.get_git_changes_summary()
            if changes_summary != "No uncommitted changes" and changes_summary != "Not a Git repository":
                logger.info(f"Auto-committing changes after update: {changes_summary}")
                success, message = self.auto_commit_changes("Post-update changes")
                if not success:
                    logger.warning(f"Failed to auto-commit after update: {message}")
                else:
                    logger.info(f"Post-update commit: {message}")

            # Restart server immediately
            restart_success, restart_message = self.restart_server()
            if not restart_success:
                logger.warning(f"Could not restart server: {restart_message}")

            return True, "Git update completed successfully - server restarting immediately"
        except Exception as e:
            return False, f"Git update failed: {str(e)}"
    
    def copy_directory(self, src, dst, skip_files=None):
        """Recursively copy directory contents, overwriting existing files, but skipping any in skip_files."""
        import shutil
        skip_files = set(os.path.abspath(f) for f in (skip_files or []))
        try:
            for root, dirs, files in os.walk(src):
                rel_root = os.path.relpath(root, src)
                dst_root = os.path.join(dst, rel_root) if rel_root != '.' else dst
                if not os.path.exists(dst_root):
                    os.makedirs(dst_root, exist_ok=True)
                for file in files:
                    src_file = os.path.join(root, file)
                    dst_file = os.path.abspath(os.path.join(dst_root, file))
                    if dst_file in skip_files:
                        continue
                    shutil.copy2(src_file, dst_file)
            return True
        except Exception as e:
            raise Exception(f"Failed to copy directory: {str(e)}")

    def perform_direct_update(self):
        """Perform direct download update from GitHub, preserving important files."""
        try:
            import shutil
            repo_url = self.config.get('repository_url', '')
            branch = self.config.get('branch', 'main')
            if not repo_url:
                return False, "Repository URL not configured"

            # Convert Git URL to GitHub ZIP download URL
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

                # Create GitHub ZIP download URL
                download_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
                logger.info(f"Downloading update from: {download_url}")

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

                    # --- PRESERVE FILES ---
                    app_root = os.path.dirname(self.config_path)
                    preserve_files = [
                        os.path.abspath(os.path.join(app_root, 'instance', 'scouting.db')),
                        os.path.abspath(os.path.join(app_root, 'config', 'pit_config.json')),
                    ]
                    temp_preserve = []
                    for f in preserve_files:
                        if os.path.exists(f):
                            temp_path = f + ".bak_update"
                            shutil.copy2(f, temp_path)
                            temp_preserve.append((f, temp_path))

                    # Copy files to application directory (overwrite all except preserved)
                    self.copy_directory(extracted_dir, app_root, skip_files=preserve_files)

                    # --- RESTORE FILES ---
                    for orig, bak in temp_preserve:
                        shutil.copy2(bak, orig)
                        os.remove(bak)
                    logger.info(f"Restored preserved files after ZIP update: {[f for f, _ in temp_preserve]}")

                    # Install packages from requirements.txt
                    success, message = self.install_requirements()
                    if not success:
                        return False, message

                    # Run database migrations if alembic is available
                    try:
                        result = subprocess.run(['flask', 'db', 'upgrade'], capture_output=True, text=True, timeout=60)
                        if result.returncode != 0:
                            logger.warning(f"Database migration failed (continuing anyway): {result.stderr}")
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        logger.warning("Database migration skipped (alembic not available)")

                    # Restart server immediately
                    restart_success, restart_message = self.restart_server()
                    if not restart_success:
                        logger.warning(f"Could not restart server: {restart_message}")

                    return True, "Direct download update completed successfully - server restarting immediately (preserved db/config files)"
            else:
                return False, "Direct download only supports GitHub repositories"
        except Exception as e:
            return False, f"Direct download update failed: {str(e)}"
    
    def initialize_git_repository(self):
        """Initialize a Git repository in the current directory and sync with remote if possible, preserving db and config files."""
        try:
            import shutil
            app_root = os.path.dirname(self.config_path)
            preserve_files = [
                os.path.join(app_root, 'app_config.json'),
                os.path.join(app_root, 'instance', 'scouting.db'),
                os.path.join(app_root, 'config', 'pit_config.json'),
            ]
            temp_preserve = []

            # Check if Git is available
            try:
                result = subprocess.run(['git', '--version'], capture_output=True, text=True)
                if result.returncode != 0:
                    return False, "Git is not installed on this system"
            except FileNotFoundError:
                return False, "Git is not installed on this system"

            # Check if this is already a Git repository
            git_dir = os.path.join(app_root, '.git')
            if os.path.exists(git_dir):
                # Repository exists, try to clean it up
                try:
                    # Check if it's a valid repository
                    result = subprocess.run(['git', 'status'], cwd=app_root, capture_output=True, text=True)
                    if result.returncode != 0:
                        # Invalid repository, remove and reinitialize
                        logger.info("Removing invalid Git repository and reinitializing...")
                        shutil.rmtree(git_dir)
                except:
                    # Repository is corrupted, remove and reinitialize
                    logger.info("Removing corrupted Git repository and reinitializing...")
                    shutil.rmtree(git_dir)

            # Initialize Git repository
            result = subprocess.run(['git', 'init'], cwd=app_root, capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Failed to initialize Git repository: {result.stderr}"

            # Add all files
            result = subprocess.run(['git', 'add', '.'], cwd=app_root, capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Failed to add files: {result.stderr}"

            # Make initial commit (ignore if nothing to commit)
            result = subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=app_root, capture_output=True, text=True)
            # If already committed, that's fine

            # Add remote origin (but don't fail if it doesn't work)
            repo_url = self.config.get('repository_url', '')
            branch = self.config.get('branch', 'main')
            if repo_url:
                # Remove existing origin if present (to avoid duplicate error)
                subprocess.run(['git', 'remote', 'remove', 'origin'], cwd=app_root, capture_output=True, text=True)
                result = subprocess.run(['git', 'remote', 'add', 'origin', repo_url], cwd=app_root, capture_output=True, text=True)
                if result.returncode != 0:
                    # If adding remote fails, try to set the URL instead
                    result = subprocess.run(['git', 'remote', 'set-url', 'origin', repo_url], cwd=app_root, capture_output=True, text=True)
                    if result.returncode != 0:
                        logger.warning(f"Could not configure remote origin: {result.stderr}")
                        logger.warning("Remote repository will need to be configured manually")

                # Fetch remote branch info
                fetch_result = subprocess.run(['git', 'fetch', 'origin'], cwd=app_root, capture_output=True, text=True)
                if fetch_result.returncode == 0:
                    # Check if remote branch exists
                    branch_check = subprocess.run(['git', 'ls-remote', '--heads', repo_url, branch], capture_output=True, text=True)
                    if branch_check.stdout.strip():
                        # --- PRESERVE FILES ---
                        for f in preserve_files:
                            if os.path.exists(f):
                                temp_path = f + ".bak_update"
                                shutil.copy2(f, temp_path)
                                temp_preserve.append((f, temp_path))
                        # Remote branch exists, hard reset local to match remote
                        subprocess.run(['git', 'checkout', '-B', branch], cwd=app_root, capture_output=True, text=True)
                        subprocess.run(['git', 'reset', '--hard', f'origin/{branch}'], cwd=app_root, capture_output=True, text=True)
                        logger.info(f"Checked out and reset to remote branch origin/{branch}")
                        # Remove all untracked files and directories (except preserved)
                        subprocess.run(['git', 'clean', '-fdx'], cwd=app_root, capture_output=True, text=True)
                        # --- RESTORE FILES ---
                        for orig, bak in temp_preserve:
                            shutil.copy2(bak, orig)
                            os.remove(bak)
                        logger.info(f"Restored preserved files after reset: {[f for f, _ in temp_preserve]}")
                    else:
                        # Remote branch does not exist, push local branch to create it
                        subprocess.run(['git', 'checkout', '-B', branch], cwd=app_root, capture_output=True, text=True)
                        push_result = subprocess.run(['git', 'push', '-u', 'origin', branch], cwd=app_root, capture_output=True, text=True)
                        if push_result.returncode != 0:
                            logger.warning(f"Could not push branch to remote: {push_result.stderr}")
                        else:
                            logger.info(f"Pushed local branch {branch} to remote origin")
                else:
                    logger.warning(f"Could not fetch from remote: {fetch_result.stderr}")
            else:
                logger.warning("No repository_url configured for remote origin.")

            return True, "Git repository initialized and synchronized with remote successfully (preserved db/config files)"
        except Exception as e:
            return False, f"Failed to initialize Git repository: {str(e)}"
    
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
    
    def set_git_config(self, repository_url, branch='main', backup_enabled=True):
        """Set the Git repository configuration"""
        self.config['repository_url'] = repository_url
        self.config['branch'] = branch
        self.config['backup_enabled'] = backup_enabled
        self.save_config()
    
    def get_git_config(self):
        """Get the current Git repository configuration"""
        return {
            'repository_url': self.config.get('repository_url', ''),
            'branch': self.config.get('branch', 'main'),
            'backup_enabled': self.config.get('backup_enabled', True),
            'description': 'Updates from Git repository using GitPython or direct download'
        }
    
    def is_git_repository(self):
        """Check if the current directory is a Git repository"""
        try:
            app_root = os.path.dirname(self.config_path)
            repo = Repo(app_root)
            return True
        except (InvalidGitRepositoryError, NoSuchPathError):
            return False
    
    def is_git_installed(self):
        """Check if Git is installed on the system"""
        try:
            result = subprocess.run(['git', '--version'], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def auto_commit_changes(self, message="Auto-commit changes"):
        """Automatically commit any uncommitted changes"""
        try:
            app_root = os.path.dirname(self.config_path)
            
            # Check if this is a Git repository
            try:
                repo = Repo(app_root)
            except (InvalidGitRepositoryError, NoSuchPathError):
                logger.info("Not a Git repository - skipping auto-commit")
                return True, "Not a Git repository"
            
            # Check if there are any changes to commit
            if repo.is_dirty():
                logger.info(f"Auto-committing changes: {message}")
                
                # Add all changes
                repo.git.add('.')
                
                # Commit with timestamp
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                commit_message = f"{message} - {timestamp}"
                
                try:
                    repo.index.commit(commit_message)
                    logger.info(f"Successfully committed: {commit_message}")
                    return True, f"Changes committed: {commit_message}"
                except Exception as e:
                    logger.warning(f"Failed to commit changes: {e}")
                    return False, f"Failed to commit: {str(e)}"
            else:
                logger.info("No changes to commit")
                return True, "No changes to commit"
                
        except Exception as e:
            logger.error(f"Error during auto-commit: {e}")
            return False, f"Auto-commit error: {str(e)}"
    
    def get_git_changes_summary(self):
        """Get a summary of uncommitted changes"""
        try:
            app_root = os.path.dirname(self.config_path)
            
            # Check if this is a Git repository
            try:
                repo = Repo(app_root)
            except (InvalidGitRepositoryError, NoSuchPathError):
                return "Not a Git repository"
            
            if not repo.is_dirty():
                return "No uncommitted changes"
            
            # Get status summary
            status = repo.git.status('--porcelain')
            lines = status.strip().split('\n') if status.strip() else []
            
            modified = len([line for line in lines if line.startswith('M ')])
            added = len([line for line in lines if line.startswith('A ')])
            deleted = len([line for line in lines if line.startswith('D ')])
            untracked = len([line for line in lines if line.startswith('??')])
            
            summary_parts = []
            if modified > 0:
                summary_parts.append(f"{modified} modified")
            if added > 0:
                summary_parts.append(f"{added} added")
            if deleted > 0:
                summary_parts.append(f"{deleted} deleted")
            if untracked > 0:
                summary_parts.append(f"{untracked} untracked")
            
            return f"{', '.join(summary_parts)} files" if summary_parts else "No changes"
            
        except Exception as e:
            logger.error(f"Error getting Git changes summary: {e}")
            return "Error checking changes"

    def install_requirements(self):
        """Install packages from requirements.txt"""
        try:
            app_root = os.path.dirname(self.config_path)
            requirements_file = os.path.join(app_root, 'requirements.txt')
            
            if not os.path.exists(requirements_file):
                return True, "No requirements.txt file found - skipping package installation"
            
            logger.info("Installing packages from requirements.txt...")
            
            # Run pip install
            result = subprocess.run([
                sys.executable, '-m', 'pip', 'install', '-r', requirements_file
            ], cwd=app_root, capture_output=True, text=True, timeout=300)  # 5 minute timeout
            
            if result.returncode == 0:
                return True, "Packages installed successfully"
            else:
                error_msg = result.stderr if result.stderr else result.stdout
                return False, f"Failed to install packages: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, "Package installation timed out (5 minutes)"
        except Exception as e:
            return False, f"Error installing packages: {str(e)}"
    
    def restart_server(self):
        """Restart the server gracefully using Flask's reload mechanism"""
        try:
            import os
            import sys
            import signal
            import subprocess
            import threading
            import time
            
            # Get the current script path
            app_root = os.path.dirname(self.config_path)
            script_path = os.path.join(app_root, 'run.py')
            
            logger.info("Initiating graceful server restart...")
            
            # Method 1: Try to use Flask's reload mechanism
            try:
                from flask import current_app
                if hasattr(current_app, 'testing') and not current_app.testing:
                    # We're in a Flask context, try to trigger reload
                    logger.info("Using Flask reload mechanism...")
                    
                    # Create a restart trigger file that Flask's reloader will detect
                    restart_trigger = os.path.join(app_root, '.flask_restart_trigger')
                    with open(restart_trigger, 'w') as f:
                        f.write(f"Restart triggered at {datetime.now().isoformat()}")
                    
                    # Remove the trigger file after a short delay
                    def cleanup_trigger():
                        time.sleep(1)
                        try:
                            if os.path.exists(restart_trigger):
                                os.remove(restart_trigger)
                        except:
                            pass
                    
                    threading.Thread(target=cleanup_trigger, daemon=True).start()
                    
                    return True, "Flask reload mechanism triggered"
                    
            except Exception as e:
                logger.warning(f"Flask reload mechanism failed: {e}")
            
            # Method 2: Try to send restart signal to parent process
            try:
                # Get the parent process ID
                parent_pid = os.getppid()
                if parent_pid != 1:  # Not the init process
                    logger.info(f"Sending restart signal to parent process {parent_pid}")
                    
                    if os.name == 'nt':  # Windows
                        # On Windows, we can't easily send signals, so use subprocess
                        subprocess.Popen([sys.executable, script_path], 
                                       cwd=app_root,
                                       creationflags=subprocess.DETACHED_PROCESS)
                        # Give the new process time to start
                        time.sleep(2)
                        # Exit gracefully
                        os._exit(0)
                    else:
                        # On Unix, send SIGTERM to parent
                        os.kill(parent_pid, signal.SIGTERM)
                        return True, "Restart signal sent to parent process"
                        
            except Exception as e:
                logger.warning(f"Signal-based restart failed: {e}")
            
            # Method 3: Fallback to restart flag
            logger.info("Using restart flag fallback method...")
            restart_flag = os.path.join(app_root, '.restart_flag')
            with open(restart_flag, 'w') as f:
                f.write(f"Restart requested at {datetime.now().isoformat()}")
            
            return True, "Restart flag created - server will restart on next request"
            
        except Exception as e:
            logger.error(f"Error during graceful restart: {e}")
            return False, f"Error during graceful restart: {str(e)}"
    
    def check_restart_flag(self):
        """Check if restart flag exists and remove it"""
        try:
            app_root = os.path.dirname(self.config_path)
            restart_flag = os.path.join(app_root, '.restart_flag')
            
            if os.path.exists(restart_flag):
                os.remove(restart_flag)
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error checking restart flag: {e}")
            return False

    def get_git_status(self):
        """Get Git repository status"""
        try:
            app_root = os.path.dirname(self.config_path)
            repo = Repo(app_root)
            
            return {
                'is_repo': True,
                'current_branch': repo.active_branch.name,
                'is_dirty': repo.is_dirty(),
                'remote_urls': [remote.url for remote in repo.remotes],
                'last_commit': repo.head.commit.hexsha[:8] if repo.head.commit else None,
                'git_installed': self.is_git_installed()
            }
        except (InvalidGitRepositoryError, NoSuchPathError):
            return {
                'is_repo': False,
                'current_branch': None,
                'is_dirty': False,
                'remote_urls': [],
                'last_commit': None,
                'git_installed': self.is_git_installed()
            }
        except Exception as e:
            return {
                'is_repo': False,
                'error': str(e),
                'current_branch': None,
                'is_dirty': False,
                'remote_urls': [],
                'last_commit': None,
                'git_installed': self.is_git_installed()
            } 