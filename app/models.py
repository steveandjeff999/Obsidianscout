from datetime import datetime
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
import json
import re
import math
from app.utils.config_manager import get_id_to_perm_id_mapping, get_scoring_element_by_perm_id, get_current_game_config
from app.utils.concurrent_models import ConcurrentModelMixin

# Association table for user roles (many-to-many)
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, primary_key=True),
    db.Column('role_id', db.Integer, primary_key=True),
    info={'bind_key': 'users'}
)

# Create an association table for the many-to-many relationship between teams and events
team_event = db.Table('team_event',
    db.Column('team_id', db.Integer, db.ForeignKey('team.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)


class User(UserMixin, ConcurrentModelMixin, db.Model):
    __bind_key__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(128))
    scouting_team_number = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    profile_picture = db.Column(db.String(256), nullable=True, default='img/avatars/default.png')
    must_change_password = db.Column(db.Boolean, default=False)
    
    # Many-to-many relationship with roles
    # roles relationship will be defined after Role class to provide explicit
    # join conditions when the association table does not include DB-level FKs.
    
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

    def has_roles(self):
        """Check if user has any roles"""
        return len(self.roles) > 0
    
    def can_access_route(self, route_name):
        """Check if user can access a specific route based on their roles"""
        # Superadmin can only access user management and basic functions
        if self.has_role('superadmin'):
            return route_name in [
                'auth.manage_users', 'auth.edit_user', 'auth.delete_user', 
                'auth.update_user', 'auth.add_user', 'auth.logout', 'auth.profile'
            ]

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
        
        # Remove viewer role logic
        # (No viewer-specific allowed_routes)
        
        return False
    
    def __repr__(self):
        return f'<User {self.username}>'

class Role(db.Model):
    __bind_key__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    
    def __repr__(self):
        return f'<Role {self.name}>'

# Define the many-to-many relationship between User and Role now that both
# table objects are available. Use explicit join conditions because the
# association table does not contain DB-level ForeignKey constraints (separate
# DB files cannot enforce cross-file FKs).
User.roles = db.relationship(
    'Role',
    secondary=user_roles,
    primaryjoin=(User.id == user_roles.c.user_id),
    secondaryjoin=(Role.id == user_roles.c.role_id),
    backref=db.backref('users', lazy=True),
    lazy='subquery'
)

class ScoutingTeamSettings(db.Model):
    """Model to store team-level settings and preferences"""
    id = db.Column(db.Integer, primary_key=True)
    scouting_team_number = db.Column(db.Integer, unique=True, nullable=False)
    account_creation_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_by_user_id = db.Column(db.Integer, nullable=True)
    locked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Accessor for the User who locked/unlocked accounts. We avoid an ORM
    # relationship here because User lives in a separate DB bind; instead
    # provide a runtime lookup by id.
    @property
    def locked_by_user(self):
        try:
            return User.query.get(self.locked_by_user_id) if self.locked_by_user_id else None
        except Exception:
            return None
    
    def __repr__(self):
        status = "LOCKED" if self.account_creation_locked else "UNLOCKED"
        return f'<ScoutingTeamSettings Team {self.scouting_team_number}: {status}>'
    
    @staticmethod
    def get_or_create_for_team(team_number):
        """Get or create settings for a scouting team"""
        settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=team_number).first()
        if not settings:
            settings = ScoutingTeamSettings(scouting_team_number=team_number)
            db.session.add(settings)
            db.session.commit()
        return settings
    
    def lock_account_creation(self, user):
        """Lock account creation for this team"""
        self.account_creation_locked = True
        self.locked_by_user_id = user.id
        self.locked_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        db.session.commit()
    
    def unlock_account_creation(self, user):
        """Unlock account creation for this team"""
        self.account_creation_locked = False
        self.locked_by_user_id = user.id
        self.locked_at = None
        self.updated_at = datetime.utcnow()
        db.session.commit()

class Team(ConcurrentModelMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_number = db.Column(db.Integer, nullable=False)
    team_name = db.Column(db.String(100))
    location = db.Column(db.String(100))
    scouting_team_number = db.Column(db.Integer, nullable=True)
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
    code = db.Column(db.String(20))  # Event code like "CALA" or "NYRO" - not unique anymore since multiple teams can have same event
    location = db.Column(db.String(100))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    year = db.Column(db.Integer, nullable=False)
    scouting_team_number = db.Column(db.Integer, nullable=True)
    matches = db.relationship('Match', backref='event', lazy=True)
    
    def __repr__(self):
        return f"Event: {self.name} ({self.year})"

class Match(ConcurrentModelMixin, db.Model):
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
    scouting_team_number = db.Column(db.Integer, nullable=True)
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

class ScoutingData(ConcurrentModelMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    scouting_team_number = db.Column(db.Integer, nullable=True)
    scout_name = db.Column(db.String(50))
    scout_id = db.Column(db.Integer, nullable=True)
    scouting_station = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    alliance = db.Column(db.String(10))  # 'red' or 'blue'
    data_json = db.Column(db.Text, nullable=False)  # JSON data based on game config

    # Accessor to the User who submitted this entry (optional)
    @property
    def scout(self):
        try:
            return User.query.get(self.scout_id) if self.scout_id else None
        except Exception:
            return None
    
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
        game_config = get_current_game_config()
        
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
        game_config = get_current_game_config()
        
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
            game_config = get_current_game_config()
            
        points = 0
        
        # Add points from auto period scoring elements with direct point values
        for element in game_config.get('auto_period', {}).get('scoring_elements', []):
            element_id = element.get('id')
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
            game_config = get_current_game_config()
            
        points = 0
        
        # Add points from teleop period scoring elements
        for element in game_config.get('teleop_period', {}).get('scoring_elements', []):
            element_id = element.get('id')
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
            game_config = get_current_game_config()
            
        points = 0
        
        # Add points from endgame period scoring elements
        for element in game_config.get('endgame_period', {}).get('scoring_elements', []):
            element_id = element.get('id')
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
            game_config = get_current_game_config()
            
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
            game_config = get_current_game_config()
            
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
            game_config = get_current_game_config()
            
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
    scouting_team_number = db.Column(db.Integer, nullable=True)

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
    scouting_team_number = db.Column(db.Integer, nullable=True)
    
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
    scouting_team_number = db.Column(db.Integer, nullable=True)
    scout_name = db.Column(db.String(50), nullable=False)
    scout_id = db.Column(db.Integer, nullable=True)
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
    @property
    def scout(self):
        try:
            return User.query.get(self.scout_id) if self.scout_id else None
        except Exception:
            return None
    
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

class StrategyDrawing(db.Model):
    """Model to store strategy drawing data for each match"""
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False, unique=True)
    scouting_team_number = db.Column(db.Integer, nullable=True)
    data_json = db.Column(db.Text, nullable=False)  # JSON-encoded drawing data
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    background_image = db.Column(db.String(256), nullable=True)  # Path or filename of custom background

    match = db.relationship('Match', backref=db.backref('strategy_drawing', uselist=False))

    def __repr__(self):
        return f"<StrategyDrawing for Match {self.match_id}>"

    @property
    def data(self):
        try:
            return json.loads(self.data_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @data.setter
    def data(self, value):
        self.data_json = json.dumps(value)


# ======== SCOUTING ALLIANCE MODELS ========

class ScoutingAlliance(db.Model):
    """Model to represent a scouting alliance between teams"""
    __tablename__ = 'scouting_alliance'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Configuration sync settings
    game_config_team = db.Column(db.Integer, nullable=True)  # Team whose game config to use
    pit_config_team = db.Column(db.Integer, nullable=True)  # Team whose pit config to use
    config_status = db.Column(db.String(50), default='pending')  # 'pending', 'configured', 'conflict'
    shared_game_config = db.Column(db.Text)  # JSON game config data
    shared_pit_config = db.Column(db.Text)  # JSON pit config data
    
    # Alliance members relationship
    members = db.relationship('ScoutingAllianceMember', backref='alliance', cascade='all, delete-orphan')
    events = db.relationship('ScoutingAllianceEvent', backref='alliance', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ScoutingAlliance {self.alliance_name}>'
    
    def get_active_members(self):
        """Get all active members of this alliance"""
        return [member for member in self.members if member.status == 'accepted']
    
    def get_member_team_numbers(self):
        """Get list of team numbers in this alliance"""
        return [member.team_number for member in self.get_active_members()]
    
    def is_member(self, team_number):
        """Check if a team is a member of this alliance"""
        return team_number in self.get_member_team_numbers()
    
    def get_shared_events(self):
        """Get events this alliance is collaborating on"""
        return [ae.event_code for ae in self.events if ae.is_active]
    
    def get_config_summary(self):
        """Get a summary of configuration status"""
        summary = {
            'game_config_status': 'Not Set',
            'pit_config_status': 'Not Set',
            'game_config_team': self.game_config_team,
            'pit_config_team': self.pit_config_team,
            'overall_status': self.config_status
        }
        
        if self.game_config_team:
            summary['game_config_status'] = f"Using Team {self.game_config_team}'s config"
        if self.pit_config_team:
            summary['pit_config_status'] = f"Using Team {self.pit_config_team}'s config"
            
        return summary
    
    def has_config_conflicts(self):
        """Check if there are configuration conflicts"""
        return self.config_status == 'conflict'
    
    def is_config_complete(self):
        """Check if configuration is complete"""
        return self.game_config_team is not None and self.pit_config_team is not None

class ScoutingAllianceMember(db.Model):
    """Model to represent members of a scouting alliance"""
    __tablename__ = 'scouting_alliance_member'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    team_number = db.Column(db.Integer, nullable=False)
    team_name = db.Column(db.String(100))
    role = db.Column(db.String(50), default='member')  # 'admin', 'member'
    status = db.Column(db.String(50), default='pending')  # 'pending', 'accepted', 'declined'
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    invited_by = db.Column(db.Integer, nullable=True)  # Team number that sent the invite
    
    def __repr__(self):
        return f'<AllianceMember {self.team_number} in Alliance {self.alliance_id}>'

class ScoutingAllianceInvitation(db.Model):
    """Model to represent alliance invitations"""
    __tablename__ = 'scouting_alliance_invitation'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    from_team_number = db.Column(db.Integer, nullable=False)
    to_team_number = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')  # 'pending', 'accepted', 'declined'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime)
    
    # Relationship to alliance
    alliance = db.relationship('ScoutingAlliance', backref='invitations')
    
    def __repr__(self):
        return f'<Invitation from {self.from_team_number} to {self.to_team_number}>'

class ScoutingAllianceEvent(db.Model):
    """Model to represent events an alliance is collaborating on"""
    __tablename__ = 'scouting_alliance_event'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    event_code = db.Column(db.String(20), nullable=False)
    event_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<AllianceEvent {self.event_code} for Alliance {self.alliance_id}>'

class ScoutingAllianceSync(db.Model):
    """Model to track data synchronization between alliance members"""
    __tablename__ = 'scouting_alliance_sync'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    from_team_number = db.Column(db.Integer, nullable=False)
    to_team_number = db.Column(db.Integer, nullable=False)
    data_type = db.Column(db.String(50), nullable=False)  # 'scouting_data', 'pit_data', 'chat'
    data_count = db.Column(db.Integer, default=0)
    last_sync = db.Column(db.DateTime, default=datetime.utcnow)
    sync_status = db.Column(db.String(50), default='pending')  # 'pending', 'synced', 'failed'
    
    # Relationship to alliance
    alliance = db.relationship('ScoutingAlliance', backref='sync_records')
    
    def __repr__(self):
        return f'<Sync {self.data_type} from {self.from_team_number} to {self.to_team_number}>'

class ScoutingAllianceChat(db.Model):
    """Model for chat messages between alliance members"""
    __tablename__ = 'scouting_alliance_chat'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    from_team_number = db.Column(db.Integer, nullable=False)
    from_username = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(50), default='text')  # 'text', 'system', 'data_share'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    
    # Relationship to alliance
    alliance = db.relationship('ScoutingAlliance', backref='chat_messages')
    
    def __repr__(self):
        return f'<Chat from {self.from_username} in Alliance {self.alliance_id}>'
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'from_team_number': self.from_team_number,
            'from_username': self.from_username,
            'message': self.message,
            'message_type': self.message_type,
            'created_at': self.created_at.isoformat(),
            'is_read': self.is_read
        }

class TeamAllianceStatus(db.Model):
    """Model to track which alliance is currently active for each team"""
    __tablename__ = 'team_alliance_status'
    
    id = db.Column(db.Integer, primary_key=True)
    team_number = db.Column(db.Integer, nullable=False, unique=True)
    active_alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=True)
    is_alliance_mode_active = db.Column(db.Boolean, default=False)
    activated_at = db.Column(db.DateTime, nullable=True)
    deactivated_at = db.Column(db.DateTime, nullable=True)
    
    # Relationship to active alliance
    active_alliance = db.relationship('ScoutingAlliance', backref='active_teams')
    
    def __repr__(self):
        return f'<TeamAllianceStatus Team {self.team_number} - Active: {self.is_alliance_mode_active}>'
    
    @classmethod
    def get_active_alliance_for_team(cls, team_number):
        """Get the currently active alliance for a team"""
        status = cls.query.filter_by(
            team_number=team_number, 
            is_alliance_mode_active=True
        ).first()
        return status.active_alliance if status else None
    
    @classmethod
    def is_alliance_mode_active_for_team(cls, team_number):
        """Check if alliance mode is active for a team"""
        status = cls.query.filter_by(team_number=team_number).first()
        return status.is_alliance_mode_active if status else False
    
    @classmethod
    def activate_alliance_for_team(cls, team_number, alliance_id):
        """Activate an alliance for a team - automatically deactivates any other active alliance"""
        status = cls.query.filter_by(team_number=team_number).first()
        if not status:
            status = cls(team_number=team_number)
            db.session.add(status)
        
        # Check if team is trying to activate a different alliance
        if status.is_alliance_mode_active and status.active_alliance_id != alliance_id:
            # Automatically deactivate current alliance and switch to new one
            status.deactivated_at = datetime.utcnow()
        
        status.active_alliance_id = alliance_id
        status.is_alliance_mode_active = True
        status.activated_at = datetime.utcnow()
        status.deactivated_at = None
        db.session.commit()
        return status
    
    @classmethod
    def deactivate_alliance_for_team(cls, team_number):
        """Deactivate alliance mode for a team"""
        status = cls.query.filter_by(team_number=team_number).first()
        if status:
            status.is_alliance_mode_active = False
            status.deactivated_at = datetime.utcnow()
            db.session.commit()
        return status
    
    @classmethod
    def can_team_join_alliance(cls, team_number, alliance_id):
        """Check if a team can join a new alliance (not active in another alliance)"""
        status = cls.query.filter_by(team_number=team_number).first()
        if not status:
            return True  # Team not in any alliance
        
        # Team can join if:
        # 1. They're not currently active in any alliance, OR
        # 2. They're trying to join the same alliance they're already active in
        return not status.is_alliance_mode_active or status.active_alliance_id == alliance_id
    
    @classmethod
    def get_active_alliance_name(cls, team_number):
        """Get the name of the currently active alliance for a team"""
        status = cls.query.filter_by(
            team_number=team_number, 
            is_alliance_mode_active=True
        ).first()
        return status.active_alliance.alliance_name if status and status.active_alliance else None

class SharedGraph(db.Model):
    """Model to store shared graph configurations for public viewing"""
    __tablename__ = 'shared_graph'
    
    id = db.Column(db.Integer, primary_key=True)
    share_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID for public URL
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    
    # Graph configuration
    team_numbers = db.Column(db.Text, nullable=False)  # JSON array of team numbers
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    metric = db.Column(db.String(100), nullable=False)
    graph_types = db.Column(db.Text, nullable=False)  # JSON array of graph types
    data_view = db.Column(db.String(50), default='averages')  # 'averages' or 'matches'
    
    # Metadata
    created_by_team = db.Column(db.Integer, nullable=False)  # Team number that created the share
    created_by_user = db.Column(db.String(80), nullable=False)  # Username that created the share
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)  # Optional expiration
    view_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    
    # Privacy settings
    is_public = db.Column(db.Boolean, default=True)  # Always true for now, but allows future extension
    allow_comments = db.Column(db.Boolean, default=False)  # Future feature
    
    # Relationship to event
    event = db.relationship('Event', backref='shared_graphs')
    
    def __repr__(self):
        return f'<SharedGraph {self.share_id} - {self.title}>'
    
    @property
    def team_numbers_list(self):
        """Get team numbers as a Python list"""
        try:
            return json.loads(self.team_numbers)
        except (json.JSONDecodeError, TypeError):
            return []
    
    @team_numbers_list.setter
    def team_numbers_list(self, value):
        """Set team numbers from a Python list"""
        self.team_numbers = json.dumps(value)
    
    @property
    def graph_types_list(self):
        """Get graph types as a Python list"""
        try:
            return json.loads(self.graph_types)
        except (json.JSONDecodeError, TypeError):
            return []
    
    @graph_types_list.setter
    def graph_types_list(self, value):
        """Set graph types from a Python list"""
        self.graph_types = json.dumps(value)
    
    def is_expired(self):
        """Check if this shared graph has expired"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    def get_teams(self):
        """Get Team objects for the teams in this shared graph"""
        team_numbers = self.team_numbers_list
        if not team_numbers:
            return []
        return Team.query.filter(Team.team_number.in_(team_numbers)).all()
    
    def increment_view_count(self):
        """Increment the view count for this shared graph"""
        self.view_count += 1
        db.session.commit()
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'share_id': self.share_id,
            'title': self.title,
            'description': self.description,
            'team_numbers': self.team_numbers_list,
            'event_id': self.event_id,
            'event_name': self.event.name if self.event else None,
            'metric': self.metric,
            'graph_types': self.graph_types_list,
            'data_view': self.data_view,
            'created_by_team': self.created_by_team,
            'created_by_user': self.created_by_user,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'view_count': self.view_count,
            'is_active': self.is_active,
            'is_public': self.is_public,
            'is_expired': self.is_expired()
        }
    
    @classmethod
    def create_share(cls, title, team_numbers, event_id, metric, graph_types, data_view, 
                     created_by_team, created_by_user, description=None, expires_in_days=None):
        """Create a new shared graph"""
        import uuid
        
        share_id = str(uuid.uuid4())
        
        # Calculate expiration if specified
        expires_at = None
        if expires_in_days:
            from datetime import timedelta
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        
        shared_graph = cls(
            share_id=share_id,
            title=title,
            description=description,
            team_numbers=json.dumps(team_numbers),
            event_id=event_id,
            metric=metric,
            graph_types=json.dumps(graph_types),
            data_view=data_view,
            created_by_team=created_by_team,
            created_by_user=created_by_user,
            expires_at=expires_at
        )
        
        db.session.add(shared_graph)
        db.session.commit()
        return shared_graph
    
    @classmethod
    def get_by_share_id(cls, share_id):
        """Get a shared graph by its share ID"""
        return cls.query.filter_by(share_id=share_id, is_active=True).first()
    
    @classmethod
    def get_user_shares(cls, team_number, username=None):
        """Get all shared graphs created by a team/user"""
        query = cls.query.filter_by(created_by_team=team_number, is_active=True)
        if username:
            query = query.filter_by(created_by_user=username)
        return query.order_by(cls.created_at.desc()).all()


class SharedTeamRanks(db.Model):
    """Model to store shared team ranking configurations for public viewing"""
    __tablename__ = 'shared_team_ranks'
    
    id = db.Column(db.Integer, primary_key=True)
    share_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID for public URL
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    
    # Ranking configuration
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    metric = db.Column(db.String(100), nullable=False, default='tot')  # Metric to rank by
    
    # Metadata
    created_by_team = db.Column(db.Integer, nullable=False)  # Team number that created the share
    created_by_user = db.Column(db.String(80), nullable=False)  # Username that created the share
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)  # Optional expiration
    view_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    
    # Privacy settings
    is_public = db.Column(db.Boolean, default=True)  # Always true for now, but allows future extension
    allow_comments = db.Column(db.Boolean, default=False)  # Future feature
    
    # Relationship to event
    event = db.relationship('Event', backref='shared_team_ranks')
    
    def __repr__(self):
        return f'<SharedTeamRanks {self.share_id} - {self.title}>'
    
    def is_expired(self):
        """Check if this shared ranking has expired"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    def increment_view_count(self):
        """Increment the view count for this shared ranking"""
        self.view_count += 1
        db.session.commit()
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'share_id': self.share_id,
            'title': self.title,
            'description': self.description,
            'event_id': self.event_id,
            'event_name': self.event.name if self.event else None,
            'metric': self.metric,
            'created_by_team': self.created_by_team,
            'created_by_user': self.created_by_user,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'view_count': self.view_count,
            'is_active': self.is_active,
            'is_public': self.is_public,
            'is_expired': self.is_expired()
        }
    
    @classmethod
    def create_share(cls, title, event_id, metric, created_by_team, created_by_user, 
                     description=None, expires_in_days=None):
        """Create a new shared team ranking"""
        import uuid
        
        share_id = str(uuid.uuid4())
        
        # Calculate expiration if specified
        expires_at = None
        if expires_in_days:
            from datetime import timedelta
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        
        shared_ranks = cls(
            share_id=share_id,
            title=title,
            description=description,
            event_id=event_id,
            metric=metric,
            created_by_team=created_by_team,
            created_by_user=created_by_user,
            expires_at=expires_at
        )
        
        db.session.add(shared_ranks)
        db.session.commit()
        return shared_ranks
    
    @classmethod
    def get_by_share_id(cls, share_id):
        """Get shared team ranking by its share ID"""
        return cls.query.filter_by(share_id=share_id, is_active=True).first()
    
    @classmethod
    def get_user_shares(cls, team_number, username=None):
        """Get all shared team rankings created by a team/user"""
        query = cls.query.filter_by(created_by_team=team_number, is_active=True)
        if username:
            query = query.filter_by(created_by_user=username)
        return query.order_by(cls.created_at.desc()).all()


