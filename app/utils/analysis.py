from app.models import ScoutingData, Team, Match, TeamAllianceStatus
import statistics
from flask import current_app
import random
from app.utils.config_manager import get_current_game_config, load_game_config
from app.utils.team_isolation import filter_scouting_data_by_scouting_team, get_current_scouting_team_number, filter_scouting_data_only_by_scouting_team

def calculate_team_metrics(team_id, event_id=None, game_config=None):
    """Calculate key performance metrics for a team based on their scouting data using dynamic period calculations
    
    Args:
        team_id: The ID of the team to calculate metrics for
        event_id: Optional event ID to filter scouting data by event
    """
    # Get the team object to log the team number
    team = Team.query.get(team_id)
    team_number = team.team_number if team else team_id
    
    # Get all scouting data for this team.
    # If the team is currently in alliance-mode, use scouting data shared by alliance members.
    # Otherwise, respect the normal scouting team isolation rules.
    def _get_scouting_data_for_team(team_obj, event_filter=None):
        """Return a list of ScoutingData objects to use for analytics for the given Team object or id."""
        # Accept either Team instance or team id
        if isinstance(team_obj, int):
            team_obj = Team.query.get(team_obj)
        if not team_obj:
            return []

        # Check if alliance mode is active for this team_number
        try:
            if TeamAllianceStatus.is_alliance_mode_active_for_team(team_obj.team_number):
                alliance = TeamAllianceStatus.get_active_alliance_for_team(team_obj.team_number)
                if alliance:
                    member_numbers = alliance.get_member_team_numbers()
                    # Use scouting entries contributed by alliance members for this team
                    query = ScoutingData.query.filter(ScoutingData.team_id == team_obj.id,
                                                     ScoutingData.scouting_team_number.in_(member_numbers))
                    # Apply event filter if provided
                    if event_filter:
                        query = query.join(Match).filter(Match.event_id == event_filter)
                    return query.all()
        except Exception:
            # Fall back to normal isolation if alliance lookup fails
            pass

        # Default behavior: Use EXACT same filter as /data/manage for consistency
        # This ensures predictions see exactly the same data that appears in /data/manage
        scouting_team_number = get_current_scouting_team_number()
        print(f"    DEBUG: Current scouting_team_number = {scouting_team_number}")
        if scouting_team_number is not None:
            # Use exact match filter (same as /data/manage) - no NULL entries
            query = ScoutingData.query.filter_by(team_id=team_obj.id, scouting_team_number=scouting_team_number)
            # Apply event filter if provided
            if event_filter:
                query = query.join(Match).filter(Match.event_id == event_filter)
            results = query.all()
            print(f"    DEBUG: Found {len(results)} scouting entries for team {team_obj.team_number} with scouting_team {scouting_team_number} and event_filter={event_filter}")
            return results
        
        query = ScoutingData.query.filter_by(team_id=team_obj.id, scouting_team_number=None)
        # Apply event filter if provided - get match IDs first to avoid JOIN issues
        if event_filter:
            match_ids = [m.id for m in Match.query.filter_by(event_id=event_filter).all()]
            if match_ids:
                query = query.filter(ScoutingData.match_id.in_(match_ids))
            else:
                return []
        return query.all()
    
    scouting_data = _get_scouting_data_for_team(team, event_id)

    if not scouting_data:
        print(f"    No scouting data found for team {team_number} (ID: {team_id})")
        return {
            'team_number': team_number,
            'match_count': 0,
            'metrics': {}
        }
    else:
        print(f"    Found {len(scouting_data)} scouting records for team {team_number}")
        
    # Initialize metrics dictionary
    metrics = {}
    
    # Get game configuration (use provided game_config if given, otherwise fall back to current user's config)
    if game_config is None:
        game_config = get_current_game_config()
    
    # Calculate dynamic period-based metrics
    auto_values = []
    teleop_values = []
    endgame_values = []
    total_values = []
    
    print(f"    Calculating dynamic metrics across {len(scouting_data)} matches:")
    for idx, data in enumerate(scouting_data):
        match_info = f"Match {data.match.match_number}" if data.match else f"Record #{idx+1}"
        
        # Calculate points for each period using dynamic methods
        auto_pts = data._calculate_auto_points_dynamic(data.data, game_config)
        teleop_pts = data._calculate_teleop_points_dynamic(data.data, game_config)
        endgame_pts = data._calculate_endgame_points_dynamic(data.data, game_config)
        total_pts = auto_pts + teleop_pts + endgame_pts
        
        auto_values.append(auto_pts)
        teleop_values.append(teleop_pts)
        endgame_values.append(endgame_pts)
        total_values.append(total_pts)
        
        print(f"      {match_info}: total={total_pts} (auto={auto_pts}, teleop={teleop_pts}, endgame={endgame_pts})")
    
    # Calculate statistics for each metric
    def calculate_stats(values, metric_name):
        if values:
            avg = statistics.mean(values)
            std = statistics.stdev(values) if len(values) > 1 else 0.0
            metrics[metric_name] = avg
            metrics[f"{metric_name}_std"] = std
            return avg, std
        return 0, 0
    
    # Store dynamic period metrics
    auto_avg, auto_std = calculate_stats(auto_values, 'auto_points')
    teleop_avg, teleop_std = calculate_stats(teleop_values, 'teleop_points')
    endgame_avg, endgame_std = calculate_stats(endgame_values, 'endgame_points')
    total_avg, total_std = calculate_stats(total_values, 'total_points')
    
    print(f"    Final averages: auto={auto_avg:.1f}, teleop={teleop_avg:.1f}, endgame={endgame_avg:.1f}, total={total_avg:.1f}")
    
    # Calculate endgame capability - find highest position this team has demonstrated
    endgame_positions = []
    endgame_field_id = None
    
    # Find endgame position field dynamically from config
    # Respect show/display_in_predictions flag: prefer only elements where they're True (default True for backward compatibility)
    def element_visible(el):
        return el.get('show_in_predictions', el.get('display_in_predictions', True))

    # Treat a variety of choice-like element types as selectable endgame position fields
    choice_types = {'select', 'multiple_choice', 'multiple-choice', 'single_choice', 'single-choice', 'choice', 'multiplechoice'}

    scoring_elements = game_config.get('endgame_period', {}).get('scoring_elements', [])
    for element in scoring_elements:
        if not element_visible(element):
            continue
        if element.get('type') and element.get('type').lower() in choice_types and 'position' in element.get('name', '').lower():
            endgame_field_id = element.get('id')
            break
    # If not found with 'position' in name, pick the first visible choice-like element
    if not endgame_field_id:
        for element in scoring_elements:
            if not element_visible(element):
                continue
            if element.get('type') and element.get('type').lower() in choice_types:
                endgame_field_id = element.get('id')
                break
    
    if endgame_field_id:
        for data in scouting_data:
            if endgame_field_id in data.data:
                endgame_positions.append(data.data[endgame_field_id])
    
    # Calculate endgame capability from positions
    if endgame_positions:
        position_points = {}
        # Build a points mapping from the chosen element; support both dict-style 'points' and list-style 'options'
        position_points = {}
        for element in scoring_elements:
            if not element_visible(element):
                continue
            if element.get('type') and element.get('type').lower() in choice_types and 'position' in element.get('name', '').lower():
                if isinstance(element.get('points'), dict) and element.get('points'):
                    position_points = element.get('points', {})
                elif isinstance(element.get('options'), list):
                    for opt in element.get('options', []):
                        # options may be dicts with 'name' and 'points'
                        if isinstance(opt, dict):
                            name = opt.get('name')
                            pts = opt.get('points', 0)
                            if name:
                                position_points[name] = pts
                break
        
        highest_position = "None"
        highest_points = 0
        
        if position_points:
            for position in endgame_positions:
                if position in position_points and position_points[position] > highest_points:
                    highest_points = position_points[position]
                    highest_position = position
        
        metrics['endgame_capability'] = highest_points
        metrics['endgame_position_name'] = highest_position
    
    # Add backwards compatibility - if key_metrics exist in config, calculate them too
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        print("    Also calculating legacy key_metrics from config for backwards compatibility")
        for metric in game_config['data_analysis']['key_metrics']:
            metric_id = metric.get('id')
            metric_formula = metric.get('formula')
            
            # Skip if we already calculated this metric dynamically
            if metric_id in ['auto_points', 'teleop_points', 'endgame_points', 'total_points']:
                continue
            
            # Calculate legacy metric
            values = []
            for data in scouting_data:
                value = data.calculate_metric(metric_formula)
                values.append(value)
            
            if values:
                metrics[metric_id] = statistics.mean(values)
                metrics[f"{metric_id}_std"] = statistics.stdev(values) if len(values) > 1 else 0.0
    
    return {
        'team_number': team_number,
        'match_count': len(scouting_data),
        'metrics': metrics
    }


