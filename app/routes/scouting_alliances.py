"""
Scouting Alliance Routes
Handles the collaboration features between scouting teams
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from app import db, socketio
from app.models import (
    Team, Event, Match, ScoutingData, PitScoutingData, User,
    ScoutingAlliance, ScoutingAllianceMember, ScoutingAllianceInvitation,
    ScoutingAllianceEvent, ScoutingAllianceSync, ScoutingAllianceChat,
    TeamAllianceStatus, AllianceSharedScoutingData, AllianceSharedPitData,
    AllianceDeletedData
)
from app.routes.auth import admin_required
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import load_game_config, load_pit_config
from app.utils.team_isolation import get_current_scouting_team_number
from datetime import datetime, timezone, timedelta
import json
import uuid

bp = Blueprint('scouting_alliances', __name__, url_prefix='/alliances/scouting')

def get_theme_context():
    """Get theme context with alliance status"""
    from app.utils.config_manager import is_alliance_mode_active, get_active_alliance_info
    
    theme_manager = ThemeManager()
    context = {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }
    
    # Add alliance status to context
    context.update({
        'is_alliance_mode_active': is_alliance_mode_active(),
        'active_alliance_info': get_active_alliance_info()
    })
    
    return context

# ======== DASHBOARD ROUTES ========

@bp.route('/')
@login_required
def dashboard():
    """Main scouting alliance dashboard (available to all users)"""
    from app.models import TeamAllianceStatus
    
    current_team = get_current_scouting_team_number()
    
    # Get alliances this team is part of
    my_alliances = db.session.query(ScoutingAlliance).join(ScoutingAllianceMember).filter(
        ScoutingAllianceMember.team_number == current_team,
        ScoutingAllianceMember.status == 'accepted'
    ).all()
    
    # Get current active alliance info
    active_alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team)
    
    # Get pending invitations
    pending_invitations = ScoutingAllianceInvitation.query.filter_by(
        to_team_number=current_team,
        status='pending'
    ).all()
    
    # Get sent invitations
    sent_invitations = ScoutingAllianceInvitation.query.filter_by(
        from_team_number=current_team,
        status='pending'
    ).all()
    
    return render_template('scouting_alliances/dashboard.html',
                         my_alliances=my_alliances,
                         active_alliance=active_alliance,
                         pending_invitations=pending_invitations,
                         sent_invitations=sent_invitations,
                         current_team=current_team,
                         **get_theme_context())

@bp.route('/search')
@login_required
@admin_required
def search_teams():
    """Search for scouting teams to invite to alliances"""
    query = request.args.get('q', '').strip()
    current_team = get_current_scouting_team_number()
    
    # Search for teams (excluding current team)
    teams = []
    if query:
        if query.isdigit():
            # Search by team number
            teams = User.query.filter(
                User.scouting_team_number == int(query),
                User.scouting_team_number != current_team
            ).distinct(User.scouting_team_number).all()
        else:
            # Search by username (team names are not stored separately)
            teams = User.query.filter(
                User.username.contains(query),
                User.scouting_team_number != current_team,
                User.scouting_team_number.isnot(None)
            ).distinct(User.scouting_team_number).all()
    
    # Convert to team info format
    team_results = []
    seen_teams = set()
    for user in teams:
        if user.scouting_team_number not in seen_teams:
            team_results.append({
                'team_number': user.scouting_team_number,
                'team_name': f"Team {user.scouting_team_number}",
                'has_users': True
            })
            seen_teams.add(user.scouting_team_number)
    
    return jsonify({'teams': team_results})

# ======== ALLIANCE MANAGEMENT ========

@bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_alliance():
    """Create a new scouting alliance"""
    if request.method == 'POST':
        data = request.get_json()
        current_team = get_current_scouting_team_number()
        
        # Create alliance
        alliance = ScoutingAlliance(
            alliance_name=data['name'],
            description=data.get('description', ''),
            config_status='pending'
        )
        db.session.add(alliance)
        db.session.flush()  # Get the ID
        
        # Add creator as admin member
        member = ScoutingAllianceMember(
            alliance_id=alliance.id,
            team_number=current_team,
            team_name=f"Team {current_team}",
            role='admin',
            status='accepted'
        )
        db.session.add(member)
        db.session.commit()
        
        return jsonify({'success': True, 'alliance_id': alliance.id})
    
    return render_template('scouting_alliances/create.html', **get_theme_context())

@bp.route('/<int:alliance_id>')
@login_required
def view_alliance(alliance_id):
    """View alliance details and manage settings (available to all alliance members)"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member of this alliance
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        flash('You are not a member of this alliance.', 'error')
        return redirect(url_for('scouting_alliances.dashboard'))
    
    # Get alliance data
    members = alliance.get_active_members()
    events = alliance.events
    recent_chats = ScoutingAllianceChat.query.filter_by(
        alliance_id=alliance_id
    ).order_by(ScoutingAllianceChat.created_at.desc()).limit(10).all()
    
    # Get sync statistics
    sync_stats = get_alliance_sync_stats(alliance_id, current_team)
    
    return render_template('scouting_alliances/view.html',
                         alliance=alliance,
                         member=member,
                         members=members,
                         events=events,
                         recent_chats=recent_chats,
                         sync_stats=sync_stats,
                         current_team=current_team,
                         **get_theme_context())

# ======== CONFIGURATION MANAGEMENT ========
# Note: Old config_selection route removed - use new enhanced editors instead

@bp.route('/alliance/<int:alliance_id>/toggle', methods=['POST'])
@login_required
def toggle_alliance_mode(alliance_id):
    """Toggle alliance mode on/off for the current team (any alliance member can control their own team)"""
    from app.models import TeamAllianceStatus
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    current_team = get_current_scouting_team_number()
    
    # Check if user's team is part of this alliance
    member = next((m for m in alliance.members if m.team_number == current_team and m.status == 'accepted'), None)
    if not member:
        return jsonify({'success': False, 'message': 'You are not an active member of this alliance'}), 403
    
    data = request.get_json()
    activate = data.get('activate', False)
    remove_shared_data = data.get('remove_shared_data', False)  # Option to remove data when deactivating
    
    try:
        if activate:
            # Check if alliance configuration is complete
            if not alliance.is_config_complete():
                return jsonify({
                    'success': False, 
                    'message': 'Alliance configuration must be complete before activation'
                }), 400
            
            # Check if team is currently active in a different alliance
            current_status = TeamAllianceStatus.query.filter_by(team_number=current_team).first()
            if current_status and current_status.is_alliance_mode_active and current_status.active_alliance_id != alliance_id:
                current_alliance = current_status.active_alliance
                message = f'Switched from "{current_alliance.alliance_name}" to "{alliance.alliance_name}"'
            else:
                message = f'Alliance mode activated for {alliance.alliance_name}'
            
            # Activate alliance mode (this will automatically deactivate any other active alliance)
            TeamAllianceStatus.activate_alliance_for_team(current_team, alliance_id)
            
            # Re-enable data sharing for this member
            member.is_data_sharing_active = True
            member.data_sharing_deactivated_at = None
            
            # Update alliance shared configs from the configured teams
            if alliance.game_config_team:
                game_config = load_game_config(team_number=alliance.game_config_team)
                alliance.shared_game_config = json.dumps(game_config)
            
            if alliance.pit_config_team:
                pit_config = load_pit_config(team_number=alliance.pit_config_team)
                alliance.shared_pit_config = json.dumps(pit_config)
            
            # Update config status to 'configured'
            alliance.update_config_status()
            
            db.session.commit()
            
        else:
            # Deactivate alliance mode - pass remove_shared_data option
            TeamAllianceStatus.deactivate_alliance_for_team(current_team, remove_shared_data=remove_shared_data)
            if remove_shared_data:
                message = 'Alliance mode deactivated - your shared data has been removed from the alliance'
            else:
                message = 'Alliance mode deactivated - your existing shared data remains (new syncs will not get your data)'
        
        # Get the effective configurations after toggle
        from app.utils.config_manager import get_effective_game_config, get_effective_pit_config, is_alliance_mode_active, get_active_alliance_info
        
        effective_game_config = get_effective_game_config()
        effective_pit_config = get_effective_pit_config()
        alliance_status = is_alliance_mode_active()
        alliance_info = get_active_alliance_info()
        
        # Emit Socket.IO event for real-time updates to all users from this team
        config_update_data = {
            'alliance_id': alliance_id,
            'team_number': current_team,
            'is_active': activate,
            'message': message,
            'effective_game_config': effective_game_config,
            'effective_pit_config': effective_pit_config,
            'alliance_status': alliance_status,
            'alliance_info': alliance_info
        }
        
        # Emit to alliance room and team-specific room
        socketio.emit('alliance_mode_toggled', config_update_data, room=f'alliance_{alliance_id}')
        socketio.emit('config_updated', config_update_data, room=f'team_{current_team}')
        socketio.emit('alliance_status_changed', {
            'team_number': current_team,
            'alliance_status': alliance_status,
            'alliance_info': alliance_info
        })  # Broadcast to all users for nav bar updates
        
        # ======== GLOBAL CONFIG CHANGE BROADCAST ========
        # Broadcast global config change to ALL connected users (for any page that uses config)
        socketio.emit('global_config_changed', {
            'type': 'alliance_toggle',
            'team_number': current_team,
            'alliance_id': alliance_id,
            'is_active': activate,
            'effective_game_config': effective_game_config,
            'effective_pit_config': effective_pit_config,
            'alliance_status': alliance_status,
            'alliance_info': alliance_info,
            'timestamp': datetime.now().isoformat(),
            'message': message
        })  # Broadcast to ALL users across all pages
        
        return jsonify({'success': True, 'message': message, 'is_active': activate})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error toggling alliance mode: {str(e)}'}), 500

@bp.route('/alliance/status')
@login_required
def get_alliance_status():
    """Get the current alliance status for the user's team"""
    from app.models import TeamAllianceStatus
    from app.utils.config_manager import is_alliance_mode_active, get_active_alliance_info
    
    current_team = get_current_scouting_team_number()
    
    status = {
        'is_alliance_mode_active': is_alliance_mode_active(),
        'active_alliance': get_active_alliance_info(),
        'team_number': current_team
    }
    
    return jsonify(status)

# ======== REAL-TIME CONFIG SYNC ========

@bp.route('/config/current')
@login_required
def get_current_config():
    """Get the currently effective game and pit configurations for the user's team"""
    from app.utils.config_manager import get_effective_game_config, get_effective_pit_config, is_alliance_mode_active, get_active_alliance_info
    
    current_team = get_current_scouting_team_number()
    
    config_data = {
        'game_config': get_effective_game_config(),
        'pit_config': get_effective_pit_config(),
        'alliance_status': {
            'is_active': is_alliance_mode_active(),
            'alliance_info': get_active_alliance_info(),
            'team_number': current_team
        },
        'timestamp': datetime.now().isoformat()
    }
    
    return jsonify(config_data)