# =============================================================================
# Multi-Server Synchronization Models
# =============================================================================

class SyncServer(ConcurrentModelMixin, db.Model):
    """Model for tracking sync servers in the network"""
    __tablename__ = 'sync_servers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # Friendly name for the server
    host = db.Column(db.String(255), nullable=False)  # IP address or domain
    port = db.Column(db.Integer, default=5000)
    protocol = db.Column(db.String(10), default='https')  # http or https
    is_active = db.Column(db.Boolean, default=True)
    is_primary = db.Column(db.Boolean, default=False)  # One server is designated as primary
    last_sync = db.Column(db.DateTime, nullable=True)
    last_ping = db.Column(db.DateTime, nullable=True)
    sync_priority = db.Column(db.Integer, default=1)  # 1 = highest priority
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    
    # Server metadata
    server_version = db.Column(db.String(50), nullable=True)
    server_id = db.Column(db.String(100), nullable=True)  # Unique server identifier
    
    # Sync settings
    sync_enabled = db.Column(db.Boolean, default=True)
    sync_database = db.Column(db.Boolean, default=True)
    sync_instance_files = db.Column(db.Boolean, default=True)
    sync_config_files = db.Column(db.Boolean, default=True)
    sync_uploads = db.Column(db.Boolean, default=True)
    
    # Connection tracking
    connection_timeout = db.Column(db.Integer, default=30)
    retry_attempts = db.Column(db.Integer, default=3)
    last_error = db.Column(db.Text, nullable=True)
    error_count = db.Column(db.Integer, default=0)
    
    @property
    def base_url(self):
        """Get the full base URL for this server"""
        return f"{self.protocol}://{self.host}:{self.port}"
    
    @property
    def is_healthy(self):
        """Check if server is considered healthy"""
        if not self.is_active:
            return False
        if self.error_count > 10:  # Too many errors
            return False
        if self.last_ping:
            # If we haven't pinged in 5 minutes, consider unhealthy
            time_since_ping = datetime.utcnow() - self.last_ping
            if time_since_ping.total_seconds() > 300:
                return False
        return True
    
    def update_ping(self, success=True, error_message=None):
        """Update last ping time and error tracking"""
        self.last_ping = datetime.utcnow()
        if success:
            self.error_count = max(0, self.error_count - 1)  # Decrease error count on success
            self.last_error = None
        else:
            self.error_count += 1
            self.last_error = error_message
        db.session.commit()
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'protocol': self.protocol,
            'base_url': self.base_url,
            'is_active': self.is_active,
            'is_primary': self.is_primary,
            'is_healthy': self.is_healthy,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'last_ping': self.last_ping.isoformat() if self.last_ping else None,
            'sync_priority': self.sync_priority,
            'server_version': self.server_version,
            'server_id': self.server_id,
            'sync_settings': {
                'sync_enabled': self.sync_enabled,
                'sync_database': self.sync_database,
                'sync_instance_files': self.sync_instance_files,
                'sync_config_files': self.sync_config_files,
                'sync_uploads': self.sync_uploads
            },
            'error_count': self.error_count,
            'last_error': self.last_error
        }


