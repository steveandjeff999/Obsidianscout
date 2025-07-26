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
import numpy as np
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
    selected_graph_types = request.args.getlist('graph_types')
    selected_data_view = request.args.get('data_view', 'averages')
    
    # Default to points if no metric selected
    if not selected_metric:
        selected_metric = 'points'
    
    # If points is selected but not available in dropdown, we'll still process it
    # since it's our default metric
    
    # Default to line and bar graphs if none selected
    if not selected_graph_types:
        selected_graph_types = ['bar', 'line']
    
    print(f"Selected teams: {selected_team_numbers}")
    print(f"Selected event ID: {selected_event_id}")
    print(f"Selected metric: {selected_metric}")
    print(f"Selected graph types: {selected_graph_types}")
    print(f"Selected data view: {selected_data_view}")
    
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
                # Filter out unwanted metrics
                excluded_metrics = ['coral', 'algae', 'accuracy', 'matches_scouted', 'defence', 'caa', 'dr', 'ecp', 'tot']
                for metric in key_metrics:
                    if ('formula' in metric or metric.get('auto_generated', False)) and metric['id'] not in excluded_metrics:
                        try:
                            metric_id = metric['id']
                            formula = metric.get('formula', metric_id)  # Use metric_id for auto_generated
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
            # Filter out unwanted metrics
            excluded_metrics = ['coral', 'algae', 'accuracy', 'matches_scouted', 'defence', 'caa', 'dr', 'ecp', 'tot']
            metric_ids = [m['id'] for m in key_metrics if ('formula' in m or m.get('auto_generated', False)) and m['id'] not in excluded_metrics]
            metric_names = {m['id']: m['name'] for m in key_metrics if ('formula' in m or m.get('auto_generated', False)) and m['id'] not in excluded_metrics}
            # Prepare data for radar chart (if 3+ metrics)
            radar_ready = len(metric_ids) >= 3
            radar_data = {}
            
            # Define metric_name for all cases
            if selected_metric == 'points':
                metric_name = "Total Points"
            elif selected_metric in metric_names:
                metric_name = metric_names[selected_metric]
            else:
                metric_name = "Unknown Metric"
            
            # Handle special 'points' metric selection
            if selected_metric == 'points':
                if selected_data_view == 'averages':
                    # Use total points from team_metrics for averages view
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
                else:
                    # For match-by-match view, calculate points per match
                    team_match_points = {}
                    for team_number, tdata in team_data.items():
                        team_match_points[team_number] = []
                        for match in tdata['matches']:
                            # Calculate points for this match using the same logic as team_metrics
                            match_points = 0
                            for metric_id, metric_data in match['metrics'].items():
                                if metric_data.get('value') is not None:
                                    # Add the metric value to match points
                                    match_points += metric_data['value']
                            if match_points > 0:  # Only add if there are points
                                team_match_points[team_number].append({
                                    'match_number': match['match_number'],
                                    'points': match_points
                                })
                    
                    if 'bar' in selected_graph_types:
                        if selected_data_view == 'averages':
                            fig_points = go.Figure()
                            fig_points.add_trace(go.Bar(
                                x=[d['team'] for d in points_data],
                                y=[d['points'] for d in points_data],
                                marker_color='gold',
                                hovertemplate='<b>%{x}</b><br>Total Points: %{y:.2f}<extra></extra>'
                            ))
                            fig_points.update_layout(
                                title="Total Points by Team - Averages (Bar Chart)",
                                xaxis_title="Team",
                                yaxis_title="Total Points",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(
                                    tickangle=-45,
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        else:
                            # Match-by-match points bar chart
                            fig_points = go.Figure()
                            for team_number, match_points in team_match_points.items():
                                if match_points:
                                    match_numbers = [mp['match_number'] for mp in match_points]
                                    points_values = [mp['points'] for mp in match_points]
                                    fig_points.add_trace(go.Bar(
                                        x=match_numbers,
                                        y=points_values,
                                        name=f"Team {team_number}",
                                        hovertemplate='Team %{fullData.name}<br>Match %{x}: %{y:.2f} points<extra></extra>'
                                    ))
                            fig_points.update_layout(
                                title="Points per Match - All Teams (Bar Chart)",
                                xaxis_title="Match Number",
                                yaxis_title="Points",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                barmode='group',
                                xaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        plots['points_bar'] = pio.to_json(fig_points)
                    
                    if 'line' in selected_graph_types:
                        if selected_data_view == 'averages':
                            fig_points_line = go.Figure()
                            fig_points_line.add_trace(go.Scatter(
                                x=[d['team'] for d in points_data],
                                y=[d['points'] for d in points_data],
                                mode='lines+markers',
                                marker_color='gold',
                                hovertemplate='<b>%{x}</b><br>Total Points: %{y:.2f}<extra></extra>'
                            ))
                            fig_points_line.update_layout(
                                title="Total Points by Team - Averages (Line Chart)",
                                xaxis_title="Team",
                                yaxis_title="Total Points",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(
                                    tickangle=-45,
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        else:
                            # Match-by-match points line chart
                            fig_points_line = go.Figure()
                            for team_number, match_points in team_match_points.items():
                                if match_points:
                                    match_numbers = [mp['match_number'] for mp in match_points]
                                    points_values = [mp['points'] for mp in match_points]
                                    fig_points_line.add_trace(go.Scatter(
                                        x=match_numbers,
                                        y=points_values,
                                        mode='lines+markers',
                                        name=f"Team {team_number}",
                                        hovertemplate='Team %{fullData.name}<br>Match %{x}: %{y:.2f} points<extra></extra>'
                                    ))
                            fig_points_line.update_layout(
                                title="Points per Match - All Teams (Line Chart)",
                                xaxis_title="Match Number",
                                yaxis_title="Points",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        plots['points_line'] = pio.to_json(fig_points_line)
                    
                    # For points metric, we can also generate some additional graph types using the points data
                    if 'histogram' in selected_graph_types:
                        points_values = [d['points'] for d in points_data]
                        fig_hist = go.Figure()
                        fig_hist.add_trace(go.Histogram(
                            x=points_values,
                            nbinsx=20,
                            marker_color='gold',
                            hovertemplate='Points: %{x}<br>Count: %{y}<extra></extra>'
                        ))
                        fig_hist.update_layout(
                            title="Total Points Distribution (Histogram)",
                            xaxis_title="Total Points",
                            yaxis_title="Frequency",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif"),
                            xaxis=dict(
                                showgrid=True,
                                gridcolor='rgba(128,128,128,0.2)',
                                gridwidth=1
                            ),
                            yaxis=dict(
                                showgrid=True,
                                gridcolor='rgba(128,128,128,0.2)',
                                gridwidth=1
                            )
                        )
                        plots['points_histogram'] = pio.to_json(fig_hist)
                    
                    if 'violin' in selected_graph_types:
                        # For violin plot with points, we'll create a simple distribution
                        points_values = [d['points'] for d in points_data]
                        fig_violin = go.Figure()
                        fig_violin.add_trace(go.Violin(
                            y=points_values,
                            name="All Teams",
                            box_visible=True,
                            meanline_visible=True,
                            hovertemplate='Points: %{y:.2f}<extra></extra>'
                        ))
                        fig_violin.update_layout(
                            title="Total Points Distribution (Violin Plot)",
                            yaxis_title="Total Points",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif"),
                            yaxis=dict(
                                showgrid=True,
                                gridcolor='rgba(128,128,128,0.2)',
                                gridwidth=1
                            )
                        )
                        plots['points_violin'] = pio.to_json(fig_violin)
                    
                    # Add a note about incompatible graph types for points metric
                    incompatible_graphs = []
                    if 'heatmap' in selected_graph_types:
                        incompatible_graphs.append('Heatmap')
                    if 'bubble' in selected_graph_types:
                        incompatible_graphs.append('Bubble Chart')
                    if 'area' in selected_graph_types:
                        incompatible_graphs.append('Area Chart')
                    if 'radar' in selected_graph_types:
                        incompatible_graphs.append('Radar Chart')
                    
                    if incompatible_graphs:
                        # Create an info message plot
                        fig_info = go.Figure()
                        fig_info.add_annotation(
                            text=f"Note: {', '.join(incompatible_graphs)} not available for Total Points metric<br>as they require match-by-match data.",
                            xref="paper", yref="paper",
                            x=0.5, y=0.5,
                            showarrow=False,
                            font=dict(size=14, color="gray"),
                            bgcolor="lightyellow",
                            bordercolor="gray",
                            borderwidth=1
                        )
                        fig_info.update_layout(
                            title="Graph Type Information",
                            xaxis=dict(visible=False),
                            yaxis=dict(visible=False),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            margin=dict(l=40, r=20, t=50, b=60),
                            height=200
                        )
                        plots['points_info'] = pio.to_json(fig_info)
            else:
                # Only show the selected metric as the main graph
                if selected_metric in metric_ids:
                    metric_id = selected_metric
                    # Collect per-team, per-match values
                    team_match_values = {team_number: [] for team_number in team_data}
                    for team_number, tdata in team_data.items():
                        for match in tdata['matches']:
                            value = match['metrics'].get(metric_id, {}).get('value')
                            if value is not None:
                                team_match_values[team_number].append(value)
                    

                    # Generate selected graph types
                    if 'bar' in selected_graph_types:
                        if selected_data_view == 'averages':
                            # --- Bar Chart: Average per team ---
                            avg_data = []
                            for team_number, values in team_match_values.items():
                                avg = np.mean(values) if values else 0
                                avg_data.append({'team': team_number, 'avg': avg})
                            avg_data = sorted(avg_data, key=lambda x: x['avg'], reverse=True)
                            fig_bar = go.Figure()
                            fig_bar.add_trace(go.Bar(
                                x=[str(d['team']) for d in avg_data],
                                y=[d['avg'] for d in avg_data],
                                marker_color='royalblue',
                                hovertemplate='<b>Team %{x}</b><br>Average: %{y:.2f}<extra></extra>'
                            ))
                            fig_bar.update_layout(
                                title=f"{metric_name} by Team - Averages (Bar Chart)",
                                xaxis_title="Team",
                                yaxis_title=f"Average {metric_name}",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(
                                    tickangle=-45,
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        else:
                            # --- Bar Chart: Match-by-match data ---
                            fig_bar = go.Figure()
                            for team_number, values in team_match_values.items():
                                if values:
                                    # Get match numbers for this team's matches that have data
                                    match_numbers = []
                                    match_values = []
                                    for match in team_data[team_number]['matches']:
                                        value = match['metrics'].get(metric_id, {}).get('value')
                                        if value is not None:
                                            match_numbers.append(match['match_number'])
                                            match_values.append(value)
                                    
                                    fig_bar.add_trace(go.Bar(
                                        x=match_numbers,
                                        y=match_values,
                                        name=f"Team {team_number}",
                                        hovertemplate='Team %{fullData.name}<br>Match %{x}: %{y:.2f}<extra></extra>'
                                    ))
                            fig_bar.update_layout(
                                title=f"{metric_name} by Match - All Teams (Bar Chart)",
                                xaxis_title="Match Number",
                                yaxis_title=metric_name,
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                barmode='group',
                                xaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        plots[f'{metric_id}_bar'] = pio.to_json(fig_bar)
                    
                    if 'line' in selected_graph_types:
                        if selected_data_view == 'averages':
                            # --- Line Chart: Average per team (sorted) ---
                            avg_data = []
                            for team_number, values in team_match_values.items():
                                avg = np.mean(values) if values else 0
                                avg_data.append({'team': team_number, 'avg': avg})
                            avg_data = sorted(avg_data, key=lambda x: x['avg'], reverse=True)
                            
                            fig_line = go.Figure()
                            fig_line.add_trace(go.Scatter(
                                x=[str(d['team']) for d in avg_data],
                                y=[d['avg'] for d in avg_data],
                                mode='lines+markers',
                                marker_color='royalblue',
                                hovertemplate='<b>Team %{x}</b><br>Average: %{y:.2f}<extra></extra>'
                            ))
                            fig_line.update_layout(
                                title=f"{metric_name} by Team - Averages (Line Chart)",
                                xaxis_title="Team",
                                yaxis_title=f"Average {metric_name}",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(
                                    tickangle=-45,
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        else:
                            # --- Line Chart: Value per match (trend) ---
                            fig_line = go.Figure()
                            for team_number, values in team_match_values.items():
                                if values:
                                    # Get match numbers for this team's matches that have data
                                    match_numbers = []
                                    match_values = []
                                    for match in team_data[team_number]['matches']:
                                        value = match['metrics'].get(metric_id, {}).get('value')
                                        if value is not None:
                                            match_numbers.append(match['match_number'])
                                            match_values.append(value)
                                    
                                    fig_line.add_trace(go.Scatter(
                                        x=match_numbers,
                                        y=match_values,
                                        mode='lines+markers',
                                        name=f"Team {team_number}",
                                        hovertemplate='Team %{fullData.name}<br>Match %{x}: %{y:.2f}<extra></extra>'
                                    ))
                            fig_line.update_layout(
                                title=f"{metric_name} Trend by Match (Line Chart)",
                                xaxis_title="Match Number",
                                yaxis_title=metric_name,
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='rgba(128,128,128,0.2)',
                                    gridwidth=1
                                )
                            )
                        plots[f'{metric_id}_line'] = pio.to_json(fig_line)
                    
                    if 'box' in selected_graph_types:
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
                    
                    if 'scatter' in selected_graph_types:
                        # --- Scatter Plot: Match number vs value ---
                        fig_scatter = go.Figure()
                        for team_number, values in team_match_values.items():
                            if values:
                                match_numbers = [m['match_number'] for m in team_data[team_number]['matches'] if m['metrics'].get(metric_id, {}).get('value') is not None]
                                fig_scatter.add_trace(go.Scatter(
                                    x=match_numbers,
                                    y=values,
                                    mode='markers',
                                    name=f"{team_number}",
                                    hovertemplate='Team %{name}<br>Match %{x}: %{y:.2f}<extra></extra>'
                                ))
                        fig_scatter.update_layout(
                            title=f"{metric_name} by Match (Scatter Plot)",
                            xaxis_title="Match Number",
                            yaxis_title=metric_name,
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots[f'{metric_id}_scatter'] = pio.to_json(fig_scatter)
                    
                    if 'histogram' in selected_graph_types:
                        # --- Histogram: Distribution of all values ---
                        all_values = []
                        for values in team_match_values.values():
                            all_values.extend(values)
                        if all_values:
                            fig_hist = go.Figure()
                            fig_hist.add_trace(go.Histogram(
                                x=all_values,
                                nbinsx=20,
                                marker_color='lightblue',
                                hovertemplate='Value: %{x}<br>Count: %{y}<extra></extra>'
                            ))
                            fig_hist.update_layout(
                                title=f"{metric_name} Distribution (Histogram)",
                                xaxis_title=metric_name,
                                yaxis_title="Frequency",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif")
                            )
                            plots[f'{metric_id}_histogram'] = pio.to_json(fig_hist)
                    
                    if 'violin' in selected_graph_types:
                        # --- Violin Plot: Density distribution per team ---
                        fig_violin = go.Figure()
                        for team_number, values in team_match_values.items():
                            if values and len(values) > 1:
                                fig_violin.add_trace(go.Violin(
                                    y=values,
                                    name=f"{team_number}",
                                    box_visible=True,
                                    meanline_visible=True,
                                    hovertemplate='Team %{name}<br>Value: %{y:.2f}<extra></extra>'
                                ))
                        fig_violin.update_layout(
                            title=f"{metric_name} Density Distribution (Violin Plot)",
                            yaxis_title=metric_name,
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots[f'{metric_id}_violin'] = pio.to_json(fig_violin)
                    
                    if 'area' in selected_graph_types and selected_metric != 'points':
                        # --- Area Chart: Cumulative values over time ---
                        fig_area = go.Figure()
                        for team_number, values in team_match_values.items():
                            if values:
                                match_numbers = [m['match_number'] for m in team_data[team_number]['matches'] if m['metrics'].get(metric_id, {}).get('value') is not None]
                                cumulative_values = np.cumsum(values)
                                fig_area.add_trace(go.Scatter(
                                    x=match_numbers,
                                    y=cumulative_values,
                                    mode='lines',
                                    fill='tonexty',
                                    name=f"{team_number}",
                                    hovertemplate='Team %{name}<br>Match %{x}: Cumulative %{y:.2f}<extra></extra>'
                                ))
                        fig_area.update_layout(
                            title=f"{metric_name} Cumulative Values (Area Chart)",
                            xaxis_title="Match Number",
                            yaxis_title=f"Cumulative {metric_name}",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots[f'{metric_id}_area'] = pio.to_json(fig_area)
                # --- Radar Chart: Team profiles (if 3+ metrics) ---
                if 'radar' in selected_graph_types and radar_ready and len(radar_data) > 0 and selected_metric != 'points':
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
                
                # --- Heatmap: Team vs Match performance matrix ---
                if 'heatmap' in selected_graph_types and selected_metric != 'points':
                    # Create a matrix of team vs match performance
                    team_numbers = list(team_data.keys())
                    match_numbers = []
                    for tdata in team_data.values():
                        for match in tdata['matches']:
                            if match['match_number'] not in match_numbers:
                                match_numbers.append(match['match_number'])
                    match_numbers.sort()
                    
                    if team_numbers and match_numbers:
                        # Create the heatmap data
                        heatmap_data = []
                        for team_number in team_numbers:
                            row = []
                            for match_number in match_numbers:
                                # Find the value for this team and match
                                value = None
                                for match in team_data[team_number]['matches']:
                                    if match['match_number'] == match_number:
                                        value = match['metrics'].get(metric_id, {}).get('value')
                                        break
                                row.append(value if value is not None else 0)
                            heatmap_data.append(row)
                        
                        fig_heatmap = go.Figure(data=go.Heatmap(
                            z=heatmap_data,
                            x=match_numbers,
                            y=[str(t) for t in team_numbers],
                            colorscale='Viridis',
                            hovertemplate='Team %{y}<br>Match %{x}<br>Value: %{z:.2f}<extra></extra>'
                        ))
                        fig_heatmap.update_layout(
                            title=f"{metric_name} Performance Matrix (Heatmap)",
                            xaxis_title="Match Number",
                            yaxis_title="Team",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots[f'{metric_id}_heatmap'] = pio.to_json(fig_heatmap)
                
                # --- Bubble Chart: Team performance with size based on consistency ---
                if 'bubble' in selected_graph_types and selected_metric != 'points':
                    bubble_data = []
                    for team_number, values in team_match_values.items():
                        if values:
                            avg_value = np.mean(values)
                            std_value = np.std(values) if len(values) > 1 else 0
                            consistency = 1 / (1 + std_value) if std_value > 0 else 1  # Higher consistency = larger bubble
                            bubble_data.append({
                                'team': team_number,
                                'avg': avg_value,
                                'consistency': consistency,
                                'matches': len(values)
                            })
                    
                    if bubble_data:
                        fig_bubble = go.Figure()
                        fig_bubble.add_trace(go.Scatter(
                            x=[d['avg'] for d in bubble_data],
                            y=[d['consistency'] for d in bubble_data],
                            mode='markers',
                            marker=dict(
                                size=[d['matches'] * 10 for d in bubble_data],  # Size based on number of matches
                                color=[d['avg'] for d in bubble_data],
                                colorscale='Viridis',
                                showscale=True,
                                colorbar=dict(title=f"Avg {metric_name}")
                            ),
                            text=[f"Team {d['team']}<br>Avg: {d['avg']:.2f}<br>Matches: {d['matches']}" for d in bubble_data],
                            hovertemplate='%{text}<extra></extra>'
                        ))
                        fig_bubble.update_layout(
                            title=f"{metric_name} Performance vs Consistency (Bubble Chart)",
                            xaxis_title=f"Average {metric_name}",
                            yaxis_title="Consistency (1/StdDev)",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots[f'{metric_id}_bubble'] = pio.to_json(fig_bubble)
    

    
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