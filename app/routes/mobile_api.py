"""
Mobile App API
Comprehensive REST API for mobile applications with authentication, data access, and offline sync
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_user, logout_user, current_user
from datetime import datetime, timezone, timedelta
from functools import wraps
import traceback
import json
import jwt
import uuid

from app.models import (
    User, Team, Event, Match, ScoutingData, PitScoutingData, 
    DoNotPickEntry, AvoidEntry, db
)
from app.utils.team_isolation import get_current_scouting_team_number
from app.utils.analysis import calculate_team_metrics
from werkzeug.security import check_password_hash

# Create blueprint
mobile_api = Blueprint('mobile_api', __name__, url_prefix='/api/mobile')


# Blueprint-wide enforcement: ensure mobile clients are authenticated for all
# endpoints except explicitly allowed ones (health and auth/login). This
# provides defense-in-depth so a missing decorator on an endpoint won't
# accidentally expose data.
EXEMPT_PATHS = [
    '/api/mobile/health',
    '/api/mobile/auth/login'
]


@mobile_api.before_request
def enforce_mobile_auth():
    """Require a valid JWT for all mobile API requests except exempt paths.

    This runs before each request on the blueprint and mirrors the checks
    performed by the token_required decorator. It sets `request.mobile_user`
    and `request.mobile_team_number` when a valid token is provided.
    """
    # Allow CORS preflight and other safe early exits
    if request.method == 'OPTIONS':
        return None

    path = request.path
    # If request is for an exempt path, don't require a token
    if path in EXEMPT_PATHS:
        return None

    # Expect Authorization: Bearer <token>
    auth_header = request.headers.get('Authorization')
    token = None
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1]

    if not token:
        return jsonify({
            'success': False,
            'error': 'Authentication token is missing',
            'error_code': 'AUTH_REQUIRED'
        }), 401

    payload = verify_token(token)
    if not payload:
        return jsonify({
            'success': False,
            'error': 'Invalid or expired token',
            'error_code': 'INVALID_TOKEN'
        }), 401

    user = User.query.get(payload.get('user_id')) if payload.get('user_id') else None
    if not user or not user.is_active:
        return jsonify({
            'success': False,
            'error': 'User not found or inactive',
            'error_code': 'USER_NOT_FOUND'
        }), 401

    # Attach to request so downstream handlers can use them just like
    # the token_required decorator does.
    request.mobile_user = user
    request.mobile_team_number = payload.get('team_number')

# JWT Configuration
JWT_SECRET_KEY = 'your-secret-key-change-in-production'  # TODO: Move to config
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days


def create_token(user_id, username, team_number):
    """Create a JWT token for mobile authentication"""
    payload = {
        'user_id': user_id,
        'username': username,
        'team_number': team_number,
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(token):
    """Verify a JWT token and return the payload"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(f):
    """Decorator to require JWT authentication for mobile endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        
        if not token:
            return jsonify({
                'success': False,
                'error': 'Authentication token is missing',
                'error_code': 'AUTH_REQUIRED'
            }), 401
        
        # Verify token
        payload = verify_token(token)
        if not payload:
            return jsonify({
                'success': False,
                'error': 'Invalid or expired token',
                'error_code': 'INVALID_TOKEN'
            }), 401
        
        # Get user from database
        user = User.query.get(payload['user_id'])
        if not user or not user.is_active:
            return jsonify({
                'success': False,
                'error': 'User not found or inactive',
                'error_code': 'USER_NOT_FOUND'
            }), 401
        
        # Add user info to request context
        request.mobile_user = user
        request.mobile_team_number = payload['team_number']
        
        return f(*args, **kwargs)
    
    return decorated_function


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@mobile_api.route('/auth/login', methods=['POST'])
def mobile_login():
    """
    Mobile login endpoint
    
    Request body:
    {
        "username": "user123",
        "password": "password123"
    }
    
    Response:
    {
        "success": true,
        "token": "eyJ...",
        "user": {
            "id": 1,
            "username": "user123",
            "team_number": 5454,
            "roles": ["scout"]
        },
        "expires_at": "2024-01-01T00:00:00Z"
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'username' not in data or 'password' not in data:
            return jsonify({
                'success': False,
                'error': 'Username and password are required',
                'error_code': 'MISSING_CREDENTIALS'
            }), 400
        
        # Find user - support multiple login forms:
        # 1) username + password
        # 2) username + team_number + password
        # 3) team_number + password (find first user on that team with matching password)
        user = None
        team_number = data.get('team_number')

        # If both username and team_number provided, filter by both
        if data.get('username') and team_number is not None:
            try:
                team_number = int(team_number)
            except Exception:
                team_number = None
            if team_number is not None:
                user = User.query.filter_by(username=data['username'], scouting_team_number=team_number).first()

        # If username provided and no team_number, fallback to username-only lookup
        if not user and data.get('username'):
            user = User.query.filter_by(username=data['username']).first()

        # If no username but team_number provided, attempt to find a user on that team with matching password
        if not user and team_number is not None:
            try:
                team_number = int(team_number)
            except Exception:
                team_number = None
            if team_number is not None:
                candidates = User.query.filter_by(scouting_team_number=team_number, is_active=True).all()
                for cand in candidates:
                    # Only check candidates that have a password
                    try:
                        if cand.check_password(data['password']):
                            user = cand
                            break
                    except Exception:
                        continue

        # Verify credentials
        if not user or not user.check_password(data['password']):
            return jsonify({
                'success': False,
                'error': 'Invalid credentials',
                'error_code': 'INVALID_CREDENTIALS'
            }), 401
        
        if not user.is_active:
            return jsonify({
                'success': False,
                'error': 'User account is inactive',
                'error_code': 'ACCOUNT_INACTIVE'
            }), 401
        
        # Update last login
        user.last_login = datetime.now(timezone.utc)
        db.session.commit()
        
        # Create token
        token = create_token(user.id, user.username, user.scouting_team_number)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'id': user.id,
                'username': user.username,
                'team_number': user.scouting_team_number,
                'roles': user.get_role_names(),
                'profile_picture': user.profile_picture
            },
            'expires_at': expires_at.isoformat()
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Mobile login error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': 'Login failed',
            'error_code': 'LOGIN_ERROR'
        }), 500


