from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required
from app.routes.auth import analytics_required
from app.models import Team, Match, ScoutingData, Event
from app import db
import json
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from collections import defaultdict
import plotly

bp = Blueprint('visualization', __name__, url_prefix='/visualization')

@bp.route('/')
@analytics_required
def index():
    """Visualization dashboard"""
    teams = Team.query.order_by(Team.team_number).all()
    events = Event.query.all()
    
    # Create team-event mapping for client-side filtering
    team_event_mapping = {}
    for team in teams:
        team_event_mapping[team.team_number] = [event.id for event in team.events]
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    metrics = game_config['data_analysis']['key_metrics']
    
    return render_template('visualization/index.html', teams=teams, events=events, 
                          metrics=metrics, game_config=game_config, 
                          team_event_mapping=team_event_mapping)

@bp.route('/team/<int:team_number>')
def team_stats(team_number):
    """Display statistics for a single team"""
    team = Team.query.filter_by(team_number=team_number).first_or_404()
    
    # Get team's scouting data
    scouting_data = ScoutingData.query.filter_by(team_id=team.id).all()
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Calculate team metrics
    metrics = {}
    match_metrics = []
    
    if scouting_data:
        for metric in game_config['data_analysis']['key_metrics']:
            if 'formula' in metric:
                # Calculate metrics for each match
                match_values = []
                for data in scouting_data:
                    match_num = data.match.match_number
                    value = data.calculate_metric(metric['formula'])
                    match_values.append({'match': match_num, 'value': value})
                    match_metrics.append({
                        'match': match_num, 
                        'metric': metric['id'], 
                        'name': metric['name'],
                        'value': value
                    })
                
                # Aggregate metrics
                if 'aggregate' in metric and metric['aggregate'] == 'average':
                    values = [x['value'] for x in match_values]
                    metrics[metric['id']] = {
                        'name': metric['name'],
                        'value': sum(values) / len(values) if values else 0,
                        'match_values': match_values
                    }
                elif 'aggregate' in metric and metric['aggregate'] == 'percentage':
                    values = [x['value'] for x in match_values]
                    metrics[metric['id']] = {
                        'name': metric['name'],
                        'value': (sum(values) / len(values) * 100) if values else 0,
                        'match_values': match_values
                    }
                else:
                    metrics[metric['id']] = {
                        'name': metric['name'],
                        'value': match_values,
                        'match_values': match_values
                    }
    
    # Generate plots
    plots = {}
    df = pd.DataFrame(match_metrics)
    
    if not df.empty:
        # Bar chart for each metric
        for metric_id in metrics:
            metric = metrics[metric_id]
            if 'match_values' in metric and metric['match_values']:
                metric_df = df[df['metric'] == metric_id].sort_values('match')
                
                # Create a plain bar chart that will serialize properly
                fig = px.bar(
                    metric_df, 
                    x='match', 
                    y='value',
                    title=f"{metric['name']} by Match",
                    labels={'match': 'Match Number', 'value': metric['name']}
                )
                
                # Update layout for better appearance
                fig.update_layout(
                    margin=dict(l=40, r=20, t=40, b=40),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(family="Arial, sans-serif")
                )
                
                # Serialize directly to a JSON format compatible with JavaScript Plotly
                plot_json = {
                    "data": fig.data,
                    "layout": fig.layout
                }
                
                # Use the built-in plotly serializer for guaranteed compatibility
                plots[metric_id + '_bar'] = json.dumps(plot_json, cls=plotly.utils.PlotlyJSONEncoder)
        
        # Line chart for trends - generate for all metrics that have match values
        for metric_id in metrics:
            metric = metrics[metric_id]
            if 'match_values' in metric and metric['match_values']:
                metric_df = df[df['metric'] == metric_id].sort_values('match')
                
                fig = px.line(
                    metric_df, 
                    x='match', 
                    y='value',
                    title=f"{metric['name']} Trend",
                    labels={'match': 'Match Number', 'value': metric['name']},
                    markers=True # Add markers to make the line chart more readable
                )
                
                # Update layout for better appearance
                fig.update_layout(
                    margin=dict(l=40, r=20, t=40, b=40),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(family="Arial, sans-serif")
                )
                
                # Serialize directly to a JSON format compatible with JavaScript Plotly
                plot_json = {
                    "data": fig.data,
                    "layout": fig.layout
                }
                
                # Use the built-in plotly serializer for guaranteed compatibility
                plots[metric_id + '_line'] = json.dumps(plot_json, cls=plotly.utils.PlotlyJSONEncoder)
    
    return render_template('visualization/team.html', team=team, 
                          metrics=metrics, plots=plots, game_config=game_config,
                          scouting_data=scouting_data)  # Add scouting_data to the template context

