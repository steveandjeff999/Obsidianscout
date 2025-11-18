"""
Team isolation utilities for multi-tenant scouting platform.
Provides helper functions to filter database queries by scouting team.
"""

from flask_login import current_user
from app.models import Team, Event, Match, ScoutingData, AllianceSelection, DoNotPickEntry, AvoidEntry, PitScoutingData, User, DeclinedEntry
from sqlalchemy import or_, func


def get_alliance_team_numbers():
    """Get list of all team numbers in the active alliance (including current team).
    Returns empty list if alliance mode is not active.
    """
    try:
        from app.models import TeamAllianceStatus
        
        current_team = get_current_scouting_team_number()
        if not current_team:
            return []
        
        # Check if alliance mode is active for this team
        active_alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team)
        
        if active_alliance and active_alliance.is_config_complete():
            # Return all member team numbers
            return active_alliance.get_member_team_numbers()
        
        return []
    except Exception:
        return []


def is_alliance_mode_active_for_current_user():
    """Check if alliance mode is currently active for the current user's team."""
    try:
        from app.models import TeamAllianceStatus
        
        current_team = get_current_scouting_team_number()
        if not current_team:
            return False
        
        return TeamAllianceStatus.is_alliance_mode_active_for_team(current_team)
    except Exception:
        return False


def get_alliance_shared_event_codes():
    """Get list of event codes that are shared in the active alliance.
    Returns empty list if alliance mode is not active.
    """
    try:
        from app.models import TeamAllianceStatus
        
        current_team = get_current_scouting_team_number()
        if not current_team:
            return []
        
        # Check if alliance mode is active for this team
        active_alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team)
        
        if active_alliance and active_alliance.is_config_complete():
            # Return all shared event codes
            return active_alliance.get_shared_events()
        
        return []
    except Exception:
        return []


def get_current_scouting_team_number():
    """Get the current user's scouting team number.
    
    Checks Flask's g object first (for mobile API requests), then falls back to current_user.
    """
    from flask import g
    
    # First check if scouting_team_number was set in Flask's g object (mobile API)
    if hasattr(g, 'scouting_team_number') and g.scouting_team_number is not None:
        return g.scouting_team_number
    
    # Fall back to Flask-Login's current_user
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        return current_user.scouting_team_number
    
    return None


def get_current_scouting_team():
    """Alias for get_current_scouting_team_number for compatibility."""
    return get_current_scouting_team_number()


def filter_teams_by_scouting_team(query=None):
    """Filter teams by current user's scouting team number.
    If alliance mode is active, shows teams from all alliance members (not filtered by scouting_team_number).
    """
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Team.query
    
    if scouting_team_number is not None:
        # Check if alliance mode is active
        shared_event_codes = get_alliance_shared_event_codes()
        if shared_event_codes:
            # Show all teams from any alliance member (don't filter by scouting_team_number)
            # Teams are shared across the alliance when alliance mode is active
            alliance_team_numbers = get_alliance_team_numbers()
            return query.filter(Team.scouting_team_number.in_(alliance_team_numbers))
        else:
            # Show only current team's teams
            return query.filter(Team.scouting_team_number == scouting_team_number)
    return query.filter(Team.scouting_team_number.is_(None))  # Show unassigned teams if no team set


def filter_events_by_scouting_team(query=None):
    """Filter events by current user's scouting team number.
    If alliance mode is active, filters by alliance shared event codes.
    """
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Event.query
    
    if scouting_team_number is not None:
        # Check if alliance mode is active
        shared_event_codes = get_alliance_shared_event_codes()
        if shared_event_codes:
            # Show only events that are in the alliance's shared event list
            # Use uppercase comparison to handle case-insensitive event codes
            upper_codes = [code.upper() for code in shared_event_codes]
            return query.filter(func.upper(Event.code).in_(upper_codes))
        else:
            # Show only current team's events
            return query.filter(Event.scouting_team_number == scouting_team_number)
    return query.filter(Event.scouting_team_number.is_(None))  # Show unassigned events if no team set


