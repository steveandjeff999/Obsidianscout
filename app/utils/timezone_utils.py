"""
Timezone Utility Functions
Handles timezone conversions for events and match scheduling
"""
from datetime import datetime, timezone
import pytz


# Mapping of US states/provinces to IANA timezones
STATE_TIMEZONE_MAP = {
    # US States - Eastern Time
    'Connecticut': 'America/New_York', 'CT': 'America/New_York',
    'Delaware': 'America/New_York', 'DE': 'America/New_York',
    'Florida': 'America/New_York', 'FL': 'America/New_York',
    'Georgia': 'America/New_York', 'GA': 'America/New_York',
    'Maine': 'America/New_York', 'ME': 'America/New_York',
    'Maryland': 'America/New_York', 'MD': 'America/New_York',
    'Massachusetts': 'America/New_York', 'MA': 'America/New_York',
    'Michigan': 'America/Detroit', 'MI': 'America/Detroit',
    'New Hampshire': 'America/New_York', 'NH': 'America/New_York',
    'New Jersey': 'America/New_York', 'NJ': 'America/New_York',
    'New York': 'America/New_York', 'NY': 'America/New_York',
    'North Carolina': 'America/New_York', 'NC': 'America/New_York',
    'Ohio': 'America/New_York', 'OH': 'America/New_York',
    'Pennsylvania': 'America/New_York', 'PA': 'America/New_York',
    'Rhode Island': 'America/New_York', 'RI': 'America/New_York',
    'South Carolina': 'America/New_York', 'SC': 'America/New_York',
    'Vermont': 'America/New_York', 'VT': 'America/New_York',
    'Virginia': 'America/New_York', 'VA': 'America/New_York',
    'West Virginia': 'America/New_York', 'WV': 'America/New_York',
    
    # US States - Central Time
    'Alabama': 'America/Chicago', 'AL': 'America/Chicago',
    'Arkansas': 'America/Chicago', 'AR': 'America/Chicago',
    'Illinois': 'America/Chicago', 'IL': 'America/Chicago',
    'Indiana': 'America/Indiana/Indianapolis', 'IN': 'America/Indiana/Indianapolis',
    'Iowa': 'America/Chicago', 'IA': 'America/Chicago',
    'Kansas': 'America/Chicago', 'KS': 'America/Chicago',
    'Kentucky': 'America/Kentucky/Louisville', 'KY': 'America/Kentucky/Louisville',
    'Louisiana': 'America/Chicago', 'LA': 'America/Chicago',
    'Minnesota': 'America/Chicago', 'MN': 'America/Chicago',
    'Mississippi': 'America/Chicago', 'MS': 'America/Chicago',
    'Missouri': 'America/Chicago', 'MO': 'America/Chicago',
    'Nebraska': 'America/Chicago', 'NE': 'America/Chicago',
    'North Dakota': 'America/Chicago', 'ND': 'America/Chicago',
    'Oklahoma': 'America/Chicago', 'OK': 'America/Chicago',
    'South Dakota': 'America/Chicago', 'SD': 'America/Chicago',
    'Tennessee': 'America/Chicago', 'TN': 'America/Chicago',
    'Texas': 'America/Chicago', 'TX': 'America/Chicago',
    'Wisconsin': 'America/Chicago', 'WI': 'America/Chicago',
    
    # US States - Mountain Time
    'Arizona': 'America/Phoenix', 'AZ': 'America/Phoenix',  # No DST
    'Colorado': 'America/Denver', 'CO': 'America/Denver',
    'Idaho': 'America/Boise', 'ID': 'America/Boise',
    'Montana': 'America/Denver', 'MT': 'America/Denver',
    'New Mexico': 'America/Denver', 'NM': 'America/Denver',
    'Utah': 'America/Denver', 'UT': 'America/Denver',
    'Wyoming': 'America/Denver', 'WY': 'America/Denver',
    
    # US States - Pacific Time
    'California': 'America/Los_Angeles', 'CA': 'America/Los_Angeles',
    'Nevada': 'America/Los_Angeles', 'NV': 'America/Los_Angeles',
    'Oregon': 'America/Los_Angeles', 'OR': 'America/Los_Angeles',
    'Washington': 'America/Los_Angeles', 'WA': 'America/Los_Angeles',
    
    # US States - Alaska & Hawaii
    'Alaska': 'America/Anchorage', 'AK': 'America/Anchorage',
    'Hawaii': 'Pacific/Honolulu', 'HI': 'Pacific/Honolulu',
    
    # Canadian Provinces
    'Ontario': 'America/Toronto', 'ON': 'America/Toronto',
    'Quebec': 'America/Montreal', 'QC': 'America/Montreal',
    'British Columbia': 'America/Vancouver', 'BC': 'America/Vancouver',
    'Alberta': 'America/Edmonton', 'AB': 'America/Edmonton',
    'Saskatchewan': 'America/Regina', 'SK': 'America/Regina',
    'Manitoba': 'America/Winnipeg', 'MB': 'America/Winnipeg',
    'New Brunswick': 'America/Moncton', 'NB': 'America/Moncton',
    'Nova Scotia': 'America/Halifax', 'NS': 'America/Halifax',
    'Prince Edward Island': 'America/Halifax', 'PE': 'America/Halifax',
    'Newfoundland and Labrador': 'America/St_Johns', 'NL': 'America/St_Johns',
    
    # International (common FRC locations)
    'Israel': 'Asia/Jerusalem', 'IL': 'Asia/Jerusalem',
    'Turkey': 'Europe/Istanbul', 'TR': 'Europe/Istanbul',
    'Mexico': 'America/Mexico_City', 'MX': 'America/Mexico_City',
    'Australia': 'Australia/Sydney', 'AU': 'Australia/Sydney',
    'Brazil': 'America/Sao_Paulo', 'BR': 'America/Sao_Paulo',
    'China': 'Asia/Shanghai', 'CN': 'Asia/Shanghai',
}


