import os
os.environ.setdefault('FLASK_ENV','development')
from app import create_app
from app.models import User
from flask_login import login_user
from app.routes import search as search_module

app = create_app()

with app.app_context():
    user = User.query.first()
    print('using user:', getattr(user,'username', None))
    if not user:
        print('No user in DB, cannot authenticate; rendering without login')

    # Render search_page for multiple queries
    queries = ['match 5', 'team 5454', 'climb']
    for q in queries:
        print('\n--- Query:', q)
        with app.test_request_context(f'/search?q={q}'):
            if user:
                login_user(user)
            try:
                resp_html = search_module.search_page()
                # resp_html can be a rendered template string
                html_str = resp_html if isinstance(resp_html, str) else str(resp_html)
                found_match = 'Qualification 5' in html_str or 'Match 5 - Team' in html_str
                found_scouting = 'Match 5 - Team' in html_str
                print('found_match:', found_match, 'found_scouting:', found_scouting)
                # Optionally print a small slice
                idx = html_str.find('Qualification 5')
                if idx!=-1:
                    print('sample snippet:', html_str[idx:idx+200])
            except Exception as e:
                import traceback; traceback.print_exc()

print('done')
