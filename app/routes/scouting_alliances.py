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
    TeamAllianceStatus
)
from app.routes.auth import admin_required
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import load_game_config, load_pit_config
from app.utils.team_isolation import get_current_scouting_team_number
from datetime import datetime, timedelta
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
            
            # Update alliance shared configs from the configured teams
            if alliance.game_config_team:
                game_config = load_game_config(team_number=alliance.game_config_team)
                alliance.shared_game_config = json.dumps(game_config)
            
            if alliance.pit_config_team:
                pit_config = load_pit_config(team_number=alliance.pit_config_team)
                alliance.shared_pit_config = json.dumps(pit_config)
            
            db.session.commit()
            
        else:
            # Deactivate alliance mode
            TeamAllianceStatus.deactivate_alliance_for_team(current_team)
            message = 'Alliance mode deactivated - using individual team configuration'
        
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
        invitation.responded_at = datetime.utcnow()
        
        # Send notification to alliance members
        socketio.emit('alliance_member_joined', {
            'alliance_id': invitation.alliance_id,
            'team_number': current_team,
            'team_name': f"Team {current_team}"
        }, room=f'alliance_{invitation.alliance_id}')
        
    else:
        invitation.status = 'declined'
        invitation.responded_at = datetime.utcnow()
    
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
    
    # Get all active alliance members
    all_members = alliance.get_active_members()
    member_teams = [m.team_number for m in all_members]
    
    total_imported = 0
    total_shared = 0
    
    if alliance_events:
        # Get events
        events = Event.query.filter(Event.code.in_(alliance_events)).all()
        event_ids = [e.id for e in events]
        
        # STEP 1: Collect data from ALL alliance members (including current team)
        all_scouting_data = {}
        all_pit_data = {}
        
        for team_num in member_teams:
            # Get scouting data for each team
            scouting_entries = ScoutingData.query.join(Match).filter(
                Match.event_id.in_(event_ids),
                ScoutingData.scouting_team_number == team_num
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
                        'team_id': entry.team_id
                    }
            
            # Get pit data for each team
            pit_entries = PitScoutingData.query.filter(
                PitScoutingData.scouting_team_number == team_num
            ).all()
            
            for entry in pit_entries:
                key = entry.team_number
                if key not in all_pit_data:
                    all_pit_data[key] = {
                        'team_number': entry.team_number,
                        'scout_name': entry.scout_name,
                        'data': entry.data,
                        'timestamp': entry.timestamp.isoformat(),
                        'source_team': team_num
                    }
        
        # STEP 2: Import missing data to current team
        for key, entry_data in all_scouting_data.items():
            if entry_data['source_team'] != current_team:
                # Check if we already have this data
                existing = ScoutingData.query.join(Match).join(Team).filter(
                    Team.team_number == entry_data['team_number'],
                    Match.match_number == entry_data['match_number'],
                    Match.match_type == entry_data['match_type'],
                    Match.event_id.in_(event_ids),
                    ScoutingData.alliance == entry_data['alliance'],
                    ScoutingData.scouting_team_number == current_team
                ).first()
                
                if not existing:
                    # Find the match and team
                    match = Match.query.get(entry_data['match_id'])
                    team = Team.query.get(entry_data['team_id'])
                    
                    if match and team:
                        new_entry = ScoutingData(
                            match_id=match.id,
                            team_id=team.id,
                            scouting_team_number=current_team,
                            scout_name=f"[Alliance-{entry_data['source_team']}] {entry_data['scout_name']}",
                            alliance=entry_data['alliance'],
                            data=entry_data['data'],
                            timestamp=datetime.fromisoformat(entry_data['timestamp'])
                        )
                        db.session.add(new_entry)
                        total_imported += 1
        
        # Import missing pit data
        for key, entry_data in all_pit_data.items():
            if entry_data['source_team'] != current_team:
                # Find the team first
                team = Team.query.filter_by(team_number=entry_data['team_number']).first()
                if not team:
                    continue  # Skip if team doesn't exist
                
                existing = PitScoutingData.query.filter_by(
                    team_id=team.id,
                    scouting_team_number=current_team
                ).first()
                
                if not existing:
                    new_entry = PitScoutingData(
                        team_id=team.id,
                        scouting_team_number=current_team,
                        scout_name=f"[Alliance-{entry_data['source_team']}] {entry_data['scout_name']}",
                        data_json=json.dumps(entry_data['data']),
                        timestamp=datetime.fromisoformat(entry_data['timestamp']),
                        local_id=str(uuid.uuid4())
                    )
                    db.session.add(new_entry)
                    total_imported += 1
        
        # STEP 3: Share current team's data with other members via SocketIO (if they're online)
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
                    'scouting_data': current_team_scouting,
                    'pit_data': current_team_pit,
                    'sync_id': sync_record.id
                }, room=f'team_{member_obj.team_number}')
    
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'imported_count': total_imported,
        'shared_count': total_shared,
        'synced_to': len([m for m in all_members if m.team_number != current_team]),
        'message': f'Imported {total_imported} new entries, shared {total_shared} entries with alliance members'
    })

