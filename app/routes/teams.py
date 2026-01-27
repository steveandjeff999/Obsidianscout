from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
from app.models import Team, Event, ScoutingData
from app import db
from app.utils.api_utils import get_teams, ApiError, api_to_db_team_conversion, get_event_details, get_teams_dual_api, get_event_details_dual_api
from app.utils.tba_api_utils import get_tba_team_events, TBAApiError
from datetime import datetime, timezone
import statistics
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_current_game_config, get_effective_game_config
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_events_by_scouting_team, 
    assign_scouting_team_to_model, get_event_by_code, filter_scouting_data_by_scouting_team
)
from app.utils.team_isolation import get_combined_dropdown_events
from app.utils.alliance_data import get_active_alliance_id, get_all_teams_for_alliance

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('teams', __name__, url_prefix='/teams')

@bp.route('/')
@analytics_required
def index():
    """Display teams for the selected event"""
    # Get event code from config
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    if current_event_code:
        current_event_code = str(current_event_code).strip()
    
    # Get the current event
    event = None
    event_id = request.args.get('event_id', type=int)
    
    # Get all events for the dropdown (combined/deduped like /events)
    events = get_combined_dropdown_events()

    # Prefer synthetic alliance entry for current_event_code when present (override local copy when alliance active)
    try:
        # Only auto-override with the alliance/current_event when the user did NOT explicitly request an event
        if not request.args.get('event_id') and current_event_code and events:
            code_up = str(current_event_code).upper()
            evt = next((e for e in events if getattr(e, 'is_alliance', False) and (getattr(e, 'code', '') or '').upper() == code_up), None)
            if evt and get_active_alliance_id():
                event = evt
    except Exception:
        pass

    # Also respect raw event_id param that may contain synthetic ids or codes
    try:
        raw_event_param = request.args.get('event_id')
        if raw_event_param and events:
            if isinstance(raw_event_param, str):
                if raw_event_param.startswith('alliance_'):
                    evt = next((e for e in events if str(getattr(e, 'id', '')) == raw_event_param), None)
                    if evt:
                        event = evt
                else:
                    code_up = raw_event_param.upper()
                    evt = next((e for e in events if (getattr(e, 'code', '') or '').upper() == code_up), None)
                    if evt:
                        event = evt
    except Exception:
        pass

    if event_id:
        # If a specific event ID is requested, use that (filtered by scouting team)
        event = filter_events_by_scouting_team().filter(Event.id == event_id).first()
        if not event:
            flash("Event not found or not accessible.", "error")
            return redirect(url_for('teams.index'))
    elif current_event_code:
        # Otherwise use the current event from config (filtered by scouting team)
        if not event:
            event = get_event_by_code(current_event_code)
        
        # If the config has an event code but it's not in the database yet,
        # suggest syncing teams to create the event
        if not event and events:
            flash(f"Event with code '{current_event_code}' not found. Please sync teams to create this event.", "warning")

    # Post-process: If alliance mode is active and a synthetic alliance entry exists for the
    # current_event_code, prefer that synthetic entry (override local selection) — but only when
    # the user did NOT explicitly request an `event_id`.
    try:
        if not request.args.get('event_id') and current_event_code and events and get_active_alliance_id():
            code_up = str(current_event_code).upper()
            evt = next((e for e in events if getattr(e, 'is_alliance', False) and (getattr(e, 'code', '') or '').upper() == code_up), None)
            if evt:
                # No explicit event requested; use the synthetic alliance entry
                event = evt
                force_selected_event = False
    except Exception:
        pass

    try:
        force_selected_event
    except NameError:
        force_selected_event = False
    
    # Filter teams by the selected event and scouting team
    # In alliance mode, show teams from alliance scouting data
    alliance_id = get_active_alliance_id()
    
    # If no event selected and we're not in alliance mode, default to the current team's most-recent event
    try:
        if not event and not alliance_id:
            team_event = filter_events_by_scouting_team().order_by(
                Event.year.desc(), 
                Event.start_date.desc(), 
                Event.id.desc()
            ).first()
            if team_event:
                event = team_event
    except Exception:
        pass

    # Ensure selected_event matches an entry from the events dropdown list
    selected_event_for_dropdown = None
    if event and events:
        try:
            # Check if we're in alliance mode
            is_in_alliance_mode = alliance_id is not None
            
            event_id_to_match = getattr(event, 'id', None)
            event_code_to_match = (getattr(event, 'code', '') or '').upper()
            
            # Collect all matching events, then pick the best one
            matching_events = []
            for dropdown_evt in events:
                dropdown_id = getattr(dropdown_evt, 'id', None)
                dropdown_code = (getattr(dropdown_evt, 'code', '') or '').upper()
                
                if (event_id_to_match and dropdown_id == event_id_to_match) or \
                   (event_code_to_match and dropdown_code == event_code_to_match):
                    matching_events.append(dropdown_evt)
            
            # Prefer alliance events when in alliance mode, non-alliance events otherwise
            if matching_events:
                for evt in matching_events:
                    is_alliance_evt = getattr(evt, 'is_alliance', False)
                    if is_in_alliance_mode and is_alliance_evt:
                        selected_event_for_dropdown = evt
                        break
                    elif not is_in_alliance_mode and not is_alliance_evt:
                        selected_event_for_dropdown = evt
                        break
                # Fallback to first match if preference not found
                if not selected_event_for_dropdown:
                    selected_event_for_dropdown = matching_events[0]
            
            if not selected_event_for_dropdown:
                selected_event_for_dropdown = event
        except Exception:
            selected_event_for_dropdown = event
    else:
        selected_event_for_dropdown = event

    if event:
        if alliance_id:
            # Alliance mode - get teams from alliance scouting data for this event
            try:
                is_synthetic = isinstance(getattr(event, 'id', None), str) and str(event.id).startswith('alliance_')
            except Exception:
                is_synthetic = False
            if is_synthetic:
                teams, _ = get_all_teams_for_alliance(event_code=getattr(event, 'code', None))
            else:
                teams, _ = get_all_teams_for_alliance(event_id=event.id)
        else:
            # Normal mode - get teams associated with this event, filtered by scouting team
            # Use event code matching to handle cross-team event lookups
            from sqlalchemy import func
            event_code = getattr(event, 'code', None)
            if event_code:
                teams = filter_teams_by_scouting_team().join(
                    Team.events
                ).filter(func.upper(Event.code) == event_code.upper()).order_by(Team.team_number).all()
            else:
                teams = filter_teams_by_scouting_team().join(
                    Team.events
                ).filter(Event.id == event.id).order_by(Team.team_number).all()

        # Deduplicate teams by team_number using a shared helper that applies
        # the preference rules (prefer alliance teams when alliance active,
        # else prefer local teams).
        try:
            from app.utils.team_isolation import dedupe_team_list, get_alliance_team_numbers, get_current_scouting_team_number
            alliance_team_nums = get_alliance_team_numbers() or []
            current_scouting_team = get_current_scouting_team_number()
            teams = dedupe_team_list(teams, prefer_alliance=bool(alliance_id), alliance_team_numbers=alliance_team_nums, current_scouting_team=current_scouting_team)
        except Exception:
            # If anything goes wrong, fall back to the original teams list (don't crash the page)
            pass
    else:
        # If no event selected, don't show any teams
        teams = []
        
        if not events:
            flash("No events found in the database. Add an event or sync teams to create events.", "info")
        else:
            flash("Please select an event to view teams.", "info")
    
    return render_template('teams/index.html', teams=teams, events=events, selected_event=selected_event_for_dropdown, force_selected_event=force_selected_event, is_alliance_mode=alliance_id is not None, **get_theme_context())

