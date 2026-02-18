from flask import Blueprint, render_template, request, current_app, jsonify
from app.models import Team, ScoutingData, Event
from app.utils.config_manager import get_effective_game_config
from app.utils.team_isolation import filter_teams_by_scouting_team, get_event_by_code
from app.utils.alliance_data import get_scouting_data_for_team, get_active_alliance_id
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


def _compute_total_points_from_data(data):
    """Compute a reasonable numeric 'total points' metric from arbitrary scouting `data`.

    This mirrors the logic used in the single-team analyzer: prefer explicit
    total_points fields if present, otherwise use the game config scoring
    elements to compute a weighted total, and finally fall back to summing
    numeric fields. Always returns a non-negative float.
    """
    total_points = None
    if isinstance(data, dict):
        total_points = data.get('total_points') or data.get('tot') or data.get('points')

    if total_points is None:
        # Use game config scoring elements to compute point totals if available
        game_config = get_effective_game_config() or {}

        def compute_period_points(period_name):
            pts = 0
            period = game_config.get(period_name, {})
            for el in period.get('scoring_elements', []):
                perm_id = el.get('perm_id') or el.get('id')
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

        total_points = 0
        total_points += compute_period_points('auto_period')
        total_points += compute_period_points('teleop_period')
        total_points += compute_period_points('endgame_period')

        # As a final fallback, if still zero, sum numeric fields
        if not total_points:
            numeric_values = [v for v in (data.values() if isinstance(data, dict) else []) if isinstance(v, (int, float))]
            total_points = sum(numeric_values) if numeric_values else 0

    try:
        total_points = float(total_points)
    except Exception:
        total_points = 0

    if total_points < 0:
        total_points = 0

    return total_points


@bp.route('/')
def index():
    # Provide a team selection dropdown populated from the current event code.
    # If a current_event_code is configured in the game config, only teams linked
    # to that event (and filtered by scouting team isolation) will be shown.
    teams = []
    try:
        game_config = get_effective_game_config() or {}
        event_code = game_config.get('current_event_code')
        if event_code:
            # Use the team isolation helper to respect multi-tenant filtering
            # Use get_all_teams_at_event to collect event teams (deduped by team_number),
            # then scope those numbers to the current user's visible teams and apply
            # deduplication preference (prefer alliance or current team's copy) to
            # avoid duplicate entries appearing in the dropdown.
            try:
                from app.utils.team_isolation import get_all_teams_at_event, dedupe_team_list, get_alliance_team_numbers, get_current_scouting_team_number
                event_teams = get_all_teams_at_event(event_code=event_code)
                team_numbers = [t.team_number for t in event_teams]
                if team_numbers:
                    scoped = filter_teams_by_scouting_team().filter(Team.team_number.in_(team_numbers)).order_by(Team.team_number).all()
                    teams = dedupe_team_list(scoped, prefer_alliance=True, alliance_team_numbers=get_alliance_team_numbers(), current_scouting_team=get_current_scouting_team_number())
                else:
                    teams = []
            except Exception:
                teams = []
        else:
            # Fallback: show all teams visible to this scouting team
            teams = filter_teams_by_scouting_team().order_by(Team.team_number).all()
    except Exception:
        teams = []

    # Support pre-selection via query param ?teams=254&teams=118 or ?teams=254,118
    selected_team_numbers = []
    try:
        # getlist will return multiple query params like ?teams=1&teams=2
        qlist = request.args.getlist('teams')
        if not qlist:
            # fallback to comma-separated single param
            qval = request.args.get('teams')
            if qval:
                qlist = [p.strip() for p in qval.split(',') if p.strip()]
        for p in qlist:
            try:
                selected_team_numbers.append(int(p))
            except Exception:
                continue
    except Exception:
        selected_team_numbers = []

    return render_template('team_trends/index.html', teams=teams, selected_team_numbers=selected_team_numbers)


