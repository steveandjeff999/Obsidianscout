"""
Mobile App API
Comprehensive REST API for mobile applications with authentication, data access, and offline sync
"""
from flask import Blueprint, request, jsonify, current_app, g, url_for, send_file, get_flashed_messages
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
    DoNotPickEntry, AvoidEntry, ScoutingAlliance, ScoutingAllianceMember, ScoutingAllianceInvitation, ScoutingAllianceEvent,
    ScoutingAllianceChat, TeamAllianceStatus, ScoutingDirectMessage, db, Role,
    AllianceSharedScoutingData, AllianceSharedPitData
)
from app import socketio
from app import load_user_chat_history, load_group_chat_history, load_assistant_chat_history, save_user_chat_history, save_group_chat_history, get_user_chat_file_path, load_group_members, save_group_members, get_group_members_file_path
from app.models_misc import NotificationQueue, NotificationSubscription, NotificationLog, DeviceToken
from app.utils.team_isolation import (
    get_current_scouting_team_number,
    filter_matches_by_scouting_team,
    filter_teams_by_scouting_team,
)
from app.utils.analysis import calculate_team_metrics
from app.utils.api_utils import safe_int_team_number
from app.utils.alliance_data import (
    get_active_alliance_id_for_team,
    get_scouting_data_query_for_team,
    get_pit_data_query_for_team,
    get_all_teams_for_alliance,
    get_all_matches_for_alliance
)
from werkzeug.security import check_password_hash
from app.assistant.visualizer import Visualizer

# Create blueprint
mobile_api = Blueprint('mobile_api', __name__, url_prefix='/api/mobile')

from werkzeug.utils import secure_filename
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
    '/api/mobile/auth/login',
    '/api/mobile/auth/register'
]


def resolve_event_code_to_id(event_code_param, team_number):
    """Resolve an event code string to an event ID, using year prefix from team's config.
    
    When multiple events exist with the same raw code but different year prefixes
    (e.g., 2025OKTU and 2026OKTU), this uses the team's configured season to pick
    the correct one.
    
    Args:
        event_code_param: Raw event code (e.g., "OKTU") or year-prefixed code (e.g., "2026OKTU")
        team_number: The scouting team number to scope the lookup and get season config
        
    Returns:
        Event ID if found, None otherwise
    """
    if not event_code_param:
        return None
        
    event_code = str(event_code_param).strip().upper()
    
    # Check if code already has year prefix (4 digits at start)
    if len(event_code) >= 4 and event_code[:4].isdigit():
        # Already year-prefixed, try exact match first
        evt = Event.query.filter_by(code=event_code, scouting_team_number=team_number).first()
        if not evt:
            evt = Event.query.filter_by(code=event_code).first()
        if evt:
            return evt.id
        return None
    
    # Raw code without year prefix - construct year-prefixed version from team's config
    try:
        from app.utils.config_manager import load_game_config
        game_config = load_game_config(team_number=team_number)
        season = game_config.get('season', 2026) if isinstance(game_config, dict) else 2026
    except Exception:
        season = 2026
    
    year_prefixed_code = f"{season}{event_code}"
    
    # Try year-prefixed code first (preferred)
    evt = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=team_number).first()
    if not evt:
        evt = Event.query.filter_by(code=year_prefixed_code).first()
    
    if evt:
        current_app.logger.debug(f"Resolved event code '{event_code_param}' to year-prefixed '{year_prefixed_code}' (id={evt.id})")
        return evt.id
    
    # Fall back to raw code for backwards compatibility with old data
    evt = Event.query.filter_by(code=event_code, scouting_team_number=team_number).first()
    if not evt:
        evt = Event.query.filter_by(code=event_code).first()
    
    if evt:
        current_app.logger.debug(f"Resolved event code '{event_code_param}' to raw code '{event_code}' (id={evt.id})")
        return evt.id
    
    current_app.logger.debug(f"Could not resolve event code '{event_code_param}' to an Event record")
    return None


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
    # Ensure Flask's `g` object also has scouting_team_number so
    # `app.utils.team_isolation` helpers see the same resolved team.
    try:
        g.scouting_team_number = team_number
    except Exception:
        pass
    # Attempt to set flask-login's current_user to this token user so code
    # that relies on current_user's scouting_team_number continues to work.
    try:
        login_user(user, remember=False, force=True)
    except Exception:
        pass
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
        
        # Add user info to request context. Use the same team resolution logic
        # as enforce_mobile_auth for consistency and security:
        # - If the token contains a team_number and the user's DB has a
        #   scouting_team_number that differs -> reject the request.
        # - If token contains a team_number and DB value is None or matches,
        #   accept the token-provided team.
        # - If token lacks a team_number, use the user's DB scouting_team_number.
        token_team = payload.get('team_number')
        team_number = None
        try:
            db_team = getattr(user, 'scouting_team_number', None)
            if token_team is not None:
                # If the DB has an authoritative team and it differs, reject.
                if db_team is not None and str(token_team) != str(db_team):
                    current_app.logger.warning(
                        f"mobile_api.token_required: token team {token_team} does not match DB scouting_team_number {db_team} for user {user.id}; rejecting"
                    )
                    return jsonify({'success': False, 'error': 'Token team mismatch', 'error_code': 'TEAM_MISMATCH'}), 401
                team_number = token_team
            else:
                # Token omitted team -> fall back to DB team's scouting_team_number
                team_number = db_team
        except Exception:
            team_number = payload.get('team_number')

        request.mobile_user = user
        request.mobile_team_number = team_number
        # Ensure flask `g` has the same team for helper functions
        try:
            g.scouting_team_number = team_number
        except Exception:
            pass
        try:
            login_user(user, remember=False, force=True)
        except Exception:
            pass
        
        return f(*args, **kwargs)
    
    return decorated_function


def sync_scouting_to_alliance(scouting_data_entry, team_number):
    """Sync scouting data to alliance shared tables if alliance mode is active for the team"""
    try:
        alliance_id = get_active_alliance_id_for_team(team_number)
        if not alliance_id:
            return  # No active alliance
        
        # Check if shared entry already exists
        existing_shared = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            original_scouting_data_id=scouting_data_entry.id,
            is_active=True
        ).first()
        
        if existing_shared:
            # Update existing shared data
            existing_shared.data = scouting_data_entry.data
            existing_shared.scout_name = scouting_data_entry.scout_name
            existing_shared.scout_id = scouting_data_entry.scout_id
            existing_shared.scouting_station = getattr(scouting_data_entry, 'scouting_station', None)
            existing_shared.alliance = getattr(scouting_data_entry, 'alliance', None)
            existing_shared.timestamp = scouting_data_entry.timestamp
            existing_shared.last_edited_by_team = team_number
            existing_shared.last_edited_at = datetime.now(timezone.utc)
        else:
            # Create new shared data entry
            shared_data = AllianceSharedScoutingData.create_from_scouting_data(
                scouting_data_entry, alliance_id, team_number
            )
            db.session.add(shared_data)
    except Exception as e:
        current_app.logger.error(f"Error syncing scouting to alliance: {str(e)}")


def sync_pit_to_alliance(pit_data_entry, team_number):
    """Sync pit scouting data to alliance shared tables if alliance mode is active for the team"""
    try:
        alliance_id = get_active_alliance_id_for_team(team_number)
        if not alliance_id:
            return  # No active alliance
        
        # Check if shared entry already exists
        existing_shared = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            original_pit_data_id=pit_data_entry.id,
            is_active=True
        ).first()
        
        if existing_shared:
            # Update existing shared data
            existing_shared.data = pit_data_entry.data
            existing_shared.scout_name = pit_data_entry.scout_name
            existing_shared.scout_id = pit_data_entry.scout_id
            existing_shared.timestamp = pit_data_entry.timestamp
            existing_shared.last_edited_by_team = team_number
            existing_shared.last_edited_at = datetime.now(timezone.utc)
        else:
            # Create new shared data entry
            shared_data = AllianceSharedPitData.create_from_pit_data(
                pit_data_entry, alliance_id, team_number
            )
            db.session.add(shared_data)
    except Exception as e:
        current_app.logger.error(f"Error syncing pit data to alliance: {str(e)}")


# ======== MOBILE ALLIANCE MANAGEMENT ENDPOINTS ========

@mobile_api.route('/alliances', methods=['GET'])
def mobile_list_alliances():
    """List alliances for the requesting team and show pending/sent invitations"""
    team = getattr(request, 'mobile_team_number', None)
    if team is None:
        return jsonify({'success': False, 'error': 'Scouting team not resolved'}), 400

    # Alliances current team is a member of
    my_alliances = db.session.query(ScoutingAlliance).join(ScoutingAllianceMember).filter(
        ScoutingAllianceMember.team_number == team,
        ScoutingAllianceMember.status == 'accepted'
    ).all()

    # Determine which alliance (if any) is currently active for this team
    active_alliance = TeamAllianceStatus.get_active_alliance_for_team(team)
    active_id = active_alliance.id if active_alliance else None

    my_list = []
    for a in my_alliances:
        members = a.get_active_members() if hasattr(a, 'get_active_members') else []
        my_list.append({
            'id': a.id,
            'name': a.alliance_name,
            'description': a.description,
            'member_count': len(members),
            'is_active': (active_id == a.id),
            'config_status': getattr(a, 'config_status', None),
            'is_config_complete': a.is_config_complete() if hasattr(a, 'is_config_complete') else None
        })

    pending = ScoutingAllianceInvitation.query.filter_by(to_team_number=team, status='pending').all()
    sent = ScoutingAllianceInvitation.query.filter_by(from_team_number=team, status='pending').all()

    active = TeamAllianceStatus.get_active_alliance_for_team(team)

    # Include alliance_name for invitations to make UI-friendly payloads
    def inv_to_payload(i):
        return {
            'id': i.id,
            'alliance_id': i.alliance_id,
            'alliance_name': getattr(i.alliance, 'alliance_name', None),
            'from_team': i.from_team_number
        }

    def sent_to_payload(i):
        return {
            'id': i.id,
            'to_team': i.to_team_number,
            'alliance_id': i.alliance_id,
            'alliance_name': getattr(i.alliance, 'alliance_name', None)
        }

    return jsonify({
        'success': True,
        'my_alliances': my_list,
        'pending_invitations': [inv_to_payload(i) for i in pending],
        'sent_invitations': [sent_to_payload(i) for i in sent],
        'active_alliance_id': active.id if active else None
    })


@mobile_api.route('/alliances', methods=['POST'])
def mobile_create_alliance():
    """Create a new alliance (requires user with admin role)"""
    user = getattr(request, 'mobile_user', None)
    if not user or not (user.has_role('admin') or user.has_role('superadmin')):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Alliance name is required'}), 400

    try:
        alliance = ScoutingAlliance(
            alliance_name=name,
            description=data.get('description', ''),
            config_status='pending'
        )
        db.session.add(alliance)
        db.session.flush()

        member = ScoutingAllianceMember(
            alliance_id=alliance.id,
            team_number=request.mobile_team_number,
            team_name=f"Team {request.mobile_team_number}",
            role='admin',
            status='accepted'
        )
        db.session.add(member)
        db.session.commit()

        return jsonify({'success': True, 'alliance_id': alliance.id})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating alliance via mobile API: {str(e)}")
        return jsonify({'success': False, 'error': f'Error creating alliance: {str(e)}'}), 500