def infer_timezone_from_location(city=None, state=None, country=None):
    """
    Infer IANA timezone from location information
    
    Args:
        city: City name
        state: State/Province name or abbreviation
        country: Country name or code
        
    Returns:
        IANA timezone string or None
    """
    # Try state/province first (most specific for US/Canada)
    if state:
        state_upper = state.strip().upper()
        # Try exact match
        tz = STATE_TIMEZONE_MAP.get(state.strip())
        if tz:
            return tz
        # Try abbreviation
        tz = STATE_TIMEZONE_MAP.get(state_upper)
        if tz:
            return tz
    
    # Try country-level defaults
    if country:
        country_upper = country.strip().upper()
        if country_upper in ['USA', 'US', 'UNITED STATES']:
            # Default to Eastern if we don't know the state
            return 'America/New_York'
        elif country_upper in ['CANADA', 'CA', 'CAN']:
            # Default to Toronto (Eastern) for Canada
            return 'America/Toronto'
        elif country_upper in ['MEXICO', 'MX']:
            return 'America/Mexico_City'
        elif country_upper in ['ISRAEL', 'IL']:
            return 'Asia/Jerusalem'
        elif country_upper in ['TURKEY', 'TR']:
            return 'Europe/Istanbul'
        elif country_upper in ['AUSTRALIA', 'AU']:
            return 'Australia/Sydney'
        elif country_upper in ['BRAZIL', 'BR']:
            return 'America/Sao_Paulo'
        elif country_upper in ['CHINA', 'CN']:
            return 'Asia/Shanghai'
        elif country_upper in ['TAIWAN', 'TW']:
            return 'Asia/Taipei'
        elif country_upper in ['NETHERLANDS', 'NL']:
            return 'Europe/Amsterdam'
        else:
            # Try looking up country in our map
            tz = STATE_TIMEZONE_MAP.get(country.strip())
            if tz:
                return tz
    
    # If we have a city, try some specific mappings
    if city:
        city_lower = city.lower().strip()
        city_tz_map = {
            'san jose': 'America/Los_Angeles',
            'san diego': 'America/Los_Angeles',
            'los angeles': 'America/Los_Angeles',
            'houston': 'America/Chicago',
            'dallas': 'America/Chicago',
            'chicago': 'America/Chicago',
            'detroit': 'America/Detroit',
            'new york': 'America/New_York',
            'boston': 'America/New_York',
            'toronto': 'America/Toronto',
            'montreal': 'America/Montreal',
            'vancouver': 'America/Vancouver',
        }
        tz = city_tz_map.get(city_lower)
        if tz:
            return tz
    
    return None


def get_event_timezone(event):
    """
    Get pytz timezone object for an event
    
    Args:
        event: Event model instance with timezone field
        
    Returns:
        pytz.timezone object or None if timezone not set
    """
    if not event or not event.timezone:
        return None
    
    try:
        return pytz.timezone(event.timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        print(f"️  Unknown timezone: {event.timezone}")
        return None


def convert_local_to_utc(dt, event_timezone_str):
    """
    Convert a naive datetime from event local time to UTC
    
    Args:
        dt: Naive datetime object in event local time
        event_timezone_str: IANA timezone string (e.g., 'America/Denver')
        
    Returns:
        Timezone-aware datetime in UTC
    """
    if not event_timezone_str:
        # If no timezone info, assume UTC
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    
    try:
        local_tz = pytz.timezone(event_timezone_str)
        
        # If datetime is naive, localize it to the event timezone
        if dt.tzinfo is None:
            local_dt = local_tz.localize(dt)
        else:
            # If already aware, convert to event timezone first
            local_dt = dt.astimezone(local_tz)
        
        # Convert to UTC
        return local_dt.astimezone(timezone.utc)
    except pytz.exceptions.UnknownTimeZoneError:
        print(f"️  Unknown timezone: {event_timezone_str}, treating as UTC")
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)