@bp.route('/sync/receive', methods=['POST'])
@login_required
@admin_required
def receive_sync_data():
    """Receive synchronized data from alliance member"""
    data = request.get_json()
    current_team = get_current_scouting_team_number()
    
    from_team = data['from_team']
    scouting_data = data['scouting_data']
    pit_data = data['pit_data']
    sync_id = data['sync_id']
    
    # Verify we're in the same alliance
    common_alliance = db.session.query(ScoutingAlliance).join(ScoutingAllianceMember).filter(
        ScoutingAllianceMember.team_number.in_([current_team, from_team]),
        ScoutingAllianceMember.status == 'accepted'
    ).first()
    
    if not common_alliance:
        return jsonify({'success': False, 'error': 'Not in same alliance'})
    
    # Process scouting data (create entries with alliance team prefix)
    imported_count = 0
    
    for entry_data in scouting_data:
        # Check if we already have this data
        existing = ScoutingData.query.join(Match).join(Team).filter(
            Team.team_number == entry_data['team_number'],
            Match.match_number == entry_data['match_number'],
            Match.match_type == entry_data['match_type'],
            ScoutingData.scouting_team_number == current_team
        ).first()
        
        if not existing:
            # Find or create the match and team
            event = Event.query.filter_by(code=entry_data['event_code']).first()
            if event:
                match = Match.query.filter_by(
                    event_id=event.id,
                    match_number=entry_data['match_number'],
                    match_type=entry_data['match_type']
                ).first()
                
                team = Team.query.filter_by(team_number=entry_data['team_number']).first()
                
                if match and team:
                    new_entry = ScoutingData(
                        match_id=match.id,
                        team_id=team.id,
                        scouting_team_number=current_team,
                        scout_name=f"[Alliance-{from_team}] {entry_data['scout_name']}",
                        alliance=entry_data['alliance'],
                        data=entry_data['data'],
                        timestamp=datetime.fromisoformat(entry_data['timestamp'])
                    )
                    db.session.add(new_entry)
                    imported_count += 1
    
    # Process pit data
    for entry_data in pit_data:
        # Find the team first
        team = Team.query.filter_by(team_number=entry_data['team_number']).first()
        if not team:
            continue  # Skip if team doesn't exist
            
        existing = PitScoutingData.query.filter_by(
            team_id=team.id,
            scouting_team_number=current_team
        ).first()
        
        if not existing:
            new_entry = PitScoutingData(
                team_id=team.id,
                scouting_team_number=current_team,
                scout_name=f"[Alliance-{from_team}] {entry_data['scout_name']}",
                data_json=json.dumps(entry_data['data']),
                timestamp=datetime.fromisoformat(entry_data['timestamp']),
                local_id=str(uuid.uuid4())
            )
            db.session.add(new_entry)
            imported_count += 1
    
    # Update sync record
    sync_record = ScoutingAllianceSync.query.get(sync_id)
    if sync_record:
        sync_record.sync_status = 'synced'
        sync_record.last_sync = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'success': True, 'imported_count': imported_count})

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
    """Handle receipt of automatic sync data from alliance members"""
    current_team = get_current_scouting_team_number()
    from_team = data.get('from_team')
    sync_id = data.get('sync_id')
    
    # Verify we're in the same alliance with the sending team
    common_alliance = db.session.query(ScoutingAlliance).join(ScoutingAllianceMember).filter(
        ScoutingAllianceMember.team_number.in_([current_team, from_team]),
        ScoutingAllianceMember.status == 'accepted'
    ).first()
    
    if not common_alliance:
        return
    
    # Process the auto-sync data similar to manual sync
    scouting_data = data.get('scouting_data', [])
    pit_data = data.get('pit_data', [])
    
    imported_count = 0
    
    # Process scouting data
    for entry_data in scouting_data:
        # Check if we already have this data
        existing = ScoutingData.query.join(Match).join(Team).filter(
            Team.team_number == entry_data['team_number'],
            Match.match_number == entry_data['match_number'],
            Match.match_type == entry_data['match_type'],
            ScoutingData.scouting_team_number == current_team
        ).first()
        
        if not existing:
            # Find or create the match and team
            event = Event.query.filter_by(code=entry_data['event_code']).first()
            if event:
                match = Match.query.filter_by(
                    event_id=event.id,
                    match_number=entry_data['match_number'],
                    match_type=entry_data['match_type']
                ).first()
                
                team = Team.query.filter_by(team_number=entry_data['team_number']).first()
                
                if match and team:
                    new_entry = ScoutingData(
                        match_id=match.id,
                        team_id=team.id,
                        scouting_team_number=current_team,
                        scout_name=f"[Alliance-{from_team}] {entry_data['scout_name']}",
                        alliance=entry_data['alliance'],
                        data=entry_data['data'],
                        timestamp=datetime.fromisoformat(entry_data['timestamp'])
                    )
                    db.session.add(new_entry)
                    imported_count += 1
    
    # Process pit data
    for entry_data in pit_data:
        existing = PitScoutingData.query.filter(
            PitScoutingData.team_id.in_(
                db.session.query(Team.id).filter(Team.team_number == entry_data['team_number'])
            ),
            PitScoutingData.scouting_team_number == current_team
        ).first()
        
        if not existing:
            team = Team.query.filter_by(team_number=entry_data['team_number']).first()
            if team:
                new_entry = PitScoutingData(
                    team_id=team.id,
                    scouting_team_number=current_team,
                    scout_name=f"[Alliance-{from_team}] {entry_data['scout_name']}",
                    data_json=json.dumps(entry_data['data']),
                    timestamp=datetime.fromisoformat(entry_data['timestamp']),
                    local_id=str(uuid.uuid4())
                )
                db.session.add(new_entry)
                imported_count += 1
    
    # Update sync record
    if sync_id:
        sync_record = ScoutingAllianceSync.query.get(sync_id)
        if sync_record:
            sync_record.sync_status = 'synced'
            sync_record.last_sync = datetime.utcnow()
    
    if imported_count > 0:
        db.session.commit()
        
        # Notify the client about successful auto-sync
        emit('alliance_auto_sync_complete', {
            'from_team': from_team,
            'imported_count': imported_count,
            'alliance_name': data.get('alliance_name', 'Alliance'),
            'type': data.get('type', 'auto_sync')
        })


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
        
        # Check if user is member of this alliance
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
        
        # Verify user is member of the alliance
        member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance_id,
            team_number=current_team
        ).first()
        
        if not member:
            return jsonify({'success': False, 'error': 'Not a member of this alliance'}), 403
        
        # Update or create team alliance status
        team_status = TeamAllianceStatus.query.filter_by(
            team_number=current_team
        ).first()
        
        if not team_status:
            team_status = TeamAllianceStatus(
                team_number=current_team,
                active_alliance_id=alliance_id if is_active else None,
                is_alliance_mode_active=is_active
            )
            db.session.add(team_status)
        else:
            team_status.active_alliance_id = alliance_id if is_active else None
            team_status.is_alliance_mode_active = is_active
            if is_active:
                team_status.activated_at = datetime.utcnow()
                team_status.deactivated_at = None
            else:
                team_status.deactivated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'is_active': is_active,
            'message': f'Alliance mode {"activated" if is_active else "deactivated"} successfully'
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
                    last_sync=datetime.utcnow()
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
            alliance_status.last_updated = datetime.utcnow()
        
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
                            
                            elements.append(element)
                    
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
        
        # Validate and save the configuration
        alliance.shared_game_config = json.dumps(config_data, indent=2)
        alliance.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Emit Socket.IO event to notify alliance members
        socketio.emit('alliance_config_updated', {
            'alliance_id': alliance_id,
            'config_type': 'game',
            'message': f'Game configuration updated by Team {current_team}'
        }, room=f'alliance_{alliance_id}')
        
        flash('Alliance game configuration saved successfully!', 'success')
        return jsonify({'success': True, 'config': config_data})
        
    except Exception as e:
        current_app.logger.error(f"Error saving alliance game config: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

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
        alliance.updated_at = datetime.utcnow()
        
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
            else:
                return jsonify({'success': False, 'error': 'No game configuration found for your scouting team.'}), 404
                
        elif config_type == 'pit':
            # Load scouting team's pit config
            config_data = load_pit_config(team_number=current_team)
            if config_data:
                alliance.shared_pit_config = json.dumps(config_data, indent=2)
            else:
                return jsonify({'success': False, 'error': 'No pit configuration found for your scouting team.'}), 404
        else:
            return jsonify({'success': False, 'error': 'Invalid configuration type.'}), 400
        
        alliance.updated_at = datetime.utcnow()
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
                    recent_time = datetime.utcnow() - timedelta(minutes=5)
                    
                    # Get recent scouting data for this team
                    recent_scouting = ScoutingData.query.join(Match).filter(
                        Match.event_id.in_(event_ids),
                        ScoutingData.scouting_team_number == current_team,
                        ScoutingData.timestamp >= recent_time
                    ).all()
                    
                    # Get recent pit data for this team
                    recent_pit = PitScoutingData.query.filter(
                        PitScoutingData.scouting_team_number == current_team,
                        PitScoutingData.timestamp >= recent_time
                    ).all()
                    
                    if not recent_scouting and not recent_pit:
                        continue  # No recent data to sync
                    
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
                                last_sync=datetime.utcnow()
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
                    
                    if sync_count > 0:
                        db.session.commit()
                        print(f"Periodic sync: Team {current_team} synced {len(scouting_data)} scouting + {len(pit_data)} pit entries to {sync_count} alliance members")
                
                except Exception as e:
                    print(f"Error in periodic sync for team {status.team_number}: {str(e)}")
                    continue
    
    except Exception as e:
        print(f"Error in perform_periodic_alliance_sync: {str(e)}")