def filter_matches_by_scouting_team(query=None):
    """Filter matches by current user's scouting team number.
    If alliance mode is active, shows matches from all alliance members for shared events.
    Deduplicates matches that appear in multiple alliance members' databases.
    """
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Match.query
    
    if scouting_team_number is not None:
        # Check if alliance mode is active
        shared_event_codes = get_alliance_shared_event_codes()
        if shared_event_codes:
            # Show matches from all alliance members for shared events
            # Get event IDs for shared event codes from ANY alliance member
            upper_codes = [code.upper() for code in shared_event_codes]
            alliance_team_numbers = get_alliance_team_numbers()
            # Get all events with matching codes from any alliance member
            shared_events = Event.query.filter(
                func.upper(Event.code).in_(upper_codes),
                Event.scouting_team_number.in_(alliance_team_numbers)
            ).all()
            shared_event_ids = [event.id for event in shared_events]
            if shared_event_ids:
                # Build event code mapping to deduplicate matches
                event_code_map = {}
                for event in shared_events:
                    event_code_map[event.id] = event.code.upper()
                
                # Get matches and deduplicate by (event_code, match_type, match_number)
                # Using a subquery to get distinct matches by unique identifiers
                from sqlalchemy import distinct
                base_matches = query.filter(Match.event_id.in_(shared_event_ids))
                
                # Get all matches, then deduplicate in Python to preserve full Match objects
                all_matches = base_matches.all()
                seen = set()
                unique_matches = []
                for match in all_matches:
                    event_code = event_code_map.get(match.event_id, '').upper()
                    key = (event_code, match.match_type, match.match_number)
                    if key not in seen:
                        seen.add(key)
                        unique_matches.append(match.id)
                
                # Return query filtered to unique match IDs
                if unique_matches:
                    return Match.query.filter(Match.id.in_(unique_matches))
                else:
                    return Match.query.filter(Match.id.in_([]))  # Empty result
            else:
                # No matching shared events found - fall back to showing current team's matches
                return query.filter(Match.scouting_team_number == scouting_team_number)
        else:
            # Show only current team's matches
            return query.filter(Match.scouting_team_number == scouting_team_number)
    return query.filter(Match.scouting_team_number.is_(None))  # Show unassigned matches if no team set


def filter_scouting_data_by_scouting_team(query=None):
    """Filter scouting data by current user's scouting team number.
    If alliance mode is active, includes data from all alliance members for shared events.
    """
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = ScoutingData.query
    
    # If the current user has a scouting team assigned, show both their
    # team's data and any unassigned (NULL) scouting entries. This lets
    # users see data that was created before a scouting team was set.
    if scouting_team_number is not None:
        # Check if alliance mode is active
        alliance_team_numbers = get_alliance_team_numbers()
        shared_event_codes = get_alliance_shared_event_codes()
        
        if alliance_team_numbers and shared_event_codes:
            # Show data from all alliance members, but only for shared events
            # Get all event IDs from alliance members that match shared event codes
            upper_codes = [code.upper() for code in shared_event_codes]
            shared_events = Event.query.filter(
                func.upper(Event.code).in_(upper_codes),
                Event.scouting_team_number.in_(alliance_team_numbers)
            ).all()
            shared_event_ids = [event.id for event in shared_events]
            
            if shared_event_ids:
                # Get all matches from these events
                shared_match_ids = [match.id for match in Match.query.filter(Match.event_id.in_(shared_event_ids)).all()]
                if shared_match_ids:
                    # Show data from all alliance members for these matches, plus NULL entries
                    return query.filter(
                        or_(
                            ScoutingData.scouting_team_number.in_(alliance_team_numbers),
                            ScoutingData.scouting_team_number.is_(None)
                        ),
                        ScoutingData.match_id.in_(shared_match_ids)
                    )
            # No matches found in shared events - fall back to current team's data
            return query.filter(or_(ScoutingData.scouting_team_number == scouting_team_number,
                                    ScoutingData.scouting_team_number.is_(None)))
        else:
            # Show only current team's data
            return query.filter(or_(ScoutingData.scouting_team_number == scouting_team_number,
                                    ScoutingData.scouting_team_number.is_(None)))

    # If the current user has no scouting team, only show unassigned data
    return query.filter(ScoutingData.scouting_team_number.is_(None))  # Show unassigned data if no team set


def filter_scouting_data_only_by_scouting_team(query=None):
    """Strict filter: only return scouting data that matches the current user's scouting team.
    If alliance mode is active, includes data from all alliance members for shared events.

    This differs from `filter_scouting_data_by_scouting_team` which also returns
    unassigned (NULL) entries when a scouting team is set. For prediction and
    analytics use-cases we want to avoid accidentally including NULL/unassigned
    entries from other teams, so analytics should call this stricter helper.
    """
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = ScoutingData.query

    if scouting_team_number is not None:
        # Check if alliance mode is active
        alliance_team_numbers = get_alliance_team_numbers()
        shared_event_codes = get_alliance_shared_event_codes()
        
        if alliance_team_numbers and shared_event_codes:
            # Show data from all alliance members, but only for shared events
            # Get all event IDs from alliance members that match shared event codes
            upper_codes = [code.upper() for code in shared_event_codes]
            shared_events = Event.query.filter(
                func.upper(Event.code).in_(upper_codes),
                Event.scouting_team_number.in_(alliance_team_numbers)
            ).all()
            shared_event_ids = [event.id for event in shared_events]
            
            if shared_event_ids:
                # Get all matches from these events
                shared_match_ids = [match.id for match in Match.query.filter(Match.event_id.in_(shared_event_ids)).all()]
                if shared_match_ids:
                    # Show data from all alliance members for these matches
                    return query.filter(
                        ScoutingData.scouting_team_number.in_(alliance_team_numbers),
                        ScoutingData.match_id.in_(shared_match_ids)
                    )
            # No matches found in shared events - fall back to current team's data
            return query.filter(ScoutingData.scouting_team_number == scouting_team_number)
        else:
            # Show only current team's data
            return query.filter(ScoutingData.scouting_team_number == scouting_team_number)

    # If no scouting team configured, only return unassigned entries (legacy behavior)
    return query.filter(ScoutingData.scouting_team_number.is_(None))


