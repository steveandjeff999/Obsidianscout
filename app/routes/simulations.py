from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
from app.models import Team, Event
from app.utils.team_isolation import filter_teams_by_scouting_team, filter_events_by_scouting_team, get_combined_dropdown_events, dedupe_team_list, get_alliance_team_numbers, get_current_scouting_team_number
import json
from app.utils.analysis import calculate_team_metrics, _simulate_match_outcomes
from app.utils.config_manager import get_effective_game_config
from app.utils.theme_manager import ThemeManager


def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }


bp = Blueprint('simulations', __name__, url_prefix='/simulations')


@bp.route('/', methods=['GET'])
@analytics_required
def index():
    # Reuse the team selection logic from graphs to provide a modern UI
    teams_query = filter_teams_by_scouting_team().order_by(Team.team_number).all()
    # Deduplicate by team_number (prefer alliance copies when present) to avoid
    # duplicate team entries appearing in the UI when multiple teams with the
    # same team_number exist across scouting_team_number values.
    try:
        teams = dedupe_team_list(teams_query, prefer_alliance=True, alliance_team_numbers=get_alliance_team_numbers(), current_scouting_team=get_current_scouting_team_number())
    except Exception:
        teams = teams_query
    events = get_combined_dropdown_events()

    # Calculate metrics and event mapping for client-side helpers
    team_metrics = {}
    for team in teams:
        team_metrics[team.team_number] = calculate_team_metrics(team.id).get('metrics', {})

    team_event_mapping = {}
    all_teams_data = []
    for t in teams:
        team_event_mapping[t.team_number] = [e.id for e in (t.events or [])]
        all_teams_data.append({
            'teamNumber': t.team_number,
            'teamName': t.team_name or 'Unknown',
            'displayText': f"{t.team_number} - {t.team_name or 'Unknown'}",
            'points': team_metrics.get(t.team_number, {}).get('total_points', 0)
        })

    all_teams_json = json.dumps(all_teams_data)
    # Provide teams and events for UI controls
    return render_template('simulations/index.html', teams=teams, events=events, all_teams_json=all_teams_json, team_event_mapping=team_event_mapping, team_metrics=team_metrics, **get_theme_context())


@bp.route('/run', methods=['POST'])
@analytics_required
def run_simulation():
    data = request.get_json() or {}
    red_numbers = data.get('red', [])
    blue_numbers = data.get('blue', [])
    n_simulations = int(data.get('n_simulations', 3000))
    seed = data.get('seed')
    event_id = data.get('event_id')

    # Validate lists
    if not isinstance(red_numbers, list) or not isinstance(blue_numbers, list):
        return jsonify({'ok': False, 'error': 'Invalid team lists provided'}), 400

    # Convert possible strings to ints
    try:
        red_numbers = [int(x) for x in red_numbers if x is not None and x != '']
        blue_numbers = [int(x) for x in blue_numbers if x is not None and x != '']
    except Exception:
        return jsonify({'ok': False, 'error': 'Team numbers must be integers'}), 400

    # Lookup teams - ensure we select the team record scoped to the current user's view
    # (prefer current user's scouting team or alliance copy). This avoids choosing an
    # arbitrary duplicate team record and producing inconsistent metrics.
    from app.utils.team_isolation import get_team_by_number
    teams_map = {}
    for tn in set(red_numbers + blue_numbers):
        try:
            t = get_team_by_number(tn)
            if not t:
                # Final fallback to any record with this number
                t = Team.query.filter_by(team_number=tn).first()
            if t:
                teams_map[tn] = t
        except Exception:
            continue

    if not teams_map:
        return jsonify({'ok': False, 'error': 'No matching teams found'}), 400

    # Identify team overlap but allow simulation to continue; return overlap info to client
    overlap = sorted(list(set(red_numbers).intersection(set(blue_numbers))))

    # Build red/blue alliance data suitable for _simulate_match_outcomes
    red_alliance = []
    for team_num in red_numbers:
        t = teams_map.get(team_num)
        if not t:
            continue
        metrics = calculate_team_metrics(t.id, event_id=event_id).get('metrics', {})
        red_alliance.append({'team': t, 'metrics': metrics})

    blue_alliance = []
    for team_num in blue_numbers:
        t = teams_map.get(team_num)
        if not t:
            continue
        metrics = calculate_team_metrics(t.id, event_id=event_id).get('metrics', {})
        blue_alliance.append({'team': t, 'metrics': metrics})

    # Determine which metric to use for totals (default 'tot')
    game_config = get_effective_game_config()
    total_metric_id = None
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            metric_id = metric.get('id')
            if 'total' in (metric_id or '').lower() or (metric_id or '').lower() == 'tot':
                total_metric_id = metric_id
                break
    if not total_metric_id:
        total_metric_id = 'tot'

    # Run simulation
    try:
        sim_result = _simulate_match_outcomes(red_alliance, blue_alliance, total_metric_id, n_simulations=n_simulations, seed=seed)
    except Exception as e:
        current_app.logger.exception('Simulation failed')
        return jsonify({'ok': False, 'error': 'Simulation failed', 'detail': str(e)}), 500

    # Build a simple response for frontend
    resp = {
        'ok': True,
        'red': {
            'expected_score': sim_result.get('expected_red'),
            'win_prob': sim_result.get('red_win_prob')
        },
        'blue': {
            'expected_score': sim_result.get('expected_blue'),
            'win_prob': sim_result.get('blue_win_prob')
        },
        'tie_prob': sim_result.get('tie_prob')
    }
    # Determine predicted winner by comparing win probabilities
    if resp['red']['win_prob'] > resp['blue']['win_prob']:
        resp['predicted_winner'] = 'red'
    elif resp['blue']['win_prob'] > resp['red']['win_prob']:
        resp['predicted_winner'] = 'blue'
    else:
        resp['predicted_winner'] = 'tie'

    # Add overlap info if present
    if overlap:
        resp['overlap_teams'] = overlap

    return jsonify(resp)
