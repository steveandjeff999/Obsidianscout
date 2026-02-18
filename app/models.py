from datetime import datetime, timezone
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
import json
import re
import math
from app.utils.config_manager import (
    get_id_to_perm_id_mapping,
    get_scoring_element_by_perm_id,
    get_current_game_config,
    load_game_config,
)
from app.utils.concurrent_models import ConcurrentModelMixin
from sqlalchemy.orm import validates

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
    __table_args__ = (
        db.UniqueConstraint('username', 'scouting_team_number', name='uq_user_username_team'),
    )
    id = db.Column(db.Integer, primary_key=True)
    # Username is no longer globally unique; uniqueness is enforced per scouting_team_number
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(512))
    scouting_team_number = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime)
    profile_picture = db.Column(db.String(256), nullable=True, default='img/avatars/default.png')
    must_change_password = db.Column(db.Boolean, default=False)
    # Allow users to opt out of general emails and only receive password resets
    only_password_reset_emails = db.Column(db.Boolean, default=False, nullable=False)
    # If true, the user will only receive password reset emails; other emails (e.g. notifications)
    # will be suppressed for this user when set. This preserves privacy for users who only want
    # essential account emails.
    
    # Many-to-many relationship with roles
    # roles relationship will be defined after Role class to provide explicit
    # join conditions when the association table does not include DB-level FKs.
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        # Handle case where password_hash is None (user created on another server)
        if self.password_hash is None:
            return False
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
                'scouting.view', 'scouting.qr_code', 'scouting.qr_scan', 'scouting.datamatrix',
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
    # If true, apply a modern 'liquid glass' frosted/tinted look to buttons
    liquid_glass_buttons = db.Column(db.Boolean, default=False, nullable=False)
    # If true, allow spinning/rotating counters on the scouting form (admin-controlled)
    spinning_counters_enabled = db.Column(db.Boolean, default=False, nullable=False)
    # EPA data source for graphs/predictions:
    #   'scouted_only'             – use only locally scouted data (default)
    #   'scouted_with_statbotics'  – use scouted data, fill gaps with Statbotics EPA
    #   'statbotics_only'          – use Statbotics EPA exclusively
    epa_source = db.Column(db.String(30), default='scouted_only', nullable=False)
    locked_by_user_id = db.Column(db.Integer, nullable=True)
    locked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Preference for how to display offseason teams when a 99xx remapping exists.
    # '99xx' (default) -> show numeric 99xx placeholder (safe for int(team_number) usage)
    # 'letter' -> show original letter-suffix (e.g., '254B') when available
    # Note: display preference is now a client-side per-user setting stored in browser localStorage.
    # Server-side storage was removed to avoid requiring DB migrations across deployments.
    
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
        self.locked_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        db.session.commit()
    
    def unlock_account_creation(self, user):
        """Unlock account creation for this team"""
        self.account_creation_locked = False
        self.locked_by_user_id = user.id
        self.locked_at = None
        self.updated_at = datetime.now(timezone.utc)
        db.session.commit()


