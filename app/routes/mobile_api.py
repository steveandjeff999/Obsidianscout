"""
Mobile App API
Comprehensive REST API for mobile applications with authentication, data access, and offline sync
"""
from flask import Blueprint, request, jsonify, current_app, g, url_for, send_file
from flask_login import login_user, logout_user, current_user
from datetime import datetime, timezone, timedelta
import os
from functools import wraps
import traceback
import json
import jwt
import base64
import uuid
import math
import statistics

from app.models import (
    User, Team, Event, Match, ScoutingData, PitScoutingData, 
    DoNotPickEntry, AvoidEntry, ScoutingAllianceChat, TeamAllianceStatus, ScoutingDirectMessage, db
)
from app import load_user_chat_history, load_group_chat_history, load_assistant_chat_history, save_user_chat_history, save_group_chat_history, get_user_chat_file_path, load_group_members, save_group_members, get_group_members_file_path
from app.models_misc import NotificationQueue, NotificationSubscription, NotificationLog
from app.utils.team_isolation import get_current_scouting_team_number
from app.utils.analysis import calculate_team_metrics
from app.utils.api_utils import safe_int_team_number
from werkzeug.security import check_password_hash
from app.assistant.visualizer import Visualizer

# Create blueprint
mobile_api = Blueprint('mobile_api', __name__, url_prefix='/api/mobile')

# Blueprint error handlers: return JSON for common HTTP errors so mobile clients
# don't receive HTML error pages. These apply to errors raised while handling
# requests under this blueprint.


@mobile_api.app_errorhandler(404)
def _mobile_api_not_found(err):
    try:
        current_app.logger.info(f"mobile_api 404: path={request.path} method={request.method}")
    except Exception:
        current_app.logger.info("mobile_api 404 encountered")
    return jsonify({'success': False, 'error': 'Not found', 'error_code': 'NOT_FOUND'}), 404


@mobile_api.app_errorhandler(500)
def _mobile_api_internal_error(err):
    # Log the exception with traceback if available
    try:
        current_app.logger.error(f"mobile_api internal error: {str(err)}\n{traceback.format_exc()}")
    except Exception:
        current_app.logger.error("mobile_api internal error occurred")
    return jsonify({'success': False, 'error': 'Internal server error', 'error_code': 'INTERNAL_ERROR'}), 500


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
    # Log decoded token payload for debugging token/team mismatches
    try:
        print('DECODED_TOKEN_PAYLOAD:')
        print(json.dumps(payload, indent=2))
    except Exception:
        pass

    user = User.query.get(payload.get('user_id')) if payload.get('user_id') else None
    if not user or not user.is_active:
        return jsonify({
            'success': False,
            'error': 'User not found or inactive',
            'error_code': 'USER_NOT_FOUND'
        }), 401

    # Determine team_number securely. For security, if the token includes a
    # team_number it MUST match the user's DB scouting_team_number (when set).
    # This prevents clients from presenting a token that claims to be one
    # team while accessing another team's data. If the token omits a team
    # number we fall back to the DB value.
    token_team = payload.get('team_number')
    team_number = None
    try:
        if token_team is not None:
            db_team = getattr(user, 'scouting_team_number', None)
            # If DB has a team and it doesn't match the token, reject the
            # request (security failure).
            if db_team is not None and str(token_team) != str(db_team):
                current_app.logger.warning(
                    f"mobile_api.auth: token team {token_team} does not match DB scouting_team_number {db_team} for user {user.id}; rejecting"
                )
                return jsonify({'success': False, 'error': 'Token team mismatch', 'error_code': 'TEAM_MISMATCH'}), 401
            # Accept the token's team when provided (DB either matches or is unset)
            team_number = token_team
        else:
            # No team in token: use the user's DB scouting_team_number
            team_number = getattr(user, 'scouting_team_number', None)
    except Exception:
        team_number = payload.get('team_number')

    # Attach to request so downstream handlers can use them just like
    # the token_required decorator does.
    request.mobile_user = user
    request.mobile_team_number = team_number
    # Log the resolved team information to help debug requests where the
    # token-provided team differs from the DB value. Keep this lightweight.
    try:
        current_app.logger.info(
            f"mobile_api.auth: path={path} method={request.method} user_id={getattr(user,'id',None)} "
            f"username={getattr(user,'username',None)} token_team={token_team} resolved_team={team_number} db_team={getattr(user,'scouting_team_number',None)}"
        )
    except Exception:
        pass
    # Also print a concise debug line to stdout so it's visible in simple
    # dev server logs (some deployments only show access logs). This helps
    # when troubleshooting which scouting team is used for a request.
    try:
        print(f"MOBILE_API_CALL: remote={request.remote_addr} path={path} method={request.method} user_id={getattr(user,'id',None)} username={getattr(user,'username',None)} token_team={token_team} resolved_team={team_number} db_team={getattr(user,'scouting_team_number',None)}")
    except Exception:
        pass
    # Also print raw headers and body for full request visibility (best-effort).
    try:
        print('RAW_REQUEST_HEADERS:')
        for k, v in request.headers.items():
            print(f"{k}: {v}")
    except Exception:
        pass
    try:
        raw = request.get_data(cache=True, as_text=True)
        if raw:
            print('RAW_REQUEST_BODY:')
            print(raw)
    except Exception:
        pass


@mobile_api.after_request
def _mobile_api_add_debug_headers(response):
    """Add a small debug header indicating which scouting team the request was
    resolved to. This helps clients and devs quickly see which team context
    the server used when handling the request.
    """
    try:
        team = getattr(request, 'mobile_team_number', None)
        if team is not None:
            response.headers['X-Mobile-Team'] = str(team)
    except Exception:
        pass
    return response

# JWT Configuration
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24 * 1  # 1 day


def create_token(user_id, username, team_number):
    """Create a JWT token for mobile authentication"""
    payload = {
        'user_id': user_id,
        'username': username,
        'team_number': team_number,
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.now(timezone.utc)
    }
    # Read secret from application config (set in app_config.json or environment)
    try:
        secret = current_app.config.get('JWT_SECRET_KEY')
    except Exception:
        secret = None
    if not secret:
        # Fallback placeholder (not secure) so development doesn't break
        secret = 'your-secret-key-change-in-production'
        try:
            current_app.logger.warning('Using placeholder JWT secret; set JWT_SECRET_KEY in app_config.json for production')
        except Exception:
            pass
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_token(token):
    """Verify a JWT token and return the payload"""
    try:
        try:
            secret = current_app.config.get('JWT_SECRET_KEY')
        except Exception:
            secret = None
        if not secret:
            secret = 'your-secret-key-change-in-production'
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
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
        
        # Add user info to request context. Be defensive about the team number
        # - prefer the token value, but if it is missing or matches the user id
        #   it is likely incorrect and we fall back to the DB value.
        token_team = payload.get('team_number')
        team_number = None
        try:
            if token_team is None:
                team_number = getattr(user, 'scouting_team_number', None)
            else:
                if str(token_team) == str(payload.get('user_id')):
                    current_app.logger.warning(f"token team_number equals user_id for user {payload.get('user_id')}; using DB scouting_team_number instead")
                    team_number = getattr(user, 'scouting_team_number', None)
                else:
                    team_number = token_team
        except Exception:
            team_number = payload.get('team_number')

        request.mobile_user = user
        request.mobile_team_number = team_number
        
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
        
        # Find user - support multiple login forms but enforce strict matching
        # when a team_number is provided to avoid issuing tokens for the wrong team.
        # Supported flows:
        # A) username + password
        # B) username + team_number + password  (STRICT: must match username+team)
        # C) team_number + password (find first user on that team with matching password)
        user = None
        team_number = data.get('team_number') if 'team_number' in data else None

        # If both username and team_number provided, require an exact match on both
        if data.get('username') and team_number is not None:
            # Support alphanumeric team numbers for offseason (e.g., '581B')
            team_number = safe_int_team_number(team_number)
            if team_number is None:
                return jsonify({
                    'success': False,
                    'error': 'Invalid team_number',
                    'error_code': 'INVALID_TEAM_NUMBER'
                }), 400

            # Strict username+team lookup. If no user found, reject rather than
            # falling back to username-only lookup (prevents issuing a token for
            # the wrong team).
            user = User.query.filter_by(username=data['username'], scouting_team_number=team_number).first()
            if not user:
                return jsonify({
                    'success': False,
                    'error': 'User not found for provided team',
                    'error_code': 'USER_NOT_FOUND_FOR_TEAM'
                }), 401

        # If username provided and no team_number specified, lookup by username
        if not user and data.get('username') and team_number is None:
            user = User.query.filter_by(username=data['username']).first()

        # If no username but team_number provided, attempt to find a user on that
        # team with a matching password (team-based login)
        if not user and team_number is not None and not data.get('username'):
            # Support alphanumeric team numbers for offseason (e.g., '581B')
            team_number = safe_int_team_number(team_number)
            if team_number is None:
                return jsonify({
                    'success': False,
                    'error': 'Invalid team_number',
                    'error_code': 'INVALID_TEAM_NUMBER'
                }), 400
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


@mobile_api.route('/profiles/me', methods=['GET'])
@token_required
def mobile_get_my_profile():
    """
    Return basic profile information for the authenticated mobile user.

    Response:
    {
      "success": true,
      "user": {
         "id": 1,
         "username": "bob",
         "team_number": 5454,
         "profile_picture": "img/avatars/bob.png",
             "profile_picture_url": "https://server.example/api/mobile/profiles/me/picture"  # protected; requires Authorization: Bearer <token>
      }
    }
    """
    try:
        user = request.mobile_user
        if not user:
            return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401

        # Use the stored profile path but provide a token-protected URL
        # so mobile clients fetch the profile picture via the mobile API
        # rather than the public static path. This keeps profile images
        # accessible only to authenticated mobile clients.
        pic_path = user.profile_picture or 'img/avatars/default.png'
        try:
            pic_url = url_for('mobile_api.mobile_get_my_profile_picture', _external=True)
        except Exception:
            pic_url = None

        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'team_number': user.scouting_team_number,
                'profile_picture': pic_path,
                'profile_picture_url': pic_url
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f"mobile_get_my_profile error: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to retrieve profile', 'error_code': 'PROFILE_ERROR'}), 500