class SyncLog(ConcurrentModelMixin, db.Model):
    """Model for tracking sync operations"""
    __tablename__ = 'sync_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey('sync_servers.id'), nullable=False)
    sync_type = db.Column(db.String(50), nullable=False)  # 'database', 'files', 'config', 'full'
    direction = db.Column(db.String(10), nullable=False)  # 'push', 'pull', 'bidirectional'
    status = db.Column(db.String(20), nullable=False)  # 'pending', 'in_progress', 'completed', 'failed'
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    # Sync details
    items_synced = db.Column(db.Integer, default=0)
    total_items = db.Column(db.Integer, default=0)
    bytes_transferred = db.Column(db.BigInteger, default=0)
    sync_details = db.Column(db.Text, nullable=True)  # JSON with detailed info
    
    # Relationship
    server = db.relationship('SyncServer', backref=db.backref('sync_logs', lazy=True))
    
    @property
    def duration(self):
        """Get sync duration in seconds"""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    @property
    def success(self):
        """Check if sync was successful"""
        return self.status == 'completed' and not self.error_message
    
    @property
    def progress_percentage(self):
        """Get sync progress as percentage"""
        if self.total_items > 0:
            return min(100, (self.items_synced / self.total_items) * 100)
        return 0
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'server_id': self.server_id,
            'server_name': self.server.name if self.server else None,
            'sync_type': self.sync_type,
            'direction': self.direction,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration': self.duration,
            'progress_percentage': self.progress_percentage,
            'items_synced': self.items_synced,
            'total_items': self.total_items,
            'bytes_transferred': self.bytes_transferred,
            'error_message': self.error_message,
            'sync_details': json.loads(self.sync_details) if self.sync_details else None
        }


