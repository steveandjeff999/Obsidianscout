"""
Template filters for the application
"""
import json

def init_app(app):
    """Register template filters with the Flask app"""
    
    @app.template_filter('prettify_json')
    def prettify_json(value):
        """Format JSON string with proper indentation"""
        try:
            if value:
                parsed = json.loads(value)
                return json.dumps(parsed, indent=2)
            return "{}"
        except Exception:
            return value