@mobile_api.route('/profiles/me/picture', methods=['GET'])
@token_required
def mobile_get_my_profile_picture():
    """Return the authenticated user's profile picture file (token-protected).

    This endpoint only serves the profile image for the authenticated token
    owner. It prevents exposing the public static path in mobile responses.
    """
    try:
        user = request.mobile_user
        if not user:
            return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401

        # Determine file path relative to the app's static folder
        pic_rel = user.profile_picture or 'img/avatars/default.png'
        static_dir = current_app.static_folder
        # Resolve and sanitize path to prevent traversal
        file_path = os.path.normpath(os.path.join(static_dir, pic_rel.lstrip('/\\')))

        if not file_path.startswith(os.path.normpath(static_dir)):
            return jsonify({'success': False, 'error': 'Invalid profile image path', 'error_code': 'INVALID_PICTURE_PATH'}), 400

        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': 'Profile image not found', 'error_code': 'PICTURE_NOT_FOUND'}), 404

        # send_file will set a sensible Content-Type header
        return send_file(file_path)

    except Exception as e:
        current_app.logger.exception(f"mobile_get_my_profile_picture error: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to retrieve profile image', 'error_code': 'PICTURE_ERROR'}), 500


@mobile_api.route('/auth/register', methods=['POST'])
def mobile_register():
    """
    Mobile account creation endpoint.

    Request body:
    {
        "username": "user123",
        "password": "password123",
        "confirm_password": "password123",  # optional
        "team_number": 5454,
        "email": "user@example.com"         # optional
    }

    Response (201):
    {
        "success": true,
        "token": "eyJ...",             # token for immediate use
        "user": { ... },
        "expires_at": "2025-01-01T00:00:00Z"
    }
    """
    try:
        data = request.get_json() or {}

        # Required fields
        username = data.get('username')
        password = data.get('password')
        team_number = data.get('team_number')

        if not username or not password or team_number is None:
            return jsonify({'success': False, 'error': 'username, password, and team_number are required', 'error_code': 'MISSING_FIELDS'}), 400

        # Optional confirmation check
        confirm = data.get('confirm_password')
        if confirm is not None and confirm != password:
            return jsonify({'success': False, 'error': 'Passwords do not match', 'error_code': 'PASSWORD_MISMATCH'}), 400

        # Normalize team number
        team_number = safe_int_team_number(team_number)
        if team_number is None:
            return jsonify({'success': False, 'error': 'Invalid team_number', 'error_code': 'INVALID_TEAM_NUMBER'}), 400

        # Respect per-team account creation lock
        from app.models import ScoutingTeamSettings
        team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=team_number).first()
        if team_settings and team_settings.account_creation_locked:
            return jsonify({'success': False, 'error': 'Account creation is locked for this team', 'error_code': 'ACCOUNT_CREATION_LOCKED'}), 403

        # Enforce unique username scoped to scouting team
        existing = User.query.filter_by(username=username, scouting_team_number=team_number).first()
        if existing:
            return jsonify({'success': False, 'error': 'Username already exists for that team', 'error_code': 'USERNAME_EXISTS'}), 409

        # Normalize email
        email = data.get('email')
        if email == '':
            email = None
        if email and User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'error': 'Email already in use', 'error_code': 'EMAIL_EXISTS'}), 409

        # Create the new user
        new_user = User(username=username, email=email, scouting_team_number=team_number)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        # If first user for this team -> grant admin role
        from app.models import Role
        try:
            count = User.query.filter_by(scouting_team_number=team_number).count()
            if count == 1:
                admin_role = Role.query.filter_by(name='admin').first()
                if admin_role:
                    new_user.roles.append(admin_role)
                    db.session.commit()
        except Exception:
            # Non-fatal if role assignment fails
            current_app.logger.exception('Failed to assign admin role during mobile register')

        # Issue token for immediate use
        token = create_token(new_user.id, new_user.username, new_user.scouting_team_number)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)

        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'id': new_user.id,
                'username': new_user.username,
                'team_number': new_user.scouting_team_number,
                'roles': new_user.get_role_names(),
                'profile_picture': new_user.profile_picture
            },
            'expires_at': expires_at.isoformat()
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Mobile register error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to create account', 'error_code': 'REGISTER_ERROR'}), 500


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
                    # Fallback: parse comma-separated alliances (handle alphanumeric offseason teams)
                    if m.red_alliance:
                        team_nums.update([safe_int_team_number(x.strip()) for x in m.red_alliance.split(',') if x.strip()])
                    if m.blue_alliance:
                        team_nums.update([safe_int_team_number(x.strip()) for x in m.blue_alliance.split(',') if x.strip()])

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
        # Diagnostic log to help trace token vs DB team values for scouting submissions
        try:
            current_app.logger.info(f"submit_scouting_data invoked: mobile_user_id={getattr(user,'id',None)} mobile_username={getattr(user,'username',None)} token_team={team_number} db_team={getattr(user,'scouting_team_number',None)} content_type={request.content_type}")
        except Exception:
            pass
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
        
        # Resolve local_id (clients should send a UUID to track local copies).
        # If missing, generate one server-side to satisfy DB NOT NULL unique constraint.
        import uuid
        local_id = None
        try:
            local_id = data.get('local_id') if isinstance(data, dict) else None
        except Exception:
            local_id = None

        if not local_id:
            local_id = str(uuid.uuid4())

        # If a record with the same local_id already exists for this scouting
        # team we should return it instead of attempting a duplicate insert.
        existing = PitScoutingData.query.filter_by(local_id=local_id, scouting_team_number=team_number).first()
        if existing:
            return jsonify({'success': True, 'pit_scouting_id': existing.id, 'message': 'Already exists'}), 200

        # Accept optional event context for this submission. Mobile clients
        # can pass either `event_id` (database id) or `event_code` (string)
        # when they want the uploaded pit data associated with an event.
        event_id = None
        try:
            if isinstance(data, dict):
                # numeric id preferred
                if data.get('event_id') is not None:
                    try:
                        candidate = int(data.get('event_id'))
                        evt = Event.query.filter_by(id=candidate, scouting_team_number=team_number).first()
                        if evt:
                            event_id = evt.id
                    except Exception:
                        event_id = None

                # allow event code lookup as fallback
                if event_id is None and data.get('event_code'):
                    code = str(data.get('event_code')).upper()
                    evt = Event.query.filter_by(code=code, scouting_team_number=team_number).first()
                    if evt:
                        event_id = evt.id
        except Exception:
            event_id = None
        # PitScoutingData also exposes scout_name and scout_id columns. Avoid
        # assigning to the read-only `scout` property.
        pit_data = PitScoutingData(
            team_id=data['team_id'],
            data=data['data'],
            event_id=event_id,
            local_id=local_id,
            scout_name=user.username,
            scout_id=user.id,
            scouting_team_number=team_number,
            timestamp=datetime.now(timezone.utc)
        )
        # device id if provided
        try:
            if isinstance(data, dict) and data.get('device_id'):
                pit_data.device_id = data.get('device_id')
        except Exception:
            pass
        
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
        # Determine which team number to use. Default to the DB-backed value
        # on the authenticated user, but allow an explicit per-request override
        # via header `X-Mobile-Requested-Team` or query param `team_number`.
        token_team = getattr(request, 'mobile_team_number', None)
        mobile_user = getattr(request, 'mobile_user', None)

        # Prefer DB-backed team when available (more authoritative)
        team_number = token_team
        if mobile_user and getattr(mobile_user, 'scouting_team_number', None) is not None:
            db_team = mobile_user.scouting_team_number
            if token_team is not None and str(token_team) != str(db_team):
                current_app.logger.info(f"mobile_api.get_game_config: token team {token_team} differs from DB scouting_team_number {db_team}; using DB value")
            team_number = db_team

        # Allow client to request a different team number explicitly for this
        # request (useful for testing/overrides). This must be passed via the
        # header X-Mobile-Requested-Team or the query parameter team_number.
        requested_team = None
        try:
            hdr = request.headers.get('X-Mobile-Requested-Team')
            if hdr:
                requested_team = int(hdr)
            else:
                qp = request.args.get('team_number')
                if qp is not None:
                    try:
                        requested_team = int(qp)
                    except Exception:
                        requested_team = None
        except Exception:
            requested_team = None

        if requested_team is not None:
            current_app.logger.info(f"mobile_api.get_game_config: request includes override requested_team={requested_team}; using it instead of resolved {team_number}")
            team_number = requested_team

        # Prefer the explicit per-team instance config file if it exists
        # (instance/configs/<team_number>/game_config.json). This ensures the
        # mobile API returns the exact saved file for the scouting team rather
        # than an alliance-shared or merged/default view.
        from app.utils.config_manager import load_game_config
        game_config = None
        try:
            if team_number is not None:
                base_dir = os.getcwd()
                team_config_path = os.path.join(base_dir, 'instance', 'configs', str(team_number), 'game_config.json')
                current_app.logger.debug(f"mobile_api.get_game_config: looking for team config at {team_config_path}")
                if os.path.exists(team_config_path):
                    with open(team_config_path, 'r', encoding='utf-8') as f:
                        try:
                            game_config = json.load(f)
                        except Exception:
                            # If the file exists but is invalid JSON, log and fall
                            # back to the normal loader which may provide defaults.
                            current_app.logger.warning(f"Invalid JSON in team game_config for team {team_number}")
        except Exception:
            # Non-fatal - fall back to loader below
            game_config = None

        # If no explicit team file, use the existing loader which may return
        # defaults, global, or team-specific merged configs.
        if game_config is None:
            current_app.logger.debug(f"mobile_api.get_game_config: falling back to load_game_config for team {team_number}")
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


