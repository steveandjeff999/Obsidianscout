from flask import Blueprint, render_template, current_app, request
from flask_login import login_required
from app.routes.auth import analytics_required
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd
import json
import plotly
import sys
from app.models import Team, Match, ScoutingData, Event
from app.utils.analysis import calculate_team_metrics
from app.utils.theme_manager import ThemeManager

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('graphs', __name__, url_prefix='/graphs')

@bp.route('/')
@analytics_required
def index():
    """Graphs dashboard page"""
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    # Get all teams and events for selection dropdowns
    # For graphs, we want to show all teams but prioritize current event teams
    if current_event:
        current_event_teams = list(current_event.teams)
        other_teams = Team.query.filter(~Team.id.in_([t.id for t in current_event_teams])).order_by(Team.team_number).all()
        all_teams = current_event_teams + other_teams
    else:
        all_teams = Team.query.order_by(Team.team_number).all()
    
    all_events = Event.query.all()
    
    # Calculate team metrics for sorting
    team_metrics = {}
    for team in all_teams:
        # Get metrics for the team - function only takes team_id
        metrics = calculate_team_metrics(team.id)
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
    
    print(f"Selected teams: {selected_team_numbers}")
    print(f"Selected event ID: {selected_event_id}")
    print(f"Selected metric: {selected_metric}")
    
    # Create sample demonstration graphs
    plots = {}
    
    # Only create graphs if teams are selected
    if selected_team_numbers:
        # Get scouting data for selected teams
        teams = Team.query.filter(Team.team_number.in_(selected_team_numbers)).all()
        print(f"Found {len(teams)} teams")
        
        if selected_event_id:
            # Get matches from selected event
            matches = Match.query.filter_by(event_id=selected_event_id).all()
            match_ids = [match.id for match in matches]
            
            # Filter scouting data for these matches and teams
            team_ids = [team.id for team in teams]
            scouting_data = ScoutingData.query.filter(
                ScoutingData.team_id.in_(team_ids),
                ScoutingData.match_id.in_(match_ids)
            ).all()
            print(f"Found {len(scouting_data)} scouting records for selected teams at event {selected_event_id}")
        else:
            # Get all scouting data for selected teams
            team_ids = [team.id for team in teams]
            scouting_data = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids)).all()
            print(f"Found {len(scouting_data)} scouting records for selected teams across all events")
        
        # If we have data, generate graphs
        if teams and scouting_data:
            # Create team performance graphs
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
                match_metrics = {}
                key_metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
                for metric in key_metrics:
                    if 'formula' in metric:
                        try:
                            metric_id = metric['id']
                            formula = metric['formula']
                            value = data.calculate_metric(formula)
                            match_metrics[metric_id] = {
                                'match_number': match.match_number,
                                'metric_id': metric_id,
                                'metric_name': metric['name'],
                                'value': value
                            }
                        except Exception as e:
                            match_metrics[metric_id] = {
                                'match_number': match.match_number,
                                'metric_id': metric_id,
                                'metric_name': metric['name'],
                                'value': None
                            }
                team_data[team.team_number]['matches'].append({
                    'match_number': match.match_number,
                    'metrics': match_metrics
                })

            # --- Enhanced: Generate multiple graph types for all metrics ---
            import numpy as np
            metric_ids = [m['id'] for m in key_metrics if 'formula' in m]
            metric_names = {m['id']: m['name'] for m in key_metrics if 'formula' in m}
            # Prepare data for radar chart (if 3+ metrics)
            radar_ready = len(metric_ids) >= 3
            radar_data = {}
            
            # Handle special 'points' metric selection
            if selected_metric == 'points':
                points_data = []
                for team in teams:
                    team_number = team.team_number
                    team_name = team.team_name
                    points = team_metrics.get(team_number, {}).get('total_points', 0)
                    points_data.append({
                        'team': f"{team_number} - {team_name}",
                        'points': points
                    })
                if points_data:
                    points_data = sorted(points_data, key=lambda x: x['points'], reverse=True)
                    fig_points = go.Figure()
                    fig_points.add_trace(go.Bar(
                        x=[d['team'] for d in points_data],
                        y=[d['points'] for d in points_data],
                        marker_color='gold',
                        hovertemplate='<b>%{x}</b><br>Total Points: %{y:.2f}<extra></extra>'
                    ))
                    fig_points.update_layout(
                        title="Total Points by Team (from team_metrics)",
                        xaxis_title="Team",
                        yaxis_title="Total Points",
                        margin=dict(l=40, r=20, t=50, b=60),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font=dict(family="Arial, sans-serif"),
                        xaxis=dict(tickangle=-45)
                    )
                    plots['team_comparison'] = pio.to_json(fig_points)
            else:
                # For each metric, generate bar, line, and box plots
                for metric_id in metric_ids:
                    metric_name = metric_names[metric_id]
                    # Collect per-team, per-match values
                    team_match_values = {team_number: [] for team_number in team_data}
                    for team_number, tdata in team_data.items():
                        for match in tdata['matches']:
                            value = match['metrics'].get(metric_id, {}).get('value')
                            if value is not None:
                                team_match_values[team_number].append(value)
                    # --- Bar Chart: Average per team ---
                    avg_data = []
                    for team_number, values in team_match_values.items():
                        if values:
                            avg_value = sum(values) / len(values)
                            avg_data.append({
                                'team': f"{team_number} - {team_data[team_number]['team_name']}",
                                'value': avg_value
                            })
                            if radar_ready:
                                if team_number not in radar_data:
                                    radar_data[team_number] = {}
                                radar_data[team_number][metric_id] = avg_value
                    if avg_data:
                        avg_data = sorted(avg_data, key=lambda x: x['value'], reverse=True)
                        fig_bar = go.Figure()
                        fig_bar.add_trace(go.Bar(
                            x=[d['team'] for d in avg_data],
                            y=[d['value'] for d in avg_data],
                            marker_color='rgb(55, 83, 109)',
                            hovertemplate='<b>%{x}</b><br>Avg: %{y:.2f}<extra></extra>'
                        ))
                        fig_bar.update_layout(
                            title=f"Average {metric_name} by Team",
                            xaxis_title="Team",
                            yaxis_title=f"Average {metric_name}",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif"),
                            xaxis=dict(tickangle=-45)
                        )
                        plots[f'{metric_id}_bar'] = pio.to_json(fig_bar)
                    # --- Line Chart: Value per match (trend) ---
                    fig_line = go.Figure()
                    for team_number, values in team_match_values.items():
                        if values:
                            match_numbers = [m['match_number'] for m in team_data[team_number]['matches'] if m['metrics'].get(metric_id, {}).get('value') is not None]
                            fig_line.add_trace(go.Scatter(
                                x=match_numbers,
                                y=values,
                                mode='lines+markers',
                                name=f"{team_number}",
                                hovertemplate='Match %{x}: %{y:.2f}'
                            ))
                    fig_line.update_layout(
                        title=f"{metric_name} Trend by Match",
                        xaxis_title="Match Number",
                        yaxis_title=metric_name,
                        margin=dict(l=40, r=20, t=50, b=60),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font=dict(family="Arial, sans-serif")
                    )
                    plots[f'{metric_id}_line'] = pio.to_json(fig_line)
                    # --- Box Plot: Distribution per team ---
                    fig_box = go.Figure()
                    for team_number, values in team_match_values.items():
                        if values and len(values) > 1:
                            fig_box.add_trace(go.Box(
                                y=values,
                                name=f"{team_number}",
                                boxmean=True,
                                marker_color='rgb(26, 118, 255)',
                                hovertemplate='Team %{name}<br>Value: %{y:.2f}'
                            ))
                    fig_box.update_layout(
                        title=f"{metric_name} Distribution by Team (Box Plot)",
                        yaxis_title=metric_name,
                        margin=dict(l=40, r=20, t=50, b=60),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font=dict(family="Arial, sans-serif")
                    )
                    plots[f'{metric_id}_box'] = pio.to_json(fig_box)
                # --- Radar Chart: Team profiles (if 3+ metrics) ---
                if radar_ready and len(radar_data) > 0:
                    fig_radar = go.Figure()
                    categories = [metric_names[mid] for mid in metric_ids]
                    for team_number, metrics in radar_data.items():
                        values = [metrics.get(mid, 0) for mid in metric_ids]
                        fig_radar.add_trace(go.Scatterpolar(
                            r=values + [values[0]],
                            theta=categories + [categories[0]],
                            fill='toself',
                            name=f"{team_number} - {team_data[team_number]['team_name']}"
                        ))
                    fig_radar.update_layout(
                        polar=dict(
                            radialaxis=dict(visible=True)
                        ),
                        showlegend=True,
                        title="Team Metric Profiles (Radar Chart)",
                        margin=dict(l=40, r=20, t=50, b=60),
                        font=dict(family="Arial, sans-serif")
                    )
                    plots['team_radar'] = pio.to_json(fig_radar)
    
    # After generating all metric plots, add a special 'points' bar chart using team_metrics
    if selected_team_numbers and team_metrics:
        points_data = []
        for team in teams:
            team_number = team.team_number
            team_name = team.team_name
            points = team_metrics.get(team_number, {}).get('total_points', 0)
            points_data.append({
                'team': f"{team_number} - {team_name}",
                'points': points
            })
        if points_data:
            points_data = sorted(points_data, key=lambda x: x['points'], reverse=True)
            fig_points = go.Figure()
            fig_points.add_trace(go.Bar(
                x=[d['team'] for d in points_data],
                y=[d['points'] for d in points_data],
                marker_color='gold',
                hovertemplate='<b>%{x}</b><br>Total Points: %{y:.2f}<extra></extra>'
            ))
            fig_points.update_layout(
                title="Total Points by Team (from team_metrics)",
                xaxis_title="Team",
                yaxis_title="Total Points",
                margin=dict(l=40, r=20, t=50, b=60),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(family="Arial, sans-serif"),
                xaxis=dict(tickangle=-45)
            )
            plots['points_bar'] = pio.to_json(fig_points)
    
    return render_template('graphs/index.html', 
                          plots=plots,
                          game_config=game_config,
                          all_teams=all_teams,
                          all_teams_json=all_teams_json,
                          all_events=all_events,
                          selected_team_numbers=selected_team_numbers,
                          selected_event_id=selected_event_id,
                          selected_metric=selected_metric,
                          team_event_mapping=team_event_mapping,
                          team_metrics=team_metrics,
                          **get_theme_context())

