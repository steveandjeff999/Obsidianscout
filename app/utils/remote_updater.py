#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remote updater helper - downloads a ZIP from a URL, runs the repository update logic,
edits run.py to toggle USE_WAITRESS and restarts the server.

This script is intended to be launched locally (on the server being updated) by
the `/api/sync/update` endpoint. It performs best-effort process management and
will attempt to leave the updated server running.
"""
from __future__ import annotations

import sys
import os
import signal
import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

# Ensure proper encoding for Windows
if sys.platform == 'win32':
    # Force UTF-8 encoding for stdout/stderr
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    import requests
except Exception:
    requests = None

try:
    import urllib.request
    import urllib.error
except Exception:
    urllib = None


def download_zip(url: str, dest: Path) -> Path:
    """Download ZIP using requests if available, otherwise fallback to urllib"""
    print(f"Downloading update from {url} to {dest}...", flush=True)
    
    if requests is not None:
        try:
            r = requests.get(url, stream=True, timeout=60)
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(1024 * 64):
                    if chunk:
                        f.write(chunk)
            print("SUCCESS: Download completed using requests", flush=True)
            return dest
        except Exception as e:
            print(f"ERROR: Requests download failed: {e}", flush=True)
            if urllib is None:
                raise RuntimeError(f'Download failed with requests: {e}')
            # Fall through to urllib
    
    if urllib is not None:
        try:
            print("Retrying download with urllib...", flush=True)
            with urllib.request.urlopen(url, timeout=60) as response:
                with open(dest, 'wb') as f:
                    while True:
                        chunk = response.read(1024 * 64)
                        if not chunk:
                            break
                        f.write(chunk)
            print("SUCCESS: Download completed using urllib", flush=True)
            return dest
        except urllib.error.URLError as e:
            raise RuntimeError(f'Download failed with urllib: {e}')
        except Exception as e:
            raise RuntimeError(f'Download failed: {e}')
    
    raise RuntimeError('Neither requests nor urllib are available for downloading')


def force_kill_file_locks(file_path: Path, max_attempts: int = 3):
    """
    Attempt to force release file locks by finding and killing processes using the file
    """
    print(f"Attempting to force release locks on: {file_path}", flush=True)
    
    if os.name == 'nt':
        # Windows: use handle.exe or openfiles command to find file locks
        try:
            # Try using openfiles command (built into Windows)
            result = subprocess.run(['openfiles', '/query', '/fo', 'csv'], 
                                  capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    if str(file_path).lower() in line.lower():
                        # Parse CSV format to get process info
                        parts = line.strip('"').split('","')
                        if len(parts) >= 3:
                            try:
                                hostname = parts[0]
                                process_id = parts[1]
                                open_file = parts[2]
                                print(f"Found file lock: PID {process_id} has {open_file}", flush=True)
                                
                                # Try to kill the process
                                subprocess.run(['taskkill', '/PID', process_id, '/F'], 
                                             capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                print(f"Killed process {process_id} holding file lock", flush=True)
                            except Exception as e:
                                print(f"Could not kill process: {e}", flush=True)
            else:
                print("openfiles command failed, trying alternative approach", flush=True)
        except Exception as e:
            print(f"Could not use openfiles: {e}", flush=True)
    else:
        # Linux/Unix: use lsof to find file locks
        try:
            result = subprocess.run(['lsof', str(file_path)], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            print(f"Found file lock: PID {pid} has {file_path}", flush=True)
                            os.kill(pid, signal.SIGTERM)
                            time.sleep(2)
                            print(f"Killed process {pid} holding file lock", flush=True)
                        except (ValueError, ProcessLookupError) as e:
                            print(f"Could not kill process: {e}", flush=True)
        except FileNotFoundError:
            print("lsof not available for file lock detection", flush=True)
        except Exception as e:
            print(f"Could not use lsof: {e}", flush=True)


def wait_for_file_unlock(file_path: Path, max_attempts: int = 3, wait_seconds: int = 10):
    """
    Wait for a file to become unlocked, with retry and force-kill mechanisms
    """
    for attempt in range(max_attempts):
        try:
            # Test if we can open the file for writing
            with open(file_path, 'r+b') as f:
                pass  # File is accessible
            print(f" File accessible on attempt {attempt + 1}: {file_path}", flush=True)
            return True
        except Exception as e:
            print(f" File locked on attempt {attempt + 1}: {file_path} - {e}", flush=True)
            
            if attempt < max_attempts - 1:  # Not the last attempt
                print(f"Waiting {wait_seconds} seconds before retry...", flush=True)
                time.sleep(wait_seconds)
                
                # On second attempt, try to force kill processes locking the file
                if attempt == 1:
                    force_kill_file_locks(file_path)
                    time.sleep(5)  # Additional wait after killing processes
    
    print(f" File remains locked after {max_attempts} attempts: {file_path}", flush=True)
    return False


def find_locked_files_in_directory(directory: Path, max_check: int = 100):
    """
    Scan directory for locked files that might prevent update
    """
    locked_files = []
    checked_count = 0
    
    try:
        for root, dirs, files in os.walk(directory):
            if checked_count >= max_check:
                break
                
            for file in files:
                if checked_count >= max_check:
                    break
                    
                file_path = Path(root) / file
                try:
                    # Try to open file for writing to check if locked
                    with open(file_path, 'r+b') as f:
                        pass
                except Exception as e:
                    if "being used by another process" in str(e) or "Permission denied" in str(e):
                        locked_files.append(file_path)
                        print(f"Found locked file: {file_path.relative_to(directory)}", flush=True)
                
                checked_count += 1
        
        if checked_count >= max_check:
            print(f"Note: Only checked first {max_check} files for locks", flush=True)
            
    except Exception as e:
        print(f"Error scanning directory for locks: {e}", flush=True)
    
    return locked_files


def set_use_waitress_and_port_in_run(run_py: Path, use_waitress: bool, port: int):
    """Set USE_WAITRESS in run.py and ensure proper PORT environment handling"""
    try:
        text = run_py.read_text(encoding='utf-8')
        
        # Replace USE_WAITRESS
        new_waitress_line = f"USE_WAITRESS = {str(bool(use_waitress))}  # Updated by remote_updater"
        import re
        waitress_pattern = re.compile(r"^USE_WAITRESS\s*=.*$", re.M)
        if waitress_pattern.search(text):
            text = waitress_pattern.sub(new_waitress_line, text)
        else:
            # Fallback: insert near top
            text = new_waitress_line + '\n' + text
        
        # Ensure the PORT environment variable default matches our target port
        # Look for the line: port = int(os.environ.get('PORT', 8080))
        port_pattern = re.compile(r"port\s*=\s*int\(os\.environ\.get\(['\"]PORT['\"],\s*\d+\)\)", re.M)
        new_port_line = f"port = int(os.environ.get('PORT', {port}))"
        
        if port_pattern.search(text):
            text = port_pattern.sub(new_port_line, text)
            print(f" Updated port default in run.py to {port}", flush=True)
        else:
            print("Warning: Could not find PORT environment line in run.py", flush=True)
        
        run_py.write_text(text, encoding='utf-8')
        print(f" Updated run.py: USE_WAITRESS={use_waitress}, PORT default={port}", flush=True)
        
    except UnicodeDecodeError as e:
        print(f"Warning: Could not modify run.py due to encoding error: {e}", flush=True)
        print("Server will use default settings", flush=True)
    except Exception as e:
        print(f"Warning: Could not modify run.py: {e}", flush=True)


def start_server(run_py_path: Path, port: int) -> int:
    env = os.environ.copy()
    env['PORT'] = str(port)
    # Start the server as a background process
    log_dir = Path.cwd() / 'instance'
    log_dir.mkdir(parents=True, exist_ok=True)
    out = open(log_dir / 'server_update_stdout.log', 'ab')
    err = open(log_dir / 'server_update_stderr.log', 'ab')
    proc = subprocess.Popen([sys.executable, str(run_py_path)], env=env, stdout=out, stderr=err, close_fds=True)
    return proc.pid


def kill_server_processes(keep_pids: list[int]):
    """
    Kill Python processes that are likely running the server.
    More targeted than killing ALL Python processes.
    """
    killed = []
    current_pid = os.getpid()
    
    # On Windows, use tasklist and taskkill
    if os.name == 'nt':
        try:
            import subprocess
            # Get list of python processes with command lines
            result = subprocess.run(['wmic', 'process', 'where', 'name="python.exe"', 'get', 'ProcessId,CommandLine', '/format:csv'], 
                                  capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    if line.strip() and ',' in line:
                        parts = line.split(',')
                        if len(parts) >= 3:
                            try:
                                pid = int(parts[1]) if parts[1].isdigit() else None
                                command_line = parts[2].lower() if len(parts) > 2 else ''
                                
                                if pid and pid != current_pid and pid not in keep_pids:
                                    # Only kill if it looks like a server process
                                    server_indicators = ['run.py', 'flask', 'waitress', 'gunicorn', 'app.py']
                                    if any(indicator in command_line for indicator in server_indicators):
                                        print(f"Killing server process PID {pid}: {command_line[:100]}", flush=True)
                                        subprocess.run(['taskkill', '/PID', str(pid), '/F'], 
                                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                        killed.append(pid)
                            except (ValueError, subprocess.SubprocessError, IndexError):
                                continue
        except Exception as e:
            print(f"Warning: Could not use wmic, falling back to tasklist: {e}", flush=True)
            # Fallback to simpler method
            try:
                result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'], 
                                      capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')[1:]  # Skip header
                    for line in lines:
                        if line.strip():
                            parts = line.strip('"').split('","')
                            if len(parts) >= 2:
                                try:
                                    pid = int(parts[1])
                                    if pid not in keep_pids and pid != current_pid:
                                        # Be more cautious - only kill if we're sure it's not the updater
                                        print(f"Killing Python process PID {pid}", flush=True)
                                        subprocess.run(['taskkill', '/PID', str(pid), '/F'], 
                                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                        killed.append(pid)
                                except (ValueError, subprocess.SubprocessError):
                                    continue
            except Exception:
                print("Warning: Could not kill processes on Windows", flush=True)
    else:
        # Unix/Linux process management
        try:
            my_uid = os.getuid()
            proc_dir = Path('/proc')
            for p in proc_dir.iterdir():
                if not p.name.isdigit():
                    continue
                pid = int(p.name)
                if pid in keep_pids or pid == current_pid:
                    continue
                try:
                    # Read cmdline
                    cmdline = (p / 'cmdline').read_bytes().decode('utf-8', errors='ignore')
                    if 'python' in cmdline.lower() and any(indicator in cmdline.lower() for indicator in ['run.py', 'flask', 'waitress', 'gunicorn', 'app.py']):
                        # Check ownership
                        try:
                            uid = int((p / 'status').read_text().split('Uid:')[1].strip().split()[0])
                        except Exception:
                            uid = None
                        if uid is not None and uid != my_uid:
                            continue
                        try:
                            os.kill(pid, signal.SIGTERM)
                            killed.append(pid)
                        except Exception:
                            try:
                                os.kill(pid, signal.SIGKILL)
                                killed.append(pid)
                            except Exception:
                                pass
                except Exception:
                    continue
        except Exception:
            pass  # If Unix process management fails, continue without killing
    
    return killed


def stop_server_on_port(port: int, keep_pids: list[int]):
    """
    Find and stop processes using the specified port.
    Much safer than killing all Python processes.
    """
    killed = []
    current_pid = os.getpid()
    
    if os.name == 'nt':
        # Windows: use netstat to find processes using the port
        try:
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                pid = int(parts[-1])
                                if pid != current_pid and pid not in keep_pids:
                                    print(f"Found process using port {port}: PID {pid}", flush=True)
                                    subprocess.run(['taskkill', '/PID', str(pid), '/F'], 
                                                 capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                    killed.append(pid)
                            except (ValueError, subprocess.SubprocessError):
                                continue
        except Exception as e:
            print(f"Warning: Could not check port usage: {e}", flush=True)
    else:
        # Unix/Linux: use lsof or ss
        try:
            # Try lsof first
            result = subprocess.run(['lsof', f'-i:{port}'], capture_output=True, text=True)
            if result.returncode == 0:
                for line in result.stdout.split('\n')[1:]:  # Skip header
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            if pid != current_pid and pid not in keep_pids:
                                print(f"Found process using port {port}: PID {pid}", flush=True)
                                os.kill(pid, signal.SIGTERM)
                                killed.append(pid)
                        except (ValueError, ProcessLookupError):
                            continue
        except FileNotFoundError:
            # lsof not available, try ss
            try:
                result = subprocess.run(['ss', '-tlnp'], capture_output=True, text=True)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if f':{port}' in line:
                            # Parse ss output to find PID
                            if 'pid=' in line:
                                pid_part = line.split('pid=')[1].split(',')[0]
                                try:
                                    pid = int(pid_part)
                                    if pid != current_pid and pid not in keep_pids:
                                        print(f"Found process using port {port}: PID {pid}", flush=True)
                                        os.kill(pid, signal.SIGTERM)
                                        killed.append(pid)
                                except (ValueError, ProcessLookupError):
                                    continue
            except FileNotFoundError:
                print("Warning: Neither lsof nor ss available for port checking", flush=True)
        except Exception as e:
            print(f"Warning: Could not check port usage: {e}", flush=True)
    
    return killed


def detect_original_server_port():
    """
    Try to detect what port the original server was using.
    This helps restore the same port after update.
    """
    detected_ports = []
    
    if os.name == 'nt':
        # Windows: check what ports have Python processes listening
        try:
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'LISTENING' in line and ':' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                # Extract port from address like "0.0.0.0:8081"
                                addr_part = parts[1]
                                if ':' in addr_part:
                                    port = int(addr_part.split(':')[-1])
                                    pid = int(parts[-1])
                                    # Check if it's a Python process
                                    proc_result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV'], 
                                                               capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                    if 'python' in proc_result.stdout.lower():
                                        detected_ports.append(port)
                            except (ValueError, IndexError):
                                continue
        except Exception:
            pass
    else:
        # Unix/Linux: use lsof or ss
        try:
            result = subprocess.run(['lsof', '-i', '-P', '-n'], capture_output=True, text=True)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'python' in line.lower() and 'LISTEN' in line:
                        parts = line.split()
                        for part in parts:
                            if ':' in part and part.count(':') == 1:
                                try:
                                    port = int(part.split(':')[-1])
                                    detected_ports.append(port)
                                except ValueError:
                                    continue
        except FileNotFoundError:
            pass
    
    # Return most common web server ports if found
    common_ports = [8080, 8081, 5000, 8000, 80, 443]
    for port in common_ports:
        if port in detected_ports:
            return port
    
    # Return first detected port if any
    return detected_ports[0] if detected_ports else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip-url', dest='zip_url', required=True)
    parser.add_argument('--use-waitress', dest='use_waitress', action='store_true')
    parser.add_argument('--port', dest='port', type=int, default=8080)
    args = parser.parse_args()

    # Try to detect the original server port before stopping it
    print("Detecting original server port...", flush=True)
    original_port = detect_original_server_port()
    if original_port:
        print(f"Detected original server running on port {original_port}", flush=True)
        # Use detected port instead of command line argument if available
        final_port = original_port
    else:
        print("Could not detect original port, using provided port", flush=True)
        final_port = args.port

    print("Starting remote updater...", flush=True)
    print(f"Download URL: {args.zip_url}", flush=True)
    print(f"Use Waitress: {args.use_waitress}", flush=True)
    print(f"Target Port: {final_port} (original: {original_port}, provided: {args.port})", flush=True)

    # Find the correct repo root
    script_path = Path(__file__).resolve()
    print(f"Script path: {script_path}", flush=True)
    
    # Try different possible repo root locations
    possible_roots = [
        script_path.parent.parent,  # Normal: app/utils/remote_updater.py -> repo_root
        Path.cwd(),  # Current working directory
        script_path.parent.parent.parent,  # In case we're deeper
    ]
    
    repo_root = None
    for candidate in possible_roots:
        run_py_path = candidate / 'run.py'
        print(f"Checking for run.py at: {run_py_path}", flush=True)
        if run_py_path.exists():
            repo_root = candidate
            print(f"Found repo root: {repo_root}", flush=True)
            break
    
    if repo_root is None:
        print("Error: Could not find repo root (run.py not found)", flush=True)
        print(f"Current working directory: {Path.cwd()}", flush=True)
        print(f"Script directory: {script_path.parent}", flush=True)
        sys.exit(1)
        
    run_py = repo_root / 'run.py'
    
    # Change to repo root directory
    original_cwd = Path.cwd()
    os.chdir(repo_root)
    print(f"Changed working directory to: {repo_root}", flush=True)
    
    # Environment diagnostics
    print(f"Python executable: {sys.executable}", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    if requests is None:
        print("Warning: requests module not available - trying to install it...", flush=True)
        try:
            import subprocess
            result = subprocess.run([
                sys.executable, '-m', 'pip', 'install', 'requests'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("SUCCESS: Successfully installed requests", flush=True)
                # Try to import again
                try:
                    import requests as new_requests
                    globals()['requests'] = new_requests
                    print("SUCCESS: requests module is now available", flush=True)
                except ImportError:
                    print("ERROR: Failed to import requests after installation", flush=True)
            else:
                print(f"ERROR: Failed to install requests: {result.stderr}", flush=True)
                print("Will use urllib fallback", flush=True)
        except Exception as e:
            print(f"ERROR: Error installing requests: {e}", flush=True)
            print("Will use urllib fallback", flush=True)
    else:
        print("SUCCESS: requests module is available", flush=True)
        
    if urllib is None:
        print("ERROR: urllib not available either", flush=True)
    else:
        print("SUCCESS: urllib is available as fallback", flush=True)

    # Download zip
    tmpdir = Path(tempfile.mkdtemp(prefix='obs_remote_update_'))
    zip_path = tmpdir / 'release.zip'
    try:
        print(f"Downloading update from {args.zip_url} to {zip_path}...", flush=True)
        download_zip(args.zip_url, zip_path)

        # Backup sync server configuration before update
        print("Backing up sync server configuration...", flush=True)
        try:
            backup_result = subprocess.run([
                sys.executable, 'sync_config_manager.py', '--backup'
            ], capture_output=True, text=True, cwd=repo_root)
            if backup_result.returncode == 0:
                print("SUCCESS: Sync config backed up successfully", flush=True)
            else:
                print(f"Warning: Sync config backup warning: {backup_result.stderr}", flush=True)
        except Exception as e:
            print(f"Warning: Could not backup sync config: {e}", flush=True)

        # Run perform_update from update_from_github_file as subprocess to avoid circular imports
        print("Applying update with detailed logging...", flush=True)
        
        # Log what files exist before update
        print("=== PRE-UPDATE FILE CHECK ===", flush=True)
        pre_update_assistant_files = list((repo_root / 'app' / 'assistant').glob('*.py'))
        print(f"Assistant Python files before update: {[f.name for f in pre_update_assistant_files]}", flush=True)
        
        pre_update_db_files = list(repo_root.glob('*.db*')) + list((repo_root / 'instance').glob('*.db*'))
        print(f"Database files before update: {[str(f.relative_to(repo_root)) for f in pre_update_db_files if f.exists()]}", flush=True)
        print("=== END PRE-UPDATE CHECK ===", flush=True)
        
        # First, try to stop any running server processes more safely
        print("Stopping any running server processes...", flush=True)
        try:
            # Instead of killing all processes, try a more targeted approach
            # Look for processes using the server port
            killed_before = stop_server_on_port(final_port, [os.getpid()])
            if killed_before:
                print(f"Stopped server processes: {killed_before}", flush=True)
                time.sleep(5)  # Give more time for database files to be released
            else:
                print("No running server found on target port", flush=True)
            
            # Additional wait for database file locks to be released
            print("Waiting for database files to be released...", flush=True)
            time.sleep(3)
            
        except Exception as e:
            print(f"Warning: Could not stop server processes: {e}", flush=True)
        
        # Check if critical database files are accessible before update
        print("Checking database file accessibility and creating safety copies...", flush=True)
        
        # Find ALL database files in workspace - be comprehensive
        all_db_files = []
        for db_pattern in ['*.db', '*.db-wal', '*.db-shm', '*.sqlite', '*.sqlite3']:
            all_db_files.extend(repo_root.glob(db_pattern))
            all_db_files.extend((repo_root / 'instance').glob(db_pattern))
            
        # Remove duplicates and ensure they exist
        db_files_to_check = list(set(f for f in all_db_files if f.exists()))
        
        print(f"Found {len(db_files_to_check)} database files to protect:", flush=True)
        for db_file in db_files_to_check:
            print(f"  - {db_file.relative_to(repo_root)}", flush=True)
        
        # Create safety copies of critical database files
        safety_backup_dir = repo_root / 'temp_db_backup'
        safety_backup_dir.mkdir(exist_ok=True)
        
        safety_copies = []
        locked_files = []
        for db_file in db_files_to_check:
            if db_file.exists():
                try:
                    # Create a safety copy before update
                    safety_copy = safety_backup_dir / db_file.name
                    shutil.copy2(db_file, safety_copy)
                    safety_copies.append((db_file, safety_copy))
                    print(f" Safety copy created: {db_file.name}", flush=True)
                    
                    # Try to open the original file to check if it's locked
                    with open(db_file, 'r+b') as f:
                        pass  # Just check if we can open it
                    print(f" Database file accessible: {db_file.name}", flush=True)
                except Exception as e:
                    print(f" Database file issue: {db_file.name} - {e}", flush=True)
                    locked_files.append(str(db_file))
        
        if locked_files:
            print(f"Warning: Some database files may be locked: {locked_files}", flush=True)
            print("Safety copies created - will restore if needed after update", flush=True)
        
        # Check for problematic file locks that might prevent update
        print("Comprehensive file lock detection for app directory...", flush=True)
        app_directory = repo_root / 'app'
        locked_files_found = []
        
        if app_directory.exists():
            # Scan the app directory for locked files
            locked_files_found = find_locked_files_in_directory(app_directory, max_check=9900)
        
        # Also check specific problematic files
        additional_files_to_check = [
            repo_root / 'app' / 'instance' / 'update_log.txt',
            repo_root / 'instance' / 'update_log.txt',
            repo_root / 'run.py',
        ]
        
        for check_file in additional_files_to_check:
            if check_file.exists() and not wait_for_file_unlock(check_file, max_attempts=1, wait_seconds=2):
                if check_file not in locked_files_found:
                    locked_files_found.append(check_file)
        
        # If we found locked files, try to unlock them
        if locked_files_found:
            print(f"Found {len(locked_files_found)} locked files that may prevent update", flush=True)
            print("Attempting to unlock files with extended wait times...", flush=True)
            
            successfully_unlocked = []
            still_locked = []
            
            for locked_file in locked_files_found:
                print(f"Unlocking: {locked_file.relative_to(repo_root)}", flush=True)
                if wait_for_file_unlock(locked_file, max_attempts=3, wait_seconds=10):
                    successfully_unlocked.append(locked_file)
                else:
                    still_locked.append(locked_file)
            
            print(f"Lock resolution: {len(successfully_unlocked)} unlocked, {len(still_locked)} still locked", flush=True)
            
            # If still locked files, try killing processes
            if still_locked:
                print(f"Attempting to kill processes locking {len(still_locked)} files...", flush=True)
                killed_processes = force_kill_file_locks([str(f) for f in still_locked])
                if killed_processes:
                    print(f" Killed {killed_processes} processes", flush=True)
                    time.sleep(5)  # Wait after killing processes
                    
                    # Try unlocking again after killing processes
                    final_unlock_attempt = []
                    for locked_file in still_locked:
                        if wait_for_file_unlock(locked_file, max_attempts=2, wait_seconds=3):
                            final_unlock_attempt.append(locked_file)
                    
                    if final_unlock_attempt:
                        print(f" Successfully unlocked {len(final_unlock_attempt)} files after killing processes", flush=True)
                        # Remove from still_locked list
                        still_locked = [f for f in still_locked if f not in final_unlock_attempt]
            
            if still_locked:
                print("Files that remain locked:", flush=True)
                for locked_file in still_locked:
                    print(f"   {locked_file.relative_to(repo_root)}", flush=True)
                print("Update may fail for these files - will attempt recovery", flush=True)
            else:
                print(" All file locks successfully resolved", flush=True)
        else:
            print(" No locked files detected in app directory", flush=True)
        
        try:
            # Add specific database files to preservation - these might be in root directory
            db_preserve_files = ['scouting.db', 'scouting.db-wal', 'scouting.db-shm', 'users.db', 'users.db-wal', 'users.db-shm', 'app.db', 'app.db-wal', 'app.db-shm', 'database.db', 'database.db-wal', 'database.db-shm']
            preserve_arg = ','.join(['instance', 'uploads', 'config', 'migrations', 'translations', 'ssl', '.env', 'app_config.json', '.venv', 'venv', 'env'] + db_preserve_files)
            
            update_result = subprocess.run([
                sys.executable, 'update_from_github_file.py', str(zip_path), '--zip', '--force', '--preserve', preserve_arg
            ], capture_output=True, text=True, cwd=repo_root)
            
            print(f"Update output: {update_result.stdout}", flush=True)
            if update_result.stderr:
                print(f"Update errors: {update_result.stderr}", flush=True)
                
            rc = update_result.returncode
            print(f"Update process returned {rc}", flush=True)
            
            # Log what files exist after update
            print("=== POST-UPDATE FILE CHECK ===", flush=True)
            post_update_assistant_files = []
            if (repo_root / 'app' / 'assistant').exists():
                post_update_assistant_files = list((repo_root / 'app' / 'assistant').glob('*.py'))
            print(f"Assistant Python files after update: {[f.name for f in post_update_assistant_files]}", flush=True)
            
            post_update_db_files = list(repo_root.glob('*.db*')) + list((repo_root / 'instance').glob('*.db*'))
            print(f"Database files after update: {[str(f.relative_to(repo_root)) for f in post_update_db_files if f.exists()]}", flush=True)
            
            # CRITICAL: Verify database files were not corrupted or replaced
            print("=== DATABASE CORRUPTION VERIFICATION ===", flush=True)
            corrupted_or_missing_dbs = []
            
            for original_db, safety_copy in safety_copies:
                if not original_db.exists():
                    print(f" CRITICAL: Database file missing after update: {original_db.relative_to(repo_root)}", flush=True)
                    corrupted_or_missing_dbs.append(original_db)
                else:
                    # Check if file size changed dramatically (might indicate corruption/replacement)
                    try:
                        original_size = original_db.stat().st_size
                        safety_size = safety_copy.stat().st_size
                        
                        if original_size == 0 and safety_size > 0:
                            print(f" CRITICAL: Database file appears corrupted (zero size): {original_db.relative_to(repo_root)}", flush=True)
                            corrupted_or_missing_dbs.append(original_db)
                        elif original_size < safety_size * 0.5:  # 50% size reduction might indicate corruption
                            print(f" WARNING: Database file significantly smaller after update: {original_db.relative_to(repo_root)}", flush=True)
                            print(f"   Original: {original_size} bytes, Current: {safety_size} bytes", flush=True)
                        else:
                            print(f" Database file intact: {original_db.relative_to(repo_root)} ({original_size} bytes)", flush=True)
                    except Exception as e:
                        print(f" Could not verify database integrity: {original_db.relative_to(repo_root)} - {e}", flush=True)
            
            # Restore corrupted database files
            if corrupted_or_missing_dbs:
                print(f" RESTORING {len(corrupted_or_missing_dbs)} corrupted/missing database files...", flush=True)
                for corrupted_db in corrupted_or_missing_dbs:
                    for original_db, safety_copy in safety_copies:
                        if original_db == corrupted_db and safety_copy.exists():
                            try:
                                corrupted_db.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(safety_copy, corrupted_db)
                                print(f" Restored database: {corrupted_db.relative_to(repo_root)}", flush=True)
                            except Exception as e:
                                print(f" Failed to restore database {corrupted_db.relative_to(repo_root)}: {e}", flush=True)
            else:
                print(" All database files verified intact - no corruption detected", flush=True)
                
            print("=== END DATABASE VERIFICATION ===", flush=True)
            print("=== END POST-UPDATE CHECK ===", flush=True)
            
            # Check for specific update failure patterns in the output
            if "ERROR copying" in update_result.stdout and "app" in update_result.stdout:
                print("DETECTED: App directory replacement failed due to file locks", flush=True)
                print("Attempting manual app directory recovery...", flush=True)
                
                # Try to manually copy critical app files from the ZIP
                try:
                    import zipfile
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        zip_files = zf.namelist()
                        
                        # Find the app directory in the ZIP
                        app_files = [f for f in zip_files if '/app/' in f or '\\app\\' in f]
                        print(f"Found {len(app_files)} app files in ZIP", flush=True)
                        
                        # Extract critical app files manually
                        critical_app_patterns = [
                            'assistant/core.py',
                            'assistant/visualizer.py', 
                            'assistant/__init__.py',
                            'routes/sync.py',
                            'routes/__init__.py',
                            'utils/sync_utils.py',
                            'utils/__init__.py',
                            'models.py',
                            '__init__.py'
                        ]
                        
                        extracted_count = 0
                        for pattern in critical_app_patterns:
                            matching_files = [f for f in app_files if f.endswith(pattern)]
                        for zip_file in matching_files:
                            try:
                                # CRITICAL: Skip database files to prevent corruption
                                file_name = zip_file.split('/')[-1] if '/' in zip_file else zip_file.split('\\')[-1] if '\\' in zip_file else zip_file
                                if (file_name.endswith('.db') or file_name.endswith('.db-wal') or 
                                    file_name.endswith('.db-shm') or file_name.endswith('.sqlite') or 
                                    file_name.endswith('.sqlite3')):
                                    print(f" Database protection: Skipping {file_name} extraction to prevent corruption", flush=True)
                                    continue
                                    
                                # Determine target path - handle different ZIP structures
                                target_path = None
                                
                                # Try different path extraction methods
                                if 'Obsidianscout-main/' in zip_file:
                                    relative_path = zip_file.split('Obsidianscout-main/')[-1]
                                    target_path = repo_root / relative_path
                                elif 'Obsidianscout-main\\' in zip_file:
                                    relative_path = zip_file.split('Obsidianscout-main\\')[-1]
                                    target_path = repo_root / relative_path
                                elif zip_file.startswith('app/') or zip_file.startswith('app\\'):
                                    target_path = repo_root / zip_file
                                else:
                                    # Last resort - try to extract to correct location based on pattern
                                    if pattern in zip_file:
                                        # Create the correct path based on pattern
                                        if 'assistant/' in pattern:
                                            target_path = repo_root / 'app' / 'assistant' / pattern.split('/')[-1]
                                        elif 'routes/' in pattern:
                                            target_path = repo_root / 'app' / 'routes' / pattern.split('/')[-1]
                                        elif 'utils/' in pattern:
                                            target_path = repo_root / 'app' / 'utils' / pattern.split('/')[-1]
                                        else:
                                            target_path = repo_root / 'app' / pattern
                                
                                if target_path:
                                    # Create target directory
                                    target_path.parent.mkdir(parents=True, exist_ok=True)
                                    
                                    # Extract file
                                    with zf.open(zip_file) as src:
                                        target_path.write_bytes(src.read())
                                    
                                    print(f" Manually extracted: {target_path.relative_to(repo_root)}", flush=True)
                                    extracted_count += 1
                                else:
                                    print(f" Could not determine target path for: {zip_file}", flush=True)
                                    
                            except Exception as e:
                                print(f" Failed to extract {zip_file}: {e}", flush=True)
                        
                        print(f"Manual extraction complete: {extracted_count} files extracted", flush=True)
                        
                except Exception as e:
                    print(f"Manual app directory recovery failed: {e}", flush=True)
            
            # Verify critical files exist after update - comprehensive list
            print("Verifying critical files after update...", flush=True)
            critical_files = [
                repo_root / 'app' / '__init__.py',
                repo_root / 'app' / 'models.py',
                repo_root / 'app' / 'assistant' / '__init__.py',
                repo_root / 'app' / 'assistant' / 'core.py',
                repo_root / 'app' / 'assistant' / 'visualizer.py',
                repo_root / 'app' / 'routes' / '__init__.py',
                repo_root / 'app' / 'routes' / 'assistant.py',
                repo_root / 'app' / 'routes' / 'main.py',
                repo_root / 'app' / 'routes' / 'sync.py',
                repo_root / 'app' / 'utils' / '__init__.py',
                repo_root / 'app' / 'utils' / 'sync_utils.py',
                repo_root / 'run.py',
                repo_root / 'requirements.txt'
            ]
            
            missing_files = [str(f.relative_to(repo_root)) for f in critical_files if not f.exists()]
            if missing_files:
                print(f"ERROR: Critical files missing after update: {missing_files}", flush=True)
                print("Attempting comprehensive recovery from backup...", flush=True)
                
                # Find the most recent backup directory
                backup_dirs = list(repo_root.glob('backups/update_backup_*'))
                if backup_dirs:
                    latest_backup = max(backup_dirs, key=lambda p: p.stat().st_mtime)
                    print(f"Found backup directory: {latest_backup}", flush=True)
                    
                    recovery_success = []
                    recovery_failed = []
                    
                    # Try to restore missing files from backup
                    for missing in missing_files:
                        missing_path = Path(missing)
                        backup_file = latest_backup / missing_path.name  # Try direct file name first
                        target_file = repo_root / missing
                        
                        # If direct file name not found, try full path restoration
                        if not backup_file.exists():
                            # Look for the file in subdirectories of backup
                            possible_backups = list(latest_backup.rglob(missing_path.name))
                            if possible_backups:
                                backup_file = possible_backups[0]  # Use first match
                        
                        if backup_file.exists():
                            try:
                                target_file.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(backup_file, target_file)
                                print(f" Restored {missing} from backup", flush=True)
                                recovery_success.append(missing)
                            except Exception as e:
                                print(f" Failed to restore {missing}: {e}", flush=True)
                                recovery_failed.append(missing)
                        else:
                            print(f" Backup not found for {missing}", flush=True)
                            recovery_failed.append(missing)
                    
                    print(f"Recovery summary: {len(recovery_success)} restored, {len(recovery_failed)} failed", flush=True)
                else:
                    print("No backup directory found for recovery", flush=True)
                
                # Re-verify after recovery attempt
                still_missing = [str(f.relative_to(repo_root)) for f in critical_files if not f.exists()]
                if still_missing:
                    print(f"CRITICAL: Still missing after recovery: {still_missing}", flush=True)
                    print("Server startup will likely fail. Manual intervention may be required.", flush=True)
                    
                    # Try one more recovery approach - look for these files in the ZIP directly
                    print("Attempting emergency recovery from original ZIP...", flush=True)
                    try:
                        import zipfile
                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            zip_files = zf.namelist()
                            
                            for missing in still_missing:
                                # Look for the file in the ZIP
                                matching_files = [f for f in zip_files if f.endswith(missing) or missing in f]
                                if matching_files:
                                    zip_file = matching_files[0]
                                    target_file = repo_root / missing
                                    try:
                                        target_file.parent.mkdir(parents=True, exist_ok=True)
                                        with zf.open(zip_file) as src:
                                            target_file.write_bytes(src.read())
                                        print(f" Emergency restored {missing} from ZIP", flush=True)
                                    except Exception as e:
                                        print(f" Emergency recovery failed for {missing}: {e}", flush=True)
                    except Exception as e:
                        print(f"Emergency recovery from ZIP failed: {e}", flush=True)
                    
                    # Final verification
                    final_missing = [str(f.relative_to(repo_root)) for f in critical_files if not f.exists()]
                    if not final_missing:
                        print("SUCCESS: Emergency recovery completed, all critical files restored", flush=True)
                    else:
                        print(f"FINAL CRITICAL ERROR: Unable to restore: {final_missing}", flush=True)
                else:
                    print("SUCCESS: All critical files restored from backup", flush=True)
            else:
                print("SUCCESS: All critical files verified after update", flush=True)
            
            # Check and restore database files if they were deleted
            print("=== DATABASE FILE RESTORATION CHECK ===", flush=True)
            for original_file, safety_copy in safety_copies:
                if not original_file.exists() and safety_copy.exists():
                    try:
                        original_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(safety_copy, original_file)
                        print(f" Restored missing database file: {original_file.name}", flush=True)
                    except Exception as e:
                        print(f" Failed to restore database file {original_file.name}: {e}", flush=True)
                elif original_file.exists():
                    print(f" Database file preserved: {original_file.name}", flush=True)
            
            # Clean up safety copies
            try:
                shutil.rmtree(safety_backup_dir)
                print(" Cleaned up safety backup directory", flush=True)
            except Exception:
                pass
            print("=== END DATABASE RESTORATION CHECK ===", flush=True)
            
            if rc != 0:
                print(f"WARNING: Update returned non-zero exit code {rc}", flush=True)
                # Even if update had issues, we might be able to proceed
                print("Attempting to continue with server restart...", flush=True)
        except Exception as e:
            print(f"ERROR: Failed to run update: {e}", flush=True)
            rc = 1

        # Verify sync server configuration is preserved
        print("Verifying sync server configuration...", flush=True)
        try:
            verify_result = subprocess.run([
                sys.executable, 'sync_config_manager.py', '--verify'
            ], capture_output=True, text=True, cwd=repo_root)
            if verify_result.returncode == 0:
                print("SUCCESS: Sync server configuration verified", flush=True)
                print(verify_result.stdout, flush=True)
            else:
                print(f"Warning: Sync config verification issue: {verify_result.stderr}", flush=True)
        except Exception as e:
            print(f"Warning: Could not verify sync config: {e}", flush=True)

        # Edit run.py to set USE_WAITRESS and update PORT default
        print(f"Setting USE_WAITRESS={args.use_waitress} and PORT default={final_port} in run.py", flush=True)
        set_use_waitress_and_port_in_run(run_py, args.use_waitress, final_port)

        # Verify critical files exist before starting server
        print("Verifying critical files exist...", flush=True)
        critical_files = [
            repo_root / 'app' / '__init__.py',
            repo_root / 'app' / 'assistant' / '__init__.py',
            repo_root / 'app' / 'assistant' / 'core.py',
            repo_root / 'app' / 'routes' / '__init__.py'
        ]
        
        missing_files = [f for f in critical_files if not f.exists()]
        if missing_files:
            print(f"ERROR: Critical files missing after update: {[str(f) for f in missing_files]}", flush=True)
            print("Update may have failed - attempting to restore from backup...", flush=True)
            # Could add backup restore logic here if needed
        else:
            print("All critical files verified", flush=True)

        # Start server
        print(f"Starting server on port {final_port}...", flush=True)
        child_pid = start_server(run_py, final_port)
        print(f"Started server pid={child_pid}", flush=True)

        # Give server time to start
        time.sleep(5)
        
        # Execute batch files after update
        print("Looking for batch files to execute after update...", flush=True)
        try:
            bat_files = list(repo_root.glob('*.bat'))
            if bat_files:
                print(f"Found batch files: {[f.name for f in bat_files]}", flush=True)
                
                # Look for specific batch files in priority order
                priority_bats = ['run_production.bat', 'start_server.bat', 'run.bat']
                selected_bat = None
                
                for priority_bat in priority_bats:
                    for bat_file in bat_files:
                        if bat_file.name.lower() == priority_bat.lower():
                            selected_bat = bat_file
                            break
                    if selected_bat:
                        break
                
                # If no priority bat found, use the first available
                if not selected_bat and bat_files:
                    selected_bat = bat_files[0]
                
                if selected_bat:
                    print(f"Auto-running batch file after update: {selected_bat.name}", flush=True)
                    try:
                        # Run the batch file in detached mode so updater can exit
                        if sys.platform == 'win32':
                            # Use CREATE_NEW_PROCESS_GROUP and CREATE_BREAKAWAY_FROM_JOB on Windows
                            subprocess.Popen([str(selected_bat)], 
                                           cwd=str(repo_root),
                                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 
                                                        getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0),
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL,
                                           stdin=subprocess.DEVNULL)
                        else:
                            # Use shell=True and nohup-equivalent on Unix-like systems
                            subprocess.Popen([str(selected_bat)], 
                                           cwd=str(repo_root),
                                           start_new_session=True,
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL,
                                           stdin=subprocess.DEVNULL)
                        
                        print(f" Successfully launched {selected_bat.name} in background", flush=True)
                        # Give the batch file a moment to start
                        time.sleep(2)
                        
                    except Exception as e:
                        print(f" Failed to run batch file {selected_bat.name}: {e}", flush=True)
                else:
                    print("No suitable batch file found to execute", flush=True)
            else:
                print("No batch files found in repository root", flush=True)
                
        except Exception as e:
            print(f"Warning: Error while looking for batch files: {e}", flush=True)

        # Kill other python processes
        print("Killing other python processes (best-effort)...", flush=True)
        killed = kill_server_processes([child_pid, os.getpid()])
        print(f"Killed PIDs: {killed}", flush=True)

        print("Updater finished; exiting.", flush=True)

    except Exception as e:
        print(f"Updater error: {e}", flush=True)
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass


if __name__ == '__main__':
    main()