@mobile_api.route('/auth/refresh', methods=['POST'])
@token_required
def mobile_refresh_token():
    """
    Refresh authentication token
    
    Response:
    {
        "success": true,
        "token": "eyJ...",
        "expires_at": "2024-01-01T00:00:00Z"
    }
    """
    try:
        user = request.mobile_user
        
        # Create new token
        token = create_token(user.id, user.username, user.scouting_team_number)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
        
        return jsonify({
            'success': True,
            'token': token,
            'expires_at': expires_at.isoformat()
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Token refresh error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to refresh token',
            'error_code': 'REFRESH_ERROR'
        }), 500


@mobile_api.route('/auth/verify', methods=['GET'])
@token_required
def mobile_verify_token():
    """
    Verify if current token is valid
    
    Response:
    {
        "success": true,
        "valid": true,
        "user": {...}
    }
    """
    user = request.mobile_user
    
    return jsonify({
        'success': True,
        'valid': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'team_number': user.scouting_team_number,
            'roles': user.get_role_names()
        }
    }), 200


# ============================================================================
# TEAM DATA ENDPOINTS
# ============================================================================

@mobile_api.route('/teams', methods=['GET'])
@token_required
def get_teams():
    """
    Get list of teams filtered by user's scouting team
    
    Query params:
    - event_id: Filter by event (optional)
    - limit: Max results (default 100)
    - offset: Pagination offset (default 0)
    
    Response:
    {
        "success": true,
        "teams": [...],
        "count": 10,
        "total": 50
    }
    """
    try:
        team_number = request.mobile_team_number
        
        # Base query filtered by scouting team
        teams_query = Team.query.filter_by(scouting_team_number=team_number)

        # Optional event filter by explicit event_id (query param)
        # event_id may be provided as an integer id OR as an event code (string).
        # Accept either form for backwards compatibility with clients that
        # pass the event code (e.g. 'arsea'). Resolve codes to numeric ids.
        event_param = request.args.get('event_id')
        event_id = None
        if event_param is not None:
            try:
                # try integer first
                event_id = int(event_param)
            except Exception:
                # Not an integer — attempt to resolve by event.code scoped to
                # the scouting team first, then globally as a fallback.
                try:
                    evt = Event.query.filter_by(code=str(event_param), scouting_team_number=team_number).first()
                    if not evt:
                        evt = Event.query.filter_by(code=str(event_param)).first()
                    if evt:
                        event_id = evt.id
                        current_app.logger.debug(f"Resolved event code '{event_param}' to id {event_id}")
                    else:
                        current_app.logger.debug(f"Could not resolve event code '{event_param}' to an Event record")
                except Exception:
                    current_app.logger.debug(f"Error while resolving event code '{event_param}'\n{traceback.format_exc()}")
        if event_id:
            # Build teams list from matches for the event to avoid relying on
            # Team.events association which may be incomplete.
            matches = Match.query.filter_by(event_id=event_id, scouting_team_number=team_number).all()
            team_nums = set()
            for m in matches:
                try:
                    team_nums.update(m.red_teams)
                    team_nums.update(m.blue_teams)
                except Exception:
                    # Fallback: parse comma-separated alliances
                    if m.red_alliance:
                        team_nums.update([int(x) for x in m.red_alliance.split(',') if x])
                    if m.blue_alliance:
                        team_nums.update([int(x) for x in m.blue_alliance.split(',') if x])

            if not team_nums:
                return jsonify({'success': True, 'teams': [], 'count': 0, 'total': 0}), 200

            teams_query = Team.query.filter(Team.scouting_team_number == team_number, Team.team_number.in_(list(team_nums)))
        else:
            # No event_id provided: restrict to the scouting team's "current event"
            # as defined in its effective game configuration (considers alliance mode).
            # Use load_game_config with the team_number from the token. We can't
            # rely on `current_user` inside get_effective_game_config() because
            # token-based requests do not populate flask-login's current_user.
            from app.utils.config_manager import load_game_config
            game_config = load_game_config(team_number=team_number)
            event_code = game_config.get('current_event_code') if isinstance(game_config, dict) else None

            # Resolve Event: prefer configured current_event_code, otherwise
            # pick the most recent Event for this scouting team.
            event = None
            if event_code:
                event = Event.query.filter_by(code=event_code, scouting_team_number=team_number).first()
            if not event:
                event = Event.query.filter_by(scouting_team_number=team_number).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).first()

            if not event:
                # No configured or recent event found — return empty list to
                # avoid returning teams from unrelated events.
                return jsonify({'success': True, 'teams': [], 'count': 0, 'total': 0}), 200

            # Collect team numbers from matches for this event. Prefer matches
            # that are scoped to the scouting_team_number, but fall back to any
            # matches for the event if none are scoped.
            matches = Match.query.filter_by(event_id=event.id, scouting_team_number=team_number).all()
            if not matches:
                matches = Match.query.filter_by(event_id=event.id).all()

            team_nums = set()
            for m in matches:
                try:
                    team_nums.update(m.red_teams)
                    team_nums.update(m.blue_teams)
                except Exception:
                    if m.red_alliance:
                        team_nums.update([int(x) for x in m.red_alliance.split(',') if x])
                    if m.blue_alliance:
                        team_nums.update([int(x) for x in m.blue_alliance.split(',') if x])

            if not team_nums:
                return jsonify({'success': True, 'teams': [], 'count': 0, 'total': 0}), 200

            teams_query = Team.query.filter(Team.scouting_team_number == team_number, Team.team_number.in_(list(team_nums)))
        
        # Pagination
        limit = min(request.args.get('limit', 100, type=int), 500)
        offset = request.args.get('offset', 0, type=int)
        
        total_count = teams_query.count()
        teams = teams_query.offset(offset).limit(limit).all()
        
        teams_data = [{
            'id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name,
            'location': team.location
        } for team in teams]
        
        return jsonify({
            'success': True,
            'teams': teams_data,
            'count': len(teams_data),
            'total': total_count
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get teams error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve teams',
            'error_code': 'TEAMS_ERROR'
        }), 500


