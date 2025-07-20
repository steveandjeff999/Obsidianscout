import json
import os
from flask import current_app
from typing import Dict, Any, Optional

class ThemeManager:
    """Manages application themes and customizations"""
    
    def __init__(self):
        self.config_path = os.path.join(os.getcwd(), 'config', 'theme_config.json')
        self.themes = {}
        self.current_theme = 'default'
        self.custom_themes = {}
        self.load_themes()
    
    def load_themes(self):
        """Load themes from configuration file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.themes = config.get('themes', {})
                    self.current_theme = config.get('current_theme', 'default')
                    self.custom_themes = config.get('custom_themes', {})
            else:
                # Create default configuration if file doesn't exist
                self.create_default_config()
        except Exception as e:
            current_app.logger.error(f"Error loading theme configuration: {e}")
            self.create_default_config()
    
    def create_default_config(self):
        """Create default theme configuration"""
        default_config = {
            "current_theme": "default",
            "themes": {
                "default": {
                    "name": "Default Blue",
                    "description": "Standard blue theme with light background",
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
                }
            },
            "custom_themes": {}
        }
        
        self.themes = default_config['themes']
        self.current_theme = default_config['current_theme']
        self.custom_themes = default_config['custom_themes']
        self.save_themes()
    
    def save_themes(self):
        """Save themes to configuration file"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            config = {
                'current_theme': self.current_theme,
                'themes': self.themes,
                'custom_themes': self.custom_themes
            }
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            current_app.logger.error(f"Error saving theme configuration: {e}")
    
    def get_current_theme(self) -> Dict[str, Any]:
        """Get the current theme configuration"""
        theme_id = self.current_theme
        if theme_id in self.custom_themes:
            return self.custom_themes[theme_id]
        elif theme_id in self.themes:
            return self.themes[theme_id]
        else:
            return self.themes['default']
    
    def set_current_theme(self, theme_id: str) -> bool:
        """Set the current theme"""
        if theme_id in self.themes or theme_id in self.custom_themes:
            self.current_theme = theme_id
            self.save_themes()
            return True
        return False
    
    def get_available_themes(self) -> Dict[str, Dict[str, Any]]:
        """Get all available themes (built-in and custom)"""
        all_themes = {}
        all_themes.update(self.themes)
        all_themes.update(self.custom_themes)
        return all_themes
    
    def create_custom_theme(self, theme_id: str, theme_data: Dict[str, Any]) -> bool:
        """Create a new custom theme"""
        try:
            # Validate theme data structure
            required_sections = ['name', 'description', 'colors', 'typography', 'ui']
            for section in required_sections:
                if section not in theme_data:
                    return False
            
            self.custom_themes[theme_id] = theme_data
            self.save_themes()
            return True
        except Exception as e:
            current_app.logger.error(f"Error creating custom theme: {e}")
            return False
    
    def update_custom_theme(self, theme_id: str, theme_data: Dict[str, Any]) -> bool:
        """Update an existing custom theme"""
        if theme_id in self.custom_themes:
            return self.create_custom_theme(theme_id, theme_data)
        return False
    
    def delete_custom_theme(self, theme_id: str) -> bool:
        """Delete a custom theme"""
        if theme_id in self.custom_themes:
            del self.custom_themes[theme_id]
            # If the deleted theme was current, switch to default
            if self.current_theme == theme_id:
                self.current_theme = 'default'
            self.save_themes()
            return True
        return False
    
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
    
    def duplicate_theme(self, source_theme_id: str, new_theme_id: str, new_name: str, new_description: str = "") -> bool:
        """Duplicate an existing theme with a new ID"""
        source_theme = None
        if source_theme_id in self.themes:
            source_theme = self.themes[source_theme_id].copy()
        elif source_theme_id in self.custom_themes:
            source_theme = self.custom_themes[source_theme_id].copy()
        
        if source_theme:
            source_theme['name'] = new_name
            source_theme['description'] = new_description
            return self.create_custom_theme(new_theme_id, source_theme)
        
        return False 