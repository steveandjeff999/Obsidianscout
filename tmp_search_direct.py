from app import create_app
from app.routes.search import search_teams, search_users, search_matches, search_scouting_data, search_pages

app = create_app()

with app.app_context():
    queries = ['match 5', '5', 'climb', 'team 5454']
    for q in queries:
        print('\nQuery:', q)
        try:
            t = search_teams(q)
            print(' teams:', len(t))
            if t: print('  sample team:', t[0])
        except Exception as e:
            print(' teams error:', e)
        try:
            m = search_matches(q)
            print(' matches:', len(m))
            if m: print('  sample match:', m[0])
        except Exception as e:
            print(' matches error:', e)
        try:
            s = search_scouting_data(q)
            print(' scouting:', len(s))
            if s: print('  sample scouting:', s[0])
        except Exception as e:
            print(' scouting error:', e)
        try:
            p = search_pages(q)
            print(' pages:', len(p))
        except Exception as e:
            print(' pages error:', e)

print('done')