@mobile_api.route('/teams/<int:team_id>', methods=['GET'])
@token_required
def get_team_details(team_id):
    """
    Get detailed information about a specific team
    
    Response:
    {
        "success": true,
        "team": {
            "id": 1,
            "team_number": 5454,
            "team_name": "The Bionics",
            "location": "USA",
            "events": [...],
            "recent_matches": [...]
        }
    }
    """
    try:
        team_number = request.mobile_team_number
        
        # Get team with team isolation
        team = Team.query.filter_by(id=team_id, scouting_team_number=team_number).first()
        
        if not team:
            return jsonify({
                'success': False,
                'error': 'Team not found',
                'error_code': 'TEAM_NOT_FOUND'
            }), 404
        
        # Get scouting data count
        scouting_count = ScoutingData.query.filter_by(
            team_id=team_id,
            scouting_team_number=team_number
        ).count()
        
        # Get recent matches
        recent_matches = Match.query.filter(
            db.or_(
                Match.red_alliance.contains(str(team.team_number)),
                Match.blue_alliance.contains(str(team.team_number))
            ),
            Match.scouting_team_number == team_number
        ).order_by(Match.match_number.desc()).limit(10).all()
        
        team_data = {
            'id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name,
            'location': team.location,
            'scouting_data_count': scouting_count,
            'events': [{
                'id': e.id,
                'name': e.name,
                'code': e.code
            } for e in team.events],
            'recent_matches': [{
                'id': m.id,
                'match_number': m.match_number,
                'match_type': m.match_type,
                'red_alliance': m.red_alliance,
                'blue_alliance': m.blue_alliance,
                'red_score': m.red_score,
                'blue_score': m.blue_score,
                'winner': m.winner
            } for m in recent_matches]
        }
        
        return jsonify({
            'success': True,
            'team': team_data
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get team details error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve team details',
            'error_code': 'TEAM_DETAILS_ERROR'
        }), 500


# ============================================================================
# EVENT DATA ENDPOINTS
# ============================================================================