@mobile_api.route('/alliances/<int:alliance_id>/toggle', methods=['POST'])
def mobile_toggle_alliance(alliance_id):
    """Activate or deactivate alliance mode for the requesting team"""
    team = getattr(request, 'mobile_team_number', None)
    if team is None:
        return jsonify({'success': False, 'error': 'Scouting team not resolved'}), 400

    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=team,
        status='accepted'
    ).first()

    if not member:
        return jsonify({'success': False, 'error': 'You are not an active member of this alliance'}), 403

    data = request.get_json() or {}
    activate = bool(data.get('activate', False))
    remove_shared_data = bool(data.get('remove_shared_data', False))

    try:
        if activate:
            if not alliance.is_config_complete():
                return jsonify({'success': False, 'error': 'Alliance configuration must be complete before activation'}), 400

            # Check if currently active in other alliance
            current_status = TeamAllianceStatus.query.filter_by(team_number=team).first()
            if current_status and current_status.is_alliance_mode_active and current_status.active_alliance_id != alliance_id:
                current_alliance = current_status.active_alliance
                message = f'Switched from "{current_alliance.alliance_name}" to "{alliance.alliance_name}"'
            else:
                message = f'Alliance mode activated for {alliance.alliance_name}'

            TeamAllianceStatus.activate_alliance_for_team(team, alliance_id)
            member.is_data_sharing_active = True
            member.data_sharing_deactivated_at = None

            if alliance.game_config_team:
                from app.utils.config_manager import load_game_config
                game_config = load_game_config(team_number=alliance.game_config_team)
                alliance.shared_game_config = json.dumps(game_config)
            if alliance.pit_config_team:
                from app.utils.config_manager import load_pit_config
                pit_config = load_pit_config(team_number=alliance.pit_config_team)
                alliance.shared_pit_config = json.dumps(pit_config)

            alliance.update_config_status()
            db.session.commit()

        else:
            TeamAllianceStatus.deactivate_alliance_for_team(team, remove_shared_data=remove_shared_data)
            db.session.commit()
            if remove_shared_data:
                message = 'Alliance mode deactivated - your shared data has been removed from the alliance'
            else:
                message = 'Alliance mode deactivated - your existing shared data remains (new syncs will not get your data)'

        from app.utils.config_manager import get_effective_game_config, get_effective_pit_config, is_alliance_mode_active, get_active_alliance_info

        effective_game_config = get_effective_game_config()
        effective_pit_config = get_effective_pit_config()
        alliance_status = is_alliance_mode_active()
        alliance_info = get_active_alliance_info()

        config_update_data = {
            'alliance_id': alliance_id,
            'team_number': team,
            'is_active': activate,
            'message': message,
            'effective_game_config': effective_game_config,
            'effective_pit_config': effective_pit_config,
            'alliance_status': alliance_status,
            'alliance_info': alliance_info
        }

        socketio.emit('alliance_mode_toggled', config_update_data, room=f'alliance_{alliance_id}')
        socketio.emit('config_updated', config_update_data, room=f'team_{team}')
        socketio.emit('alliance_status_changed', {
            'team_number': team,
            'alliance_status': alliance_status,
            'alliance_info': alliance_info
        })

        socketio.emit('global_config_changed', {
            'type': 'alliance_toggle',
            'team_number': team,
            'alliance_id': alliance_id,
            'is_active': activate,
            'effective_game_config': effective_game_config,
            'effective_pit_config': effective_pit_config,
            'alliance_status': alliance_status,
            'alliance_info': alliance_info,
            'timestamp': datetime.now().isoformat(),
            'message': message
        })

        return jsonify({'success': True, 'message': message, 'is_active': activate})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling alliance mode via mobile API: {str(e)}")
        return jsonify({'success': False, 'error': f'Error toggling alliance mode: {str(e)}'}), 500


@mobile_api.route('/alliances/<int:alliance_id>/invite', methods=['POST'])
def mobile_send_invitation(alliance_id):
    """Send alliance invitation to another team via mobile API"""
    team = getattr(request, 'mobile_team_number', None)
    if team is None:
        return jsonify({'success': False, 'error': 'Scouting team not resolved'}), 400

    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=team,
        role='admin',
        status='accepted'
    ).first()

    if not member:
        return jsonify({'success': False, 'error': 'You must be an alliance admin to send invitations'}), 403

    data = request.get_json() or {}
    dest_team = data.get('team_number')
    if not dest_team:
        return jsonify({'success': False, 'error': 'team_number is required'}), 400

    try:
        dest_team = int(dest_team)
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid team number'}), 400

    existing = ScoutingAllianceInvitation.query.filter_by(
        alliance_id=alliance_id,
        to_team_number=dest_team,
        status='pending'
    ).first()

    if existing:
        return jsonify({'success': False, 'error': 'Invitation already sent to this team'}), 400

    invitation = ScoutingAllianceInvitation(
        alliance_id=alliance_id,
        from_team_number=team,
        to_team_number=dest_team,
        message=data.get('message', '')
    )
    db.session.add(invitation)
    db.session.commit()

    socketio.emit('alliance_invitation', {
        'to_team': dest_team,
        'from_team': team,
        'alliance_name': member.alliance.alliance_name,
        'message': data.get('message', '')
    }, room=f'team_{dest_team}')

    return jsonify({'success': True})


@mobile_api.route('/alliances/<int:alliance_id>/leave', methods=['POST'])
def mobile_leave_alliance(alliance_id):
    """Mobile endpoint to leave an alliance; mirrors web behavior."""
    team = getattr(request, 'mobile_team_number', None)
    if team is None:
        return jsonify({'success': False, 'error': 'Scouting team not resolved'}), 400

    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    try:
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=team,
            status='accepted'
        ).first()

        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance.'}), 404

        data = request.get_json() or {}
        remove_shared_data = bool(data.get('remove_shared_data', False))
        copy_shared_data = bool(data.get('copy_shared_data', False))

        # Check if this is the only admin - prevent leaving if so
        admin_members = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            role='admin',
            status='accepted'
        ).all()

        if member.role == 'admin' and len(admin_members) == 1:
            other_members = ScoutingAllianceMember.query.filter_by(
                alliance_id=alliance_id,
                status='accepted'
            ).filter(ScoutingAllianceMember.team_number != team).all()

            if other_members:
                return jsonify({
                    'success': False,
                    'error': 'You are the only administrator. Please transfer admin rights to another member before leaving.'
                }), 400

        # If this team has alliance mode active for this alliance, optionally copy or remove shared data
        alliance_status = TeamAllianceStatus.query.filter_by(
            team_number=team,
            is_alliance_mode_active=True,
            active_alliance_id=alliance_id
        ).first()

        if alliance_status:
            # If requested, copy shared alliance data back into the team's local tables
            if copy_shared_data:
                # Copy scouting data
                shared_scouting = AllianceSharedScoutingData.query.filter_by(
                    alliance_id=alliance_id,
                    source_scouting_team_number=team,
                    is_active=True
                ).all()
                for s in shared_scouting:
                    try:
                        new = ScoutingData(
                            match_id=s.match_id,
                            team_id=s.team_id,
                            scouting_team_number=team,
                            scout_name=s.scout_name or f"Team {team}",
                            scout_id=s.scout_id,
                            scouting_station=s.scouting_station,
                            timestamp=s.timestamp,
                            alliance=s.alliance,
                            data_json=s.data_json
                        )
                        db.session.add(new)
                    except Exception as e:
                        current_app.logger.error(f"Error copying shared scouting data back to team {team}: {str(e)}")

                # Copy pit data
                shared_pit = AllianceSharedPitData.query.filter_by(
                    alliance_id=alliance_id,
                    source_scouting_team_number=team,
                    is_active=True
                ).all()
                for p in shared_pit:
                    try:
                        import uuid as _uuid
                        newp = PitScoutingData(
                            team_id=p.team_id,
                            event_id=p.event_id,
                            scouting_team_number=team,
                            scout_name=p.scout_name,
                            scout_id=p.scout_id,
                            timestamp=p.timestamp,
                            data_json=p.data_json,
                            local_id=str(_uuid.uuid4())
                        )
                        db.session.add(newp)
                    except Exception as e:
                        current_app.logger.error(f"Error copying shared pit data back to team {team}: {str(e)}")

            # Now deactivate alliance mode for the team (this will remove shared data if requested)
            TeamAllianceStatus.deactivate_alliance_for_team(team, remove_shared_data=remove_shared_data)

        # Remove the member from the alliance
        alliance_name = alliance.alliance_name
        db.session.delete(member)

        # If this was the last member, delete the alliance entirely
        remaining_members = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            status='accepted'
        ).filter(ScoutingAllianceMember.team_number != team).all()

        alliance_deleted = False
        if not remaining_members:
            # Delete any pending invitations first to avoid foreign key NOT NULL errors
            ScoutingAllianceInvitation.query.filter_by(alliance_id=alliance_id).delete()
            db.session.delete(alliance)
            alliance_deleted = True

        db.session.commit()

        # Emit notification to remaining alliance members
        if not alliance_deleted:
            socketio.emit('alliance_member_left', {
                'alliance_id': alliance_id,
                'team_number': team,
                'team_name': f"Team {team}",
                'alliance_name': alliance_name
            }, room=f'alliance_{alliance_id}')

        return jsonify({
            'success': True,
            'message': f'Successfully left the alliance "{alliance_name}"',
            'alliance_deleted': alliance_deleted
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error leaving alliance via mobile API: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# New endpoints: allow mobile clients (alliance members) to fetch alliance-shared
# configs even when the team's alliance mode is not active.
@mobile_api.route('/alliances/<int:alliance_id>/config/game', methods=['GET'])
@token_required
def mobile_get_alliance_game_config(alliance_id):
    """Return the alliance shared game configuration to accepted alliance members."""
    team = getattr(request, 'mobile_team_number', None)
    if team is None:
        return jsonify({'success': False, 'error': 'Scouting team not resolved'}), 400

    # Verify requester is an accepted member of the alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=team,
        status='accepted'
    ).first()

    if not member:
        return jsonify({'success': False, 'error': 'Forbidden: not an alliance member'}), 403

    alliance = ScoutingAlliance.query.get_or_404(alliance_id)

    # Prefer explicit shared_game_config; fall back to alliance.game_config_team if set
    cfg = None
    if getattr(alliance, 'shared_game_config', None):
        try:
            cfg = json.loads(alliance.shared_game_config)
        except Exception:
            cfg = None
    elif getattr(alliance, 'game_config_team', None):
        try:
            from app.utils.config_manager import load_game_config
            cfg = load_game_config(team_number=alliance.game_config_team)
        except Exception:
            cfg = None
    else:
        cfg = {}

    return jsonify({'success': True, 'config': cfg, 'alliance_id': alliance_id, 'alliance_name': alliance.alliance_name}), 200


@mobile_api.route('/alliances/<int:alliance_id>/config/pit', methods=['GET'])
@token_required
def mobile_get_alliance_pit_config(alliance_id):
    """Return the alliance shared pit configuration to accepted alliance members."""
    team = getattr(request, 'mobile_team_number', None)
    if team is None:
        return jsonify({'success': False, 'error': 'Scouting team not resolved'}), 400

    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=team,
        status='accepted'
    ).first()

    if not member:
        return jsonify({'success': False, 'error': 'Forbidden: not an alliance member'}), 403

    alliance = ScoutingAlliance.query.get_or_404(alliance_id)

    cfg = None
    if getattr(alliance, 'shared_pit_config', None):
        try:
            cfg = json.loads(alliance.shared_pit_config)
        except Exception:
            cfg = None
    elif getattr(alliance, 'pit_config_team', None):
        try:
            from app.utils.config_manager import load_pit_config
            cfg = load_pit_config(team_number=alliance.pit_config_team)
        except Exception:
            cfg = None
    else:
        cfg = {}

    return jsonify({'success': True, 'config': cfg, 'alliance_id': alliance_id, 'alliance_name': alliance.alliance_name}), 200


@mobile_api.route('/alliances/<int:alliance_id>/config/game', methods=['POST', 'PUT'])
@token_required
def mobile_set_alliance_game_config(alliance_id):
    """Update the alliance shared game configuration via mobile API.

    Allows site admins (`admin`/`superadmin`) or alliance admins to update
    the alliance shared config even when the requesting team has not
    activated alliance mode. Requires JSON body containing the config.
    """
    user = getattr(request, 'mobile_user', None)
    if not user:
        return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401

    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Missing or invalid JSON body', 'error_code': 'MISSING_BODY'}), 400

    # Permission: site admin or alliance admin for this alliance
    allowed = False
    try:
        if user.has_role('admin') or user.has_role('superadmin'):
            allowed = True
    except Exception:
        allowed = False

    if not allowed:
        team = getattr(request, 'mobile_team_number', None)
        try:
            member = None
            if team is not None:
                member = ScoutingAllianceMember.query.filter_by(
                    alliance_id=alliance_id,
                    team_number=team,
                    role='admin',
                    status='accepted'
                ).first()
            if member:
                allowed = True
        except Exception:
            allowed = False

    if not allowed:
        return jsonify({'success': False, 'error': 'Forbidden: alliance admin required', 'error_code': 'FORBIDDEN'}), 403

    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    try:
        alliance.shared_game_config = json.dumps(data)
        db.session.add(alliance)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Failed to update alliance shared_game_config via mobile API: {e}")
        return jsonify({'success': False, 'error': 'Failed to save alliance config', 'error_code': 'SAVE_FAILED'}), 500


@mobile_api.route('/alliances/<int:alliance_id>/config/pit', methods=['POST', 'PUT'])
@token_required
def mobile_set_alliance_pit_config(alliance_id):
    """Update the alliance shared pit configuration via mobile API.

    Mirrors the game config endpoint and enforces the same permission
    requirements (site admin or alliance admin).
    """
    user = getattr(request, 'mobile_user', None)
    if not user:
        return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401

    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Missing or invalid JSON body', 'error_code': 'MISSING_BODY'}), 400

    # Permission check
    allowed = False
    try:
        if user.has_role('admin') or user.has_role('superadmin'):
            allowed = True
    except Exception:
        allowed = False

    if not allowed:
        team = getattr(request, 'mobile_team_number', None)
        try:
            member = None
            if team is not None:
                member = ScoutingAllianceMember.query.filter_by(
                    alliance_id=alliance_id,
                    team_number=team,
                    role='admin',
                    status='accepted'
                ).first()
            if member:
                allowed = True
        except Exception:
            allowed = False

    if not allowed:
        return jsonify({'success': False, 'error': 'Forbidden: alliance admin required', 'error_code': 'FORBIDDEN'}), 403

    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    try:
        alliance.shared_pit_config = json.dumps(data)
        db.session.add(alliance)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Failed to update alliance shared_pit_config via mobile API: {e}")
        return jsonify({'success': False, 'error': 'Failed to save alliance config', 'error_code': 'SAVE_FAILED'}), 500


