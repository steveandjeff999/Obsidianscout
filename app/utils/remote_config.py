import json
import requests
import os
import logging
from packaging import version

logger = logging.getLogger(__name__)

def fetch_remote_config(repo_url, branch='main'):
    """
    Fetch the app_config.json from GitHub repository
    
    Args:
        repo_url (str): The GitHub repository URL
        branch (str): The branch name, defaults to 'main'
        
    Returns:
        dict: The remote configuration or None if failed
    """
    try:
        # Parse repository URL to get owner and repo name
        if 'github.com' in repo_url:
            repo_url = repo_url.replace('.git', '')
            if repo_url.endswith('/'):
                repo_url = repo_url[:-1]
            
            parts = repo_url.split('/')
            if len(parts) >= 2:
                owner = parts[-2]
                repo = parts[-1]
            else:
                logger.error("Invalid GitHub URL format")
                return None
                
            # Get app_config.json from GitHub raw content
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/app_config.json"
            logger.info(f"Fetching remote config from: {raw_url}")
            
            response = requests.get(raw_url, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to fetch remote config: {response.status_code}")
                return None
        else:
            logger.error("Not a GitHub repository")
            return None
    except Exception as e:
        logger.error(f"Error fetching remote config: {e}")
        return None

def is_remote_version_newer(local_version, remote_version):
    """
    Check if remote version is newer than local version
    
    Args:
        local_version (str): The local version string
        remote_version (str): The remote version string
        
    Returns:
        bool: True if remote version is newer, False otherwise
        str: A message explaining the result
    """
    try:
        if version.parse(remote_version) > version.parse(local_version):
            return True, f"Update available: {remote_version}"
        else:
            return False, f"No updates available (latest: {remote_version})"
    except Exception as e:
        logger.error(f"Version comparison error: {e}")
        return False, f"Error comparing versions: {str(e)}"
