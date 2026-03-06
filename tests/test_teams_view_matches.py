import os
import json

from app import create_app, db
from app.models import Team, Event, Match


def write_config(data):
    cfg_dir = os.path.join(os.getcwd(), "config")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_path = os.path.join(cfg_dir, "game_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_matches_card_uses_config_event(monkeypatch):
    """When a current_event_code is set and the team has matches there, show them"""
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # create team and event from config
        t = Team(team_number=1234)
        db.session.add(t)
        evt = Event(code='TEST', year=2026, name='Config Event')
        db.session.add(evt)
        db.session.commit()

        # create two matches: one with score and one unplayed (scores set to -1)
        m1 = Match(match_number=1, match_type='qual', event_id=evt.id,
                   red_alliance='1234,1111', blue_alliance='2222,3333',
                   red_score=15, blue_score=10)
        m2 = Match(match_number=2, match_type='qual', event_id=evt.id,
                   red_alliance='4444,5555', blue_alliance='1234,6666',
                   red_score=-1, blue_score=-1)
        db.session.add_all([m1, m2])
        db.session.commit()

        # write config pointing to TEST
        write_config({'current_event_code': 'TEST', 'season': 2026})

        resp = client.get('/teams/1234/view')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # header of matches card should reference the event name
        assert 'Matches at Config Event' in html
        # both matches should be listed
        assert 'qual 1' in html
        assert 'qual 2' in html
        # score row should show the numeric score
        assert '15' in html and '10' in html
        # unplayed match should display 0 – 0 instead of -1
        assert '0' in html
        assert '-1' not in html
        assert 'not played' not in html


def test_matches_card_falls_back_to_recent_event_if_not_in_config():
    """If config event doesn't contain the team, use the team's most recent event"""
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # prepare a team with matches in two events
        t = Team(team_number=5678)
        db.session.add(t)
        evt_old = Event(code='OLD', year=2025, name='Old Event')
        evt_new = Event(code='NEW', year=2026, name='New Event')
        db.session.add_all([evt_old, evt_new])
        db.session.commit()

        # create a match in the newer event only
        m_new = Match(match_number=3, match_type='qual', event_id=evt_new.id,
                      red_alliance='5678,1111', blue_alliance='2222,3333')
        db.session.add(m_new)
        db.session.commit()

        # config points at an event where the team has no matches
        write_config({'current_event_code': 'UNUSED', 'season': 2026})

        resp = client.get('/teams/5678/view')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # should show the recent event name
        assert 'Matches at New Event' in html
        assert 'qual 3' in html
        # ensure scores are displayed (even if no explicit score this defaults to 0-0)
        assert 'not played' not in html
        assert '0' in html
