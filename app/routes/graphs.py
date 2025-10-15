from flask import Blueprint, render_template, current_app, request, jsonify, url_for, redirect, flash, abort
from flask_login import login_required, current_user
from app.routes.auth import analytics_required, role_required
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd
import json
import plotly
import sys
import numpy as np
from datetime import datetime, timezone
from app.models import Team, Match, ScoutingData, Event, SharedGraph
from app.models import CustomPage
from app import db
from app.utils.analysis import calculate_team_metrics
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_effective_game_config
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code
)
import os
import secrets
import copy


def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }


def _chart_theme():
    """Return a small dict of theme values to use for Plotly charts.

    Provides `plot_bg`, `paper_bg`, `text_main`, `text_muted`, and `grid_color`.
    Falls back to transparent backgrounds and reasonable defaults when theme is missing.
    """
    try:
        theme = ThemeManager().get_current_theme() or {}
    except Exception:
        theme = {}

    card_bg = theme.get('colors', {}).get('card-bg', 'rgba(0,0,0,0)')
    plot_bg = card_bg
    paper_bg = card_bg
    text_main = theme.get('colors', {}).get('text-main', '#000')
    text_muted = theme.get('colors', {}).get('text-muted', 'gray')
    grid_color = theme.get('colors', {}).get('grid-color', 'rgba(128,128,128,0.15)')

    return {
        'plot_bg': plot_bg,
        'paper_bg': paper_bg,
        'text_main': text_main,
        'text_muted': text_muted,
        'grid_color': grid_color
    }


def _sanitize_public_widgets(widgets):
    """Return a deep-copied list of widgets for public consumption.

    Historically we stripped image URLs for public shares. The user requested
    that public shares should include images again, so this helper now returns
    a deep copy of the widgets without removing image_url fields.
    """
    sanitized = []
    for w in (widgets or []):
        try:
            wcopy = copy.deepcopy(w)
        except Exception:
            try:
                wcopy = json.loads(json.dumps(w))
            except Exception:
                wcopy = {}

        # keep everything as-is (including any image_url). If we later want
        # to provide owner-controlled opt-in behavior we can filter here.

        sanitized.append(wcopy)
    return sanitized


def _build_page_context(page, scouting_team_number):
    """Build plots and viewer context for a CustomPage using the provided
    scouting_team_number for queries that would normally use current_user.

    Returns: (plots, metrics, scoring_elements, teams, events, matches)
    """
    widgets = []
    try:
        widgets = page.widgets()
    except Exception:
        widgets = []

    plots = {}

    # Import needed functions for new widget types
    from app.utils.analysis import predict_match_outcome, get_match_details_with_teams

    # For each widget, generate plots and collect them under a widget key
    for i, widget in enumerate(widgets):
        wtype = widget.get('type')
        wkey = f'widget_{i}'
        if wtype == 'graph':
            selected_teams = widget.get('teams', [])
            if isinstance(selected_teams, list):
                selected_teams = [s for s in selected_teams]
            metric = widget.get('metric', 'points')
            metric_alias = 'tot' if metric in ('total_points', 'points', 'tot') else metric
            graph_types = widget.get('graph_types', ['bar', 'line'])
            data_view = widget.get('data_view', 'averages')

            team_ids = []
            if selected_teams and not (len(selected_teams) == 1 and str(selected_teams[0]) == 'all'):
                for s in selected_teams:
                    if s == 'all':
                        team_ids = []
                        break
                    try:
                        team_ids.append(int(s))
                    except Exception:
                        pass
                if team_ids:
                    teams = Team.query.filter(Team.id.in_(team_ids)).all()
                    found_ids = {t.id for t in teams}
                    missing = [tid for tid in team_ids if tid not in found_ids]
                    if missing:
                        more_by_number = Team.query.filter(Team.team_number.in_(missing)).all()
                        if more_by_number:
                            teams.extend(more_by_number)
                else:
                    teams = Team.query.order_by(Team.team_number).all()
            else:
                teams = Team.query.order_by(Team.team_number).all()

            # Deduplicate teams
            unique_map = {}
            for t in teams:
                if t.team_number not in unique_map:
                    unique_map[t.team_number] = t
            teams = sorted(unique_map.values(), key=lambda x: x.team_number)

            team_data = {}
            if teams:
                team_ids = [t.id for t in teams]
                scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids), ScoutingData.scouting_team_number==scouting_team_number).all()
                for data in scouting_data:
                    team = data.team
                    match = data.match
                    if team.team_number not in team_data:
                        team_data[team.team_number] = {'team_name': team.team_name, 'matches': []}
                    if metric_alias == 'tot':
                        metric_value = data.calculate_metric('tot')
                    else:
                        metric_value = data.calculate_metric(metric_alias)
                    team_data[team.team_number]['matches'].append({'match_number': match.match_number if match else None, 'metric_value': metric_value, 'timestamp': match.timestamp if match else None})

            # Generate plots unless user_select controls exist
            if widget.get('user_select') or widget.get('graphtype_user_select') or widget.get('teams_user_select'):
                widget_plots = {}
            else:
                widget_plots = {}
                for gt in graph_types:
                    if gt == 'bar':
                        widget_plots.update(_create_bar_chart(team_data, metric, data_view))
                    elif gt == 'line':
                        widget_plots.update(_create_line_chart(team_data, metric, data_view))
                    elif gt == 'scatter':
                        widget_plots.update(_create_scatter_chart(team_data, metric, data_view))
                    elif gt == 'histogram':
                        widget_plots.update(_create_histogram_chart(team_data, metric, data_view))
                    elif gt == 'violin':
                        widget_plots.update(_create_violin_chart(team_data, metric, data_view))
                    elif gt == 'box':
                        widget_plots.update(_create_box_chart(team_data, metric, data_view))
                    elif gt == 'sunburst':
                        widget_plots.update(_create_sunburst_chart(team_data, metric, data_view))
                    elif gt == 'treemap':
                        widget_plots.update(_create_treemap_chart(team_data, metric, data_view))
                    elif gt == 'waterfall':
                        widget_plots.update(_create_waterfall_chart(team_data, metric, data_view))
                    elif gt == 'sankey':
                        widget_plots.update(_create_sankey_chart(team_data, metric, data_view))
                    elif gt == 'heatmap':
                        widget_plots.update(_create_heatmap_chart(team_data, metric, data_view))
                    elif gt == 'bubble':
                        widget_plots.update(_create_bubble_chart(team_data, metric, data_view))
                    elif gt == 'area':
                        widget_plots.update(_create_area_chart(team_data, metric, data_view))
                    elif gt == 'radar':
                        widget_plots.update(_create_radar_chart(team_data, metric, data_view))

            plots[wkey] = {'config': widget, 'plots': widget_plots}

        elif wtype == 'match_prediction':
            match_id = widget.get('match')
            if widget.get('prediction_match') == 'user_select':
                # no user selection available for public view by default
                match_id = None

            prediction_data = None
            if match_id and match_id != 'user_select':
                try:
                    match_details = get_match_details_with_teams(int(match_id))
                    if match_details and match_details.get('prediction'):
                        prediction = match_details['prediction']
                        prediction_data = {
                            'red_alliance': prediction.get('red_alliance', {}),
                            'blue_alliance': prediction.get('blue_alliance', {}),
                            'predicted_winner': prediction.get('predicted_winner', 'unknown'),
                            'probabilities': prediction.get('probabilities', {'red': 0, 'blue': 0, 'tie': 0}),
                            'confidence': prediction.get('confidence', 0),
                            'match': match_details.get('match'),
                            'match_completed': match_details.get('match_completed', False),
                            'actual_winner': match_details.get('actual_winner')
                        }
                except Exception:
                    prediction_data = None
            plots[wkey] = {'config': widget, 'plots': {}, 'prediction_data': prediction_data}

        else:
            plots[wkey] = {'config': widget, 'plots': {}}

    # Provide metric/scoring/teams context for viewer controls
    game_config = get_effective_game_config()
    metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
    try:
        if isinstance(metrics, list):
            if not any(m.get('id') == 'total_points' for m in metrics):
                metrics.append({'id': 'total_points', 'name': 'Total Points'})
    except Exception:
        metrics = metrics
    scoring_elements = []
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        for el in game_config.get(period, {}).get('scoring_elements', []):
            scoring_elements.append({'period': period, 'id': el.get('perm_id', el.get('id')), 'name': el.get('name', el.get('id'))})

    teams_q = Team.query.order_by(Team.team_number).all()
    teams = [{'id': t.team_number, 'name': t.team_name or f'Team {t.team_number}'} for t in teams_q]

    events_q = Event.query.order_by(Event.name).limit(500).all()
    events = [{'id': e.id, 'name': e.name or e.code, 'code': e.code} for e in events_q]

    matches_q = Match.query.order_by(Match.event_id, Match.match_number).limit(1000).all()
    matches = [{'id': m.id, 'event_id': m.event_id, 'match_type': m.match_type, 'match_number': m.match_number} for m in matches_q]

    return plots, metrics, scoring_elements, teams, events, matches

bp = Blueprint('graphs', __name__, url_prefix='/graphs')

