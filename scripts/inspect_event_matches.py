"""Inspect matches for an event and print scheduled/predicted times and status.

Run from the project root with the same Python environment used by the app.

Examples:
    python scripts/inspect_event_matches.py --event-code EXREG
    python scripts/inspect_event_matches.py --event-id 12
"""
import argparse
from datetime import datetime, timezone

from app import create_app, db
from app.models import Event, Match
from app.utils.timezone_utils import convert_local_to_utc


def print_match_row(m):
    pred = getattr(m, 'predicted_time', None)
    sched = getattr(m, 'scheduled_time', None)
    actual = getattr(m, 'actual_time', None)
    red_score = getattr(m, 'red_score', None)
    blue_score = getattr(m, 'blue_score', None)

    def iso_or_none(dt):
        if not dt:
            return None
        try:
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return str(dt)

    # Determine status similar to matches_data
    finished = bool(actual or getattr(m, 'winner', None) or (red_score is not None and red_score >= 0) or (blue_score is not None and blue_score >= 0))
    status = 'completed' if finished else 'upcoming'

    print(f"ID={m.id:4}  #{m.match_number:3}  type={m.match_type:8}  status={status:9}  scheduled={iso_or_none(sched):26}  predicted={iso_or_none(pred):26}  actual={iso_or_none(actual):26}  alliances=R[{m.red_alliance}] B[{m.blue_alliance}]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--event-code', help='Event code (preferred)')
    parser.add_argument('--event-id', type=int, help='Event id')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        ev = None
        if args.event_id:
            ev = Event.query.get(args.event_id)
        elif args.event_code:
            ev = Event.query.filter_by(code=args.event_code).first()

        if not ev:
            print('Event not found. Provide --event-code or --event-id that exists in DB for your scouting team.')
            return

        matches = Match.query.filter_by(event_id=ev.id).order_by(Match.match_number).all()
        print(f"Event: {ev.name} (id={ev.id}, code={ev.code}, timezone={ev.timezone}) — {len(matches)} matches")
        for m in matches:
            print_match_row(m)


if __name__ == '__main__':
    main()