def _simulate_match_outcomes(red_alliance_teams, blue_alliance_teams, total_metric_id, n_simulations=2000, seed=None):
    """Monte Carlo simulate match outcomes using per-team mean/std for total metric.

    Returns a dict with expected_red, expected_blue, win_probability_for_red.
    """
    if seed is not None:
        random.seed(seed)

    red_means = []
    red_stds = []
    for team_data in red_alliance_teams:
        m = team_data['metrics'].get(total_metric_id, team_data['metrics'].get('total_points', 0.0))
        s = team_data['metrics'].get(f"{total_metric_id}_std", team_data['metrics'].get('total_points_std', 0.0))
        red_means.append(float(m))
        red_stds.append(max(0.0, float(s)))

    blue_means = []
    blue_stds = []
    for team_data in blue_alliance_teams:
        m = team_data['metrics'].get(total_metric_id, team_data['metrics'].get('total_points', 0.0))
        s = team_data['metrics'].get(f"{total_metric_id}_std", team_data['metrics'].get('total_points_std', 0.0))
        blue_means.append(float(m))
        blue_stds.append(max(0.0, float(s)))

    # If no teams or no data, fall back to deterministic sum
    if not red_means and not blue_means:
        return {'expected_red': 0.0, 'expected_blue': 0.0, 'red_win_prob': 0.5}

    red_wins = 0
    blue_wins = 0
    ties = 0
    total_red = 0.0
    total_blue = 0.0

    # Pre-calc deterministic sums when std is zero to speed up
    red_det = sum(red_means)
    blue_det = sum(blue_means)

    # If all stds are zero, deterministic outcome
    if all(s == 0.0 for s in red_stds) and all(s == 0.0 for s in blue_stds):
        red_score = red_det
        blue_score = blue_det
        if red_score > blue_score:
            return {'expected_red': red_score, 'expected_blue': blue_score, 'red_win_prob': 1.0, 'blue_win_prob': 0.0, 'tie_prob': 0.0}
        elif blue_score > red_score:
            return {'expected_red': red_score, 'expected_blue': blue_score, 'red_win_prob': 0.0, 'blue_win_prob': 1.0, 'tie_prob': 0.0}
        else:
            return {'expected_red': red_score, 'expected_blue': blue_score, 'red_win_prob': 0.0, 'blue_win_prob': 0.0, 'tie_prob': 1.0}

    for _ in range(n_simulations):
        # sample per-team totals
        sim_red = 0.0
        for m, s in zip(red_means, red_stds):
            if s > 0:
                val = random.gauss(m, s)
            else:
                val = m
            sim_red += max(0.0, val)

        sim_blue = 0.0
        for m, s in zip(blue_means, blue_stds):
            if s > 0:
                val = random.gauss(m, s)
            else:
                val = m
            sim_blue += max(0.0, val)

        total_red += sim_red
        total_blue += sim_blue
        if sim_red > sim_blue:
            red_wins += 1
        elif sim_blue > sim_red:
            blue_wins += 1
        else:
            ties += 1

    expected_red = total_red / n_simulations
    expected_blue = total_blue / n_simulations
    red_win_prob = red_wins / n_simulations
    blue_win_prob = blue_wins / n_simulations
    tie_prob = ties / n_simulations

    return {'expected_red': expected_red, 'expected_blue': expected_blue, 'red_win_prob': red_win_prob, 'blue_win_prob': blue_win_prob, 'tie_prob': tie_prob}

