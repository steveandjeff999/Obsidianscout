#!/usr/bin/env python3
"""
Add automatically scheduled "test" matches to a temporary event.

This is intended for manual testing of mobile apps or the API.  The script
will create or reuse a simple event (code TEST) scoped to the scouting
team number you supply, then insert matches every four minutes for the next
four hours.  Matches are stamped with UTC scheduled_time values so mobile
clients will see them in the appropriate time range.

The database target is chosen the same way the server chooses it:
if `run.py` has USE_POSTGRES=True and a PostgreSQL configuration is
available, the app will be started in Postgres mode.  You can override the
behaviour with `--use-postgres` or `--use-sqlite` flags if you want to
exercise both backends.

Usage:
    python tools/add_test_matches.py <scouting_team_number>
    python tools/add_test_matches.py 1234 --use-postgres    # force Postgres
    python tools/add_test_matches.py 1234 --use-sqlite      # force SQLite

"""
import sys
import os
import argparse
from datetime import datetime, timedelta, timezone

# put repo root on path so imports succeed when run from anywhere
# the script lives in tools/, so add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# we import run here so we can inspect its USE_POSTGRES setting
import run

from app import create_app, db
from app.models import Event, Match
from sqlalchemy import func


def detect_postgres_config():
    """Return True if a postgres_config.json file exists with minimal fields."""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance', 'postgres_config.json')
    try:
        with open(cfg_path, 'r', encoding='utf-8') as fh:
            import json
            cfg = json.load(fh)
        if cfg.get('host') and cfg.get('database'):
            return True
    except Exception:
        pass
    return False


def add_matches_for_team(scouting_team_number):
    # run in Central time zone so matches appear in local schedule
    from zoneinfo import ZoneInfo
    central = ZoneInfo('America/Chicago')
    local_now = datetime.now(central)
    # compute scheduling window 24h in each direction
    start_local = local_now - timedelta(hours=24)
    end_local = local_now + timedelta(hours=24)
    interval = timedelta(minutes=4)
    # convert window boundaries to UTC for logging
    now = local_now.astimezone(timezone.utc)
    end = end_local.astimezone(timezone.utc)

    # find (or create) a simple "test" event scoped to the team
    evt = Event.query.filter_by(code='TEST', scouting_team_number=scouting_team_number).first()
    if not evt:
        evt = Event(
            name='Test Event',
            code='TEST',
            scouting_team_number=scouting_team_number,
            year=local_now.year,
            start_date=start_local.date(),   # start date covers full window
            end_date=end_local.date(),
            timezone='America/Chicago'  # Central time zone for testing
        )
        db.session.add(evt)
        db.session.commit()  # need an id for matches
        print(f"Created new test event id={evt.id}")
    else:
        print(f"Using existing test event id={evt.id}")

    # ensure we have some sample teams for this scouting group
    from app.models import Team
    fake_nums = [scouting_team_number * 10 + i for i in (1, 2, 3, 4)]
    for num in fake_nums:
        if not Team.query.filter_by(team_number=num, scouting_team_number=scouting_team_number).first():
            tentry = Team(team_number=num, team_name=f"Test Team {num}", scouting_team_number=scouting_team_number)
            db.session.add(tentry)
    db.session.commit()
    print(f"Ensured {len(fake_nums)} fake teams for scouting team {scouting_team_number}")

    # start match numbering just after highest existing
    existing_max = db.session.query(func.max(Match.match_number)).filter_by(event_id=evt.id).scalar() or 0
    match_num = existing_max + 1

    # start from local_now and step through local intervals, converting each to UTC
    t_local = local_now
    added = 0
    created_matches = []
    created_times = []  # keep corresponding UTC timestamps for matches
    # rotate through fake teams in alliances
    while t_local < end_local:
        idx = (match_num - existing_max - 1) % len(fake_nums)
        red1 = fake_nums[idx]
        red2 = fake_nums[(idx + 1) % len(fake_nums)]
        blue1 = fake_nums[(idx + 2) % len(fake_nums)]
        blue2 = fake_nums[(idx + 3) % len(fake_nums)]
        utc_ts = t_local.astimezone(timezone.utc)
        m = Match(
            match_number=match_num,
            match_type='test',
            event_id=evt.id,
            scouting_team_number=scouting_team_number,
            scheduled_time=utc_ts,  # stored in UTC
            red_alliance=f"{red1},{red2}",
            blue_alliance=f"{blue1},{blue2}",
        )
        print(f"Scheduling match {match_num} at local {t_local.isoformat()} ({utc_ts.isoformat()} UTC)")
        db.session.add(m)
        created_matches.append(m)
        match_num += 1
        added += 1
        t_local += interval

    db.session.commit()
    print(f"Added {added} matches (from {now.isoformat()} to {end.isoformat()})")

    # build and return API-style data for the created matches using preserved UTC times
    matches_data = []
    for match, utc_ts in zip(created_matches, created_times):
        matches_data.append({
            'id': match.id,
            'match_number': match.match_number,
            'match_type': match.match_type,
            'red_alliance': match.red_alliance,
            'blue_alliance': match.blue_alliance,
            'red_score': match.red_score,
            'blue_score': match.blue_score,
            'winner': match.winner,
            'scheduled_time': utc_ts.isoformat().replace('+00:00', 'Z'),
            'predicted_time': (match.predicted_time.isoformat().replace('+00:00','Z') if match.predicted_time else None),
            'actual_time': (match.actual_time.isoformat().replace('+00:00','Z') if match.actual_time else None),
        })

    return matches_data


