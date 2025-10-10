import os
os.environ.setdefault('FLASK_ENV','development')
from app import create_app
from app.routes.search import api_quick_search, api_suggestions
app = create_app()

with app.test_request_context('/search/api/quick-search?q=match+5'):
    try:
        resp = api_quick_search()
        print('quick-search status:', getattr(resp,'status_code', 'no status'))
        try:
            data = resp.get_json()
            print('quick-search result count:', len(data) if data else 0)
        except Exception as e:
            print('quick-search json error:', e)
    except Exception as e:
        import traceback
        traceback.print_exc()

with app.test_request_context('/search/api/suggestions?q=match+5'):
    try:
        resp2 = api_suggestions()
        print('suggestions status:', getattr(resp2,'status_code', 'no status'))
        try:
            data2 = resp2.get_json()
            print('suggestions count:', len(data2.get('suggestions', [])))
        except Exception as e:
            print('suggestions json error:', e)
    except Exception as e:
        import traceback
        traceback.print_exc()

print('done')