@bp.route('/sync_from_config')
def sync_from_config():
    """Sync teams from FIRST API using the event code from config file"""
    try:
        # Get event code from effective config (respects alliance mode)
        game_config = get_effective_game_config()
        raw_event_code = game_config.get('current_event_code')
        
        if not raw_event_code:
            flash("No event code found in configuration. Please add 'current_event_code' to your game_config.json file.", 'danger')
            return redirect(url_for('teams.index'))
        
        # Find or create the event in our database (filtered by current scouting team)
        # Use year-prefixed event code so each year is treated as a different event (e.g., 2026ARLI)
        current_year = game_config.get('season', 2026)
        event_code = f"{current_year}{raw_event_code}"
        event = get_event_by_code(event_code)
        
        if not event:
            try:
                # Try to get event details from dual API (use raw code for external API)
                from app.routes.data import get_or_create_event
                event_details = get_event_details_dual_api(raw_event_code)
                
                # Convert date strings to datetime.date objects
                start_date_str = event_details.get('dateStart')
                end_date_str = event_details.get('dateEnd')
                
                start_date = None
                end_date = None
                
                # Parse start date if present
                if start_date_str:
                    try:
                        start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
                    except ValueError:
                        print(f"Could not parse start date: {start_date_str}")
                
                # Parse end date if present
                if end_date_str:
                    try:
                        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
                    except ValueError:
                        print(f"Could not parse end date: {end_date_str}")
                
                # Get current scouting team number
                from app.utils.team_isolation import get_current_scouting_team_number
                current_scouting_team = get_current_scouting_team_number()
                
                # Use get_or_create_event to properly handle race conditions
                # Store with year-prefixed event_code to differentiate years
                event = get_or_create_event(
                    name=event_details.get('name', f"Event {raw_event_code}"),
                    code=event_code,
                    year=event_details.get('year', current_year),
                    location=event_details.get('location', ''),
                    start_date=start_date,
                    end_date=end_date,
                    scouting_team_number=current_scouting_team
                )
            except Exception:
                # If API call fails, create minimal event using get_or_create_event
                from app.routes.data import get_or_create_event
                from app.utils.team_isolation import get_current_scouting_team_number
                current_scouting_team = get_current_scouting_team_number()
                event = get_or_create_event(
                    name=f"Event {raw_event_code}",
                    code=event_code,
                    year=current_year,
                    scouting_team_number=current_scouting_team
                )
            
            db.session.commit()  # Commit to get the ID

        # Fetch teams from the dual API using raw event code (external APIs don't use year-prefixed codes)
        team_data_list = get_teams_dual_api(raw_event_code)
        
        # Track metrics for user feedback
        teams_added = 0
        teams_updated = 0
        
        # Import DisableReplication to prevent queue issues during bulk operations
        from app.utils.real_time_replication import DisableReplication
        
        # Temporarily disable replication during bulk sync to prevent queue issues
        with DisableReplication():
            # Process each team from the API
            for team_data in team_data_list:
                
                if not team_data or not team_data.get('team_number'):
                    continue
                    
                team_number = team_data.get('team_number')
                
                # Check if the team already exists for this scouting team
                team = filter_teams_by_scouting_team().filter(Team.team_number == team_number).first()
                
                if team:
                    # Update existing team
                    team.team_name = team_data.get('team_name', team.team_name)
                    team.location = team_data.get('location', team.location)
                    teams_updated += 1
                else:
                    # Add new team
                    team = Team(**team_data)
                    assign_scouting_team_to_model(team)  # Assign current scouting team
                    db.session.add(team)
                    db.session.flush()  # Flush to get the team ID
                    teams_added += 1
                
                # Associate this team with the current event if not already associated
                try:
                    # Prevent two different Team rows with the same team_number from being associated
                    # with the same Event. Check existing teams on the event with the same team_number.
                    conflict = False
                    for existing_team in event.teams:
                        if existing_team.team_number == team.team_number and existing_team.id != team.id:
                            conflict = True
                            break

                    if conflict:
                        # Log and skip association to avoid duplicate logical team entries on same event
                        print(f"Skipping association for team {team.team_number} -> event {event.code}: another team row with same number already associated")
                        continue

                    # Check if association already exists to avoid duplicate
                    if event not in team.events:
                        team.events.append(event)
                        db.session.flush()  # Flush after each team-event association
                except Exception as e:
                    # Log the error but continue processing other teams
                    print(f"Error associating team {team.team_number} with event: {str(e)}")
                    continue
            
            # Commit all changes
            db.session.commit()
        
        # Merge any duplicate events that may have been created
        try:
            from app.routes.data import merge_duplicate_events
            from app.utils.team_isolation import get_current_scouting_team_number
            current_scouting_team = get_current_scouting_team_number()
            merge_duplicate_events(current_scouting_team)
        except Exception as merge_err:
            print(f"  Warning: Could not merge duplicate events: {merge_err}")
        
        # After bulk sync, queue a single replication event for the team sync
        if teams_added > 0 or teams_updated > 0:
            from app.utils.real_time_replication import real_time_replicator
            real_time_replicator.replicate_operation(
                'update', 
                'teams', 
                {
                    'event_code': event_code,
                    'teams_added': teams_added,
                    'teams_updated': teams_updated,
                    'total_teams': len(team_data_list),
                    'sync_type': 'bulk_sync',
                    'sync_timestamp': datetime.now(timezone.utc).isoformat()
                }, 
                f"sync_summary_teams_{event_code}"
            )
        
        # Show success message
        flash(f"Teams sync complete! Added {teams_added} new teams and updated {teams_updated} existing teams.", 'success')
        
    except ApiError as e:
        msg = str(e)
        msg_lower = msg.lower()
        if '401' in msg_lower or '404' in msg_lower or 'not found' in msg_lower:
            flash("Event not found from API.", 'danger')
        else:
            flash(f"API Error: {msg}", 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f"Error syncing teams: {str(e)}", 'danger')
    
    return redirect(url_for('teams.index'))

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new team"""
    # Get all events for the form (combined/deduped like /events)
    events = get_combined_dropdown_events()
    
    # Get default event from config or URL parameter
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    default_event_id = None
    
    if current_event_code:
        event = get_event_by_code(current_event_code)
        if event:
            default_event_id = event.id
    
    # Get event from URL parameter if provided (overrides default)
    event_id_param = request.args.get('event_id', type=int)
    if event_id_param:
        default_event_id = event_id_param
    
    if request.method == 'POST':
        team_number = request.form.get('team_number', type=int)
        team_name = request.form.get('team_name')
        location = request.form.get('location')
        
        # Get the selected events (can be multiple)
        event_ids = request.form.getlist('events', type=int)
        
        # Validate that team number is provided
        if not team_number:
            flash('Team number is required', 'danger')
            return render_template('teams/add.html', events=events, default_event_id=default_event_id, **get_theme_context())
        
        # Check if team already exists for this scouting team
        existing_team = filter_teams_by_scouting_team().filter(Team.team_number == team_number).first()
        if existing_team:
            # Merge behavior: update provided fields and associate selected events
            existing_team.team_name = team_name or existing_team.team_name
            existing_team.location = location or existing_team.location
            try:
                if event_ids:
                    for event_id in event_ids:
                        event = filter_events_by_scouting_team().filter(Event.id == event_id).first()
                        if event:
                            # Prevent conflict: ensure no other Team row with same team_number is already attached
                            conflict = False
                            for et in event.teams:
                                if et.team_number == existing_team.team_number and et.id != existing_team.id:
                                    conflict = True
                                    break

                            if conflict:
                                flash(f"Skipped associating Event {event.name} — another team entry with number {existing_team.team_number} is already associated with that event.", 'warning')
                                continue

                            if event not in existing_team.events:
                                existing_team.events.append(event)

                db.session.commit()
                flash(f'Team {team_number} already existed — merged selected events and updated team info.', 'success')
                # Redirect to the last selected event if available so user sees merged associations
                if event_ids:
                    return redirect(url_for('teams.index', event_id=event_ids[-1]))
                return redirect(url_for('teams.index'))
            except Exception as e:
                db.session.rollback()
                flash(f'Error merging existing team: {str(e)}', 'danger')
                return render_template('teams/add.html', events=events, default_event_id=default_event_id, **get_theme_context())
        
        # Create new team
        team = Team(team_number=team_number, team_name=team_name, location=location)
        assign_scouting_team_to_model(team)  # Assign current scouting team
        
        try:
            db.session.add(team)
            db.session.flush()  # Flush to get the team ID
            
            # Associate team with selected events (filtered by scouting team)
            if event_ids:
                for event_id in event_ids:
                    event = filter_events_by_scouting_team().filter(Event.id == event_id).first()
                    if event:
                        # Prevent conflict: if the event already has a different team row with this team_number, skip
                        conflict = False
                        for et in event.teams:
                            if et.team_number == team.team_number and et.id != team.id:
                                conflict = True
                                break

                        if conflict:
                            flash(f"Skipped associating Event {event.name} — another team entry with number {team.team_number} is already associated with that event.", 'warning')
                            continue

                        if event not in team.events:
                            team.events.append(event)
                
                # Read team-level starting points settings from the form and set on the Team model
                try:
                    sp_val = request.form.get('starting_points', type=float)
                    sp_thresh = request.form.get('starting_points_threshold', type=int)
                    sp_enabled = request.form.get('starting_points_enabled') is not None
                    if sp_val is not None:
                        team.starting_points = sp_val
                    if sp_thresh is not None:
                        team.starting_points_threshold = sp_thresh
                    team.starting_points_enabled = bool(sp_enabled)
                except Exception:
                    pass

                # Use the last selected event as the return URL
                return_event_id = event_ids[-1]
                
                db.session.commit()
                flash(f'Team {team_number} added successfully and associated with selected events', 'success')
                return redirect(url_for('teams.index', event_id=return_event_id))
            else:
                db.session.commit()
                flash(f'Team {team_number} added successfully (not associated with any events)', 'success')
                return redirect(url_for('teams.index'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding team: {str(e)}', 'danger')
    
    return render_template('teams/add.html', events=events, default_event_id=default_event_id, **get_theme_context())

@bp.route('/<int:team_number>/edit', methods=['GET', 'POST'])
def edit(team_number):
    """Edit a team"""
    team = Team.query.filter_by(team_number=team_number).first_or_404()
    
    # Get all events for the form (combined/deduped like /events)
    events = get_combined_dropdown_events()
    # Starting points are stored on the Team model; values are updated on POST
    
    if request.method == 'POST':
        # new_team_number = request.form.get('team_number', type=int)
        team_name = request.form.get('team_name')
        location = request.form.get('location')
        
        # Get the selected events (can be multiple)
        event_ids = request.form.getlist('events', type=int)
        
        # Update team
        # Note: We're not allowing team number changes to avoid complications
        # team.team_number = new_team_number
        team.team_name = team_name
        team.location = location
        
        try:
            # Update team-event associations
            # First, remove all existing associations
            team.events = []

            # Then add the selected events, skipping any that would create a duplicate logical team
            if event_ids:
                for event_id in event_ids:
                    event = Event.query.get(event_id)
                    if not event:
                        continue

                    # Check for conflict: another Team row with same team_number attached to this event
                    conflict = False
                    for et in event.teams:
                        if et.team_number == team.team_number and et.id != team.id:
                            conflict = True
                            break

                    if conflict:
                        flash(f"Skipped associating Event {event.name} — another team entry with number {team.team_number} is already associated with that event.", 'warning')
                        continue

                    team.events.append(event)

            # Read team-level starting points settings from the form and set on the Team model
            try:
                sp_val = request.form.get('starting_points', type=float)
                sp_thresh = request.form.get('starting_points_threshold', type=int)
                sp_enabled = request.form.get('starting_points_enabled') is not None
                if sp_val is not None:
                    team.starting_points = sp_val
                if sp_thresh is not None:
                    team.starting_points_threshold = sp_thresh
                team.starting_points_enabled = bool(sp_enabled)
            except Exception:
                pass

            db.session.commit()
            flash(f'Team {team.team_number} updated successfully', 'success')
            
            # Redirect to the teams list filtered by one of the selected events
            if event_ids:
                return redirect(url_for('teams.index', event_id=event_ids[0]))
            else:
                return redirect(url_for('teams.index'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating team: {str(e)}', 'danger')
    
    return render_template('teams/edit.html', team=team, events=events, **get_theme_context())

@bp.route('/<int:team_number>/delete', methods=['POST'])
def delete(team_number):
    """Delete a team"""
    team = Team.query.filter_by(team_number=team_number).first_or_404()
    
    try:
        db.session.delete(team)
        db.session.commit()
        flash(f'Team {team.team_number} deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting team: {str(e)}', 'danger')
    
    return redirect(url_for('teams.index'))

@bp.route('/<int:team_number>/view')
def view(team_number):
    """View team details"""
    from app.utils.team_isolation import get_current_scouting_team_number
    from app.utils.alliance_data import get_scouting_data_for_team, get_active_alliance_id
    
    # Check if we're in alliance mode
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    # Find the team entry that belongs to the current scouting team or has scouting data
    current_scouting_team = get_current_scouting_team_number()
    
    # First, try to find a team with the number that has scouting data for current scouting team
    team = None
    if current_scouting_team is not None:
        # Look for team with scouting data from current scouting team
        team = db.session.query(Team).join(ScoutingData).filter(
            Team.team_number == team_number,
            ScoutingData.scouting_team_number == current_scouting_team
        ).first()
    
    # Fallback to any team with that number if no team found with scouting data
    if team is None:
        team = Team.query.filter_by(team_number=team_number).first_or_404()
    
    # Get scouting data for this specific team - use alliance data if in alliance mode
    scouting_data, is_from_alliance = get_scouting_data_for_team(team.id)
    
    # Get game configuration for metrics calculation
    game_config = get_effective_game_config()
    
    # Fallback: If game config is empty, try to load config for the current scouting team
    if not game_config and current_scouting_team is not None:
        from app.utils.config_manager import load_game_config
        game_config = load_game_config(team_number=current_scouting_team)
    
    # Calculate key metrics for this team if we have scouting data
    metrics = {}
    component_metrics = {}  # Stores just the component metrics for separate display
    metric_info = {}  # Stores metadata about each metric
    
    # Find the component metrics and total metric from game config
    component_metric_ids = []
    total_metric_id = None
    total_metric_name = "Total Points"
    
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            metric_id = metric.get('id')
            metric_info[metric_id] = metric
            
            # Check if this is a component metric or the total metric
            if metric.get('is_total_component'):
                component_metric_ids.append(metric_id)
            elif 'total' in metric_id.lower() or 'tot' == metric_id.lower():
                total_metric_id = metric_id
                total_metric_name = metric.get('name', "Total Points")
    
    # If no component metrics defined in config, use default IDs
    if not component_metric_ids:
        component_metric_ids = ["apt", "tpt", "ept"]
        # Add default metric info for fallback metrics
        metric_info["apt"] = {"id": "apt", "name": "Auto Points", "formula": "apt"}
        metric_info["tpt"] = {"id": "tpt", "name": "Teleop Points", "formula": "tpt"}
        metric_info["ept"] = {"id": "ept", "name": "Endgame Points", "formula": "ept"}
    
    # If no total metric defined, use default ID
    if not total_metric_id:
        total_metric_id = "tot"
        # Add default metric info for total metric
        metric_info["tot"] = {"id": "tot", "name": "Total Points", "formula": "tot"}
    
    if scouting_data:
        # Initialize metric arrays
        metric_values = {metric_id: [] for metric_id in component_metric_ids}
        metric_values[total_metric_id] = []
        
        # Process all scouting data entries to calculate metrics
        for data in scouting_data:
            for metric_id in component_metric_ids:
                metric_values[metric_id].append(data.calculate_metric(metric_id))
            
            metric_values[total_metric_id].append(data.calculate_metric(total_metric_id))
        
        # Calculate averages
        for metric_id, values in metric_values.items():
            if values:
                metrics[metric_id] = sum(values) / len(values)
                if metric_id in component_metric_ids:
                    component_metrics[metric_id] = metrics[metric_id]
        
        # Add other key metrics from game config if they exist
        if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
            for metric in game_config['data_analysis']['key_metrics']:
                metric_id = metric.get('id')
                # Skip metrics we've already calculated
                if metric_id in metrics:
                    continue
                
                # Skip metrics that don't have a formula
                if not metric.get('formula'):
                    continue
                
                # Calculate this metric for each scouting entry and average
                metric_values = []
                for data in scouting_data:
                    value = data.calculate_metric(metric.get('formula', ''))
                    if value is not None:
                        metric_values.append(value)
                
                # Calculate average if we have values
                if metric_values:
                    metrics[metric_id] = sum(metric_values) / len(metric_values)
    
    # Get events this team is competing at from the API
    team_events = []
    try:
        # Use current year (2025 based on context)
        current_year = datetime.now().year
        team_key = f"frc{team_number}"
        api_events = get_tba_team_events(team_key, current_year)
        
        if api_events:
            for event_data in api_events:
                # Convert TBA event data to a format we can use
                event_info = {
                    'key': event_data.get('key'),
                    'name': event_data.get('name'),
                    'event_code': event_data.get('event_code'),
                    'start_date': event_data.get('start_date'),
                    'end_date': event_data.get('end_date'),
                    'location_name': event_data.get('location_name'),
                    'city': event_data.get('city'),
                    'state_prov': event_data.get('state_prov'),
                    'country': event_data.get('country'),
                    'event_type': event_data.get('event_type'),
                    'event_type_string': event_data.get('event_type_string')
                }
                team_events.append(event_info)
    except TBAApiError as e:
        print(f"Error fetching events for team {team_number}: {e}")
        team_events = []
    except Exception as e:
        print(f"Unexpected error fetching events for team {team_number}: {e}")
        team_events = []
    
    return render_template(
        'teams/view.html', 
        team=team, 
        scouting_data=scouting_data, 
        metrics=metrics, 
        game_config=game_config,
        component_metrics=component_metrics,
        metric_info=metric_info,
        total_metric_id=total_metric_id,
        total_metric_name=total_metric_name,
        team_events=team_events,
        **get_theme_context()
    )

@bp.route('/ranks')
@analytics_required
def ranks():
    """Display team rankings for the selected event based on average total points"""
    from app.utils.alliance_data import get_scouting_data_for_team, get_active_alliance_id
    
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    event_id = request.args.get('event_id', type=int)
    events = get_combined_dropdown_events()
    event = None
    if event_id:
        event = Event.query.get_or_404(event_id)
    elif current_event_code:
        event = get_event_by_code(current_event_code)
    # Check if alliance mode is active
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None

    # Build teams list from event but deduplicate by team_number to avoid duplicate logical teams
    if event:
        # If alliance mode is active, get teams for the alliance (includes all alliance members)
        if alliance_id:
            try:
                try:
                    is_synthetic = isinstance(getattr(event, 'id', None), str) and str(event.id).startswith('alliance_')
                except Exception:
                    is_synthetic = False
                if is_synthetic:
                    teams, _ = get_all_teams_for_alliance(event_code=getattr(event, 'code', None))
                else:
                    teams, _ = get_all_teams_for_alliance(event_id=event.id)
            except Exception:
                teams = list(event.teams)
        else:
            # Normal mode - get event teams visible to current scouting team
            try:
                from app.utils.team_isolation import filter_teams_by_scouting_team
                teams = filter_teams_by_scouting_team().join(
                    Team.events
                ).filter(Event.id == event.id).order_by(Team.team_number).all()
            except Exception:
                teams = list(event.teams)

        # Deduplicate teams by team_number using preference rules
        try:
            from app.utils.team_isolation import dedupe_team_list, get_alliance_team_numbers, get_current_scouting_team_number
            alliance_team_nums = get_alliance_team_numbers() or []
            current_scouting_team = get_current_scouting_team_number()
            teams = dedupe_team_list(teams, prefer_alliance=bool(alliance_id), alliance_team_numbers=alliance_team_nums, current_scouting_team=current_scouting_team)
        except Exception:
            # If deduplication fails, keep teams as-is
            pass
    else:
        teams = []
    
    # Determine the total metric id from config
    total_metric_id = None
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            if 'total' in metric.get('id', '').lower() or metric.get('id', '').lower() == 'tot':
                total_metric_id = metric['id']
                break
    if not total_metric_id:
        total_metric_id = 'tot'
    # Calculate average total points for each team
    team_rankings = []
    for team in teams:
        # Use alliance data if in alliance mode, otherwise use team isolation helper
        scouting_data, _ = get_scouting_data_for_team(team.id, event_id=event_id if event_id else None)
        if scouting_data:
            # Calculate metric for each scouting entry then filter out matches with 0 points
            total_points_raw = [data.calculate_metric(total_metric_id) for data in scouting_data]
            # Keep only entries that have a non-zero numeric value
            scored_points = [p for p in total_points_raw if p is not None and p != 0]
            # If we have non-zero scored points, average those
            if len(scored_points) > 0:
                avg_points = sum(scored_points) / len(scored_points)
                num_entries = len(scored_points)
            else:
                # There are scouting entries but none have non-zero points.
                # Treat this as having data (avg 0) rather than 'no data' so teams with entries are shown.
                avg_points = 0
                num_entries = len(total_points_raw)
        else:
            # No scouting entries at all -> truly no data
            avg_points = None
            num_entries = 0
        team_rankings.append({
            'team': team,
            'avg_points': avg_points,
            'num_entries': num_entries
        })
    # Sort so teams with data come first (by descending avg_points), then teams with no data
    team_rankings.sort(key=lambda x: (x['avg_points'] is None, -(x['avg_points'] or 0)))
    return render_template('teams/ranks.html',
        team_rankings=team_rankings,
        events=events,
        selected_event=event,
        total_metric_id=total_metric_id,
        is_alliance_mode=is_alliance_mode,
        alliance_id=alliance_id,
        **get_theme_context()
    )


@bp.route('/ranks/share', methods=['POST'])
@analytics_required
def create_ranks_share():
    """Create a shareable link for team rankings"""
    try:
        from app.models import SharedTeamRanks
        
        # Get form data
        title = request.form.get('share_title', '').strip()
        description = request.form.get('share_description', '').strip()
        expires_in_days = request.form.get('expires_in_days', type=int)
        event_id = request.form.get('event_id', type=int) or None
        metric = request.form.get('metric', 'tot')
        
        # Validation
        if not title:
            flash('Please provide a title for your shared team rankings.', 'error')
            return redirect(url_for('teams.ranks'))
        
        # Create the shared ranking
        shared_ranks = SharedTeamRanks.create_share(
            title=title,
            event_id=event_id,
            metric=metric,
            created_by_team=current_user.scouting_team_number,
            created_by_user=current_user.username,
            description=description,
            expires_in_days=expires_in_days
        )
        
        # Generate the share URL
        share_url = url_for('teams.view_shared_ranks', share_id=shared_ranks.share_id, _external=True)
        
        flash(f'Team rankings shared successfully! Share URL: {share_url}', 'success')
        return redirect(url_for('teams.ranks'))
        
    except Exception as e:
        current_app.logger.error(f"Error creating shared team rankings: {str(e)}")
        flash('An error occurred while creating the shared rankings. Please try again.', 'error')
        return redirect(url_for('teams.ranks'))


@bp.route('/ranks/shared/<share_id>')
def view_shared_ranks(share_id):
    """View shared team rankings (no authentication required)"""
    from app.models import SharedTeamRanks
    
    # Get the shared ranking configuration
    shared_ranks = SharedTeamRanks.get_by_share_id(share_id)
    
    if not shared_ranks:
        abort(404, description="Shared team rankings not found or have been removed.")
    
    if shared_ranks.is_expired():
        abort(410, description="This shared team rankings has expired.")
    
    # Increment view count
    shared_ranks.increment_view_count()
    
    # Get game configuration (use a default/public configuration)
    game_config = get_effective_game_config()
    
    # Get event and teams for the shared configuration
    event = shared_ranks.event
    # Build teams list from event but deduplicate by team_number to avoid duplicate logical teams
    if event:
        teams = list(event.teams)
        try:
            from app.utils.team_isolation import dedupe_team_list, get_alliance_team_numbers, get_current_scouting_team_number
            from app.utils.alliance_data import get_active_alliance_id
            alliance_team_nums = get_alliance_team_numbers() or []
            current_scouting_team = get_current_scouting_team_number()
            # For shared view, prefer alliance when active
            teams = dedupe_team_list(teams, prefer_alliance=bool(get_active_alliance_id()), alliance_team_numbers=alliance_team_nums, current_scouting_team=current_scouting_team)
        except Exception:
            teams = list(event.teams)
    else:
        teams = []
    
    if not teams:
        teams = Team.query.all()  # Fallback to all teams if no event specified
        try:
            # Deduplicate the global teams list to avoid showing multiple Team rows with the same team_number
            from app.utils.team_isolation import dedupe_team_list, get_alliance_team_numbers, get_current_scouting_team_number
            from app.utils.alliance_data import get_active_alliance_id
            alliance_team_nums = get_alliance_team_numbers() or []
            current_scouting_team = get_current_scouting_team_number()
            teams = dedupe_team_list(teams, prefer_alliance=bool(get_active_alliance_id()), alliance_team_numbers=alliance_team_nums, current_scouting_team=current_scouting_team)
        except Exception:
            # If deduplication fails for any reason, fall back to the original list
            pass
    
    # Calculate team rankings using the same logic as the main route
    # but without user-specific filtering
    total_metric_id = shared_ranks.metric
    
    team_rankings = []
    for team in teams:
        # Get all scouting data for this team (without team isolation for shared view)
        # Exclude alliance-copied data - shared ranks should only use original data
        from sqlalchemy import or_
        scouting_data = ScoutingData.query.filter_by(team_id=team.id).filter(
            or_(
                ScoutingData.scout_name == None,
                ~ScoutingData.scout_name.like('[Alliance-%')
            )
        ).all()
        if scouting_data:
            total_points_raw = [data.calculate_metric(total_metric_id) for data in scouting_data]
            scored_points = [p for p in total_points_raw if p is not None and p != 0]
            if len(scored_points) > 0:
                avg_points = sum(scored_points) / len(scored_points)
                num_entries = len(scored_points)
            else:
                avg_points = 0
                num_entries = len(total_points_raw)
        else:
            avg_points = None
            num_entries = 0

        team_rankings.append({
            'team': team,
            'avg_points': avg_points,
            'num_entries': num_entries
        })
    
    # Sort so teams with data come first (by descending avg_points), then teams with no data
    team_rankings.sort(key=lambda x: (x['avg_points'] is None, -(x['avg_points'] or 0)))
    
    return render_template('teams/shared_ranks.html',
                         shared_ranks=shared_ranks,
                         team_rankings=team_rankings,
                         event=event,
                         total_metric_id=total_metric_id,
                         game_config=game_config,
                         **get_theme_context())


@bp.route('/ranks/my-shares')
@analytics_required
def my_ranks_shares():
    """View user's created shared team rankings"""
    from app.models import SharedTeamRanks
    
    shares = SharedTeamRanks.get_user_shares(current_user.scouting_team_number, current_user.username)
    
    return render_template('teams/my_ranks_shares.html',
                         shares=shares,
                         **get_theme_context())


@bp.route('/ranks/share/<int:share_id>/delete', methods=['POST'])
@analytics_required
def delete_ranks_share(share_id):
    """Delete a shared team ranking"""
    from app.models import SharedTeamRanks
    
    shared_ranks = SharedTeamRanks.query.get_or_404(share_id)
    
    # Check if user owns this share
    if (shared_ranks.created_by_team != current_user.scouting_team_number or 
        shared_ranks.created_by_user != current_user.username):
        abort(403, description="You don't have permission to delete this shared ranking.")
    
    # Soft delete by setting is_active to False
    shared_ranks.is_active = False
    db.session.commit()
    
    flash('Shared team ranking deleted successfully.', 'success')
    return redirect(url_for('teams.my_ranks_shares'))