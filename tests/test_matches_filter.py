import re
import json
import os

try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import Event, Match, User




def test_api_live_matches_skips_zero_score_matches(monkeypatch):
    """The live-matches endpoint should treat 0‑0 entries as unplayed.

    Prior to https://github.com/... (issue #XXX) the API check used ``>= 0``
    which meant scheduled matches with default zero scores were considered
    "completed", causing the dashboard to show the last five matches instead
    of the true upcoming ones.  This regression test exercises the new logic.
    """
    app = create_app()
    with app.app_context():
        # clean schema so we know what we're working with
        try:
            db.drop_all()
        except Exception:
            pass
        db.create_all()

        from flask_login import login_user
        from app.models import User, Event, Match

        # create a logged-in user with a scouting team so filters work
        u = User(username='live_tester', scouting_team_number=42)
        u.set_password('pw')
        db.session.add(u)

        ev = Event(name='LiveTest', code='LIV', year=2026, scouting_team_number=42)
        db.session.add(ev)
        db.session.commit()

        # populate a few scheduled matches; include one completed and one
        # that is nominally a 0‑0 tie so we can verify it is *not* considered
        # finished by the algorithm.
        # ensure matches are scoped to our scouting team so the isolation filter
        # used by api_live_matches will return them
        m1 = Match(match_number=1, match_type='Qualification', event_id=ev.id, scouting_team_number=42)
        m2 = Match(match_number=2, match_type='Qualification', event_id=ev.id, scouting_team_number=42,
                   red_score=5, blue_score=3)
        m3 = Match(match_number=3, match_type='Qualification', event_id=ev.id, scouting_team_number=42)
        m4 = Match(match_number=4, match_type='Qualification', event_id=ev.id, scouting_team_number=42,
                   red_score=0, blue_score=0, winner='tie')
        m5 = Match(match_number=5, match_type='Qualification', event_id=ev.id, scouting_team_number=42,
                   red_score=0, blue_score=0)
        db.session.add_all([m1, m2, m3, m4, m5])
        db.session.commit()

        # stub out the external API to ensure earlier implementation (which we
        # no longer use) wouldn't interfere; this just returns nonsense data
        def fake_api(event_code):
            return [
                {'match_number': i, 'red_score': 0, 'blue_score': 0, 'winner': ''}
                for i in range(1, 6)
            ]
        monkeypatch.setattr('app.utils.api_utils.get_matches_dual_api', fake_api)

        # ensure the config points at our event
        cfg_dir = os.path.join(os.getcwd(), 'config')
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, 'game_config.json')
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump({'current_event_code': ev.code}, f)

        # log in with a request context then call the view directly
        with app.test_request_context('/api/live-matches'):
            login_user(u)
            from app.routes.main import api_live_matches
            resp = api_live_matches()
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['success']
            nums = [m['match_number'] for m in data['upcoming_matches']]
            # match 2 is marked completed above, but 1/3/4/5 are unplayed (4 is
            # a zero-zero "tie" and should still be considered upcoming).  The
            # results should therefore be the first four usable matches in order.
            assert nums == [1, 3, 4, 5], f"Unexpected upcoming matches: {nums}"

def test_api_brief_data_schedule(monkeypatch):
    """Brief data should use the same schedule-based upcoming logic as /matches."""
    app = create_app()
    with app.app_context():
        try:
            db.drop_all()
        except Exception:
            pass
        db.create_all()

        from flask_login import login_user
        from app.models import User, Event, Match

        u = User(username='brief_tester', scouting_team_number=7)
        u.set_password('pw')
        db.session.add(u)

        ev = Event(name='BriefEvent', code='BRF', year=2026, scouting_team_number=7)
        db.session.add(ev)
        db.session.commit()

        m1 = Match(match_number=1, match_type='Qualification', event_id=ev.id, scouting_team_number=7)
        m2 = Match(match_number=2, match_type='Qualification', event_id=ev.id, scouting_team_number=7,
                   red_score=1, blue_score=0)
        m3 = Match(match_number=3, match_type='Qualification', event_id=ev.id, scouting_team_number=7)
        m4 = Match(match_number=4, match_type='Qualification', event_id=ev.id, scouting_team_number=7,
                   red_score=0, blue_score=0, winner='tie')
        m5 = Match(match_number=5, match_type='Qualification', event_id=ev.id, scouting_team_number=7)
        db.session.add_all([m1, m2, m3, m4, m5])
        db.session.commit()

        # stub API again just in case
        def fake_api(event_code):
            return []
        monkeypatch.setattr('app.utils.api_utils.get_matches_dual_api', fake_api)

        # set config
        cfg_dir = os.path.join(os.getcwd(), 'config')
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, 'game_config.json')
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump({'current_event_code': ev.code}, f)

        with app.test_request_context('/api/brief-data'):
            login_user(u)
            from app.routes.main import api_brief_data
            resp = api_brief_data()
            assert resp.status_code == 200
            data = resp.get_json()
            nums = [m['match_number'] for m in data['upcoming_matches']]
            assert nums == [1, 3, 4, 5], f"Brief endpoint returned wrong matches: {nums}"