class FileChecksum(ConcurrentModelMixin, db.Model):
    """Model for tracking file checksums to detect changes"""
    __tablename__ = 'file_checksums'
    
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String(500), nullable=False, index=True)
    checksum = db.Column(db.String(64), nullable=False)  # SHA256 hash
    file_size = db.Column(db.BigInteger, nullable=False)
    last_modified = db.Column(db.DateTime, nullable=False)
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)
    sync_status = db.Column(db.String(20), default='synced')  # 'synced', 'modified', 'new', 'deleted'
    
    @classmethod
    def get_or_create(cls, file_path, checksum, file_size, last_modified):
        """Get existing checksum record or create new one"""
        existing = cls.query.filter_by(file_path=file_path).first()
        if existing:
            # Update existing record
            if existing.checksum != checksum:
                existing.sync_status = 'modified'
            existing.checksum = checksum
            existing.file_size = file_size
            existing.last_modified = last_modified
            existing.last_checked = datetime.utcnow()
            return existing
        else:
            # Create new record
            new_record = cls(
                file_path=file_path,
                checksum=checksum,
                file_size=file_size,
                last_modified=last_modified,
                sync_status='new'
            )
            db.session.add(new_record)
            return new_record
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'file_path': self.file_path,
            'checksum': self.checksum,
            'file_size': self.file_size,
            'last_modified': self.last_modified.isoformat() if self.last_modified else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'sync_status': self.sync_status
        }