def predict_match_outcome(match_id):
    """Predict the outcome of a match based on team performance metrics"""
    match = Match.query.get(match_id)
    if not match:
        return None
    
    print("\n" + "="*80)
    print(f"PREDICTING MATCH {match.match_type} {match.match_number} (ID: {match_id})")
    print("="*80)
    
    # Get team numbers for each alliance from the alliance strings
    # Alliance fields store comma-separated team numbers like "118,254,2767"
    red_team_numbers = match.red_alliance.split(',') if match.red_alliance else []
    blue_team_numbers = match.blue_alliance.split(',') if match.blue_alliance else []
    
    print(f"DEBUG: Raw red alliance string: '{match.red_alliance}'")
    print(f"DEBUG: Raw blue alliance string: '{match.blue_alliance}'")
    print(f"DEBUG: Initial parsed red team numbers: {red_team_numbers}")
    print(f"DEBUG: Initial parsed blue team numbers: {blue_team_numbers}")
    
    # Clean up team numbers - strip whitespace and convert to integers
    red_team_numbers_int = []
    for num in red_team_numbers:
        num = num.strip()
        if num and num.isdigit():
            red_team_numbers_int.append(int(num))
        else:
            print(f"WARNING: Invalid red team number: '{num}'")
    
    blue_team_numbers_int = []
    for num in blue_team_numbers:
        num = num.strip()
        if num and num.isdigit():
            blue_team_numbers_int.append(int(num))
        else:
            print(f"WARNING: Invalid blue team number: '{num}'")
    
    print(f"DEBUG: Cleaned red team numbers: {red_team_numbers_int}")
    print(f"DEBUG: Cleaned blue team numbers: {blue_team_numbers_int}")
    
    # Query teams - check if any teams are missing from the database
    all_team_numbers = red_team_numbers_int + blue_team_numbers_int
    all_teams = Team.query.filter(Team.team_number.in_(all_team_numbers)).all() if all_team_numbers else []
    found_team_numbers = [team.team_number for team in all_teams]
    
    missing_teams = [num for num in all_team_numbers if num not in found_team_numbers]
    if missing_teams:
        print(f"WARNING: These teams are not in the database: {missing_teams}")
    
    # Query teams
    red_teams = []
    blue_teams = []
    
    for team in all_teams:
        if team.team_number in red_team_numbers_int:
            red_teams.append(team)
        elif team.team_number in blue_team_numbers_int:
            blue_teams.append(team)
    
    print(f"DEBUG: Found {len(red_teams)} red teams: {[team.team_number for team in red_teams]}")
    print(f"DEBUG: Found {len(blue_teams)} blue teams: {[team.team_number for team in blue_teams]}")
    
    # Calculate team metrics and alliance strength
    red_alliance_teams = []
    print("\nRED ALLIANCE METRICS:")
    for team in red_teams:
        print(f"  Calculating metrics for red team {team.team_number} (ID: {team.id})")
        # Load the specific team's config so we respect their endgame elements
        try:
            team_config = load_game_config(team_number=team.team_number)
        except Exception:
            team_config = None
        # Pass event_id so we only use data from the match's event
        analytics_result = calculate_team_metrics(team.id, event_id=match.event_id, game_config=team_config)
        metrics = analytics_result.get('metrics', {})
        
        if metrics:
            print(f"  Team {team.team_number} has metrics: {list(metrics.keys())}")
            # Check for critical metrics
            if not metrics.get('total_points') and not any(key for key in metrics.keys() if 'tot' in key.lower()):
                print(f"  WARNING: Team {team.team_number} missing total points metric!")
            red_alliance_teams.append({
                'team': team,
                'metrics': metrics
            })
        else:
            print(f"  WARNING: No metrics found for team {team.team_number}")
    
    blue_alliance_teams = []
    print("\nBLUE ALLIANCE METRICS:")
    for team in blue_teams:
        print(f"  Calculating metrics for blue team {team.team_number} (ID: {team.id})")
        try:
            team_config = load_game_config(team_number=team.team_number)
        except Exception:
            team_config = None
        # Pass event_id so we only use data from the match's event
        analytics_result = calculate_team_metrics(team.id, event_id=match.event_id, game_config=team_config)
        metrics = analytics_result.get('metrics', {})
        
        if metrics:
            print(f"  Team {team.team_number} has metrics: {list(metrics.keys())}")
            # Check for critical metrics
            if not metrics.get('total_points') and not any(key for key in metrics.keys() if 'tot' in key.lower()):
                print(f"  WARNING: Team {team.team_number} missing total points metric!")
            blue_alliance_teams.append({
                'team': team,
                'metrics': metrics
            })
        else:
            print(f"  WARNING: No metrics found for team {team.team_number}")
            
    print(f"\nFinal red alliance teams for prediction: {[team_data['team'].team_number for team_data in red_alliance_teams]}")
    print(f"Final blue alliance teams for prediction: {[team_data['team'].team_number for team_data in blue_alliance_teams]}")
    
    # Get game configuration to find total_metric_id
    game_config = get_current_game_config()
    total_metric_id = None
    
    # Identify metrics from game config
    print("\nLOOKING FOR TOTAL METRIC ID:")
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            metric_id = metric.get('id')
            # Check if this is the total metric
            if 'total' in metric_id.lower() or 'tot' == metric_id.lower():
                total_metric_id = metric_id
                print(f"  Found total metric ID: {total_metric_id}")
                break
    
    # If no total metric defined, use default ID
    if not total_metric_id:
        total_metric_id = "tot"
        print(f"  No total metric found in config, using default: {total_metric_id}")
    
    # Calculate alliance scores based on total points (predictive model)
    red_alliance_score = 0
    print("\nCALCULATING RED ALLIANCE SCORE:")
    for team_data in red_alliance_teams:
        team_number = team_data['team'].team_number
        # Try different metric IDs in order of preference
        team_score = 0
        if total_metric_id in team_data['metrics']:
            team_score = team_data['metrics'][total_metric_id]
            print(f"  Team {team_number}: {team_score} points from {total_metric_id}")
        elif 'total_points' in team_data['metrics']:
            team_score = team_data['metrics']['total_points']
            print(f"  Team {team_number}: {team_score} points from total_points")
        else:
            print(f"  WARNING: Team {team_number} has no total points metric!")
        
        red_alliance_score += team_score
    
    blue_alliance_score = 0
    print("\nCALCULATING BLUE ALLIANCE SCORE:")
    for team_data in blue_alliance_teams:
        team_number = team_data['team'].team_number
        # Try different metric IDs in order of preference
        team_score = 0
        if total_metric_id in team_data['metrics']:
            team_score = team_data['metrics'][total_metric_id]
            print(f"  Team {team_number}: {team_score} points from {total_metric_id}")
        elif 'total_points' in team_data['metrics']:
            team_score = team_data['metrics']['total_points']
            print(f"  Team {team_number}: {team_score} points from total_points")
        else:
            print(f"  WARNING: Team {team_number} has no total points metric!")
        
        blue_alliance_score += team_score
    
    # Perform Monte Carlo simulation using per-team totals and stddevs (if available)
    sim = _simulate_match_outcomes(red_alliance_teams, blue_alliance_teams, total_metric_id, n_simulations=2000)

    expected_red = sim.get('expected_red', red_alliance_score)
    expected_blue = sim.get('expected_blue', blue_alliance_score)
    red_win_prob = sim.get('red_win_prob', 0.5)
    blue_win_prob = sim.get('blue_win_prob', 1.0 - red_win_prob)
    tie_prob = sim.get('tie_prob', 0.0)

    print(f"\nSIMULATION RESULTS:")
    print(f"  Expected red score: {expected_red:.1f}")
    print(f"  Expected blue score: {expected_blue:.1f}")
    print(f"  Red win probability: {red_win_prob*100:.1f}%")

    # Pick predicted winner based on the highest probability among red/blue/tie
    probs = {'red': red_win_prob, 'blue': blue_win_prob, 'tie': tie_prob}
    # Choose the outcome with the maximum probability; ties will be chosen if that has highest prob
    winner = max(probs.items(), key=lambda kv: kv[1])[0]

    print(f"  Predicted winner: {winner.upper()} with probability: {red_win_prob*100:.1f}% (red win prob)")
    print("="*80 + "\n")

    prediction = {
        'red_alliance': {
            'teams': red_alliance_teams,
            'predicted_score': round(expected_red)
        },
        'blue_alliance': {
            'teams': blue_alliance_teams,
            'predicted_score': round(expected_blue)
        },
        'predicted_winner': winner,
        # Provide a breakdown of probabilities for consumers (red/blue/tie)
        'probabilities': {
            'red': red_win_prob,
            'blue': blue_win_prob,
            'tie': tie_prob
        },
        # For backward compatibility many templates use 'confidence' - set to the probability of the predicted outcome
        'confidence': probs.get(winner, red_win_prob)
    }
    
    return prediction

