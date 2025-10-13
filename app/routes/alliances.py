from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_socketio import emit, join_room, leave_room
from app.models import AllianceSelection, Team, Event, ScoutingData, DoNotPickEntry, AvoidEntry, db, team_event
from app.utils.analysis import calculate_team_metrics
from flask_login import current_user
from app import socketio
from sqlalchemy import func, desc, and_
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_current_game_config, get_effective_game_config
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_events_by_scouting_team,
    filter_alliance_selections_by_scouting_team, filter_do_not_pick_by_scouting_team,
    filter_avoid_entries_by_scouting_team, assign_scouting_team_to_model,
    get_current_scouting_team_number
)

bp = Blueprint('alliances', __name__, url_prefix='/alliances')

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

# SocketIO event handlers for real-time sync
@socketio.on('join_alliance_room')
def on_join_alliance_room(data):
    """Join a room for alliance updates"""
    event_id = data.get('event_id')
    if event_id:
        join_room(f'alliance_event_{event_id}')
        emit('status', {'msg': f'Joined alliance room for event {event_id}'})

@socketio.on('leave_alliance_room')
def on_leave_alliance_room(data):
    """Leave a room for alliance updates"""
    event_id = data.get('event_id')
    if event_id:
        leave_room(f'alliance_event_{event_id}')
        emit('status', {'msg': f'Left alliance room for event {event_id}'})

def emit_alliance_update(event_id, alliance_data):
    """Emit alliance update to all clients in the room"""
    socketio.emit('alliance_updated', alliance_data, room=f'alliance_event_{event_id}')

def emit_recommendations_update(event_id):
    """Emit recommendations update to all clients in the room"""
    socketio.emit('recommendations_updated', {'event_id': event_id}, room=f'alliance_event_{event_id}')

def emit_lists_update(event_id, list_data):
    """Emit lists update to all clients in the room"""
    socketio.emit('lists_updated', list_data, room=f'alliance_event_{event_id}')

@bp.route('/')
def index():
    """Alliance selection main page"""
    # Get all events ordered by date (filtered by scouting team)
    events = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.start_date.desc()).all()
    
    # Get current event from game config or fall back to most recent event (filtered by scouting team)
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    
    if current_event_code:
        current_event = filter_events_by_scouting_team().filter(Event.code == current_event_code).first()
    else:
        current_event = events[0] if events else None
    
    if not current_event:
        flash('No events found. Please create an event first.', 'warning')
        return redirect(url_for('main.index'))
    
    # Get existing alliances for the current event (filtered by scouting team)
    alliances = filter_alliance_selections_by_scouting_team().filter(
        AllianceSelection.event_id == current_event.id
    ).order_by(AllianceSelection.alliance_number).all()
    
    # Create 8 alliances if they don't exist
    if len(alliances) < 8:
        for i in range(1, 9):
            existing = next((a for a in alliances if a.alliance_number == i), None)
            if not existing:
                new_alliance = AllianceSelection(alliance_number=i, event_id=current_event.id)
                assign_scouting_team_to_model(new_alliance)  # Assign current scouting team
                db.session.add(new_alliance)
        db.session.commit()
        alliances = filter_alliance_selections_by_scouting_team().filter(
            AllianceSelection.event_id == current_event.id
        ).order_by(AllianceSelection.alliance_number).all()
    
    return render_template('alliances/index.html', 
                         alliances=alliances, 
                         current_event=current_event,
                         events=events,
                         **get_theme_context())

