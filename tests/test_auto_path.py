import json
from app import create_app, db
from app.models import User, Team, Match, AutoPathDrawing, Event


def login_test_user(client):
    # reuse or create a user for tests and then manually mark session as logged-in
    u = User.query.filter_by(username='auto_tester').first()
    if not u:
        u = User(username='auto_tester', scouting_team_number=55555)
        u.set_password('pass')
        db.session.add(u)
        db.session.commit()
    # set session keys used by flask-login directly
    with client.session_transaction() as sess:
        sess['_user_id'] = str(u.id)
        sess['_fresh'] = True
    return u


def test_auto_path_page_and_api():
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()
        # login
        login_test_user(client)

        # create a team, event and match
        team = Team(team_number=1234, scouting_team_number=55555)
        db.session.add(team)
        event = Event(name='Example', year=2025)
        db.session.add(event)
        db.session.flush()
        match = Match(match_type='qualification', match_number=1, scouting_team_number=55555, event_id=event.id)
        db.session.add(match)
        db.session.commit()

        # page without params should render selection form (follow redirect in case login got lost)
        resp = client.get('/scouting/auto_path', follow_redirects=True)
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')
        assert 'Auto Path Scouting' in page
        assert '-- Select Team --' in page
        # ensure match dropdown has no duplicate visible entries
        labels = []
        import re
        for m in re.finditer(r'<option[^>]*>([^<]+)</option>', page):
            txt = m.group(1).strip()
            if txt and not txt.startswith('--'):
                labels.append(txt)
        assert len(labels) == len(set(labels)), "duplicate match labels found"

        # sidebar should include auto path link by default
        assert 'Auto Path Scouting' in page

        # page with parameters should render selection form as well
        resp2 = client.get(f'/scouting/auto_path?team_id={team.id}&match_id={match.id}', follow_redirects=True)
        assert resp2.status_code == 200
        page2 = resp2.data.decode('utf-8')
        # basic sanity: selectors exist
        assert 'id="team-selector"' in page2
        assert 'id="match-selector"' in page2
        # event dropdown should be present
        assert 'id="event-selector"' in page2
        # feedback status element and javascript should be present
        assert 'id="save-status"' in page2
        assert 'Saved at' in page2
        
        # create a second event with a different team and match
        event2 = Event(name='Other', year=2025)
        db.session.add(event2)
        db.session.flush()
        match2 = Match(match_type='qualification', match_number=2, scouting_team_number=55555, event_id=event2.id)
        team3 = Team(team_number=5678, scouting_team_number=55555)
        db.session.add_all([match2, team3])
        db.session.commit()
        # request auto_path for event2 should only list team 5678
        resp_evt = client.get(f'/scouting/auto_path?event_id={event2.id}', follow_redirects=True)
        assert resp_evt.status_code == 200
        evt_page = resp_evt.data.decode('utf-8')
        assert '5678' in evt_page
        assert '1234' not in evt_page

        # API GET returns none initially
        g = client.get(f'/scouting/api/auto_path/{match.id}/{team.id}')
        assert g.status_code == 200
        assert g.get_json() == {'data': None}

        # API POST create drawing
        data_obj = {'data': [{'id': 1, 'color': '#000', 'points': [{'x':0,'y':0}]}]}
        p = client.post(f'/scouting/api/auto_path/{match.id}/{team.id}', json=data_obj)
        assert p.status_code == 200
        assert p.get_json().get('success')

        # GET should now return the saved data
        g2 = client.get(f'/scouting/api/auto_path/{match.id}/{team.id}')
        assert g2.status_code == 200
        assert g2.get_json()['data'] == data_obj['data']

        # verify model persisted
        drawing = AutoPathDrawing.query.filter_by(match_id=match.id, team_id=team.id).first()
        assert drawing is not None
        assert drawing.data == data_obj['data']

        # listing page should include the new drawing and display a canvas element
        resp_list = client.get('/scouting/auto_paths')
        assert resp_list.status_code == 200
        list_page = resp_list.data.decode('utf-8')
        assert 'Team 1234' in list_page
        assert '<canvas' in list_page
        # page should reference the field image for previews
        assert 'Feild-2025.png' in list_page
        # ensure improved filtering UI is present
        assert 'Filter by Team' in list_page
        assert 'team-filter' in list_page
        assert 'search-box' in list_page
        # team search input for dropdown filtering
        assert 'team-search' in list_page
        # ensure JavaScript helper uses reliable loading
        assert 'imageLoaded' in list_page
        assert 'processQueue' in list_page or 'renderData' in list_page

        # add another team/drawing so we can test sorting by team
        team2 = Team(team_number=2345, scouting_team_number=55555)
        db.session.add(team2)
        db.session.commit()
        # create blank drawing (no data) to ensure it still shows on list
        drawing2 = AutoPathDrawing(match_id=match.id, team_id=team2.id, data_json='[]')
        db.session.add(drawing2)
        db.session.commit()

        # check event dropdown on list page
        resp_evtlist = client.get('/scouting/auto_paths')
        assert 'id="event-selector"' in resp_evtlist.data.decode('utf-8')

        # default sort (by match) should list both; order doesn't matter much
        resp_default = client.get('/scouting/auto_paths')
        assert resp_default.status_code == 200
        default_page = resp_default.data.decode('utf-8')
        assert default_page.index('Team 1234') < default_page.index('Team 2345') or default_page.index('Team 2345') < default_page.index('Team 1234')

        # sort by team should always show the lower team number first
        resp_team = client.get('/scouting/auto_paths?sort=team')
        team_page = resp_team.data.decode('utf-8')
        assert team_page.index('Team 1234') < team_page.index('Team 2345')

        # filtering to a single team should hide the other
        resp_filter = client.get(f'/scouting/auto_paths?team_id={team2.id}')
        filter_page = resp_filter.data.decode('utf-8')
        assert 'Team 1234' not in filter_page
        assert 'Team 2345' in filter_page

        # search by team number should filter results
        resp_search = client.get('/scouting/auto_paths?q=1234')
        search_page = resp_search.data.decode('utf-8')
        assert 'Team 1234' in search_page
        # 2345 should not appear when searching for 1234
        assert 'Team 2345' not in search_page




def test_auto_path_nav_visibility():
    """Admin can hide the Auto Path Scouting link via settings"""
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()
        # create admin user
        u = User(username='nav_admin', scouting_team_number=99999)
        u.set_password('p'); db.session.add(u); db.session.commit()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id); sess['_fresh'] = True
        # check both navigation links are present by default
        res1 = client.get('/scouting/auto_path', follow_redirects=True)
        html1 = res1.data.decode('utf-8')
        assert 'Auto Path Scouting' in html1
        assert 'Saved Auto Paths' in html1
        # hide nav item via form submit (no visible items)
        resp = client.post('/auth/admin/save-nav-visibility', data={'visible_nav_items':[]}, follow_redirects=True)
        assert resp.status_code == 200
        # reload page and verify absence
        res2 = client.get('/scouting/auto_path', follow_redirects=True)
        html2 = res2.data.decode('utf-8')
        assert 'Auto Path Scouting' not in html2
        assert 'Saved Auto Paths' not in html2
