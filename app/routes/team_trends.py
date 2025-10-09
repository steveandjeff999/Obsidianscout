from flask import Blueprint, render_template, request, current_app, jsonify
from app.models import Team, ScoutingData
from app.utils.config_manager import get_current_game_config
from statistics import mean
import math

bp = Blueprint('team_trends', __name__, url_prefix='/team-trends')


def _simple_linear_regression(x_vals, y_vals):
    """Return slope and intercept for simple linear regression. x_vals and y_vals should be lists of numbers."""
    if not x_vals or not y_vals or len(x_vals) != len(y_vals):
        return 0, 0
    n = len(x_vals)
    x_mean = mean(x_vals)
    y_mean = mean(y_vals)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
    den = sum((x - x_mean) ** 2 for x in x_vals)
    if den == 0:
        return 0, y_mean
    slope = num / den
    intercept = y_mean - slope * x_mean
    return slope, intercept


@bp.route('/')
def index():
    # Simple page with a form to enter a team number
    return render_template('team_trends/index.html')


@bp.route('/analyze', methods=['POST'])
def analyze_post():
    team_number = request.form.get('team_number')
    if not team_number:
        return render_template('team_trends/index.html', error='Please provide a team number')
    try:
        team_number = int(team_number)
    except Exception:
        return render_template('team_trends/index.html', error='Invalid team number')
    return _analyze_team(team_number)


@bp.route('/analyze/<int:team_number>')
def analyze(team_number):
    return _analyze_team(team_number)