class SyncConfig(ConcurrentModelMixin, db.Model):
    """Model for storing sync configuration"""
    __tablename__ = 'sync_config'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    value = db.Column(db.Text, nullable=True)
    data_type = db.Column(db.String(20), default='string')  # 'string', 'integer', 'boolean', 'json'
    description = db.Column(db.String(255), nullable=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, nullable=True)
    
    @classmethod
    def get_value(cls, key, default=None):
        """Get configuration value by key"""
        config = cls.query.filter_by(key=key).first()
        if not config:
            return default
        
        if config.data_type == 'boolean':
            return config.value.lower() in ('true', '1', 'yes')
        elif config.data_type == 'integer':
            try:
                return int(config.value)
            except (ValueError, TypeError):
                return default
        elif config.data_type == 'json':
            try:
                return json.loads(config.value)
            except (ValueError, TypeError):
                return default
        else:
            return config.value
    
    @classmethod
    def set_value(cls, key, value, data_type='string', description=None, user_id=None):
        """Set configuration value"""
        config = cls.query.filter_by(key=key).first()
        if not config:
            config = cls(key=key)
            db.session.add(config)
        
        if data_type == 'json':
            config.value = json.dumps(value)
        else:
            config.value = str(value)
        
        config.data_type = data_type
        if description:
            config.description = description
        config.last_updated = datetime.utcnow()
        config.updated_by = user_id
        
        db.session.commit()
        return config


