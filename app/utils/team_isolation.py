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
    
    In alliance mode, also searches alliance member events if not found
    in the current user's events.
    """
    if not event_code:
        return None
    
    # Normalize to uppercase for comparison
    event_code_upper = event_code.upper()
    
    # First try to find in current user's events
    event = filter_events_by_scouting_team().filter(func.upper(Event.code) == event_code_upper).first()
    
    if event:
        return event
    
    # If not found and in alliance mode, search alliance member events
    alliance_team_numbers = get_alliance_team_numbers()
    if alliance_team_numbers:
        event = Event.query.filter(
            func.upper(Event.code) == event_code_upper,
            Event.scouting_team_number.in_(alliance_team_numbers)
        ).first()
    
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

    events_by_code = {}
    # Precompute alliance sets
    alliance = None
    try:
        from app.models import TeamAllianceStatus
        alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team) if current_team else None
    except Exception:
        alliance = None

    alliance_event_codes_upper = set([c.strip().upper() for c in (alliance.get_shared_events() if alliance else [])]) if alliance else set()
    member_team_numbers_set = set([m.team_number for m in (alliance.get_active_members() if alliance else [])]) if alliance else set()

    for e in combined:
        key = (getattr(e, 'code', None) or f'__id_{getattr(e, "id", None)}').strip().upper()
        context_alliance = False
        try:
            if alliance:
                if key in alliance_event_codes_upper:
                    context_alliance = True
                else:
                    for t in getattr(e, 'teams', []) or []:
                        if getattr(t, 'team_number', None) in member_team_numbers_set:
                            context_alliance = True
                            break
        except Exception:
            context_alliance = False

        if key in events_by_code:
            if alliance and context_alliance and not (getattr(events_by_code[key], 'code', '').strip().upper() in alliance_event_codes_upper):
                events_by_code[key] = e
            elif event_score(e) > event_score(events_by_code[key]):
                events_by_code[key] = e
        else:
            events_by_code[key] = e

    deduped_events = []
    from app.models import ScoutingAllianceEvent
    for key, event in events_by_code.items():
        is_alliance = False
        try:
            if alliance:
                if key in alliance_event_codes_upper:
                    is_alliance = True
                else:
                    for t in getattr(event, 'teams', []) or []:
                        if getattr(t, 'team_number', None) in member_team_numbers_set:
                            is_alliance = True
                            break
            if not is_alliance and not key.startswith('__id_'):
                sae = ScoutingAllianceEvent.query.filter(func.upper(ScoutingAllianceEvent.event_code) == key, ScoutingAllianceEvent.is_active == True).first()
                is_alliance = sae is not None
        except Exception:
            is_alliance = False

        try:
            setattr(event, 'is_alliance', is_alliance)
        except Exception:
            pass
        deduped_events.append(event)

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