def main():
    p = argparse.ArgumentParser(description='Add four hours of 4‑minute test matches.')
    # make team number optional so we can prompt if omitted
    p.add_argument('scouting_team_number', nargs='?', type=int,
                   help='scouting team number to associate with matches')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--use-postgres', action='store_true', help='force using PostgreSQL')
    group.add_argument('--use-sqlite', action='store_true', help='force using SQLite')
    args = p.parse_args()

    # interactive prompts if necessary
    if args.scouting_team_number is None:
        try:
            args.scouting_team_number = int(input('Enter scouting team number: ').strip())
        except Exception:
            print('Invalid number entered, exiting.')
            return

    # determine which backend(s) to run against
    if args.use_sqlite:
        targets = ['sqlite']
    elif args.use_postgres:
        targets = ['postgres']
    else:
        # ask user which database to use
        choice = None
        while choice not in ('postgres', 'sqlite', 'auto'):
            choice = input("Choose database (postgres/sqlite/auto): ").strip().lower()
            if choice == 'p':
                choice = 'postgres'
            elif choice == 's':
                choice = 'sqlite'
            elif choice == 'a':
                choice = 'auto'
        if choice == 'postgres':
            targets = ['postgres']
        elif choice == 'sqlite':
            targets = ['sqlite']
        else:
            # auto: mimic run.py setting
            if getattr(run, 'USE_POSTGRES', False):
                targets = ['postgres']
            else:
                targets = ['sqlite']

    for target in targets:
        if target == 'postgres':
            if not detect_postgres_config():
                print('Postgres configuration not found; skipping Postgres target.')
                continue
            print('Starting app in PostgreSQL mode...')
            try:
                app = create_app(use_postgres=True)
            except Exception as e:
                print(f'Failed to start app with Postgres: {e}')
                continue
        else:
            print('Starting app in SQLite mode...')
            app = create_app(use_postgres=False)

        with app.app_context():
            matches_data = add_matches_for_team(args.scouting_team_number)
        # tear down session in case multiple targets
        try:
            db.session.remove()
        except Exception:
            pass
        # print API-style JSON so the format matches what mobile clients receive
        if matches_data is not None:
            import json
            print("\nAPI-style match objects:")
            print(json.dumps({'success': True, 'matches': matches_data, 'count': len(matches_data)}, indent=2))


if __name__ == '__main__':
    main()