@mobile_api.route('/events', methods=['GET'])
@token_required
def get_events():
    """
    Get list of events for user's scouting team
    
    Response:
    {
        "success": true,
        "events": [...]
    }
    """
    try:
        team_number = request.mobile_team_number
        
        # Get events with teams from this scouting team
        events = Event.query.join(Event.teams).filter(
            Team.scouting_team_number == team_number
        ).distinct().all()
        
        events_data = [{
            'id': event.id,
            'name': event.name,
            'code': event.code,
            'location': event.location,
            'start_date': event.start_date.isoformat() if event.start_date else None,
            'end_date': event.end_date.isoformat() if event.end_date else None,
            'timezone': event.timezone,
            'team_count': len(event.teams)
        } for event in events]
        
        return jsonify({
            'success': True,
            'events': events_data
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get events error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve events',
            'error_code': 'EVENTS_ERROR'
        }), 500


# ============================================================================
# MATCH DATA ENDPOINTS
# ============================================================================

@mobile_api.route('/matches', methods=['GET'])
@token_required
def get_matches():
    """
    Get matches for user's scouting team
    
    Query params:
    - event_id: Filter by event (required)
    - match_type: Filter by match type (optional)
    - team_number: Filter by team (optional)
    
    Response:
    {
        "success": true,
        "matches": [...]
    }
    """
    try:
        team_number = request.mobile_team_number
        event_id = request.args.get('event_id', type=int)
        
        if not event_id:
            return jsonify({
                'success': False,
                'error': 'event_id is required',
                'error_code': 'MISSING_EVENT_ID'
            }), 400
        
        # Base query
        matches_query = Match.query.filter_by(
            event_id=event_id,
            scouting_team_number=team_number
        )
        
        # Optional filters
        match_type = request.args.get('match_type')
        if match_type:
            matches_query = matches_query.filter_by(match_type=match_type)
        
        team_filter = request.args.get('team_number', type=int)
        if team_filter:
            team_str = str(team_filter)
            matches_query = matches_query.filter(
                db.or_(
                    Match.red_alliance.contains(team_str),
                    Match.blue_alliance.contains(team_str)
                )
            )
        
        matches = matches_query.order_by(Match.match_number).all()
        
        matches_data = [{
            'id': match.id,
            'match_number': match.match_number,
            'match_type': match.match_type,
            'red_alliance': match.red_alliance,
            'blue_alliance': match.blue_alliance,
            'red_score': match.red_score,
            'blue_score': match.blue_score,
            'winner': match.winner
        } for match in matches]
        
        return jsonify({
            'success': True,
            'matches': matches_data,
            'count': len(matches_data)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get matches error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve matches',
            'error_code': 'MATCHES_ERROR'
        }), 500


# ============================================================================
# SCOUTING DATA ENDPOINTS
# ============================================================================

