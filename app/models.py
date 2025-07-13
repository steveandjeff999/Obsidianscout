from datetime import datetime
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
import json
import re
import math
from app.utils.config_manager import get_id_to_perm_id_mapping, get_scoring_element_by_perm_id

# Association table for user roles (many-to-many)
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True)
)

# Create an association table for the many-to-many relationship between teams and events
team_event = db.Table('team_event',
    db.Column('team_id', db.Integer, db.ForeignKey('team.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)

class ActivityLog(db.Model):
    """Model to track user activity including keystrokes and actions"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    username = db.Column(db.String(80))  # Store username directly for quicker access
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    action_type = db.Column(db.String(50))  # e.g., 'keystroke', 'button_click', 'form_submit', 'page_view'
    page = db.Column(db.String(200))  # The page/route where action occurred
    element_id = db.Column(db.String(100), nullable=True)  # ID of UI element (if applicable)
    element_type = db.Column(db.String(50), nullable=True)  # Type of element (button, input, etc.)
    data = db.Column(db.Text, nullable=True)  # JSON data with action details
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    
    # Relationship with User model
    user = db.relationship('User', backref=db.backref('activity_logs', lazy=True))
    
    def __repr__(self):
        return f'<ActivityLog {self.action_type} by {self.username} at {self.timestamp}>'

    @staticmethod
    def log_activity(user, action_type, page, element_id=None, element_type=None, data=None, ip_address=None, user_agent=None):
        """Helper method to quickly log an activity"""
        log = ActivityLog(
            user_id=user.id if user else None,
            username=user.username if user else "Anonymous",
            action_type=action_type,
            page=page,
            element_id=element_id,
            element_type=element_type,
            data=json.dumps(data) if data else None,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(log)
        db.session.commit()
        return log

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(128))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Many-to-many relationship with roles
    roles = db.relationship('Role', secondary=user_roles, lazy='subquery',
                           backref=db.backref('users', lazy=True))
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def has_role(self, role_name):
        """Check if user has a specific role"""
        return any(role.name == role_name for role in self.roles)
    
    def get_role_names(self):
        """Get list of role names for this user"""
        return [role.name for role in self.roles]
    
    def can_access_route(self, route_name):
        """Check if user can access a specific route based on their roles"""
        # Admin can access everything
        if self.has_role('admin'):
            return True
        
        # Analytics can access everything except user management
        if self.has_role('analytics'):
            restricted_routes = ['auth.manage_users', 'auth.add_user', 'auth.edit_user', 'auth.delete_user']
            return route_name not in restricted_routes
        
        # Scouts can only access scouting routes and NOT the dashboard
        if self.has_role('scout'):
            allowed_routes = [
                'scouting.index', 'scouting.form', 'scouting.list', 
                'scouting.view', 'scouting.qr', 'scouting.qr_scan', 'scouting.datamatrix',
                'pit_scouting.index', 'pit_scouting.form', 'pit_scouting.list', 
                'pit_scouting.view', 'pit_scouting.sync', 'pit_scouting.upload',
                'auth.logout', 'auth.profile'
            ]
            return route_name in allowed_routes
        
        return False
    
    def __repr__(self):
        return f'<User {self.username}>'

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    
    def __repr__(self):
        return f'<Role {self.name}>'

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_number = db.Column(db.Integer, unique=True, nullable=False)
    team_name = db.Column(db.String(100))
    location = db.Column(db.String(100))
    # Define relationship with ScoutingData
    scouting_data = db.relationship('ScoutingData', backref='team', lazy=True)
    # Track which events this team has participated in
    events = db.relationship('Event', secondary=team_event, lazy='subquery',
                           backref=db.backref('teams', lazy=True))
    
    def __repr__(self):
        return f"Team {self.team_number}: {self.team_name}"
    
    # Add a property to find matches this team has participated in
    @property
    def matches(self):
        """Return all matches this team participated in"""
        team_str = str(self.team_number)
        from sqlalchemy import or_
        return Match.query.filter(
            or_(
                Match.red_alliance.like(f"%{team_str}%"),
                Match.blue_alliance.like(f"%{team_str}%")
            )
        ).all()

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True)  # Event code like "CALA" or "NYRO"
    location = db.Column(db.String(100))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    year = db.Column(db.Integer, nullable=False)
    matches = db.relationship('Match', backref='event', lazy=True)
    
    def __repr__(self):
        return f"Event: {self.name} ({self.year})"

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_number = db.Column(db.Integer, nullable=False)
    match_type = db.Column(db.String(20), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    red_alliance = db.Column(db.String(50))  # Comma-separated team numbers
    blue_alliance = db.Column(db.String(50))  # Comma-separated team numbers
    red_score = db.Column(db.Integer)
    blue_score = db.Column(db.Integer)
    winner = db.Column(db.String(10))  # 'red', 'blue', or 'tie'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    scouting_data = db.relationship('ScoutingData', backref='match', lazy=True)
    
    def __repr__(self):
        return f"Match {self.match_type} {self.match_number}"
    
    @property
    def red_teams(self):
        return [int(team_num) for team_num in self.red_alliance.split(',') if team_num]
    
    @property
    def blue_teams(self):
        return [int(team_num) for team_num in self.blue_alliance.split(',') if team_num]
    
    # Add a method to get team objects
    def get_teams(self):
        """Return all Team objects participating in this match"""
        team_numbers = self.red_teams + self.blue_teams
        return Team.query.filter(Team.team_number.in_(team_numbers)).all()

class ScoutingData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    scout_name = db.Column(db.String(50))
    scouting_station = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    alliance = db.Column(db.String(10))  # 'red' or 'blue'
    data_json = db.Column(db.Text, nullable=False)  # JSON data based on game config
    
    def __repr__(self):
        return f"Scouting Data for Team {self.team.team_number} in Match {self.match.match_number}"
    
    @property
    def data(self):
        """Get data as a Python dictionary"""
        return json.loads(self.data_json)
    
    @data.setter
    def data(self, value):
        """Store data as JSON string"""
        self.data_json = json.dumps(value)
    
    def migrate_data_to_perm_ids(self):
        """Migrates the data in data_json from using id to perm_id."""
        data = self.data
        if data.get('_migrated_to_perm_id'):
            return False  # Already migrated

        id_map = get_id_to_perm_id_mapping()
        new_data = {'_migrated_to_perm_id': True}
        for key, value in data.items():
            new_key = id_map.get(key, key)
            new_data[new_key] = value
        
        self.data = new_data
        return True

    def calculate_metric(self, formula_or_id):
        """Calculate metrics based on formulas or metric IDs defined in game config"""
        data = self.data
        game_config = current_app.config.get('GAME_CONFIG', {})
        
        # Check if this is a metric ID (not a formula)
        metric_config = None
        for metric in game_config.get('data_analysis', {}).get('key_metrics', []):
            if metric.get('id') == formula_or_id:
                metric_config = metric
                formula = metric.get('formula')
                break
        
        # If we found a metric ID, use its formula
        if metric_config:
            formula = metric_config.get('formula')
        else:
            formula = formula_or_id  # Treat the input as a direct formula
        
        # Special handling for auto-generated formulas
        if formula == "auto_generated":
            return self._calculate_auto_points_dynamic(self.data, game_config)
            
        # Create a safer formula evaluation
        try:
            # Initialize local dictionary with default values based on the game configuration
            local_dict = self._initialize_data_dict(game_config)
            
            # Add all data fields from the actual scouting data
            id_map = get_id_to_perm_id_mapping()
            for key, value in data.items():
                perm_id = id_map.get(key, key) # Use perm_id if available
                # For boolean fields that might be stored as string, ensure they're actual booleans
                if isinstance(value, str) and value.lower() in ['true', 'false']:
                    local_dict[perm_id] = value.lower() == 'true'
                # Keep booleans as booleans
                elif isinstance(value, bool):
                    local_dict[perm_id] = value
                # Convert numeric strings to numbers
                elif isinstance(value, str) and value.replace('.', '', 1).isdigit():
                    local_dict[perm_id] = float(value)
                # Everything else, keep as is
                else:
                    local_dict[perm_id] = value
            
            # Get the metric ID if we have it
            metric_id = None
            if metric_config:
                metric_id = metric_config.get('id')
            else:
                # Try to find the metric ID from the formula
                metric_id = self._find_metric_id_by_formula(formula, game_config)
            
            if metric_id:
                # Call the appropriate handler method for this metric
                return self._calculate_specific_metric(metric_id, formula, local_dict)
            
            # For other formulas or if specific handler not found, use general evaluation
            id_map = get_id_to_perm_id_mapping()
            id_to_perm_id = {v: k for k, v in id_map.items()}
            
            # Replace all occurrences of perm_id with id in the formula
            for perm_id, id_val in id_to_perm_id.items():
                formula = formula.replace(id_val, perm_id)

            return self._evaluate_formula(formula, local_dict)
            
        except Exception as e:
            print(f"ERROR calculating metric with formula '{formula}': {str(e)}")
            return 0
    
    def _initialize_data_dict(self, game_config):
        """Initialize data dictionary with default values based on the game configuration"""
        local_dict = {}
        
        # Add period durations to the dictionary for formula calculation
        for period in ['auto_period', 'teleop_period', 'endgame_period']:
            if period in game_config:
                period_name = period.replace('_period', '')
                local_dict[f"{period_name}_duration_seconds"] = game_config[period].get('duration_seconds', 0)
        
        # Calculate total match duration
        auto_duration = game_config.get('auto_period', {}).get('duration_seconds', 15)
        teleop_duration = game_config.get('teleop_period', {}).get('duration_seconds', 120) 
        endgame_duration = game_config.get('endgame_period', {}).get('duration_seconds', 30)
        local_dict['total_match_duration'] = auto_duration + teleop_duration + endgame_duration
        
        # Add all game_pieces to the local dictionary for reference
        if 'game_pieces' in game_config:
            for piece in game_config['game_pieces']:
                piece_id = piece.get('id')
                for attr in ['auto_points', 'teleop_points', 'bonus_points']:
                    if attr in piece:
                        local_dict[f"{piece_id}_{attr}"] = piece[attr]
        
        # Process all scoring elements from each period and set appropriate defaults
        for period in ['auto_period', 'teleop_period', 'endgame_period']:
            if period in game_config:
                for element in game_config[period].get('scoring_elements', []):
                    element_id = element.get('perm_id', element.get('id')) # Use perm_id
                    element_type = element.get('type')
                    default_value = element.get('default', 0 if element_type == 'counter' else False)
                    
                    # Set appropriate default values based on the element type
                    if element_type == 'boolean':
                        local_dict[element_id] = False
                    elif element_type == 'counter':
                        local_dict[element_id] = 0
                    elif element_type == 'select':
                        local_dict[element_id] = default_value or ''
                    else:
                        local_dict[element_id] = default_value
                        
                    # If the element has points, add to dictionary
                    if 'points' in element:
                        if isinstance(element['points'], dict):
                            # For select elements with different points per option
                            for option, points in element['points'].items():
                                local_dict[f"{element_id}_{option}_points"] = points
                        else:
                            # For simple point values
                            local_dict[f"{element_id}_points"] = element['points']
        
        # Also process rating elements
        if 'post_match' in game_config and 'rating_elements' in game_config['post_match']:
            for element in game_config['post_match']['rating_elements']:
                element_id = element.get('perm_id', element.get('id')) # Use perm_id
                default_value = element.get('default', 0)  # Default to 0 when no data is present
                local_dict[element_id] = default_value
                
        return local_dict
    
    def _find_metric_id_by_formula(self, formula, game_config):
        """Find the metric ID for a given formula in the game configuration"""
        if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
            for metric in game_config['data_analysis']['key_metrics']:
                if metric.get('formula') == formula:
                    return metric.get('id')
        return None
    
    def _calculate_specific_metric(self, metric_id, formula, local_dict):
        """Calculate a specific metric based on its ID"""
        # Get game configuration
        game_config = current_app.config.get('GAME_CONFIG', {})
        
        if metric_id == 'tot':
            # Calculate total points dynamically based on components marked with is_total_component=true
            total_points = 0
            for metric in game_config.get('data_analysis', {}).get('key_metrics', []):
                if metric.get('is_total_component'):
                    total_points += self.calculate_metric(metric['id'])
            return total_points
        
        # Check if this metric uses auto-generated formula
        metric_config = None
        for metric in game_config.get('data_analysis', {}).get('key_metrics', []):
            if metric.get('id') == metric_id:
                metric_config = metric
                break
        
        # If metric has auto_generated_formula flag, generate the formula dynamically
        if metric_config and metric_config.get('auto_generated', False):
            if metric_id == 'apt':  # auto points
                return self._calculate_auto_points_dynamic(local_dict, game_config)
            elif metric_id == 'tpt':  # teleop points
                return self._calculate_teleop_points_dynamic(local_dict, game_config)
            elif metric_id == 'ept':  # endgame points
                return self._calculate_endgame_points_dynamic(local_dict, game_config)
            elif metric_id == 'primary_accuracy' or 'accuracy' in metric_id:
                return self._calculate_accuracy_dynamic(local_dict, game_config, metric_config)
            elif metric_id == 'gamepieces_per_match':
                return self._calculate_gamepieces_per_match_dynamic(local_dict, game_config)
            elif metric_id == 'scoring_frequency':
                return self._calculate_scoring_frequency_dynamic(local_dict, game_config)
        
        # If not auto-generated or no special handling needed, use the formula directly
        return self._evaluate_formula(formula, local_dict)
    
    def _calculate_auto_points_dynamic(self, local_dict, game_config=None):
        """Dynamically calculate auto period points based on game pieces and scoring elements"""
        if not game_config:
            game_config = current_app.config.get('GAME_CONFIG', {})
            
        points = 0
        
        # Add points from auto period scoring elements with direct point values
        for element in game_config.get('auto_period', {}).get('scoring_elements', []):
            element_id = element.get('perm_id', element.get('id')) # Use perm_id
            if element_id not in local_dict:
                continue
                
            # Handle elements with direct point values
            if element.get('points') is not None:
                if element.get('type') == 'boolean':
                    # For boolean elements, add points if true
                    if local_dict.get(element_id):
                        points += element.get('points', 0)
                elif element.get('type') == 'counter':
                    # For counter elements, multiply by points
                    points += local_dict.get(element_id, 0) * element.get('points', 0)
                elif element.get('type') == 'select':
                    # For select elements with point values per option
                    selected = local_dict.get(element_id)
                    if isinstance(element.get('points'), dict) and selected in element.get('points'):
                        points += element.get('points').get(selected, 0)
            
            # Handle game pieces - only if this element doesn't already have direct points
            elif element.get('game_piece_id'):
                game_piece_id = element.get('game_piece_id')
                for game_piece in game_config.get('game_pieces', []):
                    if game_piece.get('id') == game_piece_id:
                        # Add points for this game piece
                        points += local_dict.get(element_id, 0) * game_piece.get('auto_points', 0)
                        break
        
        return int(points)
    
    def _calculate_teleop_points_dynamic(self, local_dict, game_config=None):
        """Dynamically calculate teleop period points based on game pieces and scoring elements"""
        if not game_config:
            game_config = current_app.config.get('GAME_CONFIG', {})
            
        points = 0
        
        # Add points from teleop period scoring elements
        for element in game_config.get('teleop_period', {}).get('scoring_elements', []):
            element_id = element.get('perm_id', element.get('id')) # Use perm_id
            if element_id not in local_dict:
                continue
                
            # Handle elements with direct point values
            if element.get('points') is not None:
                if element.get('type') == 'boolean':
                    # For boolean elements, add points if true
                    if local_dict.get(element_id):
                        points += element.get('points', 0)
                elif element.get('type') == 'counter':
                    # For counter elements, multiply by points
                    points += local_dict.get(element_id, 0) * element.get('points', 0)
                elif element.get('type') == 'select':
                    # For select elements with point values per option
                    selected = local_dict.get(element_id)
                    if isinstance(element.get('points'), dict) and selected in element.get('points'):
                        points += element.get('points').get(selected, 0)
            
            # Handle game pieces - only if this element doesn't already have direct points
            elif element.get('game_piece_id'):
                game_piece_id = element.get('game_piece_id')
                for game_piece in game_config.get('game_pieces', []):
                    if game_piece.get('id') == game_piece_id:
                        # Check if this is a bonus scoring element
                        if element.get('bonus'):
                            points += local_dict.get(element_id, 0) * game_piece.get('bonus_points', 0)
                        else:
                            # Normal teleop scoring
                            points += local_dict.get(element_id, 0) * game_piece.get('teleop_points', 0)
                        break
        
        return int(points)
    
    def _calculate_endgame_points_dynamic(self, local_dict, game_config=None):
        """Dynamically calculate endgame period points based on scoring elements"""
        if not game_config:
            game_config = current_app.config.get('GAME_CONFIG', {})
            
        points = 0
        
        # Add points from endgame period scoring elements
        for element in game_config.get('endgame_period', {}).get('scoring_elements', []):
            element_id = element.get('perm_id', element.get('id')) # Use perm_id
            if element_id not in local_dict:
                continue
                
            if element.get('type') == 'boolean' and element.get('points'):
                # For boolean elements, add points if true
                if local_dict.get(element_id):
                    points += element.get('points', 0)
            elif element.get('type') == 'counter' and element.get('points'):
                # For counter elements, multiply by points
                points += local_dict.get(element_id, 0) * element.get('points', 0)
            elif element.get('type') == 'select' and isinstance(element.get('points'), dict):
                # For select elements with point values per option
                selected = local_dict.get(element_id)
                if selected in element.get('points', {}):
                    points += element.get('points', {}).get(selected, 0)
        
        return int(points)
    
    def _calculate_accuracy_dynamic(self, local_dict, game_config, metric_config):
        """Dynamically calculate accuracy metrics for game pieces"""
        if not game_config:
            game_config = current_app.config.get('GAME_CONFIG', {})
            
        # Get the game piece ID from the metric config if specified
        target_game_piece_id = metric_config.get('game_piece_id') if metric_config else None
        
        # If no specific game piece ID is specified, use the first game piece
        if not target_game_piece_id and game_config.get('game_pieces'):
            target_game_piece_id = game_config['game_pieces'][0].get('id')
            
        if not target_game_piece_id:
            return 0  # No valid game piece ID
            
        # Find all scoring elements for this game piece
        scored_count = 0
        missed_count = 0
        
        # Check both auto and teleop period for all scoring elements
        for period in ['auto_period', 'teleop_period']:
            for element in game_config.get(period, {}).get('scoring_elements', []):
                element_id = element.get('id')
                
                # Count scored game pieces
                if element.get('game_piece_id') == target_game_piece_id and element_id in local_dict:
                    scored_count += local_dict.get(element_id, 0)
                    
                # Count missed game pieces (assuming all misses are counted together)
                if 'missed' in element_id.lower() and element_id in local_dict:
                    missed_count += local_dict.get(element_id, 0)
                    
        # Calculate accuracy
        total_attempts = scored_count + missed_count
        if total_attempts == 0:
            return 0
            
        return scored_count / total_attempts
    
    def _calculate_gamepieces_per_match_dynamic(self, local_dict, game_config):
        """Dynamically calculate total game pieces scored in a match"""
        if not game_config:
            game_config = current_app.config.get('GAME_CONFIG', {})
            
        total_scored = 0
        
        # Look through all periods for game piece scoring elements
        for period in ['auto_period', 'teleop_period']:
            for element in game_config.get(period, {}).get('scoring_elements', []):
                element_id = element.get('id')
                
                # Only count elements that score game pieces
                if element.get('game_piece_id') and element_id in local_dict:
                    total_scored += local_dict.get(element_id, 0)
        
        return int(total_scored)
    
    def _calculate_scoring_frequency_dynamic(self, local_dict, game_config):
        """Dynamically calculate scoring frequency (game pieces per minute)"""
        if not game_config:
            game_config = current_app.config.get('GAME_CONFIG', {})
            
        # Get total match duration in minutes
        auto_duration = game_config.get('auto_period', {}).get('duration_seconds', 15)
        teleop_duration = game_config.get('teleop_period', {}).get('duration_seconds', 120) 
        endgame_duration = game_config.get('endgame_period', {}).get('duration_seconds', 30)
        
        total_duration_minutes = (auto_duration + teleop_duration + endgame_duration) / 60.0
        if total_duration_minutes <= 0:
            total_duration_minutes = 2.75  # Default to 2.75 minutes if not specified
            
        # Count all scored game pieces
        total_scored = self._calculate_gamepieces_per_match_dynamic(local_dict, game_config)
        
        return total_scored / total_duration_minutes
    
    def _evaluate_formula(self, formula, local_dict):
        """General formula evaluation with safety checks"""
        try:
            # Process formula for Python evaluation
            processed_formula = formula
            
            # Convert ternary operators (condition ? true_val : false_val)
            while '?' in processed_formula and ':' in processed_formula:
                ternary_match = re.search(r'(.+?)\s*\?\s*(.+?)\s*:\s*(.+)', processed_formula)
                if ternary_match:
                    condition, true_val, false_val = ternary_match.groups()
                    processed_formula = processed_formula.replace(
                        f"{condition} ? {true_val} : {false_val}",
                        f"({true_val} if {condition} else {false_val})"
                    )
                else:
                    break
            
            # Replace JavaScript/C-style operators with Python equivalents
            processed_formula = processed_formula.replace('&&', ' and ')
            processed_formula = processed_formula.replace('||', ' or ')
            processed_formula = processed_formula.replace('!==', ' != ')
            processed_formula = processed_formula.replace('===', ' == ')
            
            # Add quotes around string literals in comparisons
            for key, value in local_dict.items():
                if isinstance(value, str) and key in processed_formula:
                    pattern = r'(\b' + re.escape(key) + r'\s*==\s*)([A-Za-z][A-Za-z0-9_\s]*)'
                    processed_formula = re.sub(pattern, r'\1"\2"', processed_formula)
                    
                    pattern = r'([A-Za-z][A-Za-z0-9_\s]*\s*==\s*)\b' + re.escape(key) + r'\b'
                    processed_formula = re.sub(pattern, r'"\1"', processed_formula)
            
            # Execute the formula with the data
            result = eval(processed_formula, {"__builtins__": {}}, local_dict)
            
            # Handle None or non-numeric results
            if result is None:
                return 0
                
            # Check if this is a metric that should be rounded
            if any(x in formula for x in ['auto_points', 'teleop_points', 'endgame_points', 'total_points']):
                # Round to integer for score values
                return int(result)
            elif 'gamepieces_per_match' in formula:
                # Round to integer for game piece counts
                return int(result)
            else:
                # Keep as float for rates
                return round(float(result), 2)  # Round to 2 decimal places for rates
        except Exception as e:
            print(f"Error evaluating formula '{formula}': {e}")
            return 0

class TeamListEntry(db.Model):
    """A base class for team list entries like Do Not Pick and Avoid"""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    team = db.relationship('Team', backref='list_entries')
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    event = db.relationship('Event')
    reason = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    type = db.Column(db.String(50))  # For tracking entry type (do_not_pick or avoid)

    __mapper_args__ = {
        'polymorphic_identity': 'base',
        'polymorphic_on': type
    }

class DoNotPickEntry(TeamListEntry):
    """Teams that should not be picked under any circumstances"""
    __mapper_args__ = {
        'polymorphic_identity': 'do_not_pick'
    }

class AvoidEntry(TeamListEntry):
    """Teams that should be avoided if possible but could be picked if necessary"""
    __mapper_args__ = {
        'polymorphic_identity': 'avoid'
    }

class AllianceSelection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alliance_number = db.Column(db.Integer, nullable=False)  # 1-8 for 8 alliances
    captain = db.Column(db.Integer, db.ForeignKey('team.id'))  # Captain team
    first_pick = db.Column(db.Integer, db.ForeignKey('team.id'))  # First pick
    second_pick = db.Column(db.Integer, db.ForeignKey('team.id'))  # Second pick
    third_pick = db.Column(db.Integer, db.ForeignKey('team.id'))  # Third pick (backup)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    captain_team = db.relationship('Team', foreign_keys=[captain])
    first_pick_team = db.relationship('Team', foreign_keys=[first_pick])
    second_pick_team = db.relationship('Team', foreign_keys=[second_pick])
    third_pick_team = db.relationship('Team', foreign_keys=[third_pick])
    event = db.relationship('Event', backref='alliances')
    
    def __repr__(self):
        return f"Alliance {self.alliance_number} - Event {self.event_id}"
    
    def get_all_teams(self):
        """Get all team IDs in this alliance"""
        teams = []
        if self.captain:
            teams.append(self.captain)
        if self.first_pick:
            teams.append(self.first_pick)
        if self.second_pick:
            teams.append(self.second_pick)
        if self.third_pick:
            teams.append(self.third_pick)
        return teams
    
    def get_team_objects(self):
        """Get all Team objects in this alliance"""
        teams = []
        if self.captain_team:
            teams.append(self.captain_team)
        if self.first_pick_team:
            teams.append(self.first_pick_team)
        if self.second_pick_team:
            teams.append(self.second_pick_team)
        if self.third_pick_team:
            teams.append(self.third_pick_team)
        return teams

class PitScoutingData(db.Model):
    """Model to store pit scouting data with local storage and upload capability"""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    scout_name = db.Column(db.String(50), nullable=False)
    scout_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    data_json = db.Column(db.Text, nullable=False)  # JSON data based on pit config
    
    # Local storage and sync fields
    local_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID for local storage
    is_uploaded = db.Column(db.Boolean, default=False)
    upload_timestamp = db.Column(db.DateTime, nullable=True)
    device_id = db.Column(db.String(100), nullable=True)  # To track which device created the data
    
    # Relationships
    team = db.relationship('Team', backref=db.backref('pit_scouting_data', lazy=True))
    event = db.relationship('Event', backref=db.backref('pit_scouting_data', lazy=True))
    scout = db.relationship('User', backref=db.backref('pit_scouting_data', lazy=True))
    
    def __repr__(self):
        return f"<PitScoutingData Team {self.team.team_number} by {self.scout_name}>"
    
    @property
    def data(self):
        """Get data as a Python dictionary"""
        try:
            return json.loads(self.data_json)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    @data.setter
    def data(self, value):
        """Set data from a Python dictionary"""
        self.data_json = json.dumps(value)
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'local_id': self.local_id,
            'team_id': self.team_id,
            'team_number': self.team.team_number if self.team else None,
            'event_id': self.event_id,
            'scout_name': self.scout_name,
            'scout_id': self.scout_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'data': self.data,
            'is_uploaded': self.is_uploaded,
            'upload_timestamp': self.upload_timestamp.isoformat() if self.upload_timestamp else None,
            'device_id': self.device_id
        }
    
    @classmethod
    def from_dict(cls, data_dict):
        """Create instance from dictionary"""
        pit_data = cls(
            local_id=data_dict.get('local_id'),
            team_id=data_dict.get('team_id'),
            event_id=data_dict.get('event_id'),
            scout_name=data_dict.get('scout_name'),
            scout_id=data_dict.get('scout_id'),
            data_json=json.dumps(data_dict.get('data', {})),
            is_uploaded=data_dict.get('is_uploaded', False),
            device_id=data_dict.get('device_id')
        )
        
        # Handle timestamp
        if data_dict.get('timestamp'):
            if isinstance(data_dict['timestamp'], str):
                pit_data.timestamp = datetime.fromisoformat(data_dict['timestamp'].replace('Z', '+00:00'))
            else:
                pit_data.timestamp = data_dict['timestamp']
        
        # Handle upload timestamp
        if data_dict.get('upload_timestamp'):
            if isinstance(data_dict['upload_timestamp'], str):
                pit_data.upload_timestamp = datetime.fromisoformat(data_dict['upload_timestamp'].replace('Z', '+00:00'))
            else:
                pit_data.upload_timestamp = data_dict['upload_timestamp']
        
        return pit_data