@bp.route('/recommendations/<int:event_id>')
def get_recommendations(event_id):
    """Get team recommendations based on points scored"""
    try:
        # Check whether client requested trend-aware ranking (default true)
        use_trends = request.args.get('use_trends', '1') not in ('0', 'false', 'False')
        event = filter_events_by_scouting_team().filter(Event.id == event_id).first()
        if not event:
            return jsonify({'error': 'Event not found or not accessible'}), 404
        
        # Get all teams associated with this event (filtered by scouting team)
        all_teams = filter_teams_by_scouting_team().join(
            Team.events
        ).filter(
            Event.id == event_id
        ).order_by(Team.team_number).all()
        
        # If no teams found in team_event, fall back to teams with scouting data for this scouting team
        if not all_teams:
            from app.models import Match
            scouting_team_number = get_current_scouting_team_number()
            query = db.session.query(Team).join(ScoutingData).join(
                Match, ScoutingData.match_id == Match.id
            ).filter(
                Match.event_id == event_id
            )
            
            if scouting_team_number is not None:
                query = query.filter(ScoutingData.scouting_team_number == scouting_team_number)
            else:
                query = query.filter(ScoutingData.scouting_team_number.is_(None))
                
            all_teams = query.distinct().all()
        
        # Get game configuration
        game_config = get_effective_game_config()
        
        # Find metric IDs from game config
        component_metric_ids = []
        total_metric_id = None
        metric_info = {}
        
        # Identify metrics from game config
        if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
            for metric in game_config['data_analysis']['key_metrics']:
                metric_id = metric.get('id')
                metric_info[metric_id] = {
                    'name': metric.get('name'),
                    'is_component': metric.get('is_total_component', False)
                }
                
                # Check if this is a component metric or the total metric
                if metric.get('is_total_component'):
                    component_metric_ids.append(metric_id)
                elif 'total' in metric_id.lower() or 'tot' == metric_id.lower():
                    total_metric_id = metric_id
        
        # If no component metrics defined, use default IDs
        if not component_metric_ids:
            component_metric_ids = ["apt", "tpt", "ept"]
        
        # If no total metric defined, use default ID
        if not total_metric_id:
            total_metric_id = "tot"
            
        # Get teams already picked in alliances (filtered by scouting team)
        picked_teams = set()
        alliances = filter_alliance_selections_by_scouting_team().filter(
            AllianceSelection.event_id == event_id
        ).all()
        for alliance in alliances:
            picked_teams.update(alliance.get_all_teams())
        
        # Get avoid and do not pick lists for this event (filtered by scouting team)
        avoid_teams = set(entry.team_id for entry in filter_avoid_entries_by_scouting_team().filter(
            AvoidEntry.event_id == event_id
        ).all())
        do_not_pick_teams = set(entry.team_id for entry in filter_do_not_pick_by_scouting_team().filter(
            DoNotPickEntry.event_id == event_id
        ).all())
        
        # Calculate metrics for available teams
        team_recommendations = []
        do_not_pick_recommendations = []  # Separate list for do not pick teams
        teams_with_no_data = []  # For teams without scouting data
        
        for team in all_teams:
            if team.id not in picked_teams:
                try:
                    analytics_result = calculate_team_metrics(team.id)
                    metrics = analytics_result.get('metrics', {})
                    if metrics:
                        team_data = {
                            'team': team,
                            'metrics': metrics,
                            'total_points': metrics.get('total_points', 0),
                            'auto_points': metrics.get('auto_points', 0),
                            'teleop_points': metrics.get('teleop_points', 0),
                            'endgame_points': metrics.get('endgame_points', 0),
                            'is_avoided': team.id in avoid_teams,
                            'is_do_not_pick': team.id in do_not_pick_teams
                        }
                        
                        if team.id in do_not_pick_teams:
                            do_not_pick_recommendations.append(team_data)
                        else:
                            team_recommendations.append(team_data)
                    else:
                        # Team exists but has no metrics data
                        teams_with_no_data.append({
                            'team': team,
                            'metrics': {},
                            'total_points': 0,
                            'auto_points': 0,
                            'teleop_points': 0,
                            'endgame_points': 0,
                            'is_avoided': team.id in avoid_teams,
                            'is_do_not_pick': team.id in do_not_pick_teams,
                            'has_no_data': True
                        })
                except Exception as e:
                    print(f"Error calculating metrics for team {team.team_number}: {e}")
                    # Still add the team without metrics
                    teams_with_no_data.append({
                        'team': team,
                        'metrics': {},
                        'total_points': 0,
                        'auto_points': 0,
                        'teleop_points': 0,
                        'endgame_points': 0,
                        'is_avoided': team.id in avoid_teams,
                        'is_do_not_pick': team.id in do_not_pick_teams,
                        'has_no_data': True
                    })
        
        # Optionally apply a small trend adjustment to the sort key.
        # If two teams are very close in average points, prefer the one trending up.
        def _compute_recent_trend(team_obj, event_filter=None, max_history=12):
            """Compute a trend slope (points per match) for a team by combining slopes from
            multiple historical windows. This avoids overreacting to a single last-match
            value and captures both recent form and longer-term trends.

            Approach:
              - Collect up to `max_history` recent records (by timestamp).
              - Compute simple linear slope on multiple windows (recent, mid, long).
              - Combine slopes with weights favoring recent data but including longer history.

            Returns combined slope (float).
            """
            try:
                from app.models import Match
                # Fetch recent records ordered by timestamp ascending so x indexes map to time
                q = ScoutingData.query.filter(ScoutingData.team_id == team_obj.id)
                if event_filter:
                    q = q.join(Match).filter(Match.event_id == event_filter)
                records = q.order_by(ScoutingData.timestamp).all()
                if not records:
                    return 0.0

                # Limit to most recent max_history entries
                records = records[-max_history:]
                n = len(records)
                if n < 2:
                    return 0.0

                # Helper: compute slope for a list of numeric y values (x is implicit indices)
                def _slope_from_ys(ys):
                    m = len(ys)
                    if m < 2:
                        return 0.0
                    xs = list(range(m))
                    mean_x = sum(xs) / m
                    mean_y = sum(ys) / m
                    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(xs, ys))
                    den = sum((xi - mean_x) ** 2 for xi in xs) or 1.0
                    return num / den

                # Build total points timeline
                totals = []
                for rec in records:
                    try:
                        auto_pts = rec._calculate_auto_points_dynamic(rec.data, game_config)
                        teleop_pts = rec._calculate_teleop_points_dynamic(rec.data, game_config)
                        endgame_pts = rec._calculate_endgame_points_dynamic(rec.data, game_config)
                        total_pts = auto_pts + teleop_pts + endgame_pts
                    except Exception:
                        total_pts = 0.0
                        if isinstance(rec.data, dict):
                            for v in rec.data.values():
                                if isinstance(v, (int, float)):
                                    total_pts += v
                    totals.append(float(total_pts))

                # Define windows: recent (last 3-5), mid (last ~8), long (up to max_history)
                recent_w = min(5, n)
                mid_w = min(8, n)
                long_w = n

                recent_slope = _slope_from_ys(totals[-recent_w:]) if recent_w >= 2 else 0.0
                mid_slope = _slope_from_ys(totals[-mid_w:]) if mid_w >= 2 else 0.0
                long_slope = _slope_from_ys(totals[-long_w:]) if long_w >= 2 else 0.0

                # Weighted combination (favor recent but include longer-term): Tunable weights
                combined = (0.6 * recent_slope) + (0.3 * mid_slope) + (0.1 * long_slope)

                return combined
            except Exception:
                return 0.0

        # Sort regular teams by total points (descending), but adjust by a small trend factor when use_trends is True
        def get_sort_key(team_data):
            base_score = team_data['total_points']
            # Avoid penalty for avoided teams at this stage (handled separately by badge)
            trend_adj = 0.0
            if use_trends:
                try:
                    team_obj = team if False else Team.query.get(team_data['team'].id if isinstance(team_data.get('team'), Team) else team_data['team_id'])
                except Exception:
                    team_obj = None
                # NB: team_obj may be None when team_data originates from teams_with_no_data path
                if team_obj:
                    try:
                        # Use a longer history for stability
                        slope = _compute_recent_trend(team_obj, event_filter=event_id, max_history=12)
                        # Convert slope (points per match) to a score adjustment. Use a modest weight
                        # and cap to avoid extreme influence from noisy data.
                        trend_adj = max(min(slope * 1.0, 8.0), -8.0)  # cap adjustment to +/-8 points
                    except Exception:
                        trend_adj = 0.0

            effective = base_score + trend_adj
            # Penalize avoided teams slightly
            if team_data['is_avoided']:
                return effective * 0.7  # Reduce score by 30% for avoided teams
            return effective

        team_recommendations.sort(key=get_sort_key, reverse=True)
        
        # Sort do not pick teams separately
        do_not_pick_recommendations.sort(key=lambda x: x['total_points'], reverse=True)
        
        # Sort teams with no data by team number
        teams_with_no_data.sort(key=lambda x: x['team'].team_number)
        
        # Combine lists: regular teams first, then do not pick teams, then teams with no data
        all_recommendations = team_recommendations + do_not_pick_recommendations + teams_with_no_data
        
        # Build the recommendations list
        result_recommendations = []
        for rec in all_recommendations:
            # Build component metrics display string
            component_display_parts = []
            def _resolve_metric(metrics_dict, metric_id):
                """Resolve a metric value from metrics_dict using common aliases and case-insensitive matches."""
                if not metrics_dict:
                    return 0
                # Direct match
                if metric_id in metrics_dict:
                    return metrics_dict.get(metric_id) or 0

                # Common aliases
                alias_map = {
                    'apt': 'auto_points',
                    'tpt': 'teleop_points',
                    'ept': 'endgame_points',
                    'auto': 'auto_points',
                    'teleop': 'teleop_points',
                    'endgame': 'endgame_points',
                    'tot': 'total_points'
                }
                low = metric_id.lower()
                if low in alias_map and alias_map[low] in metrics_dict:
                    return metrics_dict.get(alias_map[low]) or 0

                # Try case-insensitive key match and substring matches
                for k, v in metrics_dict.items():
                    if not k:
                        continue
                    if k.lower() == low:
                        return v or 0
                for k, v in metrics_dict.items():
                    if low in k.lower() or k.lower() in low:
                        return v or 0

                # Last resort: if metric_id looks like a short code (1-4 chars), try mapping by known prefixes
                if low.startswith('a') and 'auto_points' in metrics_dict:
                    return metrics_dict.get('auto_points') or 0
                if low.startswith('t') and 'teleop_points' in metrics_dict:
                    return metrics_dict.get('teleop_points') or 0
                if low.startswith('e') and 'endgame_points' in metrics_dict:
                    return metrics_dict.get('endgame_points') or 0

                return 0

            for i, metric_id in enumerate(component_metric_ids):
                if i == 0:
                    prefix = "A:"  # Auto
                elif i == 1:
                    prefix = "T:"  # Teleop
                elif i == 2:
                    prefix = "E:"  # Endgame
                else:
                    # Use first letter of metric name for other components
                    metric_name = metric_info.get(metric_id, {}).get('name', metric_id)
                    prefix = f"{metric_name[0]}:"

                raw_val = _resolve_metric(rec.get('metrics', {}), metric_id)
                try:
                    value = round(float(raw_val), 1)
                except Exception:
                    value = 0

                component_display_parts.append(f"{prefix}{value}")

            component_metrics_display = " ".join(component_display_parts)

            # Determine total points robustly: prefer configured total_metric_id, then 'total_points', then sum components
            metrics_dict = rec.get('metrics', {}) or {}
            total_val = 0
            if total_metric_id and total_metric_id in metrics_dict:
                total_val = metrics_dict.get(total_metric_id, 0) or 0
            elif 'total_points' in metrics_dict:
                total_val = metrics_dict.get('total_points', 0) or 0
            else:
                # Sum component metrics if available
                for mid in component_metric_ids:
                    mval = metrics_dict.get(mid, 0) or 0
                    try:
                        total_val += float(mval)
                    except Exception:
                        continue

            team_data = {
                'team_id': rec['team'].id,
                'team_number': rec['team'].team_number,
                'team_name': rec['team'].team_name or f"Team {rec['team'].team_number}",
                'total_points': round(total_val, 1),
                'component_metrics_display': component_metrics_display,
                # Keep these for backwards compatibility
                'auto_points': round(metrics_dict.get(component_metric_ids[0], metrics_dict.get('auto_points', 0)) or 0, 1) if component_metric_ids else 0,
                'teleop_points': round(metrics_dict.get(component_metric_ids[1], metrics_dict.get('teleop_points', 0)) or 0, 1) if len(component_metric_ids) > 1 else 0,
                'endgame_points': round(metrics_dict.get(component_metric_ids[2], metrics_dict.get('endgame_points', 0)) or 0, 1) if len(component_metric_ids) > 2 else 0,
                'is_avoided': rec['is_avoided'],
                'is_do_not_pick': rec['is_do_not_pick'],
                'has_no_data': rec.get('has_no_data', False)
            }
            # Compute recent trend (slope) for client display (small, robust indicator)
            try:
                slope = _compute_recent_trend(rec['team'], event_filter=event_id, max_history=12)
            except Exception:
                slope = 0.0

            # Small threshold to avoid noisy up/down flips
            THRESHOLD = 0.05
            if slope > THRESHOLD:
                direction = 'up'
            elif slope < -THRESHOLD:
                direction = 'down'
            else:
                direction = 'flat'

            team_data['trend_slope'] = round(float(slope), 2)
            team_data['trend_direction'] = direction
            # Predict next match score using average total_points plus recent slope
            try:
                predicted = float(team_data.get('total_points', 0)) + float(slope)
            except Exception:
                predicted = float(team_data.get('total_points', 0))
            team_data['predicted_points'] = round(predicted, 1)
            result_recommendations.append(team_data)
        
        return jsonify({
            'recommendations': result_recommendations
        })
        
    except Exception as e:
        print(f"Error in get_recommendations: {e}")
        return jsonify({'error': str(e), 'recommendations': []}), 500

