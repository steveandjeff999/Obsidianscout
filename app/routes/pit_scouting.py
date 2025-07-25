from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from app.models import Team, Event, PitScoutingData
from app import db, socketio
import json
import uuid
from datetime import datetime
from app.utils.config_manager import get_id_to_perm_id_mapping
from app.utils.sync_manager import SyncManager
import os
from app.utils.theme_manager import ThemeManager

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('pit_scouting', __name__, url_prefix='/pit-scouting')

def load_pit_config():
    """Load pit scouting configuration from JSON file"""
    try:
        config_path = os.path.join(os.getcwd(), 'config', 'pit_config.json')
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading pit configuration: {e}")
        return {"pit_scouting": {"title": "Pit Scouting", "sections": []}}

@bp.route('/')
@login_required
def index():
    """Pit scouting dashboard page"""
    pit_config = load_pit_config()
    
    # Get current event based on main game configuration
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = current_event.teams
    else:
        teams = Team.query.all()
    
    # Get recent pit scouting data
    recent_pit_data = PitScoutingData.query.order_by(PitScoutingData.timestamp.desc()).limit(10).all()
    
    # Get statistics
    total_teams_scouted = PitScoutingData.query.count()
    unuploaded_count = PitScoutingData.query.filter_by(is_uploaded=False).count()
    
    return render_template('scouting/pit_index.html', 
                          teams=teams, 
                          pit_data=recent_pit_data,
                          pit_config=pit_config,
                          current_event=current_event,
                          total_teams_scouted=total_teams_scouted,
                          unuploaded_count=unuploaded_count,
                          **get_theme_context())

@bp.route('/form', methods=['GET', 'POST'])
@login_required
def form():
    """Dynamic pit scouting form"""
    pit_config = load_pit_config()
    
    # Get current event based on main game configuration
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = current_event.teams
    else:
        teams = Team.query.all()
    
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
            
            if existing_data:
                flash(f'You have already scouted Team {team_number}. You can edit your existing data.', 'warning')
                return redirect(url_for('pit_scouting.view', id=existing_data.id))
            
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
    return render_template('scouting/pit_form.html', 
                          teams=teams, 
                          pit_config=pit_config,
                          current_event=current_event,
                          **get_theme_context())

@bp.route('/list')
@login_required
def list():
    """Redirect to dynamic list view"""
    return redirect(url_for('pit_scouting.list_dynamic'))

@bp.route('/list-dynamic')
@login_required
def list_dynamic():
    """Dynamic pit scouting data display with auto-refresh"""
    pit_config = load_pit_config()
    
    # Get current event based on main game configuration
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    return render_template('scouting/pit_list_dynamic.html', 
                          pit_config=pit_config,
                          current_event=current_event,
                          **get_theme_context())

