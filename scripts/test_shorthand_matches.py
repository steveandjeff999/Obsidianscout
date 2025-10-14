"""
Quick test to ensure shorthand match types like 'qual 5' route to match_results correctly
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
app = create_app()

with app.app_context():
    from app.assistant import get_assistant
    assistant = get_assistant()
    tests = [
        'qual 5',
        'playoff 3',
        'practice 2',
        'match 5',
    ]
    for q in tests:
        print('Query:', q)
        res = assistant.answer_question(q)
        text = res.get('text', '')
        # Make ASCII-safe for Windows console
        safe = text.encode('ascii', 'ignore').decode('ascii')
        print(' ->', safe[:200])
        print('---')
