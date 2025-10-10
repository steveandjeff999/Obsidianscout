import os
os.environ.setdefault('FLASK_ENV','development')
from app import create_app, db
from app.models import User
from app.routes.search import api_quick_search, api_suggestions
from flask_login import login_user

app = create_app()
with app.app_context():
    user = User.query.first()
    print('using user:', getattr(user,'username', None))
    with app.test_request_context():
        if user:
            login_user(user)
        # quick search
        with app.test_request_context('/search/api/quick-search?q=match+5'):
            try:
                resp = api_quick_search()
                print('quick-search status:', getattr(resp,'status_code', 'no status'))
                print('quick-search json:', resp.get_json())
            except Exception as e:
                import traceback; traceback.print_exc()
        # suggestions
        with app.test_request_context('/search/api/suggestions?q=match+5&types=team,user,match,scouting'):
            try:
                resp2 = api_suggestions()
                print('suggestions status:', getattr(resp2,'status_code', 'no status'))
                print('suggestions json:', resp2.get_json())
            except Exception as e:
                import traceback; traceback.print_exc()
print('done')