@bp.route('/api/list')
@login_required
def api_list():
    """API endpoint to get pit scouting data as JSON"""
    pit_config = load_pit_config()
    
    # Get current event based on main game configuration
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    # Filter by event if available
    if current_event:
        pit_data = PitScoutingData.query.filter_by(event_id=current_event.id).order_by(PitScoutingData.timestamp.desc()).all()
    else:
        pit_data = PitScoutingData.query.order_by(PitScoutingData.timestamp.desc()).all()
    
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
    pit_config = load_pit_config()
    pit_data = PitScoutingData.query.get_or_404(id)
    
    return render_template('scouting/pit_view.html', 
                          pit_data=pit_data,
                          pit_config=pit_config,
                          **get_theme_context())

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    """Edit existing pit scouting data"""
    pit_config = load_pit_config()
    pit_data = PitScoutingData.query.get_or_404(id)
    
    # Check if user can edit this data
    if not current_user.has_role('admin') and pit_data.scout_id != current_user.id:
        flash('You can only edit your own pit scouting data', 'error')
        return redirect(url_for('pit_scouting.view', id=id))
    
    if request.method == 'POST':
        try:
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
            
            # Emit real-time update
            if pit_data.event_id:
                emit_pit_data_update(pit_data.event_id, 'updated', pit_data.to_dict())
            
            flash('Pit scouting data updated successfully!', 'success')
            return redirect(url_for('pit_scouting.view', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating pit scouting data: {str(e)}', 'error')
    
    # For GET request, show the edit form
    return render_template('scouting/pit_form.html', 
                          pit_data=pit_data,
                          pit_config=pit_config,
                          edit_mode=True,
                          **get_theme_context())

@bp.route('/sync/status')
@login_required
def sync_status():
    """Get sync status for local storage and WebSocket connectivity"""
    unuploaded_count = PitScoutingData.query.filter_by(is_uploaded=False).count()
    total_count = PitScoutingData.query.count()
    
    # Get current event
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
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
            current_event = Event.query.filter_by(code=current_event_code).first()
        
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
            pit_data.upload_timestamp = datetime.utcnow()
        
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
        'export_timestamp': datetime.utcnow().isoformat(),
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
    
    pit_config = load_pit_config()
    return render_template('scouting/pit_config.html', pit_config=pit_config, **get_theme_context())

@bp.route('/config/edit', methods=['GET', 'POST'])
@login_required
def config_edit():
    """Edit pit scouting configuration"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to edit pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    config_path = os.path.join(os.getcwd(), 'config', 'pit_config.json')
    
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
            
            # Create backup
            backup_path = config_path + '.backup'
            if os.path.exists(config_path):
                import shutil
                shutil.copy2(config_path, backup_path)
            
            # Save new configuration
            with open(config_path, 'w') as f:
                json.dump(pit_config, f, indent=2)
            
            flash('Pit scouting configuration updated successfully!', 'success')
            return redirect(url_for('pit_scouting.config'))
            
        except json.JSONDecodeError as e:
            flash(f'Invalid JSON: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error saving configuration: {str(e)}', 'error')
    
    # Load current configuration for editing
    pit_config = load_pit_config()
    config_json = json.dumps(pit_config, indent=2)
    
    return render_template('scouting/pit_config_edit.html', 
                          config_json=config_json,
                          **get_theme_context())

@bp.route('/config/simple-edit')
@login_required
def config_simple_edit():
    """Simple GUI-based pit configuration editor"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to edit pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    pit_config = load_pit_config()
    return render_template('scouting/pit_config_simple.html', pit_config=pit_config, **get_theme_context())

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
        
        # Get current config as base
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
        
        # Save the configuration
        config_path = os.path.join(os.getcwd(), 'config', 'pit_config.json')
        
        # Create backup
        backup_path = config_path + '.backup'
        if os.path.exists(config_path):
            import shutil
            shutil.copy2(config_path, backup_path)
        
        # Write updated config
        with open(config_path, 'w') as f:
            json.dump(updated_config, f, indent=2)
        
        flash('Pit scouting configuration updated successfully! A backup was created.', 'success')
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

@bp.route('/config/reset', methods=['POST'])
@login_required
def config_reset():
    """Reset pit scouting configuration to default"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to reset pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    try:
        # REEFSCAPE 2025 Configuration
        default_config = {
            "pit_scouting": {
                "title": "REEFSCAPE 2025 Pit Scouting",
                "description": "Collect detailed information about teams and their robots for REEFSCAPE 2025",
                "sections": [
                    {
                        "id": "team_info",
                        "name": "Team Information",
                        "elements": [
                            {
                                "id": "team_number",
                                "perm_id": "team_number",
                                "name": "Team Number",
                                "type": "number",
                                "required": True,
                                "validation": {
                                    "min": 1,
                                    "max": 99999
                                }
                            },
                            {
                                "id": "team_name",
                                "perm_id": "team_name",
                                "name": "Team Name",
                                "type": "text"
                            },
                            {
                                "id": "drive_team_experience",
                                "perm_id": "drive_team_experience",
                                "name": "Drive Team Experience",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "rookie",
                                        "label": "Rookie (0-1 years)"
                                    },
                                    {
                                        "value": "experienced",
                                        "label": "Experienced (2-4 years)"
                                    },
                                    {
                                        "value": "veteran",
                                        "label": "Veteran (5+ years)"
                                    }
                                ]
                            },
                            {
                                "id": "programming_language",
                                "perm_id": "programming_language",
                                "name": "Programming Language",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "java",
                                        "label": "Java"
                                    },
                                    {
                                        "value": "cpp",
                                        "label": "C++"
                                    },
                                    {
                                        "value": "python",
                                        "label": "Python"
                                    },
                                    {
                                        "value": "labview",
                                        "label": "LabVIEW"
                                    },
                                    {
                                        "value": "other",
                                        "label": "Other"
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "id": "robot_design",
                        "name": "Robot Design & Drivetrain",
                        "elements": [
                            {
                                "id": "drivetrain_type",
                                "perm_id": "drivetrain_type",
                                "name": "Drivetrain Type",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "tank",
                                        "label": "Tank Drive"
                                    },
                                    {
                                        "value": "mecanum",
                                        "label": "Mecanum"
                                    },
                                    {
                                        "value": "swerve",
                                        "label": "Swerve"
                                    },
                                    {
                                        "value": "west_coast",
                                        "label": "West Coast Drive"
                                    },
                                    {
                                        "value": "other",
                                        "label": "Other"
                                    }
                                ]
                            },
                            {
                                "id": "drivetrain_motors",
                                "perm_id": "drivetrain_motors",
                                "name": "Number of Drive Motors",
                                "type": "number",
                                "validation": {
                                    "min": 1,
                                    "max": 12
                                }
                            },
                            {
                                "id": "motor_type",
                                "perm_id": "motor_type",
                                "name": "Drive Motor Type",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "neo",
                                        "label": "NEO"
                                    },
                                    {
                                        "value": "cim",
                                        "label": "CIM"
                                    },
                                    {
                                        "value": "falcon500",
                                        "label": "Falcon 500"
                                    },
                                    {
                                        "value": "kraken",
                                        "label": "Kraken X60"
                                    },
                                    {
                                        "value": "other",
                                        "label": "Other"
                                    }
                                ]
                            },
                            {
                                "id": "robot_weight",
                                "perm_id": "robot_weight",
                                "name": "Robot Weight (lbs)",
                                "type": "number",
                                "validation": {
                                    "min": 0,
                                    "max": 150
                                }
                            },
                            {
                                "id": "robot_height",
                                "perm_id": "robot_height",
                                "name": "Robot Height (inches)",
                                "type": "number",
                                "validation": {
                                    "min": 0,
                                    "max": 840
                                }
                            },
                            {
                                "id": "max_speed",
                                "perm_id": "max_speed",
                                "name": "Estimated Max Speed (ft/s)",
                                "type": "number",
                                "validation": {
                                    "min": 0,
                                    "max": 30
                                }
                            }
                        ]
                    },
                    {
                        "id": "coral_capabilities",
                        "name": "CORAL Capabilities",
                        "elements": [
                            {
                                "id": "can_score_coral",
                                "perm_id": "can_score_coral",
                                "name": "Can Score CORAL",
                                "type": "boolean"
                            },
                            {
                                "id": "coral_intake_method",
                                "perm_id": "coral_intake_method",
                                "name": "CORAL Intake Method",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "none",
                                        "label": "Cannot Intake"
                                    },
                                    {
                                        "value": "ground",
                                        "label": "Ground Pickup"
                                    },
                                    {
                                        "value": "station",
                                        "label": "Human Player Station"
                                    },
                                    {
                                        "value": "both",
                                        "label": "Both Ground and Station"
                                    }
                                ]
                            },
                            {
                                "id": "coral_levels",
                                "perm_id": "coral_levels",
                                "name": "CORAL Levels Robot Can Score",
                                "type": "multiselect",
                                "options": [
                                    {
                                        "value": "l1",
                                        "label": "Level 1"
                                    },
                                    {
                                        "value": "l2",
                                        "label": "Level 2"
                                    },
                                    {
                                        "value": "l3",
                                        "label": "Level 3"
                                    },
                                    {
                                        "value": "l4",
                                        "label": "Level 4"
                                    }
                                ]
                            },
                            {
                                "id": "coral_cycle_time",
                                "perm_id": "coral_cycle_time",
                                "name": "CORAL Cycle Time (seconds)",
                                "type": "number",
                                "validation": {
                                    "min": 0,
                                    "max": 150
                                }
                            }
                        ]
                    },
                    {
                        "id": "algae_capabilities",
                        "name": "ALGAE Capabilities",
                        "elements": [
                            {
                                "id": "can_score_algae",
                                "perm_id": "can_score_algae",
                                "name": "Can Score ALGAE",
                                "type": "boolean"
                            },
                            {
                                "id": "algae_intake_method",
                                "perm_id": "algae_intake_method",
                                "name": "ALGAE Intake Method",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "none",
                                        "label": "Cannot Intake"
                                    },
                                    {
                                        "value": "ground",
                                        "label": "Ground Pickup"
                                    },
                                    {
                                        "value": "station",
                                        "label": "Human Player Station"
                                    },
                                    {
                                        "value": "both",
                                        "label": "Both Ground and Station"
                                    }
                                ]
                            },
                            {
                                "id": "algae_locations",
                                "perm_id": "algae_locations",
                                "name": "ALGAE Scoring Locations",
                                "type": "multiselect",
                                "options": [
                                    {
                                        "value": "processor",
                                        "label": "Processor"
                                    },
                                    {
                                        "value": "net",
                                        "label": "Net"
                                    }
                                ]
                            },
                            {
                                "id": "algae_cycle_time",
                                "perm_id": "algae_cycle_time",
                                "name": "ALGAE Cycle Time (seconds)",
                                "type": "number",
                                "validation": {
                                    "min": 0,
                                    "max": 150
                                }
                            }
                        ]
                    },
                    {
                        "id": "autonomous_capabilities",
                        "name": "Autonomous Capabilities",
                        "elements": [
                            {
                                "id": "autonomous_leave_zone",
                                "perm_id": "autonomous_leave_zone",
                                "name": "Can Leave Starting Zone in Auto",
                                "type": "boolean"
                            },
                            {
                                "id": "autonomous_score_coral",
                                "perm_id": "autonomous_score_coral",
                                "name": "Can Score CORAL in Auto",
                                "type": "boolean"
                            },
                            {
                                "id": "autonomous_score_algae",
                                "perm_id": "autonomous_score_algae",
                                "name": "Can Score ALGAE in Auto",
                                "type": "boolean"
                            },
                            {
                                "id": "autonomous_collect_pieces",
                                "perm_id": "autonomous_collect_pieces",
                                "name": "Can Collect Game Pieces in Auto",
                                "type": "boolean"
                            },
                            {
                                "id": "autonomous_starting_position",
                                "perm_id": "autonomous_starting_position",
                                "name": "Preferred Starting Position",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "left",
                                        "label": "Left"
                                    },
                                    {
                                        "value": "center",
                                        "label": "Center"
                                    },
                                    {
                                        "value": "right",
                                        "label": "Right"
                                    },
                                    {
                                        "value": "flexible",
                                        "label": "Flexible"
                                    }
                                ]
                            },
                            {
                                "id": "autonomous_points_estimate",
                                "perm_id": "autonomous_points_estimate",
                                "name": "Estimated Auto Points",
                                "type": "number",
                                "validation": {
                                    "min": 0,
                                    "max": 50
                                }
                            }
                        ]
                    },
                    {
                        "id": "climb_capabilities",
                        "name": "Climb & Endgame",
                        "elements": [
                            {
                                "id": "can_climb",
                                "perm_id": "can_climb",
                                "name": "Can Climb",
                                "type": "boolean"
                            },
                            {
                                "id": "climb_levels",
                                "perm_id": "climb_levels",
                                "name": "Climb Levels Achieved",
                                "type": "multiselect",
                                "options": [
                                    {
                                        "value": "none",
                                        "label": "none"
                                    },
                                    {
                                        "value": "park",
                                        "label": "park"
                                    },
                                    {
                                        "value": "shallow",
                                        "label": "Shallow Climb"
                                    },
                                    {
                                        "value": "deep",
                                        "label": "Deep Climb"
                                    }
                                ]
                            },
                            {
                                "id": "climb_time",
                                "perm_id": "climb_time",
                                "name": "Climb Time (seconds)",
                                "type": "number",
                                "validation": {
                                    "min": 0,
                                    "max": 60
                                }
                            }
                        ]
                    },
                    {
                        "id": "strategy_notes",
                        "name": "Strategy & Notes",
                        "elements": [
                            {
                                "id": "robot_strengths",
                                "perm_id": "robot_strengths",
                                "name": "Robot Strengths",
                                "type": "textarea",
                                "placeholder": "What are this robot's main strengths and capabilities?"
                            },
                            {
                                "id": "robot_weaknesses",
                                "perm_id": "robot_weaknesses",
                                "name": "Areas for Improvement",
                                "type": "textarea",
                                "placeholder": "What areas could this robot improve on?"
                            },
                            {
                                "id": "alliance_strategy",
                                "perm_id": "alliance_strategy",
                                "name": "Alliance Strategy Notes",
                                "type": "textarea",
                                "placeholder": "How would this robot fit into alliance strategy?"
                            },
                            {
                                "id": "reliability_concerns",
                                "perm_id": "reliability_concerns",
                                "name": "Reliability Concerns",
                                "type": "textarea",
                                "placeholder": "Any known reliability issues or concerns?"
                            },
                            {
                                "id": "driver_skill_level",
                                "perm_id": "driver_skill_level",
                                "name": "Driver Skill Level",
                                "type": "select",
                                "options": [
                                    {
                                        "value": "novice",
                                        "label": "Novice"
                                    },
                                    {
                                        "value": "intermediate",
                                        "label": "Intermediate"
                                    },
                                    {
                                        "value": "advanced",
                                        "label": "Advanced"
                                    },
                                    {
                                        "value": "expert",
                                        "label": "Expert"
                                    }
                                ]
                            },
                            {
                                "id": "additional_notes",
                                "perm_id": "additional_notes",
                                "name": "Additional Notes",
                                "type": "textarea",
                                "placeholder": "Any other observations or notes about this team"
                            }
                        ]
                    }
                ]
            }
        }
        
        config_path = os.path.join(os.getcwd(), 'config', 'pit_config.json')
        
        # Create backup
        backup_path = config_path + '.backup'
        if os.path.exists(config_path):
            import shutil
            shutil.copy2(config_path, backup_path)
        
        # Save default configuration
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        
        flash('Pit scouting configuration reset to default!', 'success')
        return redirect(url_for('pit_scouting.config'))
        
    except Exception as e:
        flash(f'Error resetting configuration: {str(e)}', 'error')
        return redirect(url_for('pit_scouting.config'))

@bp.route('/config/backup')
@login_required
def config_backup():
    """Download backup of pit scouting configuration"""
    if not current_user.has_role('admin'):
        flash('You must be an admin to download pit scouting configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    try:
        pit_config = load_pit_config()
        
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
            current_event = Event.query.filter_by(code=current_event_code).first()
        
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
            current_event = Event.query.filter_by(code=current_event_code).first()
        
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
                pit_data.upload_timestamp = datetime.utcnow()
        
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
    if not current_user.has_role('admin'):
        flash('You must be an admin to view sync configuration', 'error')
        return redirect(url_for('pit_scouting.index'))
    
    if request.method == 'POST':
        try:
            # Get form data
            enabled = request.form.get('enabled') == 'on'
            base_url = request.form.get('base_url', '').strip()
            api_key = request.form.get('api_key', '').strip()
            team_key = request.form.get('team_key', '').strip()
            timeout = int(request.form.get('timeout', 30))
            retry_attempts = int(request.form.get('retry_attempts', 3))
            
            # Build config
            sync_config = {
                "sync_server": {
                    "enabled": enabled,
                    "base_url": base_url,
                    "endpoints": {
                        "upload": "/pit-scouting/upload",
                        "download": "/pit-scouting/download",
                        "sync": "/pit-scouting/sync"
                    },
                    "auth": {
                        "api_key": api_key,
                        "team_key": team_key
                    },
                    "timeout": timeout,
                    "retry_attempts": retry_attempts
                }
            }
            
            # Save config
            config_path = os.path.join(os.getcwd(), 'config', 'sync_config.json')
            
            # Create backup
            backup_path = config_path + '.backup'
            if os.path.exists(config_path):
                import shutil
                shutil.copy2(config_path, backup_path)
            
            # Write new config
            with open(config_path, 'w') as f:
                json.dump(sync_config, f, indent=2)
            
            flash('Sync configuration updated successfully!', 'success')
            return redirect(url_for('pit_scouting.sync_config'))
            
        except Exception as e:
            flash(f'Error updating sync configuration: {str(e)}', 'error')
    
    # Load current config
    sync_manager = SyncManager()
    config = sync_manager.config.get('sync_server', {})
    
    return render_template('scouting/pit_sync_config.html', config=config, **get_theme_context())

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