def get_match_details_with_teams(match_id):
    """Get complete match details with team information and metrics"""
    match = Match.query.get(match_id)
    if not match:
        return None
        
    # Get prediction data
    prediction = predict_match_outcome(match_id)
    
    # Enhance with actual match score if available
    if match.red_score is not None and match.blue_score is not None:
        match_completed = True
        actual_winner = 'red' if match.red_score > match.blue_score else 'blue' if match.blue_score > match.red_score else 'tie'
    else:
        match_completed = False
        actual_winner = None
    
    # Combine everything into a complete match report
    match_details = {
        'match': match,
        'prediction': prediction,
        'match_completed': match_completed,
        'actual_winner': actual_winner,
        'prediction_correct': match_completed and prediction and actual_winner == prediction['predicted_winner']
    }
    
    return match_details

def generate_match_strategy_analysis(match_id):
    """Generate comprehensive strategy analysis for a match, including both alliances"""
    print(f"\n=== GENERATING STRATEGY ANALYSIS FOR MATCH {match_id} ===")
    
    # Get the match
    match = Match.query.get(match_id)
    if not match:
        print(f"Match {match_id} not found")
        return None
    
    # Get team numbers for each alliance
    red_team_numbers = match.red_alliance.split(',') if match.red_alliance else []
    blue_team_numbers = match.blue_alliance.split(',') if match.blue_alliance else []
    
    # Clean and convert to integers
    red_team_numbers = [int(num.strip()) for num in red_team_numbers if num.strip()]
    blue_team_numbers = [int(num.strip()) for num in blue_team_numbers if num.strip()]
    
    print(f"Red Alliance: {red_team_numbers}")
    print(f"Blue Alliance: {blue_team_numbers}")
    
    # Get all team numbers
    all_team_numbers = red_team_numbers + blue_team_numbers
    
    # Query teams
    all_teams = Team.query.filter(Team.team_number.in_(all_team_numbers)).all() if all_team_numbers else []
    
    # Separate teams by alliance
    red_teams = []
    blue_teams = []
    
    for team in all_teams:
        if team.team_number in red_team_numbers:
            red_teams.append(team)
        elif team.team_number in blue_team_numbers:
            blue_teams.append(team)
    
    # Get game configuration
    game_config = get_current_game_config()
    
    # Calculate detailed metrics for each team
    red_alliance_data = []
    for team in red_teams:
        # Pass event_id so we only use data from the match's event
        analytics_result = calculate_team_metrics(team.id, event_id=match.event_id)
        team_metrics = analytics_result.get('metrics', {})
        # Use alliance-aware scouting data retrieval (mirror calculate_team_metrics behavior)
        try:
            if TeamAllianceStatus.is_alliance_mode_active_for_team(team.team_number):
                alliance = TeamAllianceStatus.get_active_alliance_for_team(team.team_number)
                if alliance:
                    member_numbers = alliance.get_member_team_numbers()
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter(ScoutingData.team_id == team.id,
                                                                 ScoutingData.scouting_team_number.in_(member_numbers),
                                                                 ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
                else:
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=get_current_scouting_team_number()).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
            else:
                scouting_team_number = get_current_scouting_team_number()
                if scouting_team_number is not None:
                    # Use exact match filter (same as /data/manage) with match_ids instead of JOIN
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=scouting_team_number).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
                    print(f"    DEBUG RED: Team {team.team_number} - Found {len(scouting_records)} records with scouting_team={scouting_team_number}, event={match.event_id}")
                else:
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=None).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
        except Exception as e:
            print(f"    DEBUG RED ERROR: Team {team.team_number} - Exception: {e}")
            match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
            scouting_records = ScoutingData.query.filter_by(team_id=team.id).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []

        team_data = {
            'team': team,
            'metrics': team_metrics,
            'scouting_data': scouting_records
        }
        red_alliance_data.append(team_data)
    
    blue_alliance_data = []
    for team in blue_teams:
        # Pass event_id so we only use data from the match's event
        analytics_result = calculate_team_metrics(team.id, event_id=match.event_id)
        team_metrics = analytics_result.get('metrics', {})
        try:
            if TeamAllianceStatus.is_alliance_mode_active_for_team(team.team_number):
                alliance = TeamAllianceStatus.get_active_alliance_for_team(team.team_number)
                if alliance:
                    member_numbers = alliance.get_member_team_numbers()
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter(ScoutingData.team_id == team.id,
                                                                 ScoutingData.scouting_team_number.in_(member_numbers),
                                                                 ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
                else:
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=get_current_scouting_team_number()).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
            else:
                scouting_team_number = get_current_scouting_team_number()
                if scouting_team_number is not None:
                    # Use exact match filter (same as /data/manage) with match_ids instead of JOIN
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=scouting_team_number).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
                    print(f"    DEBUG BLUE: Team {team.team_number} - Found {len(scouting_records)} records with scouting_team={scouting_team_number}, event={match.event_id}")
                else:
                    match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
                    scouting_records = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=None).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []
        except Exception as e:
            print(f"    DEBUG BLUE ERROR: Team {team.team_number} - Exception: {e}")
            match_ids = [m.id for m in Match.query.filter_by(event_id=match.event_id).all()]
            scouting_records = ScoutingData.query.filter_by(team_id=team.id).filter(ScoutingData.match_id.in_(match_ids)).all() if match_ids else []

        team_data = {
            'team': team,
            'metrics': team_metrics,
            'scouting_data': scouting_records
        }
        blue_alliance_data.append(team_data)
    
    # Generate strategy insights
    strategy_analysis = {
        'match': {
            'id': match.id,
            'number': match.match_number,
            'type': match.match_type,
            'event': match.event.name if match.event else 'Unknown Event'
        },
        'red_alliance': {
            'teams': red_alliance_data,
            'strategy': _generate_alliance_strategy(red_alliance_data, 'red', game_config),
            'strengths': _analyze_alliance_strengths(red_alliance_data, game_config),
            'weaknesses': _analyze_alliance_weaknesses(red_alliance_data, game_config),
            'recommendations': _generate_alliance_recommendations(red_alliance_data, 'red', game_config),
            'endgame_analysis': _analyze_alliance_endgame_coordination(red_alliance_data, game_config)
        },
        'blue_alliance': {
            'teams': blue_alliance_data,
            'strategy': _generate_alliance_strategy(blue_alliance_data, 'blue', game_config),
            'strengths': _analyze_alliance_strengths(blue_alliance_data, game_config),
            'weaknesses': _analyze_alliance_weaknesses(blue_alliance_data, game_config),
            'recommendations': _generate_alliance_recommendations(blue_alliance_data, 'blue', game_config),
            'endgame_analysis': _analyze_alliance_endgame_coordination(blue_alliance_data, game_config)
        },
        'matchup_analysis': _generate_matchup_analysis(red_alliance_data, blue_alliance_data, game_config),
        'key_battles': _identify_key_battles(red_alliance_data, blue_alliance_data, game_config),
        'predicted_outcome': _predict_strategy_outcome(red_alliance_data, blue_alliance_data, game_config),
        'graph_data': _generate_strategy_graph_data(red_alliance_data, blue_alliance_data, game_config)
    }
    
    return strategy_analysis