class DatabaseChange(ConcurrentModelMixin, db.Model):
    """Model for tracking database changes for synchronization"""
    __tablename__ = 'database_changes'
    
    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(100), nullable=False, index=True)
    record_id = db.Column(db.String(100), nullable=False, index=True)  # String to handle UUIDs
    operation = db.Column(db.String(20), nullable=False)  # 'insert', 'update', 'delete', 'soft_delete'
    change_data = db.Column(db.Text, nullable=True)  # JSON of the record data
    old_data = db.Column(db.Text, nullable=True)  # JSON of previous record data (for updates)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    sync_status = db.Column(db.String(20), default='pending')  # 'pending', 'synced', 'failed'
    created_by_server = db.Column(db.String(100), nullable=True)  # Which server created this change
    
    def __repr__(self):
        return f'<DatabaseChange {self.table_name}:{self.record_id} {self.operation}>'
    
    def to_dict(self):
        """Convert to dictionary for sync operations"""
        import json
        return {
            'id': self.id,
            'table': self.table_name,
            'record_id': self.record_id,
            'operation': self.operation,
            'data': json.loads(self.change_data) if self.change_data else None,
            'old_data': json.loads(self.old_data) if self.old_data else None,
            'timestamp': self.timestamp.isoformat(),
            'created_by_server': self.created_by_server
        }
    
    @classmethod
    def log_change(cls, table_name, record_id, operation, new_data=None, old_data=None, server_id=None):
        """Log a database change for synchronization"""
        import json
        
        change = cls(
            table_name=table_name,
            record_id=str(record_id),
            operation=operation,
            change_data=json.dumps(new_data) if new_data else None,
            old_data=json.dumps(old_data) if old_data else None,
            created_by_server=server_id
        )
        
        db.session.add(change)
        # Don't commit here - let the calling code handle the transaction
        return change