class StatboticsCache(ConcurrentModelMixin, db.Model):
    """Persistent cache for Statbotics EPA data.

    Stores EPA breakdown, ranks, and the year the data corresponds to so
    the app doesn't need to re-fetch from the Statbotics API on every
    request.  A configurable TTL (default 24 h) allows periodic refresh.
    """
    __tablename__ = 'statbotics_cache'
    __table_args__ = (
        db.UniqueConstraint('team_number', 'year', 'scouting_team_number',
                            name='uq_statbotics_team_year_scouting'),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_number = db.Column(db.Integer, nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    scouting_team_number = db.Column(db.Integer, nullable=True, index=True)

    # EPA breakdown
    epa_total = db.Column(db.Float, nullable=True)
    epa_auto = db.Column(db.Float, nullable=True)
    epa_teleop = db.Column(db.Float, nullable=True)
    epa_endgame = db.Column(db.Float, nullable=True)

    # Rankings
    rank_world = db.Column(db.Integer, nullable=True)
    rank_country = db.Column(db.Integer, nullable=True)

    # Metadata
    fetched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # True when the API returned no data / error for this team+year — avoids
    # repeatedly re-querying teams that don't exist on Statbotics.
    is_miss = db.Column(db.Boolean, default=False, nullable=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    DEFAULT_TTL_HOURS = 24

    @classmethod
    def get_cached(cls, team_number, year, scouting_team_number=None,
                   ttl_hours=None):
        """Return a cached row if it exists and hasn't expired."""
        if ttl_hours is None:
            ttl_hours = cls.DEFAULT_TTL_HOURS
        from datetime import timedelta
        # SQLite returns naive datetimes; use naive UTC for comparison
        cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
        row = cls.query.filter_by(
            team_number=int(team_number),
            year=int(year),
            scouting_team_number=scouting_team_number,
        ).first()
        fetched_at = row.fetched_at.replace(tzinfo=None) if (row and row.fetched_at and row.fetched_at.tzinfo) else (row.fetched_at if row else None)
        if row and fetched_at and fetched_at >= cutoff:
            return row
        return None

    @classmethod
    def upsert(cls, team_number, year, epa_dict=None,
               scouting_team_number=None):
        """Insert or update a cache entry.

        *epa_dict* should match the shape returned by
        ``statbotics_api_utils.get_statbotics_team_epa()`` (keys:
        total, auto, teleop, endgame, rank_world, rank_country) or be
        ``None`` to record a miss.
        """
        row = cls.query.filter_by(
            team_number=int(team_number),
            year=int(year),
            scouting_team_number=scouting_team_number,
        ).first()
        if row is None:
            row = cls(
                team_number=int(team_number),
                year=int(year),
                scouting_team_number=scouting_team_number,
            )
            db.session.add(row)
        if epa_dict:
            row.epa_total = epa_dict.get('total')
            row.epa_auto = epa_dict.get('auto')
            row.epa_teleop = epa_dict.get('teleop')
            row.epa_endgame = epa_dict.get('endgame')
            row.rank_world = epa_dict.get('rank_world')
            row.rank_country = epa_dict.get('rank_country')
            row.is_miss = False
        else:
            row.epa_total = None
            row.epa_auto = None
            row.epa_teleop = None
            row.epa_endgame = None
            row.rank_world = None
            row.rank_country = None
            row.is_miss = True
        row.fetched_at = datetime.now(timezone.utc)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return row

    def to_epa_dict(self):
        """Return the data in the standard EPA dict format."""
        if self.is_miss:
            return None
        return {
            'total': self.epa_total,
            'auto': self.epa_auto,
            'teleop': self.epa_teleop,
            'endgame': self.epa_endgame,
            'rank_world': self.rank_world,
            'rank_country': self.rank_country,
        }

    def __repr__(self):
        return f'<StatboticsCache team={self.team_number} year={self.year} total={self.epa_total}>'


class TbaOprCache(ConcurrentModelMixin, db.Model):
    """Persistent cache for TBA OPR data.

    Stores OPR, DPR, and CCWM values for teams at specific events.
    A configurable TTL (default 15 min) allows periodic refresh.
    """
    __tablename__ = 'tba_opr_cache'
    __table_args__ = (
        db.UniqueConstraint('team_number', 'event_key', 'scouting_team_number',
                            name='uq_tba_opr_team_event_scouting'),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_number = db.Column(db.Integer, nullable=False, index=True)
    event_key = db.Column(db.String(20), nullable=False, index=True)
    scouting_team_number = db.Column(db.Integer, nullable=True, index=True)

    # OPR breakdown
    opr = db.Column(db.Float, nullable=True)
    dpr = db.Column(db.Float, nullable=True)
    ccwm = db.Column(db.Float, nullable=True)

    # Metadata
    fetched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # True when the API returned no data / error for this team+event — avoids
    # repeatedly re-querying teams that don't exist.
    is_miss = db.Column(db.Boolean, default=False, nullable=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    DEFAULT_TTL_MINUTES = 15

    @classmethod
    def get_cached(cls, team_number, event_key, scouting_team_number=None,
                   ttl_minutes=None):
        """Return a cached row if it exists and hasn't expired."""
        if ttl_minutes is None:
            ttl_minutes = cls.DEFAULT_TTL_MINUTES
        from datetime import timedelta
        # SQLite returns naive datetimes; use naive UTC for comparison
        cutoff = datetime.utcnow() - timedelta(minutes=ttl_minutes)
        row = cls.query.filter_by(
            team_number=int(team_number),
            event_key=event_key,
            scouting_team_number=scouting_team_number,
        ).first()
        # Strip tzinfo from fetched_at in case it was stored as aware
        fetched_at = row.fetched_at.replace(tzinfo=None) if (row and row.fetched_at and row.fetched_at.tzinfo) else (row.fetched_at if row else None)
        if row and fetched_at and fetched_at >= cutoff:
            return row
        return None

    @classmethod
    def upsert(cls, team_number, event_key, opr_dict=None,
               scouting_team_number=None):
        """Insert or update a cache entry.

        *opr_dict* should match the shape returned by
        ``tba_api_utils.get_tba_team_opr()`` (keys:
        total, opr, dpr, ccwm) or be ``None`` to record a miss.
        """
        row = cls.query.filter_by(
            team_number=int(team_number),
            event_key=event_key,
            scouting_team_number=scouting_team_number,
        ).first()
        if row is None:
            row = cls(
                team_number=int(team_number),
                event_key=event_key,
                scouting_team_number=scouting_team_number,
            )
            db.session.add(row)
        if opr_dict:
            row.opr = opr_dict.get('opr')
            row.dpr = opr_dict.get('dpr')
            row.ccwm = opr_dict.get('ccwm')
            row.is_miss = False
        else:
            row.opr = None
            row.dpr = None
            row.ccwm = None
            row.is_miss = True
        row.fetched_at = datetime.now(timezone.utc)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return row

    def to_opr_dict(self):
        """Return the data in the standard OPR dict format."""
        if self.is_miss:
            return None
        return {
            'total': self.opr,  # Use OPR as the total value
            'opr': self.opr,
            'dpr': self.dpr,
            'ccwm': self.ccwm,
        }

    def __repr__(self):
        return f'<TbaOprCache team={self.team_number} event={self.event_key} opr={self.opr}>'


class Team(ConcurrentModelMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_number = db.Column(db.Integer, nullable=False)
    team_name = db.Column(db.String(100))
    location = db.Column(db.String(100))
    scouting_team_number = db.Column(db.Integer, nullable=True)
    # Per-team starting points used across all events when the team has too few scouted matches
    starting_points = db.Column(db.Float, nullable=True, default=0)
    starting_points_threshold = db.Column(db.Integer, nullable=True, default=2)
    starting_points_enabled = db.Column(db.Boolean, nullable=False, default=False)
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
    timezone = db.Column(db.String(50), nullable=True)  # IANA timezone like 'America/Denver' or 'America/New_York'
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    year = db.Column(db.Integer, nullable=False)
    scouting_team_number = db.Column(db.Integer, nullable=True)
    schedule_offset = db.Column(db.Integer, nullable=True)  # Current schedule offset in minutes (positive = behind, negative = ahead)
    matches = db.relationship('Match', backref='event', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"Event: {self.name} ({self.year})"

    @validates('code')
    def _validate_code(self, key, value):
        if value is None:
            return value
        try:
            return value.upper()
        except Exception:
            return value

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
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    scheduled_time = db.Column(db.DateTime, nullable=True, index=True)  # Scheduled match start time from API (stored in UTC)
    predicted_time = db.Column(db.DateTime, nullable=True)  # Predicted start time from TBA (stored in UTC)
    actual_time = db.Column(db.DateTime, nullable=True)  # When the match actually started (UTC)
    display_match_number = db.Column(db.String(20), nullable=True)  # Human-friendly display like '1-1' for playoffs
    scouting_team_number = db.Column(db.Integer, nullable=True)
    scouting_data = db.relationship('ScoutingData', backref='match', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"Match {self.match_type} {self.match_number}"
    
    @property
    def red_teams(self):
        if not self.red_alliance:
            return []
        try:
            return [int(team_num.strip()) for team_num in str(self.red_alliance).split(',') if team_num.strip().isdigit()]
        except Exception:
            return []
    
    @property
    def blue_teams(self):
        if not self.blue_alliance:
            return []
        try:
            return [int(team_num.strip()) for team_num in str(self.blue_alliance).split(',') if team_num.strip().isdigit()]
        except Exception:
            return []
    
    # Add a method to get team objects
    def get_teams(self):
        """Return all Team objects participating in this match"""
        team_numbers = self.red_teams + self.blue_teams
        return Team.query.filter(Team.team_number.in_(team_numbers)).all()


class StrategyShare(db.Model):
    """Public share tokens for match strategy analysis.

    A short-lived or permanent token can be created by an authorized user and
    distributed as a URL that allows non-authenticated users to view the
    strategy analysis for a specific match.
    """
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    revoked = db.Column(db.Boolean, default=False)
    # Relationship to match for convenient access
    match = db.relationship('Match', backref=db.backref('strategy_shares', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<StrategyShare match={self.match_id} token={self.token[:8]}... revoked={self.revoked}>'
    

class ScoutingData(ConcurrentModelMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    scouting_team_number = db.Column(db.Integer, nullable=True)
    scout_name = db.Column(db.String(50))
    scout_id = db.Column(db.Integer, nullable=True)
    scouting_station = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
        game_config = get_current_game_config() or {}

        # Prefer the scouting team's config when available so metric math matches their setup
        if hasattr(self, 'scouting_team_number') and self.scouting_team_number:
            team_config = load_game_config(team_number=self.scouting_team_number)
            if team_config:
                game_config = team_config
        
        # Check if this is a metric ID (not a formula)
        metric_config = None
        for metric in game_config.get('data_analysis', {}).get('key_metrics', []):
            if metric.get('id') == formula_or_id:
                metric_config = metric
                formula = metric.get('formula')
                break
        
        # Check for standard metric IDs even if not in key_metrics
        standard_metric_ids = ['tot', 'apt', 'tpt', 'ept']
        if not metric_config and formula_or_id in standard_metric_ids:
            # Create a dummy metric config for standard metrics
            metric_config = {'id': formula_or_id, 'formula': formula_or_id}
            formula = formula_or_id
        
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
            id_map = get_id_to_perm_id_mapping(game_config)
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
            
            # NOW calculate derived metrics after actual form data is loaded
            # This allows formulas to reference auto_points, teleop_points, etc.
            try:
                auto_pts = self._calculate_auto_points_dynamic(local_dict, game_config)
                teleop_pts = self._calculate_teleop_points_dynamic(local_dict, game_config)
                endgame_pts = self._calculate_endgame_points_dynamic(local_dict, game_config)
                
                local_dict['auto_points'] = auto_pts
                local_dict['teleop_points'] = teleop_pts
                local_dict['endgame_points'] = endgame_pts
                local_dict['total_points'] = auto_pts + teleop_pts + endgame_pts
            except Exception:
                # If calculation fails, provide zeros to prevent formula errors
                local_dict['auto_points'] = 0
                local_dict['teleop_points'] = 0
                local_dict['endgame_points'] = 0
                local_dict['total_points'] = 0
            
            # Get the metric ID if we have it
            metric_id = None
            if metric_config:
                metric_id = metric_config.get('id')
            else:
                # Try to find the metric ID from the formula
                metric_id = self._find_metric_id_by_formula(formula, game_config)
            
            if metric_id:
                # Call the appropriate handler method for this metric
                result = self._calculate_specific_metric(metric_id, formula, local_dict, game_config)
                # Debug logging for metric calculations
                try:
                    from flask import current_app
                    current_app.logger.debug(f"ScoutingData {self.id} metric {metric_id} -> {result}")
                except Exception:
                    pass
                return result
            
            # For other formulas or if specific handler not found, use general evaluation
            id_map = get_id_to_perm_id_mapping(game_config)
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
    
    def _calculate_specific_metric(self, metric_id, formula, local_dict, game_config):
        """Calculate a specific metric based on its ID using the provided game configuration."""
        game_config = game_config or get_current_game_config() or {}
        
        if metric_id == 'tot':
            # Calculate total points dynamically based on components marked with is_total_component=true
            total_points = 0
            key_metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
            
            # If we have key metrics with total components, use them
            if key_metrics:
                for metric in key_metrics:
                    if metric.get('is_total_component'):
                        total_points += self.calculate_metric(metric['id'])
                if total_points > 0:  # Only return if we found component metrics
                    return total_points
            
            # Fallback: Calculate total points using dynamic period calculations
            auto_pts = self._calculate_auto_points_dynamic(local_dict, game_config)
            teleop_pts = self._calculate_teleop_points_dynamic(local_dict, game_config)
            endgame_pts = self._calculate_endgame_points_dynamic(local_dict, game_config)
            return auto_pts + teleop_pts + endgame_pts
        
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
        
        # Fallback for common metric IDs when no key_metrics are defined
        elif not game_config.get('data_analysis', {}).get('key_metrics', []):
            if metric_id == 'apt':  # auto points
                return self._calculate_auto_points_dynamic(local_dict, game_config)
            elif metric_id == 'tpt':  # teleop points
                return self._calculate_teleop_points_dynamic(local_dict, game_config)
            elif metric_id == 'ept':  # endgame points
                return self._calculate_endgame_points_dynamic(local_dict, game_config)
        
        # If not auto-generated or no special handling needed, use the formula directly
        return self._evaluate_formula(formula, local_dict)
    
    def _calculate_auto_points_dynamic(self, local_dict, game_config=None):
        """Dynamically calculate auto period points based on game pieces and scoring elements"""
        if not game_config:
            game_config = get_current_game_config()
            
        points = 0
        
        # Helper function to safely convert to numeric value
        def safe_numeric(value, default=0):
            try:
                if isinstance(value, (int, float)):
                    return value
                elif isinstance(value, str):
                    return float(value) if '.' in value else int(value)
                elif isinstance(value, bool):
                    return 1 if value else 0
                else:
                    return default
            except (ValueError, TypeError):
                return default
        
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
                    count = safe_numeric(local_dict.get(element_id, 0))
                    points += count * element.get('points', 0)
                elif element.get('type') == 'select':
                    # For select elements with point values per option
                    selected = local_dict.get(element_id)
                    if isinstance(element.get('points'), dict) and selected in element.get('points'):
                        points += element.get('points').get(selected, 0)
                elif element.get('type') == 'multiple_choice':
                    # For multiple choice elements, find the selected option and get its points
                    selected = local_dict.get(element_id)
                    if selected:
                        for option in element.get('options', []):
                            if isinstance(option, dict):
                                if option.get('name') == selected:
                                    points += safe_numeric(option.get('points', 0))
                                    break
                            elif option == selected:
                                # Fallback for simple string options
                                points += element.get('points', 0)
                                break
            
            # Handle game pieces - only if this element doesn't already have direct points
            elif element.get('game_piece_id'):
                game_piece_id = element.get('game_piece_id')
                for game_piece in game_config.get('game_pieces', []):
                    if game_piece.get('id') == game_piece_id:
                        # Add points for this game piece
                        count = safe_numeric(local_dict.get(element_id, 0))
                        points += count * game_piece.get('auto_points', 0)
                        break
        
        return int(points)
    
    def _calculate_teleop_points_dynamic(self, local_dict, game_config=None):
        """Dynamically calculate teleop period points based on game pieces and scoring elements"""
        if not game_config:
            game_config = get_current_game_config()
            
        points = 0
        
        # Helper function to safely convert to numeric value
        def safe_numeric(value, default=0):
            try:
                if isinstance(value, (int, float)):
                    return value
                elif isinstance(value, str):
                    return float(value) if '.' in value else int(value)
                elif isinstance(value, bool):
                    return 1 if value else 0
                else:
                    return default
            except (ValueError, TypeError):
                return default
        
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
                    count = safe_numeric(local_dict.get(element_id, 0))
                    points += count * element.get('points', 0)
                elif element.get('type') == 'select':
                    # For select elements with point values per option
                    selected = local_dict.get(element_id)
                    if isinstance(element.get('points'), dict) and selected in element.get('points'):
                        points += element.get('points').get(selected, 0)
                elif element.get('type') == 'multiple_choice':
                    # For multiple choice elements, find the selected option and get its points
                    selected = local_dict.get(element_id)
                    if selected:
                        for option in element.get('options', []):
                            if isinstance(option, dict):
                                if option.get('name') == selected:
                                    points += safe_numeric(option.get('points', 0))
                                    break
                            elif option == selected:
                                # Fallback for simple string options
                                points += element.get('points', 0)
                                break
            
            # Handle game pieces - only if this element doesn't already have direct points
            elif element.get('game_piece_id'):
                game_piece_id = element.get('game_piece_id')
                for game_piece in game_config.get('game_pieces', []):
                    if game_piece.get('id') == game_piece_id:
                        # Check if this is a bonus scoring element
                        if element.get('bonus'):
                            count = safe_numeric(local_dict.get(element_id, 0))
                            points += count * game_piece.get('bonus_points', 0)
                        else:
                            # Normal teleop scoring
                            count = safe_numeric(local_dict.get(element_id, 0))
                            points += count * game_piece.get('teleop_points', 0)
                        break
        
        return int(points)
    
    def _calculate_endgame_points_dynamic(self, local_dict, game_config=None):
        """Dynamically calculate endgame period points based on scoring elements"""
        if not game_config:
            game_config = get_current_game_config()
            
        points = 0
        
        # Helper function to safely convert to numeric value
        def safe_numeric(value, default=0):
            try:
                if isinstance(value, (int, float)):
                    return value
                elif isinstance(value, str):
                    return float(value) if '.' in value else int(value)
                elif isinstance(value, bool):
                    return 1 if value else 0
                else:
                    return default
            except (ValueError, TypeError):
                return default
        
        # Add points from endgame period scoring elements
        for element in game_config.get('endgame_period', {}).get('scoring_elements', []):
            element_id = element.get('id')
            # Debug: show element and value
            try:
                from flask import current_app
                current_app.logger.debug(f"Endgame calc: element_id={element_id}, value={local_dict.get(element_id)}")
            except Exception:
                pass
            if element_id not in local_dict:
                continue
                
            if element.get('type') == 'boolean' and element.get('points'):
                # For boolean elements, add points if true
                if local_dict.get(element_id):
                    points += element.get('points', 0)
            elif element.get('type') == 'counter' and element.get('points'):
                # For counter elements, multiply by points
                count = safe_numeric(local_dict.get(element_id, 0))
                points += count * element.get('points', 0)
            elif element.get('type') == 'select' and isinstance(element.get('points'), dict):
                # For select elements with point values per option
                selected = local_dict.get(element_id)
                if selected in element.get('points', {}):
                    points += element.get('points', {}).get(selected, 0)
            elif element.get('type') == 'multiple_choice':
                # For multiple choice elements, find the selected option and get its points
                selected = local_dict.get(element_id)
                if selected:
                    for option in element.get('options', []):
                        if isinstance(option, dict):
                            if option.get('name') == selected:
                                points += safe_numeric(option.get('points', 0))
                                break
                        elif option == selected:
                            # Fallback for simple string options
                            points += element.get('points', 0)
                            break
        
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
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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


class DeclinedEntry(TeamListEntry):
    """Teams explicitly declined from recommendations by the user.

    These teams will be excluded from the recommendations list but can still be
    manually assigned to alliances. The entry supports an optional reason and
    is scoped by scouting_team_number like the other list entries.
    """
    __mapper_args__ = {
        'polymorphic_identity': 'declined'
    }

class WantListEntry(TeamListEntry):
    """Teams that are desired for alliance selection with a priority ranking.
    
    Teams on the want list receive a boost in recommendations based on their rank.
    Higher ranks (lower numbers, e.g., 1, 2, 3) receive larger boosts.
    This helps prioritize preferred alliance partners during selection.
    """
    __tablename__ = None  # Use parent table
    rank = db.Column(db.Integer, nullable=False, default=999)  # Lower number = higher priority
    
    __mapper_args__ = {
        'polymorphic_identity': 'want_list'
    }

class AllianceSelection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alliance_number = db.Column(db.Integer, nullable=False)  # 1-8 for 8 alliances
    captain = db.Column(db.Integer, db.ForeignKey('team.id'))  # Captain team
    first_pick = db.Column(db.Integer, db.ForeignKey('team.id'))  # First pick
    second_pick = db.Column(db.Integer, db.ForeignKey('team.id'))  # Second pick
    third_pick = db.Column(db.Integer, db.ForeignKey('team.id'))  # Third pick (backup)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
            'scouting_team_number': self.scouting_team_number,
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
            scouting_team_number=data_dict.get('scouting_team_number'),
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
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    background_image = db.Column(db.String(256), nullable=True)  # Path or filename of custom background

    match = db.relationship('Match', backref=db.backref('strategy_drawing', uselist=False, cascade='all, delete-orphan'))

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


class QualitativeScoutingData(db.Model):
    """Model to store qualitative scouting observations for entire alliances in a match"""
    __tablename__ = 'qualitative_scouting_data'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    scouting_team_number = db.Column(db.Integer, nullable=True)
    scout_name = db.Column(db.String(50), nullable=False)
    scout_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Alliance being scouted ('red', 'blue', or 'both')
    alliance_scouted = db.Column(db.String(10), nullable=False)
    
    # JSON data for team notes and rankings
    # Structure: {
    #   'red': {
    #     'team_1234': {'notes': 'text', 'ranking': 3},
    #     'team_5678': {'notes': 'text', 'ranking': 1},
    #     ...
    #   },
    #   'blue': {
    #     'team_9012': {'notes': 'text', 'ranking': 2},
    #     ...
    #   }
    # }
    data_json = db.Column(db.Text, nullable=False)
    
    # Relationships
    match = db.relationship('Match', backref=db.backref('qualitative_scouting_data', lazy=True))
    
    @property
    def scout(self):
        try:
            return User.query.get(self.scout_id) if self.scout_id else None
        except Exception:
            return None
    
    def __repr__(self):
        return f"<QualitativeScoutingData Match {self.match_id} Alliance {self.alliance_scouted}>"
    
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
            'match_id': self.match_id,
            'scouting_team_number': self.scouting_team_number,
            'scout_name': self.scout_name,
            'scout_id': self.scout_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'alliance_scouted': self.alliance_scouted,
            'data': self.data
        }


# ======== SCOUTING ALLIANCE MODELS ========

class ScoutingAlliance(db.Model):
    """Model to represent a scouting alliance between teams"""
    __tablename__ = 'scouting_alliance'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
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
    
    def get_all_team_numbers(self):
        """Get list of all team numbers including members and game_config_team.
        This is useful for data filtering where data may be stored under game_config_team.
        """
        team_numbers = set(self.get_member_team_numbers())
        if self.game_config_team:
            team_numbers.add(self.game_config_team)
        return list(team_numbers)
    
    def is_member(self, team_number):
        """Check if a team is a member of this alliance"""
        return team_number in self.get_member_team_numbers()
    
    def get_shared_events(self):
        """Get events this alliance is collaborating on by extracting from member game configs"""
        import json
        from app.utils.config_manager import load_game_config
        
        event_codes = set()
        
        # First, check the alliance's shared game config
        if self.shared_game_config:
            try:
                config = json.loads(self.shared_game_config)
                event_code = config.get('current_event_code', '').strip().upper()
                if event_code:
                    event_codes.add(event_code)
            except (json.JSONDecodeError, AttributeError):
                pass
        
        # Check the game_config_team's config (this is the authoritative source)
        if self.game_config_team:
            try:
                game_config_team_config = load_game_config(self.game_config_team)
                if isinstance(game_config_team_config, dict):
                    event_code = game_config_team_config.get('current_event_code', '').strip().upper()
                    if event_code:
                        event_codes.add(event_code)
            except Exception:
                pass
        
        # Then collect event codes from all active alliance members' configs
        for member in self.get_active_members():
            try:
                member_config = load_game_config(member.team_number)
                if isinstance(member_config, dict):
                    event_code = member_config.get('current_event_code', '').strip().upper()
                    if event_code:
                        event_codes.add(event_code)
            except Exception:
                # Skip if member config can't be loaded
                continue
        
        return list(event_codes)
    
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
        has_game_config = (self.shared_game_config is not None and self.shared_game_config.strip() != '') or self.game_config_team is not None
        has_pit_config = (self.shared_pit_config is not None and self.shared_pit_config.strip() != '') or self.pit_config_team is not None
        return has_game_config and has_pit_config
    
    def update_config_status(self):
        """Update config_status based on current configuration state"""
        if self.is_config_complete():
            self.config_status = 'configured'
        else:
            self.config_status = 'pending'
        return self.config_status

class ScoutingAllianceMember(db.Model):
    """Model to represent members of a scouting alliance"""
    __tablename__ = 'scouting_alliance_member'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    team_number = db.Column(db.Integer, nullable=False)
    team_name = db.Column(db.String(100))
    role = db.Column(db.String(50), default='member')  # 'admin', 'member'
    status = db.Column(db.String(50), default='pending')  # 'pending', 'accepted', 'declined'
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    invited_by = db.Column(db.Integer, nullable=True)  # Team number that sent the invite
    # Data sharing status - when False, other teams cannot sync NEW data from this team
    is_data_sharing_active = db.Column(db.Boolean, default=True)
    data_sharing_deactivated_at = db.Column(db.DateTime, nullable=True)
    
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Team number that added this event (nullable for older records)
    added_by = db.Column(db.Integer, nullable=True)
    
    def __repr__(self):
        return f'<AllianceEvent {self.event_code} for Alliance {self.alliance_id}>'

    @validates('event_code')
    def _validate_event_code(self, key, value):
        if value is None:
            return value
        try:
            return value.upper()
        except Exception:
            return value

class ScoutingAllianceSync(db.Model):
    """Model to track data synchronization between alliance members"""
    __tablename__ = 'scouting_alliance_sync'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    from_team_number = db.Column(db.Integer, nullable=False)
    to_team_number = db.Column(db.Integer, nullable=False)
    data_type = db.Column(db.String(50), nullable=False)  # 'scouting_data', 'pit_data', 'chat'
    data_count = db.Column(db.Integer, default=0)
    last_sync = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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


class AllianceSharedScoutingData(db.Model):
    """Model to store copies of scouting data shared with alliances.
    
    When data is synced to an alliance, a copy is made here so that deleting
    the original doesn't affect other alliance members' access to the data.
    """
    __tablename__ = 'alliance_shared_scouting_data'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    
    # Reference to original data (may be null if original was deleted)
    original_scouting_data_id = db.Column(db.Integer, nullable=True)
    
    # Team that originally scouted this data (the "owner")
    source_scouting_team_number = db.Column(db.Integer, nullable=False)
    
    # Copy of the scouting data fields
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    scout_name = db.Column(db.String(50))
    scout_id = db.Column(db.Integer, nullable=True)
    scouting_station = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    alliance = db.Column(db.String(10))  # 'red' or 'blue'
    data_json = db.Column(db.Text, nullable=False)  # JSON data based on game config
    
    # Metadata for alliance sharing
    shared_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    shared_by_team = db.Column(db.Integer, nullable=False)  # Team that shared this
    last_edited_by_team = db.Column(db.Integer, nullable=True)  # Last team to edit (for admin edits)
    last_edited_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)  # Can be set to False if source team removes from alliance
    
    # Relationships
    alliance_rel = db.relationship('ScoutingAlliance', backref='shared_scouting_data')
    match = db.relationship('Match', backref=db.backref('alliance_shared_scouting_data', lazy=True, cascade='all, delete-orphan'))
    team = db.relationship('Team')
    
    def __repr__(self):
        return f'<AllianceSharedScoutingData Alliance {self.alliance_id} Team {self.team.team_number if self.team else "?"} Match {self.match.match_number if self.match else "?"}>'
    
    @property
    def data(self):
        """Get data as a Python dictionary"""
        return json.loads(self.data_json)
    
    @data.setter
    def data(self, value):
        """Store data as JSON string"""
        self.data_json = json.dumps(value)
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'alliance_id': self.alliance_id,
            'original_id': self.original_scouting_data_id,
            'source_team': self.source_scouting_team_number,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'team_number': self.team.team_number if self.team else None,
            'match_number': self.match.match_number if self.match else None,
            'match_type': self.match.match_type if self.match else None,
            'event_code': self.match.event.code if self.match and self.match.event else None,
            'scout_name': self.scout_name,
            'alliance': self.alliance,
            'data': self.data,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'shared_at': self.shared_at.isoformat() if self.shared_at else None,
            'shared_by_team': self.shared_by_team,
            'last_edited_by_team': self.last_edited_by_team,
            'last_edited_at': self.last_edited_at.isoformat() if self.last_edited_at else None,
            'is_active': self.is_active
        }
    
    @classmethod
    def create_from_scouting_data(cls, scouting_data, alliance_id, shared_by_team):
        """Create a shared copy from original ScoutingData"""
        return cls(
            alliance_id=alliance_id,
            original_scouting_data_id=scouting_data.id,
            source_scouting_team_number=scouting_data.scouting_team_number,
            match_id=scouting_data.match_id,
            team_id=scouting_data.team_id,
            scout_name=scouting_data.scout_name,
            scout_id=scouting_data.scout_id,
            scouting_station=scouting_data.scouting_station,
            timestamp=scouting_data.timestamp,
            alliance=scouting_data.alliance,
            data_json=scouting_data.data_json,
            shared_by_team=shared_by_team
        )
    
    @property
    def scouting_team_number(self):
        """Alias for source_scouting_team_number to match ScoutingData interface."""
        return self.source_scouting_team_number
    
    def calculate_metric(self, formula_or_id):
        """Calculate metrics based on formulas or metric IDs defined in game config.
        
        This is a proxy method that uses ScoutingData's implementation by creating
        a temporary ScoutingData-like object with our data.
        """
        # Create a temporary ScoutingData object to leverage its calculate_metric logic
        temp_data = ScoutingData(
            match_id=self.match_id,
            team_id=self.team_id,
            scouting_team_number=self.source_scouting_team_number,
            data_json=self.data_json
        )
        return temp_data.calculate_metric(formula_or_id)
    
    def _calculate_auto_points_dynamic(self, local_dict, game_config=None):
        """Proxy method that delegates to ScoutingData's implementation."""
        temp_data = ScoutingData(
            match_id=self.match_id,
            team_id=self.team_id,
            scouting_team_number=self.source_scouting_team_number,
            data_json=self.data_json
        )
        return temp_data._calculate_auto_points_dynamic(local_dict, game_config)
    
    def _calculate_teleop_points_dynamic(self, local_dict, game_config=None):
        """Proxy method that delegates to ScoutingData's implementation."""
        temp_data = ScoutingData(
            match_id=self.match_id,
            team_id=self.team_id,
            scouting_team_number=self.source_scouting_team_number,
            data_json=self.data_json
        )
        return temp_data._calculate_teleop_points_dynamic(local_dict, game_config)
    
    def _calculate_endgame_points_dynamic(self, local_dict, game_config=None):
        """Proxy method that delegates to ScoutingData's implementation."""
        temp_data = ScoutingData(
            match_id=self.match_id,
            team_id=self.team_id,
            scouting_team_number=self.source_scouting_team_number,
            data_json=self.data_json
        )
        return temp_data._calculate_endgame_points_dynamic(local_dict, game_config)
    
    def _evaluate_formula(self, formula, local_dict):
        """Proxy method that delegates to ScoutingData's implementation."""
        temp_data = ScoutingData(
            match_id=self.match_id,
            team_id=self.team_id,
            scouting_team_number=self.source_scouting_team_number,
            data_json=self.data_json
        )
        return temp_data._evaluate_formula(formula, local_dict)


class AllianceSharedPitData(db.Model):
    """Model to store copies of pit scouting data shared with alliances.
    
    When pit data is synced to an alliance, a copy is made here so that deleting
    the original doesn't affect other alliance members' access to the data.
    """
    __tablename__ = 'alliance_shared_pit_data'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    
    # Reference to original data (may be null if original was deleted)
    original_pit_data_id = db.Column(db.Integer, nullable=True)
    
    # Team that originally scouted this data (the "owner")
    source_scouting_team_number = db.Column(db.Integer, nullable=False)
    
    # Copy of the pit scouting data fields
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    scout_name = db.Column(db.String(50), nullable=False)
    scout_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    data_json = db.Column(db.Text, nullable=False)  # JSON data
    local_id = db.Column(db.String(36), nullable=True)  # UUID for tracking
    
    # Metadata for alliance sharing
    shared_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    shared_by_team = db.Column(db.Integer, nullable=False)  # Team that shared this
    last_edited_by_team = db.Column(db.Integer, nullable=True)  # Last team to edit (for admin edits)
    last_edited_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)  # Can be set to False if source team removes from alliance
    
    # Relationships
    alliance_rel = db.relationship('ScoutingAlliance', backref='shared_pit_data')
    team = db.relationship('Team')
    event = db.relationship('Event')
    
    def __repr__(self):
        return f'<AllianceSharedPitData Alliance {self.alliance_id} Team {self.team.team_number if self.team else "?"}>'
    
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
            'alliance_id': self.alliance_id,
            'original_id': self.original_pit_data_id,
            'source_team': self.source_scouting_team_number,
            'team_id': self.team_id,
            'team_number': self.team.team_number if self.team else None,
            'event_id': self.event_id,
            'scout_name': self.scout_name,
            'data': self.data,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'shared_at': self.shared_at.isoformat() if self.shared_at else None,
            'shared_by_team': self.shared_by_team,
            'last_edited_by_team': self.last_edited_by_team,
            'last_edited_at': self.last_edited_at.isoformat() if self.last_edited_at else None,
            'is_active': self.is_active
        }
    
    @classmethod
    def create_from_pit_data(cls, pit_data, alliance_id, shared_by_team):
        """Create a shared copy from original PitScoutingData"""
        import uuid
        return cls(
            alliance_id=alliance_id,
            original_pit_data_id=pit_data.id,
            source_scouting_team_number=pit_data.scouting_team_number,
            team_id=pit_data.team_id,
            event_id=pit_data.event_id,
            scout_name=pit_data.scout_name,
            scout_id=pit_data.scout_id,
            timestamp=pit_data.timestamp,
            data_json=pit_data.data_json,
            local_id=str(uuid.uuid4()),
            shared_by_team=shared_by_team
        )


class AllianceDeletedData(db.Model):
    """Track data that was deleted from an alliance by admin to prevent re-sync.
    
    When alliance admin deletes shared data, we record it here so that
    future syncs don't re-add the same data.
    """
    __tablename__ = 'alliance_deleted_data'
    
    id = db.Column(db.Integer, primary_key=True)
    alliance_id = db.Column(db.Integer, db.ForeignKey('scouting_alliance.id'), nullable=False)
    data_type = db.Column(db.String(20), nullable=False)  # 'scouting' or 'pit'
    
    # Identify the data that was deleted (match these fields to prevent re-sync)
    match_id = db.Column(db.Integer, nullable=True)  # For scouting data
    team_id = db.Column(db.Integer, nullable=False)
    alliance_color = db.Column(db.String(10), nullable=True)  # 'red' or 'blue' for scouting
    source_scouting_team_number = db.Column(db.Integer, nullable=False)
    
    # Metadata
    deleted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    deleted_by_team = db.Column(db.Integer, nullable=False)
    
    # Relationship
    alliance_rel = db.relationship('ScoutingAlliance', backref='deleted_data_records')
    
    def __repr__(self):
        return f'<AllianceDeletedData Alliance {self.alliance_id} Type {self.data_type}>'
    
    @classmethod
    def is_deleted(cls, alliance_id, data_type, match_id, team_id, alliance_color, source_team):
        """Check if this data was previously deleted from the alliance"""
        query = cls.query.filter_by(
            alliance_id=alliance_id,
            data_type=data_type,
            team_id=team_id,
            source_scouting_team_number=source_team
        )
        if data_type == 'scouting':
            query = query.filter_by(match_id=match_id, alliance_color=alliance_color)
        return query.first() is not None
    
    @classmethod
    def mark_deleted(cls, alliance_id, data_type, match_id, team_id, alliance_color, source_team, deleted_by):
        """Mark data as deleted to prevent re-sync"""
        # Check if already marked
        existing = cls.query.filter_by(
            alliance_id=alliance_id,
            data_type=data_type,
            team_id=team_id,
            source_scouting_team_number=source_team
        )
        if data_type == 'scouting':
            existing = existing.filter_by(match_id=match_id, alliance_color=alliance_color)
        
        if existing.first():
            return  # Already marked
        
        record = cls(
            alliance_id=alliance_id,
            data_type=data_type,
            match_id=match_id,
            team_id=team_id,
            alliance_color=alliance_color,
            source_scouting_team_number=source_team,
            deleted_by_team=deleted_by
        )
        db.session.add(record)


class ScoutingDirectMessage(db.Model):
    """Model for direct (user-to-user) messages between users within the same
    scouting team or allied teams.
    """
    __tablename__ = 'scouting_direct_message'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)  # User.id from users bind
    recipient_id = db.Column(db.Integer, nullable=False)
    sender_team_number = db.Column(db.Integer, nullable=True)
    recipient_team_number = db.Column(db.Integer, nullable=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_read = db.Column(db.Boolean, default=False)
    offline_id = db.Column(db.String(36), nullable=True)

    def __repr__(self):
        return f'<DirectMessage {self.id} from {self.sender_id} to {self.recipient_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'recipient_id': self.recipient_id,
            'sender_team_number': self.sender_team_number,
            'recipient_team_number': self.recipient_team_number,
            'body': self.body,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_read': self.is_read,
            'offline_id': self.offline_id
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
            status.deactivated_at = datetime.now(timezone.utc)
        
        status.active_alliance_id = alliance_id
        status.is_alliance_mode_active = True
        status.activated_at = datetime.now(timezone.utc)
        status.deactivated_at = None
        db.session.commit()
        return status
    
    @classmethod
    def deactivate_alliance_for_team(cls, team_number, remove_shared_data=False):
        """Deactivate alliance mode for a team.
        
        Args:
            team_number: The team number to deactivate
            remove_shared_data: If True, removes all shared data from this team from the alliance
        """
        from app import db
        
        status = cls.query.filter_by(team_number=team_number).first()
        if status:
            alliance_id = status.active_alliance_id
            
            # Set is_data_sharing_active to False for this team's membership
            # This prevents other teams from syncing NEW data from this team
            if alliance_id:
                member = ScoutingAllianceMember.query.filter_by(
                    alliance_id=alliance_id,
                    team_number=team_number
                ).first()
                if member:
                    member.is_data_sharing_active = False
                    member.data_sharing_deactivated_at = datetime.now(timezone.utc)
                
                # Optionally remove all shared data from this team
                if remove_shared_data:
                    # Remove scouting data shared by this team
                    AllianceSharedScoutingData.query.filter_by(
                        alliance_id=alliance_id,
                        source_scouting_team_number=team_number
                    ).delete()
                    
                    # Remove pit data shared by this team
                    AllianceSharedPitData.query.filter_by(
                        alliance_id=alliance_id,
                        source_scouting_team_number=team_number
                    ).delete()
            
            status.is_alliance_mode_active = False
            status.deactivated_at = datetime.now(timezone.utc)
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        # If expires_at is naive, assume UTC. If it's aware, convert to UTC for safe comparison.
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        else:
            exp = exp.astimezone(timezone.utc)
        return now > exp
    
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
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        # If expires_at is naive, assume UTC. If it's aware, convert to UTC for safe comparison.
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        else:
            exp = exp.astimezone(timezone.utc)
        return now > exp
    
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
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        
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

class TextSnippet1(db.Model):
    """Small text storage table used to test automatic migrations.

    This table is intentionally trivial and does not come with a migration file;
    the tools will autogenerate and apply a migration for it when you run the
    auto-upgrade GUI or CLI.
    """
    __tablename__ = 'text_snippet'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<TextSnippet {self.id} {self.title}>"

class CustomPage(db.Model):
    """Model to store user-created custom pages composed of widgets.

    widgets_json stores a JSON array of widget definitions. Each widget is a
    dict with at least: {'type': 'graph', 'metric': '<metric_id>', 'graph_types': [...], 'data_view': 'averages', 'teams': [numbers]}
    """
    __tablename__ = 'custom_page'
    __bind_key__ = 'pages'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    owner_team = db.Column(db.Integer, nullable=False)
    owner_user = db.Column(db.String(80), nullable=False)
    widgets_json = db.Column(db.Text, nullable=False)  # JSON array of widget configs
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<CustomPage {self.id} - {self.title} by {self.owner_user}> '

    def widgets(self):
        try:
            return json.loads(self.widgets_json)
        except Exception:
            return []

    def set_widgets(self, widgets_obj):
        self.widgets_json = json.dumps(widgets_obj)


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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
            # Ensure last_ping is timezone-aware for comparison
            last_ping_aware = self.last_ping if self.last_ping.tzinfo else self.last_ping.replace(tzinfo=timezone.utc)
            time_since_ping = datetime.now(timezone.utc) - last_ping_aware
            if time_since_ping.total_seconds() > 300:
                return False
        return True
    
    def update_ping(self, success=True, error_message=None):
        """Update last ping time and error tracking"""
        self.last_ping = datetime.now(timezone.utc)
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
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
    
    def _parse_sync_details(self):
        """Safely parse sync_details JSON, handling malformed data"""
        if not self.sync_details:
            return None
        
        try:
            return json.loads(self.sync_details)
        except (json.JSONDecodeError, TypeError) as e:
            # Log the error and return a safe default
            print(f"Warning: Failed to parse sync_details for SyncLog {self.id}: {e}")
            print(f"Raw sync_details: {repr(self.sync_details)}")
            return {'error': 'Invalid JSON data', 'raw_data': str(self.sync_details)}
    
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
            'sync_details': self._parse_sync_details()
        }


class FileChecksum(ConcurrentModelMixin, db.Model):
    """Model for tracking file checksums to detect changes"""
    __tablename__ = 'file_checksums'
    
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String(500), nullable=False, index=True)
    checksum = db.Column(db.String(64), nullable=False)  # SHA256 hash
    file_size = db.Column(db.BigInteger, nullable=False)
    last_modified = db.Column(db.DateTime, nullable=False)
    last_checked = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
            existing.last_checked = datetime.now(timezone.utc)
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
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
        config.last_updated = datetime.now(timezone.utc)
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
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
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
    attempt_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
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
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        
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
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_old)
        
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