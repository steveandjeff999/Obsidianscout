from typing import Dict, Any


class ThemeManager:
    """Lightweight no-op ThemeManager maintained for compatibility.

    This class intentionally avoids file IO or server-side theme customization.
    It provides a minimal API so existing code that imports ThemeManager
    continues to function without requiring a themes endpoint.
    """

    def __init__(self, team_number=None):
        self.current_theme = 'light'
        self.themes = {
            'light': {'name': 'Light Mode'},
            'dark': {'name': 'Dark Mode'}
        }
        self.team_number = team_number
    
    def get_current_theme_from_preference(self):
        # No-op: always return the default theme (light) for compatibility.
        return 'light'
    
    def create_default_config(self):
        # No-op, as themes are not managed server-side in this simplified setup.
        pass
    
    def save_themes(self):
        # No-op: server-side theme state disabled.
        return True
    
    def get_current_theme(self):
        # Return a minimal theme object for templates
        return self.themes.get(self.current_theme, self.themes['light'])
    
    def set_current_theme(self, theme_id: str) -> bool:
        if theme_id in self.themes:
            self.current_theme = theme_id
            return True
        return False
    
    def save_team_theme_preference(self, theme_id: str, team_number: int) -> bool:
        # No-op in simplified theme manager
        return True
    
    def get_available_themes(self):
        return self.themes
    
    def get_theme_css_variables(self):
        # Minimal CSS variables for default theme
        return "--background: #ffffff; --text-main: #212529;"

    def get_theme_preview_data(self):
        theme = self.get_current_theme()
        return {
            'id': self.current_theme,
            'name': theme.get('name', 'Theme'),
            'description': ''
        }