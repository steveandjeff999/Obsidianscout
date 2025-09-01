"""Evaluate historical prediction accuracy and calibration.

Usage:
  python scripts/evaluate_predictions.py [--event EVENT_CODE] [--limit N]

This script runs inside the Flask app context and evaluates predictions produced by
`get_match_details_with_teams` for completed matches (both red and blue scores present).
It reports:
- Number of matches evaluated
- Prediction accuracy (winner)
- Brier score for red-win probability
- Mean absolute error for predicted scores (red and blue)
- Calibration table (bins)

Note: Running this requires the application's database to be accessible.
"""

import argparse
import math
import statistics
from collections import defaultdict

from app import create_app
from app.models import Match
from app.utils.analysis import get_match_details_with_teams
from app.utils.team_isolation import filter_matches_by_scouting_team


def evaluate(event_code=None, limit=None):
    app = create_app()
    with app.app_context():
        # Query matches with completed scores
        q = filter_matches_by_scouting_team().filter(Match.red_score != None, Match.blue_score != None)
        if event_code:
            q = q.filter(Match.event.has(code=event_code))
        q = q.order_by(Match.event_id, Match.match_type, Match.match_number)
        if limit:
            matches = q.limit(limit).all()
        else:
            matches = q.all()

        if not matches:
            print("No completed matches found for evaluation")
            return

        n = 0
        correct = 0
        brier_sum = 0.0
        red_mae_sum = 0.0
        blue_mae_sum = 0.0
        skipped = 0

        # Calibration bins
        bins = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        bin_counts = defaultdict(int)
        bin_sum_outcomes = defaultdict(float)

        for match in matches:
            try:
                details = get_match_details_with_teams(match.id)
            except Exception as e:
                print(f"Skipping match {match.id} due to error: {e}")
                skipped += 1
                continue

            prediction = details.get('prediction') if details else None
            if not prediction:
                skipped += 1
                continue

            # Determine actual outcome: red win -> 1, blue win -> 0, tie -> 0.5
            if match.red_score > match.blue_score:
                actual_red = 1.0
                actual_winner = 'red'
            elif match.blue_score > match.red_score:
                actual_red = 0.0
                actual_winner = 'blue'
            else:
                actual_red = 0.5
                actual_winner = 'tie'

            # Prediction confidence: our code stores numeric probability for red win in 'confidence'
            pred_prob = prediction.get('confidence')
            # Some older code used labels or confidence as margin - handle defensively
            if pred_prob is None:
                # Try to infer from predicted_winner vs predicted scores
                pred_prob = 0.5
            elif isinstance(pred_prob, str):
                # Map 'high'/'medium'/'low' to crude numeric
                mapping = {'high': 0.85, 'medium': 0.65, 'low': 0.55}
                pred_prob = mapping.get(pred_prob.lower(), 0.5)

            # Predicted scores
            pred_red_score = None
            pred_blue_score = None
            try:
                pred_red_score = float(prediction.get('red_alliance', {}).get('predicted_score'))
                pred_blue_score = float(prediction.get('blue_alliance', {}).get('predicted_score'))
            except Exception:
                # Older predictions may only have top-level predicted_score keys
                try:
                    pred_red_score = float(prediction.get('predicted_red', prediction.get('red_score', 0)))
                    pred_blue_score = float(prediction.get('predicted_blue', prediction.get('blue_score', 0)))
                except Exception:
                    pred_red_score = None
                    pred_blue_score = None

            # Compute winner accuracy
            if prediction.get('predicted_winner') == actual_winner:
                correct += 1

            # Brier score (for red)
            brier = (pred_prob - actual_red) ** 2
            brier_sum += brier

            # MAE for scores if available
            if pred_red_score is not None:
                red_mae_sum += abs(pred_red_score - match.red_score)
            if pred_blue_score is not None:
                blue_mae_sum += abs(pred_blue_score - match.blue_score)

            n += 1

            # Calibration bin
            # clamp pred_prob
            p = max(0.0, min(1.0, float(pred_prob)))
            # find bin
            for i in range(len(bins) - 1):
                low = bins[i]
                high = bins[i + 1]
                if p >= low and p <= high:
                    bin_key = (low, high)
                    bin_counts[bin_key] += 1
                    bin_sum_outcomes[bin_key] += actual_red
                    break

        # Summarize
        print("\nEvaluation Results")
        print("------------------")
        print(f"Matches considered: {len(matches)} (evaluated: {n}, skipped: {skipped})")

        if n == 0:
            print("No matches were evaluated. Exiting.")
            return

        accuracy = correct / n
        brier_score = brier_sum / n
        red_mae = red_mae_sum / n if n > 0 else None
        blue_mae = blue_mae_sum / n if n > 0 else None

        print(f"Winner prediction accuracy: {accuracy*100:.2f}% ({correct}/{n})")
        print(f"Brier score (red-win probability): {brier_score:.4f} (lower is better, min=0)")
        if red_mae is not None:
            print(f"Mean absolute error - Red score: {red_mae:.2f}")
        if blue_mae is not None:
            print(f"Mean absolute error - Blue score: {blue_mae:.2f}")

        # Calibration table
        print("\nCalibration by probability bin (pred_range -> count, avg_outcome):")
        for i in range(len(bins) - 1):
            low = bins[i]
            high = bins[i + 1]
            key = (low, high)
            cnt = bin_counts.get(key, 0)
            if cnt > 0:
                avg_out = bin_sum_outcomes[key] / cnt
                avg_pred = (low + high) / 2.0
                print(f" {low:.1f}-{high:.1f}: {cnt} matches, avg outcome(red win)={avg_out:.3f}, avg pred={avg_pred:.3f}")
            else:
                print(f" {low:.1f}-{high:.1f}: 0 matches")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Evaluate prediction accuracy')
    parser.add_argument('--event', dest='event', help='Event code to filter', default=None)
    parser.add_argument('--limit', dest='limit', type=int, help='Limit number of matches', default=None)
    args = parser.parse_args()

    evaluate(event_code=args.event, limit=args.limit)