@mobile_api.route('/scouting/submit', methods=['POST'])
@token_required
def submit_scouting_data():
    """
    Submit new scouting data from mobile app
    
    Request body:
    {
        "team_id": 1,
        "match_id": 5,
        "data": {...},
        "offline_id": "uuid-generated-by-app"  # For offline sync
    }
    
    Response:
    {
        "success": true,
        "scouting_id": 123,
        "message": "Scouting data submitted successfully"
    }
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided',
                'error_code': 'MISSING_DATA'
            }), 400
        
        # Validate required fields
        required_fields = ['team_id', 'match_id', 'data']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}',
                    'error_code': 'MISSING_FIELD'
                }), 400
        
        # Verify team and match exist
        team = Team.query.filter_by(id=data['team_id'], scouting_team_number=team_number).first()
        if not team:
            return jsonify({
                'success': False,
                'error': 'Team not found',
                'error_code': 'TEAM_NOT_FOUND'
            }), 404
        
        match = Match.query.filter_by(id=data['match_id'], scouting_team_number=team_number).first()
        if not match:
            return jsonify({
                'success': False,
                'error': 'Match not found',
                'error_code': 'MATCH_NOT_FOUND'
            }), 404
        
        # Create scouting data entry
        # The ScoutingData model exposes scout_name and scout_id columns.
        # The `scout` @property is a read-only accessor that returns a User
        # object and therefore cannot be assigned to. Set scout_name and
        # scout_id instead.
        scouting_data = ScoutingData(
            team_id=data['team_id'],
            match_id=data['match_id'],
            data=data['data'],
            scout_name=user.username,
            scout_id=user.id,
            scouting_team_number=team_number,
            timestamp=datetime.now(timezone.utc)
        )
        
        db.session.add(scouting_data)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'scouting_id': scouting_data.id,
            'message': 'Scouting data submitted successfully',
            'offline_id': data.get('offline_id')  # Echo back for sync tracking
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Submit scouting data error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': 'Failed to submit scouting data',
            'error_code': 'SUBMIT_ERROR'
        }), 500


@mobile_api.route('/scouting/bulk-submit', methods=['POST'])
@token_required
def bulk_submit_scouting_data():
    """
    Submit multiple scouting entries at once (for offline sync)
    
    Request body:
    {
        "entries": [
            {
                "team_id": 1,
                "match_id": 5,
                "data": {...},
                "offline_id": "uuid-1",
                "timestamp": "2024-01-01T12:00:00Z"
            },
            ...
        ]
    }
    
    Response:
    {
        "success": true,
        "submitted": 5,
        "failed": 0,
        "results": [...]
    }
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number
        data = request.get_json()
        
        if not data or 'entries' not in data:
            return jsonify({
                'success': False,
                'error': 'No entries provided',
                'error_code': 'MISSING_ENTRIES'
            }), 400
        
        results = []
        submitted_count = 0
        failed_count = 0
        
        for entry in data['entries']:
            try:
                # Validate entry
                if not all(k in entry for k in ['team_id', 'match_id', 'data']):
                    results.append({
                        'offline_id': entry.get('offline_id'),
                        'success': False,
                        'error': 'Missing required fields'
                    })
                    failed_count += 1
                    continue
                
                # Verify team and match
                team = Team.query.filter_by(id=entry['team_id'], scouting_team_number=team_number).first()
                match = Match.query.filter_by(id=entry['match_id'], scouting_team_number=team_number).first()
                
                if not team or not match:
                    results.append({
                        'offline_id': entry.get('offline_id'),
                        'success': False,
                        'error': 'Team or match not found'
                    })
                    failed_count += 1
                    continue
                
                # Create entry
                timestamp = entry.get('timestamp')
                if timestamp:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                else:
                    timestamp = datetime.now(timezone.utc)
                
                # Use scout_name and scout_id columns rather than the read-only
                # `scout` property accessor.
                scouting_data = ScoutingData(
                    team_id=entry['team_id'],
                    match_id=entry['match_id'],
                    data=entry['data'],
                    scout_name=user.username,
                    scout_id=user.id,
                    scouting_team_number=team_number,
                    timestamp=timestamp
                )
                
                db.session.add(scouting_data)
                db.session.flush()  # Get ID without committing
                
                results.append({
                    'offline_id': entry.get('offline_id'),
                    'success': True,
                    'scouting_id': scouting_data.id
                })
                submitted_count += 1
                
            except Exception as e:
                results.append({
                    'offline_id': entry.get('offline_id'),
                    'success': False,
                    'error': str(e)
                })
                failed_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'submitted': submitted_count,
            'failed': failed_count,
            'results': results
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Bulk submit error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': 'Failed to process bulk submission',
            'error_code': 'BULK_SUBMIT_ERROR'
        }), 500