@mobile_api.route('/invitations/<int:invitation_id>/respond', methods=['POST'])
def mobile_respond_invitation(invitation_id):
    """Respond to alliance invitation via mobile API"""
    data = request.get_json() or {}
    team = getattr(request, 'mobile_team_number', None)
    if team is None:
        return jsonify({'success': False, 'error': 'Scouting team not resolved'}), 400

    invitation = ScoutingAllianceInvitation.query.get_or_404(invitation_id)
    if invitation.to_team_number != team:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    response = data.get('response')
    if response not in ('accept', 'decline'):
        return jsonify({'success': False, 'error': 'Invalid response'}), 400

    try:
        if response == 'accept':
            if not TeamAllianceStatus.can_team_join_alliance(team, invitation.alliance_id):
                active_alliance_name = TeamAllianceStatus.get_active_alliance_name(team)
                return jsonify({'success': False, 'error': f'Cannot join alliance - your team is currently active in "{active_alliance_name}". Please deactivate your current alliance first.'}), 400

            member = ScoutingAllianceMember(
                alliance_id=invitation.alliance_id,
                team_number=team,
                team_name=f"Team {team}",
                role='member',
                status='accepted',
                invited_by=invitation.from_team_number
            )
            db.session.add(member)
            invitation.status = 'accepted'
            invitation.responded_at = datetime.now(timezone.utc)

            socketio.emit('alliance_member_joined', {
                'alliance_id': invitation.alliance_id,
                'team_number': team,
                'team_name': f"Team {team}"
            }, room=f'alliance_{invitation.alliance_id}')

        else:
            invitation.status = 'declined'
            invitation.responded_at = datetime.now(timezone.utc)

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error responding to invitation via mobile API: {str(e)}")
        return jsonify({'success': False, 'error': f'Error responding to invitation: {str(e)}'}), 500


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


@mobile_api.route('/admin/users/<int:user_id>', methods=['PUT', 'PATCH'])
@token_required
def mobile_update_user(user_id):
    """Update a user's profile/roles/active state using mobile API.

    Mirrors the /auth/users web update behavior for admins and superadmins.
    """
    try:
        actor = getattr(request, 'mobile_user', None)
        if not actor:
            return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401
        target = User.query.get(user_id)
        if not target:
            return jsonify({'success': False, 'error': 'User not found', 'error_code': 'USER_NOT_FOUND'}), 404

        # Determine privilege
        is_super = actor.has_role('superadmin')
        is_team_admin = actor.has_role('admin') and (getattr(actor, 'scouting_team_number', None) is not None and getattr(actor, 'scouting_team_number') == getattr(target, 'scouting_team_number', None))

        if not (is_super or is_team_admin):
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403

        # Prevent team-admins from modifying superadmins
        if target.has_role('superadmin') and not is_super:
            return jsonify({'success': False, 'error': 'Cannot modify superadmin user', 'error_code': 'PERMISSION_DENIED'}), 403

        data = request.get_json() or {}

        # If superadmin: allow username and scouting_team_number change
        if is_super:
            if 'username' in data:
                new_username = data.get('username')
                try:
                    new_team_raw = data.get('scouting_team_number')
                    new_team = safe_int_team_number(new_team_raw) if new_team_raw not in (None, '') else None
                except Exception:
                    new_team = data.get('scouting_team_number')
                if new_username:
                    conflict = User.query.filter(User.username == new_username, User.scouting_team_number == new_team, User.id != target.id).first()
                    if conflict:
                        return jsonify({'success': False, 'error': 'Username conflict for target team', 'error_code': 'USERNAME_CONFLICT'}), 409
                    target.username = new_username
                if 'scouting_team_number' in data:
                    target.scouting_team_number = new_team

        # Password
        if 'password' in data and data.get('password'):
            target.set_password(data.get('password'))

        # Active status
        if 'is_active' in data:
            target.is_active = bool(data.get('is_active'))

        # Email update - check uniqueness
        if 'email' in data:
            email_val = data.get('email') or None
            if email_val and User.query.filter(User.email == email_val, User.id != target.id).first():
                return jsonify({'success': False, 'error': 'Email already in use', 'error_code': 'EMAIL_EXISTS'}), 409
            target.email = email_val

        # Roles: list of role names (string) allowed; team-admins may not assign superadmin
        if 'roles' in data:
            roles_list = data.get('roles') or []
            if not isinstance(roles_list, list):
                return jsonify({'success': False, 'error': 'roles must be a list', 'error_code': 'INVALID_ROLES'}), 400
            # Team-admins cannot change their own roles unless superadmin
            if actor.id == target.id and not is_super:
                return jsonify({'success': False, 'error': 'Cannot modify your own roles', 'error_code': 'PERMISSION_DENIED'}), 403
            target.roles.clear()
            for rname in roles_list:
                try:
                    role_obj = Role.query.filter_by(name=str(rname)).first()
                except Exception:
                    role_obj = None
                # If not found by name, try numeric id lookup for backwards compatibility
                if not role_obj:
                    try:
                        rid = int(rname)
                        role_obj = Role.query.get(rid)
                    except Exception:
                        role_obj = None
                if role_obj:
                    if role_obj.name == 'superadmin' and not is_super:
                        return jsonify({'success': False, 'error': 'Only superadmins can assign superadmin role', 'error_code': 'PERMISSION_DENIED'}), 403
                    target.roles.append(role_obj)

        db.session.commit()
        return jsonify({'success': True, 'user': {
            'id': target.id,
            'username': target.username,
            'email': target.email,
            'team_number': target.scouting_team_number,
            'roles': target.get_role_names(),
            'is_active': target.is_active
        }}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"mobile_update_user error: {e}")
        return jsonify({'success': False, 'error': 'Failed to update user', 'error_code': 'UPDATE_ERROR'}), 500

            # Scope to actor's team

        users = query.all()
        users_data = [{
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'team_number': u.scouting_team_number,
            'roles': u.get_role_names(),
            'is_active': u.is_active
        } for u in users]
        return jsonify({'success': True, 'users': users_data, 'count': len(users_data)}), 200
    except Exception as e:
        current_app.logger.exception(f"mobile_list_users error: {e}")
        return jsonify({'success': False, 'error': 'Failed to list users', 'error_code': 'USERS_ERROR'}), 500


    


    


    



@mobile_api.route('/admin/roles', methods=['GET'])
@token_required
def mobile_list_roles():
    """List available roles for assignment. Admin-only (any admin/superadmin)."""
    try:
        actor = getattr(request, 'mobile_user', None)
        if not actor or not (actor.has_role('admin') or actor.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403
        roles = Role.query.all()
        roles_data = [{'id': r.id, 'name': r.name, 'description': r.description} for r in roles]
        return jsonify({'success': True, 'roles': roles_data}), 200
    except Exception as e:
        current_app.logger.exception(f"mobile_list_roles error: {e}")
        return jsonify({'success': False, 'error': 'Failed to list roles', 'error_code': 'ROLES_ERROR'}), 500


@mobile_api.route('/admin/users', methods=['GET'])
@token_required
def mobile_list_users():
    """List users. Scopes to admin's team unless superadmin."""
    try:
        actor = getattr(request, 'mobile_user', None)
        if not actor or not (actor.has_role('admin') or actor.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403

        query = User.query
        search = request.args.get('search')
        if search:
            from sqlalchemy import or_, func
            if search.isdigit():
                query = query.filter(or_(User.username.contains(search), User.scouting_team_number == int(search)))
            else:
                query = query.filter(or_(User.username.contains(search), func.cast(User.scouting_team_number, db.String).contains(search)))

        if not actor.has_role('superadmin'):
            query = query.filter_by(scouting_team_number=actor.scouting_team_number)

        # By default, exclude inactive users (soft-deleted). Allow admin clients
        # to include them explicitly via the 'include_inactive' query parameter.
        include_inactive = request.args.get('include_inactive', '0')
        if str(include_inactive).lower() not in ('1', 'true', 'yes', 'on'):
            query = query.filter_by(is_active=True)

        users = query.all()
        users_data = []
        for u in users:
            users_data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'team_number': u.scouting_team_number,
                'roles': u.get_role_names(),
                'is_active': u.is_active
            })
        return jsonify({'success': True, 'users': users_data, 'count': len(users_data)}), 200
    except Exception as e:
        current_app.logger.exception(f"mobile_list_users error: {e}")
        return jsonify({'success': False, 'error': 'Failed to list users', 'error_code': 'USERS_LIST_ERROR'}), 500


@mobile_api.route('/admin/users', methods=['POST'])
@token_required
def mobile_create_user():
    """Create a new user. Admins can create within their team; superadmins can set team."""
    try:
        actor = getattr(request, 'mobile_user', None)
        if not actor or not (actor.has_role('admin') or actor.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403

        data = request.get_json() or {}
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')
        team_raw = data.get('scouting_team_number')
        if not username or not password:
            return jsonify({'success': False, 'error': 'username and password required', 'error_code': 'MISSING_FIELDS'}), 400

        if not actor.has_role('superadmin'):
            team_number = actor.scouting_team_number
        else:
            team_number = safe_int_team_number(team_raw) if team_raw not in (None, '') else None

        # Username uniqueness per-team
        if User.query.filter_by(username=username, scouting_team_number=team_number).first():
            return jsonify({'success': False, 'error': 'Username already exists for that team', 'error_code': 'USERNAME_EXISTS'}), 409

        if email == '':
            email = None
        if email and User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'error': 'Email already exists', 'error_code': 'EMAIL_EXISTS'}), 409

        user = User(username=username, email=email, scouting_team_number=team_number)
        user.set_password(password)

        # Assign roles
        roles_list = data.get('roles') or []
        for r in roles_list:
            role_obj = None
            try:
                role_obj = Role.query.filter_by(name=str(r)).first()
            except Exception:
                pass
            if not role_obj:
                try:
                    role_obj = Role.query.get(int(r))
                except Exception:
                    role_obj = None
            if role_obj:
                if role_obj.name == 'superadmin' and not actor.has_role('superadmin'):
                    return jsonify({'success': False, 'error': 'Only superadmins can assign superadmin role', 'error_code': 'PERMISSION_DENIED'}), 403
                user.roles.append(role_obj)

        db.session.add(user)
        db.session.flush()

        # If first user for team, grant admin role
        try:
            count = User.query.filter_by(scouting_team_number=team_number).count()
            if count == 1:
                admin_role = Role.query.filter_by(name='admin').first()
                if admin_role:
                    user.roles.append(admin_role)
        except Exception:
            pass

        db.session.commit()

        return jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'email': user.email, 'team_number': user.scouting_team_number, 'roles': user.get_role_names()}}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"mobile_create_user error: {e}")
        return jsonify({'success': False, 'error': 'Failed to create user', 'error_code': 'CREATE_USER_ERROR'}), 500


