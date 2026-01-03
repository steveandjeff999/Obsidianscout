import json
import os
from typing import Dict, Any, Optional


def _hex_to_rgb(hex_color: str) -> Optional[str]:
    """Convert a hex color like #aabbcc or #abc to 'r,g,b' string."""
    if not hex_color or not isinstance(hex_color, str):
        return None
    v = hex_color.lstrip('#')
    if len(v) == 3:
        v = ''.join([c*2 for c in v])
    if len(v) != 6:
        return None
    try:
        r = int(v[0:2], 16)
        g = int(v[2:4], 16)
        b = int(v[4:6], 16)
        return f"{r},{g},{b}"
    except Exception:
        return None


class ThemeManager:
    """Theme manager that reads `config/theme_config.json` and produces CSS variables.

    If the config file is missing or malformed, this falls back to reasonable defaults
    so templates and client scripts still receive consistent variables.
    """

    CONFIG_PATH = os.path.join('config', 'theme_config.json')

    def __init__(self, team_number: int = None):
        self.team_number = team_number
        self._config = self._load_config()
        self.current_theme = self._config.get('current_theme', 'light')
        self.themes = self._config.get('themes', {}) or {}

    def _load_config(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.CONFIG_PATH):
                with open(self.CONFIG_PATH, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
        except Exception:
            pass
        # Fallback minimal config
        return {
            'current_theme': 'light',
            'themes': {
                'light': {'name': 'Light Mode', 'colors': {'primary': '#0d6efd', 'background': '#ffffff', 'text-main': '#212529', 'card-bg': '#ffffff'}},
                'dark': {'name': 'Dark Mode', 'colors': {'primary': '#6ea8fe', 'background': '#0b0f12', 'text-main': '#e6eef8', 'card-bg': '#0f1720'}}
            }
        }

    def get_current_theme_from_preference(self) -> str:
        # Prefer current_theme from config; otherwise default to 'light'
        return self._config.get('current_theme', 'light')

    def create_default_config(self):
        # Intentionally not implemented for now
        return False

    def save_themes(self):
        # Not implemented: server-side theme editing disabled
        return False

    def get_current_theme(self) -> Dict[str, Any]:
        return self.themes.get(self.current_theme, self.themes.get('light', {}))

    def set_current_theme(self, theme_id: str) -> bool:
        if theme_id in self.themes:
            self.current_theme = theme_id
            return True
        return False

    def save_team_theme_preference(self, theme_id: str, team_number: int) -> bool:
        # No-op: per-team preferences are implemented client-side in localStorage
        return True

    def get_available_themes(self) -> Dict[str, Dict[str, Any]]:
        return self.themes

    def get_theme_css_variables(self) -> str:
        """Return a CSS variable string like `--bs-primary: #0d6efd; --bs-body-color: #111;`"""
        theme = self.get_current_theme()
        colors = (theme.get('colors') or {})
        parts = []

        # Standard variables used across templates
        mapping = {
            'primary': '--bs-primary',
            'primary-light': '--bs-primary-light',
            'primary-dark': '--bs-primary-dark',
            'secondary': '--bs-secondary',
            'success': '--bs-success',
            'danger': '--bs-danger',
            'warning': '--bs-warning',
            'info': '--bs-info',
            'light': '--bs-light',
            'dark': '--bs-dark',
            'text-main': '--bs-body-color',
            'text-muted': '--bs-secondary',
            'background': '--background',
            'card-bg': '--card-bg',
            'card-border': '--bs-border-color',
            'navbar-bg': '--navbar-bg',
            'accent': '--accent',
            'accent-contrast': '--accent-contrast',
            'nav-accent': '--nav-accent',
            'nav-accent-2': '--nav-accent-2',
            'nav-accent-contrast': '--nav-accent-contrast'
        }

        for key, varname in mapping.items():
            value = colors.get(key)
            if value:
                parts.append(f"{varname}: {value};")

        # RGB helper vars for effects and shadows
        primary_rgb = _hex_to_rgb(colors.get('primary', ''))
        if primary_rgb:
            parts.append(f"--bs-primary-rgb: {primary_rgb};")
        accent_rgb = _hex_to_rgb(colors.get('accent', ''))
        if accent_rgb:
            parts.append(f"--accent-rgb: {accent_rgb};")

        # Ensure some fallbacks exist
        if 'card-bg' not in colors:
            parts.append("--card-bg: var(--background);")
        if 'text-main' not in colors:
            parts.append("--bs-body-color: #000000;")

        return ' '.join(parts)

    def get_theme_preview_data(self) -> Dict[str, Any]:
        theme = self.get_current_theme()
        return {
            'id': self.current_theme,
            'name': theme.get('name', 'Theme'),
            'description': theme.get('description', '')
        }