from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from app.models import Team, Event, PitScoutingData
from app import db, socketio
import json
import uuid
from datetime import datetime, timezone
from app.utils.config_manager import get_id_to_perm_id_mapping, get_effective_game_config
from app.utils.sync_manager import SyncManager
import os
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_current_pit_config, save_pit_config, get_effective_pit_config, is_alliance_mode_active
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code
)

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

def auto_sync_alliance_pit_data(pit_data_entry):
    """Automatically sync new pit scouting data to alliance members if alliance mode is active"""
    try:
        # Check if alliance mode is active for current user's team
        if not is_alliance_mode_active():
            return
        
        # Import here to avoid circular imports
        from app.models import TeamAllianceStatus, ScoutingAlliance, ScoutingAllianceMember, ScoutingAllianceSync
        
        current_team = current_user.scouting_team_number
        
        # Get the active alliance for this team
        alliance_status = TeamAllianceStatus.query.filter_by(
            team_number=current_team,
            is_alliance_mode_active=True
        ).first()
        
        if not alliance_status or not alliance_status.active_alliance:
            return
            
        alliance = alliance_status.active_alliance
        
        # Prepare the pit data for sync
        sync_data = {
            'team_number': pit_data_entry.team.team_number,
            'scout_name': pit_data_entry.scout_name,
            'data': pit_data_entry.data,
            'timestamp': pit_data_entry.timestamp.isoformat()
        }
        
        # Send data to alliance members via Socket.IO
        sync_count = 0
        active_members = alliance.get_active_members()
        
        for member in active_members:
            if member.team_number != current_team:
                # Create sync record
                sync_record = ScoutingAllianceSync(
                    alliance_id=alliance.id,
                    from_team_number=current_team,
                    to_team_number=member.team_number,
                    data_type='pit',
                    data_count=1
                )
                db.session.add(sync_record)
                sync_count += 1
                
                # Emit real-time sync to that team
                socketio.emit('alliance_data_sync_auto', {
                    'from_team': current_team,
                    'alliance_name': alliance.alliance_name,
                    'scouting_data': [],
                    'pit_data': [sync_data],
                    'sync_id': sync_record.id,
                    'type': 'auto_sync'
                }, room=f'team_{member.team_number}')
                
        if sync_count > 0:
            db.session.commit()
            print(f"Auto-synced pit data for Team {pit_data_entry.team.team_number} to {sync_count} alliance members")
            
    except Exception as e:
        print(f"Error in auto-sync alliance pit data: {str(e)}")
        # Don't raise the exception to prevent disrupting the main save operation

bp = Blueprint('pit_scouting', __name__, url_prefix='/pit-scouting')

@bp.route('/')
@login_required
def index():
    """Pit scouting dashboard page"""
    pit_config = get_effective_pit_config()  # Use alliance config if active
    
    # Get current event based on team-scoped/alliance-aware game configuration
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
    else:
        teams = filter_teams_by_scouting_team().all()
    
    # Get recent pit scouting data
    recent_pit_data = PitScoutingData.query.order_by(PitScoutingData.timestamp.desc()).limit(10).all()
    # Also gather all pit entries for the teams shown so the Teams grid can accurately
    # reflect whether a team has been scouted (not limited to the recent list)
    team_ids = [t.id for t in teams]
    if team_ids:
        all_pit_entries = PitScoutingData.query.filter(PitScoutingData.team_id.in_(team_ids)).all()
    else:
        all_pit_entries = []

    # Build quick lookup sets for template membership tests
    scouted_team_ids = set()
    scouted_team_numbers = set()
    for e in all_pit_entries:
        try:
            if e.team_id:
                scouted_team_ids.add(e.team_id)
            if hasattr(e, 'team') and e.team and hasattr(e.team, 'team_number'):
                scouted_team_numbers.add(e.team.team_number)
        except Exception:
            # be resilient to partially populated records
            continue
    
    # Get statistics
    total_teams_scouted = PitScoutingData.query.count()
    unuploaded_count = PitScoutingData.query.filter_by(is_uploaded=False).count()
    
    return render_template('scouting/pit_index.html', 
                          teams=teams, 
                          pit_data=recent_pit_data,
                          all_pit_data=all_pit_entries,
                          scouted_team_ids=list(scouted_team_ids),
                          scouted_team_numbers=list(scouted_team_numbers),
                          pit_config=pit_config,
                          current_event=current_event,
                          total_teams_scouted=total_teams_scouted,
                          unuploaded_count=unuploaded_count,
                          **get_theme_context())