def convert_utc_to_local(dt_utc, event_timezone_str):
    """
    Convert a UTC datetime to event local time
    
    Args:
        dt_utc: Datetime in UTC (timezone-aware or naive)
        event_timezone_str: IANA timezone string (e.g., 'America/Denver')
        
    Returns:
        Timezone-aware datetime in event local time
    """
    if not event_timezone_str:
        # If no timezone info, return as UTC
        if dt_utc.tzinfo is None:
            return dt_utc.replace(tzinfo=timezone.utc)
        return dt_utc
    
    try:
        local_tz = pytz.timezone(event_timezone_str)
        
        # Ensure dt_utc is timezone-aware
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        
        # Convert to local timezone
        return dt_utc.astimezone(local_tz)
    except pytz.exceptions.UnknownTimeZoneError:
        print(f"️  Unknown timezone: {event_timezone_str}, returning UTC")
        if dt_utc.tzinfo is None:
            return dt_utc.replace(tzinfo=timezone.utc)
        return dt_utc


def format_time_with_timezone(dt, event_timezone_str=None, format_str='%I:%M %p'):
    """
    Format a datetime with timezone information
    
    Args:
        dt: Datetime to format (UTC or aware)
        event_timezone_str: Optional IANA timezone string to convert to
        format_str: strftime format string
        
    Returns:
        Formatted string with timezone abbreviation
    """
    if dt is None:
        return ""
    
    # Convert to event timezone if provided and include TZ abbreviation
    if event_timezone_str:
        dt_local = convert_utc_to_local(dt, event_timezone_str)
        tz_abbr = dt_local.strftime('%Z')  # Get timezone abbreviation (e.g., 'MST', 'EDT')
        return f"{dt_local.strftime(format_str)} {tz_abbr}"
    else:
        # No explicit event timezone: display the formatted time without appending 'UTC'
        # Ensure dt is timezone-aware for consistent formatting, but don't append a label
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime(format_str)


def get_timezone_display_name(event_timezone_str):
    """
    Get a human-readable timezone name
    
    Args:
        event_timezone_str: IANA timezone string (e.g., 'America/Denver')
        
    Returns:
        Display name (e.g., 'Mountain Time') or None
    """
    if not event_timezone_str:
        return None
    
    # Map common IANA timezones to display names
    timezone_names = {
        'America/New_York': 'Eastern Time',
        'America/Chicago': 'Central Time',
        'America/Denver': 'Mountain Time',
        'America/Phoenix': 'Mountain Time (no DST)',
        'America/Los_Angeles': 'Pacific Time',
        'America/Anchorage': 'Alaska Time',
        'Pacific/Honolulu': 'Hawaii Time',
        'America/Toronto': 'Eastern Time',
        'America/Vancouver': 'Pacific Time',
        # Add more as needed
    }
    
    return timezone_names.get(event_timezone_str, event_timezone_str)


def parse_iso_with_timezone(iso_string, default_timezone_str=None):
    """
    Parse an ISO 8601 datetime string and handle timezone
    
    Args:
        iso_string: ISO 8601 formatted datetime string
        default_timezone_str: IANA timezone to use if string doesn't include timezone
        
    Returns:
        Timezone-aware datetime in UTC
    """
    if not iso_string:
        return None
    
    try:
        # Try parsing with timezone info
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        
        # If naive and default timezone provided, localize then convert to UTC
        if dt.tzinfo is None and default_timezone_str:
            return convert_local_to_utc(dt, default_timezone_str)
        
        # If naive and no default, assume UTC
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        
        # If aware, convert to UTC
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError) as e:
        print(f"️  Error parsing datetime '{iso_string}': {e}")
        return None


def get_current_time_in_timezone(event_timezone_str):
    """
    Get current time in event's timezone
    
    Args:
        event_timezone_str: IANA timezone string
        
    Returns:
        Current datetime in event timezone
    """
    now_utc = datetime.now(timezone.utc)
    return convert_utc_to_local(now_utc, event_timezone_str)


def iso_utc(dt):
    """Serialize a datetime to ISO-8601 with an explicit UTC offset.

    All datetimes stored in the database are naive UTC.  Without the
    ``+00:00`` suffix browsers parse the string as **local** time
    (per ES2015+), which silently shifts every displayed time by the
    user's UTC offset.

    Use this helper whenever a datetime leaves the server in a JSON
    response so that every client — web browser **and** mobile app —
    receives an unambiguous UTC timestamp it can convert to the user's
    local timezone.

    Args:
        dt: A :class:`datetime.datetime` or ``None``.

    Returns:
        An ISO-8601 string with offset (e.g. ``2026-03-15T14:30:00+00:00``)
        or ``None`` if *dt* is ``None``.
    """
    if dt is None:
        return None
    # Already timezone-aware → isoformat() includes the offset automatically
    if getattr(dt, 'tzinfo', None) is not None:
        return dt.isoformat()
    # Naive datetime assumed UTC → append explicit UTC offset
    return dt.isoformat() + '+00:00'


def utc_now_iso():
    """Return the current UTC time as an ISO-8601 string with ``+00:00``.

    Drop-in replacement for the widespread ``datetime.now().isoformat()``
    anti-pattern that emits server-local time without an offset.
    """
    return datetime.now(timezone.utc).isoformat()