@bp.route('/api/update', methods=['POST'])
def update_alliance():
    """Update alliance selection via API"""
    data = request.get_json()
    
    alliance_id = data.get('alliance_id')
    position = data.get('position')
    team_id = data.get('team_id')
    
    if not all([alliance_id, position, team_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    # Validate position
    if position not in ['captain', 'first_pick', 'second_pick', 'third_pick']:
        return jsonify({'success': False, 'message': 'Invalid position'})
    
    # Get the alliance
    alliance = AllianceSelection.query.filter_by(id=alliance_id, scouting_team_number=current_user.scouting_team_number).first()
    alliance = AllianceSelection.query.filter_by(id=alliance_id, scouting_team_number=current_user.scouting_team_number).first()
    if not alliance:
        return jsonify({'success': False, 'message': 'Alliance not found'})
    
    # Get the team
    team = Team.query.filter_by(team_number=team_id).first()
    if not team:
        return jsonify({'success': False, 'message': 'Team not found'})
    
    # Check if team is already picked in any alliance for this event
    existing_alliances = AllianceSelection.query.filter_by(event_id=alliance.event_id).all()
    for existing_alliance in existing_alliances:
        if team.id in existing_alliance.get_all_teams():
            return jsonify({
                'success': False, 
                'message': f'Team {team_id} is already selected in Alliance {existing_alliance.alliance_number}'
            })
    
    # Update the alliance
    setattr(alliance, position, team.id)
    
    try:
        db.session.commit()
        
        # Emit real-time update with complete data
        alliance_data = {
            'alliance_id': alliance.id,
            'alliance_number': alliance.alliance_number,
            'position': position,
            'team_id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'action': 'assign'
        }
        emit_alliance_update(alliance.event_id, alliance_data)
        emit_recommendations_update(alliance.event_id)
        
        return jsonify({'success': True, 'message': f'Team {team_id} assigned to Alliance {alliance.alliance_number}'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})

@bp.route('/api/remove', methods=['POST'])
def remove_team():
    """Remove a team from alliance selection"""
    data = request.get_json()
    
    alliance_id = data.get('alliance_id')
    position = data.get('position')
    
    if not all([alliance_id, position]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    # Validate position
    if position not in ['captain', 'first_pick', 'second_pick', 'third_pick']:
        return jsonify({'success': False, 'message': 'Invalid position'})
    
    # Get the alliance
    alliance = AllianceSelection.query.get(alliance_id)
    if not alliance:
        return jsonify({'success': False, 'message': 'Alliance not found'})
    
    # Remove the team
    setattr(alliance, position, None)
    
    try:
        db.session.commit()
        
        # Emit real-time update
        alliance_data = {
            'alliance_id': alliance.id,
            'alliance_number': alliance.alliance_number,
            'position': position,
            'team_id': None,
            'team_number': None,
            'team_name': None,
            'action': 'remove'
        }
        emit_alliance_update(alliance.event_id, alliance_data)
        emit_recommendations_update(alliance.event_id)
        
        return jsonify({'success': True, 'message': 'Team removed from alliance'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})

@bp.route('/reset/<int:event_id>')
def reset_alliances(event_id):
    """Reset all alliance selections for an event"""
    event = Event.query.get_or_404(event_id)
    
    # Clear all alliance selections for this event
    alliances = AllianceSelection.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).all()
    for alliance in alliances:
        alliance.captain = None
        alliance.first_pick = None
        alliance.second_pick = None
        alliance.third_pick = None
    
    try:
        db.session.commit()
        
        # Emit real-time reset update
        socketio.emit('alliances_reset', {'event_id': event_id}, room=f'alliance_event_{event_id}')
        emit_recommendations_update(event_id)
        
        flash('Alliance selections have been reset.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error resetting alliances: {str(e)}', 'danger')
    
    return redirect(url_for('alliances.index'))

@bp.route('/manage_lists/<int:event_id>')
def manage_lists(event_id):
    """Manage avoid and do not pick lists"""
    event = Event.query.get_or_404(event_id)
    
    # Get current lists
    avoid_entries = AvoidEntry.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).join(Team).all()
    do_not_pick_entries = DoNotPickEntry.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).join(Team).all()
    
    # Get all teams for this event from team_event relationship
    all_teams = db.session.query(Team).join(
        team_event, Team.id == team_event.c.team_id
    ).filter(
        team_event.c.event_id == event_id
    ).order_by(Team.team_number).all()
        
    # If no teams found in team_event relationship, fall back to all teams with scouting data
    if not all_teams:
        from app.models import Match
        all_teams = db.session.query(Team).join(ScoutingData).join(
            Match, ScoutingData.match_id == Match.id
        ).filter(
            Match.event_id == event_id
        ).distinct().order_by(Team.team_number).all()
    
    return render_template('alliances/manage_lists.html',
                         event=event,
                         avoid_entries=avoid_entries,
                         do_not_pick_entries=do_not_pick_entries,
                         all_teams=all_teams,
                         **get_theme_context())