@bp.route('/side-by-side')
@analytics_required
def side_by_side():
    """Side-by-side team comparison page"""
    team_numbers = request.args.getlist('teams', type=int)
    
    if not team_numbers:
        # Get game configuration
        game_config = current_app.config['GAME_CONFIG']
        
        # Get current event based on configuration
        current_event_code = game_config.get('current_event_code')
        current_event = None
        if current_event_code:
            current_event = Event.query.filter_by(code=current_event_code).first()
        
        # Get teams filtered by the current event if available, otherwise show all teams
        if current_event:
            teams = current_event.teams
        else:
            teams = Team.query.order_by(Team.team_number).all()
        
        metrics = game_config['data_analysis']['key_metrics']
        return render_template('graphs/side_by_side_form.html', teams=teams, metrics=metrics, **get_theme_context())
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Get teams
    teams = Team.query.filter(Team.team_number.in_(team_numbers)).all()
    
    # Calculate detailed metrics for each team
    teams_data = []
    
    for team in teams:
        scouting_data = ScoutingData.query.filter_by(team_id=team.id).all()
        
        team_info = {
            'team': team,
            'metrics': {},
            'match_count': len(scouting_data),
            'has_data': len(scouting_data) > 0
        }
        
        if scouting_data:
            # Calculate each metric
            for metric in game_config['data_analysis']['key_metrics']:
                metric_id = metric['id']
                match_values = []
                
                for data in scouting_data:
                    try:
                        value = data.calculate_metric(metric_id)
                        match_values.append({
                            'match': data.match.match_number,
                            'value': value
                        })
                    except Exception as e:
                        print(f"Error calculating metric {metric_id} for team {team.team_number}: {e}")
                
                if match_values:
                    values = [x['value'] for x in match_values]
                    
                    # Calculate aggregate based on metric configuration
                    if metric.get('aggregate') == 'average':
                        aggregate_value = sum(values) / len(values)
                    elif metric.get('aggregate') == 'percentage':
                        aggregate_value = (sum(values) / len(values)) * 100
                    else:
                        aggregate_value = sum(values)
                    
                    team_info['metrics'][metric_id] = {
                        'config': metric,
                        'aggregate': aggregate_value,
                        'match_data': values,
                        'match_values': match_values,
                        'min': min(values),
                        'max': max(values),
                        'avg': sum(values) / len(values)
                    }
                else:
                    team_info['metrics'][metric_id] = {
                        'config': metric,
                        'aggregate': 0,
                        'match_data': [],
                        'match_values': [],
                        'min': 0,
                        'max': 0,
                        'avg': 0
                    }
        else:
            # No data for this team
            for metric in game_config['data_analysis']['key_metrics']:
                team_info['metrics'][metric['id']] = {
                    'config': metric,
                    'aggregate': 0,
                    'match_data': [],
                    'match_values': [],
                    'min': 0,
                    'max': 0,
                    'avg': 0
                }
        
        teams_data.append(team_info)
    
    return render_template('graphs/side_by_side.html',
                         teams_data=teams_data,
                         game_config=game_config,
                         **get_theme_context())