@bp.route('/config/reload', methods=['POST'])
@login_required
def reload_global_config():
    """Force reload configuration and broadcast to all users (admin only for security)"""
    # For security, only allow admins to force global config reloads
    if not current_user.has_role('admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        # Reload the config manager
        from app import config_manager
        config_manager.load_config()
        
        # Get fresh config data
        from app.utils.config_manager import get_effective_game_config, get_effective_pit_config, is_alliance_mode_active, get_active_alliance_info
        
        current_team = get_current_scouting_team_number()
        
        fresh_config = {
            'game_config': get_effective_game_config(),
            'pit_config': get_effective_pit_config(),
            'alliance_status': {
                'is_active': is_alliance_mode_active(),
                'alliance_info': get_active_alliance_info(),
                'team_number': current_team
            },
            'timestamp': datetime.now().isoformat()
        }
        
        # Broadcast to ALL users
        socketio.emit('global_config_changed', {
            'type': 'admin_reload',
            'team_number': current_team,
            'effective_game_config': fresh_config['game_config'],
            'effective_pit_config': fresh_config['pit_config'],
            'alliance_status': fresh_config['alliance_status']['is_active'],
            'alliance_info': fresh_config['alliance_status']['alliance_info'],
            'timestamp': fresh_config['timestamp'],
            'message': f'Configuration reloaded by admin ({current_user.username})'
        })
        
        return jsonify({'success': True, 'message': 'Configuration reloaded and broadcast to all users'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error reloading config: {str(e)}'}), 500

@bp.route('/config/broadcast-change', methods=['POST'])
@login_required
def broadcast_config_change():
    """Broadcast a config change notification to all users (when config files are manually edited)"""
    # For security, only allow admins to broadcast config changes
    if not current_user.has_role('admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        data = request.get_json()
        change_message = data.get('message', 'Configuration has been updated')
        change_type = data.get('type', 'manual_edit')
        
        # Get fresh config data
        from app.utils.config_manager import get_effective_game_config, get_effective_pit_config, is_alliance_mode_active, get_active_alliance_info
        
        current_team = get_current_scouting_team_number()
        
        fresh_config = {
            'game_config': get_effective_game_config(),
            'pit_config': get_effective_pit_config(),
            'alliance_status': {
                'is_active': is_alliance_mode_active(),
                'alliance_info': get_active_alliance_info(),
                'team_number': current_team
            },
            'timestamp': datetime.now().isoformat()
        }
        
        # Broadcast to ALL users
        socketio.emit('global_config_changed', {
            'type': change_type,
            'team_number': current_team,
            'effective_game_config': fresh_config['game_config'],
            'effective_pit_config': fresh_config['pit_config'],
            'alliance_status': fresh_config['alliance_status']['is_active'],
            'alliance_info': fresh_config['alliance_status']['alliance_info'],
            'timestamp': fresh_config['timestamp'],
            'message': change_message
        })
        
        return jsonify({'success': True, 'message': 'Configuration change broadcast to all users'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error broadcasting config change: {str(e)}'}), 500

# ======== EVENT MANAGEMENT ========

@bp.route('/<int:alliance_id>/events/add', methods=['POST'])
@login_required
def add_event(alliance_id):
    """Add event to alliance"""
    current_team = get_current_scouting_team_number()
    
    # Verify user is admin of the alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to add events.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    event_code = request.form.get('event_code', '').strip()
    event_name = request.form.get('event_name', '').strip()
    
    if not event_code or not event_name:
        flash('Event code and name are required.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    try:
        # Check if event already exists for this alliance
        existing = ScoutingAllianceEvent.query.filter_by(
            alliance_id=alliance_id,
            event_code=event_code
        ).first()
        
        if existing:
            flash(f'Event {event_code} is already added to this alliance.', 'warning')
            return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
        
        # Create new alliance event
        alliance_event = ScoutingAllianceEvent(
            alliance_id=alliance_id,
            event_code=event_code,
            event_name=event_name,
            added_by=current_team
        )
        
        db.session.add(alliance_event)
        db.session.commit()
        
        flash(f'Event {event_code} added to alliance successfully!', 'success')
        
    except Exception as e:
        current_app.logger.error(f"Error adding event to alliance: {str(e)}")
        db.session.rollback()
        flash('Error adding event to alliance.', 'error')
    
    return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))

# ======== INVITATION SYSTEM ========

@bp.route('/<int:alliance_id>/invite', methods=['POST'])
@login_required
def send_invitation(alliance_id):
    """Send alliance invitation to another team"""
    current_team = get_current_scouting_team_number()
    
    # Check if sender is admin of the alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to send invitations.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    team_number = request.form.get('team_number')
    if not team_number:
        flash('Team number is required.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    try:
        team_number = int(team_number)
    except ValueError:
        flash('Invalid team number.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    # Check if invitation already exists
    existing = ScoutingAllianceInvitation.query.filter_by(
        alliance_id=alliance_id,
        to_team_number=team_number,
        status='pending'
    ).first()
    
    if existing:
        flash('Invitation already sent to this team.', 'warning')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    # Create invitation
    invitation = ScoutingAllianceInvitation(
        alliance_id=alliance_id,
        from_team_number=current_team,
        to_team_number=team_number,
        message=''
    )
    db.session.add(invitation)
    db.session.commit()
    
    # Emit real-time notification
    socketio.emit('alliance_invitation', {
        'to_team': team_number,
        'from_team': current_team,
        'alliance_name': member.alliance.alliance_name,
        'message': ''
    }, room=f'team_{team_number}')
    
    flash(f'Invitation sent to Team {team_number} successfully!', 'success')
    return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))

@bp.route('/invitation/<int:invitation_id>/respond', methods=['POST'])
@login_required
@admin_required
def respond_invitation(invitation_id):
    """Respond to alliance invitation"""
    from app.models import TeamAllianceStatus
    
    data = request.get_json()
    current_team = get_current_scouting_team_number()
    
    invitation = ScoutingAllianceInvitation.query.get_or_404(invitation_id)
    
    # Check if invitation is for current team
    if invitation.to_team_number != current_team:
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    response = data['response']  # 'accept' or 'decline'
    
    if response == 'accept':
        # Check if team is currently active in another alliance
        if not TeamAllianceStatus.can_team_join_alliance(current_team, invitation.alliance_id):
            active_alliance_name = TeamAllianceStatus.get_active_alliance_name(current_team)
            return jsonify({
                'success': False, 
                'error': f'Cannot join alliance - your team is currently active in "{active_alliance_name}". Please deactivate your current alliance first.'
            })
        
        # Create alliance member
        member = ScoutingAllianceMember(
            alliance_id=invitation.alliance_id,
            team_number=current_team,
            team_name=f"Team {current_team}",
            role='member',
            status='accepted',
            invited_by=invitation.from_team_number
        )
        db.session.add(member)
        
        # Update invitation status
        invitation.status = 'accepted'
        invitation.responded_at = datetime.now(timezone.utc)
        
        # Send notification to alliance members
        socketio.emit('alliance_member_joined', {
            'alliance_id': invitation.alliance_id,
            'team_number': current_team,
            'team_name': f"Team {current_team}"
        }, room=f'alliance_{invitation.alliance_id}')
        
    else:
        invitation.status = 'declined'
        invitation.responded_at = datetime.now(timezone.utc)
    
    db.session.commit()
    
    return jsonify({'success': True})

# ======== EVENT MANAGEMENT ========

@bp.route('/<int:alliance_id>/events', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_events(alliance_id):
    """Manage events for alliance collaboration"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    if request.method == 'POST':
        data = request.get_json()
        event_code = data['event_code']
        event_name = data.get('event_name', event_code)
        
        # Check if event already exists for this alliance
        existing = ScoutingAllianceEvent.query.filter_by(
            alliance_id=alliance_id,
            event_code=event_code
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Event already added'})
        
        # Add event
        alliance_event = ScoutingAllianceEvent(
            alliance_id=alliance_id,
            event_code=event_code,
            event_name=event_name
        )
        db.session.add(alliance_event)
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_event_added', {
            'alliance_id': alliance_id,
            'event_code': event_code,
            'event_name': event_name
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({'success': True})
    
    # GET request - return current events
    events = ScoutingAllianceEvent.query.filter_by(
        alliance_id=alliance_id,
        is_active=True
    ).all()
    
    return jsonify({'events': [{'code': e.event_code, 'name': e.event_name} for e in events]})

# ======== DATA SYNCHRONIZATION ========

@bp.route('/<int:alliance_id>/sync/data', methods=['POST'])
@login_required
@admin_required
def sync_scouting_data(alliance_id):
    """Synchronize scouting data with alliance members (bidirectional)"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    alliance_events = alliance.get_shared_events()
    
    # Get all active alliance members WHO HAVE DATA SHARING ENABLED
    all_members = alliance.get_active_members()
    # Filter to only include members with data sharing active
    data_sharing_members = [m for m in all_members if getattr(m, 'is_data_sharing_active', True)]
    member_teams = [m.team_number for m in data_sharing_members]
    
    # Build list of teams with data sharing disabled (for user feedback)
    disabled_teams = [m.team_number for m in all_members if not getattr(m, 'is_data_sharing_active', True)]
    
    total_imported = 0
    total_shared = 0
    total_shared_copies = 0
    
    if alliance_events:
        # Get events
        events = Event.query.filter(Event.code.in_(alliance_events)).all()
        event_ids = [e.id for e in events]
        
        # STEP 1: Collect data from ALL alliance members WHO HAVE DATA SHARING ENABLED and create shared copies
        all_scouting_data = {}
        all_pit_data = {}
        
        for team_num in member_teams:
            # Get scouting data for each team
            # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
            # to prevent duplicate sharing
            scouting_entries = ScoutingData.query.join(Match).filter(
                Match.event_id.in_(event_ids),
                ScoutingData.scouting_team_number == team_num,
                ~ScoutingData.scout_name.like('[Alliance-%')
            ).all()
            
            for entry in scouting_entries:
                # Create unique key for this scouting entry
                key = (entry.team.team_number, entry.match.match_number, 
                      entry.match.match_type, entry.match.event.code, entry.alliance)
                
                if key not in all_scouting_data:
                    all_scouting_data[key] = {
                        'team_number': entry.team.team_number,
                        'match_number': entry.match.match_number,
                        'match_type': entry.match.match_type,
                        'event_code': entry.match.event.code,
                        'alliance': entry.alliance,
                        'scout_name': entry.scout_name,
                        'data': entry.data,
                        'timestamp': entry.timestamp.isoformat(),
                        'source_team': team_num,
                        'match_id': entry.match_id,
                        'team_id': entry.team_id,
                        'original_id': entry.id,
                        'entry': entry  # Keep reference to original entry
                    }
                
                # STEP 1B: Create shared copy in AllianceSharedScoutingData if not exists
                # BUT SKIP if this data was previously deleted by alliance admin
                if AllianceDeletedData.is_deleted(
                    alliance_id=alliance_id,
                    data_type='scouting',
                    match_id=entry.match_id,
                    team_id=entry.team_id,
                    alliance_color=entry.alliance,
                    source_team=team_num
                ):
                    continue  # Skip - this was deleted and shouldn't be re-synced
                
                existing_shared = AllianceSharedScoutingData.query.filter_by(
                    alliance_id=alliance_id,
                    original_scouting_data_id=entry.id
                ).first()
                
                if not existing_shared:
                    # Also check by match/team/alliance combo to avoid duplicates
                    existing_shared = AllianceSharedScoutingData.query.filter_by(
                        alliance_id=alliance_id,
                        match_id=entry.match_id,
                        team_id=entry.team_id,
                        alliance=entry.alliance,
                        source_scouting_team_number=team_num
                    ).first()
                
                if not existing_shared:
                    shared_copy = AllianceSharedScoutingData.create_from_scouting_data(
                        entry, alliance_id, team_num
                    )
                    db.session.add(shared_copy)
                    total_shared_copies += 1
            
            # Get pit data for each team
            # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
            pit_entries = PitScoutingData.query.filter(
                PitScoutingData.scouting_team_number == team_num,
                ~PitScoutingData.scout_name.like('[Alliance-%')
            ).all()
            
            for entry in pit_entries:
                key = entry.team.team_number
                if key not in all_pit_data:
                    all_pit_data[key] = {
                        'team_number': entry.team.team_number,
                        'scout_name': entry.scout_name,
                        'data': entry.data,
                        'timestamp': entry.timestamp.isoformat(),
                        'source_team': team_num,
                        'original_id': entry.id,
                        'entry': entry  # Keep reference to original entry
                    }
                
                # STEP 1B: Create shared copy in AllianceSharedPitData if not exists
                # BUT SKIP if this data was previously deleted by alliance admin
                if AllianceDeletedData.is_deleted(
                    alliance_id=alliance_id,
                    data_type='pit',
                    match_id=None,
                    team_id=entry.team_id,
                    alliance_color=None,
                    source_team=team_num
                ):
                    continue  # Skip - this was deleted and shouldn't be re-synced
                
                existing_shared = AllianceSharedPitData.query.filter_by(
                    alliance_id=alliance_id,
                    original_pit_data_id=entry.id
                ).first()
                
                if not existing_shared:
                    # Also check by team to avoid duplicates
                    existing_shared = AllianceSharedPitData.query.filter_by(
                        alliance_id=alliance_id,
                        team_id=entry.team_id,
                        source_scouting_team_number=team_num
                    ).first()
                
                if not existing_shared:
                    shared_copy = AllianceSharedPitData.create_from_pit_data(
                        entry, alliance_id, team_num
                    )
                    db.session.add(shared_copy)
                    total_shared_copies += 1
        
        # NOTE: We no longer create local copies in each team's ScoutingData/PitScoutingData.
        # Alliance data lives ONLY in AllianceSharedScoutingData/AllianceSharedPitData tables.
        # This prevents duplicates and makes delete work properly.
        
        # STEP 2: Share current team's data with other members via SocketIO (if they're online)
        # This notifies them that new data is available in the shared tables
        current_team_scouting = [data for key, data in all_scouting_data.items() if data['source_team'] == current_team]
        current_team_pit = [data for key, data in all_pit_data.items() if data['source_team'] == current_team]
        total_shared = len(current_team_scouting) + len(current_team_pit)
        
        # Send to other teams via SocketIO
        sync_count = 0
        for member_obj in all_members:
            if member_obj.team_number != current_team:
                # Create sync record
                sync_record = ScoutingAllianceSync(
                    alliance_id=alliance_id,
                    from_team_number=current_team,
                    to_team_number=member_obj.team_number,
                    data_type='combined',
                    data_count=total_shared
                )
                db.session.add(sync_record)
                sync_count += 1
                
                # Emit data via SocketIO (only if online)
                socketio.emit('alliance_data_sync', {
                    'from_team': current_team,
                    'scouting_data': [{k: v for k, v in d.items() if k != 'entry'} for d in current_team_scouting],
                    'pit_data': [{k: v for k, v in d.items() if k != 'entry'} for d in current_team_pit],
                    'sync_id': sync_record.id
                }, room=f'team_{member_obj.team_number}')
    
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'imported_count': total_imported,
        'shared_count': total_shared,
        'shared_copies_created': total_shared_copies,
        'synced_to': len([m for m in data_sharing_members if m.team_number != current_team]),
        'data_sharing_disabled_teams': disabled_teams,
        'message': f'Imported {total_imported} new entries, shared {total_shared} entries with alliance members, created {total_shared_copies} alliance copies' + 
                   (f'. Note: {len(disabled_teams)} team(s) have data sharing disabled.' if disabled_teams else '')
    })


@bp.route('/<int:alliance_id>/populate-shared-data', methods=['POST'])
@login_required
@admin_required
def populate_alliance_shared_data(alliance_id):
    """Populate AllianceSharedScoutingData and AllianceSharedPitData tables with existing data.
    
    This creates shared copies of all existing scouting data from alliance members
    so that the data persists even if the original team deletes their copy.
    Only includes data from teams with data sharing active.
    """
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    alliance_events = alliance.get_shared_events()
    
    # Get all active alliance members WHO HAVE DATA SHARING ENABLED
    all_members = alliance.get_active_members()
    data_sharing_members = [m for m in all_members if getattr(m, 'is_data_sharing_active', True)]
    member_teams = [m.team_number for m in data_sharing_members]
    
    total_scouting_copies = 0
    total_pit_copies = 0
    
    if alliance_events:
        # Get events
        events = Event.query.filter(Event.code.in_(alliance_events)).all()
        event_ids = [e.id for e in events]
        
        for team_num in member_teams:
            # Get ALL scouting data for each team (not just recent)
            # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
            scouting_entries = ScoutingData.query.join(Match).filter(
                Match.event_id.in_(event_ids),
                ScoutingData.scouting_team_number == team_num,
                ~ScoutingData.scout_name.like('[Alliance-%')
            ).all()
            
            for entry in scouting_entries:
                # Skip if this data was previously deleted by alliance admin
                if AllianceDeletedData.is_deleted(
                    alliance_id=alliance_id,
                    data_type='scouting',
                    match_id=entry.match_id,
                    team_id=entry.team_id,
                    alliance_color=entry.alliance,
                    source_team=team_num
                ):
                    continue  # Skip - deleted data shouldn't be re-synced
                
                # Check if shared copy already exists by original ID
                existing_shared = AllianceSharedScoutingData.query.filter_by(
                    alliance_id=alliance_id,
                    original_scouting_data_id=entry.id
                ).first()
                
                if not existing_shared:
                    # Also check by match/team/alliance combo to avoid duplicates
                    existing_shared = AllianceSharedScoutingData.query.filter_by(
                        alliance_id=alliance_id,
                        match_id=entry.match_id,
                        team_id=entry.team_id,
                        alliance=entry.alliance,
                        source_scouting_team_number=team_num
                    ).first()
                
                if not existing_shared:
                    shared_copy = AllianceSharedScoutingData.create_from_scouting_data(
                        entry, alliance_id, team_num
                    )
                    db.session.add(shared_copy)
                    total_scouting_copies += 1
            
            # Get ALL pit data for each team
            # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
            pit_entries = PitScoutingData.query.filter(
                PitScoutingData.scouting_team_number == team_num,
                ~PitScoutingData.scout_name.like('[Alliance-%')
            ).all()
            
            for entry in pit_entries:
                # Skip if this data was previously deleted by alliance admin
                if AllianceDeletedData.is_deleted(
                    alliance_id=alliance_id,
                    data_type='pit',
                    match_id=None,
                    team_id=entry.team_id,
                    alliance_color=None,
                    source_team=team_num
                ):
                    continue  # Skip - deleted data shouldn't be re-synced
                
                # Check if shared copy already exists by original ID
                existing_shared = AllianceSharedPitData.query.filter_by(
                    alliance_id=alliance_id,
                    original_pit_data_id=entry.id
                ).first()
                
                if not existing_shared:
                    # Also check by team to avoid duplicates
                    existing_shared = AllianceSharedPitData.query.filter_by(
                        alliance_id=alliance_id,
                        team_id=entry.team_id,
                        source_scouting_team_number=team_num
                    ).first()
                
                if not existing_shared:
                    shared_copy = AllianceSharedPitData.create_from_pit_data(
                        entry, alliance_id, team_num
                    )
                    db.session.add(shared_copy)
                    total_pit_copies += 1
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'scouting_copies_created': total_scouting_copies,
        'pit_copies_created': total_pit_copies,
        'message': f'Created {total_scouting_copies} scouting and {total_pit_copies} pit shared copies'
    })


@bp.route('/sync/receive', methods=['POST'])
@login_required
@admin_required
def receive_sync_data():
    """Receive synchronized data notification from alliance member.
    
    NOTE: We no longer create local copies. Alliance data lives ONLY in the 
    shared tables (AllianceSharedScoutingData/AllianceSharedPitData).
    This endpoint now just acknowledges receipt and updates the sync record.
    """
    data = request.get_json()
    current_team = get_current_scouting_team_number()
    
    from_team = data['from_team']
    sync_id = data['sync_id']
    
    # Verify we're in the same alliance
    common_alliance = db.session.query(ScoutingAlliance).join(ScoutingAllianceMember).filter(
        ScoutingAllianceMember.team_number.in_([current_team, from_team]),
        ScoutingAllianceMember.status == 'accepted'
    ).first()
    
    if not common_alliance:
        return jsonify({'success': False, 'error': 'Not in same alliance'})
    
    # Update sync record to mark as received
    sync_record = ScoutingAllianceSync.query.get(sync_id)
    if sync_record:
        sync_record.sync_status = 'synced'
        sync_record.last_sync = datetime.now(timezone.utc)
    
    db.session.commit()
    
    # Data is already in the shared tables - no need to create local copies
    return jsonify({'success': True, 'imported_count': 0, 'message': 'Sync acknowledged - data available in shared tables'})

# ======== CHAT SYSTEM ========

@bp.route('/<int:alliance_id>/chat')
@login_required
@admin_required
def get_chat_messages(alliance_id):
    """Get chat messages for alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    # Get recent messages
    messages = ScoutingAllianceChat.query.filter_by(
        alliance_id=alliance_id
    ).order_by(ScoutingAllianceChat.created_at.desc()).limit(50).all()
    
    # Mark messages as read for current team
    ScoutingAllianceChat.query.filter_by(
        alliance_id=alliance_id
    ).filter(
        ScoutingAllianceChat.from_team_number != current_team
    ).update({'is_read': True})
    db.session.commit()
    
    return jsonify({
        'success': True,
        'messages': [msg.to_dict() for msg in reversed(messages)]
    })

@bp.route('/<int:alliance_id>/chat/send', methods=['POST'])
@login_required
@admin_required
def send_chat_message(alliance_id):
    """Send chat message to alliance"""
    current_team = get_current_scouting_team_number()
    data = request.get_json()
    
    # Check if user is a member
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    # Create message
    message = ScoutingAllianceChat(
        alliance_id=alliance_id,
        from_team_number=current_team,
        from_username=current_user.username,
        message=data['message'],
        message_type=data.get('type', 'text')
    )
    db.session.add(message)
    db.session.commit()
    
    # Emit to alliance room
    socketio.emit('alliance_chat_message', message.to_dict(), room=f'alliance_{alliance_id}')
    
    return jsonify({'success': True})

# ======== UTILITY FUNCTIONS ========

def get_alliance_sync_stats(alliance_id, current_team):
    """Get synchronization statistics for an alliance"""
    total_syncs = ScoutingAllianceSync.query.filter_by(
        alliance_id=alliance_id,
        from_team_number=current_team
    ).count()
    
    successful_syncs = ScoutingAllianceSync.query.filter_by(
        alliance_id=alliance_id,
        from_team_number=current_team,
        sync_status='synced'
    ).count()
    
    last_sync = ScoutingAllianceSync.query.filter_by(
        alliance_id=alliance_id,
        from_team_number=current_team
    ).order_by(ScoutingAllianceSync.last_sync.desc()).first()
    
    return {
        'total_syncs': total_syncs,
        'successful_syncs': successful_syncs,
        'success_rate': (successful_syncs / total_syncs * 100) if total_syncs > 0 else 0,
        'last_sync': last_sync.last_sync if last_sync else None
    }

# ======== SOCKETIO EVENTS ========

@socketio.on('join_alliance_room')
def on_join_alliance_room(data):
    """Join alliance room for real-time updates"""
    # Accept either an alliance-specific join (alliance_id) or an event-level join (event_id)
    data = data or {}
    alliance_id = data.get('alliance_id')
    event_id = data.get('event_id')
    current_team = get_current_scouting_team_number()

    # If client provided an alliance_id, verify membership and join the alliance room
    if alliance_id is not None:
        try:
            member = ScoutingAllianceMember.query.filter_by(
                alliance_id=alliance_id,
                team_number=current_team,
                status='accepted'
            ).first()
        except Exception:
            member = None

        if member:
            join_room(f'alliance_{alliance_id}')
            emit('joined_alliance_room', {'alliance_id': alliance_id})
        else:
            # Do not raise if verification fails; emit a status for debugging
            emit('joined_alliance_room', {'alliance_id': alliance_id, 'joined': False})
        return

    # If client provided an event_id, join the broader event room used by alliance selection
    if event_id is not None:
        join_room(f'alliance_event_{event_id}')
        emit('status', {'msg': f'Joined alliance_event room for event {event_id}'})
        return

    # No valid identifier provided - emit a helpful status
    emit('status', {'msg': 'join_alliance_room called without alliance_id or event_id'})

@socketio.on('leave_alliance_room')
def on_leave_alliance_room(data):
    """Leave alliance room"""
    # Accept either { 'alliance_id': ... } to join an alliance-specific room
    # or { 'event_id': ... } to join the event-wide alliance selection room.
    # Be defensive about missing keys to avoid raising exceptions when other
    # modules emit the same event name with a different payload shape.
    alliance_id = None
    event_id = None
    if isinstance(data, dict):
        alliance_id = data.get('alliance_id')
        event_id = data.get('event_id')

    current_team = get_current_scouting_team_number()

    # If caller asked to join an alliance room (scouting alliance view)
    if alliance_id:
        # Verify membership
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()

        if member:
            join_room(f'alliance_{alliance_id}')
            emit('joined_alliance_room', {'alliance_id': alliance_id})
        return

    # If caller asked to join the event-wide alliance selection room
    if event_id:
        try:
            join_room(f'alliance_event_{event_id}')
            emit('status', {'msg': f'Joined alliance event room for event {event_id}'})
        except Exception:
            # Fail silently - joining a room is non-critical for functionality
            pass
        return

    # If payload didn't include either key, ignore gracefully.
    return


# ======== API ENDPOINTS ========

@bp.route('/api/alliance-mode-status')
@login_required
def api_alliance_mode_status():
    """API endpoint to check alliance mode status for current team"""
    try:
        from app.utils.config_manager import is_alliance_mode_active
        
        current_team = get_current_scouting_team_number()
        is_active = is_alliance_mode_active()
        
        return jsonify({
            'success': True,
            'is_active': is_active,
            'team_number': current_team
        })
    except Exception as e:
        current_app.logger.error(f"Error checking alliance mode status: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/api/alliance-mode-status/<int:alliance_id>')
@login_required
def api_specific_alliance_mode_status(alliance_id):
    """API endpoint to check if a specific alliance is active for current team"""
    try:
        from app.utils.config_manager import is_alliance_mode_active, get_active_alliance_info
        
        current_team = get_current_scouting_team_number()
        
        # Handle case where user is alliance admin (team 0 or None)
        if current_team is None or current_team == 0:
            # For alliance admins, find any member they belong to for this alliance
            member = ScoutingAllianceMember.query.join(User).filter(
                ScoutingAllianceMember.alliance_id == alliance_id,
                User.id == current_user.id,
                ScoutingAllianceMember.status == 'accepted'
            ).first()
            if member:
                current_team = member.team_number
        else:
            # Check if user is member of this alliance with their team number
            member = ScoutingAllianceMember.query.filter_by(
                alliance_id=alliance_id,
                team_number=current_team,
                status='accepted'
            ).first()
        
        if not member:
            return jsonify({
                'success': False,
                'error': 'Not a member of this alliance'
            }), 403
        
        # Check if alliance mode is active and if this specific alliance is the active one
        is_alliance_mode_on = is_alliance_mode_active()
        active_alliance_info = get_active_alliance_info() if is_alliance_mode_on else None
        active_alliance_id = active_alliance_info['alliance_id'] if active_alliance_info else None
        is_this_alliance_active = is_alliance_mode_on and active_alliance_id == alliance_id
        
        return jsonify({
            'success': True,
            'is_active': is_this_alliance_active,
            'alliance_mode_on': is_alliance_mode_on,
            'active_alliance_id': active_alliance_id,
            'team_number': current_team
        })
    except Exception as e:
        current_app.logger.error(f"Error checking specific alliance mode status: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/api/toggle-alliance-mode', methods=['POST'])
@login_required
def api_toggle_alliance_mode():
    """API endpoint to toggle alliance mode for current team"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        alliance_id = data.get('alliance_id')
        is_active = data.get('is_active', False)
        current_team = get_current_scouting_team_number()
        
        # Handle case where user is alliance admin (team 0 or None)
        # Find member through user's membership in this alliance
        if current_team is None or current_team == 0:
            # For alliance admins, find any member they belong to for this alliance
            member = ScoutingAllianceMember.query.join(User).filter(
                ScoutingAllianceMember.alliance_id == alliance_id,
                User.id == current_user.id,
                ScoutingAllianceMember.status == 'accepted'
            ).first()
            if member:
                current_team = member.team_number
        else:
            # Verify user is member of the alliance with their team number
            member = ScoutingAllianceMember.query.filter_by(
                alliance_id=alliance_id,
                team_number=current_team,
                status='accepted'
            ).first()

        if not member:
            return jsonify({'success': False, 'error': 'Not an accepted member of this alliance'}), 403
        
        # Update or create team alliance status
        team_status = TeamAllianceStatus.query.filter_by(
            team_number=current_team
        ).first()

        # If activating, ensure alliance configuration is complete
        alliance = ScoutingAlliance.query.get(alliance_id)
        message = ''
        
        if is_active:
            if not alliance or not alliance.is_config_complete():
                return jsonify({'success': False, 'error': 'Alliance configuration must be complete before activation'}), 400
            
            # Check if team is currently active in a different alliance
            current_status = TeamAllianceStatus.query.filter_by(team_number=current_team).first()
            if current_status and current_status.is_alliance_mode_active and current_status.active_alliance_id != alliance_id:
                current_alliance = current_status.active_alliance
                message = f'Switched from "{current_alliance.alliance_name}" to "{alliance.alliance_name}"'
            else:
                message = f'Alliance mode activated for {alliance.alliance_name}'
            
            # Re-enable data sharing for this member when reactivating
            member.is_data_sharing_active = True
            member.data_sharing_deactivated_at = None
            
            # Activate alliance mode (this will automatically deactivate any other active alliance)
            TeamAllianceStatus.activate_alliance_for_team(current_team, alliance_id)
            
            # Only load configs from team if alliance configs don't exist yet (first time setup)
            if alliance.game_config_team and not alliance.shared_game_config:
                game_config = load_game_config(team_number=alliance.game_config_team)
                alliance.shared_game_config = json.dumps(game_config)
            
            if alliance.pit_config_team and not alliance.shared_pit_config:
                pit_config = load_pit_config(team_number=alliance.pit_config_team)
                alliance.shared_pit_config = json.dumps(pit_config)
            
            # Update config status
            alliance.update_config_status()
            
            db.session.commit()
        else:
            # Deactivate alliance mode - set data sharing to inactive
            # This prevents other teams from syncing NEW data from this team
            member.is_data_sharing_active = False
            member.data_sharing_deactivated_at = datetime.now(timezone.utc)
            
            TeamAllianceStatus.deactivate_alliance_for_team(current_team)
            message = 'Alliance mode deactivated - future syncs will not get new data from your team, but existing shared data remains'
            db.session.commit()
        
        return jsonify({
            'success': True,
            'is_active': is_active,
            'message': message
        })
        
    except Exception as e:
        current_app.logger.error(f"Error toggling alliance mode: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/api/sync-alliance-data', methods=['POST'])
@login_required
def api_sync_alliance_data():
    """API endpoint to manually sync alliance data"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        alliance_id = data.get('alliance_id')
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Get alliance
        alliance = ScoutingAlliance.query.get(alliance_id)
        if not alliance:
            return jsonify({'success': False, 'error': 'Alliance not found'}), 404
        
        # Perform manual sync by getting all current data and broadcasting it
        alliance_events = alliance.get_shared_events()
        
        # Get scouting data to sync
        scouting_data = []
        pit_data = []
        
        if alliance_events:
            # Get events
            events = Event.query.filter(Event.code.in_(alliance_events)).all()
            event_ids = [e.id for e in events]
            
            # Get scouting data for these events
            scouting_entries = ScoutingData.query.join(Match).filter(
                Match.event_id.in_(event_ids),
                ScoutingData.scouting_team_number == current_team
            ).all()
            
            for entry in scouting_entries:
                scouting_data.append({
                    'team_number': entry.team.team_number,
                    'match_number': entry.match.match_number,
                    'match_type': entry.match.match_type,
                    'event_code': entry.match.event.code,
                    'alliance': entry.alliance,
                    'scout_name': entry.scout_name,
                    'data': entry.data,
                    'timestamp': entry.timestamp.isoformat()
                })
            
            # Get pit data for these events
            pit_entries = PitScoutingData.query.filter(
                PitScoutingData.scouting_team_number == current_team
            ).all()
            
            for entry in pit_entries:
                pit_data.append({
                    'team_number': entry.team.team_number,
                    'scout_name': entry.scout_name,
                    'data': entry.data,  # This uses the @property method which parses data_json
                    'timestamp': entry.timestamp.isoformat()
                })
        
        # Send data to alliance members
        sync_count = 0
        for member_obj in alliance.get_active_members():
            if member_obj.team_number != current_team:
                # Create sync record
                sync_record = ScoutingAllianceSync(
                    alliance_id=alliance_id,
                    from_team_number=current_team,
                    to_team_number=member_obj.team_number,
                    data_type='manual_sync',
                    data_count=len(scouting_data) + len(pit_data),
                    sync_status='sent',
                    last_sync=datetime.now(timezone.utc)
                )
                db.session.add(sync_record)
                sync_count += 1
                
                # Emit data via SocketIO
                socketio.emit('alliance_data_sync_auto', {
                    'from_team': current_team,
                    'alliance_name': alliance.alliance_name,
                    'scouting_data': scouting_data,
                    'pit_data': pit_data,
                    'sync_id': sync_record.id,
                    'type': 'manual_sync'
                }, room=f'team_{member_obj.team_number}')
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Alliance data synchronized successfully',
            'synced_to': sync_count,
            'scouting_entries': len(scouting_data),
            'pit_entries': len(pit_data)
        })
        
    except Exception as e:
        current_app.logger.error(f"Error syncing alliance data: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/api/leave-alliance', methods=['POST'])
@login_required
def api_leave_alliance():
    """API endpoint for teams to leave an alliance"""
    data = request.get_json()
    alliance_id = data.get('alliance_id')
    
    if not alliance_id:
        return jsonify({
            'success': False,
            'error': 'Alliance ID is required'
        }), 400
    
    try:
        from app.models import TeamAllianceStatus
        
        current_team = get_current_scouting_team_number()
        
        # Get the alliance
        alliance = ScoutingAlliance.query.get_or_404(alliance_id)
        
        # Check if user is a member of this alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({
                'success': False,
                'error': 'You are not a member of this alliance'
            }), 403
        
        # Check if this is the only admin - prevent leaving if so
        admin_members = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            role='admin',
            status='accepted'
        ).all()
        
        if member.role == 'admin' and len(admin_members) == 1:
            # Check if there are other members who could become admin
            other_members = ScoutingAllianceMember.query.filter_by(
                alliance_id=alliance_id,
                status='accepted'
            ).filter(ScoutingAllianceMember.team_number != current_team).all()
            
            if other_members:
                return jsonify({
                    'success': False,
                    'error': 'You are the only administrator. Please transfer admin rights to another member before leaving.'
                }), 400
        
        # If this team has alliance mode active for this alliance, deactivate it
        alliance_status = TeamAllianceStatus.query.filter_by(
            team_number=current_team,
            is_alliance_mode_active=True,
            active_alliance_id=alliance_id
        ).first()
        
        if alliance_status:
            alliance_status.is_alliance_mode_active = False
            alliance_status.active_alliance_id = None
            alliance_status.last_updated = datetime.now(timezone.utc)
        
        # Remove the member from the alliance
        db.session.delete(member)
        
        # If this was the last member, delete the alliance entirely
        remaining_members = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            status='accepted'
        ).filter(ScoutingAllianceMember.team_number != current_team).all()
        
        alliance_name = alliance.alliance_name  # Store name before potential deletion
        
        if not remaining_members:
            # Delete the entire alliance and related records
            # The cascade='all, delete-orphan' should handle most cleanup
            db.session.delete(alliance)
            alliance_deleted = True
        else:
            alliance_deleted = False
        
        db.session.commit()
        
        # Emit notification to remaining alliance members
        if not alliance_deleted:
            socketio.emit('alliance_member_left', {
                'alliance_id': alliance_id,
                'team_number': current_team,
                'team_name': f"Team {current_team}",
                'alliance_name': alliance_name
            }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'message': f'Successfully left the alliance "{alliance_name}"',
            'alliance_deleted': alliance_deleted
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error leaving alliance: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ======== ALLIANCE CONFIGURATION EDITOR ========

@bp.route('/<int:alliance_id>/config/game')
@login_required
@admin_required
def edit_game_config(alliance_id):
    """Edit alliance shared game configuration"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to edit configurations.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    # Load current shared config or default to scouting team's config
    if alliance.shared_game_config:
        try:
            config_data = json.loads(alliance.shared_game_config)
        except json.JSONDecodeError:
            # If JSON is invalid, fall back to scouting team's config
            config_data = load_game_config(team_number=current_team)
    else:
        # No alliance config exists, use scouting team's config as template
        config_data = load_game_config(team_number=current_team)
    
    # If still no config found, use the default
    if not config_data:
        config_data = load_game_config()

    # Keep a copy of the original config before edits for potential migration comparisons
    try:
        original_config = json.loads(alliance.shared_game_config) if alliance.shared_game_config else {}
    except Exception:
        original_config = config_data
    
    return render_template('scouting_alliances/edit_game_config_new.html', 
                         alliance=alliance, 
                         config=config_data,
                         **get_theme_context())

@bp.route('/<int:alliance_id>/config/game', methods=['POST'])
@login_required
@admin_required
def save_game_config(alliance_id):
    """Save alliance shared game configuration"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to edit configurations.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    try:
        # Handle both JSON and form data
        if request.is_json:
            config_data = request.get_json()
        else:
            # Handle form data
            if 'json_config' in request.form:
                # JSON mode - parse the JSON from form
                config_data = json.loads(request.form['json_config'])
            else:
                # Simple mode - build config from form data like the main config editor
                # Get current config as base or create default structure
                if alliance.shared_game_config:
                    try:
                        config_data = json.loads(alliance.shared_game_config)
                    except json.JSONDecodeError:
                        config_data = load_game_config(team_number=current_team) or {}
                else:
                    config_data = load_game_config(team_number=current_team) or {}
                
                # Ensure basic structure exists
                if not config_data:
                    config_data = {
                        'game_name': 'Default Game',
                        'season': 2025,
                        'version': '1.0.0',
                        'alliance_size': 3,
                        'scouting_stations': 6,
                        'current_event_code': '',
                        'match_types': ['Qualification'],
                        'auto_period': {'duration_seconds': 15, 'scoring_elements': []},
                        'teleop_period': {'duration_seconds': 135, 'scoring_elements': []},
                        'endgame_period': {'duration_seconds': 30, 'scoring_elements': []},
                        'game_pieces': [],
                        'post_match': {'rating_elements': [], 'text_elements': []}
                    }
                
                # Update basic settings
                config_data['game_name'] = request.form.get('game_name', config_data.get('game_name', ''))
                config_data['season'] = int(request.form.get('season', config_data.get('season', 2025)))
                config_data['version'] = request.form.get('version', config_data.get('version', '1.0.0'))
                config_data['alliance_size'] = int(request.form.get('alliance_size', config_data.get('alliance_size', 3)))
                config_data['scouting_stations'] = int(request.form.get('scouting_stations', config_data.get('scouting_stations', 6)))
                config_data['current_event_code'] = request.form.get('current_event_code', config_data.get('current_event_code', ''))
                
                # Update match types
                match_types = []
                for match_type in ['practice', 'qualification', 'playoff']:
                    if request.form.get(f'match_type_{match_type}'):
                        match_types.append(match_type.title())
                config_data['match_types'] = match_types if match_types else ['Qualification']
                
                # Update period durations
                if 'auto_period' not in config_data:
                    config_data['auto_period'] = {}
                if 'teleop_period' not in config_data:
                    config_data['teleop_period'] = {}
                if 'endgame_period' not in config_data:
                    config_data['endgame_period'] = {}
                
                config_data['auto_period']['duration_seconds'] = int(request.form.get('auto_duration', 15))
                config_data['teleop_period']['duration_seconds'] = int(request.form.get('teleop_duration', 135))
                config_data['endgame_period']['duration_seconds'] = int(request.form.get('endgame_duration', 30))
                
                # Update scoring elements for each period
                for period in ['auto', 'teleop', 'endgame']:
                    period_key = f'{period}_period'
                    elements = []
                    
                    # Find all elements for this period
                    element_indices = set()
                    for key in request.form.keys():
                        if key.startswith(f'{period}_element_id_'):
                            index = key.split('_')[-1]
                            try:
                                element_indices.add(int(index))
                            except ValueError:
                                continue
                    
                    for index in sorted(element_indices):
                        element_id = request.form.get(f'{period}_element_id_{index}')
                        element_name = request.form.get(f'{period}_element_name_{index}')
                        element_type = request.form.get(f'{period}_element_type_{index}')
                        
                        if element_id and element_name and element_type:
                            element = {
                                'id': element_id,
                                'perm_id': element_id,
                                'name': element_name,
                                'type': element_type,
                                'default': 0 if element_type == 'counter' else False if element_type == 'boolean' else ''
                            }
                            
                            # Add points if provided
                            points = request.form.get(f'{period}_element_points_{index}')
                            if points:
                                try:
                                    element['points'] = float(points)
                                except ValueError:
                                    element['points'] = 0

                            # Counter-specific fields (step, alt step, enabled flag)
                            try:
                                if element_type == 'counter':
                                    # Primary step
                                    try:
                                        step_val = request.form.get(f'{period}_element_step_{index}')
                                        if step_val:
                                            element['step'] = max(1, int(step_val))
                                        else:
                                            element['step'] = 1
                                    except Exception:
                                        element['step'] = 1

                                    # Alt-step and enabled flag
                                    alt_enabled = request.form.get(f'{period}_element_alt_step_enabled_{index}')
                                    alt_step_val = request.form.get(f'{period}_element_alt_step_{index}')
                                    if alt_enabled:
                                        element['alt_step_enabled'] = True
                                        if alt_step_val:
                                            try:
                                                element['alt_step'] = int(alt_step_val)
                                            except Exception:
                                                pass
                                        else:
                                            # Default alt step to primary step when enabled but blank
                                            try:
                                                element['alt_step'] = int(element.get('step', 1))
                                            except Exception:
                                                element['alt_step'] = 1
                                    else:
                                        element['alt_step_enabled'] = False
                            except Exception:
                                pass

                            elements.append(element)
                    
                    # Debug: log parsed elements for this period so we can verify alt-step parsing
                    try:
                        debug_path = os.path.join(current_app.instance_path, 'config_save_debug.log')
                        with open(debug_path, 'a', encoding='utf-8') as dbg:
                            dbg.write(f"Parsed {period_key} scoring_elements (alliance {alliance_id}):\n")
                            dbg.write(json.dumps(elements, indent=2))
                            dbg.write('\n---\n')
                    except Exception:
                        pass
                    config_data[period_key]['scoring_elements'] = elements
                
                # Update game pieces
                game_pieces = []
                piece_indices = set()
                for key in request.form.keys():
                    if key.startswith('game_piece_id_'):
                        index = key.split('_')[-1]
                        try:
                            piece_indices.add(int(index))
                        except ValueError:
                            continue
                
                for index in sorted(piece_indices):
                    piece_id = request.form.get(f'game_piece_id_{index}')
                    piece_name = request.form.get(f'game_piece_name_{index}')
                    
                    if piece_id and piece_name:
                        piece = {
                            'id': piece_id,
                            'name': piece_name,
                            'auto_points': float(request.form.get(f'game_piece_auto_points_{index}', 0)),
                            'teleop_points': float(request.form.get(f'game_piece_teleop_points_{index}', 0))
                        }
                        game_pieces.append(piece)
                
                config_data['game_pieces'] = game_pieces
                
                # Update post-match elements
                if 'post_match' not in config_data:
                    config_data['post_match'] = {}
                
                # Rating elements
                rating_elements = []
                rating_indices = set()
                for key in request.form.keys():
                    if key.startswith('rating_element_name_'):
                        index = key.split('_')[-1]
                        try:
                            rating_indices.add(int(index))
                        except ValueError:
                            continue
                
                for index in sorted(rating_indices):
                    element_name = request.form.get(f'rating_element_name_{index}')
                    
                    if element_name:
                        element = {
                            'id': f'rating_{index}',
                            'name': element_name,
                            'type': 'rating',
                            'min': int(request.form.get(f'rating_element_min_{index}', 1)),
                            'max': int(request.form.get(f'rating_element_max_{index}', 5)),
                            'default': 3
                        }
                        rating_elements.append(element)
                
                # Text elements
                text_elements = []
                text_indices = set()
                for key in request.form.keys():
                    if key.startswith('text_element_name_'):
                        index = key.split('_')[-1]
                        try:
                            text_indices.add(int(index))
                        except ValueError:
                            continue
                
                for index in sorted(text_indices):
                    element_name = request.form.get(f'text_element_name_{index}')
                    
                    if element_name:
                        element = {
                            'id': f'text_{index}',
                            'name': element_name,
                            'type': 'text',
                            'multiline': bool(request.form.get(f'text_element_multiline_{index}')),
                            'default': ''
                        }
                        text_elements.append(element)
                
                config_data['post_match']['rating_elements'] = rating_elements
                config_data['post_match']['text_elements'] = text_elements
        
        # Capture original config for migration comparison
        try:
            original_config_before = json.loads(alliance.shared_game_config) if alliance.shared_game_config else {}
        except Exception:
            original_config_before = {}

        # Capture old event code for comparison
        old_event_code = original_config_before.get('current_event_code') if original_config_before else None
        new_event_code = config_data.get('current_event_code')

        # Validate and save the configuration
        alliance.shared_game_config = json.dumps(config_data, indent=2)
        alliance.game_config_team = current_team  # Mark that config is set
        alliance.updated_at = datetime.now(timezone.utc)
        
        # Update config status
        alliance.update_config_status()
        
        db.session.commit()
        
        # Clear event cache if current_event_code changed to ensure background sync picks up new event
        try:
            from app.utils.sync_status import clear_event_cache
            clear_event_cache(current_team)
        except Exception:
            pass
        
        # Emit Socket.IO event to notify alliance members
        socketio.emit('alliance_config_updated', {
            'alliance_id': alliance_id,
            'config_type': 'game',
            'message': f'Game configuration updated by Team {current_team}'
        }, room=f'alliance_{alliance_id}')
        
        # If event code changed, broadcast to all clients to reload immediately
        if old_event_code != new_event_code and new_event_code:
            try:
                socketio.emit('event_changed', {
                    'old_event_code': old_event_code,
                    'new_event_code': new_event_code,
                    'event_name': new_event_code,
                    'scouting_team': current_team
                }, namespace='/')
            except Exception:
                pass
        
        flash('Alliance game configuration saved successfully!', 'success')

        # Detect and prompt for migration if any scoring element ids changed
        try:
            original_config = original_config_before
        except Exception:
            original_config = {}
        skip_migration = request.form.get('skip_migration') == 'true'
        # Compute mapping suggestions
        try:
            from app.utils.config_migration import compute_mapping_suggestions
            # Use client-provided mapping_suggestions if present
            mapping_suggestions_raw = request.form.get('mapping_suggestions') or request.form.get('mapping_suggestions_json')
            if mapping_suggestions_raw:
                try:
                    mapping_suggestions = json.loads(mapping_suggestions_raw)
                except Exception:
                    mapping_suggestions = compute_mapping_suggestions(original_config, config_data)
            else:
                mapping_suggestions = compute_mapping_suggestions(original_config, config_data)
            mapping_needed = False
            for period, mappings in mapping_suggestions.items():
                for m in mappings:
                    if not m['suggested_new_id'] or m['suggested_new_id'] != m['old']['id']:
                        mapping_needed = True
                        break
                if mapping_needed:
                    break
            if mapping_needed and not skip_migration:
                try:
                    current_app.logger.debug(f"Alliance mapping needed for alliance {alliance_id}. Suggestions: {mapping_suggestions}")
                except Exception:
                    pass
                # Render migration UI so the alliance admin can migrate shared data
                return render_template('config_migrate.html', original_config=original_config, updated_config=config_data, mapping_suggestions=mapping_suggestions, alliance_id=alliance_id, team_number=None, **get_theme_context())
        except Exception:
            current_app.logger.debug('Failed to compute mapping suggestions')
        except Exception:
            pass
        
        # Handle JSON requests (API) vs form submissions
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({'success': True, 'config': config_data})
        else:
            return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
        
    except Exception as e:
        current_app.logger.error(f"Error saving alliance game config: {str(e)}")
        db.session.rollback()
        flash(f'Error saving configuration: {str(e)}', 'error')
        
        # Handle JSON requests (API) vs form submissions
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({'success': False, 'error': str(e)}), 500
        else:
            return redirect(url_for('scouting_alliances.edit_alliance_game_config', alliance_id=alliance_id))

@bp.route('/<int:alliance_id>/config/pit')
@login_required
@admin_required
def edit_pit_config(alliance_id):
    """Edit alliance shared pit configuration"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to edit configurations.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    # Load current shared config or default to scouting team's config
    if alliance.shared_pit_config:
        try:
            config_data = json.loads(alliance.shared_pit_config)
        except json.JSONDecodeError:
            # If JSON is invalid, fall back to scouting team's config
            config_data = load_pit_config(team_number=current_team)
    else:
        # No alliance config exists, use scouting team's config as template
        config_data = load_pit_config(team_number=current_team)
    
    # If still no config found, use the default
    if not config_data:
        config_data = load_pit_config()
    
    return render_template('scouting_alliances/edit_pit_config.html', 
                         alliance=alliance, 
                         config=config_data,
                         **get_theme_context())

@bp.route('/<int:alliance_id>/config/pit', methods=['POST'])
@login_required
@admin_required
def save_pit_config(alliance_id):
    """Save alliance shared pit configuration"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to edit configurations.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    try:
        # Handle both JSON and form data
        if request.is_json:
            config_data = request.get_json()
        else:
            # Handle form data
            if 'json_config' in request.form:
                # JSON mode - parse the JSON from form
                config_data = json.loads(request.form['json_config'])
            else:
                # Simple mode - build config from form data
                config_data = {
                    'pit_scouting': {
                        'title': request.form.get('pit_title', 'Pit Scouting'),
                        'description': request.form.get('pit_description', 'Robot and team assessment in the pits'),
                        'sections': []
                    }
                }
                
                # Parse sections and elements from form data
                section_indices = set()
                for key in request.form.keys():
                    if key.startswith('section_id_'):
                        section_index = int(key.split('_')[2])
                        section_indices.add(section_index)
                
                for section_index in sorted(section_indices):
                    section_id = request.form.get(f'section_id_{section_index}')
                    section_name = request.form.get(f'section_name_{section_index}')
                    
                    if section_id and section_name:
                        section = {
                            'id': section_id,
                            'name': section_name,
                            'elements': []
                        }
                        
                        # Find elements for this section
                        element_indices = set()
                        for key in request.form.keys():
                            if key.startswith(f'element_id_{section_index}_'):
                                element_index = int(key.split('_')[3])
                                element_indices.add(element_index)
                        
                        for element_index in sorted(element_indices):
                            element_id = request.form.get(f'element_id_{section_index}_{element_index}')
                            element_name = request.form.get(f'element_name_{section_index}_{element_index}')
                            element_type = request.form.get(f'element_type_{section_index}_{element_index}')
                            element_placeholder = request.form.get(f'element_placeholder_{section_index}_{element_index}')
                            
                            if element_id and element_name and element_type:
                                element = {
                                    'id': element_id,
                                    'name': element_name,
                                    'type': element_type
                                }
                                
                                if element_placeholder:
                                    element['placeholder'] = element_placeholder
                                
                                # Handle options for select/multiselect
                                if element_type in ['select', 'multiselect']:
                                    options = []
                                    option_index = 0
                                    while True:
                                        option_value = request.form.get(f'element_option_value_{section_index}_{element_index}_{option_index}')
                                        option_label = request.form.get(f'element_option_label_{section_index}_{element_index}_{option_index}')
                                        
                                        if option_value and option_label:
                                            options.append({
                                                'value': option_value,
                                                'label': option_label
                                            })
                                            option_index += 1
                                        else:
                                            break
                                    
                                    if options:
                                        element['options'] = options
                                
                                section['elements'].append(element)
                        
                        config_data['pit_scouting']['sections'].append(section)
        
        # Validate and save the configuration
        alliance.shared_pit_config = json.dumps(config_data, indent=2)
        alliance.pit_config_team = current_team  # Mark that config is set
        alliance.updated_at = datetime.now(timezone.utc)
        
        # Update config status
        alliance.update_config_status()
        
        db.session.commit()
        
        # Emit Socket.IO event to notify alliance members
        socketio.emit('alliance_config_updated', {
            'alliance_id': alliance_id,
            'config_type': 'pit',
            'message': f'Pit configuration updated by Team {current_team}'
        }, room=f'alliance_{alliance_id}')
        
        flash('Alliance pit configuration saved successfully!', 'success')
        return jsonify({'success': True, 'config': config_data})
        
    except Exception as e:
        current_app.logger.error(f"Error saving alliance pit config: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/<int:alliance_id>/config/<config_type>/copy-scouting-team', methods=['POST'])
@login_required
@admin_required
def copy_scouting_team_config(alliance_id, config_type):
    """Copy scouting team configuration to alliance shared config"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'You must be an alliance admin to copy configurations.'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    try:
        if config_type == 'game':
            # Load scouting team's game config
            config_data = load_game_config(team_number=current_team)
            if config_data:
                alliance.shared_game_config = json.dumps(config_data, indent=2)
                alliance.game_config_team = current_team  # Mark that config is set
            else:
                return jsonify({'success': False, 'error': 'No game configuration found for your scouting team.'}), 404
                
        elif config_type == 'pit':
            # Load scouting team's pit config
            config_data = load_pit_config(team_number=current_team)
            if config_data:
                alliance.shared_pit_config = json.dumps(config_data, indent=2)
                alliance.pit_config_team = current_team  # Mark that config is set
            else:
                return jsonify({'success': False, 'error': 'No pit configuration found for your scouting team.'}), 404
        else:
            return jsonify({'success': False, 'error': 'Invalid configuration type.'}), 400
        
        alliance.updated_at = datetime.now(timezone.utc)
        
        # Update config status
        alliance.update_config_status()
        
        db.session.commit()
        
        # Emit Socket.IO event to notify alliance members
        socketio.emit('alliance_config_updated', {
            'alliance_id': alliance_id,
            'config_type': config_type,
            'message': f'{config_type.title()} configuration copied from Team {current_team}'
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({'success': True, 'config': config_data})
        
    except Exception as e:
        current_app.logger.error(f"Error copying scouting team config: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ======== TEMPLATE IMPORT ENDPOINTS ========

@bp.route('/<int:alliance_id>/config/game/import', methods=['POST'])
@login_required
@admin_required
def import_game_config_template(alliance_id):
    """Import a team's game configuration as template for alliance config"""
    current_team = get_current_scouting_team_number()
    
    # Get team_number from form data
    team_number = request.form.get('team_number')
    if not team_number:
        return jsonify({'success': False, 'error': 'Team number is required'})
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        # Handle special case for scouting team
        if team_number == 'scouting_team':
            team_number = current_team
        
        # Load the specified team's game config
        template_config = load_game_config(team_number=team_number)
        
        if not template_config:
            return jsonify({'success': False, 'error': f'No game configuration found for team {team_number}'}), 404
        
        return jsonify({
            'success': True,
            'config': template_config,
            'source_team': team_number
        })
        
    except Exception as e:
        current_app.logger.error(f"Error importing game config from team {team_number}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/<int:alliance_id>/config/pit/import', methods=['POST'])
@login_required
@admin_required
def import_pit_config_template(alliance_id):
    """Import a team's pit configuration as template for alliance config"""
    current_team = get_current_scouting_team_number()
    
    # Get team_number from form data
    team_number = request.form.get('team_number')
    if not team_number:
        return jsonify({'success': False, 'error': 'Team number is required'})
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        # Handle special case for scouting team
        if team_number == 'scouting_team':
            team_number = current_team
        
        # Load the specified team's pit config
        template_config = load_pit_config(team_number=team_number)
        
        if not template_config:
            return jsonify({'success': False, 'error': f'No pit configuration found for team {team_number}'}), 404
        
        return jsonify({
            'success': True,
            'config': template_config,
            'source_team': team_number
        })
        
    except Exception as e:
        current_app.logger.error(f"Error importing pit config from team {team_number}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/<int:alliance_id>/available-templates')
@login_required
@admin_required
def get_available_templates(alliance_id):
    """Get list of teams with available configurations for template import"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        import os
        
        # Get alliance to check member teams
        alliance = ScoutingAlliance.query.get_or_404(alliance_id)
        member_team_numbers = [m.team_number for m in alliance.get_active_members()]
        
        # Check for available team configs in instance/configs
        configs_dir = os.path.join(os.getcwd(), 'instance', 'configs')
        available_templates = []
        
        if os.path.exists(configs_dir):
            for team_dir in os.listdir(configs_dir):
                if team_dir.isdigit():
                    team_number = int(team_dir)
                    team_config_dir = os.path.join(configs_dir, team_dir)
                    
                    # Check for game and pit configs
                    game_config_exists = os.path.exists(os.path.join(team_config_dir, 'game_config.json'))
                    pit_config_exists = os.path.exists(os.path.join(team_config_dir, 'pit_config.json'))
                    
                    if game_config_exists or pit_config_exists:
                        is_member = team_number in member_team_numbers
                        available_templates.append({
                            'team_number': team_number,
                            'team_name': f'Team {team_number}',
                            'has_game_config': game_config_exists,
                            'has_pit_config': pit_config_exists,
                            'is_alliance_member': is_member
                        })
        
        # Sort by team number
        available_templates.sort(key=lambda x: x['team_number'])
        
        return jsonify({
            'success': True,
            'templates': available_templates
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting available templates: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ======== PERIODIC SYNC FUNCTIONALITY ========

def perform_periodic_alliance_sync():
    """Perform periodic sync for all active alliance teams"""
    try:
        with current_app.app_context():
            # Get all active alliance statuses
            active_statuses = TeamAllianceStatus.query.filter_by(
                is_alliance_mode_active=True
            ).all()
            
            for status in active_statuses:
                try:
                    # Get the alliance
                    alliance = status.active_alliance
                    if not alliance:
                        continue
                    
                    current_team = status.team_number
                    alliance_events = alliance.get_shared_events()
                    
                    if not alliance_events:
                        continue
                    
                    # Get events
                    events = Event.query.filter(Event.code.in_(alliance_events)).all()
                    event_ids = [e.id for e in events]
                    
                    if not event_ids:
                        continue
                    
                    # Get recent scouting data (last 5 minutes) to avoid re-syncing old data
                    recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
                    
                    # Get recent scouting data for this team
                    # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
                    recent_scouting = ScoutingData.query.join(Match).filter(
                        Match.event_id.in_(event_ids),
                        ScoutingData.scouting_team_number == current_team,
                        ScoutingData.timestamp >= recent_time,
                        ~ScoutingData.scout_name.like('[Alliance-%')
                    ).all()
                    
                    # Get recent pit data for this team
                    # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
                    recent_pit = PitScoutingData.query.filter(
                        PitScoutingData.scouting_team_number == current_team,
                        PitScoutingData.timestamp >= recent_time,
                        ~PitScoutingData.scout_name.like('[Alliance-%')
                    ).all()
                    
                    if not recent_scouting and not recent_pit:
                        continue  # No recent data to sync
                    
                    # Create shared copies in AllianceSharedScoutingData/AllianceSharedPitData
                    shared_copies_created = 0
                    
                    for entry in recent_scouting:
                        # Skip if this data was previously deleted by alliance admin
                        if AllianceDeletedData.is_deleted(
                            alliance_id=alliance.id,
                            data_type='scouting',
                            match_id=entry.match_id,
                            team_id=entry.team_id,
                            alliance_color=entry.alliance,
                            source_team=current_team
                        ):
                            continue  # Skip - deleted data shouldn't be re-synced
                        
                        # Check if shared copy already exists
                        existing_shared = AllianceSharedScoutingData.query.filter_by(
                            alliance_id=alliance.id,
                            original_scouting_data_id=entry.id
                        ).first()
                        
                        if not existing_shared:
                            existing_shared = AllianceSharedScoutingData.query.filter_by(
                                alliance_id=alliance.id,
                                match_id=entry.match_id,
                                team_id=entry.team_id,
                                alliance=entry.alliance,
                                source_scouting_team_number=current_team
                            ).first()
                        
                        if not existing_shared:
                            shared_copy = AllianceSharedScoutingData.create_from_scouting_data(
                                entry, alliance.id, current_team
                            )
                            db.session.add(shared_copy)
                            shared_copies_created += 1
                    
                    for entry in recent_pit:
                        # Skip if this data was previously deleted by alliance admin
                        if AllianceDeletedData.is_deleted(
                            alliance_id=alliance.id,
                            data_type='pit',
                            match_id=None,
                            team_id=entry.team_id,
                            alliance_color=None,
                            source_team=current_team
                        ):
                            continue  # Skip - deleted data shouldn't be re-synced
                        
                        # Check if shared copy already exists
                        existing_shared = AllianceSharedPitData.query.filter_by(
                            alliance_id=alliance.id,
                            original_pit_data_id=entry.id
                        ).first()
                        
                        if not existing_shared:
                            existing_shared = AllianceSharedPitData.query.filter_by(
                                alliance_id=alliance.id,
                                team_id=entry.team_id,
                                source_scouting_team_number=current_team
                            ).first()
                        
                        if not existing_shared:
                            shared_copy = AllianceSharedPitData.create_from_pit_data(
                                entry, alliance.id, current_team
                            )
                            db.session.add(shared_copy)
                            shared_copies_created += 1
                    
                    # Prepare sync data
                    scouting_data = []
                    for entry in recent_scouting:
                        scouting_data.append({
                            'team_number': entry.team.team_number,
                            'match_number': entry.match.match_number,
                            'match_type': entry.match.match_type,
                            'event_code': entry.match.event.code,
                            'alliance': entry.alliance,
                            'scout_name': entry.scout_name,
                            'data': entry.data,
                            'timestamp': entry.timestamp.isoformat()
                        })
                    
                    pit_data = []
                    for entry in recent_pit:
                        pit_data.append({
                            'team_number': entry.team.team_number,
                            'scout_name': entry.scout_name,
                            'data': entry.data,
                            'timestamp': entry.timestamp.isoformat()
                        })
                    
                    # Send to alliance members
                    active_members = alliance.get_active_members()
                    sync_count = 0
                    
                    for member in active_members:
                        if member.team_number != current_team:
                            # Create sync record
                            sync_record = ScoutingAllianceSync(
                                alliance_id=alliance.id,
                                from_team_number=current_team,
                                to_team_number=member.team_number,
                                data_type='periodic_sync',
                                data_count=len(scouting_data) + len(pit_data),
                                sync_status='sent',
                                last_sync=datetime.now(timezone.utc)
                            )
                            db.session.add(sync_record)
                            sync_count += 1
                            
                            # Emit data via SocketIO
                            socketio.emit('alliance_data_sync_auto', {
                                'from_team': current_team,
                                'alliance_name': alliance.alliance_name,
                                'scouting_data': scouting_data,
                                'pit_data': pit_data,
                                'sync_id': sync_record.id,
                                'type': 'periodic_sync'
                            }, room=f'team_{member.team_number}')
                    
                    if sync_count > 0 or shared_copies_created > 0:
                        db.session.commit()
                        print(f"Periodic sync: Team {current_team} synced {len(scouting_data)} scouting + {len(pit_data)} pit entries to {sync_count} alliance members, created {shared_copies_created} shared copies")
                
                except Exception as e:
                    print(f"Error in periodic sync for team {status.team_number}: {str(e)}")
                    continue
    
    except Exception as e:
        print(f"Error in perform_periodic_alliance_sync: {str(e)}")


def perform_alliance_api_sync_for_alliance(alliance_id):
    """Perform immediate API sync for a specific alliance (manual trigger).
    
    This function syncs teams and matches for a specific alliance immediately,
    bypassing the interval throttling. It uses alliance member API keys as
    fallback if the primary API fails.
    
    Args:
        alliance_id: The ID of the alliance to sync
        
    Returns:
        dict with success status and sync counts
    """
    result = {
        'success': False,
        'message': '',
        'teams_added': 0,
        'teams_updated': 0,
        'matches_added': 0,
        'matches_updated': 0
    }
    
    try:
        from app.utils.config_manager import load_game_config
        from app.utils.api_utils import (
            get_teams_with_alliance_fallback, get_matches_with_alliance_fallback, 
            get_event_details_with_alliance_fallback
        )
        from app.models import ScoutingAlliance, Event, Team, Match, db
        from sqlalchemy import func
        
        alliance = ScoutingAlliance.query.get(alliance_id)
        if not alliance:
            result['message'] = f'Alliance {alliance_id} not found'
            return result
        
        if not alliance.is_config_complete():
            result['message'] = 'Alliance configuration is incomplete'
            return result
        
        # Load alliance game config
        if alliance.shared_game_config:
            try:
                game_config = json.loads(alliance.shared_game_config)
            except Exception:
                game_config = load_game_config(team_number=alliance.game_config_team)
        elif alliance.game_config_team:
            game_config = load_game_config(team_number=alliance.game_config_team)
        else:
            result['message'] = 'No game config available for alliance'
            return result
        
        # Get event code
        event_code = (game_config.get('current_event_code') or '').strip()
        if not event_code:
            result['message'] = 'No event code configured for alliance'
            return result
        
        # Determine storage team
        storage_team = alliance.game_config_team or (alliance.get_active_members()[0].team_number if alliance.get_active_members() else None)
        if storage_team is None:
            result['message'] = 'No storage team determined for alliance'
            return result
        
        # Ensure event exists
        event = Event.query.filter(
            func.upper(Event.code) == event_code.upper(),
            Event.scouting_team_number == storage_team
        ).first()
        
        if not event:
            try:
                event_details = get_event_details_with_alliance_fallback(event_code, alliance_id)
                if event_details:
                    from app.routes.data import get_or_create_event
                    event = get_or_create_event(
                        name=event_details.get('name', event_code),
                        code=event_code,
                        year=event_details.get('year', game_config.get('season', None) or game_config.get('year', 0)),
                        location=event_details.get('location'),
                        start_date=event_details.get('start_date'),
                        end_date=event_details.get('end_date'),
                        scouting_team_number=storage_team
                    )
                    if event_details.get('timezone') and not getattr(event, 'timezone', None):
                        event.timezone = event_details.get('timezone')
                        db.session.add(event)
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                result['message'] = f'Failed to create event: {str(e)}'
                return result
        
        if not event:
            result['message'] = f'Could not find or create event {event_code}'
            return result
        
        # Sync teams
        try:
            team_data_list = get_teams_with_alliance_fallback(event_code, alliance_id)
            
            for team_data in team_data_list:
                if not team_data or not team_data.get('team_number'):
                    continue
                team_number = team_data.get('team_number')
                team = Team.query.filter_by(team_number=team_number, scouting_team_number=storage_team).first()
                if team:
                    team.team_name = team_data.get('team_name', team.team_name)
                    team.location = team_data.get('location', team.location)
                    result['teams_updated'] += 1
                else:
                    team = Team(team_number=team_number,
                                team_name=team_data.get('team_name'),
                                location=team_data.get('location'),
                                scouting_team_number=storage_team)
                    db.session.add(team)
                    result['teams_added'] += 1
                if event not in team.events:
                    try:
                        team.events.append(event)
                    except Exception:
                        pass
            print(f"  Manual alliance sync (alliance {alliance_id}): {result['teams_added']} teams added, {result['teams_updated']} updated")
        except Exception as e:
            print(f"  Error syncing teams for alliance {alliance_id}: {str(e)}")
        
        # Sync matches
        try:
            match_data_list = get_matches_with_alliance_fallback(event_code, alliance_id)
            
            for match_data in match_data_list:
                if not match_data:
                    continue
                match_number = match_data.get('match_number')
                match_type = match_data.get('match_type')
                if not match_number or not match_type:
                    continue
                match = Match.query.filter_by(event_id=event.id, match_number=match_number, match_type=match_type, scouting_team_number=storage_team).first()
                if match:
                    match.red_alliance = match_data.get('red_alliance', match.red_alliance)
                    match.blue_alliance = match_data.get('blue_alliance', match.blue_alliance)
                    match.winner = match_data.get('winner', match.winner)
                    match.red_score = match_data.get('red_score', match.red_score)
                    match.blue_score = match_data.get('blue_score', match.blue_score)
                    result['matches_updated'] += 1
                else:
                    match = Match(match_number=match_number,
                                  match_type=match_type,
                                  event_id=event.id,
                                  red_alliance=match_data.get('red_alliance'),
                                  blue_alliance=match_data.get('blue_alliance'),
                                  red_score=match_data.get('red_score'),
                                  blue_score=match_data.get('blue_score'),
                                  winner=match_data.get('winner'),
                                  scouting_team_number=storage_team)
                    db.session.add(match)
                    result['matches_added'] += 1
            print(f"  Manual alliance sync (alliance {alliance_id}): {result['matches_added']} matches added, {result['matches_updated']} updated")
        except Exception as e:
            print(f"  Error syncing matches for alliance {alliance_id}: {str(e)}")
        
        # Commit changes
        try:
            db.session.commit()
            try:
                from app.routes.data import merge_duplicate_events
                merge_duplicate_events(storage_team)
            except Exception:
                pass
            result['success'] = True
            result['message'] = f'Alliance sync complete: {result["teams_added"]} teams added, {result["teams_updated"]} updated, {result["matches_added"]} matches added, {result["matches_updated"]} updated'
        except Exception as e:
            db.session.rollback()
            result['message'] = f'Failed to commit changes: {str(e)}'
        
    except Exception as e:
        result['message'] = f'Error during alliance sync: {str(e)}'
        print(f"Error in perform_alliance_api_sync_for_alliance: {str(e)}")
    
    return result


def perform_periodic_alliance_api_sync():
    """Perform periodic API autosync for alliances that have a shared game config.

    This mirrors `api_data_sync_worker` behavior which runs per scouting team.
    We scope DB writes to the alliance's configured `game_config_team` or the
    first active member if not set. Uses existing `sync_status` helpers to
    determine desired interval and throttling.
    """
    try:
        with current_app.app_context():
            from app.utils.config_manager import load_game_config
            from app.utils.api_utils import (
                get_teams_with_alliance_fallback, get_matches_with_alliance_fallback, 
                get_event_details_with_alliance_fallback
            )
            from app.utils.sync_status import get_last_sync, update_last_sync, get_event_cache, set_event_cache
            from app.models import ScoutingAlliance, Event, Team, Match, db
            from sqlalchemy import func

            # Intervals (seconds) copied from the per-team logic
            RECENT_INTERVAL = 180
            UNKNOWN_DATE_INTERVAL = 20 * 60
            DAILY_INTERVAL = 24 * 60 * 60
            CHECK_EVENT_INTERVAL = 5 * 60

            alliances = ScoutingAlliance.query.filter_by(is_active=True).all()
            for alliance in alliances:
                try:
                    if not alliance.is_config_complete():
                        continue

                    # Load alliance game config (shared config takes precedence)
                    if alliance.shared_game_config:
                        try:
                            game_config = json.loads(alliance.shared_game_config)
                        except Exception:
                            game_config = load_game_config(team_number=alliance.game_config_team)
                    elif alliance.game_config_team:
                        game_config = load_game_config(team_number=alliance.game_config_team)
                    else:
                        continue

                    # Place the alliance config into current_app for downstream helpers
                    try:
                        current_app.config['GAME_CONFIG'] = game_config
                    except Exception:
                        pass

                    # Check api_settings.auto_sync_enabled (default True)
                    api_settings = game_config.get('api_settings') or {}
                    auto_sync_enabled = api_settings.get('auto_sync_enabled', True)
                    if not auto_sync_enabled:
                        continue

                    # Determine event_code
                    event_code = (game_config.get('current_event_code') or '').strip()
                    if not event_code:
                        # Nothing to sync
                        continue

                    # Use per-alliance cache key to avoid colliding with team caches
                    cache_key = f"alliance_{alliance.id}"
                    cached = get_event_cache(cache_key)
                    now_utc = datetime.now(timezone.utc)
                    use_cached_event = cached and (now_utc - cached.get('checked_at')).total_seconds() < CHECK_EVENT_INTERVAL and cached.get('event_code') == event_code

                    if use_cached_event and cached:
                        cached_start = cached.get('start_date')
                        if cached_start:
                            try:
                                if hasattr(cached_start, 'year') and not getattr(cached_start, 'tzinfo', None):
                                    cached_start_dt = datetime.combine(cached_start, datetime.min.time()).replace(tzinfo=timezone.utc)
                                else:
                                    cached_start_dt = cached_start if getattr(cached_start, 'tzinfo', None) else cached_start.replace(tzinfo=timezone.utc)

                                delta_seconds_cached = (cached_start_dt - now_utc).total_seconds()
                                threshold_seconds = 1.5 * 7 * 24 * 60 * 60
                                if abs(delta_seconds_cached) <= threshold_seconds:
                                    set_event_cache(cache_key, event_code, cached_start, RECENT_INTERVAL)
                                else:
                                    set_event_cache(cache_key, event_code, cached_start, DAILY_INTERVAL)
                            except Exception:
                                pass

                    if not event_code:
                        set_event_cache(cache_key, None, None, UNKNOWN_DATE_INTERVAL)
                        continue

                    # Determine the storage team number for this alliance
                    storage_team = alliance.game_config_team or (alliance.get_active_members()[0].team_number if alliance.get_active_members() else None)
                    if storage_team is None:
                        continue

                    # Ensure event exists under that storage team
                    event = Event.query.filter(
                        func.upper(Event.code) == event_code.upper(),
                        Event.scouting_team_number == storage_team
                    ).first()
                    if not event:
                        try:
                            # Use alliance fallback to get event details using any member's API if needed
                            event_details = get_event_details_with_alliance_fallback(event_code, alliance.id)
                            if event_details:
                                from app.routes.data import get_or_create_event
                                event = get_or_create_event(
                                    name=event_details.get('name', event_code),
                                    code=event_code,
                                    year=event_details.get('year', game_config.get('season', None) or game_config.get('year', 0)),
                                    location=event_details.get('location'),
                                    start_date=event_details.get('start_date'),
                                    end_date=event_details.get('end_date'),
                                    scouting_team_number=storage_team
                                )
                                if event_details.get('timezone') and not getattr(event, 'timezone', None):
                                    event.timezone = event_details.get('timezone')
                                    db.session.add(event)
                                db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            print(f"  Failed to create event {event_code} for alliance {alliance.id}: {e}")
                            continue

                    # Determine desired_interval via event date
                    desired_interval = RECENT_INTERVAL
                    try:
                        if 'use_cached_event' in locals() and use_cached_event and cached:
                            desired_interval = cached.get('desired_interval', RECENT_INTERVAL)
                        else:
                            if not getattr(event, 'start_date', None):
                                desired_interval = UNKNOWN_DATE_INTERVAL
                            else:
                                event_start_dt = datetime.combine(event.start_date, datetime.min.time()).replace(tzinfo=timezone.utc) if not getattr(event.start_date, 'tzinfo', None) else event.start_date
                                delta_seconds = (event_start_dt - now_utc).total_seconds()
                                threshold_seconds = 1.5 * 7 * 24 * 60 * 60
                                if abs(delta_seconds) <= threshold_seconds:
                                    desired_interval = RECENT_INTERVAL
                                else:
                                    desired_interval = DAILY_INTERVAL
                    except Exception:
                        desired_interval = RECENT_INTERVAL

                    set_event_cache(cache_key, event_code, getattr(event, 'start_date', None), desired_interval)

                    last = get_last_sync(cache_key)
                    if last:
                        seconds_since = (datetime.now(timezone.utc) - last).total_seconds()
                        if seconds_since < desired_interval:
                            continue

                    # --- Perform the actual sync for this alliance ---
                    # Use alliance fallback API functions that try member APIs if primary fails
                    try:
                        team_data_list = get_teams_with_alliance_fallback(event_code, alliance.id)
                        teams_added = 0
                        teams_updated = 0

                        for team_data in team_data_list:
                            if not team_data or not team_data.get('team_number'):
                                continue
                            team_number = team_data.get('team_number')
                            team = Team.query.filter_by(team_number=team_number, scouting_team_number=storage_team).first()
                            if team:
                                team.team_name = team_data.get('team_name', team.team_name)
                                team.location = team_data.get('location', team.location)
                                teams_updated += 1
                            else:
                                team = Team(team_number=team_number,
                                            team_name=team_data.get('team_name'),
                                            location=team_data.get('location'),
                                            scouting_team_number=storage_team)
                                db.session.add(team)
                                teams_added += 1
                            if event not in team.events:
                                try:
                                    team.events.append(event)
                                except Exception:
                                    pass
                        print(f"  Alliance teams sync (alliance {alliance.id}): {teams_added} added, {teams_updated} updated")
                    except Exception as e:
                        print(f"  Error syncing alliance teams for {alliance.id}: {str(e)}")

                    try:
                        match_data_list = get_matches_with_alliance_fallback(event_code, alliance.id)
                        matches_added = 0
                        matches_updated = 0
                        for match_data in match_data_list:
                            if not match_data:
                                continue
                            match_data['event_id'] = event.id
                            match_number = match_data.get('match_number')
                            match_type = match_data.get('match_type')
                            if not match_number or not match_type:
                                continue
                            match = Match.query.filter_by(event_id=event.id, match_number=match_number, match_type=match_type, scouting_team_number=storage_team).first()
                            if match:
                                match.red_alliance = match_data.get('red_alliance', match.red_alliance)
                                match.blue_alliance = match_data.get('blue_alliance', match.blue_alliance)
                                match.winner = match_data.get('winner', match.winner)
                                match.red_score = match_data.get('red_score', match.red_score)
                                match.blue_score = match_data.get('blue_score', match.blue_score)
                                matches_updated += 1
                            else:
                                match = Match(match_number=match_number,
                                              match_type=match_type,
                                              event_id=event.id,
                                              red_alliance=match_data.get('red_alliance'),
                                              blue_alliance=match_data.get('blue_alliance'),
                                              red_score=match_data.get('red_score'),
                                              blue_score=match_data.get('blue_score'),
                                              winner=match_data.get('winner'),
                                              scouting_team_number=storage_team)
                                db.session.add(match)
                                matches_added += 1
                        print(f"  Alliance matches sync (alliance {alliance.id}): {matches_added} added, {matches_updated} updated")
                    except Exception as e:
                        print(f"  Error syncing alliance matches for {alliance.id}: {str(e)}")

                    try:
                        db.session.commit()
                        try:
                            from app.routes.data import merge_duplicate_events
                            merge_duplicate_events(storage_team)
                        except Exception:
                            pass
                        update_last_sync(cache_key)
                    except Exception as e:
                        db.session.rollback()
                        print(f"  Failed to commit changes for alliance {alliance.id}: {e}")

                except Exception as e:
                    print(f"  Error processing alliance {alliance.id}: {e}")

    except Exception as e:
        print(f"Error in perform_periodic_alliance_api_sync: {str(e)}")


@bp.route('/api/<int:alliance_id>/member/<int:member_id>/promote', methods=['POST'])
@login_required
def api_promote_member(alliance_id, member_id):
    """Promote a member to admin role"""
    current_team = get_current_scouting_team_number()
    
    # Check if current user is admin of this alliance
    admin_member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not admin_member:
        return jsonify({'success': False, 'message': 'Only admins can promote members'}), 403
    
    # Get the member to promote
    member = ScoutingAllianceMember.query.get_or_404(member_id)
    
    if member.alliance_id != alliance_id:
        return jsonify({'success': False, 'message': 'Member not in this alliance'}), 400
    
    if member.role == 'admin':
        return jsonify({'success': False, 'message': 'Member is already an admin'}), 400
    
    # Promote the member
    member.role = 'admin'
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Team {member.team_number} promoted to admin'
    })


@bp.route('/api/<int:alliance_id>/member/<int:member_id>/demote', methods=['POST'])
@login_required
def api_demote_member(alliance_id, member_id):
    """Demote an admin to regular member"""
    current_team = get_current_scouting_team_number()
    
    # Check if current user is admin of this alliance
    admin_member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not admin_member:
        return jsonify({'success': False, 'message': 'Only admins can demote members'}), 403
    
    # Get the member to demote
    member = ScoutingAllianceMember.query.get_or_404(member_id)
    
    if member.alliance_id != alliance_id:
        return jsonify({'success': False, 'message': 'Member not in this alliance'}), 400
    
    if member.role != 'admin':
        return jsonify({'success': False, 'message': 'Member is not an admin'}), 400
    
    # Don't allow demoting yourself if you're the only admin
    admin_count = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        role='admin',
        status='accepted'
    ).count()
    
    if admin_count <= 1 and member.id == admin_member.id:
        return jsonify({'success': False, 'message': 'Cannot demote the only admin. Promote another member first.'}), 400
    
    # Demote the member
    member.role = 'member'
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Team {member.team_number} demoted to regular member'
    })


@bp.route('/api/<int:alliance_id>/member/<int:member_id>/remove', methods=['POST'])
@login_required
def api_remove_member(alliance_id, member_id):
    """Remove a member from the alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if current user is admin of this alliance
    admin_member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin'
    ).first()
    
    if not admin_member:
        return jsonify({'success': False, 'message': 'Only admins can remove members'}), 403
    
    # Get the member to remove
    member = ScoutingAllianceMember.query.get_or_404(member_id)
    
    if member.alliance_id != alliance_id:
        return jsonify({'success': False, 'message': 'Member not in this alliance'}), 400
    
    # Don't allow removing yourself if you're the only admin
    if member.role == 'admin':
        admin_count = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            role='admin',
            status='accepted'
        ).count()
        
        if admin_count <= 1 and member.id == admin_member.id:
            return jsonify({'success': False, 'message': 'Cannot remove the only admin. Promote another member first or delete the alliance.'}), 400
    
    team_number = member.team_number
    
    # Remove any active alliance status for this team
    TeamAllianceStatus.query.filter_by(
        team_number=team_number,
        active_alliance_id=alliance_id
    ).delete()
    
    # Remove the member
    db.session.delete(member)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Team {team_number} removed from alliance'
    })

# ======== ALLIANCE DATA COPY/DELETE MANAGEMENT ========

@bp.route('/api/share-data-to-alliance', methods=['POST'])
@login_required
def api_share_data_to_alliance():
    """Share scouting or pit data to alliance (creates a copy in shared tables)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        alliance_id = data.get('alliance_id')
        data_type = data.get('data_type')  # 'scouting' or 'pit'
        data_id = data.get('data_id')
        
        if not all([alliance_id, data_type, data_id]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        if data_type == 'scouting':
            # Get original scouting data
            original = ScoutingData.query.filter_by(
                id=data_id, 
                scouting_team_number=current_team
            ).first()
            
            if not original:
                return jsonify({'success': False, 'error': 'Scouting data not found'}), 404
            
            # Check if already shared
            existing = AllianceSharedScoutingData.query.filter_by(
                alliance_id=alliance_id,
                original_scouting_data_id=data_id
            ).first()
            
            if existing:
                return jsonify({'success': False, 'error': 'Data already shared to this alliance'}), 400
            
            # Create shared copy
            shared = AllianceSharedScoutingData.create_from_scouting_data(
                original, alliance_id, current_team
            )
            db.session.add(shared)
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Scouting data shared to alliance',
                'shared_id': shared.id
            })
        
        elif data_type == 'pit':
            # Get original pit data
            original = PitScoutingData.query.filter_by(
                id=data_id, 
                scouting_team_number=current_team
            ).first()
            
            if not original:
                return jsonify({'success': False, 'error': 'Pit data not found'}), 404
            
            # Check if already shared
            existing = AllianceSharedPitData.query.filter_by(
                alliance_id=alliance_id,
                original_pit_data_id=data_id
            ).first()
            
            if existing:
                return jsonify({'success': False, 'error': 'Data already shared to this alliance'}), 400
            
            # Create shared copy
            shared = AllianceSharedPitData.create_from_pit_data(
                original, alliance_id, current_team
            )
            db.session.add(shared)
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Pit data shared to alliance',
                'shared_id': shared.id
            })
        
        return jsonify({'success': False, 'error': 'Invalid data type'}), 400
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error sharing data to alliance: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/delete-from-alliance', methods=['POST'])
@login_required
def api_delete_from_alliance():
    """Delete shared data from alliance PERMANENTLY.
    
    Two modes:
    1. Original owner deletes their data - uses original_data_id
    2. Alliance admin deletes any data - uses shared_id
    
    When deleted:
    - Removes from AllianceSharedScoutingData/AllianceSharedPitData (the ONLY place alliance data lives)
    - Cleans up any legacy synced copies from members' ScoutingData/PitScoutingData (if they exist)
    - Marks the data as deleted to PREVENT RE-SYNC
    - Preserves the original team's private copy
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        data_type = data.get('data_type')  # 'scouting' or 'pit'
        original_data_id = data.get('original_data_id')
        shared_id = data.get('shared_id')  # Direct shared entry ID (for admin delete)
        alliance_id = data.get('alliance_id')
        
        if not data_type:
            return jsonify({'success': False, 'error': 'Missing data_type'}), 400
        
        if not shared_id and not original_data_id:
            return jsonify({'success': False, 'error': 'Missing shared_id or original_data_id'}), 400
        
        current_team = get_current_scouting_team_number()
        deleted_count = 0
        synced_copies_deleted = 0
        
        # Check if user is alliance admin (can delete any data)
        is_admin = False
        if alliance_id:
            member = ScoutingAllianceMember.query.filter_by(
                alliance_id=alliance_id,
                team_number=current_team,
                role='admin',
                status='accepted'
            ).first()
            is_admin = member is not None
        
        if data_type == 'scouting':
            shared_entry = None
            
            # If shared_id provided, use it directly (admin delete mode)
            if shared_id:
                shared_entry = AllianceSharedScoutingData.query.get(shared_id)
                if not shared_entry:
                    return jsonify({'success': False, 'error': 'Shared entry not found'}), 404
                
                # Only owner or admin can delete
                if shared_entry.source_scouting_team_number != current_team and not is_admin:
                    return jsonify({'success': False, 'error': 'Only the source team or alliance admin can delete this'}), 403
                
                # Get info for removing synced copies from other teams
                source_team = shared_entry.source_scouting_team_number
                match_id = shared_entry.match_id
                team_id = shared_entry.team_id
                alliance_color = shared_entry.alliance
                the_alliance_id = shared_entry.alliance_id
                
                # MARK AS DELETED to prevent re-sync
                AllianceDeletedData.mark_deleted(
                    alliance_id=the_alliance_id,
                    data_type='scouting',
                    match_id=match_id,
                    team_id=team_id,
                    alliance_color=alliance_color,
                    source_team=source_team,
                    deleted_by=current_team
                )
                
                # Get all alliance members to remove synced copies
                alliance = ScoutingAlliance.query.get(the_alliance_id)
                if alliance:
                    member_teams = [m.team_number for m in alliance.get_active_members()]
                    
                    # Remove synced copies from other teams' ScoutingData
                    # These are entries with scout_name starting with [Alliance-
                    for member_team in member_teams:
                        if member_team != source_team:
                            # Find and delete synced copies in this team's data
                            synced_copies = ScoutingData.query.filter(
                                ScoutingData.match_id == match_id,
                                ScoutingData.team_id == team_id,
                                ScoutingData.alliance == alliance_color,
                                ScoutingData.scouting_team_number == member_team,
                                ScoutingData.scout_name.like(f'[Alliance-{source_team}]%')
                            ).all()
                            
                            for copy in synced_copies:
                                db.session.delete(copy)
                                synced_copies_deleted += 1
                
                # Delete the shared entry
                db.session.delete(shared_entry)
                deleted_count += 1
            
            else:
                # Original mode: delete by original_data_id (owner only)
                query = AllianceSharedScoutingData.query.filter_by(
                    original_scouting_data_id=original_data_id,
                    source_scouting_team_number=current_team
                )
                
                if alliance_id:
                    query = query.filter_by(alliance_id=alliance_id)
                
                shared_entries = query.all()
                
                for entry in shared_entries:
                    # Mark as deleted to prevent re-sync
                    AllianceDeletedData.mark_deleted(
                        alliance_id=entry.alliance_id,
                        data_type='scouting',
                        match_id=entry.match_id,
                        team_id=entry.team_id,
                        alliance_color=entry.alliance,
                        source_team=entry.source_scouting_team_number,
                        deleted_by=current_team
                    )
                    
                    # Also remove synced copies from all alliance members (except source)
                    alliance = ScoutingAlliance.query.get(entry.alliance_id)
                    if alliance:
                        member_teams = [m.team_number for m in alliance.get_active_members()]
                        for member_team in member_teams:
                            if member_team != entry.source_scouting_team_number:
                                # Find and delete synced copies in this team's data
                                synced_copies = ScoutingData.query.filter(
                                    ScoutingData.match_id == entry.match_id,
                                    ScoutingData.team_id == entry.team_id,
                                    ScoutingData.alliance == entry.alliance,
                                    ScoutingData.scouting_team_number == member_team,
                                    ScoutingData.scout_name.like(f'[Alliance-{entry.source_scouting_team_number}]%')
                                ).all()
                                for copy in synced_copies:
                                    db.session.delete(copy)
                                    synced_copies_deleted += 1
                    
                    db.session.delete(entry)
                    deleted_count += 1
        
        elif data_type == 'pit':
            shared_entry = None
            
            # If shared_id provided, use it directly (admin delete mode)
            if shared_id:
                shared_entry = AllianceSharedPitData.query.get(shared_id)
                if not shared_entry:
                    return jsonify({'success': False, 'error': 'Shared entry not found'}), 404
                
                # Only owner or admin can delete
                if shared_entry.source_scouting_team_number != current_team and not is_admin:
                    return jsonify({'success': False, 'error': 'Only the source team or alliance admin can delete this'}), 403
                
                # Get info for removing synced copies from other teams
                source_team = shared_entry.source_scouting_team_number
                team_id = shared_entry.team_id
                the_alliance_id = shared_entry.alliance_id
                
                # MARK AS DELETED to prevent re-sync
                AllianceDeletedData.mark_deleted(
                    alliance_id=the_alliance_id,
                    data_type='pit',
                    match_id=None,
                    team_id=team_id,
                    alliance_color=None,
                    source_team=source_team,
                    deleted_by=current_team
                )
                
                # Get all alliance members to remove synced copies
                alliance = ScoutingAlliance.query.get(the_alliance_id)
                if alliance:
                    member_teams = [m.team_number for m in alliance.get_active_members()]
                    
                    # Remove synced copies from other teams' PitScoutingData
                    for member_team in member_teams:
                        if member_team != source_team:
                            # Find and delete synced copies in this team's data
                            synced_copies = PitScoutingData.query.filter(
                                PitScoutingData.team_id == team_id,
                                PitScoutingData.scouting_team_number == member_team,
                                PitScoutingData.scout_name.like(f'[Alliance-{source_team}]%')
                            ).all()
                            
                            for copy in synced_copies:
                                db.session.delete(copy)
                                synced_copies_deleted += 1
                
                # Delete the shared entry
                db.session.delete(shared_entry)
                deleted_count += 1
            
            else:
                # Original mode: delete by original_pit_data_id (owner only)
                query = AllianceSharedPitData.query.filter_by(
                    original_pit_data_id=original_data_id,
                    source_scouting_team_number=current_team
                )
                
                if alliance_id:
                    query = query.filter_by(alliance_id=alliance_id)
                
                shared_entries = query.all()
                
                for entry in shared_entries:
                    # Mark as deleted to prevent re-sync
                    AllianceDeletedData.mark_deleted(
                        alliance_id=entry.alliance_id,
                        data_type='pit',
                        match_id=None,
                        team_id=entry.team_id,
                        alliance_color=None,
                        source_team=entry.source_scouting_team_number,
                        deleted_by=current_team
                    )
                    
                    # Also remove synced copies from all alliance members (except source)
                    alliance = ScoutingAlliance.query.get(entry.alliance_id)
                    if alliance:
                        member_teams = [m.team_number for m in alliance.get_active_members()]
                        for member_team in member_teams:
                            if member_team != entry.source_scouting_team_number:
                                # Find and delete synced copies in this team's data
                                synced_copies = PitScoutingData.query.filter(
                                    PitScoutingData.team_id == entry.team_id,
                                    PitScoutingData.scouting_team_number == member_team,
                                    PitScoutingData.scout_name.like(f'[Alliance-{entry.source_scouting_team_number}]%')
                                ).all()
                                for copy in synced_copies:
                                    db.session.delete(copy)
                                    synced_copies_deleted += 1
                    
                    db.session.delete(entry)
                    deleted_count += 1
        else:
            return jsonify({'success': False, 'error': 'Invalid data type'}), 400
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Permanently deleted {deleted_count} shared entries and {synced_copies_deleted} synced copies',
            'deleted_count': deleted_count,
            'synced_copies_deleted': synced_copies_deleted
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting from alliance: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/check-alliance-shared-data', methods=['POST'])
@login_required
def api_check_alliance_shared_data():
    """Check if scouting/pit data is shared to any alliances (for showing delete from alliance option)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        data_type = data.get('data_type')  # 'scouting' or 'pit'
        data_id = data.get('data_id')
        
        if not all([data_type, data_id]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        current_team = get_current_scouting_team_number()
        shared_alliances = []
        
        if data_type == 'scouting':
            # Find all alliances this data is shared to
            shared_entries = AllianceSharedScoutingData.query.filter_by(
                original_scouting_data_id=data_id,
                source_scouting_team_number=current_team,
                is_active=True
            ).all()
            
            for entry in shared_entries:
                alliance = ScoutingAlliance.query.get(entry.alliance_id)
                if alliance:
                    shared_alliances.append({
                        'alliance_id': alliance.id,
                        'alliance_name': alliance.alliance_name,
                        'shared_at': entry.shared_at.isoformat() if entry.shared_at else None
                    })
        
        elif data_type == 'pit':
            # Find all alliances this data is shared to
            shared_entries = AllianceSharedPitData.query.filter_by(
                original_pit_data_id=data_id,
                source_scouting_team_number=current_team,
                is_active=True
            ).all()
            
            for entry in shared_entries:
                alliance = ScoutingAlliance.query.get(entry.alliance_id)
                if alliance:
                    shared_alliances.append({
                        'alliance_id': alliance.id,
                        'alliance_name': alliance.alliance_name,
                        'shared_at': entry.shared_at.isoformat() if entry.shared_at else None
                    })
        else:
            return jsonify({'success': False, 'error': 'Invalid data type'}), 400
        
        # Also check if current team is in any active alliance
        team_alliances = db.session.query(ScoutingAlliance).join(ScoutingAllianceMember).filter(
            ScoutingAllianceMember.team_number == current_team,
            ScoutingAllianceMember.status == 'accepted',
            ScoutingAlliance.is_active == True
        ).all()
        
        return jsonify({
            'success': True,
            'is_shared': len(shared_alliances) > 0,
            'shared_alliances': shared_alliances,
            'team_alliances': [{'id': a.id, 'name': a.alliance_name} for a in team_alliances],
            'is_own_data': True  # Always true since we filter by current team
        })
        
    except Exception as e:
        current_app.logger.error(f"Error checking alliance shared data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/deactivate-alliance-with-data', methods=['POST'])
@login_required
def api_deactivate_alliance_with_data():
    """Deactivate alliance mode and optionally remove team's data from alliance.
    
    Default behavior is to KEEP data in alliance for other teams to access.
    User can explicitly choose to remove their data from the alliance.
    When removing, shared copies are deleted but the team's private data is preserved.
    Any alliance data not already in the team's private storage will be copied back.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        alliance_id = data.get('alliance_id')
        remove_data = data.get('remove_data', False)  # Default to False (keep data)
        
        if not alliance_id:
            return jsonify({'success': False, 'error': 'Alliance ID required'}), 400
        
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Set data sharing to inactive for this team (prevents future syncs from getting this team's data)
        member.is_data_sharing_active = False
        member.data_sharing_deactivated_at = datetime.now(timezone.utc)
        
        # Deactivate alliance mode
        TeamAllianceStatus.deactivate_alliance_for_team(current_team)
        
        shared_scouting_deleted = 0
        shared_pit_deleted = 0
        data_moved_to_private = 0
        
        if remove_data:
            # STEP 1: Move alliance shared data to private team data before deleting shared copies
            # This preserves the team's data privately while removing it from the alliance
            
            # Get all shared scouting data from this team
            shared_scouting_entries = AllianceSharedScoutingData.query.filter_by(
                alliance_id=alliance_id,
                source_scouting_team_number=current_team
            ).all()
            
            for entry in shared_scouting_entries:
                # Check if this data already exists in the team's private ScoutingData
                existing_private = ScoutingData.query.filter_by(
                    match_id=entry.match_id,
                    team_id=entry.team_id,
                    alliance=entry.alliance,
                    scouting_team_number=current_team
                ).first()
                
                if not existing_private:
                    # Create a private copy of the data
                    private_copy = ScoutingData(
                        match_id=entry.match_id,
                        team_id=entry.team_id,
                        scouting_team_number=current_team,
                        scout_name=entry.scout_name,
                        scout_id=entry.scout_id,
                        scouting_station=entry.scouting_station,
                        alliance=entry.alliance,
                        data_json=entry.data_json,
                        timestamp=entry.timestamp
                    )
                    db.session.add(private_copy)
                    data_moved_to_private += 1
                
                # Delete the shared copy
                db.session.delete(entry)
                shared_scouting_deleted += 1
            
            # Get all shared pit data from this team
            shared_pit_entries = AllianceSharedPitData.query.filter_by(
                alliance_id=alliance_id,
                source_scouting_team_number=current_team
            ).all()
            
            for entry in shared_pit_entries:
                # Check if this data already exists in the team's private PitScoutingData
                existing_private = PitScoutingData.query.filter_by(
                    team_id=entry.team_id,
                    scouting_team_number=current_team
                ).first()
                
                if not existing_private:
                    # Create a private copy of the data
                    private_copy = PitScoutingData(
                        team_id=entry.team_id,
                        event_id=entry.event_id,
                        scouting_team_number=current_team,
                        scout_name=entry.scout_name,
                        scout_id=entry.scout_id,
                        data_json=entry.data_json,
                        timestamp=entry.timestamp,
                        local_id=str(uuid.uuid4())
                    )
                    db.session.add(private_copy)
                    data_moved_to_private += 1
                
                # Delete the shared copy
                db.session.delete(entry)
                shared_pit_deleted += 1
            
            db.session.commit()
            
            message = f'Alliance mode deactivated. Removed {shared_scouting_deleted + shared_pit_deleted} entries from alliance. {data_moved_to_private} entries preserved as private team data.'
        else:
            db.session.commit()
            message = 'Alliance mode deactivated. Your existing shared data remains in the alliance, but future syncs will not get new data from your team.'
        
        return jsonify({
            'success': True,
            'message': message,
            'shared_data_removed': shared_scouting_deleted + shared_pit_deleted,
            'data_moved_to_private': data_moved_to_private,
            'data_kept_in_alliance': not remove_data
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deactivating alliance: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/copy-alliance-data-to-team', methods=['POST'])
@login_required
def api_copy_alliance_data_to_team():
    """Copy all alliance data (from all member teams) to the current team's local storage.
    
    This allows a team to request a copy of all alliance data before disabling alliance mode.
    The data is copied to the team's private ScoutingData and PitScoutingData tables.
    Data from other teams is prefixed with [Alliance-TEAM#] in the scout_name field.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        alliance_id = data.get('alliance_id')
        
        if not alliance_id:
            return jsonify({'success': False, 'error': 'Alliance ID required'}), 400
        
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Use the utility function to copy all alliance data
        from app.utils.alliance_data import copy_alliance_data_to_team
        stats = copy_alliance_data_to_team(alliance_id, current_team)
        
        total_copied = stats['scouting_copied'] + stats['pit_copied']
        total_skipped = stats['scouting_skipped'] + stats['pit_skipped']
        
        message = f'Copied {total_copied} entries to your team data. {total_skipped} entries already existed.'
        if stats['errors']:
            message += f' {len(stats["errors"])} errors occurred.'
        
        return jsonify({
            'success': True,
            'message': message,
            'scouting_copied': stats['scouting_copied'],
            'scouting_skipped': stats['scouting_skipped'],
            'pit_copied': stats['pit_copied'],
            'pit_skipped': stats['pit_skipped'],
            'errors': stats['errors'][:10] if stats['errors'] else []  # Limit errors in response
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error copying alliance data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/copy-all-data', methods=['POST'])
@login_required
def api_copy_all_alliance_data(alliance_id):
    """Copy all alliance data (from all member teams) to the current team's local storage.
    
    This is an alternative to /api/copy-alliance-data-to-team that accepts alliance_id in the URL.
    """
    try:
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Use the utility function to copy all alliance data
        from app.utils.alliance_data import copy_alliance_data_to_team
        stats = copy_alliance_data_to_team(alliance_id, current_team)
        
        total_copied = stats['scouting_copied'] + stats['pit_copied']
        total_skipped = stats['scouting_skipped'] + stats['pit_skipped']
        
        message = f'Copied {total_copied} entries to your team data. {total_skipped} entries already existed.'
        if stats['errors']:
            message += f' {len(stats["errors"])} errors occurred.'
        
        return jsonify({
            'success': True,
            'message': message,
            'scouting_copied': stats['scouting_copied'],
            'scouting_skipped': stats['scouting_skipped'],
            'pit_copied': stats['pit_copied'],
            'pit_skipped': stats['pit_skipped'],
            'errors': stats['errors'][:10] if stats['errors'] else []  # Limit errors in response
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error copying all alliance data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/copy-my-data', methods=['POST'])
@login_required
def api_copy_my_alliance_data(alliance_id):
    """Copy only the current team's data from the alliance shared tables back to local storage.
    
    This allows a team to retrieve only data they contributed when disabling alliance mode,
    without keeping data from other alliance members.
    """
    try:
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Use the utility function to copy only this team's data from the alliance
        from app.utils.alliance_data import copy_my_team_alliance_data
        stats = copy_my_team_alliance_data(alliance_id, current_team)
        
        total_copied = stats['scouting_copied'] + stats['pit_copied']
        total_skipped = stats['scouting_skipped'] + stats['pit_skipped']
        
        message = f'Copied {total_copied} of your team\'s entries back to local storage. {total_skipped} entries already existed.'
        if stats['errors']:
            message += f' {len(stats["errors"])} errors occurred.'
        
        return jsonify({
            'success': True,
            'message': message,
            'scouting_copied': stats['scouting_copied'],
            'scouting_skipped': stats['scouting_skipped'],
            'pit_copied': stats['pit_copied'],
            'pit_skipped': stats['pit_skipped'],
            'errors': stats['errors'][:10] if stats['errors'] else []  # Limit errors in response
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error copying team's alliance data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/<int:alliance_id>/team-data-counts', methods=['GET'])
@login_required
def api_get_team_data_counts(alliance_id):
    """Get counts of scouting/pit data for current team in a specific alliance"""
    try:
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Get the alliance to find the game_config_team (the team whose data is stored)
        alliance = ScoutingAlliance.query.get(alliance_id)
        if not alliance:
            return jsonify({'success': False, 'error': 'Alliance not found'}), 404
        
        # Count scouting data shared TO the alliance (AllianceSharedScoutingData)
        shared_scouting_count = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            source_scouting_team_number=current_team,
            is_active=True
        ).count()
        
        # Count pit data shared TO the alliance (AllianceSharedPitData)
        shared_pit_count = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            source_scouting_team_number=current_team,
            is_active=True
        ).count()
        
        # Also count the team's actual scouting data (ScoutingData and PitScoutingData)
        # This is the data that would be deleted when deactivating
        actual_scouting_count = ScoutingData.query.filter_by(
            scouting_team_number=current_team
        ).count()
        
        actual_pit_count = PitScoutingData.query.filter_by(
            scouting_team_number=current_team
        ).count()
        
        return jsonify({
            'success': True,
            'match_data_count': shared_scouting_count,  # Shared to alliance
            'pit_data_count': shared_pit_count,          # Shared to alliance
            'actual_match_data_count': actual_scouting_count,  # Team's own data
            'actual_pit_data_count': actual_pit_count,         # Team's own data
            'total_shared': shared_scouting_count + shared_pit_count,
            'total_actual': actual_scouting_count + actual_pit_count
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting team data counts: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/<int:alliance_id>/shared-data', methods=['GET'])
@login_required
def api_get_alliance_shared_data(alliance_id):
    """Get all shared data for an alliance that the current team can access"""
    try:
        current_team = get_current_scouting_team_number()
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Get all active shared scouting data
        scouting_data = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        ).all()
        
        # Get all active shared pit data
        pit_data = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        ).all()
        
        return jsonify({
            'success': True,
            'scouting_data': [d.to_dict() for d in scouting_data],
            'pit_data': [d.to_dict() for d in pit_data],
            'is_admin': member.role == 'admin'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting alliance shared data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/<int:alliance_id>/edit-shared-data', methods=['POST'])
@login_required
def api_edit_alliance_shared_data(alliance_id):
    """Edit shared data in alliance (alliance admins only).
    
    Edits propagate to all teams EXCEPT the original scout by default.
    Optionally can include the original scout's copy.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        current_team = get_current_scouting_team_number()
        
        # Verify user is admin of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team,
            role='admin',
            status='accepted'
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Only alliance admins can edit shared data'}), 403
        
        data_type = data.get('data_type')  # 'scouting' or 'pit'
        shared_id = data.get('shared_id')
        new_data = data.get('new_data')  # The updated data fields
        include_original = data.get('include_original', False)  # Whether to update original team's copy too
        
        if not all([data_type, shared_id, new_data]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        if data_type == 'scouting':
            shared = AllianceSharedScoutingData.query.filter_by(
                id=shared_id,
                alliance_id=alliance_id
            ).first()
            
            if not shared:
                return jsonify({'success': False, 'error': 'Shared data not found'}), 404
            
            # Update the shared data
            shared.data = new_data
            shared.last_edited_by_team = current_team
            shared.last_edited_at = datetime.now(timezone.utc)
            
            # Optionally update the original if requested
            if include_original and shared.original_scouting_data_id:
                original = ScoutingData.query.get(shared.original_scouting_data_id)
                if original:
                    original.data = new_data
        
        elif data_type == 'pit':
            shared = AllianceSharedPitData.query.filter_by(
                id=shared_id,
                alliance_id=alliance_id
            ).first()
            
            if not shared:
                return jsonify({'success': False, 'error': 'Shared data not found'}), 404
            
            # Update the shared data
            shared.data = new_data
            shared.last_edited_by_team = current_team
            shared.last_edited_at = datetime.now(timezone.utc)
            
            # Optionally update the original if requested
            if include_original and shared.original_pit_data_id:
                original = PitScoutingData.query.get(shared.original_pit_data_id)
                if original:
                    original.data = new_data
        else:
            return jsonify({'success': False, 'error': 'Invalid data type'}), 400
        
        db.session.commit()
        
        # Notify alliance members of the edit
        socketio.emit('alliance_data_edited', {
            'alliance_id': alliance_id,
            'data_type': data_type,
            'shared_id': shared_id,
            'edited_by_team': current_team,
            'include_original': include_original
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'message': 'Shared data updated successfully',
            'include_original': include_original
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error editing alliance shared data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/get-team-alliance-data-counts', methods=['GET'])
@login_required
def api_get_team_alliance_data_counts():
    """Get counts of data this team has shared to various alliances"""
    try:
        current_team = get_current_scouting_team_number()
        
        # Get all alliances this team is in
        team_alliances = db.session.query(ScoutingAlliance).join(ScoutingAllianceMember).filter(
            ScoutingAllianceMember.team_number == current_team,
            ScoutingAllianceMember.status == 'accepted'
        ).all()
        
        result = []
        for alliance in team_alliances:
            scouting_count = AllianceSharedScoutingData.query.filter_by(
                alliance_id=alliance.id,
                source_scouting_team_number=current_team,
                is_active=True
            ).count()
            
            pit_count = AllianceSharedPitData.query.filter_by(
                alliance_id=alliance.id,
                source_scouting_team_number=current_team,
                is_active=True
            ).count()
            
            result.append({
                'alliance_id': alliance.id,
                'alliance_name': alliance.alliance_name,
                'scouting_data_count': scouting_count,
                'pit_data_count': pit_count,
                'total_count': scouting_count + pit_count
            })
        
        return jsonify({
            'success': True,
            'alliance_data': result,
            'total_alliances': len(result)
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting team alliance data counts: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ======== ALLIANCE TEAMS & EVENTS MANAGEMENT ========

@bp.route('/<int:alliance_id>/manage/teams')
@login_required
@admin_required
def manage_alliance_teams(alliance_id):
    """Manage teams for alliance - centralized team data that propagates to all members"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to manage alliance teams.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    # Get the alliance's storage team number (game_config_team)
    storage_team = alliance.game_config_team
    if not storage_team:
        flash('Alliance must have a game configuration set before managing teams.', 'warning')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    # Get alliance events to filter teams
    alliance_events = alliance.get_shared_events()
    
    # Get events for the alliance
    events = []
    selected_event = None
    event_id = request.args.get('event_id', type=int)
    
    if alliance_events:
        # Filter to alliance events only - mark them as alliance events
        events = Event.query.filter(
            Event.code.in_(alliance_events),
            Event.scouting_team_number == storage_team
        ).all()
        
        if event_id:
            selected_event = Event.query.filter_by(id=event_id, scouting_team_number=storage_team).first()
        elif events:
            # Use first alliance event as default
            selected_event = events[0]
    
    # Get teams for the selected event, filtered by alliance storage team
    teams = []
    if selected_event:
        teams = Team.query.join(Team.events).filter(
            Event.id == selected_event.id,
            Team.scouting_team_number == storage_team
        ).order_by(Team.team_number).all()
    
    # Get effective game config for event code
    from app.utils.config_manager import get_effective_game_config
    game_config = get_effective_game_config()
    
    return render_template('scouting_alliances/manage_teams.html',
                           alliance=alliance,
                           member=member,
                           teams=teams,
                           events=events,
                           selected_event=selected_event,
                           game_config=game_config,
                           current_team=current_team,
                           **get_theme_context())


@bp.route('/<int:alliance_id>/manage/teams/sync', methods=['POST'])
@login_required
@admin_required
def sync_alliance_teams(alliance_id):
    """Sync teams from FIRST API for alliance - stores under alliance's storage team"""
    from app.utils.api_utils import get_teams_dual_api, api_to_db_team_conversion, get_event_details_dual_api
    from app.routes.data import get_or_create_event
    
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    storage_team = alliance.game_config_team
    
    if not storage_team:
        return jsonify({'success': False, 'error': 'Alliance must have a game configuration set'}), 400
    
    data = request.get_json()
    event_code = data.get('event_code')
    
    if not event_code:
        return jsonify({'success': False, 'error': 'Event code is required'}), 400
    
    try:
        # Get or create event under alliance's storage team
        event = Event.query.filter_by(
            code=event_code.upper(),
            scouting_team_number=storage_team
        ).first()
        
        if not event:
            try:
                event_details = get_event_details_dual_api(event_code)
                from datetime import datetime
                
                start_date = None
                end_date = None
                if event_details.get('dateStart'):
                    try:
                        start_date = datetime.fromisoformat(event_details['dateStart'].replace('Z', '+00:00')).date()
                    except:
                        pass
                if event_details.get('dateEnd'):
                    try:
                        end_date = datetime.fromisoformat(event_details['dateEnd'].replace('Z', '+00:00')).date()
                    except:
                        pass
                
                event = Event(
                    name=event_details.get('name', f'Event {event_code}'),
                    code=event_code.upper(),
                    year=event_details.get('year', datetime.now().year),
                    location=event_details.get('venue', ''),
                    start_date=start_date,
                    end_date=end_date,
                    scouting_team_number=storage_team,
                    is_alliance=True  # Mark as alliance event
                )
                db.session.add(event)
                db.session.flush()
            except Exception as e:
                # Create minimal event
                event = Event(
                    name=f'Event {event_code}',
                    code=event_code.upper(),
                    year=datetime.now().year,
                    scouting_team_number=storage_team,
                    is_alliance=True
                )
                db.session.add(event)
                db.session.flush()
        
        # Fetch teams from API
        api_teams = get_teams_dual_api(event_code)
        
        teams_added = 0
        teams_updated = 0
        
        for api_team in api_teams:
            team_number = api_team.get('teamNumber')
            if not team_number:
                continue
            
            # Check if team exists for this scouting team
            team = Team.query.filter_by(
                team_number=team_number,
                scouting_team_number=storage_team
            ).first()
            
            if not team:
                # Create new team
                team = Team(
                    team_number=team_number,
                    team_name=api_team.get('nameShort') or api_team.get('nameFull') or f'Team {team_number}',
                    location=f"{api_team.get('city', '')}, {api_team.get('stateProv', '')}, {api_team.get('country', '')}".strip(', '),
                    scouting_team_number=storage_team
                )
                db.session.add(team)
                teams_added += 1
            else:
                # Update existing team
                team.team_name = api_team.get('nameShort') or api_team.get('nameFull') or team.team_name
                teams_updated += 1
            
            # Associate team with event
            if event not in team.events:
                team.events.append(event)
        
        # Add event to alliance events if not already there
        alliance_event = ScoutingAllianceEvent.query.filter_by(
            alliance_id=alliance_id,
            event_code=event_code.upper()
        ).first()
        
        if not alliance_event:
            alliance_event = ScoutingAllianceEvent(
                alliance_id=alliance_id,
                event_code=event_code.upper(),
                event_name=event.name,
                added_by=current_team,
                is_active=True
            )
            db.session.add(alliance_event)
        
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_teams_synced', {
            'alliance_id': alliance_id,
            'event_code': event_code,
            'teams_added': teams_added,
            'teams_updated': teams_updated,
            'synced_by': current_team
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'teams_added': teams_added,
            'teams_updated': teams_updated,
            'total_teams': len(api_teams),
            'message': f'Synced {len(api_teams)} teams ({teams_added} new, {teams_updated} updated)'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error syncing alliance teams: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/manage/teams/add', methods=['POST'])
@login_required
@admin_required
def add_alliance_team(alliance_id):
    """Add a team manually to alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    storage_team = alliance.game_config_team
    
    if not storage_team:
        return jsonify({'success': False, 'error': 'Alliance must have a game configuration set'}), 400
    
    data = request.get_json()
    team_number = data.get('team_number')
    team_name = data.get('team_name', f'Team {team_number}')
    event_id = data.get('event_id')
    
    if not team_number:
        return jsonify({'success': False, 'error': 'Team number is required'}), 400
    
    try:
        # Check if team already exists
        team = Team.query.filter_by(
            team_number=team_number,
            scouting_team_number=storage_team
        ).first()
        
        if not team:
            team = Team(
                team_number=team_number,
                team_name=team_name,
                scouting_team_number=storage_team
            )
            db.session.add(team)
        
        # Associate with event if provided
        if event_id:
            event = Event.query.filter_by(id=event_id, scouting_team_number=storage_team).first()
            if event and event not in team.events:
                team.events.append(event)
        
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_team_added', {
            'alliance_id': alliance_id,
            'team_number': team_number,
            'team_name': team_name,
            'added_by': current_team
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'message': f'Team {team_number} added successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding alliance team: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/manage/events')
@login_required
@admin_required
def manage_alliance_events(alliance_id):
    """Manage events for alliance - centralized event data that propagates to all members"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to manage alliance events.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    # Get the alliance's storage team number (game_config_team)
    storage_team = alliance.game_config_team
    
    # Get alliance event codes
    alliance_event_codes = alliance.get_shared_events()
    
    # Get Event objects for alliance
    events = []
    if storage_team and alliance_event_codes:
        events = Event.query.filter(
            Event.code.in_(alliance_event_codes),
            Event.scouting_team_number == storage_team
        ).order_by(Event.start_date.desc()).all()
    
    # Get ScoutingAllianceEvent records
    alliance_events = ScoutingAllianceEvent.query.filter_by(
        alliance_id=alliance_id,
        is_active=True
    ).all()
    
    # Get effective game config for event code
    from app.utils.config_manager import get_effective_game_config
    game_config = get_effective_game_config()
    
    return render_template('scouting_alliances/manage_events.html',
                           alliance=alliance,
                           member=member,
                           events=events,
                           alliance_events=alliance_events,
                           game_config=game_config,
                           current_team=current_team,
                           **get_theme_context())


@bp.route('/<int:alliance_id>/manage/events/add', methods=['POST'])
@login_required
@admin_required
def add_alliance_event(alliance_id):
    """Add an event to alliance"""
    from app.utils.api_utils import get_event_details_dual_api
    
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    storage_team = alliance.game_config_team
    
    if not storage_team:
        return jsonify({'success': False, 'error': 'Alliance must have a game configuration set first'}), 400
    
    data = request.get_json()
    event_code = data.get('event_code')
    
    if not event_code:
        return jsonify({'success': False, 'error': 'Event code is required'}), 400
    
    event_code = event_code.upper()
    
    try:
        # Check if alliance event already exists
        existing = ScoutingAllianceEvent.query.filter_by(
            alliance_id=alliance_id,
            event_code=event_code
        ).first()
        
        if existing:
            if existing.is_active:
                return jsonify({'success': False, 'error': 'Event already added to alliance'}), 400
            else:
                # Reactivate
                existing.is_active = True
                db.session.commit()
                return jsonify({'success': True, 'message': 'Event reactivated'})
        
        # Try to get event details from API
        event_name = f'Event {event_code}'
        try:
            event_details = get_event_details_dual_api(event_code)
            event_name = event_details.get('name', event_name)
            
            # Create or get the event in the database under alliance's storage team
            event = Event.query.filter_by(
                code=event_code,
                scouting_team_number=storage_team
            ).first()
            
            if not event:
                from datetime import datetime
                start_date = None
                end_date = None
                if event_details.get('dateStart'):
                    try:
                        start_date = datetime.fromisoformat(event_details['dateStart'].replace('Z', '+00:00')).date()
                    except:
                        pass
                if event_details.get('dateEnd'):
                    try:
                        end_date = datetime.fromisoformat(event_details['dateEnd'].replace('Z', '+00:00')).date()
                    except:
                        pass
                
                event = Event(
                    name=event_name,
                    code=event_code,
                    year=event_details.get('year', datetime.now().year),
                    location=event_details.get('venue', ''),
                    start_date=start_date,
                    end_date=end_date,
                    scouting_team_number=storage_team,
                    is_alliance=True
                )
                db.session.add(event)
        except:
            pass  # API failed, just create alliance event with code
        
        # Create alliance event record
        alliance_event = ScoutingAllianceEvent(
            alliance_id=alliance_id,
            event_code=event_code,
            event_name=event_name,
            added_by=current_team,
            is_active=True
        )
        db.session.add(alliance_event)
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_event_added', {
            'alliance_id': alliance_id,
            'event_code': event_code,
            'event_name': event_name,
            'added_by': current_team
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'event_code': event_code,
            'event_name': event_name,
            'message': f'Event {event_code} added to alliance'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding alliance event: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/manage/events/<event_code>/remove', methods=['POST'])
@login_required
@admin_required
def remove_alliance_event(alliance_id, event_code):
    """Remove an event from alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        alliance_event = ScoutingAllianceEvent.query.filter_by(
            alliance_id=alliance_id,
            event_code=event_code.upper()
        ).first()
        
        if not alliance_event:
            return jsonify({'success': False, 'error': 'Event not found in alliance'}), 404
        
        # Mark as inactive instead of deleting (to preserve history)
        alliance_event.is_active = False
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_event_removed', {
            'alliance_id': alliance_id,
            'event_code': event_code,
            'removed_by': current_team
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'message': f'Event {event_code} removed from alliance'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error removing alliance event: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/manage/matches')
@login_required
@admin_required
def manage_alliance_matches(alliance_id):
    """Manage matches for alliance - centralized match data that propagates to all members"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        flash('You must be an alliance admin to manage alliance matches.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    # Get the alliance's storage team number (game_config_team)
    storage_team = alliance.game_config_team
    if not storage_team:
        flash('Alliance must have a game configuration set before managing matches.', 'warning')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    # Get alliance events to filter matches
    alliance_events = alliance.get_shared_events()
    
    # Get events for the alliance
    events = []
    selected_event = None
    event_id = request.args.get('event_id', type=int)
    
    if alliance_events:
        events = Event.query.filter(
            Event.code.in_(alliance_events),
            Event.scouting_team_number == storage_team
        ).all()
        
        if event_id:
            selected_event = Event.query.filter_by(id=event_id, scouting_team_number=storage_team).first()
        elif events:
            selected_event = events[0]
    
    # Get matches for the selected event
    matches = []
    if selected_event:
        matches = Match.query.filter_by(
            event_id=selected_event.id
        ).order_by(Match.match_type, Match.match_number).all()
    
    # Get effective game config for event code
    from app.utils.config_manager import get_effective_game_config
    game_config = get_effective_game_config()
    
    return render_template('scouting_alliances/manage_matches.html',
                           alliance=alliance,
                           member=member,
                           matches=matches,
                           events=events,
                           selected_event=selected_event,
                           game_config=game_config,
                           current_team=current_team,
                           **get_theme_context())


@bp.route('/<int:alliance_id>/manage/matches/sync', methods=['POST'])
@login_required
@admin_required
def sync_alliance_matches(alliance_id):
    """Sync matches from FIRST API for alliance - stores under alliance's storage team"""
    from app.utils.api_utils import get_event_matches_dual_api
    
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    storage_team = alliance.game_config_team
    
    if not storage_team:
        return jsonify({'success': False, 'error': 'Alliance must have a game configuration set'}), 400
    
    data = request.get_json()
    event_code = data.get('event_code')
    
    if not event_code:
        return jsonify({'success': False, 'error': 'Event code is required'}), 400
    
    try:
        # Get the event
        event = Event.query.filter_by(
            code=event_code.upper(),
            scouting_team_number=storage_team
        ).first()
        
        if not event:
            return jsonify({'success': False, 'error': 'Event not found. Please add the event first.'}), 404
        
        # Fetch matches from API
        api_matches = get_event_matches_dual_api(event_code)
        
        matches_added = 0
        matches_updated = 0
        
        for api_match in api_matches:
            match_number = api_match.get('matchNumber')
            match_type = api_match.get('description', 'Qualification')
            
            # Normalize match type
            if 'qualification' in match_type.lower() or 'qual' in match_type.lower():
                match_type = 'Qualification'
            elif 'playoff' in match_type.lower() or 'elim' in match_type.lower():
                match_type = 'Playoff'
            elif 'practice' in match_type.lower():
                match_type = 'Practice'
            
            # Check if match already exists
            match = Match.query.filter_by(
                event_id=event.id,
                match_number=match_number,
                match_type=match_type
            ).first()
            
            # Get teams
            red_teams = []
            blue_teams = []
            
            for team in api_match.get('teams', []):
                team_number = team.get('teamNumber')
                station = team.get('station', '')
                
                if 'Red' in station:
                    red_teams.append(str(team_number))
                elif 'Blue' in station:
                    blue_teams.append(str(team_number))
            
            red_alliance = ','.join(red_teams)
            blue_alliance = ','.join(blue_teams)
            
            # Parse scheduled time
            scheduled_time = None
            if api_match.get('startTime'):
                try:
                    from datetime import datetime
                    scheduled_time = datetime.fromisoformat(api_match['startTime'].replace('Z', '+00:00'))
                except:
                    pass
            
            if not match:
                match = Match(
                    event_id=event.id,
                    match_number=match_number,
                    match_type=match_type,
                    red_alliance=red_alliance,
                    blue_alliance=blue_alliance,
                    scheduled_time=scheduled_time
                )
                db.session.add(match)
                matches_added += 1
            else:
                # Update existing match
                match.red_alliance = red_alliance
                match.blue_alliance = blue_alliance
                if scheduled_time:
                    match.scheduled_time = scheduled_time
                matches_updated += 1
        
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_matches_synced', {
            'alliance_id': alliance_id,
            'event_code': event_code,
            'matches_added': matches_added,
            'matches_updated': matches_updated,
            'synced_by': current_team
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'matches_added': matches_added,
            'matches_updated': matches_updated,
            'total_matches': len(api_matches),
            'message': f'Synced {len(api_matches)} matches ({matches_added} new, {matches_updated} updated)'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error syncing alliance matches: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/manage/teams/<int:team_number>/delete', methods=['POST'])
@login_required
@admin_required
def delete_alliance_team(alliance_id, team_number):
    """Remove a team from the alliance's event"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    storage_team = alliance.game_config_team
    
    if not storage_team:
        return jsonify({'success': False, 'error': 'Alliance must have a game configuration set'}), 400
    
    data = request.get_json() or {}
    event_id = data.get('event_id')
    
    try:
        # Find the team
        team = Team.query.filter_by(
            team_number=team_number,
            scouting_team_number=storage_team
        ).first()
        
        if not team:
            return jsonify({'success': False, 'error': 'Team not found'}), 404
        
        if event_id:
            # Remove team from specific event
            event = Event.query.filter_by(id=event_id, scouting_team_number=storage_team).first()
            if event and event in team.events:
                team.events.remove(event)
                db.session.commit()
                
                # Notify alliance members
                socketio.emit('alliance_team_removed', {
                    'alliance_id': alliance_id,
                    'team_number': team_number,
                    'event_id': event_id,
                    'removed_by': current_team
                }, room=f'alliance_{alliance_id}')
                
                return jsonify({
                    'success': True,
                    'message': f'Team {team_number} removed from event'
                })
        else:
            # Remove team from all events (but don't delete the team itself)
            team.events = []
            db.session.commit()
            
            # Notify alliance members
            socketio.emit('alliance_team_removed', {
                'alliance_id': alliance_id,
                'team_number': team_number,
                'removed_by': current_team
            }, room=f'alliance_{alliance_id}')
            
            return jsonify({
                'success': True,
                'message': f'Team {team_number} removed from all events'
            })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error removing alliance team: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:alliance_id>/manage/matches/<int:match_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_alliance_match(alliance_id, match_id):
    """Delete a match from the alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is admin of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    storage_team = alliance.game_config_team
    
    if not storage_team:
        return jsonify({'success': False, 'error': 'Alliance must have a game configuration set'}), 400
    
    try:
        # Find the match - ensure it belongs to an alliance event
        match = Match.query.get(match_id)
        
        if not match:
            return jsonify({'success': False, 'error': 'Match not found'}), 404
        
        # Verify the match's event belongs to the alliance's storage team
        if match.event and match.event.scouting_team_number != storage_team:
            return jsonify({'success': False, 'error': 'Match does not belong to this alliance'}), 403
        
        match_number = match.match_number
        
        # Delete the match
        db.session.delete(match)
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_match_deleted', {
            'alliance_id': alliance_id,
            'match_id': match_id,
            'match_number': match_number,
            'deleted_by': current_team
        }, room=f'alliance_{alliance_id}')
        
        return jsonify({
            'success': True,
            'message': f'Match {match_number} deleted'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting alliance match: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ======== IMPORT DATA FROM SCOUTING TEAMS ========

@bp.route('/<int:alliance_id>/manage/import-data')
@login_required
@admin_required
def import_data_page(alliance_id):
    """Page to import YOUR OWN scouting data into the alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        flash('You must be an alliance member to import data.', 'error')
        return redirect(url_for('scouting_alliances.view_alliance', alliance_id=alliance_id))
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    # Get effective game config
    from app.utils.config_manager import get_effective_game_config
    game_config = get_effective_game_config()
    
    return render_template('scouting_alliances/import_data.html',
                           alliance=alliance,
                           member=member,
                           game_config=game_config,
                           current_team=current_team,
                           **get_theme_context())


@bp.route('/<int:alliance_id>/manage/import-data/scan', methods=['POST'])
@login_required
def scan_my_team_data(alliance_id):
    """Scan current team's data to find entries that can be shared with alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    data = request.get_json() or {}
    data_type = data.get('data_type', 'all')  # 'scouting', 'pit', or 'all'
    
    try:
        # Get alliance event codes (optional - if none, show all team data)
        alliance_events = alliance.get_shared_events()
        
        current_app.logger.info(f"[ImportScan] Team {current_team} scanning for alliance {alliance_id}")
        current_app.logger.info(f"[ImportScan] Alliance events: {alliance_events}")
        
        # Get events for these codes
        events = []
        event_ids = []
        if alliance_events:
            events = Event.query.filter(Event.code.in_(alliance_events)).all()
            event_ids = [e.id for e in events]
            current_app.logger.info(f"[ImportScan] Found event IDs: {event_ids}")
        
        # Get ALL existing shared data in alliance to check for duplicates
        # A duplicate is defined by match_id + team_id + alliance (for scouting)
        # or just team_id (for pit)
        existing_scouting_keys = set()
        existing_pit_team_ids = set()
        
        # Get existing shared scouting data from ANY source
        existing_shared_scouting = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        ).all()
        
        for shared in existing_shared_scouting:
            # Create a unique key for comparison (match + team + alliance color)
            key = (shared.match_id, shared.team_id, shared.alliance)
            existing_scouting_keys.add(key)
        
        current_app.logger.info(f"[ImportScan] Existing scouting keys: {len(existing_scouting_keys)}")
        
        # Get existing shared pit data from ANY source
        existing_shared_pit = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        ).all()
        
        for shared in existing_shared_pit:
            existing_pit_team_ids.add(shared.team_id)
        
        current_app.logger.info(f"[ImportScan] Existing pit team IDs: {len(existing_pit_team_ids)}")
        
        results = {
            'scouting_data': [],
            'pit_data': [],
            'source_team': current_team,
            'alliance_events': alliance_events
        }
        
        # Scan scouting data from CURRENT TEAM ONLY
        if data_type in ['all', 'scouting']:
            # Get all scouting data from current team
            # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
            scouting_query = ScoutingData.query.filter(
                ScoutingData.scouting_team_number == current_team
            )
            
            # Exclude alliance-received data
            scouting_query = scouting_query.filter(
                db.or_(
                    ScoutingData.scout_name == None,
                    ~ScoutingData.scout_name.like('[Alliance-%')
                )
            )
            
            # If we have alliance events, filter by them
            if event_ids:
                scouting_query = scouting_query.join(Match).filter(
                    Match.event_id.in_(event_ids)
                )
            
            scouting_entries = scouting_query.all()
            current_app.logger.info(f"[ImportScan] Found {len(scouting_entries)} scouting entries for team {current_team}")
            
            for entry in scouting_entries:
                # Check if already exists in alliance (from ANY source)
                key = (entry.match_id, entry.team_id, entry.alliance)
                if key in existing_scouting_keys:
                    current_app.logger.debug(f"[ImportScan] Skipping duplicate scouting entry: {key}")
                    continue
                
                # Check if this was previously ignored/deleted
                if AllianceDeletedData.is_deleted(
                    alliance_id=alliance_id,
                    data_type='scouting',
                    match_id=entry.match_id,
                    team_id=entry.team_id,
                    alliance_color=entry.alliance,
                    source_team=current_team
                ):
                    current_app.logger.debug(f"[ImportScan] Skipping deleted entry: {key}")
                    continue
                
                # Add to results
                results['scouting_data'].append({
                    'id': entry.id,
                    'team_number': entry.team.team_number if entry.team else 'Unknown',
                    'team_name': entry.team.team_name if entry.team else 'Unknown',
                    'match_number': entry.match.match_number if entry.match else 'Unknown',
                    'match_type': entry.match.match_type if entry.match else 'Unknown',
                    'event_code': entry.match.event.code if entry.match and entry.match.event else 'Unknown',
                    'event_name': entry.match.event.name if entry.match and entry.match.event else 'Unknown',
                    'alliance': entry.alliance,
                    'scout_name': entry.scout_name,
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                    'data_preview': _get_data_preview(entry.data)
                })
        
        # Scan pit data from CURRENT TEAM ONLY
        if data_type in ['all', 'pit']:
            # Get all pit data from current team
            # EXCLUDE entries that were received from alliance (have [Alliance- prefix)
            # Include NULL scouting_team_number for backwards compatibility
            pit_query = PitScoutingData.query.filter(
                db.or_(
                    PitScoutingData.scouting_team_number == current_team,
                    PitScoutingData.scouting_team_number == None
                )
            )
            
            # Exclude alliance-received data
            pit_query = pit_query.filter(
                db.or_(
                    PitScoutingData.scout_name == None,
                    ~PitScoutingData.scout_name.like('[Alliance-%')
                )
            )
            
            pit_entries = pit_query.all()
            current_app.logger.info(f"[ImportScan] Found {len(pit_entries)} pit entries for team {current_team}")
            
            for entry in pit_entries:
                # Check if already exists in alliance (from ANY source)
                if entry.team_id in existing_pit_team_ids:
                    current_app.logger.debug(f"[ImportScan] Skipping duplicate pit entry for team_id: {entry.team_id}")
                    continue
                
                # Check if this was previously ignored/deleted
                if AllianceDeletedData.is_deleted(
                    alliance_id=alliance_id,
                    data_type='pit',
                    match_id=None,
                    team_id=entry.team_id,
                    alliance_color=None,
                    source_team=current_team
                ):
                    continue
                
                # Add to results
                results['pit_data'].append({
                    'id': entry.id,
                    'team_number': entry.team.team_number if entry.team else 'Unknown',
                    'team_name': entry.team.team_name if entry.team else 'Unknown',
                    'scout_name': entry.scout_name,
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                    'data_preview': _get_data_preview(entry.data)
                })
        
        current_app.logger.info(f"[ImportScan] Results: {len(results['scouting_data'])} scouting, {len(results['pit_data'])} pit")
        
        return jsonify({
            'success': True,
            'results': results,
            'total_scouting': len(results['scouting_data']),
            'total_pit': len(results['pit_data'])
        })
        
    except Exception as e:
        current_app.logger.error(f"Error scanning team data: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


def _get_data_preview(data):
    """Get a short preview of data for display"""
    if not data:
        return 'No data'
    
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            return data[:100] + '...' if len(data) > 100 else data
    
    if isinstance(data, dict):
        # Get first few key-value pairs
        items = list(data.items())[:3]
        preview_parts = []
        for key, value in items:
            if isinstance(value, (dict, list)):
                preview_parts.append(f"{key}: [...]")
            else:
                str_val = str(value)
                if len(str_val) > 20:
                    str_val = str_val[:20] + '...'
                preview_parts.append(f"{key}: {str_val}")
        return ', '.join(preview_parts)
    
    return str(data)[:100]


@bp.route('/<int:alliance_id>/manage/import-data/import', methods=['POST'])
@login_required
def import_selected_data(alliance_id):
    """Import selected scouting data from current team into the alliance"""
    current_team = get_current_scouting_team_number()
    
    # Check if user is a member of this alliance
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        status='accepted'
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    alliance = ScoutingAlliance.query.get_or_404(alliance_id)
    
    data = request.get_json()
    scouting_ids = data.get('scouting_ids', [])  # List of ScoutingData IDs to import
    pit_ids = data.get('pit_ids', [])  # List of PitScoutingData IDs to import
    ignore_ids = data.get('ignore_ids', [])  # IDs to mark as ignored (won't show again)
    
    try:
        imported_scouting = 0
        imported_pit = 0
        ignored_count = 0
        skipped_wrong_team = 0
        skipped_duplicate = 0
        
        # Import scouting data
        for scouting_id in scouting_ids:
            entry = ScoutingData.query.get(scouting_id)
            if not entry:
                continue
                
            # Only allow importing data owned by current team
            if entry.scouting_team_number != current_team:
                skipped_wrong_team += 1
                continue
            
            # Check if already exists from this source
            existing = AllianceSharedScoutingData.query.filter_by(
                alliance_id=alliance_id,
                original_scouting_data_id=entry.id
            ).first()
            
            if existing:
                skipped_duplicate += 1
                continue
            
            # Also check by match/team/alliance combo from ANY source
            existing = AllianceSharedScoutingData.query.filter_by(
                alliance_id=alliance_id,
                match_id=entry.match_id,
                team_id=entry.team_id,
                alliance=entry.alliance,
                is_active=True
            ).first()
            
            if existing:
                skipped_duplicate += 1
                continue
            
            # Create shared copy
            shared_copy = AllianceSharedScoutingData.create_from_scouting_data(
                entry, alliance_id, current_team
            )
            db.session.add(shared_copy)
            imported_scouting += 1
        
        # Import pit data
        for pit_id in pit_ids:
            entry = PitScoutingData.query.get(pit_id)
            if not entry:
                continue
                
            # Only allow importing data owned by current team
            if entry.scouting_team_number != current_team:
                skipped_wrong_team += 1
                continue
            
            # Check if already exists from this source
            existing = AllianceSharedPitData.query.filter_by(
                alliance_id=alliance_id,
                original_pit_data_id=entry.id
            ).first()
            
            if existing:
                skipped_duplicate += 1
                continue
            
            # Also check by team from ANY source
            existing = AllianceSharedPitData.query.filter_by(
                alliance_id=alliance_id,
                team_id=entry.team_id,
                is_active=True
            ).first()
            
            if existing:
                skipped_duplicate += 1
                continue
            
            # Create shared copy
            shared_copy = AllianceSharedPitData.create_from_pit_data(
                entry, alliance_id, current_team
            )
            db.session.add(shared_copy)
            imported_pit += 1
        
        # Mark ignored entries as "deleted" so they won't show up again
        for ignore_entry in ignore_ids:
            ignore_type = ignore_entry.get('type')  # 'scouting' or 'pit'
            ignore_id = ignore_entry.get('id')
            
            if ignore_type == 'scouting':
                entry = ScoutingData.query.get(ignore_id)
                if entry and entry.scouting_team_number == current_team:
                    # Mark as deleted (ignored)
                    deleted_record = AllianceDeletedData(
                        alliance_id=alliance_id,
                        data_type='scouting',
                        match_id=entry.match_id,
                        team_id=entry.team_id,
                        alliance_color=entry.alliance,
                        source_scouting_team_number=current_team,
                        deleted_by_team=current_team
                    )
                    db.session.add(deleted_record)
                    ignored_count += 1
            
            elif ignore_type == 'pit':
                entry = PitScoutingData.query.get(ignore_id)
                if entry and entry.scouting_team_number == current_team:
                    # Mark as deleted (ignored)
                    deleted_record = AllianceDeletedData(
                        alliance_id=alliance_id,
                        data_type='pit',
                        match_id=None,
                        team_id=entry.team_id,
                        alliance_color=None,
                        source_scouting_team_number=current_team,
                        deleted_by_team=current_team
                    )
                    db.session.add(deleted_record)
                    ignored_count += 1
        
        db.session.commit()
        
        # Notify alliance members
        socketio.emit('alliance_data_imported', {
            'alliance_id': alliance_id,
            'source_team': current_team,
            'imported_scouting': imported_scouting,
            'imported_pit': imported_pit,
            'imported_by': current_team
        }, room=f'alliance_{alliance_id}')
        
        current_app.logger.info(f"[Import] Team {current_team} imported {imported_scouting} scouting, {imported_pit} pit. Skipped: {skipped_duplicate} duplicates, {skipped_wrong_team} wrong team")
        
        return jsonify({
            'success': True,
            'imported_scouting': imported_scouting,
            'imported_pit': imported_pit,
            'ignored_count': ignored_count,
            'message': f'Imported {imported_scouting} scouting entries and {imported_pit} pit entries. {ignored_count} entries marked as ignored.'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error importing data: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500