@mobile_api.route('/config/game', methods=['POST', 'PUT'])
@token_required
def set_game_config():
    """
    Set or update the game configuration for the mobile client's scouting team.

    Security: requires the authenticated mobile user to have the 'admin' or
    'superadmin' role.

    Request body: JSON representing the full game configuration (same shape
    as returned by GET /api/mobile/config/game).

    Response:
    {
        "success": true
    }
    """
    try:
        user = getattr(request, 'mobile_user', None)
        if not user:
            return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401

        # Require admin or superadmin role to modify config
        if not (user.has_role('admin') or user.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Forbidden', 'error_code': 'FORBIDDEN'}), 403

        # Ensure flask-login current_user is set so save_game_config can infer team
        try:
            login_user(user, remember=False, force=True)
        except Exception:
            # non-fatal; save_game_config accepts explicit behavior for no current_user
            pass

        data = request.get_json()
        if not data or not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'Missing or invalid JSON body', 'error_code': 'MISSING_BODY'}), 400

        # Basic structural validation could be added here. For now, delegate
        # to existing save_game_config which writes per-team or global files.
        from app.utils.config_manager import save_game_config

        saved = save_game_config(data)
        if saved:
            # Update running config in the Flask app (best-effort)
            try:
                current_app.config['GAME_CONFIG'] = data
            except Exception:
                pass
            return jsonify({'success': True}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration', 'error_code': 'SAVE_FAILED'}), 500

    except Exception as e:
        current_app.logger.error(f"Set game config error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Internal server error', 'error_code': 'INTERNAL_ERROR'}), 500


@mobile_api.route('/config/pit', methods=['GET'])
@token_required
def get_pit_config():
    """
    Return the pit configuration JSON for the mobile client's scouting team.

    Mirrors GET /api/mobile/config/game but returns the team's `pit_config.json`.
    Response:
    {
        "success": True,
        "config": { ... }
    }
    """
    try:
        requested_team = request.args.get('team') if request.args.get('team') not in (None, '') else None
        team_number = request.mobile_team_number if request.mobile_team_number else None
        if requested_team is not None:
            try:
                team_number = int(requested_team)
            except Exception:
                # ignore malformed team param
                pass

        # Prefer explicit per-team instance file if it exists
        from app.utils.config_manager import load_pit_config, merge_pit_configs
        pit_config = None
        try:
            if team_number is not None:
                base_dir = os.getcwd()
                team_config_path = os.path.join(base_dir, 'instance', 'configs', str(team_number), 'pit_config.json')
                current_app.logger.debug(f"mobile_api.get_pit_config: looking for team config at {team_config_path}")
                if os.path.exists(team_config_path):
                    with open(team_config_path, 'r', encoding='utf-8') as f:
                        try:
                            pit_config = json.load(f)
                        except Exception:
                            current_app.logger.warning(f"Invalid JSON in team pit_config for team {team_number}")
        except Exception:
            pit_config = None

        raw_requested = str(request.args.get('raw', '')).lower() in ('1', 'true', 'yes')

        if pit_config is None:
            current_app.logger.debug(f"mobile_api.get_pit_config: falling back to load_pit_config for team {team_number}")
            pit_config = load_pit_config(team_number=team_number)

        # When serving to mobile clients we generally want select/multiselect option
        # lists preserved. If the team's saved file omitted `options` then merge
        # the team config with the default `config/pit_config.json` so option
        # lists are available. If the caller requested raw JSON via `?raw=true`
        # return the file exactly as saved.
        if not raw_requested:
            try:
                default_cfg = load_pit_config(team_number=None)
                merged = merge_pit_configs(default_cfg or {}, pit_config or {})
                return jsonify({'success': True, 'config': merged}), 200
            except Exception:
                # Fall back to returning whatever we read if merging fails
                return jsonify({'success': True, 'config': pit_config}), 200

        return jsonify({'success': True, 'config': pit_config}), 200

    except Exception as e:
        current_app.logger.error(f"Get pit config error: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to retrieve pit configuration', 'error_code': 'CONFIG_ERROR'}), 500


@mobile_api.route('/config/pit', methods=['POST', 'PUT'])
@token_required
def set_pit_config():
    """
    Set or update the pit configuration for the mobile client's scouting team.

    Requires admin/superadmin roles. Request body must be a JSON object representing
    the pit configuration (same shape as config/pit_config.json).
    """
    try:
        user = getattr(request, 'mobile_user', None)
        if not user:
            return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401

        # Require admin or superadmin role to modify config
        if not (user.has_role('admin') or user.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Forbidden', 'error_code': 'FORBIDDEN'}), 403

        # Ensure flask-login current_user is set so save_pit_config can infer team
        try:
            login_user(user, remember=False, force=True)
        except Exception:
            pass

        data = request.get_json()
        if not data or not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'Missing or invalid JSON body', 'error_code': 'MISSING_BODY'}), 400

        from app.utils.config_manager import save_pit_config

        saved = save_pit_config(data)
        if saved:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration', 'error_code': 'SAVE_FAILED'}), 500

    except Exception as e:
        current_app.logger.error(f"Set pit config error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Internal server error', 'error_code': 'INTERNAL_ERROR'}), 500


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

        token_team_number = request.mobile_team_number

        graph_types_raw = payload.get('graph_types') or ['line', 'bar', 'radar']
        graph_types_normalized = [str(gt).lower() for gt in graph_types_raw if isinstance(gt, (str, bytes))]
        graph_types_set = set(graph_types_normalized)
        if not graph_types_set:
            graph_types_set = {'line'}

        metric = payload.get('metric') or 'total_points'
        metric_title = metric.replace('_', ' ').title()
        metric_alias = 'tot' if metric in ('total_points', 'points', 'tot') else metric
        data_view = payload.get('data_view') or 'averages'

        event_identifier = payload.get('event_id')
        event_obj = None
        resolved_event_id = None
        if event_identifier not in (None, ''):
            try:
                resolved_event_id = int(event_identifier)
            except Exception:
                resolved_event_id = None
            if resolved_event_id is not None:
                event_obj = Event.query.filter_by(id=resolved_event_id, scouting_team_number=token_team_number).first()
                if not event_obj:
                    event_obj = Event.query.get(resolved_event_id)
            if event_obj is None and isinstance(event_identifier, str):
                event_obj = Event.query.filter_by(code=event_identifier, scouting_team_number=token_team_number).first()
                if event_obj:
                    resolved_event_id = event_obj.id

        # Colors for datasets
        palette = ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40"]

        teams_response = []
        line_labels = set()
        team_series_entries = []
        radar_datasets = []

        # Ensure downstream helpers see the correct scouting team context (for calculate_team_metrics, etc.)
        try:
            g.scouting_team_number = token_team_number
        except Exception:
            pass

        mobile_user = getattr(request, 'mobile_user', None)
        if mobile_user:
            try:
                login_user(mobile_user, remember=False, force=True)
            except Exception:
                pass

        from app.utils.config_manager import load_game_config
        team_config = load_game_config(team_number=token_team_number) if token_team_number else None

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
            analytics = calculate_team_metrics(team.id, event_id=resolved_event_id, game_config=team_config)
            metrics = analytics.get('metrics', {})

            metric_value = metrics.get(metric)
            if metric_value is None and metric_alias != metric:
                metric_value = metrics.get(metric_alias)
            if metric_value is None:
                metric_value = metrics.get('total_points') or metrics.get('tot') or 0

            std_candidates = [f"{metric_alias}_std", f"{metric}_std", 'total_points_std', 'tot_std']
            std_value = next((metrics.get(k) for k in std_candidates if metrics.get(k) is not None), 0)

            # Build basic team entry
            team_entry = {
                'team_number': team.team_number,
                'team_name': team.team_name,
                'color': palette[idx % len(palette)],
                'value': metric_value,
                'std_dev': std_value or 0,
                'match_count': analytics.get('match_count') or 0
            }
            teams_response.append(team_entry)

            # Build per-match series for downstream chart handling
            q = ScoutingData.query.join(Match, ScoutingData.match_id == Match.id).filter(
                ScoutingData.team_id == team.id,
                ScoutingData.scouting_team_number == token_team_number
            )
            if resolved_event_id is not None:
                q = q.filter(Match.event_id == resolved_event_id)
            scouting_rows = q.order_by(Match.match_number).all()

            per_match_records = []
            metric_id_to_use = 'tot' if metric_alias == 'tot' else metric_alias
            for row in scouting_rows:
                try:
                    mnum = row.match.match_number if row.match else None
                except Exception:
                    mnum = None
                if mnum is None:
                    continue

                match_label = f"Match {mnum}"
                try:
                    raw_val = row.calculate_metric(metric_id_to_use)
                except Exception:
                    raw_val = 0

                try:
                    numeric_val = float(raw_val)
                except (TypeError, ValueError):
                    numeric_val = 0

                per_match_records.append({
                    'match_number': mnum,
                    'label': match_label,
                    'value': numeric_val
                })
                line_labels.add(match_label)

            team_series_entries.append({
                'team_number': team.team_number,
                'team_name': team.team_name,
                'color': palette[idx % len(palette)],
                'per_match': per_match_records,
                'values': [record['value'] for record in per_match_records if record['value'] is not None]
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

        def _line_label_sort_key(label):
            try:
                return int(str(label).replace('Match ', ''))
            except Exception:
                return label

        labels_sorted = sorted(list(line_labels), key=_line_label_sort_key) if line_labels else []

        line_datasets = []
        for series in team_series_entries:
            label_to_value = {record['label']: record['value'] for record in series['per_match'] if record.get('label')}
            if labels_sorted:
                data_aligned = [label_to_value.get(label) for label in labels_sorted]
            else:
                data_aligned = [record['value'] for record in series['per_match']]

            line_datasets.append({
                'label': f"{series['team_number']} - {series['team_name']}",
                'data': data_aligned,
                'borderColor': series['color'],
                'backgroundColor': series['color'],
                'tension': 0.4,
                'per_match': series['per_match']
            })

        graphs = {}
        if 'line' in graph_types_set:
            graphs['line'] = {
                'type': 'line',
                'labels': labels_sorted,
                'datasets': line_datasets
            }
        if 'bar' in graph_types_set:
            graphs['bar'] = {
                'type': 'bar',
                'labels': [str(t['team_number']) for t in teams_response],
                'datasets': [
                    {
                        'label': f'Average {metric_title}',
                        'data': [t['value'] for t in teams_response],
                        'backgroundColor': [t['color'] for t in teams_response]
                    }
                ]
            }
        if 'radar' in graph_types_set:
            graphs['radar'] = {
                'type': 'radar',
                'labels': ['Total Points', 'Auto Points', 'Teleop Points', 'Endgame Points', 'Consistency (%)'],
                'datasets': radar_datasets
            }

        histogram_requested = graph_types_set & {'hist', 'histogram'}
        if histogram_requested:
            histogram_datasets = []
            all_values = []
            for series in team_series_entries:
                if not series['values']:
                    continue
                values = series['values']
                dataset_entry = {
                    'team_number': series['team_number'],
                    'team_name': series['team_name'],
                    'color': series['color'],
                    'values': values,
                    'count': len(values),
                    'mean': sum(values) / len(values)
                }
                histogram_datasets.append(dataset_entry)
                all_values.extend(values)

            if histogram_datasets:
                if len(all_values) <= 1:
                    bin_suggestion = len(all_values)
                else:
                    bin_suggestion = max(5, min(20, int(math.sqrt(len(all_values)))))

                histogram_payload = {
                    'type': 'histogram',
                    'metric': metric,
                    'total_samples': len(all_values),
                    'overall_mean': (sum(all_values) / len(all_values)) if all_values else 0,
                    'bin_suggestion': bin_suggestion,
                    'datasets': histogram_datasets
                }
                graphs['histogram'] = histogram_payload
                if 'hist' in graph_types_set:
                    graphs['hist'] = histogram_payload

        if 'box' in graph_types_set:
            box_datasets = []
            for series in team_series_entries:
                values = series['values']
                if not values:
                    continue

                stats_summary = {
                    'count': len(values),
                    'min': min(values),
                    'max': max(values),
                    'median': statistics.median(values)
                }

                try:
                    quartiles = statistics.quantiles(values, n=4, method='inclusive')
                    if len(quartiles) >= 3:
                        stats_summary['q1'] = quartiles[0]
                        stats_summary['median'] = quartiles[1]
                        stats_summary['q3'] = quartiles[2]
                except Exception:
                    stats_summary['q1'] = stats_summary['median']
                    stats_summary['q3'] = stats_summary['median']

                box_datasets.append({
                    'team_number': series['team_number'],
                    'team_name': series['team_name'],
                    'color': series['color'],
                    'values': values,
                    'stats': stats_summary
                })

            if box_datasets:
                graphs['box'] = {
                    'type': 'box',
                    'metric': metric,
                    'datasets': box_datasets
                }

        if not event_obj and resolved_event_id is not None:
            event_obj = Event.query.get(resolved_event_id)

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


@mobile_api.route('/graphs', methods=['POST'])
@token_required
def mobile_graphs_image():
    """
    Generate a graph image for a single team or teams and return PNG bytes.

    Request JSON (examples):
    {
      "team_numbers": [5454],            # or single "team_number": 5454
      "graph_type": "line",            # line|bar|radar|scatter
      "metric": "total_points",        # metric id
      "weather": "sunny",              # optional, passthrough for future use
      "mode": "match_by_match"         # match_by_match | averages
    }

    Response: image/png bytes with Content-Type set. If image libs unavailable,
    returns JSON error.
    """
    try:
        payload = request.get_json() or {}
        # Accept either team_number or team_numbers
        from app.utils.api_utils import safe_int_team_number
        team_numbers = []
        if 'team_numbers' in payload and isinstance(payload.get('team_numbers'), (list, tuple)):
            for t in payload.get('team_numbers'):
                parsed = safe_int_team_number(t)
                if parsed is not None:
                    team_numbers.append(parsed if isinstance(parsed, int) else str(parsed))
        elif 'team_number' in payload:
            parsed = safe_int_team_number(payload.get('team_number'))
            if parsed is not None:
                team_numbers = [parsed if isinstance(parsed, int) else str(parsed)]

        if not team_numbers:
            return jsonify({'success': False, 'error': 'team_number(s) required', 'error_code': 'MISSING_TEAMS'}), 400

        graph_type = (payload.get('graph_type') or 'line').lower()
        if graph_type == 'hist':
            graph_type = 'histogram'
        metric = payload.get('metric') or 'total_points'
        metric_title = metric.replace('_', ' ').title()
        mode = (payload.get('mode') or 'match_by_match')

        token_team_number = request.mobile_team_number

        event_identifier = payload.get('event_id')
        event_obj = None
        resolved_event_id = None
        if event_identifier not in (None, ''):
            try:
                resolved_event_id = int(event_identifier)
            except Exception:
                resolved_event_id = None
            if resolved_event_id is not None:
                event_obj = Event.query.filter_by(id=resolved_event_id, scouting_team_number=token_team_number).first()
                if not event_obj:
                    event_obj = Event.query.get(resolved_event_id)
            if event_obj is None and isinstance(event_identifier, str):
                event_obj = Event.query.filter_by(code=event_identifier, scouting_team_number=token_team_number).first()
                if event_obj:
                    resolved_event_id = event_obj.id

        # Mirror the visualize endpoint: set team context so calculate_team_metrics and form helpers work
        try:
            g.scouting_team_number = token_team_number
        except Exception:
            pass

        mobile_user = getattr(request, 'mobile_user', None)
        if mobile_user:
            try:
                login_user(mobile_user, remember=False, force=True)
            except Exception:
                pass

        from app.utils.config_manager import load_game_config
        team_config = load_game_config(team_number=token_team_number) if token_team_number else None

        # Resolve teams (respect team isolation like compare endpoint)
        teams = []
        for tn in team_numbers:
            t = Team.query.filter_by(team_number=tn, scouting_team_number=token_team_number).first()
            if not t:
                t = Team.query.filter_by(team_number=tn).first()
            if t:
                teams.append(t)

        if not teams:
            return jsonify({'success': False, 'error': 'No teams found', 'error_code': 'NO_TEAMS'}), 404

        # Build minimal team_data dict compatible with graphs.py helpers
        team_ids = [t.id for t in teams]
        scouting_query = ScoutingData.query.join(Match, ScoutingData.match_id == Match.id).filter(
            ScoutingData.team_id.in_(team_ids),
            ScoutingData.scouting_team_number == token_team_number
        )
        if resolved_event_id is not None:
            scouting_query = scouting_query.filter(Match.event_id == resolved_event_id)
        scouting_rows = scouting_query.order_by(Match.match_number).all()

        # Map common metric names to metric IDs used by calculate_metric()
        metric_id_map = {
            'total_points': 'tot',
            'auto_points': 'apt',
            'teleop_points': 'tpt',
            'endgame_points': 'ept',
            'points': 'tot',
            'tot': 'tot',
            'apt': 'apt',
            'tpt': 'tpt',
            'ept': 'ept'
        }
        
        metric_id = metric_id_map.get(metric, metric)
        current_app.logger.info(f"Building team_data for metric '{metric}' (mapped to ID '{metric_id}')")
        current_app.logger.info(f"Found {len(scouting_rows)} scouting rows to process")
        
        team_data = {}
        for row in scouting_rows:
            teamnum = row.team.team_number if row.team else None
            if teamnum is None:
                continue
            if teamnum not in team_data:
                team_data[teamnum] = {'team_name': row.team.team_name if row.team else '', 'matches': []}
            
            # Calculate the specific metric requested for this match
            try:
                # Log the raw data to see what we're working with
                current_app.logger.info(f"Team {teamnum}, Match {row.match.match_number if row.match else '?'}: data keys = {list(row.data.keys())[:10] if hasattr(row, 'data') else 'NO DATA'}")
                
                raw_val = row.calculate_metric(metric_id)

                try:
                    val = float(raw_val)
                except (TypeError, ValueError):
                    val = 0.0

                current_app.logger.info(f"Team {teamnum}, Match {row.match.match_number if row.match else '?'}: {metric_id} = {val}")

                # Also try calculating tot to compare
                if metric_id != 'tot':
                    tot_val_raw = row.calculate_metric('tot')
                    try:
                        tot_val = float(tot_val_raw)
                    except (TypeError, ValueError):
                        tot_val = tot_val_raw
                    current_app.logger.info(f"  (total points for comparison: {tot_val})")
            except Exception as e:
                import traceback
                current_app.logger.error(f"Error calculating metric '{metric_id}' for team {teamnum}: {e}\n{traceback.format_exc()}")
                val = 0
                
            team_data[teamnum]['matches'].append({
                'match_number': row.match.match_number if row.match else None,
                'metric_value': val
            })
        
        current_app.logger.info(f"Final team_data: {json.dumps({k: {'matches': len(v['matches'])} for k, v in team_data.items()})}")

        # Create a plotly figure using existing helper functions where possible
        import plotly.graph_objects as go
        import plotly.io as pio
        from io import BytesIO

        # Simple rendering: if single team and match_by_match -> line chart
        fig = None
        try:
            if graph_type == 'bar':
                # bar of averages per team
                labels = []
                values = []
                for t in teams:
                    nums = [m['metric_value'] for m in team_data.get(t.team_number, {}).get('matches', [])]
                    avg = sum(nums) / len(nums) if nums else 0
                    labels.append(str(t.team_number))
                    values.append(avg)
                fig = go.Figure(data=[go.Bar(x=labels, y=values)])
                fig.update_layout(xaxis_title='Team', yaxis_title=metric_title)
            elif graph_type in ('line', 'scatter'):
                # line per team across matches
                for idx, t in enumerate(teams):
                    matches = team_data.get(t.team_number, {}).get('matches', [])
                    x = [f"Match {m['match_number']}" for m in matches if m['match_number'] is not None]
                    y = [m['metric_value'] for m in matches if m['match_number'] is not None]
                    if graph_type == 'line':
                        fig = fig or go.Figure()
                        fig.add_trace(go.Scatter(x=x, y=y, mode='lines+markers', name=str(t.team_number)))
                    else:
                        fig = fig or go.Figure()
                        fig.add_trace(go.Scatter(x=x, y=y, mode='markers', name=str(t.team_number)))
                fig = fig or go.Figure()
                fig.update_layout(xaxis_title='Match', yaxis_title=metric_title)
            elif graph_type == 'radar':
                # radar: reuse compare radar labels
                labels = ['Total Points', 'Auto Points', 'Teleop Points', 'Endgame Points', 'Consistency (%)']
                fig = go.Figure()
                for t in teams:
                    analytics = calculate_team_metrics(t.id, event_id=resolved_event_id, game_config=team_config)
                    metrics = analytics.get('metrics', {})
                    radar_metrics = [
                        metrics.get('total_points') or metrics.get('tot') or 0,
                        metrics.get('auto_points') or metrics.get('apt') or 0,
                        metrics.get('teleop_points') or metrics.get('tpt') or 0,
                        metrics.get('endgame_points') or metrics.get('ept') or 0,
                        round((metrics.get('consistency') or 0) * 100, 2) if metrics.get('consistency') is not None else 0
                    ]
                    fig.add_trace(go.Scatterpolar(r=radar_metrics, theta=labels, fill='toself', name=str(t.team_number)))
            elif graph_type == 'histogram':
                fig = go.Figure()
                for t in teams:
                    matches = team_data.get(t.team_number, {}).get('matches', [])
                    values = [m['metric_value'] for m in matches if m['metric_value'] is not None]
                    if not values:
                        continue
                    fig.add_trace(go.Histogram(x=values, name=str(t.team_number), opacity=0.75))
                fig.update_layout(barmode='overlay', xaxis_title=metric_title, yaxis_title='Frequency')
            elif graph_type == 'box':
                fig = go.Figure()
                for t in teams:
                    matches = team_data.get(t.team_number, {}).get('matches', [])
                    values = [m['metric_value'] for m in matches if m['metric_value'] is not None]
                    if not values:
                        continue
                    fig.add_trace(go.Box(y=values, name=str(t.team_number), boxmean=True))
                fig.update_layout(xaxis_title='Team', yaxis_title=metric_title)
            else:
                fig = go.Figure()

            # Apply a minimal layout
            fig.update_layout(margin=dict(l=20, r=20, t=30, b=20), template='plotly_white')

            # Convert to PNG using plotly.io if available
            try:
                img_bytes = pio.to_image(fig, format='png')
            except Exception:
                # Fallback to kaleido via write_image to a buffer
                buf = BytesIO()
                try:
                    pio.write_image(fig, buf, format='png')
                    img_bytes = buf.getvalue()
                except Exception as e:
                    current_app.logger.error(f"Graph image generation error: {str(e)}")
                    # If we cannot produce an image, fall back to returning the
                    # Plotly JSON representation so clients can render client-side.
                    try:
                        plot_json = fig.to_json()
                        return jsonify({'success': True, 'fallback_plotly_json': json.loads(plot_json)}), 200
                    except Exception:
                        return jsonify({'success': False, 'error': 'Server cannot generate images (missing dependencies)', 'error_code': 'IMAGE_LIB_MISSING'}), 500

            # Return PNG bytes
            from flask import make_response
            resp = make_response(img_bytes)
            resp.headers.set('Content-Type', 'image/png')
            resp.headers.set('Content-Disposition', 'inline; filename=graph.png')
            return resp

        except Exception as e:
            current_app.logger.error(f"mobile_graphs_image error: {str(e)}\n{traceback.format_exc()}")
            return jsonify({'success': False, 'error': 'Failed to generate graph image', 'error_code': 'GRAPH_IMAGE_ERROR'}), 500

    except Exception as e:
        current_app.logger.error(f"mobile_graphs_image top-level error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Invalid request', 'error_code': 'INVALID_REQUEST'}), 400


@mobile_api.route('/graphs/visualize', methods=['POST'])
@token_required
def mobile_graphs_visualize():
    """
    Generate a visualization using the Assistant Visualizer and return PNG bytes.

    Request JSON:
    {
      "vis_type": "team_performance",  # visualization type supported by Visualizer
      "team_numbers": [5454, 1234],     # optional list of team numbers
      "team_number": 5454,              # optional single team_number
      "visualization_data": {...}       # optional pre-built visualization_data to pass through
    }

    Response: image/png bytes
    """
    try:
        payload = request.get_json() or {}
        # Log payload for easier debugging in case of failures
        try:
            current_app.logger.debug(f"mobile_graphs_visualize payload: {json.dumps(payload)[:1000]}")
        except Exception:
            current_app.logger.debug("mobile_graphs_visualize payload (unserializable)")

        # If the payload looks like the Plotly-style /api/mobile/graphs request
        # (contains graph_type / graph_types / metric / mode), delegate to the
        # existing mobile_graphs_image implementation so we support all of its
        # options and fallbacks without duplicating the logic.
        if any(k in payload for k in ('graph_type', 'graph_types', 'metric', 'mode')):
            # mobile_graphs_image returns a Flask Response; just return it.
            return mobile_graphs_image()

        vis_type = (payload.get('vis_type') or payload.get('type') or 'team_performance')

        # If client provided visualization_data directly, use it
        data = payload.get('visualization_data') or {}

        token_team_number = request.mobile_team_number
        
        # CRITICAL FIX: Store scouting_team_number in Flask's g object
        # This allows get_current_scouting_team_number() to access it reliably
        # Flask-Login doesn't work properly for API requests, so we use g instead
        g.scouting_team_number = token_team_number
        
        mobile_user = request.mobile_user
        current_app.logger.info(f"mobile_graphs_visualize: user={mobile_user.username if mobile_user else 'None'}, scouting_team={token_team_number}")
        current_app.logger.info(f"Set g.scouting_team_number = {g.scouting_team_number} for team isolation")
        
        # Also log in the mobile user for Flask-Login compatibility (some code might still use current_user)
        if mobile_user:
            login_user(mobile_user, remember=False, force=True)
            current_app.logger.debug(f"Logged in mobile user: {mobile_user.username} (scouting_team={mobile_user.scouting_team_number})")

        # Get current event for this scouting team to scope data correctly
        from app.utils.config_manager import load_game_config
        game_config = load_game_config(team_number=token_team_number)
        event_code = game_config.get('current_event_code') if isinstance(game_config, dict) else None
        
        # Resolve event_id from payload or from config
        event_id = payload.get('event_id')
        event = None
        if event_id:
            try:
                event = Event.query.filter_by(id=int(event_id), scouting_team_number=token_team_number).first()
            except Exception:
                pass
        
        if not event and event_code:
            event = Event.query.filter_by(code=event_code, scouting_team_number=token_team_number).first()
        
        if not event:
            event = Event.query.filter_by(scouting_team_number=token_team_number).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).first()
        
        event_id = event.id if event else None
        current_app.logger.debug(f"mobile_graphs_visualize using event_id={event_id} for team {token_team_number}")

        # Build simple team/teams data if not provided
        team_numbers = []
        if not data:
            if 'team_numbers' in payload and isinstance(payload.get('team_numbers'), (list, tuple)):
                team_numbers = [t for t in payload.get('team_numbers')]
            elif 'team_number' in payload:
                team_numbers = [payload.get('team_number')]

            # If no visualization_data and no team identifiers were provided, return informative error
            if not data and not team_numbers:
                return jsonify({'success': False, 'error': 'No team_number(s) or visualization_data provided', 'error_code': 'MISSING_TEAMS_OR_DATA'}), 400

            teams = []
            for tn in team_numbers:
                try:
                    tn_int = int(tn)
                except Exception:
                    continue
                t = Team.query.filter_by(team_number=tn_int, scouting_team_number=token_team_number).first()
                if not t:
                    t = Team.query.filter_by(team_number=tn_int).first()
                if not t:
                    continue

                # Pass event_id to get scoped metrics
                current_app.logger.debug(f"Calculating metrics for team {t.team_number} (id={t.id}) with event_id={event_id}")
                analytics = calculate_team_metrics(t.id, event_id=event_id)
                stats = analytics.get('metrics', {})
                match_count = analytics.get('match_count', 0)
                current_app.logger.info(f"Team {t.team_number}: match_count={match_count}, stats_keys={list(stats.keys())[:5] if stats else 'none'}")
                
                # Get actual match data for visualizations that need it
                matches_data = []
                if event_id:
                    scouting_rows = ScoutingData.query.join(Match, ScoutingData.match_id == Match.id).filter(
                        ScoutingData.team_id == t.id,
                        ScoutingData.scouting_team_number == token_team_number,
                        Match.event_id == event_id
                    ).order_by(Match.match_number).all()
                    current_app.logger.debug(f"Found {len(scouting_rows)} scouting rows for team {t.team_number}")
                    
                    for row in scouting_rows:
                        try:
                            match_num = row.match.match_number if row.match else None
                            if match_num:
                                # Calculate actual points from this match's scouting data using dynamic calculation
                                try:
                                    auto = row.calculate_metric('apt') if hasattr(row, 'calculate_metric') else 0
                                    teleop = row.calculate_metric('tpt') if hasattr(row, 'calculate_metric') else 0
                                    endgame = row.calculate_metric('ept') if hasattr(row, 'calculate_metric') else 0
                                    total = row.calculate_metric('tot') if hasattr(row, 'calculate_metric') else (auto + teleop + endgame)
                                except Exception as calc_err:
                                    current_app.logger.warning(f"Error calculating metrics for match {match_num}: {calc_err}")
                                    auto = teleop = endgame = total = 0
                                
                                matches_data.append({
                                    'match_number': match_num,
                                    'score': total,  # visualizer expects 'score' or 'total'
                                    'auto_points': auto,
                                    'teleop_points': teleop,
                                    'endgame_points': endgame
                                })
                        except Exception as e:
                            current_app.logger.warning(f"Error processing match data: {e}")
                            continue
                
                # Ensure we have the required stats - if empty or no data, create minimal valid stats
                if not stats or match_count == 0:
                    current_app.logger.warning(f"No scouting data for team {t.team_number} - using zero stats")
                    stats = {
                        'auto_points': 0,
                        'teleop_points': 0,
                        'endgame_points': 0,
                        'total_points': 0,
                        'data_quality_score': 0,
                        'prediction_confidence': 0
                    }
                
                teams.append({
                    'number': t.team_number,
                    'team_name': t.team_name,
                    'stats': stats,
                    'match_count': match_count,
                    'matches': matches_data
                })

            # If we couldn't resolve any teams, return a clear JSON 404 rather than letting a later error produce HTML
            if not teams:
                current_app.logger.info(f"mobile_graphs_visualize: no teams resolved for payload: {payload}")
                return jsonify({'success': False, 'error': 'No teams found', 'error_code': 'NO_TEAMS'}), 404

            # Decide whether visualization expects a single team or multiple
            if teams and (str(vis_type).startswith('team') or 'team' in vis_type or vis_type in ('team_performance', 'match_breakdown', 'team_ranking', 'ranking_comparison')):
                data = {'team': teams[0]}
            else:
                data = {'teams': teams}

        viz = Visualizer()
        result = viz.generate_visualization(vis_type, data)

        if result.get('error'):
            return jsonify({'success': False, 'error': result.get('message', 'Visualization error'), 'error_code': 'VIS_ERROR'}), 500

        img_b64 = result.get('image')
        if not img_b64:
            return jsonify({'success': False, 'error': 'No image produced', 'error_code': 'NO_IMAGE'}), 500

        img_bytes = base64.b64decode(img_b64)

        from flask import make_response
        resp = make_response(img_bytes)
        resp.headers.set('Content-Type', 'image/png')
        resp.headers.set('Content-Disposition', 'inline; filename=visualization.png')
        return resp

    except Exception as e:
        current_app.logger.error(f"mobile_graphs_visualize error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to generate visualization', 'error_code': 'VIS_GEN_ERROR'}), 500


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


@mobile_api.route('/notifications/scheduled', methods=['GET'])
@token_required
def get_scheduled_notifications():
    """
    Return pending scheduled notifications for the scouting team.

    Response:
    {
      "success": true,
      "notifications": [
         {
           "id": 123,
           "subscription_id": 5,
           "notification_type": "match_reminder",
           "match_id": 10,
           "match_number": 3,
           "event_id": 7,
           "event_code": "CALA",
           "scheduled_for": "2024-01-01T12:00:00Z",
           "status": "pending",
           "attempts": 0,
           "delivery_methods": {"email": true, "push": true},
           "target_team_number": 5454,
           "minutes_before": 20,
           "weather": null
         }
      ]
    }
    """
    try:
        team_number = request.mobile_team_number
        # Use naive UTC for database comparison since SQLite stores naive datetimes
        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)

        # Join queue to subscription so we can scope by scouting_team_number
        q = NotificationQueue.query.join(NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id).filter(
            NotificationSubscription.scouting_team_number == team_number,
            NotificationQueue.status == 'pending',
            NotificationQueue.scheduled_for > now_utc_naive
        ).order_by(NotificationQueue.scheduled_for)

        limit = min(request.args.get('limit', 200, type=int), 1000)
        offset = request.args.get('offset', 0, type=int)

        total = q.count()
        rows = q.offset(offset).limit(limit).all()

        notifications = []
        for row in rows:
            try:
                sub = NotificationSubscription.query.get(row.subscription_id)
            except Exception:
                sub = None

            # Load related match and event info if available
            match_obj = Match.query.get(row.match_id) if row.match_id else None
            event_obj = match_obj.event if match_obj and hasattr(match_obj, 'event') else None

            delivery = {'email': False, 'push': False}
            if sub:
                delivery['email'] = bool(sub.email_enabled)
                delivery['push'] = bool(sub.push_enabled)

            notifications.append({
                'id': row.id,
                'subscription_id': row.subscription_id,
                'notification_type': sub.notification_type if sub else None,
                'match_id': row.match_id,
                'match_number': match_obj.match_number if match_obj else None,
                'event_id': event_obj.id if event_obj else None,
                'event_code': event_obj.code if event_obj else None,
                'scheduled_for': row.scheduled_for.isoformat() if row.scheduled_for else None,
                'status': row.status,
                'attempts': row.attempts,
                'delivery_methods': delivery,
                'target_team_number': sub.target_team_number if sub else None,
                'minutes_before': sub.minutes_before if sub else None,
                # Weather not provided by server yet; clients may fetch their own weather if needed
                'weather': None
            })

        return jsonify({'success': True, 'count': len(notifications), 'total': total, 'notifications': notifications}), 200

    except Exception as e:
        current_app.logger.error(f"Get scheduled notifications error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to retrieve scheduled notifications', 'error_code': 'NOTIFICATIONS_ERROR'}), 500


@mobile_api.route('/notifications/past', methods=['GET'])
@token_required
def get_past_notifications():
    """
    Return past/sent notifications (NotificationLog) for the scouting team.

    Query params (optional):
    - limit (int) - max results (default 200, max 1000)
    - offset (int) - pagination offset (default 0)

    Response:
    {
      "success": true,
      "count": 1,
      "total": 12,
      "notifications": [
        {
          "id": 123,
          "subscription_id": 5,
          "notification_type": "match_reminder",
          "match_id": 10,
          "match_number": 3,
          "event_code": "CALA",
          "sent_at": "2025-04-12T18:20:00+00:00",
          "email_sent": true,
          "push_sent_count": 2,
          "email_error": null,
          "push_error": null,
          "title": "Match reminder",
          "message": "Match 3 coming up in 20 minutes",
          "target_team_number": 5454
        }
      ]
    }
    """
    try:
        team_number = request.mobile_team_number

        q = NotificationLog.query.join(NotificationSubscription, NotificationLog.subscription_id == NotificationSubscription.id).filter(
            NotificationSubscription.scouting_team_number == team_number
        ).order_by(NotificationLog.sent_at.desc())

        limit = min(request.args.get('limit', 200, type=int), 1000)
        offset = request.args.get('offset', 0, type=int)

        total = q.count()
        rows = q.offset(offset).limit(limit).all()

        notifications = []
        for row in rows:
            try:
                sub = NotificationSubscription.query.get(row.subscription_id) if row.subscription_id else None
            except Exception:
                sub = None

            match_obj = Match.query.get(row.match_id) if row.match_id else None

            delivery = {'email': bool(getattr(row, 'email_sent', False)), 'push': bool(getattr(row, 'push_sent_count', 0) > 0)}

            notifications.append({
                'id': row.id,
                'subscription_id': row.subscription_id,
                'notification_type': row.notification_type,
                'match_id': row.match_id,
                'match_number': match_obj.match_number if match_obj else None,
                'event_code': row.event_code if row.event_code else (match_obj.event.code if match_obj and hasattr(match_obj, 'event') and match_obj.event else None),
                'sent_at': row.sent_at.isoformat() if row.sent_at else None,
                'email_sent': bool(row.email_sent),
                'push_sent_count': int(row.push_sent_count or 0),
                'email_error': row.email_error,
                'push_error': row.push_error,
                'title': row.title,
                'message': row.message,
                'target_team_number': sub.target_team_number if sub else row.team_number
            })

        return jsonify({'success': True, 'count': len(notifications), 'total': total, 'notifications': notifications}), 200

    except Exception as e:
        current_app.logger.error(f"Get past notifications error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to retrieve past notifications', 'error_code': 'NOTIFICATIONS_ERROR'}), 500


@mobile_api.route('/chat/all', methods=['GET'])
@token_required
def get_user_and_team_chats():
    """
    Fetch all chat messages authored by the current user or by any team that
    belongs to the same scouting_team_number as the authenticated user.

    Query params:
    - limit (int, default 200)
    - offset (int, default 0)

    Response:
    {
      "success": true,
      "count": 10,
      "total": 123,
      "messages": [ ... ]
    }
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number

        # All team numbers that belong to this scouting_team_number
        teams = Team.query.filter_by(scouting_team_number=team_number).all()
        team_numbers = [t.team_number for t in teams]

        # If no teams are registered for this scouting team, return empty
        if not team_numbers:
            return jsonify({'success': True, 'count': 0, 'total': 0, 'messages': []}), 200

        # Build query: messages authored by the requesting user OR authored by any
        # team number that belongs to this scouting team.
        q = ScoutingAllianceChat.query.filter(
            db.or_(
                ScoutingAllianceChat.from_username == user.username,
                ScoutingAllianceChat.from_team_number.in_(team_numbers)
            )
        )

        limit = min(request.args.get('limit', 200, type=int), 2000)
        offset = request.args.get('offset', 0, type=int)

        total = q.count()
        rows = q.order_by(ScoutingAllianceChat.created_at.desc()).offset(offset).limit(limit).all()

        messages = [r.to_dict() for r in rows]

        return jsonify({'success': True, 'count': len(messages), 'total': total, 'messages': messages}), 200

    except Exception as e:
        current_app.logger.error(f"Get user/team chats error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to retrieve chats', 'error_code': 'CHAT_FETCH_ERROR'}), 500


@mobile_api.route('/chat/members', methods=['GET'])
@token_required
def chat_members():
    """
    List users the authenticated mobile user is allowed to message.

    Query params:
    - scope: 'team' (default) or 'alliance'
    - team_number: optional integer to restrict to a specific member team's users

    Rules:
    - 'team' scope returns users with the same `scouting_team_number` as the token.
    - 'alliance' scope returns users who belong to teams that are members of the
      requesting team's active alliance (if any) OR users in the requesting team.
    - If `team_number` is provided, the request is allowed only when that team
      is the requesting user's scouting team or is part of the active alliance.
    """
    try:
        user = request.mobile_user
        token_team_number = request.mobile_team_number

        scope = (request.args.get('scope') or 'team').lower()
        q_team_number = request.args.get('team_number', type=int)

        # Helper to serialize users
        def serialize(u):
            return {
                'id': u.id,
                'username': u.username,
                'display_name': getattr(u, 'display_name', None) or u.username,
                'team_number': u.scouting_team_number,
                'profile_picture': u.profile_picture
            }

        # Resolve active alliance for token team (may be None)
        alliance = TeamAllianceStatus.get_active_alliance_for_team(token_team_number)
        alliance_member_team_numbers = alliance.get_member_team_numbers() if alliance else []

        # If a specific team_number was requested, validate scope permissions
        if q_team_number:
            if q_team_number == token_team_number:
                users = User.query.filter_by(scouting_team_number=token_team_number, is_active=True).all()
            elif scope == 'alliance' and q_team_number in alliance_member_team_numbers:
                users = User.query.filter_by(scouting_team_number=q_team_number, is_active=True).all()
            else:
                return jsonify({'success': False, 'error': 'Requested team not in scope', 'error_code': 'USER_NOT_IN_SCOPE'}), 403

        else:
            # No specific team requested — return according to scope
            if scope == 'alliance' and alliance:
                # Return users from all alliance member teams plus local team users
                team_nums = set(alliance_member_team_numbers)
                team_nums.add(token_team_number)
                users = User.query.filter(User.scouting_team_number.in_(list(team_nums)), User.is_active == True).all()
            else:
                # Default: team scope
                users = User.query.filter_by(scouting_team_number=token_team_number, is_active=True).all()

        members = [serialize(u) for u in users]

        return jsonify({'success': True, 'members': members, 'count': len(members)}), 200

    except Exception as e:
        current_app.logger.error(f"chat_members error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to retrieve chat members', 'error_code': 'CHAT_MEMBERS_ERROR'}), 500


@mobile_api.route('/chat/state', methods=['GET'])
@token_required
def mobile_chat_state():
    """
    Return the per-user persisted chat state (unread count, joined groups, last source, etc.)

    Response:
    {
      "success": true,
      "state": {
         "joinedGroups": [],
         "currentGroup": "",
         "lastDmUser": "",
         "unreadCount": 0,
         "lastSource": {"type": "dm", "id": "other_user"},
         "notified": true,
         "lastNotified": "2025-04-12T18:20:00+00:00"
      }
    }
    """
    try:
        user = request.mobile_user
        # Prefer token-scoped team number but fall back to user's stored scouting_team_number
        team_number = request.mobile_team_number or getattr(user, 'scouting_team_number', 'no_team') or 'no_team'

        # Use the canonical helper from main to locate the user's state file so
        # we honor legacy filenames and team-resolution logic.
        try:
            from app.routes.main import get_user_chat_state_file
            state_file = get_user_chat_state_file(user.username)
        except Exception:
            from app import normalize_username
            state_folder = os.path.join(current_app.instance_path, 'chat', 'users', str(team_number))
            os.makedirs(state_folder, exist_ok=True)
            state_file = os.path.join(state_folder, f'chat_state_{normalize_username(user.username)}.json')

        state = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as sf:
                    state = json.load(sf) or {}
            except Exception:
                state = {}

        # Ensure minimal expected fields exist for mobile clients
        if 'unreadCount' not in state:
            state['unreadCount'] = 0
        if 'joinedGroups' not in state:
            state['joinedGroups'] = []
        if 'currentGroup' not in state:
            state['currentGroup'] = ''
        if 'lastDmUser' not in state:
            state['lastDmUser'] = ''

        # Include the actual unread message objects when possible. The persisted
        # state contains only an unreadCount and an optional lastSource pointer
        # (e.g. {type: 'dm', id: '<username>'}). We'll attempt to load the
        # corresponding history and return up to `unreadCount` messages that are
        # intended for the requesting user. This is a best-effort approach when
        # no explicit last-read marker is available.
        unread_messages = []
        try:
            from app import load_user_chat_history, load_group_chat_history

            n_unread = int(state.get('unreadCount', 0) or 0)
            last_src = state.get('lastSource') if isinstance(state.get('lastSource'), dict) else None

            if n_unread > 0 and last_src:
                src_type = str(last_src.get('type') or '').lower()
                src_id = last_src.get('id')

                # Direct messages: load the DM history between the two users and
                # pick the most recent messages that were sent to the requester
                # by the lastSource user.
                if src_type == 'dm' and src_id:
                    try:
                        history = load_user_chat_history(user.username, src_id, team_number) or []
                        # Sort chronologically by timestamp (oldest -> newest)
                        hist_sorted = sorted(history, key=lambda m: (m.get('timestamp') or m.get('created_at') or ''))
                        uname_l = str(user.username).strip().lower()
                        partner_l = str(src_id).strip().lower()
                        # Select messages where recipient is the requesting user and
                        # sender matches the partner (case-insensitive)
                        candidate = [m for m in hist_sorted if str(m.get('recipient') or '').strip().lower() == uname_l and str(m.get('sender') or '').strip().lower() == partner_l]
                        if candidate:
                            # Return the last N of these messages
                            unread_messages = candidate[-n_unread:]
                    except Exception:
                        unread_messages = []

                # Group messages: load the group history and return the most
                # recent N messages not authored by the requesting user.
                elif src_type == 'group' and src_id:
                    try:
                        grp_hist = load_group_chat_history(team_number, src_id) or []
                        grp_sorted = sorted(grp_hist, key=lambda m: (m.get('timestamp') or m.get('created_at') or ''))
                        candidate = [m for m in grp_sorted if str(m.get('sender') or '').strip().lower() != str(user.username).strip().lower()]
                        if candidate:
                            unread_messages = candidate[-n_unread:]
                    except Exception:
                        unread_messages = []

            # If the lastSource-based selection returned fewer messages than
            # the persisted unreadCount, fall back to scanning all DM and
            # group histories for messages addressed to the user and return
            # the most recent N across all conversations. This handles cases
            # where unreadCount aggregates across multiple conversations.
            if n_unread > 0 and (not unread_messages or len(unread_messages) < n_unread):
                try:
                    import glob
                    import os as _os

                    uname_norm = str(user.username).strip().lower()
                    team_dir = _os.path.join(current_app.instance_path, 'chat', 'users', str(team_number))
                    dm_pattern = _os.path.join(team_dir, f'*_chat_history.json')
                    dm_files = glob.glob(dm_pattern) if _os.path.exists(team_dir) else []

                    candidates_all = []
                    for fp in dm_files:
                        try:
                            with open(fp, 'r', encoding='utf-8') as fh:
                                data = json.load(fh)
                                if isinstance(data, list):
                                    for m in data:
                                        try:
                                            sender_norm = str(m.get('sender') or '').strip().lower()
                                            recip_norm = str(m.get('recipient') or '').strip().lower()
                                            # Exclude messages authored by the requesting user
                                            if recip_norm == uname_norm and sender_norm != uname_norm:
                                                candidates_all.append(m)
                                        except Exception:
                                            continue
                        except Exception:
                            continue

                    # Also include recent group messages where the user is not the sender.
                    group_dir = _os.path.join(current_app.instance_path, 'chat', 'groups', str(team_number))
                    if _os.path.exists(group_dir):
                        for gf in _os.listdir(group_dir):
                            if not gf.endswith('_group_chat_history.json'):
                                continue
                            gpath = _os.path.join(group_dir, gf)
                            try:
                                with open(gpath, 'r', encoding='utf-8') as gh:
                                    gdata = json.load(gh)
                                    if isinstance(gdata, list):
                                        for m in gdata:
                                            try:
                                                if str(m.get('sender') or '').strip().lower() != uname_norm:
                                                    candidates_all.append(m)
                                            except Exception:
                                                continue
                            except Exception:
                                continue

                    # Sort by timestamp and return the most recent n_unread
                    def _ts_key(m):
                        return (m.get('timestamp') or m.get('created_at') or '')

                    candidates_sorted = sorted(candidates_all, key=_ts_key)
                    if candidates_sorted:
                        unread_messages = candidates_sorted[-n_unread:]
                except Exception:
                    # Keep prior unread_messages if fallback fails
                    pass

            # Attach to response state using camelCase key for mobile clients
            state['unreadMessages'] = unread_messages
        except Exception:
            # Non-fatal: if any error occurs while collecting unread messages,
            # fall back to returning the persisted state without the messages.
            state['unreadMessages'] = []

        return jsonify({'success': True, 'state': state}), 200

    except Exception as e:
        current_app.logger.error(f"mobile_chat_state error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to retrieve chat state', 'error_code': 'CHAT_STATE_ERROR'}), 500


@mobile_api.route('/chat/groups', methods=['GET'])
@token_required
def chat_groups():
    """
    List groups for the authenticated user's scouting team and whether the user is a member.

    Response:
    {
      "success": true,
      "groups": [ { "name": "main", "member_count": 3, "is_member": true }, ... ],
      "count": 3
    }
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number

        groups = []
        # Group files stored under instance/chat/groups/<team_number>/
        group_dir = os.path.join(current_app.instance_path, 'chat', 'groups', str(team_number))
        if os.path.exists(group_dir):
            for fname in os.listdir(group_dir):
                if not fname:
                    continue
                # Consider both history and members files
                if fname.endswith('_group_chat_history.json') or fname.endswith('_members.json'):
                    name = fname.replace('_group_chat_history.json', '').replace('_members.json', '')
                    if any(g['name'] == name for g in groups):
                        continue
                    try:
                        members = load_group_members(team_number, name) or []
                    except Exception:
                        members = []

                    # Determine membership case-insensitively to tolerate casing differences
                    try:
                        uname_norm = str(user.username).strip().lower()
                        is_member = any(str(m).strip().lower() == uname_norm for m in (members or []))
                    except Exception:
                        is_member = False

                    # Only expose groups where the requesting user is actually a member.
                    # This prevents history-only groups (where the user has past messages)
                    # from appearing in the user's visible group list after they've left.
                    if not is_member:
                        continue

                    groups.append({
                        'name': name,
                        'member_count': len(members),
                        'is_member': is_member
                    })

        return jsonify({'success': True, 'groups': groups, 'count': len(groups)}), 200
    except Exception as e:
        current_app.logger.error(f"chat_groups error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to list groups', 'error_code': 'GROUPS_ERROR'}), 500


@mobile_api.route('/chat/groups', methods=['POST'])
@token_required
def chat_create_group():
    """
    Create a named group for the team. Body: { "group": "pit", "members": ["user1","user2"] }

    The creator will be added as a member if not present.
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number
        data = request.get_json() or {}
        group = (data.get('group') or data.get('name') or '').strip()
        if not group:
            return jsonify({'success': False, 'error': 'Group name required', 'error_code': 'MISSING_GROUP'}), 400

        # sanitize group name
        safe_group = str(group).replace('/', '_')

        members = data.get('members') or []
        if not isinstance(members, list):
            return jsonify({'success': False, 'error': 'members must be a list'}, 400)

        # Ensure creator is member
        if user.username not in members:
            members.append(user.username)

        # Persist members list
        try:
            save_group_members(team_number, safe_group, members)
        except Exception as e:
            current_app.logger.error(f"Failed saving group members: {e}")
            return jsonify({'success': False, 'error': 'Save failed', 'error_code': 'GROUP_SAVE_ERROR'}), 500

        # Ensure history file exists (empty list) so clients can fetch messages
        try:
            hist = load_group_chat_history(team_number, safe_group) or []
            save_group_chat_history(team_number, safe_group, hist)
        except Exception:
            pass

        return jsonify({'success': True, 'group': {'name': safe_group, 'member_count': len(members)}}), 201
    except Exception as e:
        current_app.logger.error(f"chat_create_group error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to create group', 'error_code': 'GROUP_CREATE_ERROR'}), 500


@mobile_api.route('/chat/groups/<group>/members', methods=['GET', 'POST', 'DELETE'])
@token_required
def chat_group_members_api(group):
    """
    Manage members of a named group.
    - GET: return current members
    - POST: add members (body: {"members": ["a","b"]})
    - DELETE: remove members (body: {"members": ["a"]})
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number
        safe_group = str(group).replace('/', '_')

        if request.method == 'GET':
            members = load_group_members(team_number, safe_group) or []
            return jsonify({'success': True, 'group': safe_group, 'members': members, 'count': len(members)}), 200

        payload = request.get_json() or {}
        change = payload.get('members') if isinstance(payload.get('members'), list) else []

        if request.method == 'POST':
            # add members
            members = set(load_group_members(team_number, safe_group) or [])
            for m in change:
                members.add(str(m))
            # ensure requester remains a member
            members.add(user.username)
            save_group_members(team_number, safe_group, sorted(members))
            return jsonify({'success': True, 'group': safe_group, 'members': sorted(members)}), 200

        if request.method == 'DELETE':
            # remove members. If no members provided in payload, remove the requesting user.
            try:
                existing = load_group_members(team_number, safe_group) or []
            except Exception:
                existing = []

            # If client didn't specify members to remove, default to removing the caller
            if not change:
                change = [user.username]

            # Perform case-insensitive removal to be tolerant of casing differences
            members_set = set(existing)
            try:
                for m in change:
                    targ = str(m).strip().lower()
                    # remove any matching member ignoring case
                    members_set = {mm for mm in members_set if str(mm).strip().lower() != targ}
            except Exception:
                # Fallback: attempt best-effort discard
                try:
                    for m in change:
                        members_set.discard(str(m))
                except Exception:
                    pass

            # Persist updated members list (allow empty groups)
            result_members = sorted(members_set)
            try:
                save_group_members(team_number, safe_group, result_members)
            except Exception as e:
                current_app.logger.error(f"Failed saving group members (DELETE): {e}")
                return jsonify({'success': False, 'error': 'Save failed', 'error_code': 'GROUP_SAVE_ERROR'}), 500

            # Also remove this group from the requesting user's persisted chat state
            try:
                from app import normalize_username
                # user.username is the canonical name; state files are stored per-team
                state_folder = os.path.join(current_app.instance_path, 'chat', 'users', str(team_number))
                os.makedirs(state_folder, exist_ok=True)
                state_file = os.path.join(state_folder, f'chat_state_{normalize_username(user.username)}.json')
                state = {}
                if os.path.exists(state_file):
                    try:
                        with open(state_file, 'r', encoding='utf-8') as sf:
                            state = json.load(sf) or {}
                    except Exception:
                        state = {}

                joined = state.get('joinedGroups', []) or []
                # Remove group case-insensitively
                try:
                    new_joined = [g for g in joined if str(g).strip().lower() != str(safe_group).strip().lower()]
                except Exception:
                    new_joined = joined
                state['joinedGroups'] = new_joined
                # Persist updated state
                with open(state_file, 'w', encoding='utf-8') as sf:
                    json.dump(state, sf, ensure_ascii=False, indent=2)
            except Exception:
                # Non-fatal: continue even if chat state update fails
                pass

            return jsonify({'success': True, 'group': safe_group, 'members': result_members}), 200

        return jsonify({'success': False, 'error': 'Unsupported method'}), 405
    except Exception as e:
        current_app.logger.error(f"chat_group_members_api error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Group members operation failed', 'error_code': 'GROUP_MEMBERS_ERROR'}), 500


@mobile_api.route('/chat/messages', methods=['GET'])
@token_required
def chat_messages():
    """
    Fetch chat messages. Supports:
      - type=dm : direct messages for the authenticated user (use `user` param to filter conversation)
      - type=alliance : alliance chat messages for the authenticated user's active alliance

    Query params:
      - type: 'dm' or 'alliance' (default: 'alliance')
      - user: other user id (for dm conversation)
      - limit, offset
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number

        msg_type = (request.args.get('type') or 'alliance').lower()
        other_user_id = request.args.get('user', type=int)
        limit = min(request.args.get('limit', 50, type=int), 2000)
        offset = request.args.get('offset', 0, type=int)

        # Support direct messages
        if msg_type == 'dm':
            # Read direct messages from per-user JSON files under instance/chat/users/<team_number>/
            import os, glob

            username = user.username

            # If a specific other user id was provided, validate and load that single conversation
            if other_user_id:
                other = User.query.get(other_user_id)
                if not other:
                    return jsonify({'success': False, 'error': 'Other user not found', 'error_code': 'USER_NOT_FOUND'}), 404
                # Enforce team isolation: only allow DMs within the same scouting team
                if other.scouting_team_number != team_number:
                    return jsonify({'success': False, 'error': 'Requested user not in same team', 'error_code': 'USER_NOT_IN_SCOPE'}), 403

                history = load_user_chat_history(username, other.username, team_number) or []
                # Sort by timestamp (newest first)
                history_sorted = sorted(history, key=lambda m: (m.get('timestamp') or m.get('created_at') or ''), reverse=True)
                total = len(history_sorted)
                start = offset
                end = offset + limit
                messages = history_sorted[start:end]

                return jsonify({'success': True, 'count': len(messages), 'total': total, 'messages': messages}), 200

            # No other_user specified: aggregate all DM files that include this user
            team_dir = os.path.join(current_app.root_path, '..', 'instance', 'chat', 'users', str(team_number))
            username_lower = str(username).lower()
            pattern = os.path.join(team_dir, f'*{username_lower}*_chat_history.json')
            dm_files = glob.glob(pattern) if os.path.exists(team_dir) else []

            all_messages = []
            for fp in dm_files:
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            all_messages.extend(data)
                except Exception:
                    continue

            # Filter messages to those involving this username explicitly (case-insensitive)
            uname_l = username_lower
            filtered = []
            for m in all_messages:
                s = (m.get('sender') or '').lower()
                r = (m.get('recipient') or '').lower()
                if s == uname_l or r == uname_l:
                    filtered.append(m)
            all_messages = filtered
            all_sorted = sorted(all_messages, key=lambda m: (m.get('timestamp') or m.get('created_at') or ''), reverse=True)
            total = len(all_sorted)
            messages = all_sorted[offset:offset + limit]

            return jsonify({'success': True, 'count': len(messages), 'total': total, 'messages': messages}), 200

        # Support fetching named group histories via query param or via type=group|team
        if msg_type in ('group', 'team') or request.args.get('group'):
            # Example: ?group=pit_team or ?group=554
            group = request.args.get('group') or request.args.get('name')
            if not group:
                return jsonify({'success': False, 'error': 'Group parameter required', 'error_code': 'MISSING_GROUP'}), 400

            safe_group = str(group).replace('/', '_')

            # If a members file exists, enforce membership
            try:
                members = load_group_members(team_number, safe_group) or []
                if members and user.username not in members:
                    return jsonify({'success': False, 'error': 'User not a member of the group', 'error_code': 'USER_NOT_IN_SCOPE'}), 403
            except Exception:
                # If members cannot be loaded, continue and try to return history
                members = []

            grp_history = load_group_chat_history(team_number, safe_group) or []
            all_sorted = sorted(grp_history, key=lambda m: (m.get('timestamp') or m.get('created_at') or ''), reverse=True)
            total = len(all_sorted)
            messages = all_sorted[offset:offset + limit]

            return jsonify({'success': True, 'count': len(messages), 'total': total, 'messages': messages}), 200

        else:
            # alliance chat (default) - read from per-team group files named 'alliance_<id>_group_chat_history.json'
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if not alliance:
                return jsonify({'success': True, 'count': 0, 'total': 0, 'messages': []}), 200

            # Collect group histories from each alliance member team (file-backed), plus fall back to DB records
            member_team_numbers = alliance.get_member_team_numbers() if hasattr(alliance, 'get_member_team_numbers') else []
            # Always include the requesting team
            if team_number not in member_team_numbers:
                member_team_numbers.append(team_number)

            all_messages = []
            for tn in member_team_numbers:
                try:
                    grp = load_group_chat_history(tn, f'alliance_{alliance.id}') or []
                    all_messages.extend(grp)
                except Exception:
                    continue

            # Fallback: include DB alliance chat rows if present to avoid missing previously stored messages
            try:
                rows = ScoutingAllianceChat.query.filter_by(alliance_id=alliance.id).all()
                for r in rows:
                    all_messages.append(r.to_dict())
            except Exception:
                # Ignore DB errors — prefer file-backed content
                pass

            # Normalize and sort
            all_sorted = sorted(all_messages, key=lambda m: (m.get('timestamp') or m.get('created_at') or ''), reverse=True)
            total = len(all_sorted)
            messages = all_sorted[offset:offset + limit]

            return jsonify({'success': True, 'count': len(messages), 'total': total, 'messages': messages}), 200

    except Exception as e:
        current_app.logger.error(f"chat_messages error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to retrieve chat messages', 'error_code': 'CHAT_MESSAGES_ERROR'}), 500



@mobile_api.route('/chat/send', methods=['POST'])
@token_required
def chat_send():
    """
    Send a chat message. Supports direct messages and alliance/group messages.

    Request JSON examples:
      { "recipient_id": 43, "body": "Hello" }
      { "conversation_type": "alliance", "body": "Alliance update" }

    Response: 201 with saved message dict on success.
    """
    try:
        user = request.mobile_user
        team_number = request.mobile_team_number

        # Try JSON first (common case)
        data = None
        try:
            data = request.get_json(silent=True)
        except Exception:
            data = None

        # Fallback to form-encoded or multipart
        if not data:
            if request.form and len(request.form) > 0:
                data = request.form.to_dict()

        # Fallback to raw body (text/plain or clients that send raw text)
        if not data or not isinstance(data, dict):
            raw = request.get_data(as_text=True) or ''
            if raw:
                # If raw looks like JSON, try to parse it
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        data = parsed
                except Exception:
                    # treat raw text as message body
                    data = {'body': raw}

        if not data:
            current_app.logger.info(f"chat_send missing body: content_type={request.content_type} raw={request.get_data(as_text=True)}")
            return jsonify({'success': False, 'error': 'Message body required', 'error_code': 'MISSING_DATA'}), 400

        # Accept multiple keys for message text for robustness
        body = (data.get('body') or data.get('text') or data.get('message') or '').strip()
        if not body:
            current_app.logger.info(f"chat_send empty body after parsing: data={data} content_type={request.content_type}")
            return jsonify({'success': False, 'error': 'Message body required', 'error_code': 'MISSING_DATA'}), 400

        recipient_id = data.get('recipient_id')
        conversation_type = (data.get('conversation_type') or data.get('type') or 'direct')

        import uuid
        timestamp = datetime.now(timezone.utc).isoformat()

        if recipient_id:
            try:
                recipient_id = int(recipient_id)
            except Exception:
                # if recipient provided as username rather than id, try lookup
                pass

            other = None
            if isinstance(recipient_id, int):
                other = User.query.get(recipient_id)
            else:
                # treat as username (do a case-insensitive lookup within the token's team)
                try:
                    from app.utils.team_isolation import find_user_in_same_team
                    other = find_user_in_same_team(str(recipient_id))
                except Exception:
                    other = User.query.filter_by(username=str(recipient_id)).first()

            if not other:
                return jsonify({'success': False, 'error': 'Recipient not found', 'error_code': 'USER_NOT_FOUND'}), 404
            if other.scouting_team_number != team_number:
                return jsonify({'success': False, 'error': 'Recipient not in same team', 'error_code': 'USER_NOT_IN_SCOPE'}), 403

            message = {
                'id': str(uuid.uuid4()),
                'sender': user.username,
                'recipient': other.username,
                'text': body,
                'body': body,
                'timestamp': timestamp,
                'offline_id': data.get('offline_id')
            }

            # Load existing history and append
            hist = load_user_chat_history(user.username, other.username, team_number) or []
            hist.append(message)
            save_user_chat_history(user.username, other.username, team_number, hist)
            # Log the file path we wrote to (helps debug visibility issues)
            try:
                fp = get_user_chat_file_path(user.username, other.username, team_number)
                current_app.logger.info(f"chat_send: saved DM to {fp} (sender={user.username} recipient={other.username})")
            except Exception:
                pass

            # Emit Socket.IO event so online recipients receive the DM in real-time
            try:
                from app import socketio
                socketio.emit('dm_message', message, room=user.username)
                socketio.emit('dm_message', message, room=other.username)
            except Exception:
                pass

            # Also increment recipient's chat state unread count so their UI poll picks it up
            try:
                current_app.logger.error(f"mobile chat_send: incrementing chat state for recipient={other.username}")
                # Use canonical helper so we don't write to a different filename than the web UI reads
                try:
                    from app.routes.main import get_user_chat_state_file
                    state_file = get_user_chat_state_file(other.username)
                except Exception:
                    from app import normalize_username
                    state_folder = os.path.join(current_app.instance_path, 'chat', 'users', str(other.scouting_team_number or team_number))
                    os.makedirs(state_folder, exist_ok=True)
                    state_file = os.path.join(state_folder, f'chat_state_{normalize_username(other.username)}.json')

                state = {}
                if os.path.exists(state_file):
                    try:
                        with open(state_file, 'r', encoding='utf-8') as sf:
                            state = json.load(sf) or {}
                    except Exception:
                        state = {}
                # increment unreadCount
                try:
                    prev = int(state.get('unreadCount', 0) or 0)
                except Exception:
                    prev = 0
                state['unreadCount'] = prev + 1
                state['lastSource'] = {'type': 'dm', 'id': user.username}
                state['lastNotified'] = datetime.now(timezone.utc).isoformat()
                with open(state_file, 'w', encoding='utf-8') as sf:
                    json.dump(state, sf, ensure_ascii=False, indent=2)
                current_app.logger.error(f"mobile chat_send: wrote chat state {state_file} unreadCount={state.get('unreadCount')}")
            except Exception as e:
                try:
                    current_app.logger.error(f"mobile chat_send: failed incrementing chat state for {getattr(other,'username',None)}: {e}")
                except Exception:
                    pass

            return jsonify({'success': True, 'message': message}), 201

        # conversation_type-based sends
        if str(conversation_type).lower() == 'alliance':
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if not alliance:
                return jsonify({'success': False, 'error': 'No active alliance', 'error_code': 'NO_ALLIANCE'}), 400

            message = {
                'id': str(uuid.uuid4()),
                'sender': user.username,
                'group': f'alliance_{alliance.id}',
                'team': team_number,
                'text': body,
                'timestamp': timestamp,
                'offline_id': data.get('offline_id')
            }

            # Save to requesting team's alliance group file
            hist = load_group_chat_history(team_number, f'alliance_{alliance.id}') or []
            hist.append(message)
            save_group_chat_history(team_number, f'alliance_{alliance.id}', hist)

            return jsonify({'success': True, 'message': message}), 201

        # Other conversation types (group) - require 'group' field
        group = data.get('group')
        if group:
            message = {
                'id': str(uuid.uuid4()),
                'sender': user.username,
                'group': group,
                'team': team_number,
                'text': body,
                'timestamp': timestamp,
                'offline_id': data.get('offline_id')
            }
            hist = load_group_chat_history(team_number, group) or []
            hist.append(message)
            save_group_chat_history(team_number, group, hist)
            return jsonify({'success': True, 'message': message}), 201

        return jsonify({'success': False, 'error': 'Invalid send parameters', 'error_code': 'INVALID_PARAMS'}), 400

    except Exception as e:
        current_app.logger.error(f"chat_send error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to send message', 'error_code': 'CHAT_SEND_ERROR'}), 500


# Mobile-side message editing (mirror web /chat/edit-message)
@mobile_api.route('/chat/edit-message', methods=['POST'])
@token_required
def mobile_edit_message():
    try:
        user = request.mobile_user
        
        data = request.get_json() or {}
        message_id = data.get('message_id')
        new_text = data.get('text')

        if not message_id or not new_text:
            return jsonify({'success': False, 'error': 'Message ID and text required.'}), 400

        # Import helper to locate and save message history (import inside to avoid circular imports)
        from app import find_message_in_user_files

        team_number = getattr(user, 'scouting_team_number', 'no_team')
        username = user.username

        message_info = find_message_in_user_files(message_id, username, team_number)
        if not message_info:
            return jsonify({'success': False, 'error': 'Message not found.'}), 404

        message = message_info['message']
        # Only allow editing messages authored by this user (and not assistant)
        sender_val = str(message.get('sender') or '')
        # Compare case-insensitively and trim whitespace to avoid false mismatches
        if sender_val.strip().lower() != str(username).strip().lower():
            current_app.logger.info(f"mobile_edit_message: ownership mismatch: token_user={username} message_sender={sender_val} message_id={message_id}")
            return jsonify({'success': False, 'error': 'Cannot edit other users messages.'}), 403
        if sender_val.strip().lower() == 'assistant':
            return jsonify({'success': False, 'error': 'Cannot edit assistant messages.'}), 403

        history = message_info['history']
        history[message_info['index']]['text'] = new_text
        history[message_info['index']]['edited'] = True
        from datetime import datetime, timezone
        history[message_info['index']]['edited_timestamp'] = datetime.now(timezone.utc).isoformat()

        # Save
        message_info['save_func'](history)

        # Emit socket event
        from app import socketio
        emit_data = {'message_id': message_id, 'text': new_text, 'reactions': message.get('reactions', [])}
        message_type = message_info.get('file_type')
        if message_type == 'assistant':
            socketio.emit('message_updated', emit_data, room=username)
        elif message_type == 'dm' and message.get('recipient'):
            socketio.emit('message_updated', emit_data, room=message['sender'])
            socketio.emit('message_updated', emit_data, room=message['recipient'])

        return jsonify({'success': True, 'message': 'Message edited.'}), 200
    except Exception as e:
        current_app.logger.error(f"mobile_edit_message error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Edit failed'}), 500


# Internal helper for marking a conversation read. Returns (response_dict, status_code)
def _mark_conversation_read(user, team_number, conv_type, conv_id, last_read_message_id):
    try:
        # Print to terminal for debugging so incoming read requests are visible
        try:
            print(f"[mobile_mark_read] user={getattr(user,'username',None)} team={team_number} type={conv_type} id={conv_id} last_read={last_read_message_id}", flush=True)
        except Exception:
            pass
        # Validate membership/scope
        if conv_type == 'dm':
            other = None
            try:
                if isinstance(conv_id, int) or (str(conv_id).isdigit() and len(str(conv_id)) < 10):
                    other = User.query.get(int(conv_id))
                    if not other:
                        # Fallback: maybe it's a username that looks like a number
                        other = User.query.filter_by(username=str(conv_id)).first()
                else:
                    other = User.query.filter_by(username=str(conv_id)).first()
            except Exception as e:
                current_app.logger.error(f"_mark_conversation_read: user lookup error conv_id={conv_id}: {e}")
                other = None
            if not other:
                current_app.logger.error(f"_mark_conversation_read: user not found conv_id={conv_id} current_user={getattr(user,'username',None)}")
                return ({'success': False, 'error': 'Other user not found', 'error_code': 'USER_NOT_FOUND'}, 404)
            if getattr(other, 'scouting_team_number', None) != team_number:
                current_app.logger.error(f"_mark_conversation_read: team mismatch other_team={getattr(other,'scouting_team_number',None)} expected={team_number}")
                return ({'success': False, 'error': 'User not in same team', 'error_code': 'USER_NOT_IN_SCOPE'}, 403)

        elif conv_type in ('group', 'alliance'):
            safe_group = str(conv_id).replace('/', '_')
            try:
                members = load_group_members(team_number, safe_group) or []
                if members and user.username not in members:
                    return ({'success': False, 'error': 'User not a member of the group', 'error_code': 'USER_NOT_IN_SCOPE'}, 403)
            except Exception:
                pass

        # Locate canonical state file
        try:
            from app.routes.main import get_user_chat_state_file
            state_file = get_user_chat_state_file(user.username)
        except Exception:
            from app import normalize_username
            state_folder = os.path.join(current_app.instance_path, 'chat', 'users', str(team_number))
            os.makedirs(state_folder, exist_ok=True)
            state_file = os.path.join(state_folder, f'chat_state_{normalize_username(user.username)}.json')

        state = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as sf:
                    state = json.load(sf) or {}
            except Exception:
                state = {}

        last_read_map = state.get('lastRead', {}) or {}
        conv_key = f"{('group' if conv_type != 'dm' else 'dm')}:{str(conv_id)}"
        last_read_map[conv_key] = last_read_message_id
        state['lastRead'] = last_read_map
        state['lastSource'] = {'type': conv_type if conv_type != 'alliance' else 'group', 'id': str(conv_id)}

        # Resolve timestamps for last-read markers when possible
        last_read_ts_map = {}
        try:
            from app import find_message_in_user_files
            for k, mid in last_read_map.items():
                try:
                    mi = find_message_in_user_files(mid, user.username, team_number)
                    if mi and isinstance(mi.get('message'), dict):
                        last_read_ts_map[k] = (mi['message'].get('timestamp') or mi['message'].get('created_at'))
                    else:
                        last_read_ts_map[k] = None
                except Exception:
                    last_read_ts_map[k] = None
        except Exception:
            last_read_ts_map = {}

        # Recompute unreadCount using message-id positions where possible.
        # Normalize last-read keys to lowercase to avoid casing mismatches.
        unread_total = 0
        try:
            import glob
            import os as _os

            uname_norm = str(user.username).strip().lower()

            # Build a normalized last-read map keyed by lowercased conversation keys
            normalized_last_mid = {}
            try:
                for k, mid in last_read_map.items():
                    if not k:
                        continue
                    try:
                        typ, ident = k.split(':', 1)
                        nkey = f"{typ}:{str(ident).strip().lower()}"
                    except Exception:
                        nkey = str(k).strip().lower()
                    normalized_last_mid[nkey] = mid
            except Exception:
                normalized_last_mid = {}

            team_dir = _os.path.join(current_app.instance_path, 'chat', 'users', str(team_number))
            dm_pattern = _os.path.join(team_dir, f'*_chat_history.json')
            dm_files = glob.glob(dm_pattern) if _os.path.exists(team_dir) else []

            def _msg_id(m):
                return (m.get('id') or m.get('message_id') or m.get('uuid') or m.get('offline_id') or m.get('mid'))

            for fp in dm_files:
                try:
                    with open(fp, 'r', encoding='utf-8') as fh:
                        data_list = json.load(fh) or []
                except Exception:
                    continue

                base = _os.path.basename(fp)
                nm = base.replace('_chat_history.json', '')
                parts = nm.split('_')
                other_norm = None
                if len(parts) >= 2:
                    if parts[0].strip().lower() == uname_norm:
                        other_norm = parts[1].strip().lower()
                    elif parts[1].strip().lower() == uname_norm:
                        other_norm = parts[0].strip().lower()

                if not other_norm:
                    # Couldn't detect other participant; conservative count
                    for m in (data_list or []):
                        try:
                            sender = str(m.get('sender') or '').strip().lower()
                            recip = str(m.get('recipient') or '').strip().lower()
                            if recip != uname_norm or sender == uname_norm:
                                continue
                            unread_total += 1
                        except Exception:
                            continue
                    continue

                convk = f"dm:{other_norm}"
                last_mid = normalized_last_mid.get(convk)

                if last_mid:
                    # Try to find message by id in the history and count messages after it
                    idx = None
                    try:
                        for i, m in enumerate(data_list or []):
                            try:
                                if str(_msg_id(m)) == str(last_mid):
                                    idx = i
                                    break
                            except Exception:
                                continue
                    except Exception:
                        idx = None

                    if idx is not None:
                        for m in (data_list or [])[idx+1:]:
                            try:
                                sender = str(m.get('sender') or '').strip().lower()
                                recip = str(m.get('recipient') or '').strip().lower()
                                if recip != uname_norm or sender == uname_norm:
                                    continue
                                unread_total += 1
                            except Exception:
                                continue
                        continue

                # Fallback: no last_mid or not found — count messages newer than last_read_ts_map entry if present,
                # otherwise conservative count all inbound messages
                last_ts = None
                try:
                    last_ts = last_read_ts_map.get(f"dm:{other_norm}")
                except Exception:
                    last_ts = None

                for m in (data_list or []):
                    try:
                        sender = str(m.get('sender') or '').strip().lower()
                        recip = str(m.get('recipient') or '').strip().lower()
                        ts = (m.get('timestamp') or m.get('created_at') or '')
                        if recip != uname_norm or sender == uname_norm:
                            continue
                        if last_ts:
                            if ts > last_ts:
                                unread_total += 1
                        else:
                            unread_total += 1
                    except Exception:
                        continue

            group_dir = _os.path.join(current_app.instance_path, 'chat', 'groups', str(team_number))
            if _os.path.exists(group_dir):
                for gf in _os.listdir(group_dir):
                    if not gf.endswith('_group_chat_history.json'):
                        continue
                    gname = gf.replace('_group_chat_history.json', '')
                    try:
                        with open(_os.path.join(group_dir, gf), 'r', encoding='utf-8') as gh:
                            gdata = json.load(gh) or []
                    except Exception:
                        continue

                    try:
                        members = load_group_members(team_number, gname) or []
                        if members and user.username not in members:
                            continue
                    except Exception:
                        pass

                    convk = f"group:{gname.strip().lower()}"
                    last_mid = normalized_last_mid.get(convk)

                    if last_mid:
                        idx = None
                        try:
                            for i, m in enumerate(gdata or []):
                                try:
                                    if str(_msg_id(m)) == str(last_mid):
                                        idx = i
                                        break
                                except Exception:
                                    continue
                        except Exception:
                            idx = None

                        if idx is not None:
                            for m in (gdata or [])[idx+1:]:
                                try:
                                    sender = str(m.get('sender') or '').strip().lower()
                                    if sender == uname_norm:
                                        continue
                                    unread_total += 1
                                except Exception:
                                    continue
                            continue

                    # Fallback: count all messages from others
                    for m in (gdata or []):
                        try:
                            sender = str(m.get('sender') or '').strip().lower()
                            if sender == uname_norm:
                                continue
                            unread_total += 1
                        except Exception:
                            continue

        except Exception:
            try:
                unread_total = int(state.get('unreadCount', 0) or 0)
            except Exception:
                unread_total = 0

        state['unreadCount'] = unread_total

        try:
            with open(state_file, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, ensure_ascii=False, indent=2)
        except Exception:
            current_app.logger.error(f"Failed to persist chat state file: {state_file}")

        try:
            from app import socketio
            socketio.emit('conversation_read', {'conversation': conv_key, 'user': user.username, 'last_read': last_read_message_id}, room=user.username)
        except Exception:
            pass

        return ({'success': True}, 200)

    except Exception as e:
        current_app.logger.error(f"_mark_conversation_read error: {e}\n{traceback.format_exc()}")
        return ({'success': False, 'error': 'Failed to mark conversation read', 'error_code': 'MARK_READ_ERROR'}, 500)


# Mark conversation read endpoint (mobile) - preferred JSON form
@mobile_api.route('/chat/conversations/read', methods=['POST'])
@token_required
def mobile_mark_conversation_read():
    """Mark a conversation as read for the authenticated mobile user using the JSON payload form."""
    data = request.get_json() or {}
    conv_type = (data.get('type') or data.get('conversation_type') or 'dm')
    conv_type = str(conv_type).strip().lower()
    conv_id = data.get('id') or data.get('conversation_id') or data.get('user') or data.get('group')
    last_read_message_id = data.get('last_read_message_id')

    if not conv_id or not last_read_message_id:
        return jsonify({'success': False, 'error': 'conversation id and last_read_message_id required', 'error_code': 'MISSING_DATA'}), 400

    user = request.mobile_user
    team_number = request.mobile_team_number
    try:
        print(f"[mobile_mark_read_route] payload={data} user={getattr(user,'username',None)} team={team_number}", flush=True)
    except Exception:
        pass
    
    try:
        resp, status = _mark_conversation_read(user, team_number, conv_type, conv_id, last_read_message_id)
        return jsonify(resp), status
    except Exception as e:
        current_app.logger.error(f"mobile_mark_conversation_read error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e), 'error_code': 'MARK_READ_ERROR'}), 500


# Legacy route: support URL form /chat/conversations/{conversation_id}/read
@mobile_api.route('/chat/conversations/<path:conversation_id>/read', methods=['POST'])
@token_required
def mobile_mark_conversation_read_legacy(conversation_id):
    """Legacy compatibility: accept conversation id in the URL and last_read_message_id in the body.

    Examples of URL conversation_id values:
      - dm_5454
      - group_pit_team
      - alliance_12
    """
    data = request.get_json() or {}
    last_read_message_id = data.get('last_read_message_id') or data.get('last_read') or request.args.get('last_read_message_id')
    if not last_read_message_id:
        return jsonify({'success': False, 'error': 'last_read_message_id required in body or query', 'error_code': 'MISSING_DATA'}), 400

    # Heuristic to derive type and id from the path portion
    cid = str(conversation_id)
    conv_type = 'dm'
    conv_id = cid
    if cid.startswith('dm_'):
        conv_type = 'dm'
        conv_id = cid[len('dm_'):]
    elif cid.startswith('group_'):
        conv_type = 'group'
        conv_id = cid[len('group_'):]
    elif cid.startswith('alliance_'):
        conv_type = 'alliance'
        conv_id = cid[len('alliance_'):]
    elif cid.startswith('dm:'):
        conv_type = 'dm'
        conv_id = cid.split(':', 1)[1]
    elif cid.startswith('group:'):
        conv_type = 'group'
        conv_id = cid.split(':', 1)[1]

    user = request.mobile_user
    team_number = request.mobile_team_number
    try:
        print(f"[mobile_mark_read_legacy] url_conversation_id={conversation_id} body={data} user={getattr(user,'username',None)} team={team_number}", flush=True)
    except Exception:
        pass
    
    try:
        resp, status = _mark_conversation_read(user, team_number, conv_type, conv_id, last_read_message_id)
        return jsonify(resp), status
    except Exception as e:
        current_app.logger.error(f"mobile_mark_conversation_read_legacy error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e), 'error_code': 'MARK_READ_ERROR'}), 500

# Mobile-side message deletion (mirror web /chat/delete-message)
@mobile_api.route('/chat/delete-message', methods=['POST'])
@token_required
def mobile_delete_message():
    try:
        user = request.mobile_user
        data = request.get_json() or {}
        message_id = data.get('message_id')
        if not message_id:
            return jsonify({'success': False, 'error': 'Message ID required.'}), 400

        from app import find_message_in_user_files
        team_number = getattr(user, 'scouting_team_number', 'no_team')
        username = user.username

        message_info = find_message_in_user_files(message_id, username, team_number)
        if not message_info:
            return jsonify({'success': False, 'error': 'Message not found.'}), 404

        message = message_info['message']
        sender_val = str(message.get('sender') or '')
        if sender_val.strip().lower() != str(username).strip().lower():
            current_app.logger.info(f"mobile_delete_message: ownership mismatch: token_user={username} message_sender={sender_val} message_id={message_id}")
            return jsonify({'success': False, 'error': 'Cannot delete other users messages.'}), 403
        if sender_val.strip().lower() == 'assistant':
            return jsonify({'success': False, 'error': 'Cannot delete assistant messages.'}), 403

        history = message_info['history']
        history.pop(message_info['index'])
        message_info['save_func'](history)

        # Emit socket event
        from app import socketio
        emit_data = {'message_id': message_id}
        message_type = message_info.get('file_type')
        if message_type == 'assistant':
            socketio.emit('message_deleted', emit_data, room=username)
        elif message_type == 'dm' and message.get('recipient'):
            socketio.emit('message_deleted', emit_data, room=message['sender'])
            socketio.emit('message_deleted', emit_data, room=message['recipient'])

        return jsonify({'success': True, 'message': 'Message deleted.'}), 200
    except Exception as e:
        current_app.logger.error(f"mobile_delete_message error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Delete failed'}), 500


# Mobile-side reaction toggle (mirror web /chat/react-message)
@mobile_api.route('/chat/react-message', methods=['POST'])
@token_required
def mobile_react_to_message():
    try:
        user = request.mobile_user
        data = request.get_json() or {}
        message_id = data.get('message_id')
        emoji = data.get('emoji')
        if not message_id or not emoji:
            return jsonify({'success': False, 'error': 'Message ID and emoji required.'}), 400

        from app import find_message_in_user_files
        team_number = getattr(user, 'scouting_team_number', 'no_team')
        username = user.username

        message_info = find_message_in_user_files(message_id, username, team_number)
        if not message_info:
            return jsonify({'success': False, 'error': 'Message not found.'}), 404

        message = message_info['message']
        history = message_info['history']
        if 'reactions' not in history[message_info['index']]:
            history[message_info['index']]['reactions'] = []

        # Toggle reaction locally
        def _toggle(reactions, username, emoji):
            existing = next((r for r in reactions if r.get('user') == username and r.get('emoji') == emoji), None)
            if existing:
                reactions.remove(existing)
            else:
                from datetime import datetime, timezone
                reactions.append({'user': username, 'emoji': emoji, 'timestamp': datetime.now(timezone.utc).isoformat()})
            return reactions

        updated_reactions = _toggle(history[message_info['index']]['reactions'], username, emoji)
        history[message_info['index']]['reactions'] = updated_reactions

        # Build summary
        def _group(reactions):
            emoji_counts = {}
            for r in reactions:
                em = r.get('emoji')
                if not em: continue
                emoji_counts[em] = emoji_counts.get(em, 0) + 1
            return [{'emoji': e, 'count': c} for e, c in emoji_counts.items()]

        reaction_summary = _group(updated_reactions)
        try:
            history[message_info['index']]['reactions_summary'] = reaction_summary
        except Exception:
            pass

        message_info['save_func'](history)

        # Emit socket update
        from app import socketio
        emit_data = {'message_id': message_id, 'reactions': reaction_summary}
        message_type = message_info.get('file_type')
        if message_type == 'assistant':
            socketio.emit('message_updated', emit_data, room=username)
        elif message_type == 'dm' and message.get('recipient'):
            socketio.emit('message_updated', emit_data, room=message['sender'])
            socketio.emit('message_updated', emit_data, room=message['recipient'])
        elif message_type == 'group':
            grp = message.get('group') or message.get('group_name')
            team = message.get('team') or message.get('team_number')
            try:
                room_name = f"group_{team}_{grp}"
                socketio.emit('message_updated', emit_data, room=room_name)
            except Exception:
                pass

        # Return JSON with ensure_ascii=False so emoji are sent as unicode characters
        resp_text = json.dumps({'success': True, 'reactions': reaction_summary}, ensure_ascii=False)
        return current_app.response_class(resp_text, mimetype='application/json'), 200
    except Exception as e:
        current_app.logger.error(f"mobile_react_to_message error: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'React failed'}), 500


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
