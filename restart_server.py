#!/usr/bin/env python3
"""
Simple script to manually restart the server.
This script attempts immediate restart first, then falls back to restart flag if needed.
"""

import os
import sys
import subprocess
from datetime import datetime
import time
import threading
import signal

def create_restart_flag():
    """Create a restart flag file to trigger server restart (fallback method)"""
    try:
        # Get the application root directory
        app_root = os.path.dirname(os.path.abspath(__file__))
        restart_flag = os.path.join(app_root, '.restart_flag')
        
        # Create restart flag file
        with open(restart_flag, 'w') as f:
            f.write(f"Restart requested at {datetime.now().isoformat()}")
        
        print("✅ Restart flag created successfully!")
        print(f"📁 Flag file: {restart_flag}")
        print("🔄 The server will restart on the next request.")
        print("💡 You may need to refresh your browser or make a new request.")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating restart flag: {str(e)}")
        return False

def restart_server_immediately():
    """Attempt to restart the server gracefully using Flask's reload mechanism"""
    try:
        # Get the current script path
        app_root = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(app_root, 'run.py')
        
        print("🔄 Attempting graceful server restart...")
        
        # Method 1: Try Flask reload mechanism
        try:
            restart_trigger = os.path.join(app_root, '.flask_restart_trigger')
            with open(restart_trigger, 'w') as f:
                f.write(f"Restart triggered at {datetime.now().isoformat()}")
            
            print("✅ Flask reload trigger created")
            print("🔄 The server should reload automatically")
            print("💡 If it doesn't reload, the server may not be running with reload enabled")
            
            # Clean up trigger file after a delay
            def cleanup_trigger():
                time.sleep(2)
                try:
                    if os.path.exists(restart_trigger):
                        os.remove(restart_trigger)
                except:
                    pass
            
            threading.Thread(target=cleanup_trigger, daemon=True).start()
            return True
            
        except Exception as e:
            print(f"❌ Flask reload mechanism failed: {e}")
        
        # Method 2: Check if we're running from main script and try signal-based restart
        if os.path.abspath(sys.argv[0]) == os.path.abspath(script_path):
            print("✅ Running from main script - attempting signal-based restart...")
            
            # For Windows, use subprocess to restart
            if os.name == 'nt':  # Windows
                subprocess.Popen([sys.executable, script_path], 
                               cwd=app_root,
                               creationflags=subprocess.DETACHED_PROCESS)
                print("✅ New server process started. Exiting current process...")
                # Give the new process time to start
                time.sleep(2)
                # Exit gracefully
                os._exit(0)
            else:
                # For Unix, try to send signal to parent
                try:
                    parent_pid = os.getppid()
                    if parent_pid != 1:  # Not the init process
                        os.kill(parent_pid, signal.SIGTERM)
                        print("✅ Restart signal sent to parent process")
                        return True
                except Exception as e:
                    print(f"❌ Signal-based restart failed: {e}")
        else:
            print("ℹ️ Not running from main script - using restart flag method")
        
        # Method 3: Fallback to restart flag
        print("🔄 Using restart flag fallback method...")
        return create_restart_flag()
            
    except Exception as e:
        print(f"❌ Error with graceful restart: {str(e)}")
        print("🔄 Falling back to restart flag method...")
        return create_restart_flag()

def check_restart_flag():
    """Check if restart flag exists"""
    try:
        app_root = os.path.dirname(os.path.abspath(__file__))
        restart_flag = os.path.join(app_root, '.restart_flag')
        
        if os.path.exists(restart_flag):
            print("🔄 Restart flag exists - server will restart on next request")
            return True
        else:
            print("✅ No restart flag found - server is running normally")
            return False
            
    except Exception as e:
        print(f"❌ Error checking restart flag: {str(e)}")
        return False

def remove_restart_flag():
    """Remove the restart flag file"""
    try:
        app_root = os.path.dirname(os.path.abspath(__file__))
        restart_flag = os.path.join(app_root, '.restart_flag')
        
        if os.path.exists(restart_flag):
            os.remove(restart_flag)
            print("✅ Restart flag removed")
            return True
        else:
            print("ℹ️ No restart flag found to remove")
            return False
            
    except Exception as e:
        print(f"❌ Error removing restart flag: {str(e)}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "create" or command == "restart":
            restart_server_immediately()
        elif command == "check" or command == "status":
            check_restart_flag()
        elif command == "remove" or command == "clear":
            remove_restart_flag()
        else:
            print("Usage:")
            print("  python restart_server.py [create|restart]  - Restart server immediately")
            print("  python restart_server.py [check|status]    - Check restart flag status")
            print("  python restart_server.py [remove|clear]    - Remove restart flag")
    else:
        # Default action: restart server immediately
        restart_server_immediately() 