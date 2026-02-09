"""
Team isolation utilities for multi-tenant scouting platform.
Provides helper functions to filter database queries by scouting team.
"""

from flask_login import current_user
from app.models import Team, Event, Match, ScoutingData, AllianceSelection, DoNotPickEntry, AvoidEntry, PitScoutingData, User, DeclinedEntry
from sqlalchemy import or_, func


def get_alliance_team_numbers():
    """Get list of all team numbers in the active alliance (including current team and game_config_team).
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
            team_numbers = set(active_alliance.get_member_team_numbers())
            
            # Also include the game_config_team if set (data may be synced under this team)
            if active_alliance.game_config_team:
                team_numbers.add(active_alliance.game_config_team)
            
            return list(team_numbers)
        
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
    Deduplicates by team_number at SQL level.
    """
    from sqlalchemy import distinct
    
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Team.query
    
    if scouting_team_number is not None:
        # Check if alliance mode is active by presence of alliance team numbers
        alliance_team_numbers = get_alliance_team_numbers()
        if alliance_team_numbers:
            # Show all teams from any alliance member (don't filter by scouting_team_number)
            # Teams are shared across the alliance when alliance mode is active
            # Use DISTINCT on team_number to prevent duplicates
            return query.filter(Team.scouting_team_number.in_(alliance_team_numbers)).distinct(Team.team_number)
        else:
            # Show only current team's teams
            return query.filter(Team.scouting_team_number == scouting_team_number)
    return query.filter(Team.scouting_team_number.is_(None))  # Show unassigned teams if no team set


def get_all_teams_at_event(event_id=None, event_code=None):
    """Get ALL teams at an event, regardless of scouting_team_number.
    This is used when we want to show all teams at an event for analysis/graphs,
    not just teams that the current scouting team imported.
    
    Args:
        event_id: The event database ID
        event_code: The event code (alternative to event_id)
    
    Returns:
        List of Team objects at the event, deduplicated by team_number
    """
    if not event_id and not event_code:
        return []
    
    # Find the event
    if event_id:
        event = Event.query.get(event_id)
    else:
        # Find any event with this code (case-insensitive)
        event = Event.query.filter(func.upper(Event.code) == event_code.upper()).first()
    
    if not event:
        return []
    
    # Get all teams associated with this event through the team_event relationship
    # This includes teams from all scouting teams
    all_teams = Team.query.join(Team.events).filter(Event.id == event.id).all()
    
    # Also get teams from matches at events with the same code
    # This catches teams that might not be in the team_event table but have matches
    event_codes_to_check = [event.code.upper()]
    events_with_same_code = Event.query.filter(func.upper(Event.code) == event.code.upper()).all()
    event_ids_to_check = [e.id for e in events_with_same_code]
    
    # Get teams from matches at these events
    matches = Match.query.filter(Match.event_id.in_(event_ids_to_check)).all()
    team_numbers_from_matches = set()
    for match in matches:
        try:
            if match.red_alliance:
                for tn in match.red_alliance.split(','):
                    tn = tn.strip()
                    if tn.isdigit():
                        team_numbers_from_matches.add(int(tn))
            if match.blue_alliance:
                for tn in match.blue_alliance.split(','):
                    tn = tn.strip()
                    if tn.isdigit():
                        team_numbers_from_matches.add(int(tn))
        except Exception:
            continue
    
    # Add teams from matches that aren't already in the list
    existing_team_numbers = {t.team_number for t in all_teams}
    for tn in team_numbers_from_matches:
        if tn not in existing_team_numbers:
            team = Team.query.filter_by(team_number=tn).first()
            if team:
                all_teams.append(team)
                existing_team_numbers.add(tn)
    
    # Deduplicate by team_number, preferring teams with meaningful names
    teams_by_number = {}
    for team in all_teams:
        tn = team.team_number
        if tn not in teams_by_number:
            teams_by_number[tn] = team
        else:
            # Prefer team with meaningful name
            existing = teams_by_number[tn]
            existing_name = (existing.team_name or '').strip()
            team_name = (team.team_name or '').strip()
            if team_name and (not existing_name or existing_name.isdigit()):
                teams_by_number[tn] = team
    
    return sorted(teams_by_number.values(), key=lambda t: t.team_number)


