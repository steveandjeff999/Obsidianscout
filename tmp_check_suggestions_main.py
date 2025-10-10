import os
os.environ.setdefault('FLASK_ENV','development')
from app import create_app
from app.models import User
from flask_login import login_user
from app.routes.search import api_suggestions

app = create_app()
with app.app_context():
    user = User.query.first()
    print('auth user', getattr(user,'username', None))
    with app.test_request_context('/search/api/suggestions?q=match+5'):
        if user:
            login_user(user)
        resp = api_suggestions()
        data = resp.get_json()
        print('suggestions count', len(data.get('suggestions', [])))
        for s in data.get('suggestions', [])[:8]:
            print(s.get('type'), '-', s.get('text') or s.get('title') or s.get('search_query'))