@mobile_api.route('/scouting/history', methods=['GET'])
@token_required
def get_scouting_history():
    """
    Get scouting history for current user
    
    Query params:
    - limit: Max results (default 50)
    - offset: Pagination offset
    
    Response:
    {
        "success": true,
        "entries": [...],
        "count": 10
    }
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number
        
        limit = min(request.args.get('limit', 50, type=int), 200)
        offset = request.args.get('offset', 0, type=int)
        
        # Get user's scouting entries
        entries = ScoutingData.query.filter_by(
            scout=user.username,
            scouting_team_number=team_number
        ).order_by(ScoutingData.timestamp.desc()).offset(offset).limit(limit).all()
        
        entries_data = [{
            'id': entry.id,
            'team_id': entry.team_id,
            'match_id': entry.match_id,
            'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
            'data': entry.data
        } for entry in entries]
        
        return jsonify({
            'success': True,
            'entries': entries_data,
            'count': len(entries_data)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get scouting history error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve scouting history',
            'error_code': 'HISTORY_ERROR'
        }), 500


@mobile_api.route('/scouting/all', methods=['GET'])
@token_required
def get_all_scouting_data():
    """
    Return scouting data rows for the scouting team with optional filters.

    Query params:
    - team_number (int) or team_id (int): filter by team
    - event_id (int): filter by event (joins Match safely)
    - match_id (int): filter by match id
    - limit (int): max rows (default 200, max 2000)
    - offset (int): pagination offset

    Response:
    {
      "success": true,
      "count": 10,
      "total": 123,
      "entries": [{...}]
    }
    """
    try:
        team_number = request.mobile_team_number

        # Parse filters - NOTE: team_number is now for filtering *which team was scouted*
        # not the scouting_team_number. The scouting team is always from the token.
        q_team_number = request.args.get('team_number', type=int)
        q_team_id = request.args.get('team_id', type=int)
        match_id = request.args.get('match_id', type=int)

        # event_id may be an integer id or an event code string (e.g. 'arsea')
        event_param = request.args.get('event_id')
        event_id = None
        if event_param is not None:
            try:
                event_id = int(event_param)
            except Exception:
                try:
                    evt = Event.query.filter_by(code=str(event_param), scouting_team_number=team_number).first()
                    if not evt:
                        evt = Event.query.filter_by(code=str(event_param)).first()
                    if evt:
                        event_id = evt.id
                        current_app.logger.debug(f"Resolved event code '{event_param}' to id {event_id} in scouting/all")
                except Exception:
                    current_app.logger.debug(f"Error resolving event code '{event_param}' in scouting/all\n{traceback.format_exc()}")

        # Scoping: by default mobile API is scoped to the token's scouting_team_number.
        # For testing, clients may pass scoped=0 to retrieve rows regardless of scouting_team_number.
        scoped_param = request.args.get('scoped', '1')
        scoped = False if str(scoped_param).lower() in ('0', 'false', 'no', 'off') else True

        limit = min(request.args.get('limit', 200, type=int), 2000)
        offset = request.args.get('offset', 0, type=int)

        # Build query mirroring the web /scouting/list logic:
        # Start with ScoutingData filtered by the token's scouting_team_number,
        # then optionally filter by which team was scouted, event, or match.
        base_q = ScoutingData.query.filter_by(scouting_team_number=team_number)

        # Optional filter: which team was scouted (team_id or team_number)
        # This is about the *scouted* team (Team.id or Team.team_number), not the scouting team.
        # IMPORTANT: If user passes team_number that matches their own scouting_team_number,
        # ignore it (common mistake — they want all data for their scouting team, not filtered).
        if q_team_id:
            base_q = base_q.filter(ScoutingData.team_id == q_team_id)
        elif q_team_number and q_team_number != team_number:
            # Only filter if q_team_number is different from the token's scouting team.
            # Resolve Team.id for the *scouted* team_number.
            # Look for a Team record with that team_number. Prefer one scoped to the
            # token's scouting_team_number if it exists, otherwise any team with that number.
            t_scouted = Team.query.filter_by(team_number=q_team_number, scouting_team_number=team_number).first()
            if not t_scouted:
                t_scouted = Team.query.filter_by(team_number=q_team_number).first()
            if t_scouted:
                base_q = base_q.filter(ScoutingData.team_id == t_scouted.id)
            else:
                # No such team exists; return empty
                return jsonify({'success': True, 'count': 0, 'total': 0, 'entries': []}), 200

        # Optional filter: by match_id
        if match_id:
            base_q = base_q.filter(ScoutingData.match_id == match_id)

        # Join Match, Team, and Event to populate related fields in the response.
        # Mirror /scouting/list which does:
        #   ScoutingData.query.filter_by(scouting_team_number=...).join(Match).join(Event).join(Team)
        joined_q = base_q.join(Match, ScoutingData.match_id == Match.id).join(Team, ScoutingData.team_id == Team.id).join(Event, Match.event_id == Event.id)

        # Optional filter: by event_id (after joining)
        if event_id:
            joined_q = joined_q.filter(Match.event_id == event_id)

        total = joined_q.count()
        rows = joined_q.order_by(ScoutingData.timestamp.desc()).offset(offset).limit(limit).all()

        entries = []
        for r in rows:
            # Access related objects safely (they may be None)
            team_obj = getattr(r, 'team', None)
            match_obj = getattr(r, 'match', None)
            event_obj = getattr(match_obj, 'event', None) if match_obj else None

            entries.append({
                'id': r.id,
                'team_id': r.team_id,
                'team_number': team_obj.team_number if team_obj else None,
                'team_name': team_obj.team_name if team_obj else None,
                'match_id': r.match_id,
                'match_number': match_obj.match_number if match_obj else None,
                'match_type': match_obj.match_type if match_obj else None,
                'event_id': event_obj.id if event_obj else None,
                'event_code': event_obj.code if event_obj else None,
                'alliance': r.alliance,
                'scout_name': r.scout_name,
                'scout_id': r.scout_id,
                'scouting_station': r.scouting_station,
                'timestamp': r.timestamp.isoformat() if r.timestamp else None,
                'scouting_team_number': r.scouting_team_number,
                'data': r.data
            })

        return jsonify({'success': True, 'count': len(entries), 'total': total, 'entries': entries}), 200

    except Exception as e:
        current_app.logger.error(f"Get all scouting data error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to retrieve scouting data', 'error_code': 'SCOUTING_ALL_ERROR'}), 500


# ============================================================================
# PIT SCOUTING ENDPOINTS
# ============================================================================

@mobile_api.route('/pit-scouting/submit', methods=['POST'])
@token_required
def submit_pit_scouting_data():
    """
    Submit pit scouting data
    
    Request body:
    {
        "team_id": 1,
        "data": {...},
        "images": ["base64_string1", ...]  # Optional
    }
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number
        data = request.get_json()
        
        if not data or 'team_id' not in data or 'data' not in data:
            return jsonify({
                'success': False,
                'error': 'team_id and data are required',
                'error_code': 'MISSING_DATA'
            }), 400
        
        # Verify team
        team = Team.query.filter_by(id=data['team_id'], scouting_team_number=team_number).first()
        if not team:
            return jsonify({
                'success': False,
                'error': 'Team not found',
                'error_code': 'TEAM_NOT_FOUND'
            }), 404
        
        # Create pit scouting entry
        # PitScoutingData also exposes scout_name and scout_id columns. Avoid
        # assigning to the read-only `scout` property.
        pit_data = PitScoutingData(
            team_id=data['team_id'],
            data=data['data'],
            scout_name=user.username,
            scout_id=user.id,
            scouting_team_number=team_number,
            timestamp=datetime.now(timezone.utc)
        )
        
        db.session.add(pit_data)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'pit_scouting_id': pit_data.id,
            'message': 'Pit scouting data submitted successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Submit pit scouting error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to submit pit scouting data',
            'error_code': 'PIT_SUBMIT_ERROR'
        }), 500