def _analyze_team(team_number):
    # Gather historical scouting data for this team across matches
    # We'll compute a simple 'total points' metric per match if possible
    try:
        team = Team.query.filter_by(team_number=team_number).first()
    except Exception:
        team = None

    # Find all ScoutingData entries for this team (by team_id or team_number match)
    try:
        entries = []
        # If we have team object, prefer team.id
        if team:
            entries = ScoutingData.query.filter_by(team_id=team.id).order_by(ScoutingData.timestamp).all()
        else:
            # Fallback: query by team number in Team table
            entries = ScoutingData.query.join(Team).filter(Team.team_number == team_number).order_by(ScoutingData.timestamp).all()
    except Exception:
        entries = []

    # Build timeline and compute a simple total points metric using available key metrics
    timeline = []
    x_vals = []
    y_vals = []
    for idx, entry in enumerate(entries):
        try:
            data = entry.data
            # Prefer an explicit 'total_points' field if present
            total_points = None
            if isinstance(data, dict):
                total_points = data.get('total_points') or data.get('tot') or data.get('points')

            # If no explicit total, compute from game config periods (auto + teleop + endgame)
            if total_points is None:
                # Use game config scoring elements to compute point totals if available
                game_config = get_current_game_config() or {}
                total_points = 0

                def compute_period_points(period_name):
                    pts = 0
                    period = game_config.get(period_name, {})
                    for el in period.get('scoring_elements', []):
                        perm_id = el.get('perm_id') or el.get('id')
                        el_type = el.get('type')
                        # For counters and numeric fields, multiply by points if defined
                        if isinstance(data, dict) and perm_id in data:
                            val = data.get(perm_id)
                            try:
                                val_num = float(val) if val is not None and val != '' else 0
                            except Exception:
                                val_num = 0
                            # If element defines points per unit
                            points_per = el.get('points') or el.get('point_value') or 0
                            if isinstance(points_per, dict):
                                # If points depend on option, skip complex mapping and try direct numeric
                                pts += val_num
                            else:
                                try:
                                    pts += val_num * float(points_per)
                                except Exception:
                                    pts += val_num
                        else:
                            # no data for this element; skip
                            pass
                    return pts

                total_points += compute_period_points('auto_period')
                total_points += compute_period_points('teleop_period')
                total_points += compute_period_points('endgame_period')

                # As a final fallback, if still zero, sum numeric fields
                if not total_points:
                    numeric_values = [v for v in (data.values() if isinstance(data, dict) else []) if isinstance(v, (int, float))]
                    total_points = sum(numeric_values) if numeric_values else 0
            # Never allow negative points
            try:
                total_points = float(total_points)
            except Exception:
                total_points = 0
            if total_points < 0:
                total_points = 0

            timeline.append({'timestamp': entry.timestamp.isoformat(), 'total_points': total_points})
            x_vals.append(idx)
            y_vals.append(total_points)
        except Exception:
            continue

    slope, intercept = _simple_linear_regression(x_vals, y_vals)

    # Predict next value (one step ahead)
    next_x = len(x_vals)
    predicted_next = slope * next_x + intercept if x_vals else 0

    # Simple trend classification
    # Compute recent trend over the last N points
    recent_window = min(5, len(y_vals))
    recent_trend_info = {
        'recent_slope': 0,
        'recent_intercept': 0,
        'recent_pct_change': 0,
        'recent_consistency': 0
    }

    if recent_window >= 2:
        recent_x = list(range(len(y_vals) - recent_window, len(y_vals)))
        recent_y = y_vals[-recent_window:]
        rslope, rintercept = _simple_linear_regression(recent_x, recent_y)
        recent_trend_info['recent_slope'] = rslope
        recent_trend_info['recent_intercept'] = rintercept
        # percent change over recent window
        try:
            y_first = recent_y[0]
            y_last = recent_y[-1]
            recent_trend_info['recent_pct_change'] = (y_last - y_first) / max(1.0, (abs(y_first) + abs(y_last)) / 2.0)
        except Exception:
            recent_trend_info['recent_pct_change'] = 0
        # recent consistency: proportion of positive diffs
        diffs = [recent_y[i] - recent_y[i-1] for i in range(1, len(recent_y))]
        if diffs:
            pos = sum(1 for d in diffs if d > 0)
            neg = sum(1 for d in diffs if d < 0)
            recent_trend_info['recent_consistency'] = (pos - neg) / len(diffs)
            recent_trend_info['recent_consistency_strength'] = max(pos, neg) / len(diffs)

    # Overall consistency and percent change
    overall_trend_info = {
        'overall_slope': slope,
        'overall_intercept': intercept,
        'overall_pct_change': 0,
        'overall_consistency': 0
    }
    if len(y_vals) >= 2:
        try:
            y_first = y_vals[0]
            y_last = y_vals[-1]
            overall_trend_info['overall_pct_change'] = (y_last - y_first) / max(1.0, (abs(y_first) + abs(y_last)) / 2.0)
        except Exception:
            overall_trend_info['overall_pct_change'] = 0

        diffs_all = [y_vals[i] - y_vals[i-1] for i in range(1, len(y_vals))]
        if diffs_all:
            pos = sum(1 for d in diffs_all if d > 0)
            neg = sum(1 for d in diffs_all if d < 0)
            # normalized consistency between -1 and 1 (signed)
            overall_trend_info['overall_consistency'] = (pos - neg) / len(diffs_all)
            # strength = proportion of steps in the majority direction (0..1)
            overall_trend_info['overall_consistency_strength'] = max(pos, neg) / len(diffs_all)

    # Qualitative classification rules - produce separate overall and recent classifications
    overall_classification = 'insufficient data'
    recent_classification = 'insufficient data'
    # Closeness/consistency statistics (how close points are to their average)
    closeness = {
        'overall_mean': None,
        'overall_stddev': None,
        'overall_cv': None,
        'overall_within_1std': None,
        'overall_within_pct_threshold': None,
        'recent_mean': None,
        'recent_stddev': None,
        'recent_cv': None,
        'recent_within_1std': None,
        'recent_within_pct_threshold': None
    }
    if len(y_vals) >= 2:
        # thresholds for percent change
        strong_pct = 0.10
        mild_pct = 0.03

        oc = overall_trend_info['overall_consistency']
        rpc = recent_trend_info.get('recent_pct_change', 0)
        opc = overall_trend_info['overall_pct_change']
        rc = recent_trend_info.get('recent_consistency', 0)

        # Overall classification
        # Priority: large percent change -> strong inc/dec; moderate percent -> inc/dec;
        # for very small percent change, use consistency strength and direction to decide.
        abs_opc = abs(opc)
        if abs_opc >= strong_pct:
            overall_classification = 'strong increase' if opc > 0 else 'strong decrease'
        elif abs_opc >= mild_pct:
            overall_classification = 'somewhat increasing' if opc > 0 else 'somewhat decreasing'
        else:
            # Small percent change; prefer majority direction if consistent enough
            strength = overall_trend_info.get('overall_consistency_strength', 0)
            if strength >= 0.6:
                overall_classification = 'consistent increase' if overall_trend_info['overall_consistency'] > 0 else 'consistent decrease'
            else:
                # If percent change is small but the signed consistency indicates the majority direction
                if opc < 0 and overall_trend_info.get('overall_consistency', 0) < 0:
                    overall_classification = 'somewhat decreasing'
                elif opc > 0 and overall_trend_info.get('overall_consistency', 0) > 0:
                    overall_classification = 'somewhat increasing'
                else:
                    overall_classification = 'stable'

        # Recent classification (prioritize recent percent-change then strength)
        if recent_trend_info.get('recent_slope') is not None and recent_window >= 2:
            abs_rpc = abs(rpc)
            if abs_rpc >= strong_pct:
                recent_classification = 'recent strong increase' if rpc > 0 else 'recent strong decrease'
            elif abs_rpc >= mild_pct:
                recent_classification = 'recently increasing' if rpc > 0 else 'recently decreasing'
            else:
                rstrength = recent_trend_info.get('recent_consistency_strength', 0)
                if rstrength >= 0.6:
                    recent_classification = 'recent consistent increase' if recent_trend_info['recent_consistency'] > 0 else 'recent consistent decrease'
                else:
                    # If recent percent change small but recent signed consistency points to decrease, show that
                    if rpc < 0 and recent_trend_info.get('recent_consistency', 0) < 0:
                        recent_classification = 'recently decreasing'
                    elif rpc > 0 and recent_trend_info.get('recent_consistency', 0) > 0:
                        recent_classification = 'recently increasing'
                    else:
                        recent_classification = 'recently stable'

            # Compute closeness metrics (overall)
            try:
                mean_all = mean(y_vals) if y_vals else 0
                # population stddev (sample) fallback
                diffsq = [(v - mean_all) ** 2 for v in y_vals]
                stddev_all = math.sqrt(sum(diffsq) / max(1, (len(y_vals) - 1))) if len(y_vals) > 1 else 0
                cv_all = (stddev_all / mean_all) if mean_all else 0
                within_1std = sum(1 for v in y_vals if abs(v - mean_all) <= stddev_all) / len(y_vals) if len(y_vals) else 0
                pct_threshold = 0.05
                within_pct = sum(1 for v in y_vals if abs(v - mean_all) <= abs(mean_all) * pct_threshold) / len(y_vals) if len(y_vals) else 0

                closeness['overall_mean'] = mean_all
                closeness['overall_stddev'] = stddev_all
                closeness['overall_cv'] = cv_all
                closeness['overall_within_1std'] = within_1std
                closeness['overall_within_pct_threshold'] = within_pct
            except Exception:
                pass

    context = {
        'team_number': team_number,
        'team': team,
        'timeline': timeline,
        'slope': slope,
        'intercept': intercept,
        'predicted_next': predicted_next,
        'trend': overall_classification,
        'data_points': len(x_vals)
    }

    # merge trend details and classifications
    context.update(recent_trend_info)
    context.update(overall_trend_info)
    # merge closeness stats
    context.update(closeness)
    context['overall_classification'] = overall_classification
    context['recent_classification'] = recent_classification

    return render_template('team_trends/analyze.html', **context)


