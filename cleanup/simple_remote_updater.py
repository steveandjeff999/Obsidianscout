#!/usr/bin/env python3
"""
Simple remote updater for servers that don't have the full updater script
This can be manually copied to remote servers to enable remote updates
"""
import argparse
import os
import sys
import shutil
import tempfile
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests module not found. Install with: pip install requests")
    sys.exit(1)

def download_and_extract(zip_url, dest_dir):
    """Download and extract ZIP to destination directory"""
    print(f"Downloading {zip_url}...")
    
    # Download ZIP
    response = requests.get(zip_url, stream=True)
    response.raise_for_status()
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
        for chunk in response.iter_content(chunk_size=8192):
            tmp_file.write(chunk)
        zip_path = tmp_file.name
    
    try:
        # Extract ZIP
        print(f"Extracting to {dest_dir}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_file:
            zip_file.extractall(dest_dir)
        
        # Find the extracted folder (usually has a name like "Obsidianscout-main")
        extracted_items = list(Path(dest_dir).iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            return extracted_items[0]
        else:
            return Path(dest_dir)
    finally:
        os.unlink(zip_path)

def main():
    parser = argparse.ArgumentParser(description='Simple remote updater')
    parser.add_argument('--zip-url', required=True, help='URL of the ZIP file to download')
    parser.add_argument('--port', type=int, default=8080, help='Port to restart server on')
    parser.add_argument('--use-waitress', action='store_true', help='Use waitress server')
    
    args = parser.parse_args()
    
    # Get current directory (should be the repo root)
    repo_root = Path.cwd()
    
    print(f"Starting simple update process...")
    print(f"Repository root: {repo_root}")
    print(f"Download URL: {args.zip_url}")
    print(f"Target port: {args.port}")
    print(f"Use waitress: {args.use_waitress}")
    
    # Create temporary directory for download
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Download and extract
            extracted_dir = download_and_extract(args.zip_url, temp_dir)
            print(f"Extracted to: {extracted_dir}")
            
            # Update run.py USE_WAITRESS setting
            run_py = repo_root / 'run.py'
            if run_py.exists():
                content = run_py.read_text()
                import re
                pattern = re.compile(r'^USE_WAITRESS\s*=.*$', re.M)
                new_line = f"USE_WAITRESS = {args.use_waitress}  # Updated by simple_remote_updater"
                if pattern.search(content):
                    content = pattern.sub(new_line, content)
                    run_py.write_text(content)
                    print(f"Updated USE_WAITRESS setting in run.py")
            
            print(f" Simple update completed. Please manually copy updated files from:")
            print(f"   {extracted_dir}")
            print(f"   to")
            print(f"   {repo_root}")
            print(f"")
            print(f"️  This is a simplified updater. For full update functionality,")
            print(f"   copy the new app/utils/remote_updater.py file to enable")
            print(f"   automatic updates in the future.")
            
        except Exception as e:
            print(f" Update failed: {e}")
            return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
