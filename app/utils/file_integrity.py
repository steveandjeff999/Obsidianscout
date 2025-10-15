import hashlib
import os
import json
import threading
import time
from datetime import datetime, timezone
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash

class FileIntegrityMonitor:
    def __init__(self, app=None):
        self.app = app
        self.checksums = {}
        self.integrity_compromised = False
        self.integrity_password_hash = None
        self.warning_only_mode = True  # Always use warning-only mode
        self.checksums_file = 'instance/file_checksums.json'
        self.config_file = 'instance/integrity_config.json'
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        self.app = app
        app.file_integrity_monitor = self
        
        # Load existing checksums and config
        self.load_config()
        self.load_checksums()
        
        # Always enable warning-only mode
        self.warning_only_mode = True
        self.save_config()
        
        # Set default integrity password if not set (for compatibility)
        if not self.integrity_password_hash:
            self.set_integrity_password("admin123")  # Default password
    
    def get_file_checksum(self, file_path):
        """Calculate SHA256 checksum of a file"""
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"Error calculating checksum for {file_path}: {e}")
            return None
    
    def should_monitor_file(self, file_path):
        """Determine if a file should be monitored"""
        # Skip certain files and directories
        skip_patterns = [
            '__pycache__',
            '.pyc',
            '.git',
            'file_checksums.json',
            'integrity_config.json',
            'scouting.db',
            'game_config.json',  # Skip configuration files as requested
            'ai_config.json',
            'uploads/',
            '.log',
            '.tmp',
            'ssl/',
            'cert.pem',
            'key.pem'
        ]
        
        for pattern in skip_patterns:
            if pattern in file_path:
                return False
        
        return True
    
    def scan_directory(self, directory):
        """Recursively scan directory and calculate checksums"""
        checksums = {}
        
        for root, dirs, files in os.walk(directory):
            # Skip hidden directories and __pycache__
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, directory)
                
                if self.should_monitor_file(relative_path):
                    checksum = self.get_file_checksum(file_path)
                    if checksum:
                        checksums[relative_path] = {
                            'checksum': checksum,
                            'modified': os.path.getmtime(file_path),
                            'size': os.path.getsize(file_path)
                        }
        
        return checksums
    
    def initialize_checksums(self):
        """Initialize checksums for all monitored files"""
        print("Initializing file integrity monitoring...")
        
        # Get the application root directory
        if self.app:
            app_root = os.path.dirname(os.path.abspath(self.app.root_path))
        else:
            app_root = os.getcwd()
        
        # Store the previous checksums to detect changes
        previous_checksums = self.checksums.copy() if self.checksums else {}
        
        # Generate new checksums
        self.checksums = self.scan_directory(app_root)
        self.save_checksums()
        
        print(f"File integrity monitoring initialized. Monitoring {len(self.checksums)} files.")
    
    def check_integrity(self):
        """Check if any monitored files have been modified"""
        if not self.checksums:
            return True  # No checksums to check
        
        # Get the application root directory
        if self.app:
            app_root = os.path.dirname(os.path.abspath(self.app.root_path))
        else:
            app_root = os.getcwd()
        
        current_checksums = self.scan_directory(app_root)
        modified_files = []
        
        # Check for modified files
        for file_path, original_data in self.checksums.items():
            if file_path in current_checksums:
                current_data = current_checksums[file_path]
                if original_data['checksum'] != current_data['checksum']:
                    modified_files.append(file_path)
            else:
                # File was deleted
                modified_files.append(f"{file_path} (deleted)")
        
        # Check for new files
        for file_path in current_checksums:
            if file_path not in self.checksums:
                modified_files.append(f"{file_path} (new)")
        
        if modified_files:
            print(f"File integrity compromised! Modified files: {modified_files}")
            if not self.warning_only_mode:
                self.integrity_compromised = True
            else:
                print("WARNING: File integrity compromised but running in warning-only mode.")
            return False
        
        return True
    
    def verify_integrity_password(self, password):
        """Verify the integrity password"""
        if not self.integrity_password_hash:
            return False
        return check_password_hash(self.integrity_password_hash, password)
    
    def set_integrity_password(self, password):
        """Set the integrity password"""
        self.integrity_password_hash = generate_password_hash(password)
        self.save_config()
    
    def reset_integrity(self):
        """Reset integrity monitoring after successful password verification"""
        self.integrity_compromised = False
        self.initialize_checksums()
        # Perform an integrity check immediately
        integrity_ok = self.check_integrity()
        if integrity_ok:
            print("File integrity monitoring reset and verified.")
        else:
            print("File integrity monitoring reset, but some files are still modified.")
        return integrity_ok
    
    # Monitoring functionality has been removed - integrity is now checked only at startup
    
    def save_checksums(self):
        """Save checksums to file"""
        try:
            os.makedirs(os.path.dirname(self.checksums_file), exist_ok=True)
            with open(self.checksums_file, 'w') as f:
                json.dump({
                    'checksums': self.checksums,
                    'created': datetime.now(timezone.utc).isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving checksums: {e}")
    
    def load_checksums(self):
        """Load checksums from file"""
        try:
            if os.path.exists(self.checksums_file):
                with open(self.checksums_file, 'r') as f:
                    data = json.load(f)
                    self.checksums = data.get('checksums', {})
                    print(f"Loaded {len(self.checksums)} file checksums")
        except Exception as e:
            print(f"Error loading checksums: {e}")
            self.checksums = {}
    
    def save_config(self):
        """Save integrity configuration"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump({
                    'integrity_password_hash': self.integrity_password_hash,
                    'warning_only_mode': self.warning_only_mode,
                    'created': datetime.now(timezone.utc).isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving integrity config: {e}")
    
    def load_config(self):
        """Load integrity configuration"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.integrity_password_hash = data.get('integrity_password_hash')
                    self.warning_only_mode = data.get('warning_only_mode', True)  # Default to True
                    print("Loaded integrity configuration")
        except Exception as e:
            print(f"Error loading integrity config: {e}")