def filter_events_by_scouting_team(query=None):
    """Filter events by current user's scouting team number.
    If alliance mode is active, filters by alliance shared event codes AND alliance team numbers.
    Deduplicates by uppercase event code at SQL level.
    """
    from sqlalchemy import distinct
    
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Event.query
    
    if scouting_team_number is not None:
        # Check if alliance mode is active
        shared_event_codes = get_alliance_shared_event_codes()
        if shared_event_codes:
            # Show only events that are in the alliance's shared event list
            # AND belong to alliance members (including game_config_team)
            # Use uppercase comparison to handle case-insensitive event codes
            # Use DISTINCT on uppercase code to prevent duplicate events
            upper_codes = [code.upper() for code in shared_event_codes]
            alliance_team_numbers = get_alliance_team_numbers()
            return query.filter(
                func.upper(Event.code).in_(upper_codes),
                Event.scouting_team_number.in_(alliance_team_numbers)
            ).distinct(func.upper(Event.code))
        else:
            # Show only current team's events
            return query.filter(Event.scouting_team_number == scouting_team_number)
    return query.filter(Event.scouting_team_number.is_(None))  # Show unassigned events if no team set


def filter_matches_by_scouting_team(query=None):
    """Filter matches by current user's scouting team number.
    If alliance mode is active, shows matches from all alliance members for shared events.
    Deduplicates matches at SQL level using subquery with MIN(id) grouped by event code, match type, and match number.
    """
    from sqlalchemy import select, and_
    from app import db
    
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = Match.query
    
    if scouting_team_number is not None:
        # Check if alliance mode is active
        alliance_team_numbers = get_alliance_team_numbers()
        if alliance_team_numbers:
            # Show matches from all alliance members. We include matches
            # where the event is associated with an alliance team OR where
            # either red_alliance or blue_alliance contains a member team's number.
            alliance_team_numbers = list(alliance_team_numbers)

            from sqlalchemy import func as sql_func
            from sqlalchemy import or_

            # Build match filters for red/blue alliance membership
            red_filters = [Match.red_alliance.contains(str(n)) for n in alliance_team_numbers]
            blue_filters = [Match.blue_alliance.contains(str(n)) for n in alliance_team_numbers]

            # Build subquery that deduplicates matches by event code / match type / number
            subq = db.session.query(
                sql_func.min(Match.id).label('match_id')
            ).join(
                Event, Match.event_id == Event.id
            ).filter(
                or_(
                    Event.scouting_team_number.in_(alliance_team_numbers),
                    *red_filters,
                    *blue_filters
                )
            ).group_by(
                sql_func.upper(Event.code),
                Match.match_type,
                Match.match_number
            ).subquery()

            return query.filter(Match.id.in_(select(subq.c.match_id)))
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
            # Use SQL subquery instead of loading all events/matches into memory
            from sqlalchemy import select
            from app import db
            upper_codes = [code.upper() for code in shared_event_codes]
            
            # Subquery for event IDs
            event_subq = db.session.query(Event.id).filter(
                func.upper(Event.code).in_(upper_codes),
                Event.scouting_team_number.in_(alliance_team_numbers)
            ).subquery()
            
            # Subquery for match IDs from those events
            match_subq = db.session.query(Match.id).filter(
                Match.event_id.in_(select(event_subq.c.id))
            ).subquery()
            
            # Show data from all alliance members for these matches, plus NULL entries
            return query.filter(
                or_(
                    ScoutingData.scouting_team_number.in_(alliance_team_numbers),
                    ScoutingData.scouting_team_number.is_(None)
                ),
                ScoutingData.match_id.in_(select(match_subq.c.id))
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
            # Use SQL subquery instead of loading all events/matches into memory
            from sqlalchemy import select
            from app import db
            upper_codes = [code.upper() for code in shared_event_codes]
            
            # Subquery for event IDs
            event_subq = db.session.query(Event.id).filter(
                func.upper(Event.code).in_(upper_codes),
                Event.scouting_team_number.in_(alliance_team_numbers)
            ).subquery()
            
            # Subquery for match IDs from those events
            match_subq = db.session.query(Match.id).filter(
                Match.event_id.in_(select(event_subq.c.id))
            ).subquery()
            
            # Show data from all alliance members for these matches
            return query.filter(
                ScoutingData.scouting_team_number.in_(alliance_team_numbers),
                ScoutingData.match_id.in_(select(match_subq.c.id))
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


def filter_want_list_by_scouting_team(query=None):
    """Filter want list entries by current user's scouting team number."""
    from app.models import WantListEntry
    scouting_team_number = get_current_scouting_team_number()
    if query is None:
        query = WantListEntry.query

    if scouting_team_number is not None:
        return query.filter(WantListEntry.scouting_team_number == scouting_team_number)
    return query.filter(WantListEntry.scouting_team_number.is_(None))


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


def dedupe_team_list(teams, prefer_alliance=False, alliance_team_numbers=None, current_scouting_team=None):
    """Deduplicate a list of Team-like objects by team_number.

    Preference rules:
      - If prefer_alliance is True, prefer a Team whose scouting_team_number
        is in the provided alliance_team_numbers list.
      - If prefer_alliance is False, prefer a Team whose scouting_team_number
        equals the provided current_scouting_team.

    Returns a sorted list of unique teams (by team_number).
    """
    if not teams:
        return []

    alliance_team_numbers = set(alliance_team_numbers or [])
    deduped = {}

    for t in teams:
        tn = getattr(t, 'team_number', None)
        if tn is None:
            # Skip malformed entries
            continue
        if tn not in deduped:
            deduped[tn] = t
            continue

        existing = deduped[tn]

        try:
            if prefer_alliance:
                if getattr(t, 'scouting_team_number', None) in alliance_team_numbers and getattr(existing, 'scouting_team_number', None) not in alliance_team_numbers:
                    deduped[tn] = t
            else:
                if getattr(t, 'scouting_team_number', None) == current_scouting_team and getattr(existing, 'scouting_team_number', None) != current_scouting_team:
                    deduped[tn] = t
        except Exception:
            # If comparison fails, keep existing
            pass

    return sorted(deduped.values(), key=lambda x: (getattr(x, 'team_number', 0) or 0))

def get_team_by_number(team_number):
    """Get a team by number, filtered by current scouting team."""
    return filter_teams_by_scouting_team().filter(Team.team_number == team_number).first()


def get_event_by_code(event_code):
    """Get an event by code, filtered by current scouting team.

    Uses case-insensitive comparison to handle event codes consistently
    regardless of how they were originally stored.

    Supports year-prefixed event codes (e.g., "2026OKTU") and raw codes (e.g., "OKTU").
    If a raw code is passed, it will try year-prefixed version first using the season
    from game_config.

    In alliance mode, prefer a synthetic alliance entry when the code is part
    of the active alliance's shared events (this ensures pages show the
    '(Alliance)' choice instead of the local team copy when appropriate).
    """
    if not event_code:
        return None

    # Normalize to uppercase and strip whitespace for comparison
    event_code_upper = str(event_code).strip().upper()

    # Try to construct year-prefixed code if the code appears to be raw (no year prefix)
    # Year-prefixed codes start with 4 digits (e.g., "2026OKTU")
    year_prefixed_code = event_code_upper
    if not (len(event_code_upper) >= 4 and event_code_upper[:4].isdigit()):
        # Code doesn't start with year, try to add year prefix from the team's game_config
        # Use the team-specific config (not global) to get the correct season
        try:
            from app.utils.config_manager import get_effective_game_config
            game_config = get_effective_game_config()
            if isinstance(game_config, dict):
                season = game_config.get('season')
                if season:
                    year_prefixed_code = f"{season}{event_code_upper}"
        except Exception:
            # Fallback: try to get season from current user's team config directly
            try:
                from app.utils.config_manager import load_game_config
                from flask_login import current_user
                team_number = None
                if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                    team_number = getattr(current_user, 'scouting_team_number', None)
                game_config = load_game_config(team_number=team_number)
                if isinstance(game_config, dict):
                    season = game_config.get('season')
                    if season:
                        year_prefixed_code = f"{season}{event_code_upper}"
            except Exception:
                pass

    # First try to find with year-prefixed code in current user's events (scoped by scouting team)
    event = filter_events_by_scouting_team().filter(func.upper(Event.code) == year_prefixed_code).first()
    
    # If not found with year prefix, try with the original code
    if not event and year_prefixed_code != event_code_upper:
        event = filter_events_by_scouting_team().filter(func.upper(Event.code) == event_code_upper).first()

    # Determine if we are in an active alliance that shares this code
    current_team = get_current_scouting_team_number()
    try:
        from app.models import TeamAllianceStatus, ScoutingAllianceEvent
        active_alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team) if current_team else None
    except Exception:
        active_alliance = None

    # If alliance is active and the code is a shared alliance event (or present in ScoutingAllianceEvent table),
    # prefer returning a synthetic alliance entry so UI dropdowns select the alliance copy.
    try:
        is_shared_by_alliance = False
        if active_alliance:
            shared_codes = [c.strip().upper() for c in (active_alliance.get_shared_events() or []) if c]
            # Check both raw code and year-prefixed code
            if event_code_upper in shared_codes or year_prefixed_code in shared_codes:
                is_shared_by_alliance = True
        # Also check ScoutingAllianceEvent table for an active mapping (try both codes)
        sae_exists = False
        try:
            sae_exists = ScoutingAllianceEvent.query.filter(
                or_(func.upper(ScoutingAllianceEvent.event_code) == event_code_upper,
                    func.upper(ScoutingAllianceEvent.event_code) == year_prefixed_code),
                ScoutingAllianceEvent.is_active == True
            ).first() is not None
        except Exception:
            sae_exists = False

        if (is_shared_by_alliance or (active_alliance and sae_exists)):
            # Find a local event copy to borrow display attributes if available (any member's event)
            # Try year-prefixed code first
            local = Event.query.filter(func.upper(Event.code) == year_prefixed_code).first()
            if not local and year_prefixed_code != event_code_upper:
                local = Event.query.filter(func.upper(Event.code) == event_code_upper).first()
            from types import SimpleNamespace
            obj = SimpleNamespace()
            obj.id = f'alliance_{year_prefixed_code}'
            obj.name = getattr(local, 'name', None) or year_prefixed_code
            obj.code = year_prefixed_code
            obj.location = getattr(local, 'location', None) if local else None
            obj.year = getattr(local, 'year', None) if local else None
            obj.scouting_team_number = None
            obj.is_alliance = True
            return obj
    except Exception:
        # On error, fall back to DB results
        pass

    # If we found an event scoped to current user's team, return it
    if event:
        return event

    # Otherwise, if alliance mode is active, search alliance member events
    alliance_team_numbers = get_alliance_team_numbers()
    if alliance_team_numbers:
        # Try year-prefixed code first
        event = Event.query.filter(
            func.upper(Event.code) == year_prefixed_code,
            Event.scouting_team_number.in_(alliance_team_numbers)
        ).first()
        # If not found, try original code
        if not event and year_prefixed_code != event_code_upper:
            event = Event.query.filter(
                func.upper(Event.code) == event_code_upper,
                Event.scouting_team_number.in_(alliance_team_numbers)
            ).first()
        if event:
            return event

    # Final fallback: find any event with this code (case-insensitive) regardless of scouting_team_number.
    # This helps cases where the configured current_event_code refers to an event imported by another team.
    try:
        # Try year-prefixed code first
        fallback_event = Event.query.filter(func.upper(Event.code) == year_prefixed_code).first()
        # If not found, try original code
        if not fallback_event and year_prefixed_code != event_code_upper:
            fallback_event = Event.query.filter(func.upper(Event.code) == event_code_upper).first()
        if fallback_event:
            return fallback_event
    except Exception:
        pass

    return event


def get_combined_dropdown_events():
    """Return a combined list of Event objects and alliance event entries
    for use in dropdowns. This keeps local events and explicit alliance events
    separate (so non-alliance vs. alliance entries with the same code are
    both shown). Deduplication should be handled by the template `dedupe_events` filter.
    """
    from types import SimpleNamespace
    from sqlalchemy import func
    try:
        scouting_team_number = get_current_scouting_team_number()
        # If alliance is active for this team, return the union of member events + explicit alliance event codes
        alliance_team_numbers = get_alliance_team_numbers()
        shared_codes = get_alliance_shared_event_codes()

        if scouting_team_number is not None and alliance_team_numbers and shared_codes:
            member_events = []
            try:
                # Join on teams to capture events associated with alliance members
                member_events = Event.query.join(Event.teams).filter(Team.team_number.in_(alliance_team_numbers)).distinct().all()
            except Exception:
                member_events = []

            code_events = []
            try:
                upper_codes = [c.upper() for c in (shared_codes or [])]
                if upper_codes:
                    code_events = Event.query.filter(func.upper(Event.code).in_(upper_codes)).all()
            except Exception:
                code_events = []

            # Combine lists, avoiding identical ORM objects
            events = list(member_events)
            for e in code_events:
                if e not in events:
                    events.append(e)
        else:
            # Not an active alliance case - just return scoped events
            events = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.name).all()
    except Exception:
        events = []

    # Collect alliance synthetic entries for the current user's active alliance (if any)
    alliance_entries = []
    try:
        current_team = get_current_scouting_team_number()
        from app.models import TeamAllianceStatus, ScoutingAllianceEvent
        if current_team:
            active_alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team)
            if active_alliance:
                codes = [c.event_code for c in ScoutingAllianceEvent.query.filter_by(alliance_id=active_alliance.id, is_active=True).all()]
                # For each code, construct a synthetic event-like object
                for code in set(codes or []):
                    # Find existing local event to reuse attributes when possible
                    local = next((e for e in events if (getattr(e, 'code', '') or '').upper() == str(code).upper()), None)
                    name = None
                    year = None
                    if local:
                        name = local.name
                        year = local.year
                    # Create a simple object mimicking Event
                    obj = SimpleNamespace()
                    obj.id = f'alliance_{str(code).upper()}'
                    obj.name = name or str(code)
                    obj.code = str(code).upper()
                    obj.location = None
                    obj.year = year
                    obj.scouting_team_number = None
                    obj.is_alliance = True
                    alliance_entries.append(obj)
    except Exception:
        pass

    # Add alliance synthetic entries to the event list (after local entries)
    combined = list(events) + alliance_entries
    try:
        combined = sorted(combined, key=lambda x: (getattr(x, 'year', 0) or 0, getattr(x, 'name', '') or ''), reverse=True)
    except Exception:
        pass

    # Now apply the /events index style dedup and is_alliance labeling
    def event_score(e):
        score = 0
        try:
            if getattr(e, 'name', None):
                score += 10
            if getattr(e, 'location', None):
                score += 5
            if getattr(e, 'start_date', None):
                score += 5
            if getattr(e, 'end_date', None):
                score += 3
            if getattr(e, 'timezone', None):
                score += 2
            if getattr(e, 'year', None):
                score += 1
        except Exception:
            pass
        return score

    # Separate alliance and team events to allow both to exist with same code
    team_events_by_code = {}
    alliance_events_by_code = {}
    
    # Precompute alliance sets
    alliance = None
    try:
        from app.models import TeamAllianceStatus
        alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team) if current_team else None
    except Exception:
        alliance = None

    alliance_event_codes_upper = set([c.strip().upper() for c in (alliance.get_shared_events() if alliance else [])]) if alliance else set()
    member_team_numbers_set = set([m.team_number for m in (alliance.get_active_members() if alliance else [])]) if alliance else set()

    from app.models import ScoutingAllianceEvent
    
    for e in combined:
        code = (getattr(e, 'code', None) or f'__id_{getattr(e, "id", None)}').strip().upper()
        
        # Check if this is an alliance synthetic entry (created above with id='alliance_CODE')
        is_synthetic_alliance = str(getattr(e, 'id', '')).startswith('alliance_')
        
        # Determine if this event should be treated as an alliance event
        is_alliance_event = False
        try:
            if is_synthetic_alliance:
                is_alliance_event = True
            elif alliance:
                # Check if event code is in alliance shared events
                # Also consider if the code is year-prefixed (e.g., 2026TEST)
                from app.utils.api_utils import strip_year_prefix
                code_stripped = strip_year_prefix(code)
                if code in alliance_event_codes_upper or code_stripped in alliance_event_codes_upper:
                    # Only mark as alliance if it's NOT owned by the current user's team
                    event_scouting_team = getattr(e, 'scouting_team_number', None)
                    if event_scouting_team != current_team:
                        is_alliance_event = True
                else:
                    # Check if event is owned by an alliance member (not current team)
                    event_scouting_team = getattr(e, 'scouting_team_number', None)
                    if event_scouting_team and event_scouting_team != current_team and event_scouting_team in member_team_numbers_set:
                        is_alliance_event = True
            
            # Also check ScoutingAllianceEvent table but only if not owned by current team
            if not is_alliance_event and not code.startswith('__id_'):
                    event_scouting_team = getattr(e, 'scouting_team_number', None)
                    if event_scouting_team != current_team:
                        from app.utils.api_utils import strip_year_prefix
                        code_stripped = strip_year_prefix(code)
                        sae = ScoutingAllianceEvent.query.filter(
                            ScoutingAllianceEvent.is_active == True,
                            func.upper(ScoutingAllianceEvent.event_code).in_([code.upper(), code_stripped.upper()])
                        ).first()
                        if sae is not None:
                            is_alliance_event = True
        except Exception:
            is_alliance_event = False
        
        # Set the is_alliance attribute
        try:
            setattr(e, 'is_alliance', is_alliance_event)
        except Exception:
            pass
        
        # Store in appropriate dictionary based on alliance status
        if is_alliance_event:
            if code in alliance_events_by_code:
                if event_score(e) > event_score(alliance_events_by_code[code]):
                    alliance_events_by_code[code] = e
            else:
                alliance_events_by_code[code] = e
        else:
            if code in team_events_by_code:
                if event_score(e) > event_score(team_events_by_code[code]):
                    team_events_by_code[code] = e
            else:
                team_events_by_code[code] = e

    # Combine both lists - team events first, then alliance events
    deduped_events = list(team_events_by_code.values()) + list(alliance_events_by_code.values())
    
    # Sort by year desc, then name
    try:
        deduped_events = sorted(deduped_events, key=lambda x: (getattr(x, 'year', 0) or 0, getattr(x, 'name', '') or ''), reverse=True)
    except Exception:
        pass

    return deduped_events


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
