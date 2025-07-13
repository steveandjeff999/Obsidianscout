"""
AI Helper utilities for Scout Assistant
Provides integration with browser-based AI services for enhanced question answering
"""

import json
import logging
import requests
import os
from typing import Dict, Any, Optional
from flask import current_app

logger = logging.getLogger(__name__)

# Default endpoint for a publicly available AI service
DEFAULT_AI_ENDPOINT = "https://api.browserai.co/v1/chat/completions"

def query_browser_ai(question: str, context: Dict[str, Any] = None) -> Optional[str]:
    """
    Send a query to a browser-based AI service
    
    Args:
        question: The question to send to the AI
        context: Optional context information to help the AI understand the question
        
    Returns:
        AI response string or None if there was an error
    """
    try:
        # Get API key from app config, with a default of None
        api_key = current_app.config.get('BROWSER_AI_API_KEY')
        endpoint = current_app.config.get('BROWSER_AI_ENDPOINT', DEFAULT_AI_ENDPOINT)
        
        # If we don't have an API key, use the local fallback
        if not api_key:
            return fallback_ai_response(question, context)
        
        # Prepare the query with context
        prompt = f"You are an assistant for an FRC Scouting App. "
        
        if context:
            prompt += f"Context: {json.dumps(context)}. "
            
        prompt += f"Please answer this question concisely: {question}"
        
        # Prepare the request
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "gpt-3.5-turbo",  # This is a common model name - adjust as needed
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 150,  # Limit response size
            "temperature": 0.7  # Balance between creative and focused
        }
        
        # Send the request
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=5  # 5 second timeout
        )
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and result['choices']:
                return result['choices'][0]['message']['content'].strip()
        
        # If we got here, something went wrong with the API
        logger.warning(f"AI API returned status {response.status_code}")
        return fallback_ai_response(question, context)
    
    except requests.RequestException as e:
        logger.error(f"Error calling AI API: {str(e)}")
        return fallback_ai_response(question, context)
    except Exception as e:
        logger.error(f"Unexpected error in AI query: {str(e)}")
        return None

def fallback_ai_response(question: str, context: Dict[str, Any] = None) -> str:
    """
    Generate a fallback response when the AI service is not available
    
    Args:
        question: The original question
        context: Any context information
        
    Returns:
        A fallback response string
    """
    # Check if the question contains certain keywords and provide relevant responses
    question_lower = question.lower()
    
    # FRC-related questions
    if any(term in question_lower for term in ['frc', 'first robotics', 'competition']):
        return "FRC (FIRST Robotics Competition) is a robotics competition for high school students. Teams build and program robots to compete in alliance formats against other teams."
    
    # Scouting-related questions
    if any(term in question_lower for term in ['scouting', 'scout', 'data collection']):
        return "Scouting in FRC involves collecting data on robot performance during matches to inform strategy and alliance selection. Our app helps teams efficiently collect, analyze, and visualize this data."
    
    # General robotics questions
    if any(term in question_lower for term in ['robot', 'autonomous', 'teleop']):
        return "FRC robots compete in matches with autonomous and teleoperated periods. The autonomous period is when robots operate independently using pre-programmed instructions, while teleop is when human drivers control the robots."
    
    # Default response for unknown questions
    return "I don't have enough information to answer that question. Try asking about specific teams, matches, or scouting data instead."

def get_config_file_path():
    """Get the path to the AI configuration file"""
    instance_path = current_app.instance_path
    config_file = os.path.join(instance_path, 'ai_config.json')
    return config_file

def load_ai_config_from_file():
    """Load AI configuration from file"""
    try:
        config_file = get_config_file_path()
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
                
                # Update app config with values from file
                if 'endpoint' in config:
                    current_app.config['BROWSER_AI_ENDPOINT'] = config['endpoint']
                if 'api_key' in config and config['api_key']:
                    current_app.config['BROWSER_AI_API_KEY'] = config['api_key']
                
                return True
    except Exception as e:
        logger.error(f"Error loading AI config from file: {str(e)}")
    return False

def get_ai_config() -> Dict[str, Any]:
    """
    Get the current AI configuration
    
    Returns:
        Dictionary with AI configuration settings
    """
    # Try to load config from file if not already loaded
    load_ai_config_from_file()
    
    return {
        "endpoint": current_app.config.get('BROWSER_AI_ENDPOINT', DEFAULT_AI_ENDPOINT),
        "api_key_configured": bool(current_app.config.get('BROWSER_AI_API_KEY')),
        "fallback_enabled": True,
        "max_tokens": 150
    }

def set_ai_config(config: Dict[str, Any]) -> bool:
    """
    Update the AI configuration in the app and save to file
    
    Args:
        config: Dictionary with new configuration values
        
    Returns:
        True if successful, False otherwise
    """
    try:
        updated_config = {}
        
        # Update in-memory config
        if 'endpoint' in config:
            current_app.config['BROWSER_AI_ENDPOINT'] = config['endpoint']
            updated_config['endpoint'] = config['endpoint']
        
        # Handle API key specially - preserve existing key if not provided
        if 'api_key' in config and config['api_key']:
            # New API key provided - update it
            current_app.config['BROWSER_AI_API_KEY'] = config['api_key']
            updated_config['api_key'] = config['api_key']
        elif 'api_key' in config and not config['api_key']:
            # Empty API key field - check if we should preserve existing key
            existing_key = current_app.config.get('BROWSER_AI_API_KEY')
            if existing_key:
                # Keep existing key in updated config
                updated_config['api_key'] = existing_key
        
        # Save to file
        config_file = get_config_file_path()
        
        # If file exists, read it first to preserve other settings
        existing_config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    existing_config = json.load(f)
            except:
                # If there's an error reading the file, we'll overwrite it
                pass
        
        # Update existing config with new values
        existing_config.update(updated_config)
        
        # Write back to file
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w') as f:
            json.dump(existing_config, f)
            
        return True
    except Exception as e:
        logger.error(f"Error updating AI config: {str(e)}")
        return False
