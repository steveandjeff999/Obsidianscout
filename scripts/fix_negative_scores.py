"""
Fix negative sentinel scores in the database.

Some external APIs use -1 to indicate "no score / unplayed". Historically the
application sometimes persisted those -1 values in the DB which causes template
checks like `if match.red_score is not none` to treat the match as "played".

This script finds matches with negative scores and sets them to NULL (None).
It also clears or recalculates the `winner` field when appropriate.

Usage: run from project root in the app virtualenv:
    python scripts/fix_negative_scores.py

The script uses the app factory to create an application context and commits
changes in one transaction.
"""
from app import create_app, db
from app.models import Match
from sqlalchemy import or_


def run():
    app = create_app()
    with app.app_context():
        print("Scanning for matches with negative scores...")
        # Query matches where either score is negative (stored as integer < 0)
        matches = Match.query.filter(or_(Match.red_score < 0, Match.blue_score < 0)).all()
        total = len(matches)
        if total == 0:
            print("No matches with negative scores found.")
            return

        print(f"Found {total} matches with negative scores. Updating records...")
        fixed = 0
        for m in matches:
            changed = False
            if m.red_score is not None and isinstance(m.red_score, int) and m.red_score < 0:
                m.red_score = None
                changed = True
            if m.blue_score is not None and isinstance(m.blue_score, int) and m.blue_score < 0:
                m.blue_score = None
                changed = True

            # Recompute winner field if both scores are present, otherwise clear it
            if m.red_score is None or m.blue_score is None:
                if m.winner is not None:
                    m.winner = None
                    changed = True
            else:
                # both present and non-negative - recompute just in case
                if m.red_score > m.blue_score:
                    new_winner = 'red'
                elif m.blue_score > m.red_score:
                    new_winner = 'blue'
                else:
                    new_winner = 'tie'
                if m.winner != new_winner:
                    m.winner = new_winner
                    changed = True

            if changed:
                fixed += 1

        # Commit changes
        db.session.commit()
        print(f"Updated {fixed} records (out of {total} found).")


if __name__ == '__main__':
    run()