@bp.route('/form', methods=['GET', 'POST'])
@login_required
def form():
    """Dynamic pit scouting form"""
    team_param = request.args.get('team')
    if team_param:
        try:
            team_param_int = int(team_param)
        except Exception:
            team_param_int = None
    else:
        team_param_int = None

    # Always load the current user's scouting team pit config
    # (ignore team parameter for form - form should always use current user's config)
    pit_config = get_current_pit_config()
    
    # Get current event based on team-scoped/alliance-aware game configuration
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
    else:
        teams = filter_teams_by_scouting_team().all()

    # Gather all pit entries for these teams so the form can show scouted status
    team_ids = [t.id for t in teams]
    if team_ids:
        form_all_pit_entries = PitScoutingData.query.filter(PitScoutingData.team_id.in_(team_ids)).all()
    else:
        form_all_pit_entries = []

    # Split into local (not uploaded) and server (uploaded) sets for UI
    scouted_local_ids = set()
    scouted_server_ids = set()
    scouted_local_numbers = set()
    scouted_server_numbers = set()
    for e in form_all_pit_entries:
        try:
            if e.team_id:
                if e.is_uploaded:
                    scouted_server_ids.add(e.team_id)
                else:
                    scouted_local_ids.add(e.team_id)
            if hasattr(e, 'team') and e.team and hasattr(e.team, 'team_number'):
                if e.is_uploaded:
                    scouted_server_numbers.add(e.team.team_number)
                else:
                    scouted_local_numbers.add(e.team.team_number)
        except Exception:
            continue
    
    if request.method == 'POST':
        try:
            # Get form data
            team_number = request.form.get('team_number')
            if not team_number:
                flash('Team number is required', 'error')
                return redirect(url_for('pit_scouting.form'))
            
            # Find or create team
            team = Team.query.filter_by(team_number=int(team_number)).first()
            if not team:
                team = Team(team_number=int(team_number))
                db.session.add(team)
                db.session.commit()
            
            # Check if this team has already been scouted by this scout
            existing_data = PitScoutingData.query.filter_by(
                team_id=team.id,
                scout_id=current_user.id
            ).first()
            # If data exists for this scout/team, overwrite it with the new submission
            if existing_data:
                try:
                    # Collect form data based on pit config (same logic as for new entries)
                    form_data = {}
                    for section in pit_config['pit_scouting']['sections']:
                        for element in section['elements']:
                            element_id = element['id']
                            element_type = element['type']

                            if element_type == 'multiselect':
                                values = request.form.getlist(element_id)
                                form_data[element_id] = values
                            elif element_type == 'boolean':
                                form_data[element_id] = element_id in request.form
                            elif element_type == 'number':
                                value = request.form.get(element_id)
                                if value:
                                    try:
                                        form_data[element_id] = float(value)
                                    except ValueError:
                                        form_data[element_id] = 0
                                else:
                                    form_data[element_id] = 0
                            else:
                                form_data[element_id] = request.form.get(element_id, '')

                    # Update existing record
                    existing_data.data_json = json.dumps(form_data)
                    existing_data.is_uploaded = False
                    existing_data.device_id = request.headers.get('User-Agent', 'Unknown')[:100]
                    existing_data.timestamp = datetime.now(timezone.utc)
                    db.session.commit()

                    # Auto-sync and emit update
                    auto_sync_alliance_pit_data(existing_data)
                    if current_event:
                        emit_pit_data_update(current_event.id, 'updated', existing_data.to_dict())

                    flash(f'Pit scouting data for Team {team_number} updated successfully!', 'success')
                    return redirect(url_for('pit_scouting.view', id=existing_data.id))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error updating existing pit scouting data: {str(e)}', 'error')
                    return redirect(url_for('pit_scouting.form'))
            
            # Collect form data based on pit config
            form_data = {}
            for section in pit_config['pit_scouting']['sections']:
                for element in section['elements']:
                    element_id = element['id']
                    element_type = element['type']
                    
                    if element_type == 'multiselect':
                        # Handle multiselect fields
                        values = request.form.getlist(element_id)
                        form_data[element_id] = values
                    elif element_type == 'boolean':
                        # Handle boolean fields (checkboxes)
                        form_data[element_id] = element_id in request.form
                    elif element_type == 'number':
                        # Handle number fields
                        value = request.form.get(element_id)
                        if value:
                            try:
                                form_data[element_id] = float(value)
                            except ValueError:
                                form_data[element_id] = 0
                        else:
                            form_data[element_id] = 0
                    else:
                        # Handle text, textarea, select fields
                        form_data[element_id] = request.form.get(element_id, '')
            
            # Create pit scouting data entry
            pit_data = PitScoutingData(
                local_id=str(uuid.uuid4()),
                team_id=team.id,
                event_id=current_event.id if current_event else None,
                scout_name=current_user.username,
                scout_id=current_user.id,
                data_json=json.dumps(form_data),
                is_uploaded=False,
                device_id=request.headers.get('User-Agent', 'Unknown')[:100]
            )
            
            db.session.add(pit_data)
            db.session.commit()
            
            # Automatically sync to alliance members if alliance mode is active
            auto_sync_alliance_pit_data(pit_data)
            
            # Emit real-time update
            if current_event:
                emit_pit_data_update(current_event.id, 'added', pit_data.to_dict())
            
            flash(f'Pit scouting data for Team {team_number} saved successfully!', 'success')
            return redirect(url_for('pit_scouting.view', id=pit_data.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving pit scouting data: {str(e)}', 'error')
            return redirect(url_for('pit_scouting.form'))
    
    # For GET request, show the form
    # Build a JSON-serializable representation of teams for use in JS
    teams_for_js = []
    for t in teams:
        try:
            teams_for_js.append({
                'id': t.id,
                'team_number': t.team_number,
                'team_name': t.team_name or ''
            })
        except Exception:
            continue

    return render_template('scouting/pit_form.html', 
                          teams=teams, 
                          pit_config=pit_config,
                          current_event=current_event,
                          all_pit_data=form_all_pit_entries,
                          scouted_local_ids=list(scouted_local_ids),
                          scouted_server_ids=list(scouted_server_ids),
                          scouted_local_numbers=list(scouted_local_numbers),
                          scouted_server_numbers=list(scouted_server_numbers),
                          teams_for_js=teams_for_js,
                          **get_theme_context())

@bp.route('/list', endpoint='list')
@login_required
def list_redirect():
    """Redirect to dynamic list view (keeps endpoint 'list' for compatibility)"""
    return redirect(url_for('pit_scouting.list_dynamic'))

@bp.route('/list-dynamic')
@login_required
def list_dynamic():
    """Dynamic pit scouting data display with auto-refresh"""
    pit_config = get_effective_pit_config()
    
    # Get current event based on team-scoped/alliance-aware game configuration
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    return render_template('scouting/pit_list_dynamic.html', 
                          pit_config=pit_config,
                          current_event=current_event,
                          **get_theme_context())

@bp.route('/api/list')
@login_required
def api_list():
    """API endpoint to get pit scouting data as JSON"""
    pit_config = get_effective_pit_config()
    
    # Get current event based on team-scoped/alliance-aware game configuration
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Filter by event if available. Show both records for the current event
    # and records with no event_id (locally collected entries). Also scope
    # results to the current user's scouting team so users only see their
    # team's pit data.
    from flask_login import current_user
    team_scope = None
    try:
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
            team_scope = current_user.scouting_team_number
    except Exception:
        team_scope = None

    query = PitScoutingData.query
    if team_scope is not None:
        query = query.filter(PitScoutingData.scouting_team_number == team_scope)

    if current_event:
        pit_data = query.filter(
            (PitScoutingData.event_id == current_event.id) | (PitScoutingData.event_id.is_(None))
        ).order_by(PitScoutingData.timestamp.desc()).all()
    else:
        pit_data = query.order_by(PitScoutingData.timestamp.desc()).all()
    
    # Convert to JSON format
    data_list = []
    for entry in pit_data:
        entry_data = {
            'id': entry.id,
            'team_number': entry.team.team_number,
            'team_name': entry.team.team_name or f'Team {entry.team.team_number}',
            'scout_name': entry.scout_name,
            'timestamp': entry.timestamp.isoformat(),
            'is_uploaded': entry.is_uploaded,
            'data': entry.data  # This contains the actual form data
        }
        data_list.append(entry_data)
    
    return jsonify({
        'success': True,
        'data': data_list,
        'config': pit_config['pit_scouting'],
        'current_event': {
            'name': current_event.name,
            'code': current_event.code
        } if current_event else None,
        'total_count': len(data_list)
    })

@bp.route('/view/<int:id>')
@login_required
def view(id):
    """View specific pit scouting data"""
    pit_config = get_effective_pit_config()
    pit_data = PitScoutingData.query.get_or_404(id)
    
    return render_template('scouting/pit_view.html', 
                          pit_data=pit_data,
                          pit_config=pit_config,
                          **get_theme_context())

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    """Edit existing pit scouting data"""
    pit_config = get_effective_pit_config()
    pit_data = PitScoutingData.query.get_or_404(id)
    
    # Check if user can edit this data
    if not current_user.has_role('admin') and pit_data.scout_id != current_user.id:
        flash('You can only edit your own pit scouting data', 'error')
        return redirect(url_for('pit_scouting.view', id=id))
    
    if request.method == 'POST':
        try:
            # Allow changing the team number when editing
            team_number = request.form.get('team_number')
            if team_number:
                try:
                    team_number_int = int(team_number)
                except ValueError:
                    team_number_int = None

                if team_number_int:
                    team = Team.query.filter_by(team_number=team_number_int).first()
                    if not team:
                        team = Team(team_number=team_number_int)
                        db.session.add(team)
                        db.session.flush()  # ensure id is available
                    pit_data.team_id = team.id
                    # If we have a current_event in scope, optionally keep event association
                    game_config = get_effective_game_config()
                    current_event_code = game_config.get('current_event_code')
                    current_event = None
                    if current_event_code:
                        current_event = get_event_by_code(current_event_code)
                    if current_event:
                        pit_data.event_id = current_event.id

            # Collect form data based on pit config
            form_data = {}
            for section in pit_config['pit_scouting']['sections']:
                for element in section['elements']:
                    element_id = element['id']
                    element_type = element['type']
                    
                    if element_type == 'multiselect':
                        values = request.form.getlist(element_id)
                        form_data[element_id] = values
                    elif element_type == 'boolean':
                        form_data[element_id] = element_id in request.form
                    elif element_type == 'number':
                        value = request.form.get(element_id)
                        if value:
                            try:
                                form_data[element_id] = float(value)
                            except ValueError:
                                form_data[element_id] = 0
                        else:
                            form_data[element_id] = 0
                    else:
                        form_data[element_id] = request.form.get(element_id, '')
            
            # Update pit scouting data
            pit_data.data_json = json.dumps(form_data)
            pit_data.is_uploaded = False  # Mark as needing re-upload
            
            db.session.commit()
            
            # Automatically sync to alliance members if alliance mode is active
            auto_sync_alliance_pit_data(pit_data)
            
            # Emit real-time update
            if pit_data.event_id:
                emit_pit_data_update(pit_data.event_id, 'updated', pit_data.to_dict())
            
            flash('Pit scouting data updated successfully!', 'success')
            return redirect(url_for('pit_scouting.view', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating pit scouting data: {str(e)}', 'error')
    
    # For GET request, show the edit form
    # Build teams for the dropdown (same behavior as the create form)
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)

    if current_event:
        teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
    else:
        teams = filter_teams_by_scouting_team().all()

    # Gather all pit entries for these teams so the edit form can show scouted status
    team_ids = [t.id for t in teams]
    if team_ids:
        form_all_pit_entries = PitScoutingData.query.filter(PitScoutingData.team_id.in_(team_ids)).all()
    else:
        form_all_pit_entries = []

    # Split into local (not uploaded) and server (uploaded) sets for UI
    scouted_local_ids = set()
    scouted_server_ids = set()
    scouted_local_numbers = set()
    scouted_server_numbers = set()
    for e in form_all_pit_entries:
        try:
            if e.team_id:
                if e.is_uploaded:
                    scouted_server_ids.add(e.team_id)
                else:
                    scouted_local_ids.add(e.team_id)
            if hasattr(e, 'team') and e.team and hasattr(e.team, 'team_number'):
                if e.is_uploaded:
                    scouted_server_numbers.add(e.team.team_number)
                else:
                    scouted_local_numbers.add(e.team.team_number)
        except Exception:
            continue

    # JSON-serializable teams for optional JS use
    teams_for_js = []
    for t in teams:
        try:
            teams_for_js.append({
                'id': t.id,
                'team_number': t.team_number,
                'team_name': t.team_name or ''
            })
        except Exception:
            continue

    return render_template('scouting/pit_form.html', 
                          pit_data=pit_data,
                          pit_config=pit_config,
                          edit_mode=True,
                          teams=teams,
                          current_event=current_event,
                          all_pit_data=form_all_pit_entries,
                          scouted_local_ids=list(scouted_local_ids),
                          scouted_server_ids=list(scouted_server_ids),
                          scouted_local_numbers=list(scouted_local_numbers),
                          scouted_server_numbers=list(scouted_server_numbers),
                          teams_for_js=teams_for_js,
                          **get_theme_context())

@bp.route('/sync/status')
@login_required
def sync_status():
    """Get sync status for local storage and WebSocket connectivity"""
    unuploaded_count = PitScoutingData.query.filter_by(is_uploaded=False).count()
    total_count = PitScoutingData.query.count()
    
    # Get current event (team-scoped/alliance-aware)
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    return jsonify({
        'unuploaded_count': unuploaded_count,
        'total_count': total_count,
        'sync_percentage': (total_count - unuploaded_count) / total_count * 100 if total_count > 0 else 100,
        'server_enabled': True,  # WebSocket sync is always enabled
        'server_available': True,  # WebSocket sync is always available
        'server_url': 'WebSocket (Real-time)',
        'device_id': 'N/A',
        'last_sync': 'Real-time',
        'sync_type': 'websocket',
        'event_id': current_event.id if current_event else None,
        'event_name': current_event.name if current_event else 'No event'
    })

@bp.route('/upload', methods=['POST'])
@login_required
def upload():
    """Mark all unuploaded pit scouting data as uploaded (for WebSocket sync)"""
    try:
        # Get current event
        game_config = current_app.config.get('GAME_CONFIG', {})
        current_event_code = game_config.get('current_event_code')
        current_event = None
        if current_event_code:
            current_event = get_event_by_code(current_event_code)
        
        # Get unuploaded data
        unuploaded_data = PitScoutingData.query.filter_by(is_uploaded=False).all()
        
        if not unuploaded_data:
            return jsonify({
                'success': True,
                'uploaded_count': 0,
                'message': 'No data to upload.'
            })
        
        # Mark data as uploaded (since WebSocket sync handles real-time updates)
        for pit_data in unuploaded_data:
            pit_data.is_uploaded = True
            pit_data.upload_timestamp = datetime.now(timezone.utc)
        
        db.session.commit()
        
        # Emit sync status update
        if current_event:
            emit_pit_sync_status(current_event.id, {
                'unuploaded_count': 0,
                'total_count': PitScoutingData.query.count(),
                'message': f'Marked {len(unuploaded_data)} entries as uploaded'
            })
        
        flash(f'Successfully marked {len(unuploaded_data)} pit scouting entries as uploaded!', 'success')
        
        return jsonify({
            'success': True,
            'uploaded_count': len(unuploaded_data),
            'message': f'Successfully marked {len(unuploaded_data)} pit scouting entries as uploaded!'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Upload failed: {str(e)}'
        }), 500

@bp.route('/export')
@login_required
def export():
    """Export all pit scouting data as JSON"""
    pit_data = PitScoutingData.query.order_by(PitScoutingData.timestamp.desc()).all()
    
    export_data = []
    for entry in pit_data:
        export_data.append(entry.to_dict())
    
    return jsonify({
        'pit_scouting_data': export_data,
        'export_timestamp': datetime.now(timezone.utc).isoformat(),
        'total_entries': len(export_data)
    })

@bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    """Delete pit scouting data"""
    pit_data = PitScoutingData.query.get_or_404(id)
    
    # Check if user can delete this data
    if not current_user.has_role('admin') and pit_data.scout_id != current_user.id:
        flash('You can only delete your own pit scouting data', 'error')
        return redirect(url_for('pit_scouting.view', id=id))
    
    try:
        team_number = pit_data.team.team_number
        event_id = pit_data.event_id
        pit_data_dict = pit_data.to_dict()  # Get data before deletion
        
        db.session.delete(pit_data)
        db.session.commit()
        
        # Emit real-time update
        if event_id:
            emit_pit_data_update(event_id, 'deleted', pit_data_dict)
        
        flash(f'Pit scouting data for Team {team_number} deleted successfully!', 'success')
        return redirect(url_for('pit_scouting.list'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting pit scouting data: {str(e)}', 'error')
        return redirect(url_for('pit_scouting.view', id=id))

@bp.route('/config')
@login_required
def config():
    """View pit scouting configuration"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to view pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    # Allow viewing a specific team's instance config via ?team=<team_number>
    team_num = request.args.get('team')
    if team_num:
        try:
            team_num_int = int(team_num)
        except Exception:
            team_num_int = None
    else:
        team_num_int = None

    if team_num_int is not None:
        from app.utils.config_manager import load_pit_config
        pit_config = load_pit_config(team_number=team_num_int)
    else:
        # If the user has a scouting team preference, prefer the team's instance file
        try:
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and getattr(current_user, 'scouting_team_number', None):
                from app.utils.config_manager import load_pit_config
                candidate = load_pit_config(team_number=current_user.scouting_team_number)
                if candidate:
                    pit_config = candidate
                else:
                    pit_config = get_effective_pit_config()
            else:
                pit_config = get_effective_pit_config()
        except Exception:
            pit_config = get_effective_pit_config()

    # Provide list of teams for admins to choose from in the UI
    teams = Team.query.order_by(Team.team_number).all()

    return render_template('scouting/pit_config.html', pit_config=pit_config, teams=teams, selected_team=team_num_int, **get_theme_context())

@bp.route('/config/edit', methods=['GET', 'POST'])
@login_required
def config_edit():
    """Edit pit scouting configuration"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to edit pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    if request.method == 'GET':
        # Import here to avoid circular imports
        from app.utils.config_manager import get_available_default_configs
        default_configs = get_available_default_configs()
        # Allow admin to edit a specific team's instance config by passing
        # ?team=<team_number> — falls back to current_user-scoped config.
        team_num = request.args.get('team')
        if team_num:
            try:
                team_num_int = int(team_num)
            except Exception:
                team_num_int = None
        else:
            team_num_int = None

        # Always load the current user's scouting team pit config
        pit_config = get_current_pit_config()

        teams = Team.query.order_by(Team.team_number).all()
        return render_template('config/pit_editor.html', pit_config=pit_config, default_configs=default_configs, teams=teams, selected_team=None, **get_theme_context())
    
    if request.method == 'POST':
        try:
            # Get the JSON data from the form
            config_json = request.form.get('config_json')
            
            # Validate JSON
            pit_config = json.loads(config_json)
            
            # Basic validation
            if 'pit_scouting' not in pit_config:
                flash('Configuration must contain a "pit_scouting" section', 'error')
                return redirect(url_for('pit_scouting.config_edit'))
            
            if 'sections' not in pit_config['pit_scouting']:
                flash('Pit scouting configuration must contain a "sections" array', 'error')
                return redirect(url_for('pit_scouting.config_edit'))
            
            # Validate sections
            for section in pit_config['pit_scouting']['sections']:
                if 'id' not in section or 'name' not in section or 'elements' not in section:
                    flash('Each section must have id, name, and elements', 'error')
                    return redirect(url_for('pit_scouting.config_edit'))
                
                # Validate elements
                for element in section['elements']:
                    required_fields = ['id', 'perm_id', 'name', 'type']
                    for field in required_fields:
                        if field not in element:
                            flash(f'Element missing required field: {field}', 'error')
                            return redirect(url_for('pit_scouting.config_edit'))
            
            # Save new configuration: always save to the current user's scouting
            # team instance file (admins must belong to a team for this to work).
            save_team = None
            try:
                if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and getattr(current_user, 'scouting_team_number', None):
                    save_team = current_user.scouting_team_number
            except Exception:
                save_team = None

            # Save to the user's team instance file
            if save_pit_config(pit_config, team_number=save_team):
                flash('Pit scouting configuration updated successfully!', 'success')
            else:
                flash('Error saving pit scouting configuration.', 'danger')
            return redirect(url_for('pit_scouting.config'))
            
        except json.JSONDecodeError as e:
            flash(f'Invalid JSON: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error saving configuration: {str(e)}', 'error')
    
    # Load current configuration for editing — always use current user's
    # team-specific pit_config when available.
    pit_config = get_current_pit_config()
    config_json = json.dumps(pit_config, indent=2)
    teams = Team.query.order_by(Team.team_number).all()
    return render_template('scouting/pit_config_edit.html', 
                          config_json=config_json,
                          teams=teams,
                          selected_team=team_num_int,
                          **get_theme_context())

@bp.route('/config/reset', methods=['POST'])
@login_required
def config_reset():
    """Reset pit configuration to a default template"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to reset pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    try:
        from app.utils.config_manager import reset_config_to_default
        
        default_file = request.form.get('default_config')
        
        if not default_file:
            flash('No default configuration selected', 'error')
            return redirect(url_for('pit_scouting.config_edit'))
        
        success, message = reset_config_to_default(default_file, 'pit')
        
        if success:
            flash(message, 'success')
        else:
            flash(f'Error: {message}', 'error')
            
        return redirect(url_for('pit_scouting.config_edit'))
        
    except Exception as e:
        flash(f'Error resetting configuration: {str(e)}', 'error')
        return redirect(url_for('pit_scouting.config_edit'))

@bp.route('/config/simple-edit')
@login_required
def config_simple_edit():
    """Simple GUI-based pit configuration editor"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to edit pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    # Always load the current user's scouting team pit config
    pit_config = get_current_pit_config()

    teams = Team.query.order_by(Team.team_number).all()
    # Provide available defaults to the simple editor for reset capability
    from app.utils.config_manager import get_available_default_configs
    default_configs = get_available_default_configs()
    return render_template('scouting/pit_config_simple.html', pit_config=pit_config, teams=teams, default_configs=default_configs, selected_team=None, **get_theme_context())

@bp.route('/config/simple-save', methods=['POST'])
@login_required
def config_simple_save():
    """Save pit configuration from simple editor"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to save pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    try:
        # Debug: Print form data
        print("Form data received:")
        for key, value in request.form.items():
            print(f"  {key}: {value}")
        
        # Always save to the current user's scouting team instance config
        # Editors should operate on the current user's team only.
        save_team = getattr(current_user, 'scouting_team_number', None)

        # Build updated config
        updated_config = {
            "pit_scouting": {
                "title": request.form.get('title', 'Pit Scouting'),
                "description": request.form.get('description', ''),
                "sections": []
            }
        }
        
        # Process sections
        section_indices = set()
        for key in request.form.keys():
            if key.startswith('section_id_'):
                index = key.split('_')[-1]
                section_indices.add(int(index))
        
        print(f"Section indices found: {section_indices}")
        
        for section_index in sorted(section_indices):
            section_id = request.form.get(f'section_id_{section_index}')
            section_name = request.form.get(f'section_name_{section_index}')
            
            print(f"Processing section {section_index}: {section_id} - {section_name}")
            
            if section_id and section_name:
                section = {
                    "id": section_id,
                    "name": section_name,
                    "elements": []
                }
                
                # Process elements for this section
                element_indices = set()
                for key in request.form.keys():
                    if key.startswith(f'element_id_{section_index}_'):
                        index = key.split('_')[-1]
                        element_indices.add(int(index))
                
                print(f"  Element indices for section {section_index}: {element_indices}")
                
                for element_index in sorted(element_indices):
                    element_id = request.form.get(f'element_id_{section_index}_{element_index}')
                    element_name = request.form.get(f'element_name_{section_index}_{element_index}')
                    element_type = request.form.get(f'element_type_{section_index}_{element_index}')
                    
                    print(f"    Processing element {element_index}: {element_id} - {element_name} ({element_type})")
                    
                    if element_id and element_name and element_type:
                        element = {
                            "id": element_id,
                            "perm_id": element_id,
                            "name": element_name,
                            "type": element_type
                        }
                        
                        # Add required field
                        if request.form.get(f'element_required_{section_index}_{element_index}'):
                            element["required"] = True
                        
                        # Add default value if provided
                        default_value = request.form.get(f'element_default_{section_index}_{element_index}')
                        if default_value:
                            element["default"] = parse_default_value(default_value, element_type)
                        
                        # Add placeholder if provided
                        placeholder = request.form.get(f'element_placeholder_{section_index}_{element_index}')
                        if placeholder:
                            element["placeholder"] = placeholder
                        
                        # Handle validation for number fields
                        if element_type == 'number':
                            validation = {}
                            min_val = request.form.get(f'element_min_{section_index}_{element_index}')
                            max_val = request.form.get(f'element_max_{section_index}_{element_index}')
                            if min_val:
                                validation["min"] = int(min_val)
                            if max_val:
                                validation["max"] = int(max_val)
                            if validation:
                                element["validation"] = validation
                        
                        # Handle options for select/multiselect fields with per-option points
                        if element_type in ['select', 'multiselect']:
                            options = []
                            points_dict = {}
                            option_idx = 0
                            while True:
                                opt_val = request.form.get(f'element_option_value_{section_index}_{element_index}_{option_idx}')
                                opt_label = request.form.get(f'element_option_label_{section_index}_{element_index}_{option_idx}')
                                opt_points = request.form.get(f'element_option_points_{section_index}_{element_index}_{option_idx}')
                                if opt_val is None:
                                    break
                                options.append({"value": opt_val, "label": opt_label if opt_label else opt_val})
                                try:
                                    points_dict[opt_val] = float(opt_points) if opt_points is not None else 0
                                except ValueError:
                                    points_dict[opt_val] = 0
                                option_idx += 1
                            if options:
                                element["options"] = options
                                element["points"] = points_dict
                        
                        section["elements"].append(element)
                
                updated_config["pit_scouting"]["sections"].append(section)
        
        print(f"Final config: {json.dumps(updated_config, indent=2)}")
        
        # Save the configuration to the current user's team
        if save_pit_config(updated_config, team_number=save_team):
            flash('Pit scouting configuration updated successfully!', 'success')
        else:
            flash('Error saving pit scouting configuration.', 'danger')
        return redirect(url_for('pit_scouting.config'))
        
    except Exception as e:
        print(f"Error in config_simple_save: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error updating configuration: {str(e)}', 'error')
        return redirect(url_for('pit_scouting.config_simple_edit'))

def parse_default_value(value, element_type):
    """Parse default value based on element type"""
    if element_type == 'boolean':
        return value.lower() in ('true', '1', 'yes', 'on') if isinstance(value, str) else bool(value)
    elif element_type == 'number':
        try:
            return int(value) if value else 0
        except ValueError:
            return 0
    else:
        return value if value else ""

@bp.route('/config/backup')
@login_required
def config_backup():
    """Download backup of pit scouting configuration"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to download pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    try:
        # Download the current user's scouting team pit config
        pit_config = get_current_pit_config()
        
        from flask import make_response
        response = make_response(json.dumps(pit_config, indent=2))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = 'attachment; filename=pit_config_backup.json'
        
        return response
        
    except Exception as e:
        flash(f'Error creating backup: {str(e)}', 'error')
        return redirect(url_for('pit_scouting.config'))

@bp.route('/sync/download', methods=['POST'])
@login_required
def sync_download():
    """Download pit scouting data from server"""
    sync_manager = SyncManager()
    
    # Check if sync is enabled and server is available
    if not sync_manager.enabled:
        return jsonify({
            'success': False,
            'error': 'Server sync is not enabled. Please check your sync configuration.'
        }), 400
    
    if not sync_manager.is_server_available():
        return jsonify({
            'success': False,
            'error': 'Sync server is not available. Please check your internet connection and try again.'
        }), 503
    
    try:
        # Get current event
        game_config = current_app.config.get('GAME_CONFIG', {})
        current_event_code = game_config.get('current_event_code')
        current_event = None
        if current_event_code:
            current_event = get_event_by_code(current_event_code)
        
        # Get last sync timestamp
        last_sync = sync_manager.get_last_sync_timestamp()
        
        # Download data from server
        download_result = sync_manager.download_pit_data(
            since_timestamp=last_sync,
            event_id=current_event.id if current_event else None
        )
        
        if download_result['success']:
            new_data_count = 0
            updated_data_count = 0
            
            # Process downloaded data
            for item_data in download_result.get('data', []):
                # Check if this data already exists locally
                existing_data = PitScoutingData.query.filter_by(
                    local_id=item_data.get('local_id')
                ).first()
                
                if existing_data:
                    # Update existing data if remote version is newer
                    remote_timestamp = datetime.fromisoformat(item_data['timestamp'].replace('Z', '+00:00'))
                    if remote_timestamp > existing_data.timestamp:
                        existing_data.data_json = json.dumps(item_data.get('data', {}))
                        existing_data.timestamp = remote_timestamp
                        if item_data.get('is_uploaded'):
                            existing_data.is_uploaded = True
                            existing_data.upload_timestamp = datetime.fromisoformat(item_data['upload_timestamp'].replace('Z', '+00:00'))
                        updated_data_count += 1
                else:
                    # Create new local data entry
                    team = Team.query.filter_by(team_number=item_data['team_number']).first()
                    if not team:
                        team = Team(team_number=item_data['team_number'])
                        db.session.add(team)
                        db.session.flush()  # Get the team ID
                    
                    new_pit_data = PitScoutingData(
                        local_id=item_data.get('local_id'),
                        team_id=team.id,
                        event_id=item_data.get('event_id'),
                        scout_name=item_data.get('scout_name'),
                        scout_id=item_data.get('scout_id'),
                        data_json=json.dumps(item_data.get('data', {})),
                        is_uploaded=item_data.get('is_uploaded', False),
                        device_id=item_data.get('device_id'),
                        timestamp=datetime.fromisoformat(item_data['timestamp'].replace('Z', '+00:00'))
                    )
                    
                    if item_data.get('upload_timestamp'):
                        new_pit_data.upload_timestamp = datetime.fromisoformat(item_data['upload_timestamp'].replace('Z', '+00:00'))
                    
                    db.session.add(new_pit_data)
                    new_data_count += 1
            
            db.session.commit()
            
            # Update last sync timestamp
            sync_manager.update_last_sync_timestamp()
            
            message = f'Downloaded {new_data_count} new entries and updated {updated_data_count} existing entries from server.'
            flash(message, 'success')
            
            return jsonify({
                'success': True,
                'new_data_count': new_data_count,
                'updated_data_count': updated_data_count,
                'message': message
            })
        else:
            return jsonify({
                'success': False,
                'error': download_result.get('error', 'Download failed')
            }), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Download failed: {str(e)}'
        }), 500

@bp.route('/sync/full', methods=['POST'])
@login_required
def sync_full():
    """Perform full bidirectional sync - upload local data and download remote data"""
    sync_manager = SyncManager()
    
    # Check if sync is enabled and server is available
    if not sync_manager.enabled:
        return jsonify({
            'success': False,
            'error': 'Server sync is not enabled. Please check your sync configuration.'
        }), 400
    
    if not sync_manager.is_server_available():
        return jsonify({
            'success': False,
            'error': 'Sync server is not available. Please check your internet connection and try again.'
        }), 503
    
    try:
        # Get current event
        game_config = current_app.config.get('GAME_CONFIG', {})
        current_event_code = game_config.get('current_event_code')
        current_event = None
        if current_event_code:
            current_event = get_event_by_code(current_event_code)
        
        # Get all local data for context
        if current_event:
            all_local_data = PitScoutingData.query.filter_by(event_id=current_event.id).all()
        else:
            all_local_data = PitScoutingData.query.all()
        
        # Get unuploaded data
        unuploaded_data = PitScoutingData.query.filter_by(is_uploaded=False).all()
        
        # Perform sync
        sync_result = sync_manager.sync_pit_data(
            unuploaded_data,
            event_id=current_event.id if current_event else None
        )
        
        # Process results
        if sync_result['upload_success'] and unuploaded_data:
            # Mark uploaded data as uploaded
            for pit_data in unuploaded_data:
                pit_data.is_uploaded = True
                pit_data.upload_timestamp = datetime.now(timezone.utc)
        
        new_data_count = 0
        updated_data_count = 0
        
        if sync_result['download_success']:
            # Process downloaded data
            for item_data in sync_result.get('new_data', []):
                # Check if this data already exists locally
                existing_data = PitScoutingData.query.filter_by(
                    local_id=item_data.get('local_id')
                ).first()
                
                if existing_data:
                    # Update existing data if remote version is newer
                    remote_timestamp = datetime.fromisoformat(item_data['timestamp'].replace('Z', '+00:00'))
                    if remote_timestamp > existing_data.timestamp:
                        existing_data.data_json = json.dumps(item_data.get('data', {}))
                        existing_data.timestamp = remote_timestamp
                        if item_data.get('is_uploaded'):
                            existing_data.is_uploaded = True
                            existing_data.upload_timestamp = datetime.fromisoformat(item_data['upload_timestamp'].replace('Z', '+00:00'))
                        updated_data_count += 1
                else:
                    # Create new local data entry
                    team = Team.query.filter_by(team_number=item_data['team_number']).first()
                    if not team:
                        team = Team(team_number=item_data['team_number'])
                        db.session.add(team)
                        db.session.flush()  # Get the team ID
                    
                    new_pit_data = PitScoutingData(
                        local_id=item_data.get('local_id'),
                        team_id=team.id,
                        event_id=item_data.get('event_id'),
                        scout_name=item_data.get('scout_name'),
                        scout_id=item_data.get('scout_id'),
                        data_json=json.dumps(item_data.get('data', {})),
                        is_uploaded=item_data.get('is_uploaded', False),
                        device_id=item_data.get('device_id'),
                        timestamp=datetime.fromisoformat(item_data['timestamp'].replace('Z', '+00:00'))
                    )
                    
                    if item_data.get('upload_timestamp'):
                        new_pit_data.upload_timestamp = datetime.fromisoformat(item_data['upload_timestamp'].replace('Z', '+00:00'))
                    
                    db.session.add(new_pit_data)
                    new_data_count += 1
        
        db.session.commit()
        
        # Update last sync timestamp
        sync_manager.update_last_sync_timestamp()
        
        # Build response message
        messages = []
        if sync_result['upload_success']:
            messages.append(f"Uploaded {sync_result['uploaded_count']} entries to server")
        if sync_result['download_success']:
            messages.append(f"Downloaded {new_data_count} new entries and updated {updated_data_count} existing entries")
        
        if sync_result['errors']:
            messages.extend([f"Error: {error}" for error in sync_result['errors']])
        
        message = '. '.join(messages) if messages else 'Sync completed successfully'
        
        # Determine overall success
        overall_success = (sync_result['upload_success'] or len(unuploaded_data) == 0) and \
                         (sync_result['download_success'] or len(sync_result.get('errors', [])) == 0)
        
        if overall_success:
            flash(f'Sync completed! {message}', 'success')
        else:
            flash(f'Sync completed with issues: {message}', 'warning')
        
        return jsonify({
            'success': overall_success,
            'uploaded_count': sync_result['uploaded_count'],
            'new_data_count': new_data_count,
            'updated_data_count': updated_data_count,
            'message': message,
            'errors': sync_result.get('errors', [])
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Sync failed: {str(e)}'
        }), 500

@bp.route('/sync/config', methods=['GET', 'POST'])
@login_required
def sync_config():
    """View and edit sync configuration"""
    # Sync configuration for pit scouting has been removed/disabled.
    # Redirect back to the main pit config page with an informational message.
    flash('Sync configuration for pit scouting has been removed. Use the main configuration editor instead.', 'info')
    return redirect(url_for('pit_scouting.config'))

@bp.route('/sync/test', methods=['POST'])
@login_required
def sync_test():
    """Test sync server connection"""
    if not current_user.has_role('admin'):
        return jsonify({
            'success': False,
            'error': 'Admin access required'
        }), 403
    
    try:
        sync_manager = SyncManager()
        
        if not sync_manager.enabled:
            return jsonify({
                'success': False,
                'error': 'Sync is not enabled'
            })
        
        if not sync_manager.base_url:
            return jsonify({
                'success': False,
                'error': 'Sync server URL not configured'
            })
        
        # Test server connection
        server_available = sync_manager.is_server_available()
        
        if server_available:
            return jsonify({
                'success': True,
                'message': 'Successfully connected to sync server',
                'server_url': sync_manager.base_url
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Unable to connect to sync server'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Connection test failed: {str(e)}'
        }), 500

# SocketIO event handlers for real-time sync
@socketio.on('join_pit_room')
def on_join_pit_room(data):
    """Join a room for pit scouting updates"""
    event_id = data.get('event_id')
    if event_id:
        join_room(f'pit_event_{event_id}')
        emit('status', {'msg': f'Joined pit scouting room for event {event_id}'})

@socketio.on('leave_pit_room')
def on_leave_pit_room(data):
    """Leave a room for pit scouting updates"""
    event_id = data.get('event_id')
    if event_id:
        leave_room(f'pit_event_{event_id}')
        emit('status', {'msg': f'Left pit scouting room for event {event_id}'})

def emit_pit_data_update(event_id, action, data):
    """Emit pit data update to all clients in the room"""
    socketio.emit('pit_data_updated', {
        'action': action,  # 'added', 'updated', 'deleted'
        'data': data,
        'event_id': event_id
    }, room=f'pit_event_{event_id}')

def emit_pit_sync_status(event_id, status):
    """Emit sync status update to all clients in the room"""
    socketio.emit('pit_sync_status', {
        'status': status,
        'event_id': event_id
    }, room=f'pit_event_{event_id}')

@bp.route('/data')
@login_required
def pit_data():
    """AJAX endpoint for pit scouting data - used for real-time config updates"""
    try:
        # Get current configurations (alliance-aware)
        pit_config = get_effective_pit_config()
        
        # Get current event based on main game configuration
        game_config = current_app.config.get('GAME_CONFIG', {})
        current_event_code = game_config.get('current_event_code')
        current_event = None
        if current_event_code:
            current_event = get_event_by_code(current_event_code)
        
        # Get teams filtered by the current event if available
        if current_event:
            teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
        else:
            teams = filter_teams_by_scouting_team().all()
        
        # Get pit scouting data
        pit_data = PitScoutingData.query.join(Team).filter(
            Team.id.in_([team.id for team in teams])
        ).all()
        
        # Get scouted teams count
        scouted_teams = len(set([data.team_id for data in pit_data]))
        total_teams = len(teams)
        
        # Prepare data for JSON response
        teams_data = [{'id': team.id, 'team_number': team.team_number, 'name': team.name or ''} for team in teams]
        
        pit_data_serialized = []
        for data in pit_data:
            pit_data_serialized.append({
                'id': data.id,
                'team_id': data.team_id,
                'team_number': data.team.team_number,
                'scout_name': data.scout.username if data.scout else 'Unknown',
                'timestamp': data.timestamp.isoformat() if data.timestamp else None,
                'data': data.data
            })
        
        return jsonify({
            'success': True,
            'pit_config': pit_config,
            'current_event': {
                'id': current_event.id if current_event else None,
                'name': current_event.name if current_event else None,
                'code': current_event.code if current_event else None
            } if current_event else None,
            'teams': teams_data,
            'pit_data': pit_data_serialized,
            'stats': {
                'scouted_teams': scouted_teams,
                'total_teams': total_teams,
                'completion_percentage': round((scouted_teams / total_teams * 100) if total_teams > 0 else 0, 1)
            },
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in pit_data endpoint: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