class LoginAttempt(db.Model):
    """Track failed login attempts for brute force protection"""
    __tablename__ = 'login_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False)  # Support IPv6
    username = db.Column(db.String(80), nullable=True)  # Can be null for non-existent users
    team_number = db.Column(db.Integer, nullable=True)
    attempt_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    user_agent = db.Column(db.String(500), nullable=True)
    
    @staticmethod
    def record_attempt(ip_address, username=None, team_number=None, success=False, user_agent=None):
        """Record a login attempt"""
        from sqlalchemy.exc import OperationalError
        attempt = LoginAttempt(
            ip_address=ip_address,
            username=username,
            team_number=team_number,
            success=success,
            user_agent=user_agent
        )
        db.session.add(attempt)
        try:
            db.session.commit()
            return attempt
        except OperationalError as oe:
            # Likely missing table because default DB was deleted. Try to recreate
            from app.utils.database_init import ensure_default_tables
            from flask import current_app
            db.session.rollback()
            ensure_default_tables(current_app._get_current_object())
            db.session.add(attempt)
            db.session.commit()
            return attempt
    
    @staticmethod
    def get_failed_attempts_count(ip_address, username=None, since_minutes=60):
        """Get count of failed attempts for IP/username in the last X minutes"""
        from datetime import timedelta
        
        cutoff_time = datetime.utcnow() - timedelta(minutes=since_minutes)
        
        from sqlalchemy.exc import OperationalError
        try:
            query = LoginAttempt.query.filter(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= cutoff_time
            )
        except OperationalError:
            from app.utils.database_init import ensure_default_tables
            from flask import current_app
            ensure_default_tables(current_app._get_current_object())
            query = LoginAttempt.query.filter(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= cutoff_time
            )
        
        # Optionally filter by username if provided
        if username:
            query = query.filter(LoginAttempt.username == username)
        
        return query.count()
    
    @staticmethod
    def is_blocked(ip_address, username=None, max_attempts=10, lockout_minutes=15):
        """Check if an IP/username combination is currently blocked"""
        failed_count = LoginAttempt.get_failed_attempts_count(
            ip_address, username, since_minutes=lockout_minutes
        )
        return failed_count >= max_attempts
    
    @staticmethod
    def clear_successful_attempts(ip_address, username=None):
        """Clear failed attempts after successful login"""
        from sqlalchemy.exc import OperationalError
        try:
            query = LoginAttempt.query.filter(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success == False
            )
            if username:
                query = query.filter(LoginAttempt.username == username)
            query.delete()
            db.session.commit()
        except OperationalError:
            from app.utils.database_init import ensure_default_tables
            from flask import current_app
            db.session.rollback()
            ensure_default_tables(current_app._get_current_object())
            query = LoginAttempt.query.filter(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success == False
            )
            if username:
                query = query.filter(LoginAttempt.username == username)
            query.delete()
            db.session.commit()
    
    @staticmethod 
    def cleanup_old_attempts(days_old=30):
        """Clean up old login attempts to prevent table bloat"""
        from datetime import timedelta
        
        cutoff_time = datetime.utcnow() - timedelta(days=days_old)
        
        from sqlalchemy.exc import OperationalError
        try:
            old_attempts = LoginAttempt.query.filter(
                LoginAttempt.attempt_time < cutoff_time
            ).delete()
            db.session.commit()
            return old_attempts
        except OperationalError:
            from app.utils.database_init import ensure_default_tables
            from flask import current_app
            db.session.rollback()
            ensure_default_tables(current_app._get_current_object())
            old_attempts = LoginAttempt.query.filter(
                LoginAttempt.attempt_time < cutoff_time
            ).delete()
            db.session.commit()
            return old_attempts