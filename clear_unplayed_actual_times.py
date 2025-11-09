"""
Clear actual_time for matches that haven't been played yet (no scores or winner)
This fixes matches incorrectly showing as "Played at" when they're actually future matches.
"""
import os
os.environ['WERKZEUG_RUN_MAIN'] = 'false'  # Disable Flask debug reloader

from app import create_app, db
from app.models import Match
from app.utils.score_utils import norm_db_score

app = create_app()
app.config['DEBUG'] = False  # Disable debug mode

with app.app_context():
    # Find all matches with actual_time set but no real scores/winner
    matches = Match.query.filter(Match.actual_time.isnot(None)).all()
    
    print(f"Found {len(matches)} matches with actual_time set")
    cleared_count = 0
    
    for match in matches:
        # Check if match has real scores or winner
        red_score = norm_db_score(match.red_score)
        blue_score = norm_db_score(match.blue_score)
        has_winner = match.winner is not None
        has_scores = (red_score is not None and red_score >= 0) or (blue_score is not None and blue_score >= 0)
        
        # If no winner and no valid scores, the match hasn't actually been played
        if not has_winner and not has_scores:
            print(f"Clearing actual_time for Match {match.match_type} #{match.match_number}")
            match.actual_time = None
            cleared_count += 1
    
    if cleared_count > 0:
        db.session.commit()
        print(f"\n✅ Cleared actual_time for {cleared_count} unplayed matches")
    else:
        print("\n✅ No matches needed clearing")
