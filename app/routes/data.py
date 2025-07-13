from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from app.routes.auth import analytics_required
from app.models import Team, Match, Event, ScoutingData
from app import db
import pandas as pd
import json
import os
from werkzeug.utils import secure_filename
import qrcode
from io import BytesIO
import base64

bp = Blueprint('data', __name__, url_prefix='/data')

@bp.route('/')
@analytics_required
def index():
    """Data import/export dashboard"""
    # Get database statistics
    teams_count = Team.query.count()
    matches_count = Match.query.count()
    scouting_count = ScoutingData.query.count()
    
    return render_template('data/index.html', 
                          teams_count=teams_count,
                          matches_count=matches_count, 
                          scouting_count=scouting_count)

@bp.route('/import/excel', methods=['GET', 'POST'])
def import_excel():
    """Import data from Excel files"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and file.filename.endswith(('.xlsx', '.xls')):
            # Save file temporarily
            filename = secure_filename(file.filename)
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            try:
                # Process Excel file
                df = pd.read_excel(file_path)
                
                # Get game configuration
                game_config = current_app.config['GAME_CONFIG']
                
                # Process each row as scouting data
                records_added = 0
                records_updated = 0
                
                for _, row in df.iterrows():
                    # Extract basic information
                    try:
                        match_number = int(row.get('match_number'))
                        team_number = int(row.get('team_number'))
                        scout_name = row.get('scout_name', 'Excel Import')
                        alliance = row.get('alliance', 'unknown')
                        
                        # Find or create team
                        team = Team.query.filter_by(team_number=team_number).first()
                        if not team:
                            team = Team(team_number=team_number, team_name=f'Team {team_number}')
                            db.session.add(team)
                            db.session.flush()
                            
                        # Find or create match
                        match_type = row.get('match_type', 'Qualification')
                        match = Match.query.filter_by(match_number=match_number, match_type=match_type).first()
                        if not match:
                            # Need to find or create an event first
                            event_name = row.get('event_name', 'Unknown Event')
                            event = Event.query.filter_by(name=event_name).first()
                            if not event:
                                event = Event(name=event_name, year=game_config['season'])
                                db.session.add(event)
                                db.session.flush()
                                
                            # Create the match
                            match = Match(
                                match_number=match_number,
                                match_type=match_type,
                                event_id=event.id,
                                red_alliance=str(team_number) if alliance == 'red' else '',
                                blue_alliance=str(team_number) if alliance == 'blue' else ''
                            )
                            db.session.add(match)
                            db.session.flush()
                        
                        # Build scouting data from row
                        data = {}
                        
                        # Process data based on game config
                        all_elements = []
                        all_elements.extend(game_config['auto_period']['scoring_elements'])
                        all_elements.extend(game_config['teleop_period']['scoring_elements'])
                        all_elements.extend(game_config['endgame_period']['scoring_elements'])
                        all_elements.extend(game_config['post_match']['rating_elements'])
                        all_elements.extend(game_config['post_match']['text_elements'])
                        
                        for element in all_elements:
                            element_id = element['id']
                            if element_id in row:
                                if element['type'] == 'boolean':
                                    # Convert to boolean
                                    data[element_id] = bool(row[element_id])
                                elif element['type'] == 'counter':
                                    # Convert to integer
                                    data[element_id] = int(row[element_id])
                                else:
                                    # Keep as is
                                    data[element_id] = row[element_id]
                            else:
                                # Use default if available
                                if 'default' in element:
                                    data[element_id] = element['default']
                        
                        # Check if scouting data already exists
                        existing_data = ScoutingData.query.filter_by(
                            match_id=match.id, 
                            team_id=team.id
                        ).first()
                        
                        if existing_data:
                            # Update existing record
                            existing_data.data = data
                            existing_data.alliance = alliance
                            existing_data.scout_name = scout_name
                            records_updated += 1
                        else:
                            # Create new record
                            scouting_data = ScoutingData(
                                match_id=match.id,
                                team_id=team.id,
                                scout_name=scout_name,
                                alliance=alliance,
                                data_json=json.dumps(data)
                            )
                            db.session.add(scouting_data)
                            records_added += 1
                    
                    except Exception as e:
                        flash(f'Error processing row: {e}', 'error')
                        continue
                
                # Commit all changes
                db.session.commit()
                
                flash(f'Import successful! {records_added} records added, {records_updated} records updated.', 'success')
            
            except Exception as e:
                flash(f'Error processing Excel file: {e}', 'error')
            
            finally:
                # Clean up the temporary file
                os.remove(file_path)
            
            return redirect(url_for('data.index'))
        
        else:
            flash('Invalid file format. Please upload an Excel file (.xlsx, .xls)', 'error')
            return redirect(request.url)
    
    return render_template('data/import_excel.html')

@bp.route('/import_qr', methods=['GET', 'POST'])
def import_qr():
    """Import data from QR codes (manual entry or upload)"""
    if request.method == 'POST':
        # Handle API request with JSON data
        if request.is_json:
            try:
                qr_data = request.get_json().get('data')
                if not qr_data:
                    return {'success': False, 'message': 'No data provided'}
            except Exception as e:
                return {'success': False, 'message': f'Invalid JSON: {str(e)}'}
        else:
            # Handle form submission
            qr_data = request.form.get('qr_data')
            if not qr_data:
                flash('No QR code data received', 'error')
                return redirect(request.url)
                
        try:
            # Parse QR data (assuming it's JSON)
            scouting_data_json = json.loads(qr_data)
            
            # Detect the format of the QR code
            if 'offline_generated' in scouting_data_json:
                # This is from our offline Generate QR button
                team_id = scouting_data_json.get('team_id')
                match_id = scouting_data_json.get('match_id')
                scout_name = scouting_data_json.get('scout_name', 'QR Import')
                alliance = scouting_data_json.get('alliance', 'unknown')
                
                # Get team and match directly by ID
                team = Team.query.get(team_id)
                match = Match.query.get(match_id)
                
                if not team or not match:
                    error_msg = 'Team or match not found in database'
                    if request.is_json:
                        return {'success': False, 'message': error_msg}
                    flash(error_msg, 'error')
                    return redirect(request.url)
                
                # Extract all form data, excluding metadata fields
                data = {}
                for key, value in scouting_data_json.items():
                    # Skip metadata fields
                    if key not in ['team_id', 'match_id', 'scout_name', 'alliance', 
                                  'generated_at', 'offline_generated']:
                        data[key] = value
                
            elif 't' in scouting_data_json and 'm' in scouting_data_json:
                # Compact format with single-letter keys
                team_number = scouting_data_json.get('t')  # team_number
                match_number = scouting_data_json.get('m')  # match_number
                scout_name = scouting_data_json.get('s', 'QR Import')  # scout_name
                alliance = scouting_data_json.get('a', 'unknown')  # alliance
                match_type = scouting_data_json.get('mt', 'Qualification')  # match_type
                
                # Find or create team
                team = Team.query.filter_by(team_number=team_number).first()
                if not team:
                    team = Team(team_number=team_number, team_name=f'Team {team_number}')
                    db.session.add(team)
                    db.session.flush()
                
                # Find or create match
                match = Match.query.filter_by(match_number=match_number, match_type=match_type).first()
                if not match:
                    # Need to find or create an event first
                    game_config = current_app.config['GAME_CONFIG']
                    event_name = scouting_data_json.get('event_name', 'Unknown Event')
                    event = Event.query.filter_by(name=event_name).first()
                    if not event:
                        event = Event(name=event_name, year=game_config['season'])
                        db.session.add(event)
                        db.session.flush()
                    
                    # Create the match
                    match = Match(
                        match_number=match_number,
                        match_type=match_type,
                        event_id=event.id,
                        red_alliance=str(team_number) if alliance == 'red' else '',
                        blue_alliance=str(team_number) if alliance == 'blue' else ''
                    )
                    db.session.add(match)
                    db.session.flush()
                
                # Get data from compact format
                data = {}
                if 'd' in scouting_data_json:
                    data = scouting_data_json['d']
            
            else:
                # Legacy format or unknown format
                team_number = scouting_data_json.get('team_number')
                match_number = scouting_data_json.get('match_number')
                
                if not team_number or not match_number:
                    error_msg = 'Invalid QR data: missing team or match number'
                    if request.is_json:
                        return {'success': False, 'message': error_msg}
                    flash(error_msg, 'error')
                    return redirect(request.url)
                
                scout_name = scouting_data_json.get('scout_name', 'QR Import')
                alliance = scouting_data_json.get('alliance', 'unknown')
                match_type = scouting_data_json.get('match_type', 'Qualification')
                
                # Find or create team
                team = Team.query.filter_by(team_number=team_number).first()
                if not team:
                    team = Team(team_number=team_number, team_name=f'Team {team_number}')
                    db.session.add(team)
                    db.session.flush()
                
                # Find or create match
                match = Match.query.filter_by(match_number=match_number, match_type=match_type).first()
                if not match:
                    # Need to find or create an event first
                    game_config = current_app.config['GAME_CONFIG']
                    event_name = scouting_data_json.get('event_name', 'Unknown Event')
                    event = Event.query.filter_by(name=event_name).first()
                    if not event:
                        event = Event(name=event_name, year=game_config['season'])
                        db.session.add(event)
                        db.session.flush()
                    
                    # Create the match
                    match = Match(
                        match_number=match_number,
                        match_type=match_type,
                        event_id=event.id,
                        red_alliance=str(team_number) if alliance == 'red' else '',
                        blue_alliance=str(team_number) if alliance == 'blue' else ''
                    )
                    db.session.add(match)
                    db.session.flush()
                
                # Check if data is in a nested field or directly in root
                if 'scouting_data' in scouting_data_json:
                    # Data is in the nested 'scouting_data' field
                    data = scouting_data_json.get('scouting_data', {})
                else:
                    # Data is directly in the root (try to extract all non-metadata fields)
                    data = {}
                    for key, value in scouting_data_json.items():
                        # Skip metadata fields we've already processed
                        if key not in ['match_number', 'team_number', 'scout_name', 'alliance', 
                                      'match_type', 'event_name', 'timestamp']:
                            data[key] = value
            
            # Check if scouting data already exists
            existing_data = ScoutingData.query.filter_by(
                match_id=match.id, 
                team_id=team.id
            ).first()
            
            if existing_data:
                # Update existing record
                existing_data.data = data
                existing_data.alliance = alliance
                existing_data.scout_name = scout_name
                db.session.commit()
                
                success_msg = f'Updated scouting data for Team {team.team_number} in Match {match.match_number}'
                if request.is_json:
                    return {'success': True, 'message': success_msg}
                flash(success_msg, 'success')
            else:
                # Create new record
                new_scouting_data = ScoutingData(
                    match_id=match.id,
                    team_id=team.id,
                    scout_name=scout_name,
                    alliance=alliance,
                    data_json=json.dumps(data),

                )
                db.session.add(new_scouting_data)
                db.session.commit()
                
                success_msg = f'Added new scouting data for Team {team.team_number} in Match {match.match_number}'
                if request.is_json:
                    return {'success': True, 'message': success_msg}
                flash(success_msg, 'success')
            
            if request.is_json:
                return {'success': True, 'message': 'Data processed successfully'}
            return redirect(url_for('data.import_qr', success=True))
            
        except json.JSONDecodeError as e:
            error_msg = 'Invalid QR code data format. Expected JSON data.'
            if request.is_json:
                return {'success': False, 'message': error_msg}
            flash(error_msg, 'error')
        except Exception as e:
            error_msg = f'Error processing QR data: {str(e)}'
            if request.is_json:
                return {'success': False, 'message': error_msg}
            flash(error_msg, 'error')
    
    success = request.args.get('success', False)
    return render_template('data/import_qr.html', success=success)

@bp.route('/export/excel')
def export_excel():
    """Export all scouting data to Excel"""
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Get all scouting data
    scouting_data = ScoutingData.query.all()
    
    # Create a list of dictionaries for the DataFrame
    data_list = []
    
    for data in scouting_data:
        row = {
            'match_number': data.match.match_number,
            'match_type': data.match.match_type,
            'team_number': data.team.team_number,
            'team_name': data.team.team_name,
            'alliance': data.alliance,
            'scout_name': data.scout_name,
            'timestamp': data.timestamp
        }
        
        # Add all data fields from the JSON
        for key, value in data.data.items():
            row[key] = value
        
        data_list.append(row)
    
    # Create a DataFrame
    df = pd.DataFrame(data_list)
    
    # Generate Excel file
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Scouting Data')
    
    output.seek(0)
    
    # Encode as base64 for download
    excel_data = base64.b64encode(output.read()).decode('utf-8')
    
    return render_template('data/export_excel.html', excel_data=excel_data,
                          filename=f'scouting_data_{game_config["season"]}.xlsx')

@bp.route('/manage', methods=['GET'])
def manage_entries():
    """Manage database entries (view, edit, delete)."""
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    # Fetch all scouting entries with eager loading of related models
    scouting_entries = (ScoutingData.query
                       .join(Match)
                       .join(Event)
                       .join(Team)
                       .order_by(ScoutingData.timestamp.desc())
                       .all())
    
    # Get teams and matches filtered by the current event if available
    if current_event:
        teams = current_event.teams
        matches = Match.query.filter_by(event_id=current_event.id).order_by(Match.match_type, Match.match_number).all()
    else:
        teams = []  # No teams if no current event is set
        matches = []  # No matches if no current event is set

    return render_template('data/manage/index.html', 
                         scouting_entries=scouting_entries, 
                         teams=teams,
                         matches=matches)

@bp.route('/edit/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(entry_id):
    """Edit a scouting data entry"""
    # Get the scouting data entry
    entry = ScoutingData.query.get_or_404(entry_id)
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    if request.method == 'POST':
        # Update scout name and alliance
        entry.scout_name = request.form.get('scout_name')
        entry.alliance = request.form.get('alliance')
        
        # Build updated data dictionary from form
        data = {}
        
        # Process all game elements from config
        all_elements = []
        all_elements.extend(game_config['auto_period']['scoring_elements'])
        all_elements.extend(game_config['teleop_period']['scoring_elements'])
        all_elements.extend(game_config['endgame_period']['scoring_elements'])
        all_elements.extend(game_config['post_match']['rating_elements'])
        all_elements.extend(game_config['post_match']['text_elements'])
        
        for element in all_elements:
            element_id = element['id']
            if element['type'] == 'boolean':
                data[element_id] = element_id in request.form
            elif element['type'] == 'counter':
                data[element_id] = int(request.form.get(element_id, 0))
            elif element['type'] == 'select':
                data[element_id] = request.form.get(element_id, element.get('default', ''))
            elif element['type'] == 'rating':
                data[element_id] = int(request.form.get(element_id, element.get('default', 0)))
            else:
                data[element_id] = request.form.get(element_id, '')
        
        # Update data
        entry.data_json = json.dumps(data)
        db.session.commit()
        
        flash('Scouting data updated successfully!', 'success')
        return redirect(url_for('data.manage_entries'))
    
    return render_template('data/manage/edit.html', entry=entry, game_config=game_config)

@bp.route('/delete/<int:entry_id>', methods=['POST'])
def delete_entry(entry_id):
    """Delete a scouting data entry"""
    entry = ScoutingData.query.get_or_404(entry_id)
    
    team_number = entry.team.team_number
    match_number = entry.match.match_number
    
    db.session.delete(entry)
    db.session.commit()
    
    flash(f'Scouting data for Team {team_number} in Match {match_number} deleted!', 'success')
    return redirect(url_for('data.manage_entries'))

@bp.route('/wipe_database', methods=['POST'])
def wipe_database():
    """Wipe all data from the database"""
    try:
        # Import all models that need to be cleared
        from app.models import ScoutingData, Match, Team, Event
        
        # Delete all data in order to respect foreign key constraints
        ScoutingData.query.delete()
        Match.query.delete()
        Team.query.delete()
        Event.query.delete()
        
        # Commit the changes
        db.session.commit()
        
        flash("Database wiped successfully. All data has been deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error wiping database: {str(e)}", "danger")
    
    return redirect(url_for('data.index'))