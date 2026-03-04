import json
import os
import uuid

try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import Event, Team, Match, QualitativeScoutingData, PitScoutingData


def test_team_view_includes_qualitative_and_pit():
    """Viewing a team should surface any qualitative notes or pit entries for that team."""
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        # simple config file to satisfy get_effective_game_config
        cfg_dir = os.path.join(os.getcwd(), 'config')
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, 'game_config.json')
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        client = app.test_client()

        # create supporting data: event, match, team
        e = Event(name='EV', code='EVT', year=2025)
        db.session.add(e)
        db.session.commit()

        t = Team(team_number=314, team_name='Pi')
        db.session.add(t)
        db.session.commit()

        m = Match(match_type='qm', match_number=1, event_id=e.id)
        db.session.add(m)
        db.session.commit()

        # qualitative entry containing notes for team 314
        qual_data = {
            'red': {f'team_{t.team_number}': {'notes': 'Great drivetrain'}}
        }
        qual = QualitativeScoutingData(
            match_id=m.id,
            scouting_team_number=9999,
            scout_name='tester',
            alliance_scouted='red',
            data_json=json.dumps(qual_data)
        )
        db.session.add(qual)

        # simple pit entry for the team
        pit = PitScoutingData(
            team_id=t.id,
            scouting_team_number=9999,
            scout_name='pitty',
            data_json=json.dumps({'foo': 'bar'}),
            local_id=str(uuid.uuid4())
        )
        db.session.add(pit)
        db.session.commit()

        # request the team view page and inspect content
        resp = client.get(f"/teams/{t.team_number}/view")
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # the qualitative note should be rendered
        assert 'Great drivetrain' in html, "Qualitative notes were not shown on team view"
        # the pit view link should appear
        assert f"/pit/view/{pit.id}" in html, "Pit entry link missing"
        # there should also be a link to qualitative view
        assert '/qualitative/view/' in html, "Qualitative view link not present"

        # optionally verify scout names appear
        assert 'tester' in html
        assert 'pitty' in html
