#!/usr/bin/env python3
"""
Server Mode Switcher

This script allows you to easily switch between Waitress and Flask development server
by modifying the USE_WAITRESS flag in run.py
"""

import os
import sys

def modify_server_flag(use_waitress):
    """Modify the USE_WAITRESS flag in run.py"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    run_py_path = os.path.join(script_dir, 'run.py')
    
    if not os.path.exists(run_py_path):
        print(" Error: run.py not found!")
        return False
    
    # Read the file
    with open(run_py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace the flag
    if use_waitress:
        new_line = "USE_WAITRESS = True  # Change this to False to use Flask development server with SSL"
        old_patterns = [
            "USE_WAITRESS = False  # Change this to False to use Flask development server with SSL",
            "USE_WAITRESS = False",
            "USE_WAITRESS = True"
        ]
    else:
        new_line = "USE_WAITRESS = False  # Change this to False to use Flask development server with SSL"
        old_patterns = [
            "USE_WAITRESS = True  # Change this to False to use Flask development server with SSL",
            "USE_WAITRESS = True",
            "USE_WAITRESS = False"
        ]
    
    # Find and replace the line
    lines = content.split('\n')
    modified = False
    
    for i, line in enumerate(lines):
        if any(pattern in line for pattern in old_patterns):
            lines[i] = new_line
            modified = True
            break
    
    if not modified:
        print(" Error: Could not find USE_WAITRESS flag in run.py")
        return False
    
    # Write back to file
    with open(run_py_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return True

def main():
    if len(sys.argv) != 2 or sys.argv[1].lower() not in ['waitress', 'flask']:
        print("Usage: python server_switcher.py [waitress|flask]")
        print()
        print("Examples:")
        print("  python server_switcher.py waitress    # Use Waitress WSGI server")
        print("  python server_switcher.py flask       # Use Flask dev server with SSL")
        sys.exit(1)
    
    mode = sys.argv[1].lower()
    use_waitress = (mode == 'waitress')
    
    print(f" Switching to {'Waitress' if use_waitress else 'Flask development server'}...")
    
    if modify_server_flag(use_waitress):
        if use_waitress:
            print(" Server mode set to: Waitress WSGI Server")
            print("    Production-ready server")
            print("    HTTP only (use reverse proxy for SSL)")
            print("    SocketIO polling mode")
            print("    URL: http://localhost:5000")
        else:
            print(" Server mode set to: Flask Development Server")
            print("    SSL/HTTPS support enabled")
            print("    Full WebSocket support")
            print("   ️  Debug mode enabled")
            print("    URL: https://localhost:5000")
        
        print()
        print("Now run: python run.py")
    else:
        print(" Failed to modify server configuration")
        sys.exit(1)

if __name__ == '__main__':
    main()
