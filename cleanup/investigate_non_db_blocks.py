#!/usr/bin/env python3
"""
Non-Database Login Blocking Investigation
Check for factors that could block login even after database deletion
"""
import os
import sys
from datetime import datetime, timedelta

def investigate_non_database_blocks():
    """Check for non-database factors that could block login"""
    try:
        from app import create_app
        from flask import current_app
        import json
        
        app = create_app()
        
        with app.app_context():
            print(" NON-DATABASE LOGIN BLOCKING INVESTIGATION")
            print("=" * 70)
            
            print("CHECKING POTENTIAL NON-DATABASE BLOCKING FACTORS:")
            print("-" * 70)
            
            # 1. Check for file-based session storage
            print("1. FILE-BASED SESSION STORAGE")
            print("-" * 40)
            
            # Check instance directory for session files
            instance_path = current_app.instance_path
            print(f"Instance path: {instance_path}")
            
            if os.path.exists(instance_path):
                instance_files = os.listdir(instance_path)
                print(f"Instance files: {instance_files}")
                
                # Look for Flask session files
                session_files = [f for f in instance_files if 'session' in f.lower()]
                if session_files:
                    print(f"️  Found session files: {session_files}")
                    for session_file in session_files:
                        file_path = os.path.join(instance_path, session_file)
                        try:
                            stat = os.stat(file_path)
                            print(f"   {session_file}: {stat.st_size} bytes, modified {datetime.fromtimestamp(stat.st_mtime)}")
                        except Exception as e:
                            print(f"   {session_file}: Error reading - {e}")
                else:
                    print(" No session files found")
            else:
                print(" No instance directory")
            
            # 2. Check for temporary/cache files that might store login state
            print(f"\n2. CACHE AND TEMPORARY FILES")
            print("-" * 40)
            
            current_dir = os.path.dirname(os.path.abspath(__file__))
            potential_cache_dirs = [
                os.path.join(current_dir, 'tmp'),
                os.path.join(current_dir, 'cache'),
                os.path.join(current_dir, '.cache'),
                os.path.join(current_dir, '__pycache__'),
                os.path.join(current_dir, 'app', '__pycache__'),
            ]
            
            for cache_dir in potential_cache_dirs:
                if os.path.exists(cache_dir):
                    files = os.listdir(cache_dir)
                    if files:
                        print(f"️  Found cache directory: {cache_dir}")
                        print(f"   Files: {len(files)} items")
                    else:
                        print(f" Empty cache directory: {cache_dir}")
                else:
                    print(f" No cache directory: {cache_dir}")
            
            # 3. Check for config files that might affect login
            print(f"\n3. CONFIGURATION FILES")
            print("-" * 40)
            
            config_files = [
                'app_config.json',
                'config.py',
                'config.json',
                '.env',
                'instance/config.py',
                'instance/config.json'
            ]
            
            for config_file in config_files:
                config_path = os.path.join(current_dir, config_file)
                if os.path.exists(config_path):
                    print(f"️  Found config file: {config_file}")
                    try:
                        stat = os.stat(config_path)
                        print(f"   Size: {stat.st_size} bytes, modified: {datetime.fromtimestamp(stat.st_mtime)}")
                        
                        # Try to read config files
                        if config_file.endswith('.json'):
                            try:
                                with open(config_path, 'r') as f:
                                    config_data = json.load(f)
                                    if any('login' in str(key).lower() or 'auth' in str(key).lower() for key in config_data.keys()):
                                        print(f"   ️  Contains auth-related settings")
                                    else:
                                        print(f"    No auth settings found")
                            except Exception as e:
                                print(f"   Error reading JSON: {e}")
                        
                    except Exception as e:
                        print(f"   Error accessing file: {e}")
                else:
                    print(f" No config file: {config_file}")
            
            # 4. Check Flask app configuration for login-related settings
            print(f"\n4. FLASK APP CONFIGURATION")
            print("-" * 40)
            
            auth_related_configs = [
                'SECRET_KEY',
                'WTF_CSRF_ENABLED',
                'WTF_CSRF_TIME_LIMIT',
                'PERMANENT_SESSION_LIFETIME',
                'SESSION_COOKIE_SECURE',
                'SESSION_COOKIE_HTTPONLY',
                'SESSION_COOKIE_SAMESITE',
                'LOGIN_DISABLED',
                'TESTING',
            ]
            
            for config_key in auth_related_configs:
                if config_key in current_app.config:
                    value = current_app.config[config_key]
                    print(f"   {config_key}: {value}")
                else:
                    print(f" {config_key}: Not set")
            
            # 5. Check for application state that persists across database deletion
            print(f"\n5. APPLICATION STATE & MEMORY")
            print("-" * 40)
            
            # Check if there are any global variables or cached objects
            print("Checking for cached authentication objects...")
            
            # Check if Flask-Login has any cached state
            try:
                from flask_login import current_user
                print(f"   Current user authenticated: {current_user.is_authenticated if current_user else 'No current_user'}")
            except Exception as e:
                print(f"   Flask-Login state: Error - {e}")
            
            # Check for any custom authentication caches
            try:
                from app.utils import brute_force_protection
                if hasattr(brute_force_protection, 'brute_force_protection'):
                    bf = brute_force_protection.brute_force_protection
                    if hasattr(bf, '_cached_attempts'):
                        print(f"   ️  Brute force cache exists: {len(getattr(bf, '_cached_attempts', {}))}")
                    else:
                        print(f"    No brute force cache found")
                else:
                    print(f"    No brute force protection instance")
            except Exception as e:
                print(f"   Brute force check error: {e}")
            
            # 6. Check for external files that might block login
            print(f"\n6. EXTERNAL BLOCKING FILES")
            print("-" * 40)
            
            blocking_files = [
                '.restart_flag',
                '.maintenance_mode',
                '.login_disabled',
                'DISABLE_LOGIN',
                'maintenance.lock',
                '.flask_restart_trigger'
            ]
            
            for blocking_file in blocking_files:
                file_path = os.path.join(current_dir, blocking_file)
                if os.path.exists(file_path):
                    print(f"️  Found potential blocking file: {blocking_file}")
                    try:
                        stat = os.stat(file_path)
                        print(f"   Size: {stat.st_size} bytes, created: {datetime.fromtimestamp(stat.st_ctime)}")
                        
                        # Try to read small files
                        if stat.st_size < 1000:
                            try:
                                with open(file_path, 'r') as f:
                                    content = f.read().strip()
                                    print(f"   Content: {content[:100]}...")
                            except:
                                print(f"   Content: [Binary or unreadable]")
                        else:
                            print(f"   Content: [File too large to display]")
                    except Exception as e:
                        print(f"   Error reading: {e}")
                else:
                    print(f" No blocking file: {blocking_file}")
            
            # 7. Check application startup code for login blocks
            print(f"\n7. STARTUP CODE ANALYSIS")
            print("-" * 40)
            
            print("Checking run.py for potential login-blocking code...")
            
            # Read run.py to check for anything that might block login
            run_py_path = os.path.join(current_dir, 'run.py')
            if os.path.exists(run_py_path):
                try:
                    with open(run_py_path, 'r') as f:
                        run_py_content = f.read()
                    
                    # Look for potential blocking patterns
                    blocking_patterns = [
                        'LOGIN_DISABLED',
                        'disable_login',
                        'block_login',
                        'maintenance_mode',
                        'TESTING = True',
                        'DEBUG = False'
                    ]
                    
                    found_patterns = []
                    for pattern in blocking_patterns:
                        if pattern.lower() in run_py_content.lower():
                            found_patterns.append(pattern)
                    
                    if found_patterns:
                        print(f"️  Found potential blocking patterns: {found_patterns}")
                    else:
                        print(" No obvious blocking patterns in run.py")
                    
                    # Check for hardcoded authentication bypasses or blocks
                    if 'return False' in run_py_content and 'login' in run_py_content.lower():
                        print("️  Found 'return False' near login code - potential hardcoded block")
                    else:
                        print(" No hardcoded login blocks found")
                        
                except Exception as e:
                    print(f"Error reading run.py: {e}")
            
            # 8. Check environment variables
            print(f"\n8. ENVIRONMENT VARIABLES")
            print("-" * 40)
            
            auth_env_vars = [
                'FLASK_ENV',
                'FLASK_DEBUG',
                'LOGIN_DISABLED',
                'DISABLE_AUTH',
                'TESTING',
                'MAINTENANCE_MODE'
            ]
            
            for env_var in auth_env_vars:
                value = os.environ.get(env_var)
                if value:
                    print(f"️  {env_var}: {value}")
                else:
                    print(f" {env_var}: Not set")
            
            # Summary and recommendations
            print(f"\n9. SUMMARY & RECOMMENDATIONS")
            print("-" * 40)
            
            print("POTENTIAL NON-DATABASE BLOCKING FACTORS:")
            print("1. File-based sessions (Flask-Session)")
            print("2. Application configuration settings")
            print("3. Environment variables")
            print("4. Cached authentication state")
            print("5. External lock/flag files")
            print("6. Hardcoded blocks in application code")
            print("7. Browser/client-side caching")
            print()
            print("TO COMPLETELY RESET LOGIN SYSTEM:")
            print("1. Delete database files (already done)")
            print("2. Clear instance directory: rm -rf instance/")
            print("3. Clear cache directories: rm -rf __pycache__/ app/__pycache__/")
            print("4. Clear environment variables related to auth")
            print("5. Restart application completely")
            print("6. Clear browser cache/cookies")
            print("7. Check for any .lock or .flag files")
            
    except Exception as e:
        print(f" Error during investigation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    investigate_non_database_blocks()
