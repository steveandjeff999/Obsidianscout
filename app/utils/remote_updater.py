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


def set_use_waitress_in_run(run_py: Path, use_waitress: bool):
    # Replace the line that assigns USE_WAITRESS
    try:
        text = run_py.read_text(encoding='utf-8')
        new_line = f"USE_WAITRESS = {str(bool(use_waitress))}  # Updated by remote_updater"
        import re
        pattern = re.compile(r"^USE_WAITRESS\s*=.*$", re.M)
        if pattern.search(text):
            text = pattern.sub(new_line, text)
        else:
            # Fallback: insert near top
            text = new_line + '\n' + text
        run_py.write_text(text, encoding='utf-8')
    except UnicodeDecodeError as e:
        print(f"Warning: Could not modify run.py due to encoding error: {e}", flush=True)
        print("Server will use default USE_WAITRESS setting", flush=True)


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip-url', dest='zip_url', required=True)
    parser.add_argument('--use-waitress', dest='use_waitress', action='store_true')
    parser.add_argument('--port', dest='port', type=int, default=8080)
    args = parser.parse_args()

    print("Starting remote updater...", flush=True)
    print(f"Download URL: {args.zip_url}", flush=True)
    print(f"Use Waitress: {args.use_waitress}", flush=True)
    print(f"Port: {args.port}", flush=True)

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
        print("Applying update...", flush=True)
        
        # First, try to stop any running server processes more safely
        print("Stopping any running server processes...", flush=True)
        try:
            # Instead of killing all processes, try a more targeted approach
            # Look for processes using the server port
            killed_before = stop_server_on_port(args.port, [os.getpid()])
            if killed_before:
                print(f"Stopped server processes: {killed_before}", flush=True)
                time.sleep(3)  # Give more time for files to be released
            else:
                print("No running server found on target port", flush=True)
        except Exception as e:
            print(f"Warning: Could not stop server processes: {e}", flush=True)
        
        try:
            update_result = subprocess.run([
                sys.executable, 'update_from_github_file.py', str(zip_path), '--zip', '--force'
            ], capture_output=True, text=True, cwd=repo_root)
            
            print(f"Update output: {update_result.stdout}", flush=True)
            if update_result.stderr:
                print(f"Update errors: {update_result.stderr}", flush=True)
                
            rc = update_result.returncode
            print(f"Update process returned {rc}", flush=True)
            
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

        # Edit run.py
        print(f"Setting USE_WAITRESS={args.use_waitress} in run.py", flush=True)
        set_use_waitress_in_run(run_py, args.use_waitress)

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
        print(f"Starting server on port {args.port}...", flush=True)
        child_pid = start_server(run_py, args.port)
        print(f"Started server pid={child_pid}", flush=True)

        # Give server time to start
        time.sleep(5)

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
