"""
Template filters for the application
"""
import json
from datetime import datetime, timezone
from app.utils.timezone_utils import convert_utc_to_local, format_time_with_timezone

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
    
    @app.template_filter('format_time_tz')
    def format_time_tz(dt, event_timezone=None, format_str='%I:%M %p'):
        """
        Format a datetime with timezone information
        
        Usage in templates:
            {{ match.scheduled_time | format_time_tz(event.timezone) }}
            {{ match.scheduled_time | format_time_tz(event.timezone, '%Y-%m-%d %I:%M %p') }}
        """
        if dt is None:
            return ""
        return format_time_with_timezone(dt, event_timezone, format_str)
    
    @app.template_filter('to_local_tz')
    def to_local_tz(dt_utc, event_timezone):
        """
        Convert UTC datetime to event local timezone
        
        Usage in templates:
            {{ match.scheduled_time | to_local_tz(event.timezone) }}
        """
        if dt_utc is None or not event_timezone:
            return dt_utc
        return convert_utc_to_local(dt_utc, event_timezone)