def filter_alliance_selections_by_scouting_team(query=None):
    """Filter alliance selections by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = AllianceSelection.query
    
    if scouting_team_number is not None:
        return query.filter(AllianceSelection.scouting_team_number == scouting_team_number)
    return query.filter(AllianceSelection.scouting_team_number.is_(None))


def filter_do_not_pick_by_scouting_team(query=None):
    """Filter do not pick entries by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = DoNotPickEntry.query
    
    if scouting_team_number is not None:
        return query.filter(DoNotPickEntry.scouting_team_number == scouting_team_number)
    return query.filter(DoNotPickEntry.scouting_team_number.is_(None))


def filter_avoid_entries_by_scouting_team(query=None):
    """Filter avoid entries by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = AvoidEntry.query
    
    if scouting_team_number is not None:
        return query.filter(AvoidEntry.scouting_team_number == scouting_team_number)
    return query.filter(AvoidEntry.scouting_team_number.is_(None))


def filter_declined_entries_by_scouting_team(query=None):
    """Filter declined entries by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = DeclinedEntry.query

    if scouting_team_number is not None:
        return query.filter(DeclinedEntry.scouting_team_number == scouting_team_number)
    return query.filter(DeclinedEntry.scouting_team_number.is_(None))


def filter_pit_scouting_data_by_scouting_team(query=None):
    """Filter pit scouting data by current user's scouting team number.
    If alliance mode is active, includes pit data from all alliance members.
    """
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = PitScoutingData.query
    
    if scouting_team_number is not None:
        # Check if alliance mode is active
        alliance_team_numbers = get_alliance_team_numbers()
        if alliance_team_numbers:
            # Show pit data from all alliance members
            return query.filter(PitScoutingData.scouting_team_number.in_(alliance_team_numbers))
        else:
            # Show only current team's pit data
            return query.filter(PitScoutingData.scouting_team_number == scouting_team_number)
    return query.filter(PitScoutingData.scouting_team_number.is_(None))


def assign_scouting_team_to_model(model_instance):
    """Assign the current user's scouting team number to a model instance."""
    scouting_team_number = get_current_scouting_team_number()
    if scouting_team_number is not None and hasattr(model_instance, 'scouting_team_number'):
        model_instance.scouting_team_number = scouting_team_number
    return model_instance


def get_team_by_number(team_number):
    """Get a team by number, filtered by current scouting team."""
    return filter_teams_by_scouting_team().filter(Team.team_number == team_number).first()


def get_event_by_code(event_code):
    """Get an event by code, filtered by current scouting team.
    
    Uses case-insensitive comparison to handle event codes consistently
    regardless of how they were originally stored.
    """
    if not event_code:
        return None
    
    # Normalize to uppercase for comparison
    event_code_upper = event_code.upper()
    return filter_events_by_scouting_team().filter(func.upper(Event.code) == event_code_upper).first()


def filter_users_by_scouting_team(query=None):
    """Filter users by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = User.query
    
    if scouting_team_number is not None:
        return query.filter(User.scouting_team_number == scouting_team_number)
    return query.filter(User.scouting_team_number.is_(None))  # Show unassigned users if no team set


def validate_user_in_same_team(username):
    """Check if a user with the given username is in the same scouting team as current user."""
    scouting_team_number = get_current_scouting_team_number()
    if scouting_team_number is None:
        return True  # If no team set, allow all users
    # Perform a case-insensitive lookup for the username to avoid mismatches
    try:
        uname = str(username).strip().lower()
        user = User.query.filter(func.lower(User.username) == uname).first()
    except Exception:
        user = User.query.filter_by(username=username).first()

    if not user:
        return False

    return user.scouting_team_number == scouting_team_number


def find_user_in_same_team(username):
    """Return the canonical User object for `username` if the user exists and is
    in the same scouting team as the current user. Returns None otherwise.

    This helper performs a case-insensitive username lookup and is useful when
    code needs the DB's canonical username (for Socket.IO room names, etc.).
    """
    scouting_team_number = get_current_scouting_team_number()
    if scouting_team_number is None:
        # If no team set, return the user if it exists (no team scoping applied)
        try:
            uname = str(username).strip().lower()
            return User.query.filter(func.lower(User.username) == uname).first()
        except Exception:
            return User.query.filter_by(username=username).first()

    try:
        uname = str(username).strip().lower()
        user = User.query.filter(func.lower(User.username) == uname, User.scouting_team_number == scouting_team_number).first()
    except Exception:
        user = User.query.filter_by(username=username, scouting_team_number=scouting_team_number).first()

    return user