# Lightweight JSON endpoint for programmatic use
@bp.route('/api/analyze/<int:team_number>')
def api_analyze(team_number):
    resp = _analyze_team_json(team_number)
    return jsonify(resp)


def _analyze_team_json(team_number):
    try:
        entries = ScoutingData.query.join(Team).filter(Team.team_number == team_number).order_by(ScoutingData.timestamp).all()
    except Exception:
        entries = []

    timeline = []
    x_vals = []
    y_vals = []
    for idx, entry in enumerate(entries):
        try:
            data = entry.data
            total_points = None
            if isinstance(data, dict):
                total_points = data.get('total_points') or data.get('tot') or data.get('points')
            if total_points is None:
                numeric_values = [v for v in (data.values() if isinstance(data, dict) else []) if isinstance(v, (int, float))]
                total_points = sum(numeric_values) if numeric_values else 0
            timeline.append({'timestamp': entry.timestamp.isoformat(), 'total_points': total_points})
            x_vals.append(idx)
            y_vals.append(total_points)
        except Exception:
            continue

    slope, intercept = _simple_linear_regression(x_vals, y_vals)
    next_x = len(x_vals)
    predicted_next = slope * next_x + intercept if x_vals else 0
    trend = 'stable'
    if slope > 0.01:
        trend = 'increasing'
    elif slope < -0.01:
        trend = 'decreasing'

    return {
        'team_number': team_number,
        'data_points': len(x_vals),
        'slope': slope,
        'intercept': intercept,
        'predicted_next': predicted_next,
        'trend': trend,
        'timeline': timeline
    }
