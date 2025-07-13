"""
Scout Assistant Module
Provides question answering and data visualization capabilities for the 5454 Scout App
"""

from app.assistant.core import Assistant
from app.assistant.visualizer import Visualizer

# Create a lazy-loaded instance
_assistant_instance = None
_visualizer_instance = None

def get_assistant():
    """Get or create the Assistant instance"""
    global _assistant_instance
    if _assistant_instance is None:
        _assistant_instance = Assistant()
    return _assistant_instance

def get_visualizer():
    """Get or create the Visualizer instance"""
    global _visualizer_instance
    if _visualizer_instance is None:
        _visualizer_instance = Visualizer()
    return _visualizer_instance

# For backward compatibility
assistant = get_assistant()
visualizer = get_visualizer()