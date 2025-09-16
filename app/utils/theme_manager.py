import json
import os
from flask import current_app, request, session
from flask_login import current_user
from typing import Dict, Any, Optional

class ThemeManager:
    """Manages application themes and customizations"""
    
    def __init__(self, team_number=None):
        self.config_path = os.path.join(os.getcwd(), 'config', 'theme_config.json')
        self.themes = {}
        self.current_theme = 'default'
        self.custom_themes = {}
        self.team_number = team_number
        self.load_themes()
    
    def load_themes(self):
        """Load themes from configuration file"""
        try:
            # Always create/update to simplified light/dark config
            self.create_default_config()
        except Exception as e:
            current_app.logger.error(f"Error loading theme configuration: {e}")
            self.create_default_config()
    
    def get_current_theme_from_preference(self):
        """Get current theme from cookie preference, fallback to team default, then global default"""
        try:
            # Get team number from current user or passed parameter
            team_number = self.team_number
            if not team_number and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                team_number = getattr(current_user, 'scouting_team_number', None)
            
            # Check for cookie preference for this team
            if team_number and request and hasattr(request, 'cookies'):
                cookie_name = f"theme_team_{team_number}"
                cookie_theme = request.cookies.get(cookie_name)
                if cookie_theme and cookie_theme in ['light', 'dark']:
                    return cookie_theme
            
            # Fallback to team-specific config file
            if team_number:
                team_config_path = os.path.join(os.getcwd(), 'instance', 'configs', str(team_number), 'theme_config.json')
                if os.path.exists(team_config_path):
                    with open(team_config_path, 'r', encoding='utf-8') as f:
                        team_config = json.load(f)
                        team_theme = team_config.get('current_theme', 'light')
                        if team_theme in ['light', 'dark']:
                            return team_theme
            
            # Fallback to global default
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    global_theme = config.get('current_theme', 'light')
                    if global_theme in ['light', 'dark']:
                        return global_theme
                    
        except Exception as e:
            if current_app:
                current_app.logger.error(f"Error getting theme preference: {e}")
        
        # Always fallback to light theme
        return 'light'
    
    def create_default_config(self):
        """Create default theme configuration with only light and dark themes"""
        default_config = {
            "current_theme": "light",
            "themes": {
                "light": {
                    "name": "Light Mode",
                    "description": "Light theme with bright background",
                    "colors": {
                        "primary": "#0d6efd",
                        "primary-light": "#cfe2ff",
                        "primary-dark": "#0a58ca",
                        "secondary": "#6c757d",
                        "success": "#198754",
                        "danger": "#dc3545",
                        "warning": "#ffc107",
                        "info": "#0dcaf0",
                        "light": "#f8f9fa",
                        "dark": "#212529",
                        "red-alliance": "#dc3545",
                        "red-alliance-bg": "#f8d7da",
                        "blue-alliance": "#0d6efd",
                        "blue-alliance-bg": "#cfe2ff",
                        "auto-color": "#fd7e14",
                        "teleop-color": "#0d6efd",
                        "endgame-color": "#198754",
                        "navbar-bg": "#ffffff",
                        "card-bg": "#ffffff",
                        "card-border": "#dee2e6",
                        "card-header": "#f8f9fa",
                        "text-main": "#212529",
                        "text-muted": "#6c757d",
                        "background": "#ffffff"
                    },
                    "typography": {
                        "font-family-base": "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif",
                        "font-family-headings": "'Montserrat', 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif"
                    },
                    "ui": {
                        "border-radius": "0.5rem",
                        "transition-speed": "0.2s",
                        "card-shadow": "0 .125rem .25rem rgba(0, 0, 0, .075)",
                        "card-shadow-hover": "0 .5rem 1rem rgba(0, 0, 0, .15)"
                    }
                },
                "dark": {
                    "name": "Dark Mode",
                    "description": "Dark theme with dark background",
                    "colors": {
                        "primary": "#6ea8fe",
                        "primary-light": "#263653",
                        "primary-dark": "#9ec5fe",
                        "secondary": "#adb5bd",
                        "success": "#75b798",
                        "danger": "#ea868f",
                        "warning": "#ffda6a",
                        "info": "#6edff6",
                        "light": "#343a40",
                        "dark": "#e6eef8",
                        "red-alliance": "#ea868f",
                        "red-alliance-bg": "#2c0b0e",
                        "blue-alliance": "#6ea8fe",
                        "blue-alliance-bg": "#0c2461",
                        "auto-color": "#fd7e14",
                        "teleop-color": "#6ea8fe",
                        "endgame-color": "#75b798",
                        "navbar-bg": "#0f1720",
                        "card-bg": "#0f1720",
                        "card-border": "rgba(255,255,255,0.06)",
                        "card-header": "#0f1720",
                        "text-main": "#e6eef8",
                        "text-muted": "rgba(255,255,255,0.6)",
                        "background": "#0b0f12"
                    },
                    "typography": {
                        "font-family-base": "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif",
                        "font-family-headings": "'Montserrat', 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif"
                    },
                    "ui": {
                        "border-radius": "0.5rem",
                        "transition-speed": "0.2s",
                        "card-shadow": "0 .125rem .25rem rgba(0, 0, 0, .3)",
                        "card-shadow-hover": "0 .5rem 1rem rgba(0, 0, 0, .4)"
                    }
                }
            }
        }
        
        self.themes = default_config['themes']
        self.current_theme = self.get_current_theme_from_preference()
        self.save_themes()
    
    def save_themes(self):
        """Save themes to configuration file"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            config = {
                'current_theme': self.current_theme,
                'themes': self.themes
            }
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            if current_app:
                current_app.logger.error(f"Error saving theme configuration: {e}")
    
    def get_current_theme(self) -> Dict[str, Any]:
        """Get the current theme configuration"""
        theme_id = self.current_theme
        if theme_id in self.themes:
            return self.themes[theme_id]
        else:
            return self.themes['light']
    
    def set_current_theme(self, theme_id: str) -> bool:
        """Set the current theme for the current team via cookie"""
        if theme_id in self.themes:
            self.current_theme = theme_id
            # Don't save to global config, just update instance
            return True
        return False
    
    def save_team_theme_preference(self, theme_id: str, team_number: int) -> bool:
        """Save theme preference for a specific team (as fallback when no cookie)"""
        try:
            if theme_id not in self.themes:
                return False
                
            team_config_dir = os.path.join(os.getcwd(), 'instance', 'configs', str(team_number))
            os.makedirs(team_config_dir, exist_ok=True)
            
            team_config_path = os.path.join(team_config_dir, 'theme_config.json')
            
            team_config = {}
            if os.path.exists(team_config_path):
                with open(team_config_path, 'r', encoding='utf-8') as f:
                    team_config = json.load(f)
            
            team_config['current_theme'] = theme_id
            
            with open(team_config_path, 'w', encoding='utf-8') as f:
                json.dump(team_config, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            if current_app:
                current_app.logger.error(f"Error saving team theme preference: {e}")
            return False
    
    def get_available_themes(self) -> Dict[str, Dict[str, Any]]:
        """Get all available themes (only light and dark)"""
        return self.themes
    
    def get_theme_css_variables(self) -> str:
        """Generate CSS variables for the current theme"""
        theme = self.get_current_theme()
        css_vars = []
        
        # Add color variables
        for key, value in theme['colors'].items():
            css_vars.append(f"    --{key}: {value};")
        
        # Add typography variables
        for key, value in theme['typography'].items():
            css_vars.append(f"    --{key}: {value};")
        
        # Add UI variables
        for key, value in theme['ui'].items():
            css_vars.append(f"    --{key}: {value};")
        
        return '\n'.join(css_vars)

    def get_theme_preview_data(self) -> Dict[str, Any]:
        """Get theme data for preview purposes"""
        theme = self.get_current_theme()
        return {
            'id': self.current_theme,
            'name': theme.get('name', 'Unknown Theme'),
            'description': theme.get('description', ''),
            'colors': theme.get('colors', {}),
            'typography': theme.get('typography', {}),
            'ui': theme.get('ui', {})
        } 