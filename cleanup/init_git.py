#!/usr/bin/env python3
"""
Git Repository Initialization Script

This script helps initialize the application directory as a Git repository
and set up the remote origin for updates.
"""

import os
import sys
import subprocess
from git import Repo, GitCommandError
from git.exc import InvalidGitRepositoryError, NoSuchPathError

def run_command(command, cwd=None):
    """Run a shell command and return the result"""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def init_git_repository():
    """Initialize the current directory as a Git repository"""
    current_dir = os.getcwd()
    
    print("Git Repository Initialization")
    print("=" * 40)
    print(f"Current directory: {current_dir}")
    print()
    
    # Check if this is already a Git repository
    try:
        repo = Repo(current_dir)
        print("✅ This directory is already a Git repository!")
        print(f"   Current branch: {repo.active_branch.name}")
        print(f"   Remotes: {[remote.name for remote in repo.remotes]}")
        return True
    except (InvalidGitRepositoryError, NoSuchPathError):
        print("❌ This directory is not a Git repository.")
        print()
    
    # Ask user if they want to initialize
    response = input("Do you want to initialize this as a Git repository? (y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("Git repository initialization cancelled.")
        return False
    
    print()
    print("Initializing Git repository...")
    
    # Initialize Git repository
    success, stdout, stderr = run_command("git init")
    if not success:
        print(f"❌ Failed to initialize Git repository: {stderr}")
        return False
    
    print("✅ Git repository initialized successfully!")
    
    # Add all files
    print("Adding files to repository...")
    success, stdout, stderr = run_command("git add .")
    if not success:
        print(f"❌ Failed to add files: {stderr}")
        return False
    
    # Make initial commit
    print("Making initial commit...")
    success, stdout, stderr = run_command('git commit -m "Initial commit"')
    if not success:
        print(f"❌ Failed to make initial commit: {stderr}")
        return False
    
    print("✅ Initial commit created successfully!")
    
    # Ask for remote repository URL
    print()
    print("Remote Repository Setup")
    print("-" * 30)
    print("To enable automatic updates, you need to set up a remote repository.")
    print("This can be on GitHub, GitLab, or any other Git hosting service.")
    print()
    
    remote_url = input("Enter the remote repository URL (or press Enter to skip): ").strip()
    
    if remote_url:
        print(f"Adding remote origin: {remote_url}")
        success, stdout, stderr = run_command(f'git remote add origin "{remote_url}"')
        if not success:
            print(f"❌ Failed to add remote: {stderr}")
            return False
        
        print("✅ Remote origin added successfully!")
        
        # Try to push to remote
        print("Pushing to remote repository...")
        success, stdout, stderr = run_command("git push -u origin main")
        if not success:
            print(f"⚠️  Warning: Failed to push to remote: {stderr}")
            print("   You may need to push manually later.")
        else:
            print("✅ Successfully pushed to remote repository!")
    
    print()
    print("Git repository setup completed!")
    print()
    print("Next steps:")
    print("1. Update your app_config.json with the repository URL")
    print("   Example: https://github.com/steveandjeff999/Obsidianscout.git")
    print("2. Use the web interface to configure Git updates")
    print("3. Make sure your remote repository has an app_config.json file")
    
    return True

def main():
    """Main function"""
    try:
        init_git_repository()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 