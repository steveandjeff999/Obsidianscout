import json
import os
from flask import current_app
from flask_login import current_user
import shutil
import copy

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

    # If no team number is present (for example an admin editing the global config),
    # persist to the global config file under `config/game_config.json` so changes
    # are not silently discarded. This preserves previous behavior for team-scoped
    # configs while allowing admin/global saves.
    if team_number is None:
        try:
            base_dir = os.getcwd()
            config_dir = os.path.join(base_dir, 'config')
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, 'game_config.json')
            # Make a backup of the previous global config if it exists
            if os.path.exists(config_path):
                try:
                    shutil.copyfile(config_path, config_path + '.bak')
                except Exception:
                    pass
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
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

def get_id_to_perm_id_mapping(config=None):
    """Return a dictionary mapping the current config element IDs to their permanent IDs."""
    if config is None:
        config = get_current_game_config()

    mapping = {}
    if not config:
        return mapping

    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if 'id' in element and 'perm_id' in element:
                    mapping[element['id']] = element['perm_id']

    # Legacy configs may define scoring elements at the top level
    for element in config.get('scoring_elements', []):
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
                # Merge shared config with default so missing option lists are preserved
                shared = json.loads(active_alliance.shared_pit_config)
                default = load_pit_config(team_number=None)
                return merge_pit_configs(default, shared)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Fallback to the alliance's configured team's config
        if active_alliance.pit_config_team:
            team_cfg = load_pit_config(team_number=active_alliance.pit_config_team)
            default = load_pit_config(team_number=None)
            return merge_pit_configs(default, team_cfg)
    
    # Use team's own config
    default = load_pit_config(team_number=None)
    team_cfg = get_current_pit_config()
    return merge_pit_configs(default, team_cfg)


def merge_pit_configs(base_config, override_config):
    """Return a merged pit config where missing fields in override_config are filled from base_config.

    Specifically ensures that select/multiselect elements retain option lists from the base when the
    team-specific config omitted them (common when instance files were edited incorrectly).
    """
    if not base_config:
        return override_config or {}
    if not override_config:
        return base_config

    result = copy.deepcopy(base_config)

    # Top-level pit_scouting keys (title/description) - override if provided
    base_ps = result.get('pit_scouting', {})
    over_ps = override_config.get('pit_scouting', {})

    if 'title' in over_ps:
        base_ps['title'] = over_ps['title']
    if 'description' in over_ps:
        base_ps['description'] = over_ps['description']

    # Build lookup of base sections by id
    base_sections = {s.get('id'): s for s in base_ps.get('sections', [])}

    merged_sections = []

    # Iterate through override sections; merge with base where possible
    for o_sec in over_ps.get('sections', []):
        sec_id = o_sec.get('id')
        b_sec = base_sections.get(sec_id)
        if not b_sec:
            # Section doesn't exist in base; add as-is
            merged_sections.append(copy.deepcopy(o_sec))
            continue

        # Start from base section and overlay override fields
        merged_sec = copy.deepcopy(b_sec)
        if 'name' in o_sec:
            merged_sec['name'] = o_sec['name']

        # Build element lookup from base by perm_id or id
        base_elements = {e.get('perm_id') or e.get('id'): e for e in merged_sec.get('elements', [])}

        merged_elements = []
        for o_elem in o_sec.get('elements', []):
            key = o_elem.get('perm_id') or o_elem.get('id')
            b_elem = base_elements.get(key)
            if not b_elem:
                merged_elements.append(copy.deepcopy(o_elem))
                continue

            # Start from base element and overlay override properties
            merged_elem = copy.deepcopy(b_elem)
            for k, v in o_elem.items():
                # If override explicitly provides a value, set it
                merged_elem[k] = v

            # If override omitted options but base had them, keep base.options
            if 'options' not in o_elem and 'options' in b_elem:
                merged_elem['options'] = copy.deepcopy(b_elem['options'])

            merged_elements.append(merged_elem)

        # Also include any base elements that were not present in override
        override_keys = set([e.get('perm_id') or e.get('id') for e in o_sec.get('elements', [])])
        for b_key, b_elem in base_elements.items():
            if b_key not in override_keys:
                merged_elements.append(copy.deepcopy(b_elem))

        merged_sec['elements'] = merged_elements
        merged_sections.append(merged_sec)

    # Include any base sections not present in override
    override_sec_ids = set([s.get('id') for s in over_ps.get('sections', [])])
    for b_id, b_sec in base_sections.items():
        if b_id not in override_sec_ids:
            merged_sections.append(copy.deepcopy(b_sec))

    result['pit_scouting']['sections'] = merged_sections
    return result

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