# ============================================================================
# CONFIGURATION ENDPOINTS
# ============================================================================

@mobile_api.route('/config/game', methods=['GET'])
@token_required
def get_game_config():
    """
    Get current game configuration for the mobile app
    
    Response:
    {
        "success": true,
        "config": {
            "season": 2024,
            "game_name": "Crescendo",
            "scouting_form": {...}
        }
    }
    """
    try:
        team_number = request.mobile_team_number
        
        # Load game config for this team
        from app.utils.config_manager import load_game_config
        game_config = load_game_config(team_number=team_number)
        
        # Return the full game configuration (gameconfig.json) for this scouting team
        # This mirrors the web UI and ensures mobile clients receive the complete
        # form definition, rules, and any custom settings.
        return jsonify({
            'success': True,
            'config': game_config
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get game config error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve game configuration',
            'error_code': 'CONFIG_ERROR'
        }), 500


@mobile_api.route('/graphs/compare', methods=['POST'])
@token_required
def mobile_graphs_compare():
    """
    Compare multiple teams for graphing purposes.

    Request JSON:
    {
      "team_numbers": [5454, 1234],
      "event_id": 5,               # optional
      "metric": "total_points",  # optional, default total_points
      "graph_types": ["line","bar","radar"],
      "data_view": "averages"     # optional
    }

    Response mirrors the examples in MOBILE_API_JSON_EXAMPLES.md
    """
    try:
        payload = request.get_json() or {}
        team_numbers = payload.get('team_numbers') or []
        if not team_numbers or not isinstance(team_numbers, (list, tuple)):
            return jsonify({'success': False, 'error': 'team_numbers list required', 'error_code': 'MISSING_TEAMS'}), 400

        event_id = payload.get('event_id')
        metric = payload.get('metric') or 'total_points'
        metric_alias = 'tot' if metric in ('total_points', 'points', 'tot') else metric
        graph_types = payload.get('graph_types') or ['line', 'bar', 'radar']
        data_view = payload.get('data_view') or 'averages'

        # Colors for datasets
        palette = ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40"]

        teams_response = []
        line_labels = set()
        line_datasets = []
        radar_datasets = []

        # For each requested team number, resolve Team (respecting scouting team isolation)
        token_team_number = request.mobile_team_number

        for idx, tn in enumerate(team_numbers):
            try:
                tn_int = int(tn)
            except Exception:
                continue

            team = Team.query.filter_by(team_number=tn_int, scouting_team_number=token_team_number).first()
            if not team:
                # fallback to any team record with that number
                team = Team.query.filter_by(team_number=tn_int).first()
            if not team:
                # skip unknown teams
                continue

            # Compute aggregate metrics
            analytics = calculate_team_metrics(team.id, event_id=event_id)
            metrics = analytics.get('metrics', {})

            # Build basic team entry
            team_entry = {
                'team_number': team.team_number,
                'team_name': team.team_name,
                'color': palette[idx % len(palette)],
                'value': metrics.get('total_points') or metrics.get('tot') or 0,
                'std_dev': metrics.get('total_points_std') or metrics.get('tot_std') or 0,
                'match_count': analytics.get('match_count') or 0
            }
            teams_response.append(team_entry)

            # Build per-match series for line chart
            # Query scouting data for this team, scope to the token_team_number and join Match once
            # Joining Match once avoids duplicate JOINs which can lead to ambiguous column errors.
            q = ScoutingData.query.join(Match, ScoutingData.match_id == Match.id).filter(
                ScoutingData.team_id == team.id,
                ScoutingData.scouting_team_number == token_team_number
            )
            if event_id:
                q = q.filter(Match.event_id == event_id)
            scouting_rows = q.order_by(Match.match_number).all()

            # Collect labels and values
            labels = []
            values = []
            for row in scouting_rows:
                try:
                    mnum = row.match.match_number if row.match else None
                except Exception:
                    mnum = None
                if mnum is None:
                    continue
                # label is match number
                labels.append(f"Match {mnum}")
                # compute metric per-row
                if metric_alias == 'tot':
                    val = row.calculate_metric('tot')
                else:
                    val = row.calculate_metric(metric_alias)
                values.append(val)
                line_labels.add(f"Match {mnum}")

            # Add dataset for this team
            line_datasets.append({
                'label': f"{team.team_number} - {team.team_name}",
                'data': values,
                'borderColor': palette[idx % len(palette)],
                'backgroundColor': f"{palette[idx % len(palette)]}",
                'tension': 0.4
            })

            # Radar dataset: use a small set of core metrics if available
            radar_metrics = [
                metrics.get('total_points') or metrics.get('tot') or 0,
                metrics.get('auto_points') or metrics.get('apt') or 0,
                metrics.get('teleop_points') or metrics.get('tpt') or 0,
                metrics.get('endgame_points') or metrics.get('ept') or 0,
                round((metrics.get('consistency') or 0) * 100, 2) if metrics.get('consistency') is not None else 0
            ]
            radar_datasets.append({
                'label': f"{team.team_number} - {team.team_name}",
                'data': radar_metrics,
                'borderColor': palette[idx % len(palette)],
                'backgroundColor': palette[idx % len(palette)]
            })

        # Build labels sorted
        labels_sorted = sorted(list(line_labels), key=lambda s: int(s.replace('Match ', ''))) if line_labels else []

        graphs = {}
        if 'line' in graph_types:
            graphs['line'] = {
                'type': 'line',
                'labels': labels_sorted,
                'datasets': line_datasets
            }
        if 'bar' in graph_types:
            graphs['bar'] = {
                'type': 'bar',
                'labels': [str(t['team_number']) for t in teams_response],
                'datasets': [
                    {
                        'label': 'Average Total Points',
                        'data': [t['value'] for t in teams_response],
                        'backgroundColor': [t['color'] for t in teams_response]
                    }
                ]
            }
        if 'radar' in graph_types:
            graphs['radar'] = {
                'type': 'radar',
                'labels': ['Total Points', 'Auto Points', 'Teleop Points', 'Endgame Points', 'Consistency'],
                'datasets': radar_datasets
            }

        event_obj = Event.query.get(event_id) if event_id else None

        return jsonify({
            'success': True,
            'event': {'id': event_obj.id, 'name': event_obj.name, 'code': event_obj.code} if event_obj else None,
            'metric': metric,
            'metric_display_name': metric.replace('_', ' ').title(),
            'data_view': data_view,
            'teams': teams_response,
            'graphs': graphs
        }), 200

    except Exception as e:
        current_app.logger.error(f"mobile_graphs_compare error: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to generate graph comparison', 'error_code': 'GRAPHS_COMPARE_ERROR'}), 500


# ============================================================================
# SYNC STATUS ENDPOINT
# ============================================================================

@mobile_api.route('/sync/status', methods=['GET'])
@token_required
def get_sync_status():
    """
    Get sync status and last update times
    
    Response:
    {
        "success": true,
        "server_time": "2024-01-01T12:00:00Z",
        "last_updates": {
            "teams": "2024-01-01T11:00:00Z",
            "matches": "2024-01-01T11:30:00Z",
            "events": "2024-01-01T10:00:00Z"
        }
    }
    """
    try:
        team_number = request.mobile_team_number
        
        # Get last update times for each data type
        last_team_update = db.session.query(db.func.max(Team.id)).filter_by(
            scouting_team_number=team_number
        ).scalar()
        
        last_match_update = db.session.query(db.func.max(Match.id)).filter_by(
            scouting_team_number=team_number
        ).scalar()
        
        return jsonify({
            'success': True,
            'server_time': datetime.now(timezone.utc).isoformat(),
            'last_updates': {
                'teams': last_team_update,
                'matches': last_match_update
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get sync status error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve sync status',
            'error_code': 'SYNC_STATUS_ERROR'
        }), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================

@mobile_api.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint (no authentication required)
    
    Response:
    {
        "success": true,
        "status": "healthy",
        "version": "1.0",
        "timestamp": "2024-01-01T12:00:00Z"
    }
    """
    return jsonify({
        'success': True,
        'status': 'healthy',
        'version': '1.0',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@mobile_api.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found',
        'error_code': 'NOT_FOUND'
    }), 404


@mobile_api.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error',
        'error_code': 'INTERNAL_ERROR'
    }), 500