def _generate_alliance_strategy(alliance_data, alliance_color, game_config):
    """Generate strategy recommendations for an alliance"""
    if not alliance_data:
        return {"overview": "No data available for strategy analysis"}
    
    # Analyze team strengths and roles
    strategies = []
    
    # Get key metrics from config
    key_metrics = game_config.get('data_analysis', {}).get('key_metrics', [])
    
    # Analyze auto performance
    auto_scores = []
    for team_data in alliance_data:
        auto_score = team_data['metrics'].get('apt', team_data['metrics'].get('auto_points', 0))
        auto_scores.append(auto_score)
    
    if auto_scores:
        avg_auto = sum(auto_scores) / len(auto_scores)
        if avg_auto > 10:
            strategies.append("Strong auto performance - prioritize consistent autonomous routines")
        elif avg_auto > 5:
            strategies.append("Moderate auto performance - focus on reliable scoring")
        else:
            strategies.append("Weak auto performance - focus on defensive positioning")
    
    # Analyze teleop performance
    teleop_scores = []
    for team_data in alliance_data:
        teleop_score = team_data['metrics'].get('tpt', team_data['metrics'].get('teleop_points', 0))
        teleop_scores.append(teleop_score)
    
    if teleop_scores:
        avg_teleop = sum(teleop_scores) / len(teleop_scores)
        if avg_teleop > 30:
            strategies.append("Excellent teleop scoring - maintain aggressive offensive strategy")
        elif avg_teleop > 15:
            strategies.append("Good teleop scoring - balance offense and defense")
        else:
            strategies.append("Focus on defensive play and support roles")
    
    # Analyze endgame performance
    endgame_scores = []
    for team_data in alliance_data:
        endgame_score = team_data['metrics'].get('ept', team_data['metrics'].get('endgame_points', 0))
        endgame_scores.append(endgame_score)
    
    if endgame_scores:
        avg_endgame = sum(endgame_scores) / len(endgame_scores)
        if avg_endgame > 15:
            strategies.append("Strong endgame capabilities - coordinate climbing/parking")
        elif avg_endgame > 8:
            strategies.append("Moderate endgame - ensure at least 2 robots engage")
        else:
            strategies.append("Weak endgame - focus on teleop scoring until final 30 seconds")
    
    return {
        "overview": f"Strategy recommendations for {alliance_color} alliance",
        "key_strategies": strategies,
        "coordination_notes": [
            "Establish clear communication protocols",
            "Assign primary and secondary roles for each game period",
            "Plan contingencies for robot failures or penalties"
        ]
    }

def _analyze_alliance_strengths(alliance_data, game_config):
    """Analyze the strengths of an alliance"""
    if not alliance_data:
        return []
    
    strengths = []
    
    # Calculate alliance averages
    total_scores = []
    auto_scores = []
    teleop_scores = []
    endgame_scores = []
    
    for team_data in alliance_data:
        metrics = team_data['metrics']
        total_scores.append(metrics.get('tot', metrics.get('total_points', 0)))
        auto_scores.append(metrics.get('apt', metrics.get('auto_points', 0)))
        teleop_scores.append(metrics.get('tpt', metrics.get('teleop_points', 0)))
        endgame_scores.append(metrics.get('ept', metrics.get('endgame_points', 0)))
    
    # Analyze strengths
    if total_scores and sum(total_scores) / len(total_scores) > 40:
        strengths.append("High overall scoring capability")
    
    if auto_scores and sum(auto_scores) / len(auto_scores) > 8:
        strengths.append("Strong autonomous performance")
    
    if teleop_scores and sum(teleop_scores) / len(teleop_scores) > 25:
        strengths.append("Excellent teleop scoring")
    
    if endgame_scores and sum(endgame_scores) / len(endgame_scores) > 12:
        strengths.append("Reliable endgame execution")
    
    # Check for consistency
    if total_scores and len(set(total_scores)) < len(total_scores) * 0.8:
        strengths.append("Consistent performance across teams")
    
    return strengths

def _analyze_alliance_weaknesses(alliance_data, game_config):
    """Analyze the weaknesses of an alliance"""
    if not alliance_data:
        return []
    
    weaknesses = []
    
    # Calculate alliance averages
    total_scores = []
    auto_scores = []
    teleop_scores = []
    endgame_scores = []
    
    for team_data in alliance_data:
        metrics = team_data['metrics']
        total_scores.append(metrics.get('tot', metrics.get('total_points', 0)))
        auto_scores.append(metrics.get('apt', metrics.get('auto_points', 0)))
        teleop_scores.append(metrics.get('tpt', metrics.get('teleop_points', 0)))
        endgame_scores.append(metrics.get('ept', metrics.get('endgame_points', 0)))
    
    # Analyze weaknesses
    if auto_scores and sum(auto_scores) / len(auto_scores) < 5:
        weaknesses.append("Poor autonomous performance")
    
    if teleop_scores and sum(teleop_scores) / len(teleop_scores) < 15:
        weaknesses.append("Limited teleop scoring capability")
    
    if endgame_scores and sum(endgame_scores) / len(endgame_scores) < 8:
        weaknesses.append("Weak endgame execution")
    
    # Check for inconsistency
    if total_scores and statistics.stdev(total_scores) > 15:
        weaknesses.append("Inconsistent performance across teams")
    
    return weaknesses

def _generate_alliance_recommendations(alliance_data, alliance_color, game_config):
    """Generate specific recommendations for an alliance"""
    if not alliance_data:
        return []
    
    recommendations = []
    
    # Team-specific recommendations
    for i, team_data in enumerate(alliance_data):
        team = team_data['team']
        metrics = team_data['metrics']
        
        total_score = metrics.get('tot', metrics.get('total_points', 0))
        auto_score = metrics.get('apt', metrics.get('auto_points', 0))
        teleop_score = metrics.get('tpt', metrics.get('teleop_points', 0))
        endgame_score = metrics.get('ept', metrics.get('endgame_points', 0))
        
        # Assign roles based on performance
        if total_score > 40:
            recommendations.append(f"Team {team.team_number}: Primary scorer - focus on high-value targets")
        elif total_score > 25:
            recommendations.append(f"Team {team.team_number}: Secondary scorer - support primary and play defense")
        else:
            recommendations.append(f"Team {team.team_number}: Defensive specialist - disrupt opponent scoring")
        
        # Period-specific recommendations
        if auto_score > 10:
            recommendations.append(f"Team {team.team_number}: Execute autonomous routine reliably")
        
        if endgame_score > 15:
            recommendations.append(f"Team {team.team_number}: Lead endgame coordination")
    
    # Overall alliance recommendations
    recommendations.append(f"Alliance coordination: Maintain communication throughout match")
    recommendations.append(f"Backup plan: Have contingency for robot failures")
    
    return recommendations

