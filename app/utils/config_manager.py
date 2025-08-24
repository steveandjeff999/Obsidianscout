import json
import os
from flask import current_app
from flask_login import current_user
import shutil

class ConfigManager:
    def __init__(self, app=None):
        self.app = app
        self.game_config = {}
        self.scorable_items = {}
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.load_config()
        app.config['GAME_CONFIG'] = self.game_config
        app.config['CONFIG_MANAGER'] = self

    def load_config(self):
        config_path = os.path.join(os.getcwd(), 'config', 'game_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                self.game_config = json.load(f)
            self._process_config()
        else:
            self.game_config = {}

    def _process_config(self):
        self.scorable_items = {}
        for period in ['auto_period', 'teleop_period', 'endgame_period']:
            if period in self.game_config:
                for element in self.game_config[period].get('scoring_elements', []):
                    self.scorable_items[element['id']] = element

    def get_metric_formula(self, metric_id):
        if 'data_analysis' in self.game_config and 'key_metrics' in self.game_config['data_analysis']:
            for metric in self.game_config['data_analysis']['key_metrics']:
                if metric['id'] == metric_id:
                    formula_obj = metric.get('formula')
                    if isinstance(formula_obj, dict):
                        return self._build_formula(formula_obj['type'])
                    return formula_obj
        return None

    def _build_formula(self, formula_type):
        formula_parts = []
        if formula_type == 'auto_points':
            period_elements = self.game_config.get('auto_period', {}).get('scoring_elements', [])
        elif formula_type == 'teleop_points':
            period_elements = self.game_config.get('teleop_period', {}).get('scoring_elements', [])
        elif formula_type == 'endgame_points':
            period_elements = self.game_config.get('endgame_period', {}).get('scoring_elements', [])
        elif formula_type == 'total_points':
            auto_formula = self._build_formula('auto_points')
            teleop_formula = self._build_formula('teleop_points')
            endgame_formula = self._build_formula('endgame_points')
            return f"({auto_formula}) + ({teleop_formula}) + ({endgame_formula})"
        else:
            return None

        for element in period_elements:
            element_id = element['id']
            points = element.get('points')
            element_type = element.get('type')

            if element_type == 'boolean':
                formula_parts.append(f"({element_id} ? {points} : 0)")
            elif element_type == 'counter':
                formula_parts.append(f"({element_id} * {points})")
            elif element_type == 'select':
                # Support both dict (new) and single value (legacy)
                if isinstance(points, dict):
                    options = element.get('options', [])
                    ternary = ""
                    sorted_points = sorted(points.items(), key=lambda item: item[1], reverse=True)
                    first = True
                    for option, value in sorted_points:
                        if option == "None" or value == 0: continue
                        if not first:
                            ternary += " : "
                        ternary += f"({element_id} == '{option}' ? {value}"
                        first = False
                    ternary += " : 0" + ")" * (len(sorted_points) -1)
                    formula_parts.append(ternary)
                else:
                    # Legacy: all options get the same points value
                    formula_parts.append(f"({element_id} ? {points if points is not None else 0} : 0)")


        return " + ".join(formula_parts) if formula_parts else "0"

def get_config_manager():
    return current_app.config['CONFIG_MANAGER']

def get_current_game_config():
    """Loads the game configuration for the current user's team."""
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number
    return load_game_config(team_number=team_number)

def save_game_config(data):
    """Saves the game configuration for the current user's team."""
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number

    if team_number is None:
        # Cannot save config for a non-team user
        return False

    base_dir = os.getcwd()
    config_name = 'game_config.json'
    team_config_dir = os.path.join(base_dir, 'instance', 'configs', str(team_number))
    os.makedirs(team_config_dir, exist_ok=True)
    team_config_path = os.path.join(team_config_dir, config_name)

    with open(team_config_path, 'w') as f:
        json.dump(data, f, indent=2)
    return True

def get_current_pit_config():
    """Loads the pit scouting configuration for the current user's team."""
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number
    return load_pit_config(team_number=team_number)

def save_pit_config(data):
    """Saves the pit scouting configuration for the current user's team."""
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number

    if team_number is None:
        return False

    base_dir = os.getcwd()
    config_name = 'pit_config.json'
    team_config_dir = os.path.join(base_dir, 'instance', 'configs', str(team_number))
    os.makedirs(team_config_dir, exist_ok=True)
    team_config_path = os.path.join(team_config_dir, config_name)

    with open(team_config_path, 'w') as f:
        json.dump(data, f, indent=2)
    return True

def load_config(config_name, team_number=None):
    """Generic function to load a config file for a specific team."""
    base_dir = os.getcwd()
    default_path = os.path.join(base_dir, 'config', config_name)

    config_to_load = default_path
    if team_number is not None:
        team_config_dir = os.path.join(base_dir, 'instance', 'configs', str(team_number))
        team_config_path = os.path.join(team_config_dir, config_name)

        if not os.path.exists(team_config_path):
            if os.path.exists(default_path):
                os.makedirs(team_config_dir, exist_ok=True)
                shutil.copy(default_path, team_config_path)
            else:
                os.makedirs(team_config_dir, exist_ok=True)
                with open(team_config_path, 'w') as f:
                    json.dump({}, f)

        config_to_load = team_config_path

    if os.path.exists(config_to_load):
        with open(config_to_load, 'r') as f:
            return json.load(f)
    return {}

def load_game_config(team_number=None):
    return load_config('game_config.json', team_number)

def load_pit_config(team_number=None):
    return load_config('pit_config.json', team_number)

def get_scoring_element_by_id(element_id):
    """Finds a scoring element by its ID across all periods."""
    config = get_current_game_config()
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if element['id'] == element_id:
                    return element
    return None

def get_id_by_name(element_name):
    """Finds the ID of a scoring element by its name."""
    config = get_current_game_config()
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if element['name'] == element_name:
                    return element['id']
    return None

def get_all_scoring_element_ids():
    """Returns a list of all scoring element IDs."""
    config = get_current_game_config()
    ids = []
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                ids.append(element['id'])
    return ids

def get_scoring_element_by_perm_id(perm_id):
    """Finds a scoring element by its permanent ID across all periods."""
    config = get_current_game_config()
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if element.get('perm_id') == perm_id:
                    return element
    return None

def get_id_to_perm_id_mapping():
    """Returns a dictionary mapping current IDs to permanent IDs."""
    config = get_current_game_config()
    mapping = {}
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if 'id' in element and 'perm_id' in element:
                    mapping[element['id']] = element['perm_id']
    return mapping

# ======== ALLIANCE-AWARE CONFIG FUNCTIONS ========

def get_effective_game_config():
    """Get the effective game config, considering alliance mode"""
    from app.models import TeamAllianceStatus
    from flask_login import current_user
    
    # Get current team number
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number
    
    if not team_number:
        return get_current_game_config()
    
    # Check if alliance mode is active for this team
    active_alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
    
    if active_alliance and active_alliance.is_config_complete():
        # Use alliance's shared game config
        if active_alliance.shared_game_config:
            try:
                return json.loads(active_alliance.shared_game_config)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Fallback to the alliance's configured team's config
        if active_alliance.game_config_team:
            return load_game_config(team_number=active_alliance.game_config_team)
    
    # Use team's own config
    return get_current_game_config()

def get_effective_pit_config():
    """Get the effective pit config, considering alliance mode"""
    from app.models import TeamAllianceStatus
    from flask_login import current_user
    
    # Get current team number
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number
    
    if not team_number:
        return get_current_pit_config()
    
    # Check if alliance mode is active for this team
    active_alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
    
    if active_alliance and active_alliance.is_config_complete():
        # Use alliance's shared pit config
        if active_alliance.shared_pit_config:
            try:
                return json.loads(active_alliance.shared_pit_config)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Fallback to the alliance's configured team's config
        if active_alliance.pit_config_team:
            return load_pit_config(team_number=active_alliance.pit_config_team)
    
    # Use team's own config
    return get_current_pit_config()

def is_alliance_mode_active():
    """Check if alliance mode is currently active for the current user's team"""
    from app.models import TeamAllianceStatus
    from flask_login import current_user
    
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number
    
    if not team_number:
        return False
    
    return TeamAllianceStatus.is_alliance_mode_active_for_team(team_number)

def get_active_alliance_info():
    """Get information about the currently active alliance"""
    from app.models import TeamAllianceStatus
    from flask_login import current_user
    
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        team_number = current_user.scouting_team_number
    
    if not team_number:
        return None
    
    active_alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
    if active_alliance:
        return {
            'alliance_id': active_alliance.id,
            'alliance_name': active_alliance.alliance_name,
            'game_config_team': active_alliance.game_config_team,
            'pit_config_team': active_alliance.pit_config_team,
            'config_status': active_alliance.config_status
        }
    
    return None

def get_available_default_configs():
    """Get list of available default configuration files"""
    default_configs = []
    default_config_dir = os.path.join(os.getcwd(), 'instance', 'defaultconfigs', 'years')
    
    if os.path.exists(default_config_dir):
        for filename in os.listdir(default_config_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(default_config_dir, filename)
                try:
                    with open(filepath, 'r') as f:
                        config_data = json.load(f)
                    
                    # Extract year/name from filename and config
                    year = filename.replace('.json', '')
                    game_name = config_data.get('game_name', 'Unknown Game')
                    season = config_data.get('season', year)
                    
                    default_configs.append({
                        'filename': filename,
                        'year': year,
                        'game_name': game_name,
                        'season': season,
                        'display_name': f"{season} - {game_name}"
                    })
                except (json.JSONDecodeError, FileNotFoundError, KeyError):
                    # Skip invalid config files
                    continue
    
    # Sort by year (descending)
    default_configs.sort(key=lambda x: x['year'], reverse=True)
    return default_configs

def load_default_config(filename):
    """Load a specific default configuration file"""
    default_config_dir = os.path.join(os.getcwd(), 'instance', 'defaultconfigs', 'years')
    filepath = os.path.join(default_config_dir, filename)
    
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Default config file not found: {filename}")
    
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config file {filename}: {e}")

def reset_config_to_default(filename, config_type='game'):
    """Reset current configuration to a default configuration"""
    try:
        default_config = load_default_config(filename)
        
        if config_type == 'game':
            # Save as game config
            if save_game_config(default_config):
                # Update the current app config
                current_app.config['GAME_CONFIG'] = default_config
                return True, f"Game configuration reset to {filename}"
            else:
                return False, "Failed to save game configuration"
        elif config_type == 'pit':
            # Save as pit config
            if save_pit_config(default_config):
                return True, f"Pit configuration reset to {filename}"
            else:
                return False, "Failed to save pit configuration"
        else:
            return False, f"Unknown config type: {config_type}"
    
    except FileNotFoundError as e:
        return False, str(e)
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unexpected error: {e}"
