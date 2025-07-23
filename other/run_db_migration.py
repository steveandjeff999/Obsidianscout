import os
import sys
import subprocess

# Set the base directory to the project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    print("Running database migrations with Flask-Migrate (flask db upgrade)...")
    result = subprocess.run([
        sys.executable, '-m', 'flask', 'db', 'upgrade'
    ], cwd=BASE_DIR, check=True)
    print("Database migration completed successfully.")
except subprocess.CalledProcessError as e:
    print(f"Error running Flask-Migrate migration: {e}")
    sys.exit(1) 