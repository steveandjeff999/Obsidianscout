import json
import os
from flask import current_app

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
            elif element_type == 'select' and isinstance(points, dict):
                # Create a nested ternary for select options
                options = element.get('options', [])
                ternary = ""
                # Sort points by value to build a proper ternary
                sorted_points = sorted(points.items(), key=lambda item: item[1], reverse=True)
                
                first = True
                for option, value in sorted_points:
                    if option == "None" or value == 0: continue
                    if not first:
                        ternary += " : "
                    ternary += f"({element_id} == '{option}' ? {value}"
                    first = False
                
                ternary += " : 0" + ")" * (len(sorted_points) -1) # Subtract "None"
                formula_parts.append(ternary)


        return " + ".join(formula_parts) if formula_parts else "0"

def get_config_manager():
    return current_app.config['CONFIG_MANAGER']

def load_game_config():
    """Loads the game configuration from the JSON file."""
    config_path = os.path.join(os.getcwd(), 'config', 'game_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config
    return {}

def get_scoring_element_by_id(element_id):
    """Finds a scoring element by its ID across all periods."""
    config = load_game_config()
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if element['id'] == element_id:
                    return element
    return None

def get_id_by_name(element_name):
    """Finds the ID of a scoring element by its name."""
    config = load_game_config()
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if element['name'] == element_name:
                    return element['id']
    return None

def get_all_scoring_element_ids():
    """Returns a list of all scoring element IDs."""
    config = load_game_config()
    ids = []
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                ids.append(element['id'])
    return ids

def get_scoring_element_by_perm_id(perm_id):
    """Finds a scoring element by its permanent ID across all periods."""
    config = load_game_config()
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if element.get('perm_id') == perm_id:
                    return element
    return None

def get_id_to_perm_id_mapping():
    """Returns a dictionary mapping current IDs to permanent IDs."""
    config = load_game_config()
    mapping = {}
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in config:
            for element in config[period].get('scoring_elements', []):
                if 'id' in element and 'perm_id' in element:
                    mapping[element['id']] = element['perm_id']
    return mapping