@bp.route('/compare')
def compare_teams():
    """Compare multiple teams"""
    team_numbers = request.args.getlist('teams', type=int)
    metric_id = request.args.get('metric')
    
    if not team_numbers or not metric_id:
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
            teams = Team.query.order_by(Team.team_number).all()  # Show all teams if no current event is set
        
        metrics = game_config['data_analysis']['key_metrics']
        return render_template('visualization/compare_form.html', teams=teams, metrics=metrics)
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Find the metric configuration
    metric_config = None
    for metric in game_config['data_analysis']['key_metrics']:
        if metric['id'] == metric_id:
            metric_config = metric
            break
    
    if not metric_config:
        return render_template('visualization/error.html', 
                              message=f"Metric {metric_id} not found in game configuration.")
    
    # Get teams
    teams = Team.query.filter(Team.team_number.in_(team_numbers)).all()
    
    # Calculate metrics for each team
    team_metrics = []
    teams_with_data = []
    teams_without_data = []
    
    for team in teams:
        scouting_data = ScoutingData.query.filter_by(team_id=team.id).all()
        
        if not scouting_data:
            # Include teams without data with 0 values
            teams_without_data.append(team)
            team_metrics.append({
                'team': team.team_number,
                'team_name': team.team_name,
                'aggregate_value': 0,
                'match_values': [],
                'has_data': False
            })
            continue
        
        # Calculate metric for each match
        match_values = []
        for data in scouting_data:
            try:
                match_num = data.match.match_number
                # Use the metric ID instead of the formula for auto-generated metrics
                value = data.calculate_metric(metric_config['id'])
                match_values.append({
                    'team': team.team_number,
                    'team_name': team.team_name,
                    'match': match_num,
                    'value': value
                })
            except Exception as e:
                print(f"Error calculating metric for team {team.team_number}, match {data.match.match_number}: {e}")
        
        # Calculate aggregate value
        if match_values:
            values = [x['value'] for x in match_values]
            if 'aggregate' in metric_config and metric_config['aggregate'] == 'average':
                aggregate_value = sum(values) / len(values)
            elif 'aggregate' in metric_config and metric_config['aggregate'] == 'percentage':
                aggregate_value = (sum(values) / len(values)) * 100
            else:
                aggregate_value = sum(values)
        else:
            aggregate_value = 0
        
        team_metrics.append({
            'team': team.team_number,
            'team_name': team.team_name,
            'aggregate_value': aggregate_value,
            'match_values': match_values,
            'has_data': True
        })
        teams_with_data.append(team)
    
    # Generate comparison plots
    plots = {}
    
    # Bar chart comparing aggregate values
    bar_data = []
    colors = []
    for tm in team_metrics:
        team_label = f"{tm['team']} - {tm['team_name']}"
        bar_data.append({
            'team': team_label,
            'value': tm['aggregate_value'],
            'has_data': tm.get('has_data', True)
        })
        # Use different colors for teams with/without data
        if tm.get('has_data', True):
            colors.append('#1f77b4')  # Blue for teams with data
        else:
            colors.append('#ff7f0e')  # Orange for teams without data
    
    df_bar = pd.DataFrame(bar_data)
    if not df_bar.empty:
        # Create bar chart with improved styling
        fig_bar = px.bar(
            df_bar,
            x='team',
            y='value',
            title=f"Team Comparison: {metric_config['name']}",
            labels={'team': 'Team', 'value': metric_config['name']},
            color='has_data',
            color_discrete_map={True: '#1f77b4', False: '#ff7f0e'}
        )
        
        # Update layout for better appearance
        fig_bar.update_layout(
            margin=dict(l=40, r=20, t=50, b=80),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Arial, sans-serif"),
            xaxis=dict(tickangle=-45),  # Rotate labels for better readability
            legend=dict(
                title="Data Status",
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        # Update legend labels
        fig_bar.for_each_trace(lambda t: t.update(name = "With Data" if t.name == "True" else "No Data"))
        
        # Serialize directly to a compatible JSON format
        plot_json = {
            "data": fig_bar.data,
            "layout": fig_bar.layout
        }
        
        # Use the built-in plotly serializer
        plots['comparison_bar'] = json.dumps(plot_json, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Line chart comparing match trends (only for teams with data)
    line_data = []
    for tm in team_metrics:
        if tm.get('has_data', True):  # Only include teams with data
            for mv in tm['match_values']:
                line_data.append({
                    'team': f"{tm['team']} - {tm['team_name']}",
                    'match': mv['match'],
                    'value': mv['value']
                })
    
    df_line = pd.DataFrame(line_data)
    if not df_line.empty:
        # Create line chart with markers
        fig_line = px.line(
            df_line,
            x='match',
            y='value',
            color='team',
            title=f"Match Trend Comparison: {metric_config['name']} (Teams with Data Only)",
            labels={'match': 'Match Number', 'value': metric_config['name'], 'team': 'Team'},
            markers=True  # Add markers for better readability
        )
        
        # Update layout for better appearance
        fig_line.update_layout(
            margin=dict(l=40, r=20, t=50, b=40),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Arial, sans-serif"),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.3,
                xanchor="center",
                x=0.5
            )
        )
        
        # Serialize directly to a compatible JSON format
        plot_json = {
            "data": fig_line.data,
            "layout": fig_line.layout
        }
        
        # Use the built-in plotly serializer
        plots['comparison_line'] = json.dumps(plot_json, cls=plotly.utils.PlotlyJSONEncoder)
    
    return render_template('visualization/compare.html',
                         teams=teams,
                         teams_with_data=teams_with_data,
                         teams_without_data=teams_without_data,
                         metric=metric_config,
                         team_metrics=team_metrics,
                         plots=plots)

@bp.route('/event/<int:event_id>')
def event_stats(event_id):
    """Display statistics for an entire event"""
    event = Event.query.get_or_404(event_id)
    
    # Get all matches for this event
    matches = Match.query.filter_by(event_id=event.id).all()
    
    # Get all scouting data for these matches
    match_ids = [match.id for match in matches]
    scouting_data = ScoutingData.query.filter(ScoutingData.match_id.in_(match_ids)).all()
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Calculate team rankings
    team_metrics = defaultdict(lambda: defaultdict(list))
    
    for data in scouting_data:
        team = data.team
        
        # Calculate metrics for this team
        for metric in game_config['data_analysis']['key_metrics']:
            if 'formula' in metric:
                try:
                    value = data.calculate_metric(metric['formula'])
                    team_metrics[team.team_number][metric['id']].append(value)
                except Exception as e:
                    print(f"Error calculating {metric['id']} for team {team.team_number}: {e}")
    
    # Aggregate team metrics
    team_rankings = []
    
    for team_number, metrics in team_metrics.items():
        team = Team.query.filter_by(team_number=team_number).first()
        if not team:
            continue
            
        team_data = {
            'team_number': team_number,
            'team_name': team.team_name
        }
        
        # Calculate aggregates for each metric
        for metric in game_config['data_analysis']['key_metrics']:
            metric_id = metric['id']
            if metric_id in metrics and metrics[metric_id]:
                values = metrics[metric_id]
                if 'aggregate' in metric and metric['aggregate'] == 'average':
                    team_data[metric_id] = sum(values) / len(values)
                elif 'aggregate' in metric and metric['aggregate'] == 'percentage':
                    team_data[metric_id] = (sum(values) / len(values)) * 100
                else:
                    team_data[metric_id] = sum(values)
            else:
                team_data[metric_id] = 0
        
        team_rankings.append(team_data)
    
    # Sort by primary metric (first one in config)
    primary_metric = game_config['data_analysis']['key_metrics'][0]['id']
    team_rankings.sort(key=lambda x: x.get(primary_metric, 0), reverse=True)
    
    # Generate plots
    plots = {}
    
    # Team rankings bar chart
    if team_rankings:
        for metric in game_config['data_analysis']['key_metrics']:
            metric_id = metric['id']
            df = pd.DataFrame(team_rankings)
            
            if not df.empty and metric_id in df.columns:
                # Create bar chart with improved styling
                fig = px.bar(
                    df.sort_values(metric_id, ascending=False),
                    x='team_number',
                    y=metric_id,
                    title=f"Team Rankings by {metric['name']}",
                    labels={'team_number': 'Team', metric_id: metric['name']}
                )
                
                # Update layout for better appearance
                fig.update_layout(
                    margin=dict(l=40, r=20, t=50, b=40),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(family="Arial, sans-serif")
                )
                
                # Serialize directly to a compatible JSON format
                plot_json = {
                    "data": fig.data,
                    "layout": fig.layout
                }
                
                # Use the built-in plotly serializer for guaranteed compatibility
                plots[f"ranking_{metric_id}"] = json.dumps(plot_json, cls=plotly.utils.PlotlyJSONEncoder)
    
    return render_template('visualization/event.html',
                         event=event,
                         team_rankings=team_rankings,
                         plots=plots,
                         game_config=game_config)

@bp.route('/side-by-side')
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
        return render_template('visualization/side_by_side_form.html', teams=teams, metrics=metrics)
    
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
    
    return render_template('visualization/side_by_side.html',
                         teams_data=teams_data,
                         game_config=game_config)