def _generate_matchup_analysis(red_alliance_data, blue_alliance_data, game_config):
    """Analyze the matchup between red and blue alliances"""
    if not red_alliance_data or not blue_alliance_data:
        return {}
    
    # Calculate alliance totals
    red_total = sum(team_data['metrics'].get('tot', team_data['metrics'].get('total_points', 0)) 
                   for team_data in red_alliance_data)
    blue_total = sum(team_data['metrics'].get('tot', team_data['metrics'].get('total_points', 0)) 
                    for team_data in blue_alliance_data)
    
    # Calculate period averages
    red_auto_avg = sum(team_data['metrics'].get('apt', team_data['metrics'].get('auto_points', 0)) 
                      for team_data in red_alliance_data) / len(red_alliance_data)
    blue_auto_avg = sum(team_data['metrics'].get('apt', team_data['metrics'].get('auto_points', 0)) 
                       for team_data in blue_alliance_data) / len(blue_alliance_data)
    
    red_teleop_avg = sum(team_data['metrics'].get('tpt', team_data['metrics'].get('teleop_points', 0)) 
                        for team_data in red_alliance_data) / len(red_alliance_data)
    blue_teleop_avg = sum(team_data['metrics'].get('tpt', team_data['metrics'].get('teleop_points', 0)) 
                         for team_data in blue_alliance_data) / len(blue_alliance_data)
    
    red_endgame_avg = sum(team_data['metrics'].get('ept', team_data['metrics'].get('endgame_points', 0)) 
                         for team_data in red_alliance_data) / len(red_alliance_data)
    blue_endgame_avg = sum(team_data['metrics'].get('ept', team_data['metrics'].get('endgame_points', 0)) 
                          for team_data in blue_alliance_data) / len(blue_alliance_data)
    
    return {
        'overall_comparison': {
            'red_alliance_total': red_total,
            'blue_alliance_total': blue_total,
            'advantage': 'red' if red_total > blue_total else 'blue',
            'margin': abs(red_total - blue_total)
        },
        'period_analysis': {
            'autonomous': {
                'red_average': red_auto_avg,
                'blue_average': blue_auto_avg,
                'advantage': 'red' if red_auto_avg > blue_auto_avg else 'blue'
            },
            'teleop': {
                'red_average': red_teleop_avg,
                'blue_average': blue_teleop_avg,
                'advantage': 'red' if red_teleop_avg > blue_teleop_avg else 'blue'
            },
            'endgame': {
                'red_average': red_endgame_avg,
                'blue_average': blue_endgame_avg,
                'advantage': 'red' if red_endgame_avg > blue_endgame_avg else 'blue'
            }
        },
        'key_insights': [
            f"Expected final score: Red {red_total:.1f} - Blue {blue_total:.1f}",
            f"Auto period: {'Red' if red_auto_avg > blue_auto_avg else 'Blue'} alliance favored",
            f"Teleop period: {'Red' if red_teleop_avg > blue_teleop_avg else 'Blue'} alliance favored",
            f"Endgame period: {'Red' if red_endgame_avg > blue_endgame_avg else 'Blue'} alliance favored"
        ]
    }

def _identify_key_battles(red_alliance_data, blue_alliance_data, game_config):
    """Identify key matchups and battles in the match"""
    battles = []
    
    if not red_alliance_data or not blue_alliance_data:
        return battles
    
    # Find top scorers from each alliance
    red_top_scorer = max(red_alliance_data, 
                        key=lambda x: x['metrics'].get('tot', x['metrics'].get('total_points', 0)))
    blue_top_scorer = max(blue_alliance_data, 
                         key=lambda x: x['metrics'].get('tot', x['metrics'].get('total_points', 0)))
    
    battles.append({
        'title': 'Top Scorer Matchup',
        'description': f"Team {red_top_scorer['team'].team_number} vs Team {blue_top_scorer['team'].team_number}",
        'red_team': red_top_scorer['team'].team_number,
        'blue_team': blue_top_scorer['team'].team_number,
        'key_factor': 'Overall scoring capability'
    })
    
    # Find best auto performers
    red_auto_best = max(red_alliance_data, 
                       key=lambda x: x['metrics'].get('apt', x['metrics'].get('auto_points', 0)))
    blue_auto_best = max(blue_alliance_data, 
                        key=lambda x: x['metrics'].get('apt', x['metrics'].get('auto_points', 0)))
    
    battles.append({
        'title': 'Autonomous Battle',
        'description': f"Team {red_auto_best['team'].team_number} vs Team {blue_auto_best['team'].team_number}",
        'red_team': red_auto_best['team'].team_number,
        'blue_team': blue_auto_best['team'].team_number,
        'key_factor': 'Autonomous execution'
    })
    
    # Find best endgame performers
    red_endgame_best = max(red_alliance_data, 
                          key=lambda x: x['metrics'].get('ept', x['metrics'].get('endgame_points', 0)))
    blue_endgame_best = max(blue_alliance_data, 
                           key=lambda x: x['metrics'].get('ept', x['metrics'].get('endgame_points', 0)))
    
    battles.append({
        'title': 'Endgame Showdown',
        'description': f"Team {red_endgame_best['team'].team_number} vs Team {blue_endgame_best['team'].team_number}",
        'red_team': red_endgame_best['team'].team_number,
        'blue_team': blue_endgame_best['team'].team_number,
        'key_factor': 'Endgame coordination'
    })
    
    # Add endgame capability battle
    red_endgame_capabilities = [_get_team_endgame_capabilities(team_data, game_config) for team_data in red_alliance_data]
    blue_endgame_capabilities = [_get_team_endgame_capabilities(team_data, game_config) for team_data in blue_alliance_data]
    
    # Calculate endgame strength based on consistency (convert to numeric score)
    def consistency_to_score(consistency):
        if consistency == 'Very Consistent':
            return 100
        elif consistency == 'Consistent':
            return 80
        elif consistency == 'Limited Data - Good':
            return 60
        elif consistency == 'Single Match - Success':
            return 50
        else:
            return 0
    
    red_endgame_success = sum(consistency_to_score(cap['consistency']) for cap in red_endgame_capabilities) / len(red_endgame_capabilities) if red_endgame_capabilities else 0
    blue_endgame_success = sum(consistency_to_score(cap['consistency']) for cap in blue_endgame_capabilities) / len(blue_endgame_capabilities) if blue_endgame_capabilities else 0
    
    if red_endgame_success > 30 or blue_endgame_success > 30:  # Only add if at least one alliance has decent endgame
        battles.append({
            'title': 'Endgame Positioning Battle',
            'description': f"Red Alliance ({red_endgame_success:.1f}% success) vs Blue Alliance ({blue_endgame_success:.1f}% success)",
            'red_team': 'Alliance',
            'blue_team': 'Alliance', 
            'key_factor': f"Endgame positioning and coordination - {'Red' if red_endgame_success > blue_endgame_success else 'Blue'} favored"
        })
    
    return battles

