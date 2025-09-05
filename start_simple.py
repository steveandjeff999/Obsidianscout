#!/usr/bin/env python3
"""
Simple Server Launcher
Alternative way to start the server without the complex background workers
"""
import os
import sys

def main():
    try:
        # Set environment variables for better terminal support
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        
        print("ObsidianScout FRC Scouting Platform")
        print("=" * 40)
        print("Starting server...")
        print()
        
        # Import and run the main server
        exec(open('run.py').read())
        
    except KeyboardInterrupt:
        print("\nServer stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting server: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to continue...")
        sys.exit(1)

if __name__ == '__main__':
    main()
