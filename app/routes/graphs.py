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
                
                # Debug scouting data
                print(f"\nProcessing scouting data for team {team.team_number}, match {match.match_number}")
                print(f"Scouting data ID: {data.id}")
                print(f"Alliance: {data.alliance}")
                print(f"Scout name: {data.scout_name}")
                print(f"Match type: {match.match_type}")
                
                if team.team_number not in team_data:
                    team_data[team.team_number] = {
                        'team_name': team.team_name, 
                        'matches': []
                    }
                
                # For debugging, print the raw data for this scouting record
                try:
                    raw_data = data.data
                    print(f"Raw data keys: {list(raw_data.keys())}")
                except Exception as e:
                    print(f"Error accessing data.data: {e}")
                    raw_data = {}
                
                # Process each metric we're interested in
                match_metrics = {}
                
                # Direct access to the key metrics from game config
                key_metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
                print(f"Found {len(key_metrics)} metrics in game config")
                
                for metric in key_metrics:
                    if 'formula' in metric:
                        try:
                            metric_id = metric['id']
                            formula = metric['formula']
                            
                            print(f"\n  Processing metric {metric_id} with formula: {formula}")
                            
                            # Use the calculate_metric method from ScoutingData model
                            value = data.calculate_metric(formula)
                            print(f"  → Result for {metric_id}: {value}")
                            
                            match_metrics[metric_id] = {
                                'match_number': match.match_number,
                                'metric_id': metric_id,
                                'metric_name': metric['name'],
                                'value': value
                            }
                        except Exception as e:
                            print(f"  → ERROR calculating {metric_id}: {str(e)}")
                            print(f"  → Exception type: {type(e).__name__}")
                            import traceback
                            print(traceback.format_exc())
                
                # Add all metrics for this match to the team's data
                team_data[team.team_number]['matches'].append({
                    'match_number': match.match_number,
                    'metrics': match_metrics
                })
            
            # Generate comparison plot using the selected metric
            if selected_metric:
                print(f"\nGenerating graph for metric: {selected_metric}")
                metric_config = None
                for metric in game_config['data_analysis']['key_metrics']:
                    if metric['id'] == selected_metric:
                        metric_config = metric
                        break
                
                if metric_config:
                    print(f"Found metric config: {metric_config}")
                    
                    # Extract data for the selected metric
                    chart_data = []
                    
                    # Detailed logging of team data
                    for team_number, data in team_data.items():
                        print(f"\nTeam {team_number} has {len(data['matches'])} matches:")
                        
                        for match_data in data['matches']:
                            match_number = match_data['match_number']
                            metrics = match_data['metrics']
                            print(f"  Match {match_number} has {len(metrics)} metrics:")
                            
                            for metric_id, metric_info in metrics.items():
                                print(f"    {metric_id}: {metric_info['value']}")
                            
                            if selected_metric in metrics:
                                value = metrics[selected_metric]['value']
                                print(f"  → Adding data point: Match {match_number}, Value: {value}")
                                
                                chart_data.append({
                                    'team': f"{team_number} - {data['team_name']}",
                                    'match': match_number,
                                    'value': value
                                })
                            else:
                                print(f"  → No data for metric {selected_metric} in match {match_number}")
                    
                    print(f"\nCollected {len(chart_data)} data points for the chart")
                    
                    # We're removing the top graph that doesn't work and only keeping the bottom graph
                    # that shows team average comparisons
                    
                    # Create a bar chart for average performance
                    avg_data = []
                    
                    print("\nCalculating averages for each team:")
                    for team_number, data in team_data.items():
                        values = []
                        for match_data in data['matches']:
                            metrics = match_data['metrics']
                            if selected_metric in metrics:
                                values.append(metrics[selected_metric]['value'])
                        
                        print(f"Team {team_number}: {len(values)} values - {values}")
                        
                        if values:
                            avg_value = sum(values) / len(values)
                            print(f"  → Average: {avg_value}")
                            
                            avg_data.append({
                                'team': f"{team_number} - {data['team_name']}",
                                'value': avg_value
                            })
                    
                    if avg_data:
                        print(f"\nAverage data points ({len(avg_data)}):")
                        for item in avg_data:
                            print(f"  {item['team']}: {item['value']}")
                        
                        # Use go.Figure for the bar chart
                        fig_avg = go.Figure()
                        
                        # Sort data by value for better readability
                        avg_data = sorted(avg_data, key=lambda x: x['value'], reverse=True)
                        
                        fig_avg.add_trace(go.Bar(
                            x=[d['team'] for d in avg_data],
                            y=[d['value'] for d in avg_data],
                            marker_color='rgb(55, 83, 109)'
                        ))
                        
                        # Update layout
                        fig_avg.update_layout(
                            title=f"Average {metric_config['name']} by Team",
                            xaxis_title="Team",
                            yaxis_title=f"Average {metric_config['name']}",
                            margin=dict(l=40, r=20, t=50, b=60),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(family="Arial, sans-serif"),
                            xaxis=dict(tickangle=-45)
                        )
                        
                        # Convert to JSON and assign to team_comparison instead of team_avg_comparison
                        # This ensures it displays in the expected location in the template
                        plots['team_comparison'] = pio.to_json(fig_avg)
                        print("Successfully created team average comparison plot")
                    else:
                        print("No average data available to create bar chart")
            else:
                # If no metric selected, show a default graph
                # Example: Create a simple bar chart of teams by number of matches scouted
                print("\nNo metric selected, creating default 'matches scouted' graph")
                
                team_match_counts = {}
                for data in scouting_data:
                    if data.team_id in team_match_counts:
                        team_match_counts[data.team_id] += 1
                    else:
                        team_match_counts[data.team_id] = 1
                
                chart_data = []
                for team in teams:
                    match_count = team_match_counts.get(team.id, 0)
                    print(f"Team {team.team_number} has {match_count} matches scouted")
                    
                    chart_data.append({
                        'team_number': team.team_number,
                        'team_name': team.team_name,
                        'match_count': match_count
                    })
                
                if chart_data:
                    # Create a direct Plotly figure
                    fig = go.Figure()
                    
                    # Sort by team number for consistency
                    chart_data = sorted(chart_data, key=lambda x: x['team_number'])
                    
                    fig.add_trace(go.Bar(
                        x=[f"{d['team_number']} - {d['team_name']}" for d in chart_data],
                        y=[d['match_count'] for d in chart_data],
                        marker_color='rgb(26, 118, 255)'
                    ))
                    
                    # Update layout
                    fig.update_layout(
                        title='Teams by Number of Matches Scouted',
                        xaxis_title='Team',
                        yaxis_title='Matches Scouted',
                        margin=dict(l=40, r=20, t=50, b=40),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font=dict(family="Arial, sans-serif")
                    )
                    
                    # Convert to JSON for JavaScript
                    plots['team_comparison'] = pio.to_json(fig)
                    print("Successfully created 'matches scouted' plot")
    
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
                          team_metrics=team_metrics)