def _predict_strategy_outcome(red_alliance_data, blue_alliance_data, game_config):
    """Predict the outcome with detailed reasoning"""
    if not red_alliance_data or not blue_alliance_data:
        return {}
    
    # Calculate expected scores
    red_expected = sum(team_data['metrics'].get('tot', team_data['metrics'].get('total_points', 0)) 
                      for team_data in red_alliance_data)
    blue_expected = sum(team_data['metrics'].get('tot', team_data['metrics'].get('total_points', 0)) 
                       for team_data in blue_alliance_data)
    
    # Use Monte Carlo simulation for better estimates
    sim = _simulate_match_outcomes(red_alliance_data, blue_alliance_data, 'tot')
    expected_red = sim.get('expected_red', red_expected)
    expected_blue = sim.get('expected_blue', blue_expected)
    red_win_prob = sim.get('red_win_prob', 0.5)

    # Determine winner based on expected scores
    winner = 'red' if expected_red > expected_blue else 'blue' if expected_blue > expected_red else 'tie'
    margin = abs(expected_red - expected_blue)

    return {
        'predicted_winner': winner,
        'red_score': round(expected_red, 1),
        'blue_score': round(expected_blue, 1),
        'margin': round(margin, 1),
        # Numeric probability of red winning
        'confidence': round(red_win_prob, 3),
        'reasoning': [
            f"Red alliance expected total: {expected_red:.1f} points",
            f"Blue alliance expected total: {expected_blue:.1f} points",
            f"Predicted margin: {margin:.1f} points",
            f"Red win probability: {red_win_prob*100:.1f}%"
        ]
    }

def _generate_strategy_graph_data(red_alliance_data, blue_alliance_data, game_config):
    """Generate data for strategy visualization graphs"""
    if not red_alliance_data or not blue_alliance_data:
        return {}
    
    # Prepare data for different chart types
    team_comparison = {
        'labels': [],
        'red_data': [],
        'blue_data': [],
        'categories': ['Auto', 'Teleop', 'Endgame', 'Total']
    }
    
    # Collect team data
    for team_data in red_alliance_data:
        team_comparison['labels'].append(f"Team {team_data['team'].team_number}")
        metrics = team_data['metrics']
        team_comparison['red_data'].append({
            'auto': metrics.get('apt', metrics.get('auto_points', 0)),
            'teleop': metrics.get('tpt', metrics.get('teleop_points', 0)),
            'endgame': metrics.get('ept', metrics.get('endgame_points', 0)),
            'total': metrics.get('tot', metrics.get('total_points', 0))
        })
    
    for team_data in blue_alliance_data:
        team_comparison['labels'].append(f"Team {team_data['team'].team_number}")
        metrics = team_data['metrics']
        team_comparison['blue_data'].append({
            'auto': metrics.get('apt', metrics.get('auto_points', 0)),
            'teleop': metrics.get('tpt', metrics.get('teleop_points', 0)),
            'endgame': metrics.get('ept', metrics.get('endgame_points', 0)),
            'total': metrics.get('tot', metrics.get('total_points', 0))
        })
    
    # Alliance comparison data
    alliance_comparison = {
        'categories': ['Autonomous', 'Teleop', 'Endgame'],
        'red_alliance': [],
        'blue_alliance': []
    }
    
    # Calculate alliance averages
    red_auto_avg = sum(team_data['metrics'].get('apt', team_data['metrics'].get('auto_points', 0)) 
                      for team_data in red_alliance_data) / len(red_alliance_data)
    red_teleop_avg = sum(team_data['metrics'].get('tpt', team_data['metrics'].get('teleop_points', 0)) 
                        for team_data in red_alliance_data) / len(red_alliance_data)
    red_endgame_avg = sum(team_data['metrics'].get('ept', team_data['metrics'].get('endgame_points', 0)) 
                         for team_data in red_alliance_data) / len(red_alliance_data)
    
    blue_auto_avg = sum(team_data['metrics'].get('apt', team_data['metrics'].get('auto_points', 0)) 
                       for team_data in blue_alliance_data) / len(blue_alliance_data)
    blue_teleop_avg = sum(team_data['metrics'].get('tpt', team_data['metrics'].get('teleop_points', 0)) 
                         for team_data in blue_alliance_data) / len(blue_alliance_data)
    blue_endgame_avg = sum(team_data['metrics'].get('ept', team_data['metrics'].get('endgame_points', 0)) 
                          for team_data in blue_alliance_data) / len(blue_alliance_data)
    
    alliance_comparison['red_alliance'] = [red_auto_avg, red_teleop_avg, red_endgame_avg]
    alliance_comparison['blue_alliance'] = [blue_auto_avg, blue_teleop_avg, blue_endgame_avg]
    
    return {
        'team_comparison': team_comparison,
        'alliance_comparison': alliance_comparison,
        'radar_chart_data': {
            'labels': ['Auto Performance', 'Teleop Scoring', 'Endgame Execution', 'Consistency', 'Overall Rating'],
            'red_alliance': [red_auto_avg/15*100, red_teleop_avg/35*100, red_endgame_avg/20*100, 85, 
                           (red_auto_avg + red_teleop_avg + red_endgame_avg)/70*100],
            'blue_alliance': [blue_auto_avg/15*100, blue_teleop_avg/35*100, blue_endgame_avg/20*100, 85, 
                            (blue_auto_avg + blue_teleop_avg + blue_endgame_avg)/70*100]
        }
    }