@bp.route('/api/add_to_list', methods=['POST'])
def add_to_list():
    """Add a team to avoid or do not pick list"""
    data = request.get_json()
    
    team_number = data.get('team_number')
    event_id = data.get('event_id')
    list_type = data.get('list_type')  # 'avoid' or 'do_not_pick'
    reason = data.get('reason', '')
    
    if not all([team_number, event_id, list_type]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    if list_type not in ['avoid', 'do_not_pick']:
        return jsonify({'success': False, 'message': 'Invalid list type'})
    
    # Get the team
    team = Team.query.filter_by(team_number=team_number).first()
    if not team:
        return jsonify({'success': False, 'message': 'Team not found'})
    
    # Check if team is already in the list
    if list_type == 'avoid':
        existing = AvoidEntry.query.filter_by(team_id=team.id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
        if existing:
            return jsonify({'success': False, 'message': 'Team already in avoid list'})
        
        entry = AvoidEntry(team_id=team.id, event_id=event_id, reason=reason, scouting_team_number=current_user.scouting_team_number)
    else:  # do_not_pick
        existing = DoNotPickEntry.query.filter_by(team_id=team.id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
        if existing:
            return jsonify({'success': False, 'message': 'Team already in do not pick list'})
        
        entry = DoNotPickEntry(team_id=team.id, event_id=event_id, reason=reason, scouting_team_number=current_user.scouting_team_number)
    
    try:
        db.session.add(entry)
        db.session.commit()
        
        # Emit real-time update
        list_data = {
            'event_id': event_id,
            'team_id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'list_type': list_type,
            'reason': reason,
            'action': 'add'
        }
        emit_lists_update(event_id, list_data)
        emit_recommendations_update(event_id)
        
        return jsonify({'success': True, 'message': f'Team {team_number} added to {list_type.replace("_", " ")} list'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/get_alliances/<int:event_id>')
def get_alliances(event_id):
    """Get current state of all alliances for an event"""
    try:
        alliances = filter_alliance_selections_by_scouting_team().filter(
            AllianceSelection.event_id == event_id
        ).order_by(AllianceSelection.alliance_number).all()
        
        alliance_data = []
        for alliance in alliances:
            alliance_info = {
                'id': alliance.id,
                'alliance_number': alliance.alliance_number,
                'captain': None,
                'first_pick': None,
                'second_pick': None,
                'third_pick': None
            }
            
            # Get team info for each position
            for position in ['captain', 'first_pick', 'second_pick', 'third_pick']:
                team_id = getattr(alliance, position)
                if team_id:
                    team = Team.query.get(team_id)
                    if team:
                        alliance_info[position] = {
                            'team_id': team.id,
                            'team_number': team.team_number,
                            'team_name': team.team_name or f'Team {team.team_number}'
                        }
            
            alliance_data.append(alliance_info)
        
        return jsonify({
            'success': True,
            'alliances': alliance_data
        })
    except Exception as e:
        print(f"Error in get_alliances: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/api/team_metrics')
def team_metrics():
    """Return basic metrics for a team_number (useful for client-side UI updates).

    Query params:
      - team_number (required)
      - event_id (optional)
    """
    team_number = request.args.get('team_number')
    event_id = request.args.get('event_id', type=int)

    if not team_number:
        return jsonify({'error': 'team_number required'}), 400

    # Find the team
    team = Team.query.filter_by(team_number=team_number).first()
    if not team:
        return jsonify({'error': 'Team not found'}), 404

    try:
        analytics_result = calculate_team_metrics(team.id, event_id=event_id)
        metrics = analytics_result.get('metrics', {}) or {}

        # Prefer 'total_points' then 'tot' or sum components as a fallback
        total = 0
        if 'total_points' in metrics:
            total = metrics.get('total_points', 0) or 0
        elif 'tot' in metrics:
            total = metrics.get('tot', 0) or 0
        else:
            # fallback to common component ids
            total = (metrics.get('apt', 0) or 0) + (metrics.get('tpt', 0) or 0) + (metrics.get('ept', 0) or 0)

        return jsonify({'team_number': team.team_number, 'total_points': round(float(total), 1)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/api/remove_from_list', methods=['POST'])
def remove_from_list():
    """Remove a team from avoid or do not pick list"""
    data = request.get_json()
    
    team_id = data.get('team_id')
    event_id = data.get('event_id')
    list_type = data.get('list_type')  # 'avoid' or 'do_not_pick'
    
    if not all([team_id, event_id, list_type]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    if list_type not in ['avoid', 'do_not_pick']:
        return jsonify({'success': False, 'message': 'Invalid list type'})
    
    # Find and remove the entry
    if list_type == 'avoid':
        entry = AvoidEntry.query.filter_by(team_id=team_id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
    else:  # do_not_pick
        entry = DoNotPickEntry.query.filter_by(team_id=team_id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
    
    if not entry:
        return jsonify({'success': False, 'message': 'Entry not found'})
    
    try:
        team = entry.team  # Get team info before deleting
        db.session.delete(entry)
        db.session.commit()
        
        # Emit real-time update
        list_data = {
            'event_id': event_id,
            'team_id': team_id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'list_type': list_type,
            'action': 'remove'
        }
        emit_lists_update(event_id, list_data)
        emit_recommendations_update(event_id)
        
        return jsonify({'success': True, 'message': f'Team removed from {list_type.replace("_", " ")} list'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})
