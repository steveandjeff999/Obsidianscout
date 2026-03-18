import json
from app import create_app, db
from app.models import User, Team, Match, Event, AutoPathDrawing


def login_mobile_user(client, username='mobile_tester', team_number=55555):
    # ensure user exists
    u = User.query.filter_by(username=username).first()
    if not u:
        u = User(username=username, scouting_team_number=team_number)
        u.set_password('pass')
        db.session.add(u)
        db.session.commit()
    # get a token via API
    resp = client.post('/api/mobile/auth/login', json={
        'username': username,
        'password': 'pass',
        'team_number': team_number
    })
    data = resp.get_json()
    assert data['success'], 'login failed'
    return data['token']


def test_mobile_submit_auto_path():
    app = create_app(test_config={'TESTING': True})
    with app.app_context():
        client = app.test_client()
        token = login_mobile_user(client)
        headers = {'Authorization': f'Bearer {token}'}

        # create supporting records
        team = Team(team_number=123, scouting_team_number=55555)
        event = Event(name='Test', year=2025, code='2025TEST', scouting_team_number=55555)
        db.session.add_all([team, event])
        db.session.flush()
        match = Match(match_type='qualification', match_number=1, event_id=event.id, scouting_team_number=55555)
        db.session.add(match)
        db.session.commit()

        payload = {
            'team_id': team.id,
            'match_id': match.id,
            'data': {
                'auto_path_generated': True,
                'export_type': 'auto_path',
                'drawing_data': [{'type': 'score', 'x': 0.1, 'y': 0.2}]
            }
        }
        resp = client.post('/api/mobile/scouting/submit', json=payload, headers=headers)
        assert resp.status_code == 201
        result = resp.get_json()
        assert result['success']
        assert 'auto_path_id' in result
        dap = AutoPathDrawing.query.get(result['auto_path_id'])
        assert dap is not None
        assert dap.data == payload['data']['drawing_data']


def test_mobile_bulk_submit_auto_path():
    app = create_app(test_config={'TESTING': True})
    with app.app_context():
        client = app.test_client()
        token = login_mobile_user(client, username='mobile_bulk', team_number=55555)
        headers = {'Authorization': f'Bearer {token}'}

        # reuse same team/match from previous test or recreate
        team = Team.query.filter_by(team_number=123).first()
        match = Match.query.filter_by(match_number=1).first()
        if not team or not match:
            team = Team(team_number=123, scouting_team_number=55555)
            event = Event(name='Test2', year=2025, code='2025T2', scouting_team_number=55555)
            db.session.add(event); db.session.flush()
            match = Match(match_type='qualification', match_number=1, event_id=event.id, scouting_team_number=55555)
            db.session.add(match)
            db.session.add(team)
            db.session.commit()

        entry = {
            'team_id': team.id,
            'match_id': match.id,
            'data': {
                'auto_path_generated': True,
                'export_type': 'auto_path',
                'drawing_data': [{'type': 'score', 'x': 0.5, 'y': 0.5}]
            },
            'offline_id': 'abc123',
            'timestamp': '2026-03-12T00:00:00Z'
        }
        resp = client.post('/api/mobile/scouting/bulk-submit', json={'entries': [entry]}, headers=headers)
        assert resp.status_code == 200
        result = resp.get_json()
        assert result['success']
        assert result['submitted'] == 1
        assert result['failed'] == 0
        assert 'auto_path_id' in result['results'][0]
        dap = AutoPathDrawing.query.get(result['results'][0]['auto_path_id'])
        assert dap is not None
        assert dap.data == entry['data']['drawing_data']