@bp.route('/analyze', methods=['POST'])
def analyze_post():
    # Accept multiple teams via multi-select named 'teams' or legacy 'team_number' comma-separated input
    form_list = request.form.getlist('teams')
    if not form_list:
        # fallback to legacy single field
        team_numbers = request.form.get('team_number')
        if team_numbers:
            form_list = [p.strip() for p in str(team_numbers).split(',') if p.strip()]

    if not form_list:
        return render_template('team_trends/index.html', error='Please provide at least one team number')

    nums = []
    for part in form_list:
        try:
            nums.append(int(part))
        except Exception:
            continue

    if not nums:
        return render_template('team_trends/index.html', error='No valid team numbers provided')

    # If only one team, keep backward-compatible single-team analyze
    if len(nums) == 1:
        return _analyze_team(nums[0])

    # For multiple teams, compute combined context
    return _analyze_multiple_teams(nums)


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

    # Find all ScoutingData entries for this team - use alliance data if in alliance mode
    try:
        entries = []
        if team:
            # Use alliance-aware data retrieval
            entries, is_alliance = get_scouting_data_for_team(team.id)
            # Sort by timestamp
            entries = sorted(entries, key=lambda x: x.timestamp if x.timestamp else x.id)
        else:
            # Fallback: query by team number in Team table
            entries = ScoutingData.query.join(Team).filter(Team.team_number == team_number).order_by(ScoutingData.timestamp).all()
    except Exception:
        entries = []

    # EPA enrichment: if EPA is enabled, fetch it for potential fallback / display
    from app.utils.analysis import get_current_epa_source, get_epa_metrics_for_team
    _tt_epa_source = get_current_epa_source()
    _tt_use_epa = _tt_epa_source in ('scouted_with_statbotics', 'statbotics_only', 'tba_opr_only', 'scouted_with_tba_opr')
    _tt_statbotics_only = _tt_epa_source in ('statbotics_only', 'tba_opr_only')
    epa_data = None
    if _tt_use_epa:
        epa_data = get_epa_metrics_for_team(team_number)

    # Build timeline and compute a simple total points metric using available key metrics
    timeline = []
    x_vals = []
    y_vals = []

    if _tt_statbotics_only:
        # In statbotics-only mode, show EPA as a single flat data point
        if epa_data and epa_data.get('total'):
            y_vals.append(epa_data['total'])
            x_vals.append(0)
    else:
        for idx, entry in enumerate(entries):
            try:
                data = entry.data
                total_points = _compute_total_points_from_data(data)
                y_vals.append(total_points)
                x_vals.append(idx)
            except Exception:
                continue

        # If no scouting data but EPA is available, inject EPA baseline
        if not y_vals and epa_data and epa_data.get('total') and _tt_use_epa:
            y_vals.append(epa_data['total'])
            x_vals.append(0)

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
        'data_points': len(x_vals),
        'epa_data': epa_data,
        'epa_source': _tt_epa_source,
    }

    # merge trend details and classifications
    context.update(recent_trend_info)
    context.update(overall_trend_info)
    # merge closeness stats
    context.update(closeness)
    context['overall_classification'] = overall_classification
    context['recent_classification'] = recent_classification

    return render_template('team_trends/analyze.html', **context)