@bp.route('/')
@analytics_required
def index():
    """Graphs dashboard page"""
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Get all teams and events for selection dropdowns
    # For graphs, we want to show all teams but prioritize current event teams
    from app.utils.team_isolation import get_current_scouting_team_number
    
    current_scouting_team = get_current_scouting_team_number()
    
    if current_event:
        # Only include teams/events visible to the current scouting team
        current_event_teams = list(filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all())
        other_teams = filter_teams_by_scouting_team().filter(~Team.id.in_([t.id for t in current_event_teams])).order_by(Team.team_number).all()
        all_teams_raw = current_event_teams + other_teams
    else:
        # No current event: only show teams visible to the current scouting team
        all_teams_raw = filter_teams_by_scouting_team().order_by(Team.team_number).all()
    
    # Deduplicate teams by team_number.
    # Preference order when duplicate team_number found:
    # 1) prefer a team record with a non-empty, non-numeric team_name
    # 2) if both/neither have a good name, prefer the one with scouting data for current_scouting_team
    teams_by_number = {}
    for team in all_teams_raw:
        team_number = team.team_number

        if team_number not in teams_by_number:
            teams_by_number[team_number] = team
        else:
            existing_team = teams_by_number[team_number]

            # Helper to determine if a name is meaningful (non-empty and not purely numeric)
            def _has_meaningful_name(t):
                try:
                    name = (t.team_name or '').strip()
                except Exception:
                    name = ''
                return bool(name) and not name.isdigit()

            team_has_name = _has_meaningful_name(team)
            existing_has_name = _has_meaningful_name(existing_team)

            # If one has a meaningful name and the other doesn't, prefer the named one
            if team_has_name and not existing_has_name:
                teams_by_number[team_number] = team
                continue
            if existing_has_name and not team_has_name:
                continue

            # Otherwise, fall back to preferring records with scouting data for current_scouting_team
            has_data = ScoutingData.query.filter_by(
                team_id=team.id,
                scouting_team_number=current_scouting_team
            ).first() is not None
            existing_has_data = ScoutingData.query.filter_by(
                team_id=existing_team.id,
                scouting_team_number=current_scouting_team
            ).first() is not None

            if has_data and not existing_has_data:
                teams_by_number[team_number] = team
    
    # Convert back to list, sorted by team number
    all_teams = sorted(teams_by_number.values(), key=lambda t: t.team_number)
    
    all_events = filter_events_by_scouting_team().all()
    
    # Calculate team metrics for sorting
    team_metrics = {}
    for team in all_teams:
        # Get metrics for the team - function returns {team_number, match_count, metrics}
        analytics_result = calculate_team_metrics(team.id)
        metrics = analytics_result.get('metrics', {})
        team_metrics[team.team_number] = metrics
    
    # Create team-event mapping for client-side filtering
    team_event_mapping = {}
    for team in all_teams:
        team_event_mapping[team.team_number] = [event.id for event in team.events]
        
    # Create a JSON representation of all teams for use in JavaScript
    all_teams_data = []
    for team in all_teams:
        team_data = {
            'teamNumber': team.team_number,
            'teamName': team.team_name or "Unknown",
            'displayText': f"{team.team_number} - {team.team_name or 'Unknown'}",
            'points': team_metrics.get(team.team_number, {}).get('total_points', 0)
        }
        all_teams_data.append(team_data)
    
    all_teams_json = json.dumps(all_teams_data)
    
    # Get selected teams from query parameters if any
    selected_team_numbers = request.args.getlist('teams', type=int)
    selected_event_id = request.args.get('event_id', type=int)
    selected_metric = request.args.get('metric', '')
    selected_graph_types = request.args.getlist('graph_types')
    selected_data_view = request.args.get('data_view', 'averages')
    # New sort parameter: controls x-axis ordering for team-level charts
    # Supported values: 'points_desc' (default), 'points_asc', 'team_asc', 'team_desc'
    selected_sort = request.args.get('sort', 'points_desc')
    
    # Normalize metric selection: treat empty/default, legacy ids and explicit total_points
    # as the canonical 'points' metric so the default behaves like Total Points.
    if not selected_metric or selected_metric.strip() == '' or selected_metric in ('total_points', 'tot'):
        selected_metric = 'points'
    
    # If points is selected but not available in dropdown, we'll still process it
    # since it's our default metric
    
    # Default to bar, line, and scatter graphs if none selected
    if not selected_graph_types:
        selected_graph_types = ['bar', 'line', 'scatter']
    
    print(f"Selected teams: {selected_team_numbers}")
    print(f"Selected event ID: {selected_event_id}")
    print(f"Selected metric: {selected_metric}")
    print(f"Selected graph types: {selected_graph_types}")
    print(f"Selected data view: {selected_data_view}")
    
    # Create sample demonstration graphs
    plots = {}
    
    # Only create graphs if teams are selected
    if selected_team_numbers:
        # Get scouting data for selected teams (respect team isolation)
        teams = filter_teams_by_scouting_team().filter(Team.team_number.in_(selected_team_numbers)).all()
        print(f"Found {len(teams)} teams")
        
        if selected_event_id:
            # Get matches from selected event
            matches = Match.query.filter_by(event_id=selected_event_id).all()
            match_ids = [match.id for match in matches]
            
            # Filter scouting data for these matches and teams
            team_ids = [team.id for team in teams]
            scouting_data = ScoutingData.query.filter(
                ScoutingData.team_id.in_(team_ids),
                ScoutingData.match_id.in_(match_ids),
                ScoutingData.scouting_team_number==current_user.scouting_team_number
            ).all()
            print(f"Found {len(scouting_data)} scouting records for selected teams at event {selected_event_id}")
        else:
            # Get all scouting data for selected teams
            team_ids = [team.id for team in teams]
            scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids), ScoutingData.scouting_team_number==current_user.scouting_team_number).all()
            print(f"Found {len(scouting_data)} scouting records for selected teams across all events")
        
        # Generate graphs if we have teams selected
        if teams:
            # Create team performance graphs using shared graph helper structure
            team_data = {}
            
            # Process scouting data to match shared graph format
            if scouting_data:
                # Calculate selected metric for each team's matches
                for data in scouting_data:
                    team = data.team
                    match = data.match
                    if team.team_number not in team_data:
                        team_data[team.team_number] = {
                            'team_name': team.team_name, 
                            'matches': []
                        }
                    
                    # Calculate the selected metric for this match
                    # Handle default 'points' metric which should map to total points
                    if selected_metric == 'points' or selected_metric == '':
                        metric_value = data.calculate_metric('tot')  # Use 'tot' for total points
                    else:
                        metric_value = data.calculate_metric(selected_metric)
                    
                    team_data[team.team_number]['matches'].append({
                        'match_number': match.match_number,
                        'match_type': match.match_type,
                        'metric_value': metric_value,
                        'timestamp': match.timestamp
                    })
            else:
                # No scouting data found, create empty structure
                print("No scouting data found")
                for team in teams:
                    team_data[team.team_number] = {
                        'team_name': team.team_name,
                        'matches': []
                    }

            # Generate the requested graph types using helper functions
            # Use the selected list of graph types for rendering
            for graph_type in selected_graph_types:
                if graph_type == 'bar':
                    plots.update(_create_bar_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'line':
                    plots.update(_create_line_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'scatter':
                    plots.update(_create_scatter_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'histogram':
                    plots.update(_create_histogram_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'violin':
                    plots.update(_create_violin_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'box':
                    plots.update(_create_box_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'sunburst':
                    plots.update(_create_sunburst_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'treemap':
                    plots.update(_create_treemap_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'waterfall':
                    plots.update(_create_waterfall_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'sankey':
                    plots.update(_create_sankey_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'heatmap':
                    plots.update(_create_heatmap_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'bubble':
                    plots.update(_create_bubble_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'area':
                    plots.update(_create_area_chart(team_data, selected_metric, selected_data_view))
                elif graph_type == 'radar':
                    plots.update(_create_radar_chart(team_data, selected_metric, selected_data_view))

    
    return render_template('graphs/index.html', 
                          plots=plots,
                          game_config=game_config,
                          all_teams=all_teams,
                          all_teams_json=all_teams_json,
                          all_events=all_events,
                          selected_team_numbers=selected_team_numbers,
                          selected_event_id=selected_event_id,
                          selected_metric=selected_metric,
                          selected_graph_types=selected_graph_types,
                          selected_data_view=selected_data_view,
                          selected_sort=selected_sort,
                          team_event_mapping=team_event_mapping,
                          team_metrics=team_metrics,
                          **get_theme_context())


@bp.route('/scout-leaderboard')
@role_required('scout', 'analytics', 'admin')
def scout_leaderboard():
    """Leaderboard of scouts: counts of scouted matches and prediction accuracy.

    Accuracy is computed only for scouting entries where:
      - the related Match has completed scores (red_score and blue_score present), and
      - the scouting entry contains a prediction value we can interpret (several keys checked).

    The leaderboard groups by scout_id when available, otherwise by scout_name.
    """
    from app.models import ScoutingData, Match, User

    # Respect team isolation (use current user's scouting_team_number)
    scouting_team_number = getattr(current_user, 'scouting_team_number', None)

    q = ScoutingData.query
    if scouting_team_number is not None:
        q = q.filter_by(scouting_team_number=scouting_team_number)

    entries = q.all()

    # Aggregate per-scout
    leaders = {}

    def normalize_pred(pred, match):
        """Normalize a prediction value to 'red'|'blue'|'tie' or None."""
        if pred is None:
            return None
        try:
            # If numeric string or int -> treat as team number and map to alliance
            if isinstance(pred, (int,)) or (isinstance(pred, str) and pred.isdigit()):
                team_num = int(pred)
                if match and match.red_alliance:
                    if str(team_num) in (match.red_alliance or '').split(','):
                        return 'red'
                    if str(team_num) in (match.blue_alliance or '').split(','):
                        return 'blue'
                return None

            s = str(pred).strip().lower()
            if not s:
                return None
            if 'red' in s:
                return 'red'
            if 'blue' in s:
                return 'blue'
            if 'tie' in s or 'draw' in s:
                return 'tie'
            # If it's a team name like '254' already handled; otherwise unknown
            return None
        except Exception:
            return None

    for e in entries:
        key = e.scout_id if e.scout_id else (e.scout_name or 'Unknown')
        if key not in leaders:
            # Try to resolve username if we have id
            username = None
            if e.scout_id:
                try:
                    u = User.query.get(e.scout_id)
                    username = u.username if u else None
                except Exception:
                    username = None
            leaders[key] = {
                'scout_id': e.scout_id,
                'scout_name': username or e.scout_name or 'Unknown',
                'total': 0,
                'evaluated': 0,
                'correct': 0,
                'last_scouted': None
            }

        rec = leaders[key]
        rec['total'] += 1
        # update last scouted
        if not rec['last_scouted'] or (e.timestamp and e.timestamp > rec['last_scouted']):
            rec['last_scouted'] = e.timestamp

        # Only evaluate accuracy when match has completed scores
        match = None
        try:
            match = e.match
        except Exception:
            match = None

        if match and match.red_score is not None and match.blue_score is not None:
            # Attempt to find prediction value in the scouting data
            data = {}
            try:
                data = e.data or {}
            except Exception:
                data = {}

            pred_candidates = [
                data.get('predicted_winner'),
                data.get('prediction'),
                data.get('predicted'),
                data.get('winner_prediction'),
                data.get('predicted_winner_choice'),
                data.get('predicted_winner_team'),
            ]

            pred_val = None
            for p in pred_candidates:
                if p is not None:
                    pred_val = p
                    break

            norm = normalize_pred(pred_val, match)
            if norm is not None:
                rec['evaluated'] += 1
                actual = 'red' if match.red_score > match.blue_score else 'blue' if match.blue_score > match.red_score else 'tie'
                if norm == actual:
                    rec['correct'] += 1

    # Determine sort mode from query parameter. Supported: 'total' (matches scouted) or 'accuracy'
    sort_mode = request.args.get('sort', 'total') or 'total'

    leader_list = list(leaders.values())
    if sort_mode == 'accuracy':
        # Sort by accuracy desc (evaluated==0 go last), then by total desc
        leader_list.sort(key=lambda it: ((it['correct'] / it['evaluated']) if it['evaluated'] > 0 else -1, it['total']), reverse=True)
    else:
        # Default: sort by total scouted desc
        leader_list.sort(key=lambda it: it['total'], reverse=True)

    # Add rank and formatted accuracy
    ranked = []
    rank = 1
    for it in leader_list:
        accuracy = (it['correct'] / it['evaluated']) if it['evaluated'] > 0 else None
        ranked.append({
            'rank': rank,
            'scout_id': it['scout_id'],
            'scout_name': it['scout_name'],
            'total': it['total'],
            'evaluated': it['evaluated'],
            'correct': it['correct'],
            'accuracy': round(accuracy*100,2) if accuracy is not None else None,
            'last_scouted': it['last_scouted']
        })
        rank += 1

    return render_template('graphs/scout_leaderboard.html', leaders=ranked, sort_mode=sort_mode, **get_theme_context())

@bp.route('/data')
@analytics_required
def graphs_data():
    """AJAX endpoint for refreshing graphs data with new configuration"""
    # Get game configuration (will automatically use alliance config if active)
    game_config = get_effective_game_config()
    
    # Get selected parameters
    selected_team_numbers = request.args.getlist('teams', type=int)
    selected_event_id = request.args.get('event_id', type=int)
    selected_metric = request.args.get('metric', 'points')
    selected_graph_types = request.args.getlist('graph_types') or ['bar', 'line']
    selected_data_view = request.args.get('data_view', 'averages')
    selected_sort = request.args.get('sort', 'points_desc')
    
    # Get teams and events data
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    if current_event:
        current_event_teams = list(filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all())
        other_teams = filter_teams_by_scouting_team().filter(~Team.id.in_([t.id for t in current_event_teams])).order_by(Team.team_number).all()
        all_teams_raw = current_event_teams + other_teams
    else:
        all_teams_raw = filter_teams_by_scouting_team().order_by(Team.team_number).all()
    
    # Deduplicate teams by team_number, preferring ones with scouting data for current scouting team
    from app.utils.team_isolation import get_current_scouting_team_number
    current_scouting_team = get_current_scouting_team_number()
    
    teams_by_number = {}
    for team in all_teams_raw:
        team_number = team.team_number
        
        if team_number not in teams_by_number:
            teams_by_number[team_number] = team
        else:
            # If we already have a team with this number, prefer the one with scouting data
            existing_team = teams_by_number[team_number]
            
            # Check if current team has scouting data for our scouting team
            has_data = ScoutingData.query.filter_by(
                team_id=team.id, 
                scouting_team_number=current_scouting_team
            ).first() is not None
            
            # Check if existing team has scouting data for our scouting team  
            existing_has_data = ScoutingData.query.filter_by(
                team_id=existing_team.id,
                scouting_team_number=current_scouting_team  
            ).first() is not None
            
            # Prefer team with scouting data, or keep existing if both/neither have data
            if has_data and not existing_has_data:
                teams_by_number[team_number] = team
    
    # Convert back to list, sorted by team number
    all_teams = sorted(teams_by_number.values(), key=lambda t: t.team_number)
    
    all_events = filter_events_by_scouting_team().all()
    
    # Calculate team metrics
    team_metrics = {}
    for team in all_teams:
        analytics_result = calculate_team_metrics(team.id)
        metrics = analytics_result.get('metrics', {})
        team_metrics[team.team_number] = metrics
    
    # Prepare teams data for JSON
    all_teams_data = []
    for team in all_teams:
        team_data = {
            'id': team.id,
            'teamNumber': team.team_number,
            'teamName': team.team_name or "Unknown",
            'displayText': f"{team.team_number} - {team.team_name or 'Unknown'}",
            'points': team_metrics.get(team.team_number, {}).get('total_points', 0)
        }
        all_teams_data.append(team_data)
    
    # Return updated data for AJAX requests
    return jsonify({
        'success': True,
        'game_config': game_config,
        'teams': all_teams_data,
        'selected_sort': selected_sort,
        'events': [{'id': e.id, 'name': e.name, 'code': e.code} for e in all_events],
        'current_event': {'id': current_event.id, 'name': current_event.name, 'code': current_event.code} if current_event else None,
        'team_metrics': team_metrics,
        'config_timestamp': datetime.now().isoformat()
    })

@bp.route('/side-by-side')
@analytics_required
def side_by_side():
    """Side-by-side team comparison page"""
    team_numbers = request.args.getlist('teams', type=int)
    
    if not team_numbers:
        # Get game configuration
        game_config = get_effective_game_config()
        
        # Get current event based on configuration
        current_event_code = game_config.get('current_event_code')
        current_event = None
        if current_event_code:
            current_event = get_event_by_code(current_event_code)
        
        # Get teams filtered by the current event if available, otherwise show all teams
        if current_event:
            teams_raw = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
        else:
            # Only include teams visible to the current scouting team
            teams_raw = filter_teams_by_scouting_team().order_by(Team.team_number).all()
        
        # Deduplicate teams by team_number, preferring ones with scouting data for current scouting team
        from app.utils.team_isolation import get_current_scouting_team_number
        current_scouting_team = get_current_scouting_team_number()
        
        teams_by_number = {}
        for team in teams_raw:
            team_number = team.team_number
            
            if team_number not in teams_by_number:
                teams_by_number[team_number] = team
            else:
                # If we already have a team with this number, prefer the one with scouting data
                existing_team = teams_by_number[team_number]
                
                # Check if current team has scouting data for our scouting team
                has_data = ScoutingData.query.filter_by(
                    team_id=team.id, 
                    scouting_team_number=current_scouting_team
                ).first() is not None
                
                # Check if existing team has scouting data for our scouting team  
                existing_has_data = ScoutingData.query.filter_by(
                    team_id=existing_team.id,
                    scouting_team_number=current_scouting_team  
                ).first() is not None
                
                # Prefer team with scouting data, or keep existing if both/neither have data
                if has_data and not existing_has_data:
                    teams_by_number[team_number] = team
        
        # Convert back to list, sorted by team number
        teams = sorted(teams_by_number.values(), key=lambda t: t.team_number)
        
        # Use legacy key_metrics if available, otherwise use dynamic metrics
        metrics = game_config.get('data_analysis', {}).get('key_metrics', [
            {'id': 'auto_points', 'name': 'Auto Points'},
            {'id': 'teleop_points', 'name': 'Teleop Points'},
            {'id': 'endgame_points', 'name': 'Endgame Points'},
            {'id': 'total_points', 'name': 'Total Points'}
        ])
        return render_template('graphs/side_by_side_form.html', teams=teams, metrics=metrics, **get_theme_context())
    
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Get teams (respect team isolation)
    teams = filter_teams_by_scouting_team().filter(Team.team_number.in_(team_numbers)).all()
    
    # Define available metrics (use legacy if available, otherwise use dynamic)
    key_metrics_from_config = game_config.get('data_analysis', {}).get('key_metrics', [])
    
    available_metrics = key_metrics_from_config if key_metrics_from_config else [
        {'id': 'auto_points', 'name': 'Auto Points'},
        {'id': 'teleop_points', 'name': 'Teleop Points'},
        {'id': 'endgame_points', 'name': 'Endgame Points'},
        {'id': 'total_points', 'name': 'Total Points'}
    ]
    
    # Calculate detailed metrics for each team
    teams_data = []

    # Group Team records by team_number so multiple Team rows for the same team_number
    # (e.g., from different events) are combined into a single entry.
    teams_by_number = {}
    for t in teams:
        teams_by_number.setdefault(t.team_number, []).append(t)

    # Prepare helper imports once
    from app.utils.team_isolation import filter_scouting_data_by_scouting_team, get_current_scouting_team_number
    from app.utils.config_manager import get_current_game_config

    scouting_team_number = get_current_scouting_team_number()
    game_config = get_current_game_config()

    for team_number, team_group in teams_by_number.items():
        # Use first Team object as representative (for team_name, id display, etc.)
        rep_team = team_group[0]
        team_ids = [t.id for t in team_group]

        # Fetch scouting data across all team ids, honoring team isolation if enabled
        if scouting_team_number is not None:
            scouting_q = filter_scouting_data_by_scouting_team()
            scouting_data = scouting_q.filter(ScoutingData.team_id.in_(team_ids)).all()
        else:
            scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids), ScoutingData.scouting_team_number == None).all()

        # Build team_info container
        team_info = {
            'team': rep_team,
            'metrics': {},
            'match_count': len(scouting_data),
            'has_data': len(scouting_data) > 0
        }

        # For each available metric, compute per-match values and aggregates from combined data
        for metric in available_metrics:
            metric_id = metric['id']
            match_values = []

            for data in scouting_data:
                match_number = data.match.match_number if data.match else f"#{data.id}"

                if metric_id == 'auto_points':
                    match_value = data._calculate_auto_points_dynamic(data.data, game_config)
                elif metric_id == 'teleop_points':
                    match_value = data._calculate_teleop_points_dynamic(data.data, game_config)
                elif metric_id == 'endgame_points':
                    match_value = data._calculate_endgame_points_dynamic(data.data, game_config)
                elif metric_id == 'total_points':
                    auto_pts = data._calculate_auto_points_dynamic(data.data, game_config)
                    teleop_pts = data._calculate_teleop_points_dynamic(data.data, game_config)
                    endgame_pts = data._calculate_endgame_points_dynamic(data.data, game_config)
                    match_value = auto_pts + teleop_pts + endgame_pts
                else:
                    match_value = data.data.get(metric_id, 0)

                match_values.append({'match': match_number, 'value': match_value})

            # Derive aggregates from match_values
            values = [mv['value'] for mv in match_values if isinstance(mv.get('value'), (int, float))]
            if values:
                avg_val = sum(values) / len(values)
                min_val = min(values)
                max_val = max(values)
            else:
                avg_val = 0
                min_val = 0
                max_val = 0

            team_info['metrics'][metric_id] = {
                'config': metric,
                'aggregate': avg_val,
                'match_data': scouting_data,
                'match_values': match_values,
                'min': min_val,
                'max': max_val,
                'avg': avg_val
            }

        teams_data.append(team_info)
    
    # Debug: Log match values for troubleshooting
    for team_data in teams_data:
        print(f"DEBUG: Team {team_data['team'].team_number} match values:")
        for metric_id, metric_info in team_data['metrics'].items():
            match_values = metric_info.get('match_values', [])
            print(f"  {metric_id}: {len(match_values)} matches - {match_values}")
    
    return render_template('graphs/side_by_side.html',
                         teams_data=teams_data,
                         available_metrics=available_metrics,
                         game_config=game_config,
                         **get_theme_context())

# ======== SHARING FUNCTIONALITY ========

@bp.route('/share', methods=['POST'])
@analytics_required
def create_share():
    """Create a shareable link for the current graph configuration"""
    try:
        # Get form data
        title = request.form.get('share_title', '').strip()
        description = request.form.get('share_description', '').strip()
        expires_in_days = request.form.get('expires_in_days', type=int)
        
        # Get current graph configuration from form
        team_numbers = request.form.getlist('teams', type=int)
        event_id = request.form.get('event_id', type=int) or None
        metric = request.form.get('metric', 'points')
        graph_types = request.form.getlist('graph_types')
        data_view = request.form.get('data_view', 'averages')
        
        # Validation
        if not title:
            flash('Please provide a title for your shared graph.', 'error')
            return redirect(url_for('graphs.index'))
        
        if not team_numbers:
            flash('Please select at least one team to share.', 'error')
            return redirect(url_for('graphs.index'))
        
        if not graph_types:
            graph_types = ['bar', 'line', 'scatter']  # Default graph types
        
        # Create the shared graph
        shared_graph = SharedGraph.create_share(
            title=title,
            team_numbers=team_numbers,
            event_id=event_id,
            metric=metric,
            graph_types=graph_types,
            data_view=data_view,
            created_by_team=current_user.scouting_team_number,
            created_by_user=current_user.username,
            description=description,
            expires_in_days=expires_in_days
        )
        
        # Generate the share URL using client's origin if available
        from urllib.parse import urlparse
        origin = request.headers.get('Origin') or request.headers.get('Referer')
        if origin:
            parsed = urlparse(origin)
            base = f"{parsed.scheme}://{parsed.netloc}"
        else:
            base = request.url_root.rstrip('/')

        share_path = url_for('graphs.view_shared', share_id=shared_graph.share_id)
        share_url = base.rstrip('/') + share_path
        
        flash(f'Graph shared successfully! Share URL: {share_url}', 'success')
        return redirect(url_for('graphs.index'))
        
    except Exception as e:
        current_app.logger.error(f"Error creating shared graph: {str(e)}")
        flash('An error occurred while creating the shared graph. Please try again.', 'error')
        return redirect(url_for('graphs.index'))

@bp.route('/shared/<share_id>')
def view_shared(share_id):
    """View a shared graph (no authentication required)"""
    # Get the shared graph configuration
    shared_graph = SharedGraph.get_by_share_id(share_id)
    
    if not shared_graph:
        abort(404, description="Shared graph not found or has been removed.")
    
    if shared_graph.is_expired():
        abort(410, description="This shared graph has expired.")
    
    # Increment view count
    shared_graph.increment_view_count()
    
    # Get game configuration (use a default/public configuration)
    game_config = get_effective_game_config()
    
    # Allow overriding teams and graph types via query parameters so viewers
    # can interactively filter the shared view. Accepts either multiple
    # occurrences (e.g. ?teams=123&teams=456) or a comma-separated string
    # (e.g. ?teams=123,456).
    def _parse_int_list(arg_name):
        vals = request.args.getlist(arg_name)
        if len(vals) == 1 and vals[0] and ',' in vals[0]:
            vals = [v.strip() for v in vals[0].split(',') if v.strip()]
        # Filter out empty and non-numeric values
        out = []
        for v in vals:
            try:
                out.append(int(v))
            except Exception:
                continue
        return out

    def _parse_str_list(arg_name):
        vals = request.args.getlist(arg_name)
        if len(vals) == 1 and vals[0] and ',' in vals[0]:
            vals = [v.strip() for v in vals[0].split(',') if v.strip()]
        return [v for v in vals if v]

    # Whitelist of allowed graph types (keeps backend safe)
    available_graph_types = [
        'bar','line','scatter','histogram','violin','box','sunburst','treemap',
        'waterfall','sankey','heatmap','bubble','area','radar'
    ]

    # Parse overrides from query params
    query_team_numbers = _parse_int_list('teams')
    query_graph_types = _parse_str_list('graph_types')

    # Decide which teams and graph types to use for rendering
    team_numbers = query_team_numbers if query_team_numbers else shared_graph.team_numbers_list
    # Respect only whitelisted graph types; fall back to stored types if none provided
    selected_graph_types = [g for g in query_graph_types if g in available_graph_types] if query_graph_types else shared_graph.graph_types_list

    # Debug logging to help diagnose cases where selections are not applied
    try:
        current_app.logger.debug(f"Shared view override - query_graph_types={query_graph_types}, selected_graph_types={selected_graph_types}")
    except Exception:
        # Swallow logging errors to avoid breaking view
        pass

    teams = Team.query.filter(Team.team_number.in_(team_numbers)).all()
    
    if not teams:
        abort(404, description="No teams found for this shared graph.")
    
    # Generate graphs using the same logic as the main index route
    # but without user-specific filtering
    plots = {}
    
    # Get scouting data for selected teams (without team isolation)
    if shared_graph.event_id:
        # Get matches from selected event
        matches = Match.query.filter_by(event_id=shared_graph.event_id).all()
        match_ids = [match.id for match in matches]
        
        # Filter scouting data for these matches and teams
        team_ids = [team.id for team in teams]
        scouting_data = ScoutingData.query.filter(
            ScoutingData.team_id.in_(team_ids),
            ScoutingData.match_id.in_(match_ids)
        ).all()
    else:
        # Get all scouting data for selected teams
        team_ids = [team.id for team in teams]
        scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids)).all()
    
    # Process the data and create graphs
    if teams and scouting_data:
        # Create team performance graphs using the selected metric and graph types
        # Deduplicate team rows and prepare team_data
        unique_map = {}
        for t in teams:
            if t.team_number not in unique_map:
                unique_map[t.team_number] = t
        teams = sorted(unique_map.values(), key=lambda x: x.team_number) if teams else []
        team_data = {}
        
        # Calculate metrics for each team's matches
        for data in scouting_data:
            team = data.team
            match = data.match
            if team.team_number not in team_data:
                team_data[team.team_number] = {
                    'team_name': team.team_name, 
                    'matches': []
                }
            
            # Calculate the selected metric for this match
            # Handle default 'points' metric which should map to total points
            if shared_graph.metric == 'points' or shared_graph.metric == '':
                metric_value = data.calculate_metric('tot')  # Use 'tot' for total points
            else:
                metric_value = data.calculate_metric(shared_graph.metric)
            
            team_data[team.team_number]['matches'].append({
                'match_number': match.match_number,
                'match_type': match.match_type,
                'metric_value': metric_value,
                'timestamp': match.timestamp
            })
        
        # Generate the requested graph types
    # Use the selected/overridden list of graph types for rendering
    for graph_type in selected_graph_types:
            if graph_type == 'bar':
                plots.update(_create_bar_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'line':
                plots.update(_create_line_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'scatter':
                plots.update(_create_scatter_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'histogram':
                plots.update(_create_histogram_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'violin':
                plots.update(_create_violin_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'box':
                plots.update(_create_box_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'sunburst':
                plots.update(_create_sunburst_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'treemap':
                plots.update(_create_treemap_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'waterfall':
                plots.update(_create_waterfall_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'sankey':
                plots.update(_create_sankey_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'heatmap':
                plots.update(_create_heatmap_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'bubble':
                plots.update(_create_bubble_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'area':
                plots.update(_create_area_chart(team_data, shared_graph.metric, shared_graph.data_view))
            elif graph_type == 'radar':
                plots.update(_create_radar_chart(team_data, shared_graph.metric, shared_graph.data_view))
    
    # Provide the same selection UI context as the main graphs index so
    # viewers can make selections just like regular graphs.
    try:
        all_teams = Team.query.order_by(Team.team_number).all()
    except Exception:
        all_teams = []

    try:
        all_events = Event.query.order_by(Event.id).all()
    except Exception:
        all_events = []

    team_event_mapping = {}
    for t in all_teams:
        try:
            team_event_mapping[t.team_number] = [e.id for e in t.events]
        except Exception:
            team_event_mapping[t.team_number] = []

    all_teams_data = []
    for t in all_teams:
        all_teams_data.append({
            'teamNumber': t.team_number,
            'teamName': t.team_name or 'Unknown',
            'displayText': f"{t.team_number} - {t.team_name or 'Unknown'}",
            'points': 0
        })
    all_teams_json = json.dumps(all_teams_data)

    # Selected values for the UI controls: prefer query params, fall back to share settings
    selected_team_numbers = team_numbers
    selected_event_id = request.args.get('event_id', type=int) or shared_graph.event_id
    selected_metric = request.args.get('metric') or (shared_graph.metric or 'points')
    selected_data_view = request.args.get('data_view') or (shared_graph.data_view or 'averages')
    selected_sort = request.args.get('sort', 'points_desc')

    return render_template('graphs/shared.html',
                         shared_graph=shared_graph,
                         plots=plots,
                         teams=teams,
                         game_config=game_config,
                         available_graph_types=available_graph_types,
                         all_teams=all_teams,
                         all_events=all_events,
                         team_event_mapping=team_event_mapping,
                         all_teams_json=all_teams_json,
                         selected_team_numbers=selected_team_numbers,
                         selected_event_id=selected_event_id,
                         selected_metric=selected_metric,
                         selected_graph_types=selected_graph_types,
                         selected_data_view=selected_data_view,
                         selected_sort=selected_sort,
                         **get_theme_context())

@bp.route('/my-shares')
@analytics_required
def my_shares():
    """View user's created shared graphs"""
    shares = SharedGraph.get_user_shares(current_user.scouting_team_number, current_user.username)
    # Load strategy shares from instance file (if any)
    strategy_shares = []
    try:
        shares_file = os.path.join(current_app.instance_path, 'strategy_shares.json')
        if os.path.exists(shares_file):
            import json
            with open(shares_file, 'r') as f:
                all_shares = json.load(f) or {}
                # Filter shares created by this team or user if desired; currently include all
                # Determine base URL from request headers if possible
                from urllib.parse import urlparse
                origin = request.headers.get('Origin') or request.headers.get('Referer')
                if origin:
                    parsed = urlparse(origin)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                else:
                    base = request.url_root.rstrip('/')

                for token, entry in all_shares.items():
                    if not entry.get('revoked'):
                        public_path = url_for('matches.public_strategy_view', token=token)
                        # Return path; client will prepend its origin
                        strategy_shares.append({
                            'token': token,
                            'match_id': entry.get('match_id'),
                            'created_by': entry.get('created_by'),
                            'created_at': entry.get('created_at'),
                            'path': public_path
                        })
    except Exception:
        strategy_shares = []

    return render_template('graphs/my_shares.html',
                         shares=shares,
                         strategy_shares=strategy_shares,
                         **get_theme_context())


# ======== CUSTOM PAGES ========


@bp.route('/pages')
@analytics_required
def pages_index():
    """List custom pages created by this user's team/user"""
    pages = CustomPage.query.filter_by(owner_team=current_user.scouting_team_number, is_active=True).order_by(CustomPage.updated_at.desc()).all()
    return render_template('graphs/pages_index.html', pages=pages, **get_theme_context())


@bp.route('/pages/share', methods=['POST'])
@analytics_required
def create_page_share():
    """Create a public share token for a custom page. Expects JSON: {"page_id": <int>, "expires_in": <seconds, optional>}"""
    data = request.get_json() or {}
    page_id = data.get('page_id')
    if not page_id:
        return jsonify({'error': 'page_id required'}), 400

    page = CustomPage.query.get(page_id)
    if not page:
        return jsonify({'error': 'page not found'}), 404

    # Only owner may create a public share for now
    if page.owner_team != current_user.scouting_team_number or page.owner_user != current_user.username:
        return jsonify({'error': 'insufficient permissions'}), 403

    token = secrets.token_urlsafe(24)
    shares_file = os.path.join(current_app.instance_path, 'pages_shares.json')
    os.makedirs(current_app.instance_path, exist_ok=True)
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
        else:
            shares = {}
    except Exception:
        shares = {}

    entry = {
        'page_id': int(page_id),
        'created_by': current_user.id if current_user.is_authenticated else None,
        'created_by_user': current_user.username if current_user.is_authenticated else None,
        'owner_team': current_user.scouting_team_number,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'revoked': False
    }

    shares[token] = entry

    # Atomic write
    tmp = shares_file + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(shares, f)
    os.replace(tmp, shares_file)

    # Compute public path (relative) and return it
    public_path = url_for('graphs.public_page_view', token=token)
    return jsonify({'path': public_path, 'token': token})


@bp.route('/pages/public/<token>')
def public_page_view(token):
    """Public view for a shared custom page identified by token. Renders a simple preview and a download link."""
    shares_file = os.path.join(current_app.instance_path, 'pages_shares.json')
    entry = None
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
                e = shares.get(token)
                if e and not e.get('revoked'):
                    entry = e
    except Exception:
        entry = None

    if not entry:
        flash('Shared page not found or access revoked.', 'danger')
        return redirect(url_for('graphs.pages_index'))

    page = CustomPage.query.get(entry.get('page_id'))
    if not page:
        flash('Shared page not available.', 'danger')
        return redirect(url_for('graphs.pages_index'))

    # Build the full page context but use the owning team number for data
    plots, metrics, scoring_elements, teams, events, matches = _build_page_context(page, page.owner_team or current_user.scouting_team_number)

    # Render the same view template so public shares look identical to authenticated view
    return render_template('graphs/pages_view.html', page=page, plots=plots, metrics=metrics, scoring_elements=scoring_elements, teams=teams, events=events, matches=matches, public_share_token=token, **get_theme_context())


@bp.route('/pages/public/<token>/download')
def public_page_download(token):
    """Return the raw page JSON for a valid share token."""
    shares_file = os.path.join(current_app.instance_path, 'pages_shares.json')
    entry = None
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
                e = shares.get(token)
                if e and not e.get('revoked'):
                    entry = e
    except Exception:
        entry = None

    if not entry:
        return jsonify({'error': 'invalid or revoked token'}), 404

    page = CustomPage.query.get(entry.get('page_id'))
    if not page:
        return jsonify({'error': 'page not found'}), 404

    # Provide sanitized widgets in the public download as well
    try:
        widgets = page.widgets()
    except Exception:
        widgets = []

    payload = {
        'title': page.title,
        'widgets': widgets
    }
    return jsonify(payload)


@bp.route('/pages/public/<token>/render_widget/<int:widget_index>', methods=['POST'])
def public_page_widget_render(token, widget_index):
        """Render a single widget for a public shared page identified by token.

        This mirrors pages_widget_render but validates the share token and uses
        the owning team's scouting_team_number for any data isolation.
        Returns the same JSON structure as pages_widget_render.
        """
        # Validate token
        shares_file = os.path.join(current_app.instance_path, 'pages_shares.json')
        entry = None
        try:
                if os.path.exists(shares_file):
                        with open(shares_file, 'r') as f:
                                shares = json.load(f) or {}
                                e = shares.get(token)
                                if e and not e.get('revoked'):
                                        entry = e
        except Exception:
                entry = None

        if not entry:
                return jsonify({'error': 'invalid or revoked token'}), 404

        page = CustomPage.query.get(entry.get('page_id'))
        if not page:
                return jsonify({'error': 'page not found'}), 404

        from flask import render_template_string
        from app.utils.analysis import predict_match_outcome, get_match_details_with_teams, calculate_team_metrics

        try:
                widgets = page.widgets()
        except Exception:
                widgets = []

        if widget_index < 0 or widget_index >= len(widgets):
                return jsonify({'error': 'Invalid widget index'}), 400

        widget = dict(widgets[widget_index])
        overrides = request.get_json() or {}
        for k, v in overrides.items():
                widget[k] = v

        # Normalize graph_types override
        try:
                raw_gt = widget.get('graph_types', ['bar', 'line'])
                if isinstance(raw_gt, str):
                        raw_gt = [raw_gt]
                graph_types = [str(x).lower() for x in (raw_gt or []) if x is not None]
                if not graph_types:
                        graph_types = ['bar', 'line']
                widget['graph_types'] = graph_types
        except Exception:
                widget['graph_types'] = widget.get('graph_types', ['bar', 'line'])

        # Use owner's scouting team number for data isolation
        scouting_team_number = entry.get('owner_team')

        wtype = widget.get('type')
        widget_plots = {}

        if wtype == 'graph':
                selected_teams = widget.get('teams', [])
                if isinstance(selected_teams, list):
                        selected_teams = [s for s in selected_teams]
                metric = widget.get('metric', 'points')
                metric_alias = 'tot' if metric in ('total_points', 'points', 'tot') else metric
                graph_types = widget.get('graph_types', ['bar', 'line'])
                data_view = widget.get('data_view', 'averages')

                if selected_teams and not (len(selected_teams) == 1 and str(selected_teams[0]) == 'all'):
                        team_ids = []
                        for s in selected_teams:
                                if s == 'all':
                                        team_ids = []
                                        break
                                try:
                                        team_ids.append(int(s))
                                except Exception:
                                        pass
                        if team_ids:
                                teams = Team.query.filter(Team.id.in_(team_ids)).all()
                                found_ids = {t.id for t in teams}
                                missing = [tid for tid in team_ids if tid not in found_ids]
                                if missing:
                                        more_by_number = Team.query.filter(Team.team_number.in_(missing)).all()
                                        if more_by_number:
                                                teams.extend(more_by_number)
                        else:
                                teams = Team.query.order_by(Team.team_number).all()
                else:
                        teams = Team.query.order_by(Team.team_number).all()

                team_data = {}
                if teams:
                        team_ids = [t.id for t in teams]
                        for t in teams:
                                if t.team_number not in team_data:
                                        team_data[t.team_number] = {'team_name': t.team_name, 'matches': []}

                        scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids), ScoutingData.scouting_team_number==scouting_team_number).all()
                        for data in scouting_data:
                                team = data.team
                                match = data.match
                                if team.team_number not in team_data:
                                        team_data[team.team_number] = {'team_name': team.team_name, 'matches': []}
                                if metric_alias == 'tot':
                                        metric_value = data.calculate_metric('tot')
                                else:
                                        metric_value = data.calculate_metric(metric_alias)
                                team_data[team.team_number]['matches'].append({'match_number': match.match_number if match else None, 'metric_value': metric_value, 'timestamp': match.timestamp if match else None})

                for gt in graph_types:
                        if gt == 'bar':
                                widget_plots.update(_create_bar_chart(team_data, metric, data_view))
                        elif gt == 'line':
                                widget_plots.update(_create_line_chart(team_data, metric, data_view))
                        elif gt == 'scatter':
                                widget_plots.update(_create_scatter_chart(team_data, metric, data_view))
                        elif gt == 'histogram':
                                widget_plots.update(_create_histogram_chart(team_data, metric, data_view))
                        elif gt == 'violin':
                                widget_plots.update(_create_violin_chart(team_data, metric, data_view))
                        elif gt == 'box':
                                widget_plots.update(_create_box_chart(team_data, metric, data_view))
                        elif gt == 'sunburst':
                                widget_plots.update(_create_sunburst_chart(team_data, metric, data_view))
                        elif gt == 'treemap':
                                widget_plots.update(_create_treemap_chart(team_data, metric, data_view))
                        elif gt == 'waterfall':
                                widget_plots.update(_create_waterfall_chart(team_data, metric, data_view))
                        elif gt == 'sankey':
                                widget_plots.update(_create_sankey_chart(team_data, metric, data_view))
                        elif gt == 'heatmap':
                                widget_plots.update(_create_heatmap_chart(team_data, metric, data_view))
                        elif gt == 'bubble':
                                widget_plots.update(_create_bubble_chart(team_data, metric, data_view))
                        elif gt == 'area':
                                widget_plots.update(_create_area_chart(team_data, metric, data_view))
                        elif gt == 'radar':
                                widget_plots.update(_create_radar_chart(team_data, metric, data_view))

        elif wtype == 'match_prediction':
                match_id = overrides.get('prediction_match')
                prediction_data = None
                if match_id:
                        try:
                                match_details = get_match_details_with_teams(int(match_id))
                                if match_details and match_details.get('prediction'):
                                        prediction = match_details['prediction']
                                        prediction_data = {
                                                'red_alliance': prediction.get('red_alliance', {}),
                                                'blue_alliance': prediction.get('blue_alliance', {}),
                                                'predicted_winner': prediction.get('predicted_winner', 'unknown'),
                                                'probabilities': prediction.get('probabilities', {'red': 0, 'blue': 0, 'tie': 0}),
                                                'confidence': prediction.get('confidence', 0),
                                                'match': match_details.get('match'),
                                                'match_completed': match_details.get('match_completed', False),
                                                'actual_winner': match_details.get('actual_winner')
                                        }
                        except Exception:
                                prediction_data = None
                prediction_style = widget.get('prediction_style', 'default')
                html_template = '''
                <div class="match-prediction-widget">
                {% if prediction_data %}
                    <div class="alert alert-info">
                        <h5><i class="fas fa-trophy me-2"></i>Match Prediction</h5>
                        <div class="prediction-display">
                            {% if prediction_style == 'compact' %}
                                <p class="mb-0"><strong>Predicted Winner:</strong> <span class="badge bg-{{ 'danger' if prediction_data['predicted_winner'] == 'red' else 'primary' if prediction_data['predicted_winner'] == 'blue' else 'secondary' }}">{{ prediction_data['predicted_winner']|upper }}</span></p>
                            {% elif prediction_style == 'detailed' %}
                                <div class="row">
                                    <div class="col-md-6">
                                        <h6>Red Alliance</h6>
                                        <p>Win Probability: {{ (prediction_data['probabilities']['red'] * 100)|round(1) }}%</p>
                                        <p>Predicted Score: {{ prediction_data['red_alliance']['predicted_score'] }}</p>
                                    </div>
                                    <div class="col-md-6">
                                        <h6>Blue Alliance</h6>
                                        <p>Win Probability: {{ (prediction_data['probabilities']['blue'] * 100)|round(1) }}%</p>
                                        <p>Predicted Score: {{ prediction_data['blue_alliance']['predicted_score'] }}</p>
                                    </div>
                                </div>
                            {% else %}
                                <div class="text-center">
                                    <h6>Win Probability</h6>
                                    <div class="progress mb-2" style="height: 30px;">
                                        <div class="progress-bar bg-danger" style="width: {{ prediction_data['probabilities']['red'] * 100 }}%">Red {{ (prediction_data['probabilities']['red'] * 100)|round(1) }}%</div>
                                        <div class="progress-bar bg-primary" style="width: {{ prediction_data['probabilities']['blue'] * 100 }}%">Blue {{ (prediction_data['probabilities']['blue'] * 100)|round(1) }}%</div>
                                    </div>
                                    <p class="mb-0">Predicted: Red {{ prediction_data['red_alliance']['predicted_score'] }} - {{ prediction_data['blue_alliance']['predicted_score'] }} Blue</p>
                                </div>
                            {% endif %}
                        </div>
                    </div>
                {% else %}
                    <div class="alert alert-warning">
                        <i class="fas fa-info-circle me-2"></i>Select a match to view prediction
                    </div>
                {% endif %}
                </div>
                '''
                html = render_template_string(html_template, prediction_data=prediction_data, prediction_style=prediction_style)
                return jsonify({'html': html})

        elif wtype == 'team_comparison':
                # reuse pages_widget_render logic for these widget types
                team1_num = overrides.get('comparison_team1')
                team2_num = overrides.get('comparison_team2')
                event_filter = overrides.get('comparison_event', 'all')
                metrics_list = widget.get('metrics', []) or widget.get('comparison_metrics', [])
                if not metrics_list:
                        metrics_list = ['total_points', 'auto_points', 'teleop_points', 'endgame_points']
                comparison_data = None
                if team1_num and team2_num:
                        try:
                                team1 = Team.query.filter_by(team_number=int(team1_num)).first()
                                team2 = Team.query.filter_by(team_number=int(team2_num)).first()
                                if team1 and team2:
                                        event_id = None
                                        if event_filter and event_filter != 'all':
                                                try:
                                                        event_id = int(event_filter)
                                                except ValueError:
                                                        pass
                                        team1_analytics = calculate_team_metrics(team1.id, event_id=event_id)
                                        team2_analytics = calculate_team_metrics(team2.id, event_id=event_id)
                                        comparison_data = {
                                                'team1': {
                                                        'team_number': team1.team_number,
                                                        'team_name': team1.team_name or f'Team {team1.team_number}',
                                                        'metrics': team1_analytics.get('metrics', {})
                                                },
                                                'team2': {
                                                        'team_number': team2.team_number,
                                                        'team_name': team2.team_name or f'Team {team2.team_number}',
                                                        'metrics': team2_analytics.get('metrics', {})
                                                },
                                                'selected_metrics': metrics_list
                                        }
                        except Exception:
                                pass
                html_template = '''
                {% if comparison_data %}
                    <div class="row mb-3">
                        <div class="col-md-6">
                            <div class="card bg-danger text-white">
                                <div class="card-body text-center">
                                    <h5>{{ comparison_data.team1.team_name }}</h5>
                                    <small>#{{ comparison_data.team1.team_number }}</small>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="card bg-primary text-white">
                                <div class="card-body text-center">
                                    <h5>{{ comparison_data.team2.team_name }}</h5>
                                    <small>#{{ comparison_data.team2.team_number }}</small>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-striped table-sm">
                            <thead>
                                <tr>
                                    <th>Metric</th>
                                    <th class="text-center">{{ comparison_data.team1.team_name }}</th>
                                    <th class="text-center">{{ comparison_data.team2.team_name }}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for metric_id in comparison_data.selected_metrics %}
                                <tr>
                                    <td>{{ metric_id|replace('_', ' ')|title }}</td>
                                    <td class="text-center">{% set val = comparison_data.team1.metrics.get(metric_id) %}{{ val|round(2) if val is number else (val if val else 'N/A') }}</td>
                                    <td class="text-center">{% set val = comparison_data.team2.metrics.get(metric_id) %}{{ val|round(2) if val is number else (val if val else 'N/A') }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                {% else %}
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>Enter team numbers to compare statistics
                    </div>
                {% endif %}
                '''
                html = render_template_string(html_template, comparison_data=comparison_data)
                return jsonify({'html': html})

        elif wtype == 'team_rankings':
                event_filter = overrides.get('rankings_event', 'all')
                count = int(widget.get('count', 10) or widget.get('rankings_count', 10))
                sort_by = widget.get('sort_by', 'points') or widget.get('rankings_sort', 'points')
                show_stats = widget.get('show_stats', False) or widget.get('rankings_show_stats', False)
                rankings_data = None
                try:
                        event_id = None
                        if event_filter and event_filter != 'all':
                                try:
                                        event_id = int(event_filter)
                                except ValueError:
                                        pass
                        teams_query = Team.query.order_by(Team.team_number).all()
                        team_rankings = []
                        for team in teams_query:
                                analytics_result = calculate_team_metrics(team.id, event_id=event_id)
                                metrics = analytics_result.get('metrics', {})
                                if sort_by == 'points' or sort_by == 'score':
                                        sort_value = metrics.get('total_points') or metrics.get('tot') or 0
                                elif sort_by == 'wins':
                                        sort_value = metrics.get('wins') or 0
                                elif sort_by == 'RP':
                                        sort_value = metrics.get('ranking_points') or 0
                                else:
                                        sort_value = metrics.get(sort_by) or 0
                                team_rankings.append({'team_number': team.team_number, 'team_name': team.team_name or f'Team {team.team_number}', 'sort_value': sort_value, 'metrics': metrics if show_stats else {}})
                        team_rankings.sort(key=lambda x: x['sort_value'], reverse=True)
                        team_rankings = team_rankings[:count]
                        for idx, ranking in enumerate(team_rankings):
                                ranking['rank'] = idx + 1
                        rankings_data = {'rankings': team_rankings, 'sort_by': sort_by, 'show_stats': show_stats, 'event_filter': event_filter if event_id else 'all'}
                except Exception:
                        rankings_data = None
                html_template = '''
                {% if rankings_data %}
                    <h5 class="mb-3"><i class="fas fa-list-ol me-2"></i>Team Rankings{% if rankings_data.event_filter != 'all' %} (Event){% endif %} ({{ rankings_data.sort_by|title }})</h5>
                    <div class="table-responsive">
                        <table class="table table-hover table-sm">
                            <thead class="table-light">
                                <tr>
                                    <th>Rank</th>
                                    <th>Team</th>
                                    <th class="text-end">{{ rankings_data.sort_by|replace('_', ' ')|title }}</th>
                                    {% if rankings_data.show_stats %}
                                    <th class="text-end">Avg Points</th>
                                    {% endif %}
                                </tr>
                            </thead>
                            <tbody>
                                {% for team in rankings_data.rankings %}
                                <tr>
                                    <td><span class="badge bg-{{ 'warning' if team.rank <= 3 else 'secondary' }}">{{ team.rank }}</span></td>
                                    <td><strong>{{ team.team_number }}</strong> - {{ team.team_name }}</td>
                                    <td class="text-end">{{ team.sort_value|round(2) }}</td>
                                    {% if rankings_data.show_stats %}
                                    <td class="text-end">{{ team.metrics.get('total_points', team.metrics.get('tot', 'N/A')) }}</td>
                                    {% endif %}
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                {% else %}
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>No ranking data available
                    </div>
                {% endif %}
                '''
                html = render_template_string(html_template, rankings_data=rankings_data)
                return jsonify({'html': html})

        elif wtype == 'recent_matches':
                event_filter = overrides.get('matches_event')
                filter_type = widget.get('filter', 'all')
                count = int(widget.get('count', 10) or widget.get('matches_count', 10))
                show_scores = widget.get('show_scores', True) if widget.get('show_scores') is not None else widget.get('matches_show_scores', True)
                matches_data = None
                try:
                        matches_query = Match.query
                        if event_filter:
                                try:
                                        event_id = int(event_filter)
                                        matches_query = matches_query.filter_by(event_id=event_id)
                                except ValueError:
                                        pass
                        matches_query = matches_query.order_by(Match.timestamp.desc()).limit(count)
                        matches = matches_query.all()
                        matches_list = []
                        for match in matches:
                                match_data = {'match_id': match.id, 'match_type': match.match_type, 'match_number': match.match_number, 'red_alliance': match.red_alliance, 'blue_alliance': match.blue_alliance, 'timestamp': match.timestamp}
                                if show_scores and match.red_score is not None and match.blue_score is not None:
                                        match_data['red_score'] = match.red_score
                                        match_data['blue_score'] = match.blue_score
                                        match_data['winner'] = 'red' if match.red_score > match.blue_score else 'blue' if match.blue_score > match.red_score else 'tie'
                                matches_list.append(match_data)
                        matches_data = {'matches': matches_list, 'show_scores': show_scores}
                except Exception:
                        matches_data = None
                html_template = '''
                {% if matches_data %}
                    <h5 class="mb-3"><i class="fas fa-history me-2"></i>Recent Matches</h5>
                    <div class="list-group">
                        {% for match in matches_data.matches %}
                        <div class="list-group-item">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <strong>{{ match.match_type }} {{ match.match_number }}</strong>
                                    {% if match.timestamp %}
                                    <small class="text-muted ms-2">{{ match.timestamp.strftime('%m/%d %H:%M') }}</small>
                                    {% endif %}
                                </div>
                                {% if matches_data.show_scores and match.get('red_score') is not none %}
                                <div>
                                    <span class="badge bg-{{ 'danger' if match.get('winner') == 'red' else 'secondary' }}">Red: {{ match.red_score }}</span>
                                    <span class="badge bg-{{ 'primary' if match.get('winner') == 'blue' else 'secondary' }} ms-1">Blue: {{ match.blue_score }}</span>
                                </div>
                                {% endif %}
                            </div>
                            <div class="mt-1">
                                <small class="text-danger">Red: {{ match.red_alliance }}</small>
                                <small class="text-primary ms-3">Blue: {{ match.blue_alliance }}</small>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                {% else %}
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>No match data available
                    </div>
                {% endif %}
                '''
                html = render_template_string(html_template, matches_data=matches_data)
                return jsonify({'html': html})

        return jsonify({'plots': widget_plots})


@bp.route('/pages/shares')
@analytics_required
def pages_shares():
    """List public shares created by this team and allow revocation."""
    shares_file = os.path.join(current_app.instance_path, 'pages_shares.json')
    shares_list = []
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
                for token, entry in shares.items():
                    # Only include shares for this team
                    try:
                        if int(entry.get('owner_team')) == int(current_user.scouting_team_number):
                            shares_list.append({'token': token, **entry})
                    except Exception:
                        continue
    except Exception:
        shares_list = []

    # Enrich with page title if possible
    for s in shares_list:
        try:
            p = CustomPage.query.get(s.get('page_id'))
            s['page_title'] = p.title if p else 'Deleted'
        except Exception:
            s['page_title'] = 'Unknown'

    return render_template('graphs/pages_shares.html', shares=shares_list, **get_theme_context())


@bp.route('/pages/shares/<token>/revoke', methods=['POST'])
@analytics_required
def revoke_page_share(token):
    shares_file = os.path.join(current_app.instance_path, 'pages_shares.json')
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
        else:
            shares = {}
    except Exception:
        shares = {}

    entry = shares.get(token)
    if not entry:
        flash('Share not found', 'danger')
        return redirect(url_for('graphs.pages_shares'))

    # Only owner team may revoke
    try:
        if int(entry.get('owner_team')) != int(current_user.scouting_team_number):
            flash('Insufficient permissions to revoke this share', 'danger')
            return redirect(url_for('graphs.pages_shares'))
    except Exception:
        flash('Insufficient permissions', 'danger')
        return redirect(url_for('graphs.pages_shares'))

    entry['revoked'] = True
    shares[token] = entry
    tmp = shares_file + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(shares, f)
    os.replace(tmp, shares_file)

    flash('Share revoked', 'success')
    return redirect(url_for('graphs.pages_shares'))


@bp.route('/pages/create', methods=['GET', 'POST'])
@analytics_required
def pages_create():
    """Create a new custom page. Simple form-based creation where widgets are submitted as JSON."""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        widgets_raw = request.form.get('widgets_json', '').strip()
        if not title:
            flash('Please provide a title for your custom page.', 'error')
            return redirect(url_for('graphs.pages_create'))
        try:
            widgets_obj = json.loads(widgets_raw) if widgets_raw else []
        except Exception as e:
            current_app.logger.error(f'Failed to parse widgets JSON for custom page: {e}')
            flash(f'Widgets JSON is invalid: {str(e)}', 'error')
            return redirect(url_for('graphs.pages_create'))

        page = CustomPage(title=title, owner_team=current_user.scouting_team_number, owner_user=current_user.username, widgets_json=json.dumps(widgets_obj))
        db.session.add(page)
        db.session.commit()
        flash('Custom page created.', 'success')
        return redirect(url_for('graphs.pages_index'))

    # Prepare a minimal game_config-driven widget palette for the form
    game_config = get_effective_game_config()
    # Collect metrics and scoring elements
    metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
    # Ensure a 'total_points' metric exists so widgets can select it even if not in game_config
    try:
        if isinstance(metrics, list):
            if not any(m.get('id') == 'total_points' for m in metrics):
                metrics.append({'id': 'total_points', 'name': 'Total Points'})
    except Exception:
        metrics = metrics
    scoring_elements = []
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        for el in game_config.get(period, {}).get('scoring_elements', []):
            scoring_elements.append({'period': period, 'id': el.get('perm_id', el.get('id')), 'name': el.get('name', el.get('id'))})

    # Provide teams list for team-selection dropdown in the widget builder
    teams_q = Team.query.order_by(Team.team_number).all()
    teams = [{'id': t.team_number, 'name': t.team_name or f'Team {t.team_number}'} for t in teams_q]
    
    # Fetch events and matches for dropdown population
    events_q = Event.query.order_by(Event.name).limit(500).all()
    events = [{'id': e.id, 'name': e.name or e.code, 'code': e.code} for e in events_q]
    
    matches_q = Match.query.order_by(Match.event_id, Match.match_number).limit(1000).all()
    matches = [{'id': m.id, 'event_id': m.event_id, 'match_type': m.match_type, 'match_number': m.match_number} for m in matches_q]
    
    return render_template('graphs/pages_create.html', game_config=game_config, metrics=metrics, scoring_elements=scoring_elements, teams=teams, events=events, matches=matches, initial_widgets=None, **get_theme_context())


@bp.route('/pages/<int:page_id>/edit', methods=['GET', 'POST'])
@analytics_required
def pages_edit(page_id):
    """Edit an existing custom page. Only the creator and team may edit."""
    page = CustomPage.query.get_or_404(page_id)
    if page.owner_team != current_user.scouting_team_number or page.owner_user != current_user.username:
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        widgets_raw = request.form.get('widgets_json', '').strip()
        if not title:
            flash('Please provide a title for your custom page.', 'error')
            return redirect(url_for('graphs.pages_edit', page_id=page.id))
        try:
            widgets_obj = json.loads(widgets_raw) if widgets_raw else []
        except Exception as e:
            current_app.logger.error(f'Failed to parse widgets JSON for custom page {page.id}: {e}')
            flash(f'Widgets JSON is invalid: {str(e)}', 'error')
            return redirect(url_for('graphs.pages_edit', page_id=page.id))

        page.title = title
        page.set_widgets(widgets_obj)
        db.session.commit()
        flash('Custom page updated.', 'success')
        return redirect(url_for('graphs.pages_index'))

    # GET -> render builder with initial widgets loaded
    game_config = get_effective_game_config()
    metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
    # Ensure a 'total_points' metric exists so widgets can select it even if not in game_config
    try:
        if isinstance(metrics, list):
            if not any(m.get('id') == 'total_points' for m in metrics):
                metrics.append({'id': 'total_points', 'name': 'Total Points'})
    except Exception:
        metrics = metrics
    scoring_elements = []
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        for el in game_config.get(period, {}).get('scoring_elements', []):
            scoring_elements.append({'period': period, 'id': el.get('perm_id', el.get('id')), 'name': el.get('name', el.get('id'))})

    try:
        initial_widgets = page.widgets()
    except Exception:
        initial_widgets = []

    teams_q = Team.query.order_by(Team.team_number).all()
    teams = [{'id': t.team_number, 'name': t.team_name or f'Team {t.team_number}'} for t in teams_q]
    
    # Fetch events and matches for dropdown population
    events_q = Event.query.order_by(Event.name).limit(500).all()
    events = [{'id': e.id, 'name': e.name or e.code, 'code': e.code} for e in events_q]
    
    matches_q = Match.query.order_by(Match.event_id, Match.match_number).limit(1000).all()
    matches = [{'id': m.id, 'event_id': m.event_id, 'match_type': m.match_type, 'match_number': m.match_number} for m in matches_q]

    return render_template('graphs/pages_create.html', game_config=game_config, metrics=metrics, scoring_elements=scoring_elements, teams=teams, events=events, matches=matches, initial_widgets=initial_widgets, page=page, **get_theme_context())


@bp.route('/pages/<int:page_id>/render_widget/<int:widget_index>', methods=['POST'])
@analytics_required
def pages_widget_render(page_id, widget_index):
    """Render a single widget for a page with optional overrides (used by user-selectable controls).
    Expects JSON body with overrides for fields like 'metric' or 'teams'. 
    For graph widgets: Returns JSON mapping plot_key -> plot_json.
    For other widgets: Returns JSON with HTML fragment."""
    from flask import render_template_string
    from app.utils.analysis import predict_match_outcome, get_match_details_with_teams, calculate_team_metrics
    
    page = CustomPage.query.get_or_404(page_id)
    if page.owner_team != current_user.scouting_team_number:
        abort(403)

    widgets = page.widgets()
    if widget_index < 0 or widget_index >= len(widgets):
        return jsonify({'error': 'Invalid widget index'}), 400

    widget = dict(widgets[widget_index])
    overrides = request.get_json() or {}
    # apply overrides shallowly
    for k, v in overrides.items():
        widget[k] = v

    # Normalize graph_types override: ensure it's a non-empty list of lowercase strings
    try:
        raw_gt = widget.get('graph_types', ['bar', 'line'])
        if isinstance(raw_gt, str):
            raw_gt = [raw_gt]
        graph_types = [str(x).lower() for x in (raw_gt or []) if x is not None]
        if not graph_types:
            graph_types = ['bar', 'line']
        widget['graph_types'] = graph_types
    except Exception:
        widget['graph_types'] = widget.get('graph_types', ['bar', 'line'])

    # helpful debug logging when rendering widgets dynamically
    try:
        current_app.logger.debug('pages_widget_render: overrides=%s, resolved_graph_types=%s, metric=%s, type=%s', overrides, widget.get('graph_types'), widget.get('metric'), widget.get('type'))
    except Exception:
        pass

    # Reuse the same plot creation logic as pages_view for a single widget
    wtype = widget.get('type')
    widget_plots = {}

    if wtype == 'graph':
        selected_teams = widget.get('teams', [])
        # normalize strings/numeric values (clients may send strings for 'all' or numeric ids)
        if isinstance(selected_teams, list):
            selected_teams = [s for s in selected_teams]
        metric = widget.get('metric', 'points')
        # allow alias 'total_points' to map to backend 'tot' calculation
        metric_alias = 'tot' if metric in ('total_points', 'points', 'tot') else metric
        graph_types = widget.get('graph_types', ['bar', 'line'])
        data_view = widget.get('data_view', 'averages')
        # Interpret ['all'] or empty selection as all teams
        # If explicit teams were selected and not the 'all' sentinel, interpret them as team ids or numbers
        if selected_teams and not (len(selected_teams) == 1 and str(selected_teams[0]) == 'all'):
            # coerce values to ints where possible (these may be Team.id or team_number values coming from the client)
            team_ids = []
            for s in selected_teams:
                if s == 'all':
                    team_ids = []
                    break
                try:
                    team_ids.append(int(s))
                except Exception:
                    pass
            if team_ids:
                # First try to find teams by database id
                teams = Team.query.filter(Team.id.in_(team_ids)).all()
                found_ids = {t.id for t in teams}
                # For any values not found as ids, try matching by team_number
                missing = [tid for tid in team_ids if tid not in found_ids]
                if missing:
                    more_by_number = Team.query.filter(Team.team_number.in_(missing)).all()
                    if more_by_number:
                        teams.extend(more_by_number)
            else:
                teams = Team.query.order_by(Team.team_number).all()
        else:
            teams = Team.query.order_by(Team.team_number).all()
        team_data = {}
        if teams:
            team_ids = [t.id for t in teams]
            # Initialize team_data entries for all selected teams so teams with no scouting rows are still represented
            for t in teams:
                if t.team_number not in team_data:
                    team_data[t.team_number] = {'team_name': t.team_name, 'matches': []}

            scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids), ScoutingData.scouting_team_number==current_user.scouting_team_number).all()
            for data in scouting_data:
                team = data.team
                match = data.match
                if team.team_number not in team_data:
                    team_data[team.team_number] = {'team_name': team.team_name, 'matches': []}
                if metric_alias == 'tot':
                    metric_value = data.calculate_metric('tot')
                else:
                    metric_value = data.calculate_metric(metric_alias)
                team_data[team.team_number]['matches'].append({'match_number': match.match_number if match else None, 'metric_value': metric_value, 'timestamp': match.timestamp if match else None})

        for gt in graph_types:
            if gt == 'bar':
                widget_plots.update(_create_bar_chart(team_data, metric, data_view))
            elif gt == 'line':
                widget_plots.update(_create_line_chart(team_data, metric, data_view))
            elif gt == 'scatter':
                widget_plots.update(_create_scatter_chart(team_data, metric, data_view))
            elif gt == 'histogram':
                widget_plots.update(_create_histogram_chart(team_data, metric, data_view))
            elif gt == 'violin':
                widget_plots.update(_create_violin_chart(team_data, metric, data_view))
            elif gt == 'box':
                widget_plots.update(_create_box_chart(team_data, metric, data_view))
            elif gt == 'sunburst':
                widget_plots.update(_create_sunburst_chart(team_data, metric, data_view))
            elif gt == 'treemap':
                widget_plots.update(_create_treemap_chart(team_data, metric, data_view))
            elif gt == 'waterfall':
                widget_plots.update(_create_waterfall_chart(team_data, metric, data_view))
            elif gt == 'sankey':
                widget_plots.update(_create_sankey_chart(team_data, metric, data_view))
            elif gt == 'heatmap':
                widget_plots.update(_create_heatmap_chart(team_data, metric, data_view))
            elif gt == 'bubble':
                widget_plots.update(_create_bubble_chart(team_data, metric, data_view))
            elif gt == 'area':
                widget_plots.update(_create_area_chart(team_data, metric, data_view))
            elif gt == 'radar':
                widget_plots.update(_create_radar_chart(team_data, metric, data_view))

    elif wtype == 'match_prediction':
        # Handle match prediction widget - return HTML fragment
        match_id = overrides.get('prediction_match')
        prediction_data = None
        if match_id:
            try:
                match_details = get_match_details_with_teams(int(match_id))
                if match_details and match_details.get('prediction'):
                    # Get the prediction dict which already has the proper structure
                    prediction = match_details['prediction']
                    # Build a complete prediction_data structure for the template
                    prediction_data = {
                        'red_alliance': prediction.get('red_alliance', {}),
                        'blue_alliance': prediction.get('blue_alliance', {}),
                        'predicted_winner': prediction.get('predicted_winner', 'unknown'),
                        'probabilities': prediction.get('probabilities', {'red': 0, 'blue': 0, 'tie': 0}),
                        'confidence': prediction.get('confidence', 0),
                        'match': match_details.get('match'),
                        'match_completed': match_details.get('match_completed', False),
                        'actual_winner': match_details.get('actual_winner')
                    }
            except Exception as e:
                current_app.logger.error(f"Error fetching match prediction: {e}")
                import traceback
                current_app.logger.error(traceback.format_exc())
        
        prediction_style = widget.get('prediction_style', 'default')
        html_template = '''
        <div class="match-prediction-widget">
        {% if prediction_data %}
          <div class="alert alert-info">
            <h5><i class="fas fa-trophy me-2"></i>Match Prediction</h5>
            <div class="prediction-display">
              {% if prediction_style == 'compact' %}
                <p class="mb-0"><strong>Predicted Winner:</strong> <span class="badge bg-{{ 'danger' if prediction_data['predicted_winner'] == 'red' else 'primary' if prediction_data['predicted_winner'] == 'blue' else 'secondary' }}">{{ prediction_data['predicted_winner']|upper }}</span></p>
              {% elif prediction_style == 'detailed' %}
                <div class="row">
                  <div class="col-md-6">
                    <h6>Red Alliance</h6>
                    <p>Win Probability: {{ (prediction_data['probabilities']['red'] * 100)|round(1) }}%</p>
                    <p>Predicted Score: {{ prediction_data['red_alliance']['predicted_score'] }}</p>
                  </div>
                  <div class="col-md-6">
                    <h6>Blue Alliance</h6>
                    <p>Win Probability: {{ (prediction_data['probabilities']['blue'] * 100)|round(1) }}%</p>
                    <p>Predicted Score: {{ prediction_data['blue_alliance']['predicted_score'] }}</p>
                  </div>
                </div>
              {% else %}
                <div class="text-center">
                  <h6>Win Probability</h6>
                  <div class="progress mb-2" style="height: 30px;">
                    <div class="progress-bar bg-danger" style="width: {{ prediction_data['probabilities']['red'] * 100 }}%">Red {{ (prediction_data['probabilities']['red'] * 100)|round(1) }}%</div>
                    <div class="progress-bar bg-primary" style="width: {{ prediction_data['probabilities']['blue'] * 100 }}%">Blue {{ (prediction_data['probabilities']['blue'] * 100)|round(1) }}%</div>
                  </div>
                  <p class="mb-0">Predicted: Red {{ prediction_data['red_alliance']['predicted_score'] }} - {{ prediction_data['blue_alliance']['predicted_score'] }} Blue</p>
                </div>
              {% endif %}
            </div>
          </div>
        {% else %}
          <div class="alert alert-warning">
            <i class="fas fa-info-circle me-2"></i>Select a match to view prediction
          </div>
        {% endif %}
        </div>
        '''
        html = render_template_string(html_template, prediction_data=prediction_data, prediction_style=prediction_style)
        return jsonify({'html': html})

    elif wtype == 'team_comparison':
        # Handle team comparison widget - return HTML fragment
        team1_num = overrides.get('comparison_team1')
        team2_num = overrides.get('comparison_team2')
        event_filter = overrides.get('comparison_event', 'all')
        metrics_list = widget.get('metrics', []) or widget.get('comparison_metrics', [])
        # If no metrics specified, use default ones
        if not metrics_list:
            metrics_list = ['total_points', 'auto_points', 'teleop_points', 'endgame_points']
        comparison_data = None
        
        if team1_num and team2_num:
            try:
                team1 = Team.query.filter_by(team_number=int(team1_num)).first()
                team2 = Team.query.filter_by(team_number=int(team2_num)).first()
                
                if team1 and team2:
                    # Parse event_id for filtering
                    event_id = None
                    if event_filter and event_filter != 'all':
                        try:
                            event_id = int(event_filter)
                        except ValueError:
                            pass
                    
                    team1_analytics = calculate_team_metrics(team1.id, event_id=event_id)
                    team2_analytics = calculate_team_metrics(team2.id, event_id=event_id)
                    
                    comparison_data = {
                        'team1': {
                            'team_number': team1.team_number,
                            'team_name': team1.team_name or f'Team {team1.team_number}',
                            'metrics': team1_analytics.get('metrics', {})
                        },
                        'team2': {
                            'team_number': team2.team_number,
                            'team_name': team2.team_name or f'Team {team2.team_number}',
                            'metrics': team2_analytics.get('metrics', {})
                        },
                        'selected_metrics': metrics_list
                    }
                else:
                    current_app.logger.warning(f"One or both teams not found: {team1_num}, {team2_num}")
            except Exception as e:
                current_app.logger.error(f"Error fetching team comparison: {e}")
                import traceback
                current_app.logger.error(traceback.format_exc())
        
        html_template = '''
        {% if comparison_data %}
          <div class="row mb-3">
            <div class="col-md-6">
              <div class="card bg-danger text-white">
                <div class="card-body text-center">
                  <h5>{{ comparison_data.team1.team_name }}</h5>
                  <small>#{{ comparison_data.team1.team_number }}</small>
                </div>
              </div>
            </div>
            <div class="col-md-6">
              <div class="card bg-primary text-white">
                <div class="card-body text-center">
                  <h5>{{ comparison_data.team2.team_name }}</h5>
                  <small>#{{ comparison_data.team2.team_number }}</small>
                </div>
              </div>
            </div>
          </div>
          <div class="table-responsive">
            <table class="table table-striped table-sm">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th class="text-center">{{ comparison_data.team1.team_name }}</th>
                  <th class="text-center">{{ comparison_data.team2.team_name }}</th>
                </tr>
              </thead>
              <tbody>
                {% for metric_id in comparison_data.selected_metrics %}
                <tr>
                  <td>{{ metric_id|replace('_', ' ')|title }}</td>
                  <td class="text-center">{% set val = comparison_data.team1.metrics.get(metric_id) %}{{ val|round(2) if val is number else (val if val else 'N/A') }}</td>
                  <td class="text-center">{% set val = comparison_data.team2.metrics.get(metric_id) %}{{ val|round(2) if val is number else (val if val else 'N/A') }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        {% else %}
          <div class="alert alert-info">
            <i class="fas fa-info-circle me-2"></i>Enter team numbers to compare statistics
          </div>
        {% endif %}
        '''
        html = render_template_string(html_template, comparison_data=comparison_data)
        return jsonify({'html': html})

    elif wtype == 'team_rankings':
        # Handle team rankings widget - return HTML fragment
        event_filter = overrides.get('rankings_event', 'all')
        count = int(widget.get('count', 10) or widget.get('rankings_count', 10))
        sort_by = widget.get('sort_by', 'points') or widget.get('rankings_sort', 'points')
        show_stats = widget.get('show_stats', False) or widget.get('rankings_show_stats', False)
        rankings_data = None
        
        try:
            # Build event filter if specified
            event_id = None
            if event_filter and event_filter != 'all':
                try:
                    event_id = int(event_filter)
                except ValueError:
                    pass
            
            teams_query = Team.query.order_by(Team.team_number).all()
            team_rankings = []
            for team in teams_query:
                # Pass event_id to calculate_team_metrics to filter data by event
                analytics_result = calculate_team_metrics(team.id, event_id=event_id)
                metrics = analytics_result.get('metrics', {})
                
                if sort_by == 'points' or sort_by == 'score':
                    sort_value = metrics.get('total_points') or metrics.get('tot') or 0
                elif sort_by == 'wins':
                    sort_value = metrics.get('wins') or 0
                elif sort_by == 'RP':
                    sort_value = metrics.get('ranking_points') or 0
                else:
                    sort_value = metrics.get(sort_by) or 0
                
                team_rankings.append({
                    'team_number': team.team_number,
                    'team_name': team.team_name or f'Team {team.team_number}',
                    'sort_value': sort_value,
                    'metrics': metrics if show_stats else {}
                })
            
            team_rankings.sort(key=lambda x: x['sort_value'], reverse=True)
            team_rankings = team_rankings[:count]
            
            for idx, ranking in enumerate(team_rankings):
                ranking['rank'] = idx + 1
            
            rankings_data = {
                'rankings': team_rankings,
                'sort_by': sort_by,
                'show_stats': show_stats,
                'event_filter': event_filter if event_id else 'all'
            }
        except Exception as e:
            current_app.logger.error(f"Error calculating team rankings: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
        
        html_template = '''
        {% if rankings_data %}
          <h5 class="mb-3"><i class="fas fa-list-ol me-2"></i>Team Rankings{% if rankings_data.event_filter != 'all' %} (Event){% endif %} ({{ rankings_data.sort_by|title }})</h5>
          <div class="table-responsive">
            <table class="table table-hover table-sm">
              <thead class="table-light">
                <tr>
                  <th>Rank</th>
                  <th>Team</th>
                  <th class="text-end">{{ rankings_data.sort_by|replace('_', ' ')|title }}</th>
                  {% if rankings_data.show_stats %}
                  <th class="text-end">Avg Points</th>
                  {% endif %}
                </tr>
              </thead>
              <tbody>
                {% for team in rankings_data.rankings %}
                <tr>
                  <td><span class="badge bg-{{ 'warning' if team.rank <= 3 else 'secondary' }}">{{ team.rank }}</span></td>
                  <td><strong>{{ team.team_number }}</strong> - {{ team.team_name }}</td>
                  <td class="text-end">{{ team.sort_value|round(2) }}</td>
                  {% if rankings_data.show_stats %}
                  <td class="text-end">{{ team.metrics.get('total_points', team.metrics.get('tot', 'N/A')) }}</td>
                  {% endif %}
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        {% else %}
          <div class="alert alert-info">
            <i class="fas fa-info-circle me-2"></i>No ranking data available
          </div>
        {% endif %}
        '''
        html = render_template_string(html_template, rankings_data=rankings_data)
        return jsonify({'html': html})

    elif wtype == 'recent_matches':
        # Handle recent matches widget - return HTML fragment
        event_filter = overrides.get('matches_event')
        filter_type = widget.get('filter', 'all') or widget.get('matches_filter', 'all')
        count = int(widget.get('count', 10) or widget.get('matches_count', 10))
        show_scores = widget.get('show_scores', True) if widget.get('show_scores') is not None else widget.get('matches_show_scores', True)
        matches_data = None
        
        try:
            matches_query = Match.query
            
            if event_filter:
                try:
                    event_id = int(event_filter)
                    matches_query = matches_query.filter_by(event_id=event_id)
                except ValueError:
                    pass
            
            matches_query = matches_query.order_by(Match.timestamp.desc()).limit(count)
            matches = matches_query.all()
            
            matches_list = []
            for match in matches:
                match_data = {
                    'match_id': match.id,
                    'match_type': match.match_type,
                    'match_number': match.match_number,
                    'red_alliance': match.red_alliance,
                    'blue_alliance': match.blue_alliance,
                    'timestamp': match.timestamp
                }
                
                if show_scores and match.red_score is not None and match.blue_score is not None:
                    match_data['red_score'] = match.red_score
                    match_data['blue_score'] = match.blue_score
                    match_data['winner'] = 'red' if match.red_score > match.blue_score else 'blue' if match.blue_score > match.red_score else 'tie'
                
                matches_list.append(match_data)
            
            matches_data = {
                'matches': matches_list,
                'show_scores': show_scores
            }
        except Exception as e:
            current_app.logger.error(f"Error fetching recent matches: {e}")
        
        html_template = '''
        {% if matches_data %}
          <h5 class="mb-3"><i class="fas fa-history me-2"></i>Recent Matches</h5>
          <div class="list-group">
            {% for match in matches_data.matches %}
            <div class="list-group-item">
              <div class="d-flex justify-content-between align-items-center">
                <div>
                  <strong>{{ match.match_type }} {{ match.match_number }}</strong>
                  {% if match.timestamp %}
                  <small class="text-muted ms-2">{{ match.timestamp.strftime('%m/%d %H:%M') }}</small>
                  {% endif %}
                </div>
                {% if matches_data.show_scores and match.get('red_score') is not none %}
                <div>
                  <span class="badge bg-{{ 'danger' if match.get('winner') == 'red' else 'secondary' }}">Red: {{ match.red_score }}</span>
                  <span class="badge bg-{{ 'primary' if match.get('winner') == 'blue' else 'secondary' }} ms-1">Blue: {{ match.blue_score }}</span>
                </div>
                {% endif %}
              </div>
              <div class="mt-1">
                <small class="text-danger">Red: {{ match.red_alliance }}</small>
                <small class="text-primary ms-3">Blue: {{ match.blue_alliance }}</small>
              </div>
            </div>
            {% endfor %}
          </div>
        {% else %}
          <div class="alert alert-info">
            <i class="fas fa-info-circle me-2"></i>No match data available
          </div>
        {% endif %}
        '''
        html = render_template_string(html_template, matches_data=matches_data)
        return jsonify({'html': html})

    else:
        # no dynamic plots for other widget types
        widget_plots = {}

    return jsonify({'plots': widget_plots})


@bp.route('/pages/<int:page_id>')
@analytics_required
def pages_view(page_id):
    """Render a custom page composed of widgets. Graph widgets will be generated using existing chart helpers."""
    from flask import request
    page = CustomPage.query.get_or_404(page_id)
    # Only allow viewing pages owned by this team (for now)
    if page.owner_team != current_user.scouting_team_number:
        abort(403)

    widgets = page.widgets()
    plots = {}

    # Import needed functions for new widget types
    from app.utils.analysis import predict_match_outcome, get_match_details_with_teams

    # For each widget, generate plots and collect them under a widget key
    for i, widget in enumerate(widgets):
        wtype = widget.get('type')
        wkey = f'widget_{i}'
        if wtype == 'graph':
            # Build team_data limited to provided teams
            selected_teams = widget.get('teams', [])
            # normalize selection values
            if isinstance(selected_teams, list):
                selected_teams = [s for s in selected_teams]
            metric = widget.get('metric', 'points')
            metric_alias = 'tot' if metric in ('total_points', 'points', 'tot') else metric
            graph_types = widget.get('graph_types', ['bar', 'line'])
            data_view = widget.get('data_view', 'averages')

            # Fetch team objects. Interpret empty selected_teams as "all teams"
            team_ids = []
            if selected_teams and not (len(selected_teams) == 1 and str(selected_teams[0]) == 'all'):
                # client sends Team.id values; coerce
                team_ids = []
                for s in selected_teams:
                    if s == 'all':
                        team_ids = []
                        break
                    try:
                        team_ids.append(int(s))
                    except Exception:
                        pass
                if team_ids:
                    teams = Team.query.filter(Team.id.in_(team_ids)).all()
                    found_ids = {t.id for t in teams}
                    missing = [tid for tid in team_ids if tid not in found_ids]
                    if missing:
                        more_by_number = Team.query.filter(Team.team_number.in_(missing)).all()
                        if more_by_number:
                            teams.extend(more_by_number)
                else:
                    teams = Team.query.order_by(Team.team_number).all()
            else:
                teams = Team.query.order_by(Team.team_number).all()
            # Ensure we have an entry for each requested team (even if no ScoutingData exists)
            if selected_teams and team_ids:
                existing_ids = {t.id for t in teams}
                missing_ids = [tid for tid in team_ids if tid not in existing_ids]
                if missing_ids:
                    more = Team.query.filter(Team.id.in_(missing_ids)).all()
                    teams.extend(more)
            # Deduplicate teams by team_number (some events may have duplicate rows)
            unique_map = {}
            for t in teams:
                if t.team_number not in unique_map:
                    unique_map[t.team_number] = t
            teams = sorted(unique_map.values(), key=lambda x: x.team_number)
            team_numbers = [t.team_number for t in teams]

            team_data = {}
            # Gather scouting data for these teams
            if teams:
                team_ids = [t.id for t in teams]
                scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids), ScoutingData.scouting_team_number==current_user.scouting_team_number).all()
                for data in scouting_data:
                    team = data.team
                    match = data.match
                    if team.team_number not in team_data:
                        team_data[team.team_number] = {'team_name': team.team_name, 'matches': []}
                    if metric_alias == 'tot':
                        metric_value = data.calculate_metric('tot')
                    else:
                        metric_value = data.calculate_metric(metric_alias)
                    team_data[team.team_number]['matches'].append({'match_number': match.match_number if match else None, 'metric_value': metric_value, 'timestamp': match.timestamp if match else None})

            # If this widget exposes user-select controls to viewers, don't auto-generate the plots here.
            # The viewer will click Refresh to generate with their overrides. This avoids heavy rendering when viewers need to pick options.
            if widget.get('user_select') or widget.get('graphtype_user_select') or widget.get('teams_user_select'):
                widget_plots = {}
            else:
                # Use graph helpers to create plots for this widget
                widget_plots = {}
                for gt in graph_types:
                    if gt == 'bar':
                        widget_plots.update(_create_bar_chart(team_data, metric, data_view))
                    elif gt == 'line':
                        widget_plots.update(_create_line_chart(team_data, metric, data_view))
                    elif gt == 'scatter':
                        widget_plots.update(_create_scatter_chart(team_data, metric, data_view))
                    elif gt == 'histogram':
                        widget_plots.update(_create_histogram_chart(team_data, metric, data_view))
                    elif gt == 'violin':
                        widget_plots.update(_create_violin_chart(team_data, metric, data_view))
                    elif gt == 'box':
                        widget_plots.update(_create_box_chart(team_data, metric, data_view))
                    elif gt == 'sunburst':
                        widget_plots.update(_create_sunburst_chart(team_data, metric, data_view))
                    elif gt == 'treemap':
                        widget_plots.update(_create_treemap_chart(team_data, metric, data_view))
                    elif gt == 'waterfall':
                        widget_plots.update(_create_waterfall_chart(team_data, metric, data_view))
                    elif gt == 'sankey':
                        widget_plots.update(_create_sankey_chart(team_data, metric, data_view))
                    elif gt == 'heatmap':
                        widget_plots.update(_create_heatmap_chart(team_data, metric, data_view))
                    elif gt == 'bubble':
                        widget_plots.update(_create_bubble_chart(team_data, metric, data_view))
                    elif gt == 'area':
                        widget_plots.update(_create_area_chart(team_data, metric, data_view))
                    elif gt == 'radar':
                        widget_plots.update(_create_radar_chart(team_data, metric, data_view))

            plots[wkey] = {'config': widget, 'plots': widget_plots}

        elif wtype == 'match_prediction':
            # Handle match prediction widget
            # Check if user has selected a match via URL parameter
            match_id = widget.get('match')
            if widget.get('prediction_match') == 'user_select':
                # Look for user selection in URL parameters
                user_match = request.args.get(f'prediction_{i}')
                if user_match:
                    match_id = user_match
            
            prediction_data = None
            if match_id and match_id != 'user_select':
                try:
                    match_details = get_match_details_with_teams(int(match_id))
                    if match_details and match_details.get('prediction'):
                        # Structure the data the same way as the AJAX endpoint
                        prediction = match_details['prediction']
                        prediction_data = {
                            'red_alliance': prediction.get('red_alliance', {}),
                            'blue_alliance': prediction.get('blue_alliance', {}),
                            'predicted_winner': prediction.get('predicted_winner', 'unknown'),
                            'probabilities': prediction.get('probabilities', {'red': 0, 'blue': 0, 'tie': 0}),
                            'confidence': prediction.get('confidence', 0),
                            'match': match_details.get('match'),
                            'match_completed': match_details.get('match_completed', False),
                            'actual_winner': match_details.get('actual_winner')
                        }
                except Exception as e:
                    current_app.logger.error(f"Error fetching match prediction for widget {i}: {e}")
                    import traceback
                    current_app.logger.error(traceback.format_exc())
            plots[wkey] = {'config': widget, 'plots': {}, 'prediction_data': prediction_data}

        elif wtype == 'team_comparison':
            # Handle team comparison widget
            team1_num = widget.get('team1') or widget.get('comparison_team1')
            team2_num = widget.get('team2') or widget.get('comparison_team2')
            # Check if user has selected teams via URL parameters
            if widget.get('comparison_user_select'):
                user_team1 = request.args.get(f'comparison_{i}_team1')
                user_team2 = request.args.get(f'comparison_{i}_team2')
                if user_team1:
                    team1_num = user_team1
                if user_team2:
                    team2_num = user_team2
            
            metrics = widget.get('metrics', []) or widget.get('comparison_metrics', [])
            comparison_data = None
            
            if team1_num and team2_num:
                try:
                    team1 = Team.query.filter_by(team_number=int(team1_num)).first()
                    team2 = Team.query.filter_by(team_number=int(team2_num)).first()
                    
                    if team1 and team2:
                        from app.utils.analysis import calculate_team_metrics
                        # Support event filtering on initial load
                        event_filter = widget.get('event', 'all') or widget.get('comparison_event', 'all')
                        event_id = None
                        if event_filter and event_filter != 'all' and event_filter != 'user_select':
                            try:
                                event_id = int(event_filter)
                            except ValueError:
                                pass
                        
                        team1_analytics = calculate_team_metrics(team1.id, event_id=event_id)
                        team2_analytics = calculate_team_metrics(team2.id, event_id=event_id)
                        
                        # Use default metrics if none specified
                        if not metrics:
                            metrics = ['total_points', 'auto_points', 'teleop_points', 'endgame_points']
                        
                        comparison_data = {
                            'team1': {
                                'team_number': team1.team_number,
                                'team_name': team1.team_name or f'Team {team1.team_number}',
                                'metrics': team1_analytics.get('metrics', {})
                            },
                            'team2': {
                                'team_number': team2.team_number,
                                'team_name': team2.team_name or f'Team {team2.team_number}',
                                'metrics': team2_analytics.get('metrics', {})
                            },
                            'selected_metrics': metrics
                        }
                except Exception as e:
                    current_app.logger.error(f"Error fetching team comparison for widget {i}: {e}")
            plots[wkey] = {'config': widget, 'plots': {}, 'comparison_data': comparison_data}

        elif wtype == 'team_rankings':
            # Handle team rankings widget
            event_filter = widget.get('event', 'all') or widget.get('rankings_event', 'all')
            # Check if user has selected an event via URL parameters
            if event_filter == 'user_select':
                user_event = request.args.get(f'rankings_{i}_event')
                if user_event:
                    event_filter = user_event
            
            count = int(widget.get('count', 10) or widget.get('rankings_count', 10))
            sort_by = widget.get('sort_by', 'points') or widget.get('rankings_sort', 'points')
            show_stats = widget.get('show_stats', False) or widget.get('rankings_show_stats', False)
            rankings_data = None
            
            try:
                from app.utils.analysis import calculate_team_metrics
                
                # Parse event_id for filtering
                event_id = None
                if event_filter and event_filter != 'all' and event_filter != 'user_select':
                    try:
                        event_id = int(event_filter)
                    except ValueError:
                        pass
                
                # Get all teams
                teams_query = Team.query.order_by(Team.team_number).all()
                
                # Calculate metrics for each team
                team_rankings = []
                for team in teams_query:
                    # Pass event_id to filter metrics by event
                    analytics_result = calculate_team_metrics(team.id, event_id=event_id)
                    metrics = analytics_result.get('metrics', {})
                    
                    # Determine sort value based on sort_by parameter
                    if sort_by == 'points' or sort_by == 'score':
                        sort_value = metrics.get('total_points') or metrics.get('tot') or 0
                    elif sort_by == 'wins':
                        sort_value = metrics.get('wins') or 0
                    elif sort_by == 'RP':
                        sort_value = metrics.get('ranking_points') or 0
                    else:
                        sort_value = metrics.get(sort_by) or 0
                    
                    team_rankings.append({
                        'team_number': team.team_number,
                        'team_name': team.team_name or f'Team {team.team_number}',
                        'sort_value': sort_value,
                        'metrics': metrics if show_stats else {}
                    })
                
                # Sort by sort_value descending
                team_rankings.sort(key=lambda x: x['sort_value'], reverse=True)
                
                # Limit to count
                team_rankings = team_rankings[:count]
                
                # Add rank numbers
                for idx, ranking in enumerate(team_rankings):
                    ranking['rank'] = idx + 1
                
                rankings_data = {
                    'rankings': team_rankings,
                    'sort_by': sort_by,
                    'show_stats': show_stats
                }
            except Exception as e:
                current_app.logger.error(f"Error calculating team rankings for widget {i}: {e}")
            
            plots[wkey] = {'config': widget, 'plots': {}, 'rankings_data': rankings_data}

        elif wtype == 'recent_matches':
            # Handle recent matches widget
            filter_type = widget.get('filter', 'all') or widget.get('matches_filter', 'all')
            team_num = widget.get('team') or widget.get('matches_team')
            event_filter = widget.get('event') or widget.get('matches_event')
            # Check if user has selected an event via URL parameters
            if event_filter == 'user_select':
                user_event = request.args.get(f'matches_{i}_event')
                if user_event:
                    event_filter = user_event
                    filter_type = 'event'  # Override filter type when user selects
            
            count = int(widget.get('count', 10) or widget.get('matches_count', 10))
            show_scores = widget.get('show_scores', True) if widget.get('show_scores') is not None else widget.get('matches_show_scores', True)
            matches_data = None
            
            try:
                # Build query based on filter
                matches_query = Match.query
                
                if filter_type == 'team' and team_num:
                    # Filter matches that include this team
                    team_num_str = str(team_num)
                    matches_query = matches_query.filter(
                        db.or_(
                            Match.red_alliance.like(f'%{team_num_str}%'),
                            Match.blue_alliance.like(f'%{team_num_str}%')
                        )
                    )
                elif filter_type == 'event' and event_filter and event_filter != 'user_select':
                    # Filter by event ID
                    try:
                        event_id = int(event_filter)
                        matches_query = matches_query.filter_by(event_id=event_id)
                    except ValueError:
                        pass  # Invalid event ID
                
                # Order by most recent and limit
                matches_query = matches_query.order_by(Match.timestamp.desc()).limit(count)
                matches = matches_query.all()
                
                # Format matches data
                matches_list = []
                for match in matches:
                    match_data = {
                        'match_id': match.id,
                        'match_type': match.match_type,
                        'match_number': match.match_number,
                        'red_alliance': match.red_alliance,
                        'blue_alliance': match.blue_alliance,
                        'timestamp': match.timestamp
                    }
                    
                    if show_scores and match.red_score is not None and match.blue_score is not None:
                        match_data['red_score'] = match.red_score
                        match_data['blue_score'] = match.blue_score
                        match_data['winner'] = 'red' if match.red_score > match.blue_score else 'blue' if match.blue_score > match.red_score else 'tie'
                    
                    matches_list.append(match_data)
                
                matches_data = {
                    'matches': matches_list,
                    'filter_type': filter_type,
                    'show_scores': show_scores
                }
            except Exception as e:
                current_app.logger.error(f"Error fetching recent matches for widget {i}: {e}")
            
            plots[wkey] = {'config': widget, 'plots': {}, 'matches_data': matches_data}

        else:
            # For unknown widget types, store as-is
            plots[wkey] = {'config': widget, 'plots': {}}

    # Provide metric/scoring/teams context for viewer controls
    game_config = get_effective_game_config()
    metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
    # Ensure a 'total_points' metric exists for viewers as well
    try:
        if isinstance(metrics, list):
            if not any(m.get('id') == 'total_points' for m in metrics):
                metrics.append({'id': 'total_points', 'name': 'Total Points'})
    except Exception:
        metrics = metrics
    scoring_elements = []
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        for el in game_config.get(period, {}).get('scoring_elements', []):
            scoring_elements.append({'period': period, 'id': el.get('perm_id', el.get('id')), 'name': el.get('name', el.get('id'))})

    teams_q = Team.query.order_by(Team.team_number).all()
    teams = [{'id': t.team_number, 'name': t.team_name or f'Team {t.team_number}'} for t in teams_q]

    # Fetch events and matches for dropdown population
    events_q = Event.query.order_by(Event.name).limit(500).all()
    events = [{'id': e.id, 'name': e.name or e.code, 'code': e.code} for e in events_q]
    
    matches_q = Match.query.order_by(Match.event_id, Match.match_number).limit(1000).all()
    matches = [{'id': m.id, 'event_id': m.event_id, 'match_type': m.match_type, 'match_number': m.match_number} for m in matches_q]

    return render_template('graphs/pages_view.html', page=page, plots=plots, metrics=metrics, scoring_elements=scoring_elements, teams=teams, events=events, matches=matches, **get_theme_context())


@bp.route('/pages/<int:page_id>/delete', methods=['POST'])
@analytics_required
def pages_delete(page_id):
    page = CustomPage.query.get_or_404(page_id)
    if page.owner_team != current_user.scouting_team_number or page.owner_user != current_user.username:
        abort(403)
    page.is_active = False
    db.session.commit()
    flash('Custom page deleted.', 'success')
    return redirect(url_for('graphs.pages_index'))


@bp.route('/strategy_share/<token>/revoke', methods=['POST'])
@analytics_required
def revoke_strategy_share(token):
    """Revoke a file-backed strategy share token"""
    shares_file = os.path.join(current_app.instance_path, 'strategy_shares.json')
    try:
        if not os.path.exists(shares_file):
            flash('Share not found.', 'danger')
            return redirect(url_for('graphs.my_shares'))
        import json
        with open(shares_file, 'r') as f:
            shares = json.load(f) or {}

        if token not in shares:
            flash('Share not found.', 'danger')
            return redirect(url_for('graphs.my_shares'))

        shares[token]['revoked'] = True
        tmp_path = shares_file + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(shares, f)
        os.replace(tmp_path, shares_file)
        flash('Strategy share revoked.', 'success')
    except Exception as e:
        current_app.logger.exception('Error revoking strategy share')
        flash('Unable to revoke share.', 'danger')

    return redirect(url_for('graphs.my_shares'))

@bp.route('/share/<int:share_id>/delete', methods=['POST'])
@analytics_required
def delete_share(share_id):
    """Delete a shared graph"""
    shared_graph = SharedGraph.query.get_or_404(share_id)
    
    # Check if user owns this share
    if (shared_graph.created_by_team != current_user.scouting_team_number or 
        shared_graph.created_by_user != current_user.username):
        abort(403, description="You don't have permission to delete this shared graph.")
    
    # Soft delete by setting is_active to False
    shared_graph.is_active = False
    db.session.commit()
    
    flash('Shared graph deleted successfully.', 'success')
    return redirect(url_for('graphs.my_shares'))

# Helper functions for creating different chart types
def _create_bar_chart(team_data, metric, data_view):
    """Create a bar chart for the given team data and metric"""
    plots = {}
    
    if data_view == 'averages':
        # Team averages bar chart
        teams = []
        values = []
        
        for team_number, data in team_data.items():
            # Include teams even if they have no matches; show zero for no-data teams
            if data['matches']:
                avg_value = sum(m['metric_value'] for m in data['matches']) / len(data['matches'])
            else:
                avg_value = 0
            teams.append(f"Team {team_number}")
            values.append(avg_value)
        
        if teams:
            fig = go.Figure(data=[
                go.Bar(x=teams, y=values, name=metric.replace('_', ' ').title())
            ])
            fig.update_layout(
                title=f"{metric.replace('_', ' ').title()} by Team - Averages (Bar Chart)",
                xaxis_title="Team",
                yaxis_title=metric.replace('_', ' ').title(),
                margin=dict(l=40, r=20, t=50, b=60)
            )
            plots[f'{metric}_bar_avg'] = pio.to_json(fig)
    else:
        # Match-by-match bar chart
        fig = go.Figure()
        for team_number, data in team_data.items():
            if data['matches']:
                match_numbers = [m['match_number'] for m in data['matches']]
                values = [m['metric_value'] for m in data['matches']]
                fig.add_trace(go.Bar(
                    x=match_numbers,
                    y=values,
                    name=f"Team {team_number}"
                ))
        
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} per Match - All Teams (Bar Chart)",
            xaxis_title="Match Number",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60),
            barmode='group'
        )
        plots[f'{metric}_bar_matches'] = pio.to_json(fig)
    
    return plots

def _create_line_chart(team_data, metric, data_view):
    """Create a line chart for the given team data and metric"""
    plots = {}
    
    if data_view == 'matches':
        # Match-by-match line chart
        fig = go.Figure()
        for team_number, data in team_data.items():
            if data['matches']:
                # Sort matches by match number
                sorted_matches = sorted(data['matches'], key=lambda x: x['match_number'])
                match_numbers = [m['match_number'] for m in sorted_matches]
                values = [m['metric_value'] for m in sorted_matches]
                fig.add_trace(go.Scatter(
                    x=match_numbers,
                    y=values,
                    mode='lines+markers',
                    name=f"Team {team_number}"
                ))
        
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Trend - All Teams (Line Chart)",
            xaxis_title="Match Number",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60)
        )
        plots[f'{metric}_line_matches'] = pio.to_json(fig)
    else:
        # Averages view: show a line across team averages (like index page)
        avg_data = []
        for team_number, data in team_data.items():
            values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
            avg = np.mean(values) if values else 0
            avg_data.append({'team': team_number, 'avg': avg})

        if avg_data:
            # sort by team number for stable ordering
            avg_data = sorted(avg_data, key=lambda x: int(x['team']))
            fig_line = go.Figure()
            fig_line.add_trace(go.Scatter(
                x=[str(d['team']) for d in avg_data],
                y=[d['avg'] for d in avg_data],
                mode='lines+markers',
                marker_color='royalblue'
            ))
            fig_line.update_layout(
                title=f"{metric.replace('_', ' ').title()} by Team - Averages (Line Chart)",
                xaxis_title="Team",
                yaxis_title=metric.replace('_', ' ').title(),
                margin=dict(l=40, r=20, t=50, b=60)
            )
            plots[f'{metric}_line_avg'] = pio.to_json(fig_line)

    return plots

def _create_scatter_chart(team_data, metric, data_view):
    """Create a scatter plot for the given team data and metric"""
    plots = {}
    
    if data_view == 'matches':
        # Match-by-match scatter plot
        fig = go.Figure()
        for team_number, data in team_data.items():
            if data['matches']:
                match_numbers = [m['match_number'] for m in data['matches']]
                values = [m['metric_value'] for m in data['matches']]
                fig.add_trace(go.Scatter(
                    x=match_numbers,
                    y=values,
                    mode='markers',
                    name=f"Team {team_number}",
                    marker=dict(size=8)
                ))
        
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Distribution - All Teams (Scatter Plot)",
            xaxis_title="Match Number",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60)
        )
        plots[f'{metric}_scatter_matches'] = pio.to_json(fig)
    else:
        # Averages view: scatter of team averages
        avg_data = []
        for team_number, data in team_data.items():
            values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
            avg = np.mean(values) if values else 0
            avg_data.append({'team': team_number, 'avg': avg})

        if avg_data:
            avg_data = sorted(avg_data, key=lambda x: int(x['team']))
            fig_scatter = go.Figure()
            fig_scatter.add_trace(go.Scatter(
                x=[str(d['team']) for d in avg_data],
                y=[d['avg'] for d in avg_data],
                mode='markers',
                marker=dict(size=10, color='royalblue')
            ))
            fig_scatter.update_layout(
                title=f"{metric.replace('_', ' ').title()} by Team - Averages (Scatter Plot)",
                xaxis_title="Team",
                yaxis_title=metric.replace('_', ' ').title(),
                margin=dict(l=40, r=20, t=50, b=60)
            )
            plots[f'{metric}_scatter_avg'] = pio.to_json(fig_scatter)

    return plots

def _create_histogram_chart(team_data, metric, data_view):
    """Create a histogram for the given team data and metric"""
    plots = {}
    
    # Collect all values
    all_values = []
    for team_number, data in team_data.items():
        for match in data['matches']:
            if match['metric_value'] is not None:
                all_values.append(match['metric_value'])
    
    if all_values:
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=all_values,
            nbinsx=20,
            name=metric.replace('_', ' ').title(),
            hovertemplate=f'{metric.replace("_", " ").title()}: %{{x}}<br>Count: %{{y}}<extra></extra>'
        ))
        
        theme_vals = _chart_theme()
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Distribution (Histogram)",
            xaxis_title=metric.replace('_', ' ').title(),
            yaxis_title="Frequency",
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            font=dict(color=theme_vals['text_main'])
        )
        plots[f'{metric}_histogram'] = pio.to_json(fig)
    
    return plots

def _create_violin_chart(team_data, metric, data_view):
    """Create a violin plot for the given team data and metric"""
    plots = {}
    
    if data_view == 'matches':
        fig = go.Figure()
        for team_number, data in team_data.items():
            if data['matches'] and len(data['matches']) > 1:
                values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
                if values:
                    fig.add_trace(go.Violin(
                        y=values,
                        name=f"Team {team_number}",
                        box_visible=True,
                        meanline_visible=True,
                        hovertemplate=f'Team %{{fullData.name}}<br>{metric.replace("_", " ").title()}: %{{y}}<extra></extra>'
                    ))
        
        theme_vals = _chart_theme()
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Distribution by Team (Violin Plot)",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            font=dict(color=theme_vals['text_main'])
        )
        plots[f'{metric}_violin'] = pio.to_json(fig)
    
    return plots

def _create_box_chart(team_data, metric, data_view):
    """Create a box plot for the given team data and metric"""
    plots = {}
    
    if data_view == 'matches':
        fig = go.Figure()
        for team_number, data in team_data.items():
            if data['matches'] and len(data['matches']) > 1:
                values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
                if values:
                    fig.add_trace(go.Box(
                        y=values,
                        name=f"Team {team_number}",
                        boxmean=True,
                        hovertemplate=f'Team %{{fullData.name}}<br>{metric.replace("_", " ").title()}: %{{y}}<extra></extra>'
                    ))
        
        theme_vals = _chart_theme()
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Distribution by Team (Box Plot)",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            font=dict(color=theme_vals['text_main'])
        )
        plots[f'{metric}_box'] = pio.to_json(fig)
    
    return plots

def _create_sunburst_chart(team_data, metric, data_view):
    """Create a sunburst chart for the given team data and metric"""
    plots = {}
    
    # Collect all values for percentile calculation
    all_values = []
    for team_number, data in team_data.items():
        team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
        if team_values:
            if data_view == 'averages':
                all_values.append(sum(team_values) / len(team_values))
            else:
                all_values.extend(team_values)
    
    if all_values:
        import numpy as np
        sunburst_data = []
        
        for team_number, data in team_data.items():
            team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
            if team_values:
                if data_view == 'averages':
                    team_metric = sum(team_values) / len(team_values)
                else:
                    team_metric = sum(team_values)
                
                # Categorize performance
                if team_metric >= np.percentile(all_values, 75):
                    category = "High Performers"
                elif team_metric >= np.percentile(all_values, 50):
                    category = "Medium Performers"
                elif team_metric >= np.percentile(all_values, 25):
                    category = "Low Performers"
                else:
                    category = "Developing Teams"
                
                sunburst_data.append({
                    'ids': f"Team {team_number}",
                    'labels': f"Team {team_number}",
                    'parents': category,
                    'values': team_metric
                })
        
        # Add category parents
        categories = ["High Performers", "Medium Performers", "Low Performers", "Developing Teams"]
        for category in categories:
            total_value = sum([d['values'] for d in sunburst_data if d.get('parents') == category])
            if total_value > 0:
                sunburst_data.append({
                    'ids': category,
                    'labels': category,
                    'parents': "",
                    'values': total_value
                })
        
        if sunburst_data:
            fig = go.Figure(go.Sunburst(
                ids=[d['ids'] for d in sunburst_data],
                labels=[d['labels'] for d in sunburst_data],
                parents=[d['parents'] for d in sunburst_data],
                values=[d['values'] for d in sunburst_data],
                branchvalues="total",
                hovertemplate=f'<b>%{{label}}</b><br>{metric.replace("_", " ").title()}: %{{value:.2f}}<extra></extra>'
            ))
            theme_vals = _chart_theme()
            fig.update_layout(
                title=f"Team {metric.replace('_', ' ').title()} Performance Hierarchy (Sunburst)",
                margin=dict(l=40, r=20, t=50, b=60),
                plot_bgcolor=theme_vals['plot_bg'],
                paper_bgcolor=theme_vals['paper_bg'],
                font=dict(color=theme_vals['text_main'])
            )
            plots[f'{metric}_sunburst'] = pio.to_json(fig)
    
    return plots

def _create_treemap_chart(team_data, metric, data_view):
    """Create a treemap chart for the given team data and metric"""
    plots = {}
    
    # Calculate team values
    team_values = []
    for team_number, data in team_data.items():
        team_matches = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
        if team_matches:
            if data_view == 'averages':
                value = sum(team_matches) / len(team_matches)
            else:
                value = sum(team_matches)
            team_values.append((f"Team {team_number}", value))
    
    if team_values:
        teams, values = zip(*team_values)
        
        fig = go.Figure(go.Treemap(
            labels=list(teams),
            values=list(values),
            parents=[""] * len(teams),
            hovertemplate=f'<b>%{{label}}</b><br>{metric.replace("_", " ").title()}: %{{value:.2f}}<extra></extra>'
        ))
        
        theme_vals = _chart_theme()
        fig.update_layout(
            title=f"Team {metric.replace('_', ' ').title()} Performance (Treemap)",
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            font=dict(color=theme_vals['text_main'])
        )
        plots[f'{metric}_treemap'] = pio.to_json(fig)
    
    return plots

def _create_waterfall_chart(team_data, metric, data_view):
    """Create a waterfall chart for the given team data and metric"""
    plots = {}
    
    if data_view == 'averages':
        # Team contribution waterfall
        team_values = []
        for team_number, data in team_data.items():
            team_matches = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
            if team_matches:
                avg_value = sum(team_matches) / len(team_matches)
                team_values.append((f"Team {team_number}", avg_value))
        
        if team_values:
            # Sort by value
            team_values.sort(key=lambda x: x[1])
            teams, values = zip(*team_values)
            
            fig = go.Figure(go.Waterfall(
                name="Team Contributions",
                orientation="v",
                measure=["relative"] * len(teams),
                x=list(teams),
                y=list(values),
                text=[f"{v:.2f}" for v in values],
                textposition="outside",
                hovertemplate=f'<b>%{{x}}</b><br>{metric.replace("_", " ").title()}: %{{y:.2f}}<extra></extra>'
            ))
            
            theme_vals = _chart_theme()
            fig.update_layout(
                title=f"Team {metric.replace('_', ' ').title()} Contribution (Waterfall)",
                xaxis_title="Teams",
                yaxis_title=metric.replace('_', ' ').title(),
                margin=dict(l=40, r=20, t=50, b=60),
                plot_bgcolor=theme_vals['plot_bg'],
                paper_bgcolor=theme_vals['paper_bg'],
                font=dict(color=theme_vals['text_main'])
            )
            plots[f'{metric}_waterfall'] = pio.to_json(fig)
    
    return plots

def _create_sankey_chart(team_data, metric, data_view):
    """Create an enhanced sankey diagram for the given team data and metric"""
    plots = {}
    
    # Collect all values for categorization
    all_values = []
    for team_number, data in team_data.items():
        for match in data['matches']:
            if match['metric_value'] is not None:
                all_values.append(match['metric_value'])
    
    if all_values and len(team_data) > 1:
        import numpy as np
        # Use theme card background so charts blend with UI
        try:
            theme = ThemeManager().get_current_theme()
        except Exception:
            theme = {}
        card_bg = theme.get('colors', {}).get('card-bg') if isinstance(theme, dict) else None
        
        sankey_nodes = []
        sankey_links = []
        
        if data_view == 'averages':
            # Enhanced multi-layer Sankey for averages view
            # Layer 1: Teams
            teams_layer_start = 0
            team_indices = {}
            for i, team_number in enumerate(team_data.keys()):
                team_name = f"Team {team_number}"
                sankey_nodes.append(team_name)
                team_indices[team_number] = i
            
            # Layer 2: Performance Categories  
            perf_layer_start = len(sankey_nodes)
            performance_categories = ["Elite Performance", "Strong Performance", "Solid Performance", "Developing Performance"]
            perf_indices = {}
            for i, category in enumerate(performance_categories):
                sankey_nodes.append(category)
                perf_indices[category] = perf_layer_start + i
            
            # Layer 3: Impact Categories
            impact_layer_start = len(sankey_nodes)
            impact_categories = ["High Impact", "Consistent Contributor", "Steady Player", "Growth Focus"]
            impact_indices = {}
            for i, category in enumerate(impact_categories):
                sankey_nodes.append(category)
                impact_indices[category] = impact_layer_start + i
            
            # Calculate team averages and thresholds
            team_averages = {}
            for team_number, data in team_data.items():
                team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
                if team_values:
                    team_averages[team_number] = np.mean(team_values)
            
            avg_values = list(team_averages.values())
            threshold_80 = np.percentile(avg_values, 80)
            threshold_60 = np.percentile(avg_values, 60)
            threshold_40 = np.percentile(avg_values, 40)
            
            # Teams -> Performance Categories
            for team_number, avg_value in team_averages.items():
                team_idx = team_indices[team_number]
                
                if avg_value >= threshold_80:
                    target_idx = perf_indices["Elite Performance"]
                    color = "rgba(76, 175, 80, 0.7)"  # Green
                elif avg_value >= threshold_60:
                    target_idx = perf_indices["Strong Performance"]  
                    color = "rgba(255, 193, 7, 0.7)"  # Amber
                elif avg_value >= threshold_40:
                    target_idx = perf_indices["Solid Performance"]
                    color = "rgba(255, 152, 0, 0.7)"  # Orange
                else:
                    target_idx = perf_indices["Developing Performance"]
                    color = "rgba(244, 67, 54, 0.7)"  # Red
                
                sankey_links.append({
                    'source': team_idx,
                    'target': target_idx,
                    'value': avg_value,
                    'color': color
                })
            
            # Performance Categories -> Impact Categories
            for team_number, data in team_data.items():
                team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
                if len(team_values) > 1:
                    avg_value = np.mean(team_values)
                    consistency = (1 - (np.std(team_values) / np.mean(team_values))) * 100 if np.mean(team_values) > 0 else 0
                    
                    # Determine source performance category
                    if avg_value >= threshold_80:
                        source_idx = perf_indices["Elite Performance"]
                    elif avg_value >= threshold_60:
                        source_idx = perf_indices["Strong Performance"]
                    elif avg_value >= threshold_40:
                        source_idx = perf_indices["Solid Performance"]
                    else:
                        source_idx = perf_indices["Developing Performance"]
                    
                    # Determine impact category
                    if avg_value >= threshold_80 and consistency >= 70:
                        target_idx = impact_indices["High Impact"]
                        color = "rgba(139, 195, 74, 0.8)"  # Light Green
                    elif avg_value >= threshold_60 and consistency >= 50:
                        target_idx = impact_indices["Consistent Contributor"]
                        color = "rgba(255, 235, 59, 0.8)"  # Yellow
                    elif avg_value >= threshold_40:
                        target_idx = impact_indices["Steady Player"]
                        color = "rgba(255, 183, 77, 0.8)"  # Light Orange
                    else:
                        target_idx = impact_indices["Growth Focus"]
                        color = "rgba(239, 154, 154, 0.8)"  # Light Red
                    
                    flow_value = avg_value * len(team_values)
                    
                    sankey_links.append({
                        'source': source_idx,
                        'target': target_idx,
                        'value': flow_value,
                        'color': color
                    })
            
            # Create node colors
            node_colors = []
            for i, node in enumerate(sankey_nodes):
                if i < perf_layer_start:  # Teams
                    node_colors.append("rgba(33, 150, 243, 0.9)")  # Blue
                elif i < impact_layer_start:  # Performance
                    node_colors.append("rgba(156, 39, 176, 0.9)")  # Purple
                else:  # Impact
                    node_colors.append("rgba(0, 150, 136, 0.9)")  # Teal
            
            title_text = f"Enhanced Team {metric.replace('_', ' ').title()} Performance Analysis"
            subtitle_text = "Teams → Performance Categories → Impact Assessment"
            height = 650
            
        else:
            # Enhanced match-by-match Sankey
            # Layer 1: Teams
            teams_layer_start = 0
            team_indices = {}
            for i, team_number in enumerate(team_data.keys()):
                team_name = f"Team {team_number}"
                sankey_nodes.append(team_name)
                team_indices[team_number] = i
            
            # Layer 2: Match Performance Categories
            perf_layer_start = len(sankey_nodes)
            match_categories = ["Dominant Matches", "Strong Matches", "Average Matches", "Weak Matches"]
            perf_indices = {}
            for i, category in enumerate(match_categories):
                sankey_nodes.append(category)
                perf_indices[category] = perf_layer_start + i
            
            # Layer 3: Consistency Categories
            consistency_layer_start = len(sankey_nodes)
            consistency_categories = ["Highly Consistent", "Generally Reliable", "Somewhat Variable", "Highly Variable"]
            consistency_indices = {}
            for i, category in enumerate(consistency_categories):
                sankey_nodes.append(category)
                consistency_indices[category] = consistency_layer_start + i
            
            # Calculate thresholds
            threshold_85 = np.percentile(all_values, 85)
            threshold_65 = np.percentile(all_values, 65)
            threshold_35 = np.percentile(all_values, 35)
            
            # Teams -> Match Performance
            for team_number, data in team_data.items():
                team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
                team_idx = team_indices[team_number]
                
                if team_values:
                    # Categorize matches
                    dominant_matches = [v for v in team_values if v >= threshold_85]
                    strong_matches = [v for v in team_values if threshold_65 <= v < threshold_85]
                    average_matches = [v for v in team_values if threshold_35 <= v < threshold_65]
                    weak_matches = [v for v in team_values if v < threshold_35]
                    
                    categories_data = [
                        (dominant_matches, "Dominant Matches", "rgba(76, 175, 80, 0.7)"),
                        (strong_matches, "Strong Matches", "rgba(255, 193, 7, 0.7)"),
                        (average_matches, "Average Matches", "rgba(255, 152, 0, 0.7)"),
                        (weak_matches, "Weak Matches", "rgba(244, 67, 54, 0.7)")
                    ]
                    
                    for matches, category, color in categories_data:
                        if matches:
                            total_value = sum(matches)
                            target_idx = perf_indices[category]
                            
                            sankey_links.append({
                                'source': team_idx,
                                'target': target_idx,
                                'value': total_value,
                                'color': color
                            })
            
            # Match Performance -> Consistency
            for team_number, data in team_data.items():
                team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
                
                if len(team_values) > 2:
                    avg_value = np.mean(team_values)
                    std_value = np.std(team_values)
                    consistency = (1 - (std_value / avg_value)) * 100 if avg_value > 0 else 0
                    
                    # Determine primary performance category
                    dominant_total = sum(v for v in team_values if v >= threshold_85)
                    strong_total = sum(v for v in team_values if threshold_65 <= v < threshold_85)
                    average_total = sum(v for v in team_values if threshold_35 <= v < threshold_65)
                    weak_total = sum(v for v in team_values if v < threshold_35)
                    
                    primary_category = max(
                        [(dominant_total, "Dominant Matches"), (strong_total, "Strong Matches"),
                         (average_total, "Average Matches"), (weak_total, "Weak Matches")],
                        key=lambda x: x[0]
                    )
                    
                    if primary_category[0] > 0:
                        source_idx = perf_indices[primary_category[1]]
                        
                        # Determine consistency category
                        if consistency >= 75:
                            target_idx = consistency_indices["Highly Consistent"]
                            color = "rgba(139, 195, 74, 0.8)"
                        elif consistency >= 50:
                            target_idx = consistency_indices["Generally Reliable"] 
                            color = "rgba(255, 235, 59, 0.8)"
                        elif consistency >= 25:
                            target_idx = consistency_indices["Somewhat Variable"]
                            color = "rgba(255, 183, 77, 0.8)"
                        else:
                            target_idx = consistency_indices["Highly Variable"]
                            color = "rgba(239, 154, 154, 0.8)"
                        
                        sankey_links.append({
                            'source': source_idx,
                            'target': target_idx,
                            'value': primary_category[0],
                            'color': color
                        })
            
            # Create node colors
            node_colors = []
            for i, node in enumerate(sankey_nodes):
                if i < perf_layer_start:  # Teams
                    node_colors.append("rgba(33, 150, 243, 0.9)")  # Blue
                elif i < consistency_layer_start:  # Performance
                    node_colors.append("rgba(156, 39, 176, 0.9)")  # Purple
                else:  # Consistency
                    node_colors.append("rgba(0, 150, 136, 0.9)")  # Teal
            
            title_text = f"Enhanced Match-by-Match {metric.replace('_', ' ').title()} Analysis"
            subtitle_text = "Teams → Match Performance → Consistency Analysis"
            height = 700
        
        if sankey_nodes and sankey_links:
            # cap height to avoid overflowing page/card, still allow reasonable size
            max_height = 700
            height = min(height if 'height' in locals() else 650, max_height)

            fig = go.Figure(data=[go.Sankey(
                node = dict(
                    pad = 25,
                    thickness = 30,
                    line = dict(color = "rgba(0,0,0,0.4)", width = 1.5),
                    label = sankey_nodes,
                    color = node_colors,
                    hovertemplate='<b>%{label}</b><br>Total Flow: %{value:.1f}<extra></extra>'
                ),
                link = dict(
                    source = [link['source'] for link in sankey_links],
                    target = [link['target'] for link in sankey_links],
                    value = [link['value'] for link in sankey_links],
                    color = [link['color'] for link in sankey_links],
                    hovertemplate='<b>%{source.label}</b> → <b>%{target.label}</b><br>Flow: %{value:.1f}<extra></extra>'
                )
            )])
            theme_vals = _chart_theme()
            fig.update_layout(
                title=title_text,
                margin=dict(l=30, r=30, t=70, b=50),
                plot_bgcolor=theme_vals['plot_bg'],
                paper_bgcolor=theme_vals['paper_bg'],
                font=dict(family="Arial, sans-serif", size=12, color=theme_vals['text_main']),
                height=height,
                autosize=True,
                annotations=[
                    dict(
                        text=subtitle_text,
                        showarrow=False,
                        xref="paper", yref="paper",
                        x=0.5, y=1.02, xanchor='center', yanchor='bottom',
                        font=dict(size=13, color=theme_vals['text_muted'])
                    )
                ]
            )
            plots[f'{metric}_sankey'] = pio.to_json(fig)
    
    return plots

def _create_heatmap_chart(team_data, metric, data_view):
    """Create a heatmap for the given team data and metric"""
    plots = {}
    
    if data_view == 'matches' and len(team_data) > 1:
        # Team vs Match heatmap
        teams = list(team_data.keys())
        all_matches = set()
        
        # Get all match numbers
        for data in team_data.values():
            for match in data['matches']:
                all_matches.add(match['match_number'])
        
        sorted_matches = sorted(all_matches)
        
        # Create matrix
        z_data = []
        for team_number in teams:
            team_row = []
            for match_num in sorted_matches:
                # Find value for this team and match
                value = None
                for match in team_data[team_number]['matches']:
                    if match['match_number'] == match_num:
                        value = match['metric_value']
                        break
                team_row.append(value if value is not None else 0)
            z_data.append(team_row)
        
        if z_data:
            fig = go.Figure(data=go.Heatmap(
                z=z_data,
                x=[f"Match {m}" for m in sorted_matches],
                y=[f"Team {t}" for t in teams],
                colorscale='Viridis',
                hovertemplate=f'%{{y}} - %{{x}}<br>{metric.replace("_", " ").title()}: %{{z:.2f}}<extra></extra>'
            ))
            
            fig.update_layout(
                title=f"Team {metric.replace('_', ' ').title()} Performance (Heatmap)",
                xaxis_title="Matches",
                yaxis_title="Teams",
                margin=dict(l=40, r=20, t=50, b=60)
            )
            plots[f'{metric}_heatmap'] = pio.to_json(fig)
    
    return plots

def _create_bubble_chart(team_data, metric, data_view):
    """Create a bubble chart for the given team data and metric"""
    plots = {}
    
    if data_view == 'matches':
        fig = go.Figure()
        for team_number, data in team_data.items():
            if data['matches']:
                match_numbers = [m['match_number'] for m in data['matches']]
                values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
                sizes = [abs(v) + 5 for v in values]  # Bubble size based on absolute value
                
                fig.add_trace(go.Scatter(
                    x=match_numbers,
                    y=values,
                    mode='markers',
                    name=f"Team {team_number}",
                    marker=dict(
                        size=sizes,
                        sizemode='diameter',
                        sizeref=2.*max(sizes)/(40.**2),
                        sizemin=4
                    ),
                    hovertemplate=f'Team %{{fullData.name}}<br>Match %{{x}}: %{{y:.2f}}<extra></extra>'
                ))
        
        theme_vals = _chart_theme()
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} by Match (Bubble Chart)",
            xaxis_title="Match Number",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            font=dict(color=theme_vals['text_main'])
        )
        plots[f'{metric}_bubble'] = pio.to_json(fig)
    
    return plots

def _create_area_chart(team_data, metric, data_view):
    """Create an area chart for the given team data and metric"""
    plots = {}
    
    if data_view == 'matches':
        fig = go.Figure()
        for team_number, data in team_data.items():
            if data['matches']:
                # Sort by match number
                sorted_matches = sorted(data['matches'], key=lambda x: x['match_number'])
                match_numbers = [m['match_number'] for m in sorted_matches]
                values = [m['metric_value'] for m in sorted_matches if m['metric_value'] is not None]
                
                # Calculate cumulative values
                import numpy as np
                cumulative_values = np.cumsum(values)
                
                fig.add_trace(go.Scatter(
                    x=match_numbers,
                    y=cumulative_values,
                    mode='lines',
                    name=f"Team {team_number}",
                    fill='tonexty' if len(fig.data) > 0 else 'tozeroy',
                    hovertemplate=f'<b>Team %{{fullData.name}}</b><br>Match %{{x}}: %{{y:.2f}} cumulative<extra></extra>'
                ))
        
        theme_vals = _chart_theme()
        fig.update_layout(
            title=f"Cumulative {metric.replace('_', ' ').title()} Over Matches (Area Chart)",
            xaxis_title="Match Number",
            yaxis_title=f"Cumulative {metric.replace('_', ' ').title()}",
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            font=dict(color=theme_vals['text_main'])
        )
        plots[f'{metric}_area'] = pio.to_json(fig)
    
    return plots

def _create_radar_chart(team_data, metric, data_view):
    """Create a radar chart for the given team data and metric"""
    plots = {}

    # Build radar-friendly summary series for each team (allow 2+ teams to render)
    import numpy as np

    radar_metrics = ['Average', 'Total', 'Consistency', 'Peak Performance']
    team_series = {}
    all_totals = []
    all_averages = []
    all_peaks = []

    for team_number, data in team_data.items():
        vals = [m['metric_value'] for m in data['matches'] if m.get('metric_value') is not None]
        if vals:
            total = sum(vals)
            avg = total / len(vals)
            peak = max(vals)
            # If only one datapoint, treat consistency as high (can't compute stddev reliably)
            if len(vals) > 1 and np.mean(vals) > 0:
                consistency = max(0, min(100, 100 - (np.std(vals) / np.mean(vals) * 100)))
            else:
                consistency = 100.0

            team_series[team_number] = {
                'avg': avg,
                'total': total,
                'consistency': consistency,
                'peak': peak
            }
            all_totals.append(total)
            all_averages.append(avg)
            all_peaks.append(peak)

    # Require at least 2 teams with data to render a useful radar chart
    if len(team_series) >= 2:
        max_total = max(all_totals) if all_totals else 1
        max_avg = max(all_averages) if all_averages else 1
        max_peak = max(all_peaks) if all_peaks else 1

        fig = go.Figure()

        for team_number, series in team_series.items():
            normalized = [
                (series['avg'] / max_avg * 100) if max_avg > 0 else 0,
                (series['total'] / max_total * 100) if max_total > 0 else 0,
                max(0, min(100, series['consistency'])),
                (series['peak'] / max_peak * 100) if max_peak > 0 else 0
            ]

            fig.add_trace(go.Scatterpolar(
                r=normalized + [normalized[0]],
                theta=radar_metrics + [radar_metrics[0]],
                fill='toself',
                name=f"Team {team_number}",
                hovertemplate=f'<b>Team %{{fullData.name}}</b><br>%{{theta}}: %{{r:.1f}}<extra></extra>'
            ))

        # Height and layout
        base_height = 380
        extra_per_team = 16
        calculated_height = base_height + len(team_series) * extra_per_team
        height = min(calculated_height, 520)

        theme_vals = _chart_theme()

        fig.update_layout(
            polar=dict(
                radialaxis=dict(range=[0, 100], tickfont=dict(color=theme_vals['text_main']), gridcolor=theme_vals['grid_color']),
                angularaxis=dict(tickfont=dict(color=theme_vals['text_main']))
            ),
            showlegend=True,
            title=f"Team {metric.replace('_', ' ').title()} Performance Comparison (Radar)",
            margin=dict(l=20, r=20, t=60, b=40),
            height=height,
            autosize=True,
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            font=dict(color=theme_vals['text_main']),
            legend=dict(orientation='h', yanchor='bottom', y=-0.12, xanchor='center', x=0.5)
        )

        plots[f'{metric}_radar'] = pio.to_json(fig)
    else:
        # Not enough data; return an info figure so the card displays a message
        theme_vals = _chart_theme()
        fig_info = go.Figure()
        fig_info.add_annotation(
            text="Not enough data for Radar chart. Select at least 2 teams with match data.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color=theme_vals['text_muted'])
        )
        fig_info.update_layout(
            title=f"Team {metric.replace('_', ' ').title()} Performance Comparison (Radar)",
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            margin=dict(l=20, r=20, t=50, b=40),
            plot_bgcolor=theme_vals['plot_bg'],
            paper_bgcolor=theme_vals['paper_bg'],
            height=220,
            font=dict(color=theme_vals['text_main'])
        )
        plots[f'{metric}_radar'] = pio.to_json(fig_info)

    return plots