@mobile_api.route('/admin/users/<int:user_id>', methods=['GET'])
@token_required
def mobile_get_user(user_id):
    """Return user details. Scoped to admin's team unless superadmin."""
    try:
        actor = getattr(request, 'mobile_user', None)
        if not actor or not (actor.has_role('admin') or actor.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403

        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found', 'error_code': 'USER_NOT_FOUND'}), 404

        if not actor.has_role('superadmin') and user.scouting_team_number != actor.scouting_team_number:
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403

        # Hide inactive users by default to mimic list behavior; allow retrieval when
        # explicitly requested via 'include_inactive' query parameter.
        include_inactive = request.args.get('include_inactive', '0')
        if not user.is_active and str(include_inactive).lower() not in ('1', 'true', 'yes', 'on'):
            return jsonify({'success': False, 'error': 'User not found', 'error_code': 'USER_NOT_FOUND'}), 404

        return jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'email': user.email, 'team_number': user.scouting_team_number, 'roles': user.get_role_names(), 'is_active': user.is_active}}), 200
    except Exception as e:
        current_app.logger.exception(f"mobile_get_user error: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve user', 'error_code': 'USER_GET_ERROR'}), 500


    except Exception as e:
        current_app.logger.exception(f"mobile_get_user error: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve user', 'error_code': 'USER_GET_ERROR'}), 500


@mobile_api.route('/admin/users/<int:user_id>', methods=['DELETE'])
@token_required
def mobile_delete_user(user_id):
    """Soft-delete (deactivate) a user. Team-admin cannot deactivate superadmin; cannot delete themselves."""
    try:
        actor = getattr(request, 'mobile_user', None)
        if not actor or not (actor.has_role('admin') or actor.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403

        user = User.query.get_or_404(user_id)

        # Prevent deleting self
        if user.id == actor.id:
            return jsonify({'success': False, 'error': 'You cannot delete your own account', 'error_code': 'PERMISSION_DENIED'}), 403

        # Allow deletion by superadmins, or team-admins for users in their same team
        is_super = actor.has_role('superadmin')
        is_team_admin = actor.has_role('admin') and (getattr(actor, 'scouting_team_number', None) == getattr(user, 'scouting_team_number', None))
        if not (is_super or is_team_admin):
            return jsonify({'success': False, 'error': 'Permission denied', 'error_code': 'PERMISSION_DENIED'}), 403

        # Prevent deleting other superadmins
        if user.has_role('superadmin') and not is_super:
            return jsonify({'success': False, 'error': 'Cannot permanently delete superadmin user', 'error_code': 'PERMISSION_DENIED'}), 403

        # Begin cleanup across binds: clear roles and remove device/subscription rows
        try:
            # Remove role associations (users bind)
            user.roles.clear()

            # Anonymize ScoutingData and PitScoutingData entries that reference this user as scout
            try:
                ScoutingData.query.filter(ScoutingData.scout_id == user.id).update({ 'scout_id': None, 'scout_name': None }, synchronize_session=False)
            except Exception:
                pass
            try:
                PitScoutingData.query.filter(PitScoutingData.scout_id == user.id).update({ 'scout_id': None, 'scout_name': None }, synchronize_session=False)
            except Exception:
                pass

            # Sanitize direct messages referencing this user
            try:
                ScoutingDirectMessage.query.filter(ScoutingDirectMessage.sender_id == user.id).update({ 'sender_id': None }, synchronize_session=False)
                ScoutingDirectMessage.query.filter(ScoutingDirectMessage.recipient_id == user.id).update({ 'recipient_id': None }, synchronize_session=False)
            except Exception:
                pass

            # Remove device tokens and notification subscriptions (misc bind)
            try:
                DeviceToken.query.filter_by(user_id=user.id).delete()
            except Exception:
                pass
            try:
                NotificationSubscription.query.filter_by(user_id=user.id).delete()
            except Exception:
                pass
        except Exception as cleanup_err:
            current_app.logger.exception(f"mobile_delete_user cleanup error: {cleanup_err}")

        # Perform the hard delete (permanent)
        try:
            db.session.delete(user)
            db.session.commit()
            try:
                current_app.logger.info(f"mobile_delete_user: actor={actor.id} target={user.id} permanently deleted")
            except Exception:
                pass
            return jsonify({'success': True, 'message': 'User permanently deleted'}), 200
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception(f"mobile_delete_user error: {e}")
            return jsonify({'success': False, 'error': 'Failed to permanently delete user', 'error_code': 'DELETE_USER_ERROR'}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"mobile_delete_user error: {e}")
        return jsonify({'success': False, 'error': 'Failed to deactivate user', 'error_code': 'DELETE_USER_ERROR'}), 500


@mobile_api.route('/teams', methods=['GET'])
@token_required
def get_teams():
    """
    Get list of teams filtered by user's scouting team
    
    Query params:
    - event_id: Filter by event (optional)
    - limit: Max results (default 100)
            actor = getattr(request, 'mobile_user', None)
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

        # Determine if the requesting team is in alliance mode and get member teams
        alliance = None
        alliance_member_numbers = []
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if alliance:
                # Use get_all_team_numbers to include game_config_team for data filtering
                alliance_member_numbers = alliance.get_all_team_numbers()
        except Exception:
            alliance = None

        # Base query: use isolation helper so alliance/shared events are respected
        teams_query = filter_teams_by_scouting_team()

        # Optional event filter by explicit event_id (query param)
        # event_id may be provided as an integer id OR as an event code (string).
        # Accept either form for backwards compatibility with clients that
        # pass the event code (e.g. 'arsea'). Resolve codes to numeric ids.
        # Uses team's configured season to pick correct year when multiple events exist.
        event_param = request.args.get('event_id')
        event_id = None
        if event_param is not None:
            try:
                # try integer first
                event_id = int(event_param)
            except Exception:
                # Not an integer — resolve by event code using team's season config
                event_id = resolve_event_code_to_id(event_param, team_number)
        if event_id:
            # Build teams list from matches for the event to avoid relying on
            # Team.events association which may be incomplete.
            if alliance and alliance_member_numbers:
                # Alliance mode - use alliance-aware function to get all teams for the event
                teams_list, _ = get_all_teams_for_alliance(event_id=event_id)
                # Return directly with pagination
                limit = min(request.args.get('limit', 100, type=int), 500)
                offset = request.args.get('offset', 0, type=int)
                
                total_count = len(teams_list)
                teams = teams_list[offset:offset+limit]
                
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
            else:
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
            event_code_team = game_config.get('current_event_code') if isinstance(game_config, dict) else None
            # If in alliance mode, prefer the alliance's current event if configured
            event_code = event_code_team
            try:
                if alliance and alliance_member_numbers:
                    alliance_event_code = None
                    try:
                        if alliance.shared_game_config:
                            acfg = json.loads(alliance.shared_game_config)
                            alliance_event_code = acfg.get('current_event_code')
                    except Exception:
                        alliance_event_code = None
                    if not alliance_event_code:
                        try:
                            aes = [ae for ae in alliance.events if getattr(ae, 'is_active', True)]
                            if aes:
                                alliance_event_code = aes[0].event_code
                        except Exception:
                            alliance_event_code = None
                    if not alliance_event_code and getattr(alliance, 'game_config_team', None):
                        try:
                            acfg = load_game_config(team_number=alliance.game_config_team)
                            if isinstance(acfg, dict):
                                alliance_event_code = acfg.get('current_event_code')
                        except Exception:
                            alliance_event_code = None
                    if alliance_event_code:
                        event_code = alliance_event_code
            except Exception:
                event_code = event_code_team

            # Resolve Event: prefer configured current_event_code, otherwise
            # pick the most recent Event for this scouting team.
            # Construct year-prefixed event code if needed (database stores codes like '2026OKTU')
            event = None
            if event_code:
                # Try year-prefixed code first
                year_prefixed_code = event_code
                if not (len(str(event_code)) >= 4 and str(event_code)[:4].isdigit()):
                    season = game_config.get('season', 2026) if isinstance(game_config, dict) else 2026
                    year_prefixed_code = f"{season}{event_code}"
                event = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=team_number).first()
                # Fall back to raw code if year-prefixed not found
                if not event and year_prefixed_code != event_code:
                    event = Event.query.filter_by(code=event_code, scouting_team_number=team_number).first()
            if not event:
                event = Event.query.filter_by(scouting_team_number=team_number).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).first()

            if not event:
                # No configured or recent event found — return empty list to
                # avoid returning teams from unrelated events.
                return jsonify({'success': True, 'teams': [], 'count': 0, 'total': 0}), 200

            # Alliance mode - use alliance-aware function to get all teams for the event
            if alliance and alliance_member_numbers:
                teams_list, _ = get_all_teams_for_alliance(event_id=event.id)
                # Return directly with pagination
                limit = min(request.args.get('limit', 100, type=int), 500)
                offset = request.args.get('offset', 0, type=int)
                
                total_count = len(teams_list)
                teams = teams_list[offset:offset+limit]
                
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

            # Collect team numbers from matches for this event. Prefer matches
            # that are scoped to the scouting_team_number, but fall back to any
            # matches for the event if none are scoped.
            matches = filter_matches_by_scouting_team().filter(Match.event_id == event.id).all()
            if not matches:
                # No matches scoped to the user's scouting team; only consider
                # global/unscoped matches (scouting_team_number IS NULL) to avoid
                # returning data from other scouting teams.
                matches = Match.query.filter(
                    Match.event_id == event.id,
                    db.or_(Match.scouting_team_number == team_number, Match.scouting_team_number.is_(None))
                ).all()

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


@mobile_api.route('/teams/current', methods=['GET'])
@token_required
def get_teams_current():
    """
    Get list of teams for the current event
    
    Query params:
    - limit: Max results (default 100)
    - offset: Pagination offset (default 0)
            
    Response:
    {
        "success": true,
        "teams": [...],
        "count": 10,
        "total": 50,
        "event": {
            "id": 1,
            "name": "Event Name",
            "code": "2026CODE"
        }
    }
    """
    try:
        team_number = request.mobile_team_number

        # Determine if the requesting team is in alliance mode and get member teams
        alliance = None
        alliance_member_numbers = []
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if alliance:
                alliance_member_numbers = alliance.get_all_team_numbers()
        except Exception:
            alliance = None

        # Resolve current event from team config (respecting alliance shared config)
        from app.utils.config_manager import load_game_config
        game_config = load_game_config(team_number=team_number)
        event_code_team = game_config.get('current_event_code') if isinstance(game_config, dict) else None
        
        # If in alliance mode, prefer the alliance's current event if configured
        event_code = event_code_team
        try:
            if alliance and alliance_member_numbers:
                alliance_event_code = None
                try:
                    if alliance.shared_game_config:
                        acfg = json.loads(alliance.shared_game_config)
                        alliance_event_code = acfg.get('current_event_code')
                except Exception:
                    alliance_event_code = None
                if not alliance_event_code:
                    try:
                        aes = [ae for ae in alliance.events if getattr(ae, 'is_active', True)]
                        if aes:
                            alliance_event_code = aes[0].event_code
                    except Exception:
                        alliance_event_code = None
                if not alliance_event_code and getattr(alliance, 'game_config_team', None):
                    try:
                        acfg = load_game_config(team_number=alliance.game_config_team)
                        if isinstance(acfg, dict):
                            alliance_event_code = acfg.get('current_event_code')
                    except Exception:
                        alliance_event_code = None
                if alliance_event_code:
                    event_code = alliance_event_code
        except Exception:
            event_code = event_code_team

        # Resolve Event: prefer configured current_event_code, otherwise pick the most recent Event
        event = None
        if event_code:
            # Try year-prefixed code first
            year_prefixed_code = event_code
            if not (len(str(event_code)) >= 4 and str(event_code)[:4].isdigit()):
                season = game_config.get('season', 2026) if isinstance(game_config, dict) else 2026
                year_prefixed_code = f"{season}{event_code}"
            event = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=team_number).first()
            # Fall back to raw code if year-prefixed not found
            if not event and year_prefixed_code != event_code:
                event = Event.query.filter_by(code=event_code, scouting_team_number=team_number).first()
        if not event:
            event = Event.query.filter_by(scouting_team_number=team_number).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).first()

        if not event:
            return jsonify({
                'success': True,
                'teams': [],
                'count': 0,
                'total': 0,
                'event': None
            }), 200

        # Alliance mode - use alliance-aware function to get all teams for the event
        if alliance and alliance_member_numbers:
            teams_list, _ = get_all_teams_for_alliance(event_id=event.id)
            # Return directly with pagination
            limit = min(request.args.get('limit', 100, type=int), 500)
            offset = request.args.get('offset', 0, type=int)
            
            total_count = len(teams_list)
            teams = teams_list[offset:offset+limit]
            
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
                'total': total_count,
                'event': {
                    'id': event.id,
                    'name': event.name,
                    'code': event.code
                }
            }), 200

        # Collect team numbers from matches for this event
        matches = filter_matches_by_scouting_team().filter(Match.event_id == event.id).all()
        if not matches:
            matches = Match.query.filter(
                Match.event_id == event.id,
                db.or_(Match.scouting_team_number == team_number, Match.scouting_team_number.is_(None))
            ).all()

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
            return jsonify({
                'success': True,
                'teams': [],
                'count': 0,
                'total': 0,
                'event': {
                    'id': event.id,
                    'name': event.name,
                    'code': event.code
                }
            }), 200

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
            'total': total_count,
            'event': {
                'id': event.id,
                'name': event.name,
                'code': event.code
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get teams current error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve current teams',
            'error_code': 'TEAMS_CURRENT_ERROR'
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

        # Resolve alliance mode and members
        alliance = None
        alliance_member_numbers = []
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if alliance:
                # Use get_all_team_numbers to include game_config_team for data filtering
                alliance_member_numbers = alliance.get_all_team_numbers()
        except Exception:
            alliance = None

        # If alliance active, allow team details for alliance member teams (by team_number)
        team = None
        if alliance and alliance_member_numbers:
            # Try to find a Team that matches the requested id and is in the alliance
            t = Team.query.get(team_id)
            if t and t.team_number in alliance_member_numbers:
                team = t
        if not team:
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
        
        # Get recent matches. When alliance mode is active, include matches that
        # involve this team regardless of match.scouting_team_number.
        if alliance and alliance_member_numbers:
            recent_matches = Match.query.filter(
                db.or_(
                    Match.red_alliance.contains(str(team.team_number)),
                    Match.blue_alliance.contains(str(team.team_number))
                )
            ).order_by(Match.match_number.desc()).limit(10).all()
        else:
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

        # Determine if the team is in alliance mode
        alliance = None
        alliance_member_numbers = []
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if alliance:
                # Use get_all_team_numbers to include game_config_team for data filtering
                alliance_member_numbers = alliance.get_all_team_numbers()
        except Exception:
            alliance = None

        if alliance:
            # Mirror web /events/ behavior: show events from alliance members and explicit alliance event codes
            # Collect alliance member team numbers and explicit alliance event codes
            try:
                member_team_numbers = [m.team_number for m in alliance.get_active_members()]
            except Exception:
                member_team_numbers = []

            try:
                alliance_event_codes = alliance.get_shared_events() or []
            except Exception:
                alliance_event_codes = []

            # Query events associated with members' teams
            try:
                member_events = Event.query.join(Event.teams).filter(Team.team_number.in_(member_team_numbers)).distinct().all()
            except Exception:
                member_events = []

            # Query events explicitly added to alliance (match raw code or strip leading 4-digit year)
            from sqlalchemy import func
            code_events = []
            if alliance_event_codes:
                codes_upper = [c.strip().upper() for c in alliance_event_codes]
                try:
                    code_events = Event.query.filter(
                        func.upper(Event.code).in_(codes_upper)
                    ).all()
                except Exception:
                    # best-effort fallback: try stripping a leading year for matching
                    try:
                        code_events = Event.query.filter(func.upper(func.substr(Event.code, 5)).in_(codes_upper)).all()
                    except Exception:
                        code_events = []

            # Union the results preserving order logic from web view
            combined = list(member_events)
            for e in code_events:
                if e not in combined:
                    combined.append(e)

            try:
                events = sorted(combined, key=lambda x: (x.year if getattr(x, 'year', None) is not None else 0, x.name), reverse=True)
            except Exception:
                events = combined
        else:
            # Default behavior: show events that involve teams from this scouting team.
            # Order by most recent year first and then by name to be consistent with UI dropdowns.
            events = Event.query.join(Event.teams).filter(
                Team.scouting_team_number == team_number
            ).distinct().order_by(Event.year.desc(), Event.name).all()
        
        # Deduplicate events by code and mark if they are from an alliance
        from app.models import ScoutingAllianceEvent
        from sqlalchemy import func
        def event_score(e):
            score = 0
            if e.name: score += 10
            if e.location: score += 5
            if getattr(e, 'start_date', None): score += 5
            if getattr(e, 'end_date', None): score += 3
            if getattr(e, 'timezone', None): score += 2
            if e.year: score += 1
            return score

        # Separate dictionaries for team events and alliance events (match web behavior)
        team_events_by_code = {}
        alliance_events_by_code = {}

        # Precompute alliance sets if alliance mode is active
        alliance_event_codes_upper = set([c.strip().upper() for c in (alliance.get_shared_events() if alliance else [])]) if alliance else set()
        member_team_numbers_set = set([m.team_number for m in (alliance.get_active_members() if alliance else [])]) if alliance else set()

        for e in events:
            code = (e.code or f'__id_{e.id}').strip().upper()
            try:
                # Compute stripped code
                from app.utils.api_utils import strip_year_prefix
                code_stripped = strip_year_prefix(code)
            except Exception:
                code_stripped = code

            # Determine if this event should be treated as an alliance event
            is_alliance_event = False
            try:
                event_scouting_team = getattr(e, 'scouting_team_number', None)

                if alliance:
                    if (code in alliance_event_codes_upper) or (code_stripped in alliance_event_codes_upper):
                        if event_scouting_team != team_number:
                            is_alliance_event = True
                    else:
                        if event_scouting_team and event_scouting_team != team_number and event_scouting_team in member_team_numbers_set:
                            is_alliance_event = True

                if not is_alliance_event and not code.startswith('__id_'):
                    sae = ScoutingAllianceEvent.query.filter(
                        func.upper(ScoutingAllianceEvent.event_code).in_([code, code_stripped]),
                        ScoutingAllianceEvent.is_active == True
                    ).first()
                    if sae is not None and event_scouting_team != team_number:
                        is_alliance_event = True
            except Exception:
                is_alliance_event = False

            # Attach attribute and assign to appropriate bucket
            try:
                setattr(e, 'is_alliance', is_alliance_event)
            except Exception:
                pass

            # Place into team/alliance dicts with scoring tie-breakers
            if is_alliance_event:
                if code in alliance_events_by_code:
                    if event_score(e) > event_score(alliance_events_by_code[code]):
                        alliance_events_by_code[code] = e
                else:
                    alliance_events_by_code[code] = e
            else:
                if code in team_events_by_code:
                    if event_score(e) > event_score(team_events_by_code[code]):
                        team_events_by_code[code] = e
                else:
                    team_events_by_code[code] = e

        # Combine both lists - team events first, then alliance events
        deduped_events = list(team_events_by_code.values()) + list(alliance_events_by_code.values())
        try:
            events = sorted(deduped_events, key=lambda x: (getattr(x, 'year', 0) or 0, getattr(x, 'name', '') or ''), reverse=True)
        except Exception:
            events = deduped_events

        events_data = []
        # Build response from the resolved `events` list; each event already has `is_alliance` set
        for event in events:
            is_alliance = getattr(event, 'is_alliance', False)
            events_data.append({
                'id': event.id,
                'name': event.name,
                'code': event.code,
                'location': event.location,
                'start_date': event.start_date.isoformat() if event.start_date else None,
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'timezone': event.timezone,
                'team_count': len(event.teams),
                'is_alliance': is_alliance
            })
        
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
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
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
        # Accept event_id as integer or event code string
        # Uses team's configured season to pick correct year when multiple events exist.
        event_param = request.args.get('event_id')
        event_id = None
        if event_param is not None:
            try:
                event_id = int(event_param)
            except Exception:
                # Not an integer — resolve by event code using team's season config
                event_id = resolve_event_code_to_id(event_param, team_number)

        # Determine alliance status for requesting team
        alliance = None
        alliance_member_numbers = []
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if alliance:
                # Use get_all_team_numbers to include game_config_team for data filtering
                alliance_member_numbers = alliance.get_all_team_numbers()
        except Exception:
            alliance = None
        
        if not event_id:
            # Resolve current event from team config (respecting alliance shared config)
            from app.utils.config_manager import load_game_config
            game_config = load_game_config(team_number=team_number)
            event_code_team = game_config.get('current_event_code') if isinstance(game_config, dict) else None
            # Determine alliance's preferred event if in alliance mode
            event_code = event_code_team
            try:
                if alliance and alliance_member_numbers:
                    alliance_event_code = None
                    try:
                        if alliance.shared_game_config:
                            acfg = json.loads(alliance.shared_game_config)
                            alliance_event_code = acfg.get('current_event_code')
                    except Exception:
                        alliance_event_code = None
                    if not alliance_event_code:
                        try:
                            aes = [ae for ae in alliance.events if getattr(ae, 'is_active', True)]
                            if aes:
                                alliance_event_code = aes[0].event_code
                        except Exception:
                            alliance_event_code = None
                    if not alliance_event_code and getattr(alliance, 'game_config_team', None):
                        try:
                            acfg = load_game_config(team_number=alliance.game_config_team)
                            if isinstance(acfg, dict):
                                alliance_event_code = acfg.get('current_event_code')
                        except Exception:
                            alliance_event_code = None
                    if alliance_event_code:
                        event_code = alliance_event_code
            except Exception:
                event_code = event_code_team

            # Resolve Event: prefer configured current_event_code, otherwise pick the most recent Event for the team.
            # Construct year-prefixed event code if needed (database stores codes like '2026OKTU')
            event = None
            if event_code:
                # Try year-prefixed code first
                year_prefixed_code = event_code
                if not (len(str(event_code)) >= 4 and str(event_code)[:4].isdigit()):
                    season = game_config.get('season', 2026) if isinstance(game_config, dict) else 2026
                    year_prefixed_code = f"{season}{event_code}"
                event = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=team_number).first()
                # Fall back to raw code if year-prefixed not found
                if not event and year_prefixed_code != event_code:
                    event = Event.query.filter_by(code=event_code, scouting_team_number=team_number).first()
            if not event:
                event = Event.query.filter_by(scouting_team_number=team_number).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).first()
            if not event:
                # No configured or recent event found — return empty list
                return jsonify({'success': True, 'matches': [], 'count': 0}), 200
            event_id = event.id
        
        # Build the base query: allow event_id resolution and use the helper that respects alliance config
        if event_id:
            if alliance and alliance_member_numbers:
                # Alliance mode - use alliance-aware function to get all matches for the event
                matches, _ = get_all_matches_for_alliance(event_id=event_id)
            else:
                matches_query = filter_matches_by_scouting_team().filter(Match.event_id == event_id)
                matches = matches_query.order_by(Match.match_number).all()
        else:
            return jsonify({
                'success': False,
                'error': 'event_id is required',
                'error_code': 'MISSING_EVENT_ID'
            }), 400
        
        # Optional filters (apply after getting matches)
        match_type = request.args.get('match_type')
        if match_type:
            matches = [m for m in matches if m.match_type == match_type]
        
        team_filter = request.args.get('team_number', type=int)
        if team_filter:
            team_str = str(team_filter)
            matches = [m for m in matches if (m.red_alliance and team_str in m.red_alliance) or (m.blue_alliance and team_str in m.blue_alliance)]
        
        matches_data = [{
            'id': match.id,
            'match_number': match.match_number,
            'match_type': match.match_type,
            'red_alliance': match.red_alliance,
            'blue_alliance': match.blue_alliance,
            'red_score': match.red_score,
            'blue_score': match.blue_score,
            'winner': match.winner
            ,
            'scheduled_time': match.scheduled_time.isoformat() if hasattr(match, 'scheduled_time') and match.scheduled_time else None,
            'predicted_time': match.predicted_time.isoformat() if hasattr(match, 'predicted_time') and match.predicted_time else None,
            'actual_time': getattr(match, 'actual_time', None).isoformat() if getattr(match, 'actual_time', None) else None
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


@mobile_api.route('/matches/current', methods=['GET'])
@token_required
def get_matches_current():
    """
    Get matches for the current event
    
    Query params:
    - match_type: Filter by match type (optional)
    - team_number: Filter by team (optional)
    
    Response:
    {
        "success": true,
        "matches": [...],
        "count": 10,
        "event": {
            "id": 1,
            "name": "Event Name",
            "code": "2026CODE"
        }
    }
    """
    try:
        team_number = request.mobile_team_number
        
        # Determine alliance status for requesting team
        alliance = None
        alliance_member_numbers = []
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            if alliance:
                alliance_member_numbers = alliance.get_all_team_numbers()
        except Exception:
            alliance = None
        
        # Resolve current event from team config (respecting alliance shared config)
        from app.utils.config_manager import load_game_config
        game_config = load_game_config(team_number=team_number)
        event_code_team = game_config.get('current_event_code') if isinstance(game_config, dict) else None
        
        # Determine alliance's preferred event if in alliance mode
        event_code = event_code_team
        try:
            if alliance and alliance_member_numbers:
                alliance_event_code = None
                try:
                    if alliance.shared_game_config:
                        acfg = json.loads(alliance.shared_game_config)
                        alliance_event_code = acfg.get('current_event_code')
                except Exception:
                    alliance_event_code = None
                if not alliance_event_code:
                    try:
                        aes = [ae for ae in alliance.events if getattr(ae, 'is_active', True)]
                        if aes:
                            alliance_event_code = aes[0].event_code
                    except Exception:
                        alliance_event_code = None
                if not alliance_event_code and getattr(alliance, 'game_config_team', None):
                    try:
                        acfg = load_game_config(team_number=alliance.game_config_team)
                        if isinstance(acfg, dict):
                            alliance_event_code = acfg.get('current_event_code')
                    except Exception:
                        alliance_event_code = None
                if alliance_event_code:
                    event_code = alliance_event_code
        except Exception:
            event_code = event_code_team

        # Resolve Event: prefer configured current_event_code, otherwise pick the most recent Event
        event = None
        if event_code:
            # Try year-prefixed code first
            year_prefixed_code = event_code
            if not (len(str(event_code)) >= 4 and str(event_code)[:4].isdigit()):
                season = game_config.get('season', 2026) if isinstance(game_config, dict) else 2026
                year_prefixed_code = f"{season}{event_code}"
            event = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=team_number).first()
            # Fall back to raw code if year-prefixed not found
            if not event and year_prefixed_code != event_code:
                event = Event.query.filter_by(code=event_code, scouting_team_number=team_number).first()
        if not event:
            event = Event.query.filter_by(scouting_team_number=team_number).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).first()
        
        if not event:
            return jsonify({
                'success': True,
                'matches': [],
                'count': 0,
                'event': None
            }), 200
        
        # Build the base query using the resolved event
        if alliance and alliance_member_numbers:
            # Alliance mode - use alliance-aware function to get all matches for the event
            matches, _ = get_all_matches_for_alliance(event_id=event.id)
        else:
            matches_query = filter_matches_by_scouting_team().filter(Match.event_id == event.id)
            matches = matches_query.order_by(Match.match_number).all()
        
        # Optional filters (apply after getting matches)
        match_type = request.args.get('match_type')
        if match_type:
            matches = [m for m in matches if m.match_type == match_type]
        
        team_filter = request.args.get('team_number', type=int)
        if team_filter:
            team_str = str(team_filter)
            matches = [m for m in matches if (m.red_alliance and team_str in m.red_alliance) or (m.blue_alliance and team_str in m.blue_alliance)]
        
        matches_data = [{
            'id': match.id,
            'match_number': match.match_number,
            'match_type': match.match_type,
            'red_alliance': match.red_alliance,
            'blue_alliance': match.blue_alliance,
            'red_score': match.red_score,
            'blue_score': match.blue_score,
            'winner': match.winner,
            'scheduled_time': match.scheduled_time.isoformat() if hasattr(match, 'scheduled_time') and match.scheduled_time else None,
            'predicted_time': match.predicted_time.isoformat() if hasattr(match, 'predicted_time') and match.predicted_time else None,
            'actual_time': getattr(match, 'actual_time', None).isoformat() if getattr(match, 'actual_time', None) else None
        } for match in matches]
        
        return jsonify({
            'success': True,
            'matches': matches_data,
            'count': len(matches_data),
            'event': {
                'id': event.id,
                'name': event.name,
                'code': event.code
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get matches current error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve current matches',
            'error_code': 'MATCHES_CURRENT_ERROR'
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
        
        # Sync to alliance if active
        sync_scouting_to_alliance(scouting_data, team_number)
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
                
                # Sync to alliance if active
                sync_scouting_to_alliance(scouting_data, team_number)
                
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
        
        # Get user's scouting entries - filter by scout_id to avoid collisions
        # when multiple users share the same username across different teams.
        entries = ScoutingData.query.filter_by(
            scout_id=user.id,
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
    Uses alliance shared data if alliance mode is active for the team.

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
      "entries": [{...}],
      "is_alliance_mode": false
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
        # Uses team's configured season to pick correct year when multiple events exist.
        event_param = request.args.get('event_id')
        event_id = None
        if event_param is not None:
            try:
                event_id = int(event_param)
            except Exception:
                # Not an integer — resolve by event code using team's season config
                event_id = resolve_event_code_to_id(event_param, team_number)

        limit = min(request.args.get('limit', 200, type=int), 2000)
        offset = request.args.get('offset', 0, type=int)

        # Check if alliance mode is active for this team
        alliance_id = get_active_alliance_id_for_team(team_number)
        is_alliance_mode = alliance_id is not None

        # Resolve team_id if team_number filter is provided
        resolved_team_id = q_team_id
        if not resolved_team_id and q_team_number and q_team_number != team_number:
            t_scouted = Team.query.filter_by(team_number=q_team_number, scouting_team_number=team_number).first()
            if not t_scouted:
                t_scouted = Team.query.filter_by(team_number=q_team_number).first()
            if t_scouted:
                resolved_team_id = t_scouted.id
            else:
                return jsonify({'success': True, 'count': 0, 'total': 0, 'entries': [], 'is_alliance_mode': is_alliance_mode}), 200

        if is_alliance_mode:
            # Alliance mode - query from shared tables
            # Note: Must query by team_number, not team_id, because different alliance members
            # have different team_id values for the same team_number
            base_q = AllianceSharedScoutingData.query.filter_by(
                alliance_id=alliance_id,
                is_active=True
            )
            
            # Apply team filter by team_number if provided
            team_number_filter = q_team_number
            if not team_number_filter and resolved_team_id:
                t_for_filter = Team.query.get(resolved_team_id)
                if t_for_filter:
                    team_number_filter = t_for_filter.team_number
            
            if team_number_filter:
                # Join with Team and filter by team_number
                base_q = base_q.join(
                    Team, AllianceSharedScoutingData.team_id == Team.id
                ).filter(Team.team_number == team_number_filter)
            
            if match_id:
                # Note: match_id filtering in alliance mode may need similar treatment
                # for now, filter by match_id directly since it references the source team's match
                base_q = base_q.filter(AllianceSharedScoutingData.match_id == match_id)
            
            # Join for related data (only if not already joined)
            if team_number_filter:
                # Team already joined, just add Match and Event
                joined_q = base_q.join(Match, AllianceSharedScoutingData.match_id == Match.id).join(Event, Match.event_id == Event.id)
            else:
                joined_q = base_q.join(Match, AllianceSharedScoutingData.match_id == Match.id).join(Team, AllianceSharedScoutingData.team_id == Team.id).join(Event, Match.event_id == Event.id)
            
            if event_id:
                # Filter by event code, not event_id, since event_ids differ across alliance members
                event_for_filter = Event.query.get(event_id)
                if event_for_filter and event_for_filter.code:
                    from sqlalchemy import func
                    joined_q = joined_q.filter(func.upper(Event.code) == func.upper(event_for_filter.code))
                else:
                    joined_q = joined_q.filter(Match.event_id == event_id)
            
            total = joined_q.count()
            rows = joined_q.order_by(AllianceSharedScoutingData.timestamp.desc()).offset(offset).limit(limit).all()
            
            entries = []
            for r in rows:
                team_obj = getattr(r, 'team', None)
                match_obj = getattr(r, 'match', None)
                event_obj = getattr(match_obj, 'event', None) if match_obj else None

                entries.append({
                    'id': r.id,
                    'shared_id': r.id,
                    'original_id': r.original_scouting_data_id,
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
                    'scouting_team_number': r.source_scouting_team_number,
                    'source_team': r.source_scouting_team_number,
                    'data': r.data,
                    'is_alliance_data': True
                })
        else:
            # Normal mode - query from team's data
            base_q = ScoutingData.query.filter_by(scouting_team_number=team_number)

            if resolved_team_id:
                base_q = base_q.filter(ScoutingData.team_id == resolved_team_id)

            if match_id:
                base_q = base_q.filter(ScoutingData.match_id == match_id)

            joined_q = base_q.join(Match, ScoutingData.match_id == Match.id).join(Team, ScoutingData.team_id == Team.id).join(Event, Match.event_id == Event.id)

            if event_id:
                joined_q = joined_q.filter(Match.event_id == event_id)

            total = joined_q.count()
            rows = joined_q.order_by(ScoutingData.timestamp.desc()).offset(offset).limit(limit).all()

            entries = []
            for r in rows:
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
                    'data': r.data,
                    'is_alliance_data': False
                })

        return jsonify({'success': True, 'count': len(entries), 'total': total, 'entries': entries, 'is_alliance_mode': is_alliance_mode}), 200

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
        
        # Sync to alliance if active
        sync_pit_to_alliance(pit_data, team_number)
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
            # Only permit overriding to a different team when the caller is a
            # superadmin. Otherwise, reject to avoid exposing other teams' configs.
            if mobile_user and getattr(mobile_user, 'has_role', None) and mobile_user.has_role('superadmin'):
                current_app.logger.info(f"mobile_api.get_game_config: superadmin override requested_team={requested_team}; using it instead of resolved {team_number}")
                team_number = requested_team
            else:
                try:
                    if int(requested_team) != int(team_number if team_number is not None else -999999):
                        return jsonify({'success': False, 'error': 'Forbidden to access another team', 'error_code': 'FORBIDDEN'}), 403
                except Exception:
                    return jsonify({'success': False, 'error': 'Forbidden to access another team', 'error_code': 'FORBIDDEN'}), 403

        # Determine if the team is currently in an active alliance; if so,
        # prefer the alliance's shared config or its configured team's config.
        alliance_cfg = None
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
        except Exception:
            alliance = None

        # If alliance is active, prefer alliance's shared or referenced team config
        if alliance:
            try:
                if alliance.shared_game_config:
                    alliance_cfg = json.loads(alliance.shared_game_config)
                elif getattr(alliance, 'game_config_team', None):
                    from app.utils.config_manager import load_game_config as _load_game_config
                    alt_cfg = _load_game_config(team_number=alliance.game_config_team)
                    if alt_cfg:
                        alliance_cfg = alt_cfg
            except Exception:
                alliance_cfg = None

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
        # Use alliance config if present (take precedence over team config)
        if alliance_cfg is not None:
            current_app.logger.debug(f"mobile_api.get_game_config: using alliance config for team {team_number}")
            game_config = alliance_cfg
        else:
            if game_config is None:
                current_app.logger.debug(f"mobile_api.get_game_config: falling back to load_game_config for team {team_number}")
                game_config = load_game_config(team_number=team_number)
        
        # Determine the effective "current event" for this requester. Prefer
        # an active alliance's configured/current event when alliance mode is
        # active. Fall back to the team-specific `current_event_code`.
        current_event = None
        current_event_is_alliance = False
        try:
            from app.utils.config_manager import load_game_config as _load_game_config

            # Resolve alliance, if any
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
            alliance_event_code = None
            if alliance:
                # If alliance defines a shared_game_config, use its current_event_code
                try:
                    if alliance.shared_game_config:
                        cfg = json.loads(alliance.shared_game_config)
                        alliance_event_code = cfg.get('current_event_code')
                except Exception:
                    alliance_event_code = None

                # If still no code, check explicit ScoutingAllianceEvent entries
                if not alliance_event_code:
                    try:
                        aes = [ae for ae in alliance.events if getattr(ae, 'is_active', True)]
                        if aes:
                            alliance_event_code = aes[0].event_code
                    except Exception:
                        pass

                # If alliance has a game_config_team flag, resolve that team's current_event
                if not alliance_event_code and getattr(alliance, 'game_config_team', None):
                    try:
                        alt_cfg = _load_game_config(team_number=alliance.game_config_team)
                        if isinstance(alt_cfg, dict):
                            alliance_event_code = alt_cfg.get('current_event_code')
                    except Exception:
                        pass

            # Team-level current event
            team_cfg_current = None
            if isinstance(game_config, dict):
                team_cfg_current = game_config.get('current_event_code')
            else:
                try:
                    # Fall back to loader in case team_config wasn't a dict
                    tcfg = _load_game_config(team_number=team_number)
                    if isinstance(tcfg, dict):
                        team_cfg_current = tcfg.get('current_event_code')
                except Exception:
                    team_cfg_current = None

            # Choose alliance code over team code when present
            chosen_code = alliance_event_code or team_cfg_current or None
            if chosen_code:
                # Resolve code to Event record (prefer scoped to team, otherwise global)
                evt = Event.query.filter_by(code=str(chosen_code), scouting_team_number=team_number).first()
                if not evt:
                    evt = Event.query.filter_by(code=str(chosen_code)).first()
                if evt:
                    current_event = {
                        'id': evt.id,
                        'code': evt.code,
                        'name': evt.name,
                        'scoping': 'alliance' if bool(alliance_event_code) and alliance_event_code == chosen_code else 'team'
                    }
                    current_event_is_alliance = bool(alliance_event_code) and alliance_event_code == chosen_code
                else:
                    # No Event record found — still expose the code as string
                    current_event = {
                        'id': None,
                        'code': str(chosen_code).upper(),
                        'name': None,
                        'scoping': 'alliance' if bool(alliance_event_code) and alliance_event_code == chosen_code else 'team'
                    }
        except Exception:
            current_event = None
            current_event_is_alliance = False

        # Return the full game configuration (gameconfig.json) for this scouting team
        # This mirrors the web UI and ensures mobile clients receive the complete
        # form definition, rules, and any custom settings.
        resp = {'success': True, 'config': game_config}
        if current_event is not None:
            resp['current_event'] = current_event
            resp['current_event_is_alliance'] = current_event_is_alliance
        return jsonify(resp), 200
        
    except Exception as e:
        current_app.logger.error(f"Get game config error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve game configuration',
            'error_code': 'CONFIG_ERROR'
        }), 500


@mobile_api.route('/config/game/active', methods=['GET'])
@token_required
def get_game_config_active():
    """
    Alias for the active config (preference for alliance shared config when active).
    """
    return get_game_config()


@mobile_api.route('/config/game/team', methods=['GET'])
@token_required
def get_game_config_team():
    """
    Return the explicit per-team game config file (team config only, no alliance merge).
    """
    try:
        token_team = getattr(request, 'mobile_team_number', None)
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

        team_number = requested_team if requested_team is not None else token_team
        # Only allow explicit request for different team if caller is superadmin
        if requested_team is not None and requested_team != token_team:
            user = getattr(request, 'mobile_user', None)
            if not (user and getattr(user, 'has_role', None) and user.has_role('superadmin')):
                return jsonify({'success': False, 'error': 'Forbidden to access another team', 'error_code': 'FORBIDDEN'}), 403
        from app.utils.config_manager import load_game_config
        game_config = None
        try:
            if team_number is not None:
                base_dir = os.getcwd()
                team_config_path = os.path.join(base_dir, 'instance', 'configs', str(team_number), 'game_config.json')
                if os.path.exists(team_config_path):
                    with open(team_config_path, 'r', encoding='utf-8') as f:
                        try:
                            game_config = json.load(f)
                        except Exception:
                            current_app.logger.warning(f"Invalid JSON in team game_config for team {team_number}")
        except Exception:
            game_config = None

        if game_config is None:
            game_config = load_game_config(team_number=team_number)

        return jsonify({'success': True, 'config': game_config}), 200
    except Exception as e:
        current_app.logger.error(f"Get team game config error: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to retrieve team game configuration', 'error_code': 'CONFIG_ERROR'}), 500


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

        # Require admin or superadmin role to modify config OR allow alliance admins
        allowed = user.has_role('admin') or user.has_role('superadmin')
        if not allowed:
            # Allow alliance admins (who may not be team admins) to edit the
            # active (alliance) configuration. We only check for alliance
            # admin on the resolved team number from the token or request.
            from app.utils.alliance_data import get_active_alliance_id_for_team, is_alliance_admin
            token_team = getattr(request, 'mobile_team_number', None)
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

            team_number_to_check = requested_team if requested_team is not None else token_team
            try:
                alliance_id_check = get_active_alliance_id_for_team(team_number_to_check)
            except Exception:
                alliance_id_check = None
            if alliance_id_check and is_alliance_admin(alliance_id_check):
                allowed = True

        if not allowed:
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
        # to either saving the per-team config or the alliance-shared config
        # depending on the active config context. If an active alliance exists
        # and the user has alliance-admin rights, update the alliance config.
        from app.utils.config_manager import save_game_config
        from app.utils.alliance_data import get_active_alliance_id_for_team, is_alliance_admin

        # Respect potential per-request override to act on a different team
        token_team = getattr(request, 'mobile_team_number', None)
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

        team_number = requested_team if requested_team is not None else token_team

        # If there's an active alliance for this team, attempt to update alliance cfg
        alliance_id = None
        try:
            alliance_id = get_active_alliance_id_for_team(team_number)
        except Exception:
            alliance_id = None

        # Capture old event code for comparison
        old_event_code = None
        try:
            from app.utils.config_manager import load_game_config
            old_config = load_game_config(team_number=team_number)
            old_event_code = old_config.get('current_event_code') if old_config else None
        except Exception:
            pass
        new_event_code = data.get('current_event_code')

        saved = False
        if alliance_id:
            # When in alliance mode, only alliance admins may edit the alliance config
            try:
                if not is_alliance_admin(alliance_id):
                    return jsonify({'success': False, 'error': 'Forbidden: alliance admin required to edit alliance config', 'error_code': 'FORBIDDEN'}), 403
                from app.models import ScoutingAlliance
                alliance = ScoutingAlliance.query.get(alliance_id)
                if alliance is None:
                    return jsonify({'success': False, 'error': 'Alliance not found', 'error_code': 'NOT_FOUND'}), 404
                alliance.shared_game_config = json.dumps(data)
                db.session.add(alliance)
                db.session.commit()
                saved = True
                # Clear event cache so background sync picks up the new event immediately
                try:
                    from app.utils.sync_status import clear_event_cache
                    clear_event_cache(team_number)
                except Exception:
                    pass
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception(f"Failed to update alliance shared_game_config: {e}")
                saved = False
        else:
            # No active alliance -> fall back to per-team save behavior
            try:
                saved = save_game_config(data)
                if saved:
                    # Clear event cache so background sync picks up the new event immediately
                    try:
                        from app.utils.sync_status import clear_event_cache
                        clear_event_cache(team_number)
                    except Exception:
                        pass
            except Exception as e:
                current_app.logger.exception(f"Failed to save team game config: {e}")
                saved = False

        if saved:
            # Update running config in the Flask app (best-effort)
            try:
                current_app.config['GAME_CONFIG'] = data
            except Exception:
                pass
            
            # Broadcast event change via Socket.IO if event code changed
            if old_event_code != new_event_code and new_event_code:
                try:
                    from app import socketio
                    socketio.emit('event_changed', {
                        'old_event_code': old_event_code,
                        'new_event_code': new_event_code,
                        'event_name': new_event_code,
                        'scouting_team': team_number
                    }, namespace='/')
                except Exception:
                    pass
            
            return jsonify({'success': True}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration', 'error_code': 'SAVE_FAILED'}), 500

    except Exception as e:
        current_app.logger.error(f"Set game config error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Internal server error', 'error_code': 'INTERNAL_ERROR'}), 500


@mobile_api.route('/config/game/active', methods=['POST', 'PUT'])
@token_required
def set_game_config_active():
    """
    Alias that updates the "active" config. Calls the existing set_game_config (which implements active-mode behavior).
    """
    return set_game_config()


@mobile_api.route('/config/game/team', methods=['POST', 'PUT'])
@token_required
def set_game_config_team():
    """
    Save the per-team game configuration explicitly (team-only file). Requires admin role.
    """
    try:
        user = getattr(request, 'mobile_user', None)
        if not user:
            return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401
        if not (user.has_role('admin') or user.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Forbidden', 'error_code': 'FORBIDDEN'}), 403
        try:
            login_user(user, remember=False, force=True)
        except Exception:
            pass
        data = request.get_json()
        if not data or not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'Missing or invalid JSON body', 'error_code': 'MISSING_BODY'}), 400
        from app.utils.config_manager import save_game_config
        saved = save_game_config(data)
        if saved:
            try:
                current_app.config['GAME_CONFIG'] = data
            except Exception:
                pass
            # Clear event cache so background sync picks up the new event immediately
            try:
                from app.utils.sync_status import clear_event_cache
                team_number = user.scouting_team_number if hasattr(user, 'scouting_team_number') else None
                clear_event_cache(team_number)
            except Exception:
                pass
            return jsonify({'success': True}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration', 'error_code': 'SAVE_FAILED'}), 500
    except Exception as e:
        current_app.logger.error(f"Set team game config error: {str(e)}\n{traceback.format_exc()}")
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
        # Only superadmins may request a different team number explicitly
        if requested_team is not None and team_number is not None and int(requested_team) != int(request.mobile_team_number if request.mobile_team_number is not None else -999999):
            user = getattr(request, 'mobile_user', None)
            if not (user and getattr(user, 'has_role', None) and user.has_role('superadmin')):
                return jsonify({'success': False, 'error': 'Forbidden to access another team', 'error_code': 'FORBIDDEN'}), 403
        # Restrict explicit team queries to superadmins only for security
        if requested_team is not None and team_number is not None and int(requested_team) != int(request.mobile_team_number if request.mobile_team_number is not None else -999999):
            user = getattr(request, 'mobile_user', None)
            if not (user and getattr(user, 'has_role', None) and user.has_role('superadmin')):
                return jsonify({'success': False, 'error': 'Forbidden to access another team', 'error_code': 'FORBIDDEN'}), 403

        # Determine if alliance is active and prefer alliance pit config when present
        alliance_pit_cfg = None
        try:
            alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
        except Exception:
            alliance = None
        try:
            if alliance:
                if alliance.shared_pit_config:
                    alliance_pit_cfg = json.loads(alliance.shared_pit_config)
                elif getattr(alliance, 'pit_config_team', None):
                    from app.utils.config_manager import load_pit_config as _load_pit_config
                    alt_pcfg = _load_pit_config(team_number=alliance.pit_config_team)
                    if alt_pcfg:
                        alliance_pit_cfg = alt_pcfg
        except Exception:
            alliance_pit_cfg = None

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

        # If alliance config is present, use it; otherwise fall back
        if alliance_pit_cfg is not None:
            current_app.logger.debug(f"mobile_api.get_pit_config: using alliance pit config for team {team_number}")
            pit_config = alliance_pit_cfg
        elif pit_config is None:
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

        # Require admin or superadmin role to modify config OR allow alliance admins
        allowed = user.has_role('admin') or user.has_role('superadmin')
        if not allowed:
            # Determine token/request team to check if this user is an alliance admin
            from app.utils.alliance_data import get_active_alliance_id_for_team, is_alliance_admin
            token_team = getattr(request, 'mobile_team_number', None)
            requested_team = None
            try:
                hdr = request.headers.get('X-Mobile-Requested-Team')
                if hdr:
                    requested_team = int(hdr)
                else:
                    qp = request.args.get('team')
                    if qp is not None:
                        try:
                            requested_team = int(qp)
                        except Exception:
                            requested_team = None
            except Exception:
                requested_team = None

            team_number_to_check = requested_team if requested_team is not None else token_team
            try:
                alliance_id_check = get_active_alliance_id_for_team(team_number_to_check)
            except Exception:
                alliance_id_check = None
            if alliance_id_check and is_alliance_admin(alliance_id_check):
                allowed = True

        if not allowed:
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
        from app.utils.alliance_data import get_active_alliance_id_for_team, is_alliance_admin

        # Determine team_number respect token override
        token_team = getattr(request, 'mobile_team_number', None)
        requested_team = None
        try:
            hdr = request.headers.get('X-Mobile-Requested-Team')
            if hdr:
                requested_team = int(hdr)
            else:
                qp = request.args.get('team')
                if qp is not None:
                    try:
                        requested_team = int(qp)
                    except Exception:
                        requested_team = None
        except Exception:
            requested_team = None

        team_number = requested_team if requested_team is not None else token_team

        saved = False
        alliance_id = None
        try:
            alliance_id = get_active_alliance_id_for_team(team_number)
        except Exception:
            alliance_id = None

        if alliance_id:
            # Must be alliance admin to update alliance shared pit config
            try:
                if not is_alliance_admin(alliance_id):
                    return jsonify({'success': False, 'error': 'Forbidden: alliance admin required to edit alliance pit config', 'error_code': 'FORBIDDEN'}), 403
                from app.models import ScoutingAlliance
                alliance = ScoutingAlliance.query.get(alliance_id)
                if alliance is None:
                    return jsonify({'success': False, 'error': 'Alliance not found', 'error_code': 'NOT_FOUND'}), 404
                alliance.shared_pit_config = json.dumps(data)
                db.session.add(alliance)
                db.session.commit()
                saved = True
            except Exception:
                db.session.rollback()
                saved = False
        else:
            try:
                saved = save_pit_config(data)
            except Exception as e:
                current_app.logger.exception(f"Failed to save team pit config: {e}")
                saved = False
        if saved:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration', 'error_code': 'SAVE_FAILED'}), 500

    except Exception as e:
        current_app.logger.error(f"Set pit config error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Internal server error', 'error_code': 'INTERNAL_ERROR'}), 500


@mobile_api.route('/config/pit/active', methods=['GET'])
@token_required
def get_pit_config_active():
    """
    Return active pit config (alliance if active, else team)
    """
    return get_pit_config()


@mobile_api.route('/config/pit/team', methods=['GET'])
@token_required
def get_pit_config_team():
    """
    Return explicit per-team pit config file (team-only no alliance merge)
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
        from app.utils.config_manager import load_pit_config
        pit_config = None
        try:
            if team_number is not None:
                base_dir = os.getcwd()
                team_config_path = os.path.join(base_dir, 'instance', 'configs', str(team_number), 'pit_config.json')
                if os.path.exists(team_config_path):
                    with open(team_config_path, 'r', encoding='utf-8') as f:
                        try:
                            pit_config = json.load(f)
                        except Exception:
                            current_app.logger.warning(f"Invalid JSON in team pit_config for team {team_number}")
        except Exception:
            pit_config = None

        if pit_config is None:
            pit_config = load_pit_config(team_number=team_number)

        return jsonify({'success': True, 'config': pit_config}), 200
    except Exception as e:
        current_app.logger.error(f"Get team pit config error: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to retrieve team pit configuration', 'error_code': 'CONFIG_ERROR'}), 500


@mobile_api.route('/config/pit/active', methods=['POST', 'PUT'])
@token_required
def set_pit_config_active():
    return set_pit_config()


@mobile_api.route('/config/pit/team', methods=['POST', 'PUT'])
@token_required
def set_pit_config_team():
    """
    Save explicit per-team pit config file; requires admin/superadmin.
    """
    try:
        user = getattr(request, 'mobile_user', None)
        if not user:
            return jsonify({'success': False, 'error': 'Authentication required', 'error_code': 'AUTH_REQUIRED'}), 401
        if not (user.has_role('admin') or user.has_role('superadmin')):
            return jsonify({'success': False, 'error': 'Forbidden', 'error_code': 'FORBIDDEN'}), 403
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
        current_app.logger.error(f"Set team pit config error: {str(e)}\n{traceback.format_exc()}")
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
                # Try year-prefixed code first (database stores codes like '2026OKTU')
                from app.utils.config_manager import load_game_config
                _cfg = load_game_config(team_number=token_team_number)
                _season = _cfg.get('season', 2026) if isinstance(_cfg, dict) else 2026
                year_prefixed_code = event_identifier
                if not (len(event_identifier) >= 4 and event_identifier[:4].isdigit()):
                    year_prefixed_code = f"{_season}{event_identifier.upper()}"
                event_obj = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=token_team_number).first()
                # Fall back to raw code if year-prefixed not found
                if not event_obj and year_prefixed_code != event_identifier.upper():
                    event_obj = Event.query.filter_by(code=event_identifier.upper(), scouting_team_number=token_team_number).first()
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

        # Check for alliance mode
        alliance_id = get_active_alliance_id_for_team(token_team_number)
        
        # In alliance mode, get all available teams from alliance data
        alliance_teams_map = {}
        if alliance_id:
            alliance_teams, _ = get_all_teams_for_alliance(event_id=resolved_event_id)
            alliance_teams_map = {t.team_number: t for t in alliance_teams}

        for idx, tn in enumerate(team_numbers):
            try:
                tn_int = int(tn)
            except Exception:
                continue

            # In alliance mode, prefer teams from alliance data
            if alliance_id and tn_int in alliance_teams_map:
                team = alliance_teams_map[tn_int]
            else:
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
            # Check for alliance mode
            alliance_id = get_active_alliance_id_for_team(token_team_number)
            
            if alliance_id:
                # Alliance mode - query from shared tables by team_number (not team_id)
                # since different alliance members have different team_id for the same team_number
                q = AllianceSharedScoutingData.query.join(
                    Match, AllianceSharedScoutingData.match_id == Match.id
                ).join(
                    Team, AllianceSharedScoutingData.team_id == Team.id
                ).join(
                    Event, Match.event_id == Event.id
                ).filter(
                    Team.team_number == team.team_number,
                    AllianceSharedScoutingData.alliance_id == alliance_id,
                    AllianceSharedScoutingData.is_active == True
                )
                if resolved_event_id is not None:
                    # Filter by event code, not event_id in alliance mode
                    from sqlalchemy import func as sqla_func
                    resolved_event = Event.query.get(resolved_event_id)
                    if resolved_event and resolved_event.code:
                        q = q.filter(sqla_func.upper(Event.code) == sqla_func.upper(resolved_event.code))
            else:
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
            if str(data_view).lower() in ('averages', 'average', 'avg', 'mean', 'means'):
                # Represent averages across teams as a line (x: team_number)
                avg_labels = [str(t['team_number']) for t in teams_response]
                avg_values = [t['value'] for t in teams_response]
                graphs['line'] = {
                    'type': 'line',
                    'labels': avg_labels,
                    'datasets': [
                        {
                            'label': f'Average {metric_title}',
                            'data': avg_values,
                            'borderColor': '#36A2EB',
                            'backgroundColor': '#36A2EB'
                        }
                    ]
                }
            else:
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
            if str(data_view).lower() in ('averages', 'average', 'avg', 'mean', 'means'):
                # Histogram over team averages
                avg_vals = []
                for s in team_series_entries:
                    vals = s['values'] or []
                    avg_vals.append(sum(vals) / len(vals) if vals else 0)
                if avg_vals:
                    histogram_datasets.append({
                        'team_number': 'averages',
                        'team_name': 'Averages',
                        'color': '#FFCE56',
                        'values': avg_vals,
                        'count': len(avg_vals),
                        'mean': sum(avg_vals) / len(avg_vals) if avg_vals else 0
                    })
                    all_values.extend(avg_vals)
            else:
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
            if str(data_view).lower() in ('averages', 'average', 'avg', 'mean', 'means'):
                avg_vals = []
                for s in team_series_entries:
                    vals = s['values'] or []
                    avg_vals.append(sum(vals) / len(vals) if vals else 0)
                if avg_vals:
                    box_datasets.append({
                        'team_number': 'averages',
                        'team_name': 'Averages',
                        'color': '#FFCE56',
                        'values': avg_vals,
                        'stats': {
                            'count': len(avg_vals),
                            'min': min(avg_vals),
                            'max': max(avg_vals),
                            'median': statistics.median(avg_vals)
                        }
                    })
            else:
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
        # Normalized boolean for average-mode plotting
        is_averages_mode = str(mode).lower() in ('averages', 'average', 'avg', 'mean', 'means')

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
                # Try year-prefixed code first (database stores codes like '2026OKTU')
                from app.utils.config_manager import load_game_config
                _cfg = load_game_config(team_number=token_team_number)
                _season = _cfg.get('season', 2026) if isinstance(_cfg, dict) else 2026
                year_prefixed_code = event_identifier
                if not (len(event_identifier) >= 4 and event_identifier[:4].isdigit()):
                    year_prefixed_code = f"{_season}{event_identifier.upper()}"
                event_obj = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=token_team_number).first()
                # Fall back to raw code if year-prefixed not found
                if not event_obj and year_prefixed_code != event_identifier.upper():
                    event_obj = Event.query.filter_by(code=event_identifier.upper(), scouting_team_number=token_team_number).first()
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

        # Check for alliance mode
        alliance_id = get_active_alliance_id_for_team(token_team_number)

        # Resolve teams (in alliance mode, use alliance teams; otherwise respect team isolation)
        teams = []
        if alliance_id:
            # Get all teams from alliance data
            alliance_teams, _ = get_all_teams_for_alliance(event_id=resolved_event_id)
            alliance_teams_map = {t.team_number: t for t in alliance_teams}
            for tn in team_numbers:
                if tn in alliance_teams_map:
                    teams.append(alliance_teams_map[tn])
                else:
                    # Fallback if team not in alliance data
                    t = Team.query.filter_by(team_number=tn).first()
                    if t:
                        teams.append(t)
        else:
            for tn in team_numbers:
                t = Team.query.filter_by(team_number=tn, scouting_team_number=token_team_number).first()
                if not t:
                    t = Team.query.filter_by(team_number=tn).first()
                if t:
                    teams.append(t)

        if not teams:
            return jsonify({'success': False, 'error': 'No teams found', 'error_code': 'NO_TEAMS'}), 404

        # Build minimal team_data dict compatible with graphs.py helpers
        team_numbers_list = [t.team_number for t in teams]
        if alliance_id:
            # Alliance mode - query from shared tables by team_number (not team_id)
            scouting_query = AllianceSharedScoutingData.query.join(
                Match, AllianceSharedScoutingData.match_id == Match.id
            ).join(
                Team, AllianceSharedScoutingData.team_id == Team.id
            ).join(
                Event, Match.event_id == Event.id
            ).filter(
                Team.team_number.in_(team_numbers_list),
                AllianceSharedScoutingData.alliance_id == alliance_id,
                AllianceSharedScoutingData.is_active == True
            )
            if resolved_event_id is not None:
                # Filter by event code in alliance mode
                from sqlalchemy import func as sqla_func
                resolved_event = Event.query.get(resolved_event_id)
                if resolved_event and resolved_event.code:
                    scouting_query = scouting_query.filter(sqla_func.upper(Event.code) == sqla_func.upper(resolved_event.code))
        else:
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
                if is_averages_mode:
                    # Averages mode: compare team averages across teams as a line
                    labels = [str(t.team_number) for t in teams]
                    values = []
                    for t in teams:
                        nums = [m['metric_value'] for m in team_data.get(t.team_number, {}).get('matches', [])]
                        avg = sum(nums) / len(nums) if nums else 0
                        values.append(avg)
                    if graph_type == 'line':
                        fig = go.Figure(data=[go.Scatter(x=labels, y=values, mode='lines+markers')])
                    else:
                        fig = go.Figure(data=[go.Scatter(x=labels, y=values, mode='markers')])
                else:
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
                if is_averages_mode:
                    # Histogram of averages across teams
                    avg_vals = []
                    for t in teams:
                        nums = [m['metric_value'] for m in team_data.get(t.team_number, {}).get('matches', [])]
                        avg_vals.append(sum(nums) / len(nums) if nums else 0)
                    if avg_vals:
                        fig.add_trace(go.Histogram(x=avg_vals, name='Averages', opacity=0.75))
                else:
                    for t in teams:
                        matches = team_data.get(t.team_number, {}).get('matches', [])
                        values = [m['metric_value'] for m in matches if m['metric_value'] is not None]
                        if not values:
                            continue
                        fig.add_trace(go.Histogram(x=values, name=str(t.team_number), opacity=0.75))
                fig.update_layout(barmode='overlay', xaxis_title=metric_title, yaxis_title='Frequency')
            elif graph_type == 'box':
                fig = go.Figure()
                if is_averages_mode:
                    # Box plot of averages across teams
                    avg_vals = []
                    for t in teams:
                        nums = [m['metric_value'] for m in team_data.get(t.team_number, {}).get('matches', [])]
                        avg_vals.append(sum(nums) / len(nums) if nums else 0)
                    if avg_vals:
                        fig.add_trace(go.Box(y=avg_vals, name='Averages', boxmean=True))
                else:
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
            # Try year-prefixed code first (database stores codes like '2026OKTU')
            year_prefixed_code = event_code
            if not (len(str(event_code)) >= 4 and str(event_code)[:4].isdigit()):
                season = game_config.get('season', 2026) if isinstance(game_config, dict) else 2026
                year_prefixed_code = f"{season}{event_code}"
            event = Event.query.filter_by(code=year_prefixed_code, scouting_team_number=token_team_number).first()
            # Fall back to raw code if year-prefixed not found
            if not event and year_prefixed_code != event_code:
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

            # Check for alliance mode
            alliance_id = get_active_alliance_id_for_team(token_team_number)
            
            # In alliance mode, get teams from alliance data
            alliance_teams_map = {}
            if alliance_id:
                alliance_teams, _ = get_all_teams_for_alliance(event_id=event_id)
                alliance_teams_map = {t.team_number: t for t in alliance_teams}

            teams = []
            for tn in team_numbers:
                try:
                    tn_int = int(tn)
                except Exception:
                    continue
                
                # In alliance mode, prefer teams from alliance data
                if alliance_id and tn_int in alliance_teams_map:
                    t = alliance_teams_map[tn_int]
                else:
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
                    # Check for alliance mode
                    alliance_id = get_active_alliance_id_for_team(token_team_number)
                    
                    if alliance_id:
                        # Alliance mode - query from shared tables by team_number (not team_id)
                        from sqlalchemy import func as sqla_func
                        resolved_event = Event.query.get(event_id)
                        scouting_rows = AllianceSharedScoutingData.query.join(
                            Match, AllianceSharedScoutingData.match_id == Match.id
                        ).join(
                            Team, AllianceSharedScoutingData.team_id == Team.id
                        ).join(
                            Event, Match.event_id == Event.id
                        ).filter(
                            Team.team_number == t.team_number,
                            AllianceSharedScoutingData.alliance_id == alliance_id,
                            AllianceSharedScoutingData.is_active == True,
                            sqla_func.upper(Event.code) == sqla_func.upper(resolved_event.code) if resolved_event and resolved_event.code else Match.event_id == event_id
                        ).order_by(Match.match_number).all()
                    else:
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


# ============================================================================
# MOBILE TRIGGERED SYNC ENDPOINT
# ============================================================================
@mobile_api.route('/sync/trigger', methods=['POST'])
@token_required
def mobile_trigger_sync():
    """
    Trigger a combined teams + matches sync (same behavior as admin `/api/sync-event`).

    Security: Only users with `admin` or `analytics` roles may trigger this via mobile token.

    Response JSON mirrors the admin endpoint:
    {
      "success": true|false,
      "results": {
         "teams_sync": {"success": bool, "message": str, "flashes": [ {"category": str, "message": str} ] },
         "matches_sync": { ... },
         "alliance_sync": {"triggered": bool, ... }
      }
    }
    """
    # Require admin or analytics role on the mobile user
    user = getattr(request, 'mobile_user', None)
    if not user or not (user.has_role('admin') or user.has_role('analytics')):
        return jsonify({'success': False, 'error': 'Insufficient permissions', 'error_code': 'INSUFFICIENT_PERMISSIONS'}), 403

    results = {
        'teams_sync': {'success': False, 'message': '', 'flashes': []},
        'matches_sync': {'success': False, 'message': '', 'flashes': []},
        'alliance_sync': {'success': False, 'message': '', 'triggered': False}
    }

    try:
        # If alliance mode active, run alliance sync for the active alliance (safe to call)
        from app.utils.alliance_data import get_active_alliance_id
        alliance_id = get_active_alliance_id()
        if alliance_id:
            try:
                from app.routes.scouting_alliances import perform_alliance_api_sync_for_alliance
                sync_result = perform_alliance_api_sync_for_alliance(alliance_id)
                results['alliance_sync']['triggered'] = True
                results['alliance_sync']['success'] = sync_result.get('success', False)
                results['alliance_sync']['message'] = sync_result.get('message', 'Alliance sync attempted')
                results['alliance_sync']['teams_added'] = sync_result.get('teams_added', 0)
                results['alliance_sync']['teams_updated'] = sync_result.get('teams_updated', 0)
                results['alliance_sync']['matches_added'] = sync_result.get('matches_added', 0)
                results['alliance_sync']['matches_updated'] = sync_result.get('matches_updated', 0)
            except Exception as e:
                current_app.logger.exception('Alliance sync failed')
                results['alliance_sync']['triggered'] = True
                results['alliance_sync']['success'] = False
                results['alliance_sync']['message'] = str(e)

        # Teams sync
        from app.routes import teams as teams_bp
        try:
            try:
                _ = get_flashed_messages(with_categories=True)
            except Exception:
                pass

            teams_resp = teams_bp.sync_from_config()
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []

            results['teams_sync']['success'] = True
            results['teams_sync']['message'] = 'Teams sync attempted.'
            results['teams_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]
        except Exception as e:
            current_app.logger.exception('Teams sync failed')
            results['teams_sync']['success'] = False
            results['teams_sync']['message'] = str(e)
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []
            results['teams_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]

        # Matches sync
        from app.routes import matches as matches_bp
        try:
            try:
                _ = get_flashed_messages(with_categories=True)
            except Exception:
                pass

            matches_resp = matches_bp.sync_from_config()
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []

            results['matches_sync']['success'] = True
            results['matches_sync']['message'] = 'Matches sync attempted.'
            results['matches_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]
        except Exception as e:
            current_app.logger.exception('Matches sync failed')
            results['matches_sync']['success'] = False
            results['matches_sync']['message'] = str(e)
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []
            results['matches_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]

        overall_success = results['teams_sync']['success'] or results['matches_sync']['success'] or results['alliance_sync'].get('success', False)
        return jsonify({'success': overall_success, 'results': results})

    except Exception as e:
        current_app.logger.exception('Mobile-triggered sync failed')
        return jsonify({'success': False, 'error': str(e)}), 500


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
                from app import socketio, normalize_username
                try:
                    socketio.emit('dm_message', message, room=normalize_username(user.username))
                except Exception:
                    socketio.emit('dm_message', message, room=user.username)
                try:
                    socketio.emit('dm_message', message, room=normalize_username(other.username))
                except Exception:
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
