# Import all models from the main models.py file
import sys
import os

# Add the parent directory to the path to import from models.py
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Import everything from models.py
from app.models import *# Import all models for easy access
from app.models.api_models import *