def _get_team_endgame_capabilities(team_data, game_config):
    """Analyze a team's endgame capabilities based on scouting data"""
    if not team_data or not team_data.get('scouting_data'):
        return {
            'primary_strategy': 'No Data',
            'consistency': 'No Data'
        }
    
    scouting_records = team_data['scouting_data']
    endgame_config = game_config.get('endgame_period', {})
    endgame_elements = endgame_config.get('scoring_elements', [])
    
    # Find the endgame position element using dynamic ID from config
    position_element = None
    def element_visible(el):
        return el.get('show_in_predictions', el.get('display_in_predictions', True))
    choice_types = {'select', 'multiple_choice', 'multiple-choice', 'single_choice', 'single-choice', 'choice', 'multiplechoice'}
    visible_elements = [e for e in endgame_elements if element_visible(e)]
    for element in visible_elements:
        if element.get('type') and element.get('type').lower() in choice_types and 'position' in element.get('name', '').lower():
            position_element = element
            break

    # If not found by name, try to find the first choice-like element in visible elements
    if not position_element:
        for element in visible_elements:
            if element.get('type') and element.get('type').lower() in choice_types:
                position_element = element
                break
    
    if not position_element:
        return {
            'primary_strategy': 'No endgame configuration',
            'consistency': 'No Data'
        }
    
    # Get the dynamic field ID
    endgame_field_id = position_element.get('id')
    print(f"  Analyzing endgame for team {team_data['team'].team_number} using field ID: {endgame_field_id}")
    
    # Analyze endgame positions from scouting data
    position_counts = {}
    total_matches = len(scouting_records)
    total_endgame_points = 0
    
    for record in scouting_records:
        # Get endgame position from the scouting data using the dynamic field ID
        position = None
        
        # Try to get position from the record's data dictionary
        if hasattr(record, 'data') and record.data:
            position = record.data.get(endgame_field_id, position_element.get('default', 'None'))
        
        # Fallback: try to get from direct attribute (for backward compatibility)
        if not position or position == position_element.get('default', 'None'):
            if hasattr(record, endgame_field_id):
                position = getattr(record, endgame_field_id)
            else:
                position = position_element.get('default', 'None')
        
        print(f"    Match {record.match.match_number if record.match else 'N/A'}: {endgame_field_id} = {position}")
        
        # Count the position
        if position not in position_counts:
            position_counts[position] = 0
        position_counts[position] += 1
        
        # Calculate endgame points for this match using the points mapping
        endgame_points = 0
        if position and position != position_element.get('default', 'None'):
            # Support points described either as dict or list of options
            points_map = {}
            if isinstance(position_element.get('points'), dict) and position_element.get('points'):
                points_map = position_element.get('points', {})
            elif isinstance(position_element.get('options'), list):
                for opt in position_element.get('options', []):
                    if isinstance(opt, dict):
                        points_map[opt.get('name')] = opt.get('points', 0)
            endgame_points = points_map.get(position, 0)
        
        total_endgame_points += endgame_points
    
    # Determine primary strategy (most common position)
    if position_counts:
        primary_position = max(position_counts.items(), key=lambda x: x[1])
        primary_strategy = primary_position[0]
        
        # Calculate success rate (non-default positions)
        default_value = position_element.get('default', 'None')
        successful_endgames = sum(count for pos, count in position_counts.items() if pos != default_value)
        success_rate = (successful_endgames / total_matches * 100) if total_matches > 0 else 0
        
        # Calculate consistency based on both success rate and match count
        if total_matches >= 3:
            if success_rate >= 80:
                consistency = 'Very Consistent'
            elif success_rate >= 60:
                consistency = 'Consistent'
            elif success_rate >= 40:
                consistency = 'Somewhat Consistent'
            else:
                consistency = 'Inconsistent'
        elif total_matches == 2:
            if success_rate >= 50:
                consistency = 'Limited Data - Good'
            else:
                consistency = 'Limited Data - Poor'
        elif total_matches == 1:
            if success_rate > 0:
                consistency = 'Single Match - Success'
            else:
                consistency = 'Single Match - Failed'
        else:
            consistency = 'No Data'
    else:
        primary_strategy = 'No endgame attempts'
        success_rate = 0
        consistency = 'No Data'
    
    # Calculate average endgame points
    avg_endgame_points = total_endgame_points / total_matches if total_matches > 0 else 0
    
    # Create detailed positioning data
    positioning_data = {}
    # Build points_map once
    points_map = {}
    if isinstance(position_element.get('points'), dict) and position_element.get('points'):
        points_map = position_element.get('points', {})
    elif isinstance(position_element.get('options'), list):
        for opt in position_element.get('options', []):
            if isinstance(opt, dict):
                points_map[opt.get('name')] = opt.get('points', 0)

    for position, count in position_counts.items():
        percentage = (count / total_matches * 100) if total_matches > 0 else 0
        points = points_map.get(position, 0)
        positioning_data[position] = {
            'count': count,
            'percentage': round(percentage, 1),
            'points_value': points
        }
    
    print(f"  Team {team_data['team'].team_number} endgame analysis: {primary_strategy} ({consistency})")
    
    return {
        'primary_strategy': primary_strategy,
        'consistency': consistency,
        'total_matches': total_matches
    }

def _analyze_alliance_endgame_coordination(alliance_data, game_config):
    """Analyze how well an alliance might coordinate in endgame"""
    if not alliance_data:
        return {
            'coordination_score': 0,
            'strategy_conflicts': [],
            'recommendations': []
        }
    
    endgame_capabilities = []
    for team_data in alliance_data:
        capabilities = _get_team_endgame_capabilities(team_data, game_config)
        endgame_capabilities.append({
            'team_number': team_data['team'].team_number,
            'capabilities': capabilities
        })
    
    # Analyze coordination potential - teams with consistent endgame performance
    successful_teams = sum(1 for cap in endgame_capabilities 
                          if cap['capabilities']['consistency'] in ['Very Consistent', 'Consistent', 'Limited Data - Good', 'Single Match - Success'])
    total_teams = len(endgame_capabilities)
    
    coordination_score = (successful_teams / total_teams * 100) if total_teams > 0 else 0
    
    # Check for strategy conflicts using dynamic endgame options from config
    endgame_config = game_config.get('endgame_period', {})
    endgame_elements = endgame_config.get('scoring_elements', [])

    def element_visible(el):
        return el.get('show_in_predictions', el.get('display_in_predictions', True))
    choice_types = {'select', 'multiple_choice', 'multiple-choice', 'single_choice', 'single-choice', 'choice', 'multiplechoice'}

    # Find endgame position element among visible choice-like elements
    position_element = None
    visible_elements = [e for e in endgame_elements if element_visible(e)]
    for element in visible_elements:
        if element.get('type') and element.get('type').lower() in choice_types and 'position' in element.get('name', '').lower():
            position_element = element
            break
    if not position_element:
        for element in visible_elements:
            if element.get('type') and element.get('type').lower() in choice_types:
                position_element = element
                break
    
    # Analyze position preferences
    position_preferences = {}
    default_value = position_element.get('default', 'None') if position_element else 'None'
    
    for cap in endgame_capabilities:
        primary = cap['capabilities']['primary_strategy']
        if primary and primary not in [default_value, 'No endgame attempts', 'No Data', 'No endgame configuration']:
            if primary not in position_preferences:
                position_preferences[primary] = []
            position_preferences[primary].append(cap['team_number'])
    
    # Check for conflicts based on game-specific position limitations
    strategy_conflicts = []
    limited_capacity_positions = []
    
    # Identify positions that might have limited capacity based on their names or points
    if position_element:
        # Build options list (support both dict and list formats)
        options_list = []
        if isinstance(position_element.get('options'), dict):
            options_list = list(position_element.get('options').keys())
        elif isinstance(position_element.get('options'), list):
            # options may be list of strings or list of {name, points}
            for opt in position_element.get('options', []):
                if isinstance(opt, str):
                    options_list.append(opt)
                elif isinstance(opt, dict):
                    if opt.get('name'):
                        options_list.append(opt.get('name'))

        for option in options_list:
            if 'cage' in option.lower() or 'hang' in option.lower() or 'climb' in option.lower():
                limited_capacity_positions.append(option)
    
    for position, teams in position_preferences.items():
        if len(teams) > 1:
            if position in limited_capacity_positions:
                strategy_conflicts.append(f"Multiple teams ({', '.join(map(str, teams))}) prefer {position} - coordinate roles")
            elif len(teams) > 2:  # More than 2 teams going for the same position might be problematic
                strategy_conflicts.append(f"Too many teams ({', '.join(map(str, teams))}) targeting {position}")
    
    # Generate coordination recommendations
    recommendations = []
    if successful_teams >= 2:
        recommendations.append("Good endgame potential - coordinate positioning early")
    if strategy_conflicts:
        recommendations.append("Resolve position conflicts before match - assign primary/backup roles")
    if successful_teams == 0:
        recommendations.append("Focus on teleop scoring - endgame may not be viable")
    elif successful_teams == 1:
        recommendations.append("One reliable endgame robot - support with defensive/scoring roles")
    
    # Add specific recommendations based on the positions available
    if position_element:
        high_value_positions = []
        points_map = position_element.get('points', {})
        for position, points in points_map.items():
            if points > 0:
                high_value_positions.append(position)
        
        if high_value_positions:
            recommendations.append(f"Focus on these positions for points: {', '.join(high_value_positions)}")
    
    return {
        'coordination_score': round(coordination_score, 1),
        'strategy_conflicts': strategy_conflicts,
        'recommendations': recommendations,
        'team_capabilities': endgame_capabilities
    }