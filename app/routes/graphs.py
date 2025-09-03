from flask import Blueprint, render_template, current_app, request, jsonify, url_for, redirect, flash, abort
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd
import json
import plotly
import sys
import numpy as np
from datetime import datetime
from app.models import Team, Match, ScoutingData, Event, SharedGraph
from app import db
from app.utils.analysis import calculate_team_metrics
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_effective_game_config
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code
)
import os

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
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Get all teams and events for selection dropdowns
    # For graphs, we want to show all teams but prioritize current event teams
    if current_event:
        current_event_teams = list(filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all())
        other_teams = Team.query.filter(~Team.id.in_([t.id for t in current_event_teams])).order_by(Team.team_number).all()
        all_teams = current_event_teams + other_teams
    else:
        all_teams = Team.query.order_by(Team.team_number).all()
    
    all_events = filter_events_by_scouting_team().all()
    
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
    
    # Default to points if no metric selected or if metric is empty
    if not selected_metric or selected_metric.strip() == '':
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
            # Create team performance graphs
            team_data = {}
            
            # Get key metrics from game config (needed for both branches)
            key_metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
            
            # If we have scouting data, process it
            if scouting_data:
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
            else:
                # No scouting data, but we can still show points graphs using team_metrics
                print("No scouting data found, but generating points graphs from team_metrics")
                for team in teams:
                    team_data[team.team_number] = {
                        'team_name': team.team_name,
                        'matches': []
                    }

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
                # Initialize points_data for all cases
                points_data = []
                # Initialize team_match_points for all cases
                # Fixed UnboundLocalError by restructuring conditional blocks
                team_match_points = {}
                for team in teams:
                    team_number = team.team_number
                    team_name = team.team_name
                    points = team_metrics.get(team_number, {}).get('total_points', 0)
                    points_data.append({
                        'team': f"{team_number} - {team_name}",
                        'points': points
                    })
                    # Initialize empty list for each team
                    team_match_points[team_number] = []
                
                if points_data:
                    points_data = sorted(points_data, key=lambda x: x['points'], reverse=True)
                
                if selected_data_view == 'averages':
                    # points_data is already prepared above
                    pass
                else:
                    # For match-by-match view, calculate points per match
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
                    
                # Generate graphs for points metric
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
                
                if 'scatter' in selected_graph_types:
                        if selected_data_view == 'averages':
                            fig_points_scatter = go.Figure()
                            fig_points_scatter.add_trace(go.Scatter(
                                x=[d['team'] for d in points_data],
                                y=[d['points'] for d in points_data],
                                mode='markers',
                                marker=dict(size=12, color='gold'),
                                hovertemplate='<b>%{x}</b><br>Total Points: %{y:.2f}<extra></extra>'
                            ))
                            fig_points_scatter.update_layout(
                                title="Total Points by Team - Averages (Scatter Plot)",
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
                            plots['points_scatter'] = pio.to_json(fig_points_scatter)
                        else:
                            # Match-by-match points scatter plot
                            fig_points_scatter = go.Figure()
                            for team_number, match_points in team_match_points.items():
                                if match_points:
                                    match_numbers = [mp['match_number'] for mp in match_points]
                                    points_values = [mp['points'] for mp in match_points]
                                    fig_points_scatter.add_trace(go.Scatter(
                                        x=match_numbers,
                                        y=points_values,
                                        mode='markers',
                                        name=f"Team {team_number}",
                                        hovertemplate='Team %{fullData.name}<br>Match %{x}: %{y:.2f} points<extra></extra>'
                                    ))
                            fig_points_scatter.update_layout(
                                title="Points per Match - All Teams (Scatter Plot)",
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
                        plots['points_scatter'] = pio.to_json(fig_points_scatter)
                
                if 'box' in selected_graph_types:
                        if selected_data_view == 'averages':
                            # Box plot not available for averages view - show info message
                            fig_box_info = go.Figure()
                            fig_box_info.add_annotation(
                                text="Box Plot not available for averages view.<br>Switch to 'matches' view to see distribution data.",
                                xref="paper", yref="paper",
                                x=0.5, y=0.5,
                                xanchor='center', yanchor='middle',
                                showarrow=False,
                                font=dict(size=16, color='orange'),
                                bordercolor='orange',
                                borderwidth=1
                            )
                            fig_box_info.update_layout(
                                title="Box Plot - Information",
                                xaxis=dict(visible=False),
                                yaxis=dict(visible=False),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                margin=dict(l=40, r=20, t=50, b=60),
                                height=200
                            )
                            plots['points_box'] = pio.to_json(fig_box_info)
                        else:
                            # For box plot with points, show distribution by team
                            if team_match_points:
                                fig_box = go.Figure()
                                for team_number, match_points in team_match_points.items():
                                    if match_points and len(match_points) > 1:
                                        points_values = [mp['points'] for mp in match_points]
                                        fig_box.add_trace(go.Box(
                                            y=points_values,
                                            name=f"Team {team_number}",
                                            boxmean=True,
                                            marker_color='gold',
                                            hovertemplate='Team %{name}<br>Points: %{y:.2f}<extra></extra>'
                                        ))
                                fig_box.update_layout(
                                    title="Points Distribution by Team (Box Plot)",
                                    yaxis_title="Points",
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
                                plots['points_box'] = pio.to_json(fig_box)
                    
                if 'sunburst' in selected_graph_types:
                        # Create performance hierarchy for points
                        if points_data:
                            sunburst_data = []
                            points_values = [d['points'] for d in points_data]
                            
                            for team_data in points_data:
                                points = team_data['points']
                                if points >= np.percentile(points_values, 75):
                                    category = "High Scorers"
                                elif points >= np.percentile(points_values, 50):
                                    category = "Medium Scorers"  
                                elif points >= np.percentile(points_values, 25):
                                    category = "Low Scorers"
                                else:
                                    category = "Developing Teams"
                                    
                                sunburst_data.append({
                                    'ids': team_data['team'],
                                    'labels': team_data['team'],
                                    'parents': category,
                                    'values': points
                                })
                            
                            # Add category parents
                            categories = ["High Scorers", "Medium Scorers", "Low Scorers", "Developing Teams"]
                            for category in categories:
                                total_value = sum([d['values'] for d in sunburst_data if d.get('parents') == category])
                                if total_value > 0:
                                    sunburst_data.append({
                                        'ids': category,
                                        'labels': category,
                                        'parents': "",
                                        'values': total_value
                                    })
                            
                            fig_sunburst = go.Figure(go.Sunburst(
                                ids=[d['ids'] for d in sunburst_data],
                                labels=[d['labels'] for d in sunburst_data],
                                parents=[d['parents'] for d in sunburst_data],
                                values=[d['values'] for d in sunburst_data],
                                branchvalues="total",
                                hovertemplate='<b>%{label}</b><br>Points: %{value:.2f}<extra></extra>'
                            ))
                            fig_sunburst.update_layout(
                                title="Team Scoring Performance Hierarchy (Sunburst)",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif")
                            )
                            plots['points_sunburst'] = pio.to_json(fig_sunburst)
                    
                if 'treemap' in selected_graph_types:
                        # Create treemap for points
                        if points_data:
                            treemap_data = []
                            points_values = [d['points'] for d in points_data]
                            
                            for team_data in points_data:
                                points = team_data['points']
                                if points >= np.percentile(points_values, 75):
                                    category = "High Scorers"
                                elif points >= np.percentile(points_values, 50):
                                    category = "Medium Scorers"
                                elif points >= np.percentile(points_values, 25):
                                    category = "Low Scorers"
                                else:
                                    category = "Developing Teams"
                                    
                                treemap_data.append({
                                    'ids': team_data['team'],
                                    'labels': team_data['team'],
                                    'parents': category,
                                    'values': points
                                })
                            
                            # Add category parents
                            categories = ["High Scorers", "Medium Scorers", "Low Scorers", "Developing Teams"]
                            for category in categories:
                                total_value = sum([d['values'] for d in treemap_data if d.get('parents') == category])
                                if total_value > 0:
                                    treemap_data.append({
                                        'ids': category,
                                        'labels': category,
                                        'parents': "",
                                        'values': total_value
                                    })
                            
                            fig_treemap = go.Figure(go.Treemap(
                                ids=[d['ids'] for d in treemap_data],
                                labels=[d['labels'] for d in treemap_data],
                                parents=[d['parents'] for d in treemap_data],
                                values=[d['values'] for d in treemap_data],
                                branchvalues="total",
                                hovertemplate='<b>%{label}</b><br>Points: %{value:.2f}<extra></extra>'
                            ))
                            fig_treemap.update_layout(
                                title="Team Scoring Distribution (Treemap)",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif")
                            )
                            plots['points_treemap'] = pio.to_json(fig_treemap)
                
                # --- Waterfall Chart: Show contribution breakdown ---
                if 'waterfall' in selected_graph_types:
                    if points_data and team_match_points:
                        # Create waterfall chart showing team contributions to total event score
                        waterfall_data = []
                        cumulative = 0
                        
                        # Sort teams by points for better visualization
                        sorted_teams = sorted(points_data, key=lambda x: x['points'], reverse=True)[:10]  # Top 10 teams
                        
                        for i, team_data in enumerate(sorted_teams):
                            points = team_data['points']
                            waterfall_data.append({
                                'x': team_data['team'],
                                'y': points,
                                'measure': 'relative' if i > 0 else 'absolute',
                                'text': f"{points:.1f} pts"
                            })
                        
                        if waterfall_data:
                            fig_waterfall = go.Figure()
                            fig_waterfall.add_trace(go.Waterfall(
                                name="Team Contributions",
                                orientation="v",
                                measure=[d['measure'] for d in waterfall_data],
                                x=[d['x'] for d in waterfall_data],
                                textposition="outside",
                                text=[d['text'] for d in waterfall_data],
                                y=[d['y'] for d in waterfall_data],
                                connector={"line":{"color":"rgb(63, 63, 63)"}},
                                decreasing={"marker":{"color":"red"}},
                                increasing={"marker":{"color":"green"}},
                                totals={"marker":{"color":"blue"}}
                            ))
                            fig_waterfall.update_layout(
                                title="Team Points Contribution Breakdown (Waterfall)",
                                xaxis_title="Teams",
                                yaxis_title="Points Contribution",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(tickangle=-45)
                            )
                            plots['points_waterfall'] = pio.to_json(fig_waterfall)
                
                # --- Enhanced Sankey Diagram: Show comprehensive performance flow ---
                if 'sankey' in selected_graph_types:
                    if points_data and team_match_points:
                        # Create multi-layer Sankey diagram showing team -> performance -> results flow
                        sankey_nodes = []
                        sankey_links = []
                        
                        # Layer 1: Teams
                        teams_layer_start = 0
                        team_indices = {}
                        for i, team_data in enumerate(points_data):
                            team_name = team_data['team']
                            sankey_nodes.append(f"Team {team_name}")
                            team_indices[team_name] = i
                        
                        # Layer 2: Performance Categories
                        perf_layer_start = len(sankey_nodes)
                        performance_categories = ["Elite Performance", "Strong Performance", "Average Performance", "Developing Performance"]
                        perf_indices = {}
                        for i, category in enumerate(performance_categories):
                            sankey_nodes.append(category)
                            perf_indices[category] = perf_layer_start + i
                        
                        # Layer 3: Match Outcome Categories
                        outcome_layer_start = len(sankey_nodes)
                        outcome_categories = ["High Impact Matches", "Solid Contributions", "Standard Performance", "Growth Opportunities"]
                        outcome_indices = {}
                        for i, category in enumerate(outcome_categories):
                            sankey_nodes.append(category)
                            outcome_indices[category] = outcome_layer_start + i
                        
                        # Calculate performance metrics for categorization
                        points_values = [d['points'] for d in points_data]
                        perf_75 = np.percentile(points_values, 75)
                        perf_50 = np.percentile(points_values, 50)
                        perf_25 = np.percentile(points_values, 25)
                        
                        # Create links from Teams to Performance Categories
                        for team_data in points_data:
                            team_name = team_data['team']
                            points = team_data['points']
                            team_idx = team_indices[team_name]
                            
                            # Determine performance category and flow weight
                            if points >= perf_75:
                                target_idx = perf_indices["Elite Performance"]
                                color = "rgba(76, 175, 80, 0.6)"  # Green
                            elif points >= perf_50:
                                target_idx = perf_indices["Strong Performance"]
                                color = "rgba(255, 193, 7, 0.6)"  # Amber
                            elif points >= perf_25:
                                target_idx = perf_indices["Average Performance"]
                                color = "rgba(255, 152, 0, 0.6)"  # Orange
                            else:
                                target_idx = perf_indices["Developing Performance"]
                                color = "rgba(244, 67, 54, 0.6)"  # Red
                            
                            sankey_links.append({
                                'source': team_idx,
                                'target': target_idx,
                                'value': points,
                                'color': color
                            })
                        
                        # Create links from Performance Categories to Match Outcomes
                        # Get match-level data for outcome categorization
                        for team_name, match_points in team_match_points.items():
                            if match_points and team_name in [str(d['team']).replace('Team ', '') for d in points_data]:
                                team_points = next(d['points'] for d in points_data if str(d['team']).replace('Team ', '') == team_name)
                                match_values = [mp['points'] for mp in match_points]
                                
                                # Categorize based on consistency and peak performance
                                avg_match = np.mean(match_values) if match_values else 0
                                peak_match = max(match_values) if match_values else 0
                                consistency = (1 - (np.std(match_values) / np.mean(match_values))) * 100 if match_values and np.mean(match_values) > 0 else 0
                                
                                # Determine source performance category
                                if team_points >= perf_75:
                                    source_idx = perf_indices["Elite Performance"]
                                elif team_points >= perf_50:
                                    source_idx = perf_indices["Strong Performance"]
                                elif team_points >= perf_25:
                                    source_idx = perf_indices["Average Performance"]
                                else:
                                    source_idx = perf_indices["Developing Performance"]
                                
                                # Determine outcome based on match performance characteristics
                                if peak_match > perf_75 and consistency > 70:
                                    target_idx = outcome_indices["High Impact Matches"]
                                    color = "rgba(139, 195, 74, 0.7)"  # Light Green
                                elif avg_match > perf_50 and consistency > 50:
                                    target_idx = outcome_indices["Solid Contributions"] 
                                    color = "rgba(255, 235, 59, 0.7)"  # Yellow
                                elif avg_match > perf_25:
                                    target_idx = outcome_indices["Standard Performance"]
                                    color = "rgba(255, 183, 77, 0.7)"  # Light Orange
                                else:
                                    target_idx = outcome_indices["Growth Opportunities"]
                                    color = "rgba(239, 154, 154, 0.7)"  # Light Red
                                
                                # Flow value proportional to match performance
                                flow_value = avg_match * len(match_values)  # Total contribution
                                
                                sankey_links.append({
                                    'source': source_idx,
                                    'target': target_idx,
                                    'value': flow_value,
                                    'color': color
                                })
                        
                        # Create node colors based on their layer
                        node_colors = []
                        for i, node in enumerate(sankey_nodes):
                            if i < perf_layer_start:  # Teams layer
                                node_colors.append("rgba(33, 150, 243, 0.8)")  # Blue
                            elif i < outcome_layer_start:  # Performance layer  
                                node_colors.append("rgba(156, 39, 176, 0.8)")  # Purple
                            else:  # Outcome layer
                                node_colors.append("rgba(0, 150, 136, 0.8)")  # Teal
                        
                        if sankey_nodes and sankey_links:
                            fig_sankey = go.Figure(data=[go.Sankey(
                                node = dict(
                                    pad = 20,
                                    thickness = 25,
                                    line = dict(color = "rgba(0,0,0,0.3)", width = 1),
                                    label = sankey_nodes,
                                    color = node_colors,
                                    hovertemplate='<b>%{label}</b><br>Total Flow: %{value}<extra></extra>'
                                ),
                                link = dict(
                                    source = [link['source'] for link in sankey_links],
                                    target = [link['target'] for link in sankey_links],
                                    value = [link['value'] for link in sankey_links],
                                    color = [link['color'] for link in sankey_links],
                                    hovertemplate='<b>%{source.label}</b> → <b>%{target.label}</b><br>Flow: %{value:.1f}<extra></extra>'
                                )
                            )])
                            fig_sankey.update_layout(
                                title="Team Performance Flow Analysis (Enhanced Sankey Diagram)",
                                margin=dict(l=50, r=50, t=80, b=50),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif", size=11),
                                height=600,
                                annotations=[
                                    dict(
                                        text="Teams → Performance Categories → Match Outcomes",
                                        showarrow=False,
                                        xref="paper", yref="paper",
                                        x=0.5, y=1.02, xanchor='center', yanchor='bottom',
                                        font=dict(size=12, color='gray')
                                    )
                                ]
                            )
                            plots['points_sankey'] = pio.to_json(fig_sankey)
                
                # Add heatmap implementation for "averages" data view
                if selected_data_view == 'averages' and 'heatmap' in selected_graph_types:
                    if points_data and team_match_points:
                        # Create a team vs metrics heatmap for averages view
                        # Calculate different performance metrics for each team
                        team_metrics_data = []
                        metric_names = ['Total Points', 'Average Points', 'Consistency', 'Match Count', 'Peak Performance']
                        
                        for team_number, match_points in team_match_points.items():
                            if match_points:
                                points_values = [mp['points'] for mp in match_points]
                                total_points = sum(points_values)
                                avg_points = np.mean(points_values)
                                # Consistency: higher value = more consistent (100 - coefficient of variation)
                                consistency = 100 - (np.std(points_values) / np.mean(points_values) * 100) if np.mean(points_values) > 0 else 0
                                match_count = len(points_values)
                                peak_performance = max(points_values)
                                
                                team_metrics_data.append({
                                    'team': team_number,
                                    'metrics': [total_points, avg_points, max(0, consistency), match_count, peak_performance]
                                })
                        
                        if team_metrics_data:
                            # Normalize metrics to 0-100 scale for better heatmap visualization
                            normalized_data = []
                            for i, metric_name in enumerate(metric_names):
                                metric_values = [team['metrics'][i] for team in team_metrics_data]
                                max_val = max(metric_values) if metric_values else 1
                                min_val = min(metric_values) if metric_values else 0
                                range_val = max_val - min_val if max_val != min_val else 1
                                
                                for j, team in enumerate(team_metrics_data):
                                    if j >= len(normalized_data):
                                        normalized_data.append([])
                                    # Normalize to 0-100 scale
                                    normalized_val = ((team['metrics'][i] - min_val) / range_val) * 100
                                    normalized_data[j].append(normalized_val)
                            
                            # Create the heatmap
                            fig_heatmap = go.Figure(data=go.Heatmap(
                                z=normalized_data,
                                x=metric_names,
                                y=[f"Team {team['team']}" for team in team_metrics_data],
                                colorscale='RdYlBu_r',  # Red-Yellow-Blue reversed (red=high, blue=low)
                                hovertemplate='<b>%{y}</b><br>%{x}: %{z:.1f}<br>Normalized Score<extra></extra>',
                                colorbar=dict(title="Performance Score (0-100)")
                            ))
                            fig_heatmap.update_layout(
                                title="Team Performance Metrics Heatmap (Averages View)",
                                xaxis_title="Performance Metrics",
                                yaxis_title="Teams",
                                margin=dict(l=80, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                height=max(400, len(team_metrics_data) * 25 + 100)  # Dynamic height based on team count
                            )
                            plots['points_heatmap'] = pio.to_json(fig_heatmap)
                
                # Add match-by-match chart implementations for "matches" data view
                if selected_data_view == 'matches' and team_match_points:
                    # --- Heatmap: Team vs Match performance matrix ---
                    if 'heatmap' in selected_graph_types:
                        # Prepare data for heatmap
                        all_matches = set()
                        for team_number, match_points in team_match_points.items():
                            for mp in match_points:
                                all_matches.add(mp['match_number'])
                        
                        if all_matches:
                            all_matches = sorted(list(all_matches))
                            team_numbers = sorted(team_match_points.keys())
                            
                            # Create heatmap data matrix
                            heatmap_data = []
                            for team_number in team_numbers:
                                row = []
                                for match_number in all_matches:
                                    # Find points for this team in this match
                                    points = None
                                    for mp in team_match_points[team_number]:
                                        if mp['match_number'] == match_number:
                                            points = mp['points']
                                            break
                                    row.append(points if points is not None else 0)
                                heatmap_data.append(row)
                            
                            fig_heatmap = go.Figure(data=go.Heatmap(
                                z=heatmap_data,
                                x=[f"Match {m}" for m in all_matches],
                                y=[f"Team {t}" for t in team_numbers],
                                colorscale='Viridis',
                                hovertemplate='<b>%{y}</b><br>%{x}: %{z:.2f} points<extra></extra>'
                            ))
                            fig_heatmap.update_layout(
                                title="Team vs Match Points Heatmap",
                                xaxis_title="Matches",
                                yaxis_title="Teams",
                                margin=dict(l=60, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif")
                            )
                            plots['points_heatmap'] = pio.to_json(fig_heatmap)
                    
                    # --- Bubble Chart: Match number vs Points with team size as bubble size ---
                    if 'bubble' in selected_graph_types:
                        fig_bubble = go.Figure()
                        for team_number, match_points in team_match_points.items():
                            if match_points:
                                match_numbers = [mp['match_number'] for mp in match_points]
                                points_values = [mp['points'] for mp in match_points]
                                # Use team number as bubble size (scaled)
                                bubble_sizes = [max(10, min(50, team_number / 100)) for _ in match_points]
                                
                                fig_bubble.add_trace(go.Scatter(
                                    x=match_numbers,
                                    y=points_values,
                                    mode='markers',
                                    name=f"Team {team_number}",
                                    marker=dict(
                                        size=bubble_sizes,
                                        sizemode='diameter',
                                        opacity=0.7
                                    ),
                                    hovertemplate='<b>Team %{fullData.name}</b><br>Match %{x}: %{y:.2f} points<extra></extra>'
                                ))
                        
                        fig_bubble.update_layout(
                            title="Points by Match - Bubble Chart",
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
                        plots['points_bubble'] = pio.to_json(fig_bubble)
                    
                    # --- Area Chart: Cumulative points over matches ---
                    if 'area' in selected_graph_types:
                        fig_area = go.Figure()
                        for team_number, match_points in team_match_points.items():
                            if match_points:
                                # Sort by match number
                                sorted_matches = sorted(match_points, key=lambda x: x['match_number'])
                                match_numbers = [mp['match_number'] for mp in sorted_matches]
                                points_values = [mp['points'] for mp in sorted_matches]
                                
                                # Calculate cumulative points
                                cumulative_points = np.cumsum(points_values)
                                
                                fig_area.add_trace(go.Scatter(
                                    x=match_numbers,
                                    y=cumulative_points,
                                    mode='lines',
                                    name=f"Team {team_number}",
                                    fill='tonexty' if len(fig_area.data) > 0 else 'tozeroy',
                                    hovertemplate='<b>Team %{fullData.name}</b><br>Match %{x}: %{y:.2f} cumulative points<extra></extra>'
                                ))
                        
                        fig_area.update_layout(
                            title="Cumulative Points Over Matches (Area Chart)",
                            xaxis_title="Match Number",
                            yaxis_title="Cumulative Points",
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
                        plots['points_area'] = pio.to_json(fig_area)
                    
                    # --- Radar Chart: Multi-dimensional team performance comparison ---
                    if 'radar' in selected_graph_types and len(team_match_points) >= 3:
                        # Calculate metrics for radar chart
                        radar_metrics = ['Total Points', 'Average Points', 'Consistency', 'Peak Performance']
                        fig_radar = go.Figure()
                        
                        # Calculate radar metrics for each team
                        for team_number, match_points in team_match_points.items():
                            if match_points and len(match_points) >= 2:
                                points_values = [mp['points'] for mp in match_points]
                                total_points = sum(points_values)
                                avg_points = np.mean(points_values)
                                consistency = 100 - (np.std(points_values) / np.mean(points_values) * 100) if np.mean(points_values) > 0 else 0
                                peak_performance = max(points_values)
                                
                                # Normalize values for radar chart (0-100 scale)
                                max_total = max([sum([mp['points'] for mp in mps]) for mps in team_match_points.values()])
                                max_avg = max([np.mean([mp['points'] for mp in mps]) for mps in team_match_points.values() if mps])
                                max_peak = max([max([mp['points'] for mp in mps]) for mps in team_match_points.values() if mps])
                                
                                normalized_values = [
                                    (total_points / max_total * 100) if max_total > 0 else 0,
                                    (avg_points / max_avg * 100) if max_avg > 0 else 0,
                                    max(0, min(100, consistency)),
                                    (peak_performance / max_peak * 100) if max_peak > 0 else 0
                                ]
                                
                                fig_radar.add_trace(go.Scatterpolar(
                                    r=normalized_values + [normalized_values[0]],  # Close the shape
                                    theta=radar_metrics + [radar_metrics[0]],
                                    fill='toself',
                                    name=f"Team {team_number}",
                                    hovertemplate='<b>Team %{fullData.name}</b><br>%{theta}: %{r:.1f}<extra></extra>'
                                ))
                        
                        fig_radar.update_layout(
                            polar=dict(
                                radialaxis=dict(
                                    visible=True,
                                    range=[0, 100]
                                )
                            ),
                            title="Team Performance Radar Chart",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots['points_radar'] = pio.to_json(fig_radar)
                    
                    # --- Waterfall Chart: Match-by-match progression ---
                    if 'waterfall' in selected_graph_types:
                        # Create waterfall chart for a representative team showing match progression
                        # Select team with most matches for demonstration
                        best_team = max(team_match_points.items(), key=lambda x: len(x[1])) if team_match_points else None
                        
                        if best_team:
                            team_number, match_points = best_team
                            if len(match_points) >= 3:  # Need at least 3 matches for meaningful waterfall
                                sorted_matches = sorted(match_points, key=lambda x: x['match_number'])
                                
                                waterfall_data = []
                                waterfall_data.append({
                                    'x': f"Match {sorted_matches[0]['match_number']}",
                                    'y': sorted_matches[0]['points'],
                                    'measure': 'absolute',
                                    'text': f"{sorted_matches[0]['points']:.1f}"
                                })
                                
                                # Add subsequent matches as relative changes
                                for i in range(1, len(sorted_matches)):
                                    change = sorted_matches[i]['points'] - sorted_matches[i-1]['points']
                                    waterfall_data.append({
                                        'x': f"Match {sorted_matches[i]['match_number']}",
                                        'y': change,
                                        'measure': 'relative',
                                        'text': f"{change:+.1f}"
                                    })
                                
                                # Add total
                                total_points = sum([mp['points'] for mp in sorted_matches])
                                waterfall_data.append({
                                    'x': 'Total',
                                    'y': total_points,
                                    'measure': 'total',
                                    'text': f"{total_points:.1f}"
                                })
                                
                                fig_waterfall = go.Figure()
                                fig_waterfall.add_trace(go.Waterfall(
                                    name=f"Team {team_number} Progression",
                                    orientation="v",
                                    measure=[d['measure'] for d in waterfall_data],
                                    x=[d['x'] for d in waterfall_data],
                                    textposition="outside",
                                    text=[d['text'] for d in waterfall_data],
                                    y=[d['y'] for d in waterfall_data],
                                    connector={"line":{"color":"rgb(63, 63, 63)"}},
                                    decreasing={"marker":{"color":"red"}},
                                    increasing={"marker":{"color":"green"}},
                                    totals={"marker":{"color":"blue"}}
                                ))
                                fig_waterfall.update_layout(
                                    title=f"Team {team_number} Match Progression (Waterfall)",
                                    xaxis_title="Matches",
                                    yaxis_title="Points Change",
                                    margin=dict(l=40, r=20, t=50, b=60),
                                    plot_bgcolor='rgba(0,0,0,0)',
                                    paper_bgcolor='rgba(0,0,0,0)',
                                    font=dict(family="Arial, sans-serif"),
                                    xaxis=dict(tickangle=-45)
                                )
                                plots['points_waterfall'] = pio.to_json(fig_waterfall)
                    
                    # --- Enhanced Sankey Diagram: Multi-layer match performance flow ---
                    if 'sankey' in selected_graph_types:
                        # Create comprehensive Sankey showing teams -> match types -> performance -> outcomes
                        sankey_nodes = []
                        sankey_links = []
                        
                        # Layer 1: Teams
                        teams_with_data = [team for team, matches in team_match_points.items() if matches]
                        team_indices = {}
                        for i, team_number in enumerate(teams_with_data):
                            team_name = f"Team {team_number}"
                            sankey_nodes.append(team_name)
                            team_indices[team_number] = i
                        
                        # Layer 2: Match Performance Categories  
                        perf_layer_start = len(sankey_nodes)
                        performance_categories = ["Dominant Matches", "Strong Matches", "Competitive Matches", "Developing Matches"]
                        perf_indices = {}
                        for i, category in enumerate(performance_categories):
                            sankey_nodes.append(category)
                            perf_indices[category] = perf_layer_start + i
                        
                        # Layer 3: Consistency & Impact Categories
                        outcome_layer_start = len(sankey_nodes)
                        outcome_categories = ["High Impact Player", "Reliable Contributor", "Steady Performer", "Growth Focus"]
                        outcome_indices = {}
                        for i, category in enumerate(outcome_categories):
                            sankey_nodes.append(category)
                            outcome_indices[category] = outcome_layer_start + i
                        
                        # Calculate performance thresholds dynamically
                        all_match_points = []
                        for match_points in team_match_points.values():
                            all_match_points.extend([mp['points'] for mp in match_points])
                        
                        if all_match_points:
                            threshold_90 = np.percentile(all_match_points, 90)
                            threshold_70 = np.percentile(all_match_points, 70)
                            threshold_50 = np.percentile(all_match_points, 50)
                            threshold_30 = np.percentile(all_match_points, 30)
                        
                            # Create Links: Teams -> Performance Categories
                            for team_number in teams_with_data:
                                match_points = team_match_points[team_number]
                                team_idx = team_indices[team_number]
                                
                                # Categorize matches by performance level
                                dominant_matches = [mp for mp in match_points if mp['points'] >= threshold_90]
                                strong_matches = [mp for mp in match_points if threshold_70 <= mp['points'] < threshold_90]
                                competitive_matches = [mp for mp in match_points if threshold_30 <= mp['points'] < threshold_70]
                                developing_matches = [mp for mp in match_points if mp['points'] < threshold_30]
                                
                                # Create links based on match counts and total points in each category
                                categories_data = [
                                    (dominant_matches, "Dominant Matches", "rgba(76, 175, 80, 0.7)"),
                                    (strong_matches, "Strong Matches", "rgba(255, 193, 7, 0.7)"), 
                                    (competitive_matches, "Competitive Matches", "rgba(255, 152, 0, 0.7)"),
                                    (developing_matches, "Developing Matches", "rgba(244, 67, 54, 0.7)")
                                ]
                                
                                for matches, category, color in categories_data:
                                    if matches:
                                        total_points = sum(mp['points'] for mp in matches)
                                        target_idx = perf_indices[category]
                                        
                                        sankey_links.append({
                                            'source': team_idx,
                                            'target': target_idx,
                                            'value': total_points,
                                            'color': color
                                        })
                            
                            # Create Links: Performance Categories -> Outcome Categories
                            for team_number in teams_with_data:
                                match_points = team_match_points[team_number]
                                match_values = [mp['points'] for mp in match_points]
                                
                                if match_values:
                                    # Calculate team characteristics
                                    avg_points = np.mean(match_values)
                                    peak_points = max(match_values)
                                    consistency = (1 - (np.std(match_values) / np.mean(match_values))) * 100 if np.mean(match_values) > 0 else 0
                                    match_count = len(match_values)
                                    
                                    # Determine outcome category based on comprehensive analysis
                                    if peak_points >= threshold_90 and avg_points >= threshold_70 and consistency > 60:
                                        outcome_category = "High Impact Player"
                                        outcome_color = "rgba(139, 195, 74, 0.8)"
                                    elif avg_points >= threshold_50 and consistency > 40:
                                        outcome_category = "Reliable Contributor"
                                        outcome_color = "rgba(255, 235, 59, 0.8)"
                                    elif avg_points >= threshold_30 and match_count >= 3:
                                        outcome_category = "Steady Performer"
                                        outcome_color = "rgba(255, 183, 77, 0.8)"
                                    else:
                                        outcome_category = "Growth Focus"
                                        outcome_color = "rgba(239, 154, 154, 0.8)"
                                    
                                    # Find the primary performance category for this team
                                    dominant_total = sum(mp['points'] for mp in match_points if mp['points'] >= threshold_90)
                                    strong_total = sum(mp['points'] for mp in match_points if threshold_70 <= mp['points'] < threshold_90)
                                    competitive_total = sum(mp['points'] for mp in match_points if threshold_30 <= mp['points'] < threshold_70)
                                    developing_total = sum(mp['points'] for mp in match_points if mp['points'] < threshold_30)
                                    
                                    # Link from strongest performance category to outcome
                                    category_totals = [
                                        (dominant_total, "Dominant Matches"),
                                        (strong_total, "Strong Matches"),
                                        (competitive_total, "Competitive Matches"),
                                        (developing_total, "Developing Matches")
                                    ]
                                    
                                    primary_category = max(category_totals, key=lambda x: x[0])
                                    if primary_category[0] > 0:  # Only create link if there's actual performance
                                        source_idx = perf_indices[primary_category[1]]
                                        target_idx = outcome_indices[outcome_category]
                                        
                                        sankey_links.append({
                                            'source': source_idx,
                                            'target': target_idx,
                                            'value': primary_category[0],
                                            'color': outcome_color
                                        })
                        
                        # Create node colors for visual distinction
                        node_colors = []
                        for i, node in enumerate(sankey_nodes):
                            if i < perf_layer_start:  # Teams
                                node_colors.append("rgba(33, 150, 243, 0.9)")  # Blue
                            elif i < outcome_layer_start:  # Performance categories
                                node_colors.append("rgba(156, 39, 176, 0.9)")  # Purple  
                            else:  # Outcome categories
                                node_colors.append("rgba(0, 150, 136, 0.9)")  # Teal
                        
                        if sankey_nodes and sankey_links:
                            fig_sankey = go.Figure(data=[go.Sankey(
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
                                    hovertemplate='<b>%{source.label}</b> → <b>%{target.label}</b><br>Points Flow: %{value:.1f}<extra></extra>'
                                )
                            )])
                            fig_sankey.update_layout(
                                title="Enhanced Match Performance Flow Analysis (Sankey Diagram)",
                                margin=dict(l=60, r=60, t=100, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif", size=12),
                                height=700,
                                annotations=[
                                    dict(
                                        text="Teams → Match Performance → Player Impact Analysis",
                                        showarrow=False,
                                        xref="paper", yref="paper",
                                        x=0.5, y=1.05, xanchor='center', yanchor='bottom',
                                        font=dict(size=13, color='gray')
                                    ),
                                    dict(
                                        text=f"Analysis based on {len(all_match_points)} total matches",
                                        showarrow=False,
                                        xref="paper", yref="paper", 
                                        x=0.5, y=-0.08, xanchor='center', yanchor='top',
                                        font=dict(size=10, color='lightgray')
                                    )
                                ]
                            )
                            plots['points_sankey'] = pio.to_json(fig_sankey)
                    
                # Add a note about incompatible graph types for points metric when using averages view
                if selected_data_view == 'averages':
                    incompatible_graphs = []
                    # Heatmap is now available for averages view (team vs metric performance)
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
                
                # --- Sunburst Chart: Hierarchical team performance ---
                if 'sunburst' in selected_graph_types and selected_metric != 'points':
                    sunburst_data = []
                    for team_number, values in team_match_values.items():
                        if values:
                            avg_value = np.mean(values)
                            # Create performance categories
                            if avg_value >= np.percentile([np.mean(v) for v in team_match_values.values() if v], 75):
                                category = "High Performers"
                            elif avg_value >= np.percentile([np.mean(v) for v in team_match_values.values() if v], 50):
                                category = "Medium Performers"
                            elif avg_value >= np.percentile([np.mean(v) for v in team_match_values.values() if v], 25):
                                category = "Low Performers"
                            else:
                                category = "Developing Teams"
                                
                            sunburst_data.append({
                                'ids': f"Team {team_number}",
                                'labels': f"Team {team_number}",
                                'parents': category,
                                'values': avg_value
                            })
                    
                    # Add category parents
                    categories = ["High Performers", "Medium Performers", "Low Performers", "Developing Teams"]
                    for category in categories:
                        sunburst_data.append({
                            'ids': category,
                            'labels': category,
                            'parents': "",
                            'values': sum([d['values'] for d in sunburst_data if d.get('parents') == category])
                        })
                    
                    if sunburst_data:
                        fig_sunburst = go.Figure(go.Sunburst(
                            ids=[d['ids'] for d in sunburst_data],
                            labels=[d['labels'] for d in sunburst_data],
                            parents=[d['parents'] for d in sunburst_data],
                            values=[d['values'] for d in sunburst_data],
                            branchvalues="total",
                            hovertemplate='<b>%{label}</b><br>Value: %{value:.2f}<extra></extra>'
                        ))
                        fig_sunburst.update_layout(
                            title=f"{metric_name} Team Performance Hierarchy (Sunburst)",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots[f'{metric_id}_sunburst'] = pio.to_json(fig_sunburst)
                
                # --- Treemap Chart: Team performance as nested rectangles ---
                if 'treemap' in selected_graph_types and selected_metric != 'points':
                    treemap_data = []
                    for team_number, values in team_match_values.items():
                        if values:
                            avg_value = np.mean(values)
                            # Create performance categories
                            if avg_value >= np.percentile([np.mean(v) for v in team_match_values.values() if v], 75):
                                category = "High Performers"
                            elif avg_value >= np.percentile([np.mean(v) for v in team_match_values.values() if v], 50):
                                category = "Medium Performers"
                            elif avg_value >= np.percentile([np.mean(v) for v in team_match_values.values() if v], 25):
                                category = "Low Performers"
                            else:
                                category = "Developing Teams"
                                
                            treemap_data.append({
                                'ids': f"Team {team_number}",
                                'labels': f"Team {team_number}",
                                'parents': category,
                                'values': avg_value
                            })
                    
                    # Add category parents
                    categories = ["High Performers", "Medium Performers", "Low Performers", "Developing Teams"]
                    for category in categories:
                        treemap_data.append({
                            'ids': category,
                            'labels': category,
                            'parents': "",
                            'values': sum([d['values'] for d in treemap_data if d.get('parents') == category])
                        })
                    
                    if treemap_data:
                        fig_treemap = go.Figure(go.Treemap(
                            ids=[d['ids'] for d in treemap_data],
                            labels=[d['labels'] for d in treemap_data],
                            parents=[d['parents'] for d in treemap_data],
                            values=[d['values'] for d in treemap_data],
                            branchvalues="total",
                            hovertemplate='<b>%{label}</b><br>Value: %{value:.2f}<extra></extra>'
                        ))
                        fig_treemap.update_layout(
                            title=f"{metric_name} Team Performance Distribution (Treemap)",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif")
                        )
                        plots[f'{metric_id}_treemap'] = pio.to_json(fig_treemap)
                
                # --- Waterfall Chart for non-points metrics ---
                if 'waterfall' in selected_graph_types and selected_metric != 'points':
                    if selected_data_view == 'averages':
                        # Create waterfall for average values across teams
                        avg_data = []
                        for team_number, values in team_match_values.items():
                            avg = np.mean(values) if values else 0
                            avg_data.append({'team': team_number, 'avg': avg})
                        avg_data = sorted(avg_data, key=lambda x: x['avg'], reverse=True)[:8]  # Top 8 teams
                        
                        if avg_data:
                            waterfall_data = []
                            waterfall_data.append({
                                'x': f"Team {avg_data[0]['team']}",
                                'y': avg_data[0]['avg'],
                                'measure': 'absolute',
                                'text': f"{avg_data[0]['avg']:.1f}"
                            })
                            
                            for i in range(1, len(avg_data)):
                                change = avg_data[i]['avg'] - avg_data[i-1]['avg']
                                waterfall_data.append({
                                    'x': f"Team {avg_data[i]['team']}",
                                    'y': change,
                                    'measure': 'relative',
                                    'text': f"{change:+.1f}"
                                })
                            
                            fig_waterfall = go.Figure()
                            fig_waterfall.add_trace(go.Waterfall(
                                name=f"{metric_name} Progression",
                                orientation="v",
                                measure=[d['measure'] for d in waterfall_data],
                                x=[d['x'] for d in waterfall_data],
                                textposition="outside",
                                text=[d['text'] for d in waterfall_data],
                                y=[d['y'] for d in waterfall_data],
                                connector={"line":{"color":"rgb(63, 63, 63)"}},
                                decreasing={"marker":{"color":"red"}},
                                increasing={"marker":{"color":"green"}},
                                totals={"marker":{"color":"blue"}}
                            ))
                            fig_waterfall.update_layout(
                                title=f"{metric_name} Team Performance Waterfall",
                                xaxis_title="Teams",
                                yaxis_title=f"{metric_name} Change",
                                margin=dict(l=40, r=20, t=50, b=60),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif"),
                                xaxis=dict(tickangle=-45)
                            )
                            plots[f'{metric_id}_waterfall'] = pio.to_json(fig_waterfall)
                    else:
                        # Match-by-match waterfall for a representative team
                        best_team = max(team_match_values.items(), key=lambda x: len(x[1])) if team_match_values else None
                        
                        if best_team and len(best_team[1]) >= 3:
                            team_number, values = best_team
                            
                            # Get match data for this team
                            team_matches = team_data[team_number]['matches']
                            match_data = []
                            for match in team_matches:
                                value = match['metrics'].get(metric_id, {}).get('value')
                                if value is not None:
                                    match_data.append({
                                        'match_number': match['match_number'],
                                        'value': value
                                    })
                            
                            match_data = sorted(match_data, key=lambda x: x['match_number'])
                            
                            if len(match_data) >= 3:
                                waterfall_data = []
                                waterfall_data.append({
                                    'x': f"Match {match_data[0]['match_number']}",
                                    'y': match_data[0]['value'],
                                    'measure': 'absolute',
                                    'text': f"{match_data[0]['value']:.1f}"
                                })
                                
                                for i in range(1, len(match_data)):
                                    change = match_data[i]['value'] - match_data[i-1]['value']
                                    waterfall_data.append({
                                        'x': f"Match {match_data[i]['match_number']}",
                                        'y': change,
                                        'measure': 'relative',
                                        'text': f"{change:+.1f}"
                                    })
                                
                                fig_waterfall = go.Figure()
                                fig_waterfall.add_trace(go.Waterfall(
                                    name=f"Team {team_number} {metric_name}",
                                    orientation="v",
                                    measure=[d['measure'] for d in waterfall_data],
                                    x=[d['x'] for d in waterfall_data],
                                    textposition="outside",
                                    text=[d['text'] for d in waterfall_data],
                                    y=[d['y'] for d in waterfall_data],
                                    connector={"line":{"color":"rgb(63, 63, 63)"}},
                                    decreasing={"marker":{"color":"red"}},
                                    increasing={"marker":{"color":"green"}},
                                    totals={"marker":{"color":"blue"}}
                                ))
                                fig_waterfall.update_layout(
                                    title=f"Team {team_number} {metric_name} Progression",
                                    xaxis_title="Matches",
                                    yaxis_title=f"{metric_name} Change",
                                    margin=dict(l=40, r=20, t=50, b=60),
                                    plot_bgcolor='rgba(0,0,0,0)',
                                    paper_bgcolor='rgba(0,0,0,0)',
                                    font=dict(family="Arial, sans-serif"),
                                    xaxis=dict(tickangle=-45)
                                )
                                plots[f'{metric_id}_waterfall'] = pio.to_json(fig_waterfall)
                
                # --- Enhanced Sankey Diagram for non-points metrics ---
                if 'sankey' in selected_graph_types and selected_metric != 'points':
                    # Create multi-layer Sankey showing teams -> performance -> impact -> outcomes
                    sankey_nodes = []
                    sankey_links = []
                    
                    # Calculate performance categories based on metric values
                    all_values = []
                    for values in team_match_values.values():
                        all_values.extend(values)
                    
                    if all_values and len(team_match_values) > 1:
                        # Layer 1: Teams
                        teams_with_data = [team for team, values in team_match_values.items() if values]
                        team_indices = {}
                        for i, team_number in enumerate(teams_with_data):
                            team_name = f"Team {team_number}"
                            sankey_nodes.append(team_name)
                            team_indices[team_number] = i
                        
                        # Layer 2: Performance Levels
                        perf_layer_start = len(sankey_nodes)
                        performance_categories = [f"Elite {metric_name}", f"Strong {metric_name}", 
                                                f"Solid {metric_name}", f"Developing {metric_name}"]
                        perf_indices = {}
                        for i, category in enumerate(performance_categories):
                            sankey_nodes.append(category)
                            perf_indices[category] = perf_layer_start + i
                        
                        # Layer 3: Consistency & Impact
                        impact_layer_start = len(sankey_nodes)
                        impact_categories = ["Consistent High Impact", "Variable High Impact", 
                                           "Steady Contribution", "Inconsistent Performance"]
                        impact_indices = {}
                        for i, category in enumerate(impact_categories):
                            sankey_nodes.append(category)
                            impact_indices[category] = impact_layer_start + i
                        
                        # Layer 4: Strategic Value
                        value_layer_start = len(sankey_nodes)
                        value_categories = ["Key Strategic Asset", "Reliable Performer", 
                                          "Supporting Player", "Development Focus"]
                        value_indices = {}
                        for i, category in enumerate(value_categories):
                            sankey_nodes.append(category)
                            value_indices[category] = value_layer_start + i
                        
                        # Calculate thresholds
                        threshold_85 = np.percentile(all_values, 85)
                        threshold_65 = np.percentile(all_values, 65) 
                        threshold_40 = np.percentile(all_values, 40)
                        threshold_15 = np.percentile(all_values, 15)
                        
                        # Teams -> Performance Categories
                        for team_number in teams_with_data:
                            values = team_match_values[team_number]
                            avg_value = np.mean(values)
                            team_idx = team_indices[team_number]
                            
                            # Determine performance category and flow strength
                            if avg_value >= threshold_85:
                                target_idx = perf_indices[f"Elite {metric_name}"]
                                color = "rgba(76, 175, 80, 0.7)"  # Green
                            elif avg_value >= threshold_65:
                                target_idx = perf_indices[f"Strong {metric_name}"]
                                color = "rgba(255, 193, 7, 0.7)"  # Amber
                            elif avg_value >= threshold_40:
                                target_idx = perf_indices[f"Solid {metric_name}"]
                                color = "rgba(255, 152, 0, 0.7)"  # Orange
                            else:
                                target_idx = perf_indices[f"Developing {metric_name}"]
                                color = "rgba(244, 67, 54, 0.7)"  # Red
                            
                            sankey_links.append({
                                'source': team_idx,
                                'target': target_idx,
                                'value': avg_value * len(values),  # Total contribution
                                'color': color
                            })
                        
                        # Performance Categories -> Impact Categories
                        for team_number in teams_with_data:
                            values = team_match_values[team_number]
                            if len(values) > 1:
                                avg_value = np.mean(values)
                                std_value = np.std(values)
                                max_value = max(values)
                                consistency = (1 - (std_value / avg_value)) * 100 if avg_value > 0 else 0
                                
                                # Determine source performance category
                                if avg_value >= threshold_85:
                                    source_idx = perf_indices[f"Elite {metric_name}"]
                                elif avg_value >= threshold_65:
                                    source_idx = perf_indices[f"Strong {metric_name}"]
                                elif avg_value >= threshold_40:
                                    source_idx = perf_indices[f"Solid {metric_name}"]
                                else:
                                    source_idx = perf_indices[f"Developing {metric_name}"]
                                
                                # Determine impact category based on consistency and peak performance
                                if max_value >= threshold_85 and consistency >= 60:
                                    target_idx = impact_indices["Consistent High Impact"]
                                    color = "rgba(139, 195, 74, 0.8)"
                                elif max_value >= threshold_85 and consistency < 60:
                                    target_idx = impact_indices["Variable High Impact"]
                                    color = "rgba(255, 235, 59, 0.8)"
                                elif avg_value >= threshold_40 and consistency >= 40:
                                    target_idx = impact_indices["Steady Contribution"]
                                    color = "rgba(255, 183, 77, 0.8)"
                                else:
                                    target_idx = impact_indices["Inconsistent Performance"]
                                    color = "rgba(239, 154, 154, 0.8)"
                                
                                flow_value = avg_value * len(values) * (consistency / 100 + 0.5)  # Weighted by consistency
                                
                                sankey_links.append({
                                    'source': source_idx,
                                    'target': target_idx,
                                    'value': flow_value,
                                    'color': color
                                })
                        
                        # Impact Categories -> Strategic Value
                        impact_to_value_mapping = {
                            "Consistent High Impact": ("Key Strategic Asset", "rgba(0, 200, 83, 0.9)"),
                            "Variable High Impact": ("Reliable Performer", "rgba(255, 214, 0, 0.9)"),
                            "Steady Contribution": ("Supporting Player", "rgba(255, 171, 64, 0.9)"),
                            "Inconsistent Performance": ("Development Focus", "rgba(244, 81, 30, 0.9)")
                        }
                        
                        # Aggregate flows from impact to value categories
                        value_flows = {}
                        for team_number in teams_with_data:
                            values = team_match_values[team_number]
                            if len(values) > 1:
                                avg_value = np.mean(values)
                                std_value = np.std(values)
                                max_value = max(values)
                                consistency = (1 - (std_value / avg_value)) * 100 if avg_value > 0 else 0
                                
                                # Determine impact category
                                if max_value >= threshold_85 and consistency >= 60:
                                    impact_cat = "Consistent High Impact"
                                elif max_value >= threshold_85 and consistency < 60:
                                    impact_cat = "Variable High Impact"
                                elif avg_value >= threshold_40 and consistency >= 40:
                                    impact_cat = "Steady Contribution"
                                else:
                                    impact_cat = "Inconsistent Performance"
                                
                                value_cat, color = impact_to_value_mapping[impact_cat]
                                flow_value = avg_value * len(values)
                                
                                if (impact_cat, value_cat) not in value_flows:
                                    value_flows[(impact_cat, value_cat)] = {'value': 0, 'color': color}
                                value_flows[(impact_cat, value_cat)]['value'] += flow_value
                        
                        # Create impact -> value links
                        for (impact_cat, value_cat), flow_data in value_flows.items():
                            source_idx = impact_indices[impact_cat]
                            target_idx = value_indices[value_cat]
                            
                            sankey_links.append({
                                'source': source_idx,
                                'target': target_idx,
                                'value': flow_data['value'],
                                'color': flow_data['color']
                            })
                        
                        # Create layered node colors
                        node_colors = []
                        for i, node in enumerate(sankey_nodes):
                            if i < perf_layer_start:  # Teams
                                node_colors.append("rgba(33, 150, 243, 0.9)")  # Blue
                            elif i < impact_layer_start:  # Performance
                                node_colors.append("rgba(156, 39, 176, 0.9)")  # Purple
                            elif i < value_layer_start:  # Impact
                                node_colors.append("rgba(255, 152, 0, 0.9)")  # Orange
                            else:  # Strategic Value
                                node_colors.append("rgba(0, 150, 136, 0.9)")  # Teal
                        
                        if sankey_nodes and sankey_links:
                            fig_sankey = go.Figure(data=[go.Sankey(
                                node = dict(
                                    pad = 30,
                                    thickness = 35,
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
                            fig_sankey.update_layout(
                                title=f"Enhanced {metric_name} Performance Flow Analysis",
                                margin=dict(l=70, r=70, t=120, b=80),
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                font=dict(family="Arial, sans-serif", size=12),
                                height=750,
                                annotations=[
                                    dict(
                                        text=f"Teams → Performance → Impact → Strategic Value",
                                        showarrow=False,
                                        xref="paper", yref="paper",
                                        x=0.5, y=1.08, xanchor='center', yanchor='bottom',
                                        font=dict(size=14, color='gray')
                                    ),
                                    dict(
                                        text=f"Multi-layer analysis of {metric_name} across {len(teams_with_data)} teams",
                                        showarrow=False,
                                        xref="paper", yref="paper",
                                        x=0.5, y=-0.12, xanchor='center', yanchor='top',
                                        font=dict(size=10, color='lightgray')
                                    )
                                ]
                            )
                            plots[f'{metric_id}_sankey'] = pio.to_json(fig_sankey)
    

    
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
    
    # Get teams and events data
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    if current_event:
        current_event_teams = list(filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all())
        other_teams = Team.query.filter(~Team.id.in_([t.id for t in current_event_teams])).order_by(Team.team_number).all()
        all_teams = current_event_teams + other_teams
    else:
        all_teams = Team.query.order_by(Team.team_number).all()
    
    all_events = filter_events_by_scouting_team().all()
    
    # Calculate team metrics
    team_metrics = {}
    for team in all_teams:
        metrics = calculate_team_metrics(team.id)
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
            teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
        else:
            teams = Team.query.order_by(Team.team_number).all()
        
        metrics = game_config['data_analysis']['key_metrics']
        return render_template('graphs/side_by_side_form.html', teams=teams, metrics=metrics, **get_theme_context())
    
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Get teams
    teams = Team.query.filter(Team.team_number.in_(team_numbers)).all()
    
    # Calculate detailed metrics for each team
    teams_data = []
    
    for team in teams:
        scouting_data = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=current_user.scouting_team_number).all()
        
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
    
    # Get teams and data for the shared configuration
    team_numbers = shared_graph.team_numbers_list
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
        for graph_type in shared_graph.graph_types_list:
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
    
    return render_template('graphs/shared.html',
                         shared_graph=shared_graph,
                         plots=plots,
                         teams=teams,
                         game_config=game_config,
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
            if data['matches']:
                avg_value = sum(m['metric_value'] for m in data['matches']) / len(data['matches'])
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
        
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Distribution (Histogram)",
            xaxis_title=metric.replace('_', ' ').title(),
            yaxis_title="Frequency",
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
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
        
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Distribution by Team (Violin Plot)",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
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
        
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} Distribution by Team (Box Plot)",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
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
            fig.update_layout(
                title=f"Team {metric.replace('_', ' ').title()} Performance Hierarchy (Sunburst)",
                margin=dict(l=40, r=20, t=50, b=60),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)'
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
        
        fig.update_layout(
            title=f"Team {metric.replace('_', ' ').title()} Performance (Treemap)",
            margin=dict(l=40, r=20, t=50, b=60)
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
            
            fig.update_layout(
                title=f"Team {metric.replace('_', ' ').title()} Contribution (Waterfall)",
                xaxis_title="Teams",
                yaxis_title=metric.replace('_', ' ').title(),
                margin=dict(l=40, r=20, t=50, b=60)
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
            fig.update_layout(
                title=title_text,
                margin=dict(l=60, r=60, t=100, b=80),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(family="Arial, sans-serif", size=12),
                height=height,
                annotations=[
                    dict(
                        text=subtitle_text,
                        showarrow=False,
                        xref="paper", yref="paper",
                        x=0.5, y=1.05, xanchor='center', yanchor='bottom',
                        font=dict(size=13, color='gray')
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
        
        fig.update_layout(
            title=f"{metric.replace('_', ' ').title()} by Match (Bubble Chart)",
            xaxis_title="Match Number",
            yaxis_title=metric.replace('_', ' ').title(),
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
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
        
        fig.update_layout(
            title=f"Cumulative {metric.replace('_', ' ').title()} Over Matches (Area Chart)",
            xaxis_title="Match Number",
            yaxis_title=f"Cumulative {metric.replace('_', ' ').title()}",
            margin=dict(l=40, r=20, t=50, b=60),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
        )
        plots[f'{metric}_area'] = pio.to_json(fig)
    
    return plots

def _create_radar_chart(team_data, metric, data_view):
    """Create a radar chart for the given team data and metric"""
    plots = {}
    
    if len(team_data) >= 3:  # Need at least 3 teams for meaningful radar
        import numpy as np
        
        # Calculate radar metrics for each team
        radar_metrics = ['Average', 'Total', 'Consistency', 'Peak Performance']
        fig = go.Figure()
        
        # Calculate max values for normalization
        all_totals = []
        all_averages = []
        all_peaks = []
        
        for team_number, data in team_data.items():
            team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
            if team_values:
                all_totals.append(sum(team_values))
                all_averages.append(sum(team_values) / len(team_values))
                all_peaks.append(max(team_values))
        
        max_total = max(all_totals) if all_totals else 1
        max_avg = max(all_averages) if all_averages else 1
        max_peak = max(all_peaks) if all_peaks else 1
        
        for team_number, data in team_data.items():
            team_values = [m['metric_value'] for m in data['matches'] if m['metric_value'] is not None]
            if team_values and len(team_values) >= 2:
                total_val = sum(team_values)
                avg_val = sum(team_values) / len(team_values)
                consistency = 100 - (np.std(team_values) / np.mean(team_values) * 100) if np.mean(team_values) > 0 else 0
                peak_val = max(team_values)
                
                # Normalize values (0-100 scale)
                normalized_values = [
                    (avg_val / max_avg * 100) if max_avg > 0 else 0,
                    (total_val / max_total * 100) if max_total > 0 else 0,
                    max(0, min(100, consistency)),
                    (peak_val / max_peak * 100) if max_peak > 0 else 0
                ]
                
                fig.add_trace(go.Scatterpolar(
                    r=normalized_values + [normalized_values[0]],  # Close the shape
                    theta=radar_metrics + [radar_metrics[0]],
                    fill='toself',
                    name=f"Team {team_number}",
                    hovertemplate=f'<b>Team %{{fullData.name}}</b><br>%{{theta}}: %{{r:.1f}}<extra></extra>'
                ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100]
                )),
            showlegend=True,
            title=f"Team {metric.replace('_', ' ').title()} Performance Comparison (Radar)",
            margin=dict(l=40, r=20, t=50, b=60)
        )
        plots[f'{metric}_radar'] = pio.to_json(fig)
    
    return plots