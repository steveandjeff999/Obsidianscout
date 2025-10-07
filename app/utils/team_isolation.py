"""
Team isolation utilities for multi-tenant scouting platform.
Provides helper functions to filter database queries by scouting team.
"""

from flask_login import current_user
from app.models import Team, Event, Match, ScoutingData, AllianceSelection, DoNotPickEntry, AvoidEntry, PitScoutingData, User
from sqlalchemy import or_


def get_current_scouting_team_number():
    """Get the current user's scouting team number."""
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
        return current_user.scouting_team_number
    return None


def get_current_scouting_team():
    """Alias for get_current_scouting_team_number for compatibility."""
    return get_current_scouting_team_number()


def filter_teams_by_scouting_team(query=None):
    """Filter teams by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Team.query
    
    if scouting_team_number is not None:
        return query.filter(Team.scouting_team_number == scouting_team_number)
    return query.filter(Team.scouting_team_number.is_(None))  # Show unassigned teams if no team set


def filter_events_by_scouting_team(query=None):
    """Filter events by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Event.query
    
    if scouting_team_number is not None:
        return query.filter(Event.scouting_team_number == scouting_team_number)
    return query.filter(Event.scouting_team_number.is_(None))  # Show unassigned events if no team set


def filter_matches_by_scouting_team(query=None):
    """Filter matches by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Match.query
    
    if scouting_team_number is not None:
        return query.filter(Match.scouting_team_number == scouting_team_number)
    return query.filter(Match.scouting_team_number.is_(None))  # Show unassigned matches if no team set


def filter_scouting_data_by_scouting_team(query=None):
    """Filter scouting data by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = ScoutingData.query
    
    # If the current user has a scouting team assigned, show both their
    # team's data and any unassigned (NULL) scouting entries. This lets
    # users see data that was created before a scouting team was set.
    if scouting_team_number is not None:
        return query.filter(or_(ScoutingData.scouting_team_number == scouting_team_number,
                                ScoutingData.scouting_team_number.is_(None)))

    # If the current user has no scouting team, only show unassigned data
    return query.filter(ScoutingData.scouting_team_number.is_(None))  # Show unassigned data if no team set


def filter_scouting_data_only_by_scouting_team(query=None):
    """Strict filter: only return scouting data that matches the current user's scouting team.

    This differs from `filter_scouting_data_by_scouting_team` which also returns
    unassigned (NULL) entries when a scouting team is set. For prediction and
    analytics use-cases we want to avoid accidentally including NULL/unassigned
    entries from other teams, so analytics should call this stricter helper.
    """
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = ScoutingData.query

    if scouting_team_number is not None:
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


def filter_pit_scouting_data_by_scouting_team(query=None):
    """Filter pit scouting data by current user's scouting team number."""
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = PitScoutingData.query
    
    if scouting_team_number is not None:
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
    """Get an event by code, filtered by current scouting team."""
    return filter_events_by_scouting_team().filter(Event.code == event_code).first()


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
    
    user = User.query.filter_by(username=username).first()
    if not user:
        return False
    
    return user.scouting_team_number == scouting_team_number