def _analyze_multiple_teams(team_numbers):
    # Build per-team timelines and summary stats for overlaying on a single chart
    datasets = []
    combined_context = {
        'team_numbers': team_numbers,
        'datasets': [],
        'data_points': 0
    }

    colors = ['rgba(54,162,235,1)','rgba(255,99,132,1)','rgba(75,192,192,1)','rgba(255,159,64,1)','rgba(153,102,255,1)','rgba(201,203,207,1)']

    for idx, tn in enumerate(team_numbers):
        try:
            # Reuse the single-team analyzer to get timeline
            # But avoid rendering templates; instead extract timeline and stats
            team = Team.query.filter_by(team_number=tn).first()
        except Exception:
            team = None

        try:
            if team:
                # Use alliance-aware data retrieval
                entries, _ = get_scouting_data_for_team(team.id)
                entries = sorted(entries, key=lambda x: x.timestamp if x.timestamp else x.id)
            else:
                entries = ScoutingData.query.join(Team).filter(Team.team_number == tn).order_by(ScoutingData.timestamp).all()
        except Exception:
            entries = []

        # EPA enrichment for multi-team trends
        from app.utils.analysis import get_current_epa_source, get_epa_metrics_for_team
        _mt_epa_source = get_current_epa_source()
        _mt_use_epa = _mt_epa_source in ('scouted_with_statbotics', 'statbotics_only', 'tba_opr_only', 'scouted_with_tba_opr')
        _mt_statbotics_only = _mt_epa_source in ('statbotics_only', 'tba_opr_only')
        _mt_epa_data = None
        if _mt_use_epa:
            _mt_epa_data = get_epa_metrics_for_team(tn)

        timeline = []
        x_vals = []
        y_vals = []

        if _mt_statbotics_only:
            # In statbotics-only mode, show EPA as a single flat data point
            if _mt_epa_data and _mt_epa_data.get('total'):
                y_vals.append(_mt_epa_data['total'])
                x_vals.append(0)
                timeline.append({'timestamp': None, 'total_points': _mt_epa_data['total']})
        else:
            for i, entry in enumerate(entries):
                try:
                    data = entry.data
                    tp = _compute_total_points_from_data(data)
                    timeline.append({'timestamp': entry.timestamp.isoformat(), 'total_points': tp})
                    x_vals.append(i)
                    y_vals.append(tp)
                except Exception:
                    continue

            # If no scouting data but EPA is available, inject EPA baseline
            if not y_vals and _mt_epa_data and _mt_epa_data.get('total') and _mt_use_epa:
                y_vals.append(_mt_epa_data['total'])
                x_vals.append(0)
                timeline.append({'timestamp': None, 'total_points': _mt_epa_data['total']})

        # Compute simple regression and basic stats for this team's timeline
        try:
            slope, intercept = _simple_linear_regression(x_vals, y_vals)
            next_x = len(x_vals)
            predicted = slope * next_x + intercept if x_vals else 0
        except Exception:
            slope, intercept, predicted = 0, 0, 0

        mean_val = None
        stddev_val = None
        cv_val = None
        try:
            if y_vals:
                mean_val = mean(y_vals)
                diffsq = [(v - mean_val) ** 2 for v in y_vals]
                stddev_val = math.sqrt(sum(diffsq) / max(1, (len(y_vals) - 1))) if len(y_vals) > 1 else 0
                cv_val = (stddev_val / mean_val) if mean_val else 0
        except Exception:
            pass

        dataset = {
            'team_number': tn,
            'team_name': team.team_name if team else None,
            'timeline': timeline,
            'color': colors[idx % len(colors)],
            'slope': slope,
            'intercept': intercept,
            'predicted_next': predicted,
            'mean': mean_val,
            'stddev': stddev_val,
            'cv': cv_val
        }
        combined_context['datasets'].append(dataset)
        combined_context['data_points'] = max(combined_context['data_points'], len(timeline))

        # Log per-team computed stats for debugging/verification
        try:
            # Use INFO so it's visible in typical server logs; also print to stdout
            msg = f"team_trends: team={tn} predicted_next={dataset.get('predicted_next')} mean={dataset.get('mean')} stddev={dataset.get('stddev')}"
            current_app.logger.info(msg)
            try:
                print(msg)
            except Exception:
                pass
        except Exception:
            pass

    # Provide fallback summary keys expected by the single-team template
    # so the analyze template can render without undefined errors when
    # datasets (multi-team overlay) is present.
    combined_context.setdefault('team_number', None)
    combined_context.setdefault('team', None)
    combined_context.setdefault('overall_mean', None)
    combined_context.setdefault('overall_stddev', None)
    combined_context.setdefault('overall_cv', None)
    combined_context.setdefault('overall_classification', 'multiple teams')
    combined_context.setdefault('recent_classification', 'multiple teams')
    combined_context.setdefault('predicted_next', 0)

    # Indicate whether any dataset contains timeline rows so the template can
    # display a friendly message when there is no data to plot.
    combined_context['has_data'] = any(len(ds.get('timeline') or []) > 0 for ds in combined_context['datasets'])

    return render_template('team_trends/analyze.html', **combined_context)


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
