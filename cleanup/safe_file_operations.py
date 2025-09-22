
def safe_file_delete(file_path):
    """Safely delete a file with proper error handling"""
    import os
    import stat
    import time
    
    if not os.path.exists(file_path):
        return False, "File does not exist"
    
    # Try multiple deletion strategies
    strategies = [
        # Strategy 1: Simple deletion
        lambda: os.remove(file_path),
        
        # Strategy 2: Change permissions then delete
        lambda: (os.chmod(file_path, stat.S_IWRITE), os.remove(file_path))[1],
        
        # Strategy 3: Wait a bit and try again (in case file is locked)
        lambda: (time.sleep(0.5), os.remove(file_path))[1]
    ]
    
    for i, strategy in enumerate(strategies, 1):
        try:
            strategy()
            return True, f"Deleted using strategy {i}"
        except PermissionError as e:
            if i == len(strategies):
                return False, f"Permission denied: {e}"
            continue
        except Exception as e:
            if i == len(strategies):
                return False, f"Failed to delete: {e}"
            continue
    
    return False, "All deletion strategies failed"
