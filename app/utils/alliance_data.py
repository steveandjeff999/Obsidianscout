"""
Alliance-aware data retrieval utilities.

When alliance mode is active, these functions return data from the shared
alliance tables instead of team-specific tables. This provides a single
central database view for all alliance members.
"""

from flask import current_app
from flask_login import current_user
from sqlalchemy import func
from app import db
from app.models import (
    ScoutingData, PitScoutingData, Match, Team, Event,
    AllianceSharedScoutingData, AllianceSharedPitData,
    AllianceSharedQualitativeData, QualitativeScoutingData,
    ScoutingAlliance, ScoutingAllianceMember, TeamAllianceStatus
)
from app.utils.config_manager import is_alliance_mode_active, get_active_alliance_info


# Alliance data prefix - data copied from alliance members has this in scout_name
ALLIANCE_DATA_PREFIX = '[Alliance-'


def exclude_alliance_data_filter(model):
    """
    Returns a SQLAlchemy filter condition to exclude alliance-copied data.
    
    When NOT in alliance mode, we want to exclude any data that was copied
    from alliance members (identified by scout_name starting with '[Alliance-').
    
    Args:
        model: The SQLAlchemy model class (ScoutingData or PitScoutingData)
    
    Returns:
        SQLAlchemy filter condition
    """
    from sqlalchemy import or_
    return or_(
        model.scout_name == None,
        ~model.scout_name.like(f'{ALLIANCE_DATA_PREFIX}%')
    )


def filter_out_alliance_data(query, model):
    """
    Apply filter to exclude alliance-copied data from a query.
    
    This should be used when NOT in alliance mode to hide data that was
    copied from alliance members.
    
    Args:
        query: SQLAlchemy query object
        model: The model class being queried (ScoutingData or PitScoutingData)
    
    Returns:
        Filtered query
    """
    return query.filter(exclude_alliance_data_filter(model))


def get_active_alliance_id():
    """Get the active alliance ID for the current user's team, or None if not in alliance mode."""
    if not is_alliance_mode_active():
        return None
    
    alliance_info = get_active_alliance_info()
    if alliance_info:
        return alliance_info.get('alliance_id')
    return None


def get_active_alliance_id_for_team(team_number):
    """Get the active alliance ID for a specific team, or None if not in alliance mode.
    
    This is useful for API endpoints that use token auth instead of current_user.
    """
    if not team_number:
        return None
    
    # Check if the team has alliance mode active
    if not TeamAllianceStatus.is_alliance_mode_active_for_team(team_number):
        return None
    
    # Get the active alliance for this team
    active_alliance = TeamAllianceStatus.get_active_alliance_for_team(team_number)
    if active_alliance:
        return active_alliance.id
    
    return None


def get_current_scouting_team_number():
    """Get the current user's scouting team number."""
    if current_user and hasattr(current_user, 'scouting_team_number'):
        return current_user.scouting_team_number
    return None


def is_alliance_admin(alliance_id=None):
    """Check if current user is an admin of the active alliance (or specified alliance)."""
    if alliance_id is None:
        alliance_id = get_active_alliance_id()
    
    if not alliance_id:
        return False
    
    current_team = get_current_scouting_team_number()
    if not current_team:
        return False
    
    member = ScoutingAllianceMember.query.filter_by(
        alliance_id=alliance_id,
        team_number=current_team,
        role='admin',
        status='accepted'
    ).first()
    
    return member is not None


def can_delete_scouting_entry(entry, alliance_mode=False, alliance_id=None):
    """
    Check if the current user can delete a scouting entry.
    
    Rules:
    - Alliance admins can delete any alliance data
    - Users can always delete data they personally scouted (their scout_name matches)
    - In alliance mode, only admins or the original scout can delete
    - Outside alliance mode, users can delete their team's data
    
    Args:
        entry: The scouting data entry (ScoutingData or AllianceSharedScoutingData)
        alliance_mode: Whether we're in alliance mode
        alliance_id: The active alliance ID (if in alliance mode)
    
    Returns:
        bool: True if user can delete, False otherwise
    """
    current_team = get_current_scouting_team_number()
    
    # Check if user is alliance admin
    if alliance_mode and is_alliance_admin(alliance_id):
        return True
    
    # Check if user is the original scout (by scout_name containing their username)
    if hasattr(entry, 'scout_name') and entry.scout_name:
        if current_user.username and current_user.username.lower() in entry.scout_name.lower():
            return True
    
    # Check if user's scout_id matches
    if hasattr(entry, 'scout_id') and entry.scout_id:
        if hasattr(current_user, 'id') and entry.scout_id == current_user.id:
            return True
    
    # For alliance shared data, check if source team matches
    if hasattr(entry, 'source_scouting_team_number'):
        if entry.source_scouting_team_number == current_team:
            return True
    
    # For regular scouting data, check if team matches
    if hasattr(entry, 'scouting_team_number'):
        if entry.scouting_team_number == current_team:
            # But in alliance mode, only admins or original scouts can delete
            if alliance_mode:
                return False  # Already checked admin above
            return True
    
    return False


def can_delete_pit_entry(entry, alliance_mode=False, alliance_id=None):
    """
    Check if the current user can delete a pit scouting entry.
    Same rules as scouting entries.
    """
    return can_delete_scouting_entry(entry, alliance_mode, alliance_id)


def get_scouting_data_query(event_ids=None, team_number=None):
    """
    Get scouting data query - uses alliance shared data if alliance mode is active.
    
    Returns:
        tuple: (query, is_alliance_mode, alliance_id)
    """
    alliance_id = get_active_alliance_id()
    
    if alliance_id:
        # Alliance mode - query from shared tables
        query = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        )
        
        if event_ids:
            query = query.join(Match).filter(Match.event_id.in_(event_ids))
        
        if team_number:
            query = query.join(Team).filter(Team.team_number == team_number)
        
        return query, True, alliance_id
    else:
        # Normal mode - query from team's data
        current_team = get_current_scouting_team_number()
        
        # Get alliance team numbers for filtering (includes game_config_team)
        from app.utils.team_isolation import get_alliance_team_numbers
        alliance_team_numbers = get_alliance_team_numbers() or []
        
        team_filter_numbers = [current_team] if current_team else []
        if alliance_team_numbers:
            team_filter_numbers.extend(alliance_team_numbers)
        team_filter_numbers = list(set(team_filter_numbers))
        
        query = ScoutingData.query
        if team_filter_numbers:
            query = query.filter(ScoutingData.scouting_team_number.in_(team_filter_numbers))
        
        # IMPORTANT: When NOT in alliance mode, exclude data copied from alliance
        # (entries with scout_name starting with [Alliance-)
        from sqlalchemy import or_
        query = query.filter(
            or_(
                ScoutingData.scout_name == None,
                ~ScoutingData.scout_name.like('[Alliance-%')
            )
        )
        
        if event_ids:
            query = query.join(Match).filter(Match.event_id.in_(event_ids))
        
        if team_number:
            query = query.join(Team).filter(Team.team_number == team_number)
        
        return query, False, None


def get_pit_data_query(team_number=None):
    """
    Get pit scouting data query - uses alliance shared data if alliance mode is active.
    
    Returns:
        tuple: (query, is_alliance_mode, alliance_id)
    """
    alliance_id = get_active_alliance_id()
    
    if alliance_id:
        # Alliance mode - query from shared tables
        query = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        )
        
        if team_number:
            query = query.join(Team).filter(Team.team_number == team_number)
        
        return query, True, alliance_id
    else:
        # Normal mode - query from team's data
        current_team = get_current_scouting_team_number()
        
        from app.utils.team_isolation import get_alliance_team_numbers
        alliance_team_numbers = get_alliance_team_numbers() or []
        
        team_filter_numbers = [current_team] if current_team else []
        if alliance_team_numbers:
            team_filter_numbers.extend(alliance_team_numbers)
        team_filter_numbers = list(set(team_filter_numbers))
        
        query = PitScoutingData.query
        if team_filter_numbers:
            # Only include data with matching scouting_team_number
            # (removed NULL fallback for proper data isolation)
            query = query.filter(
                PitScoutingData.scouting_team_number.in_(team_filter_numbers)
            )
        else:
            # If no team filter, show nothing (user must have a team assignment)
            query = query.filter(PitScoutingData.id < 0)  # No results
        
        # IMPORTANT: When NOT in alliance mode, exclude data copied from alliance
        # (entries with scout_name starting with [Alliance-)
        from sqlalchemy import or_ as or_clause
        query = query.filter(
            or_clause(
                PitScoutingData.scout_name == None,
                ~PitScoutingData.scout_name.like('[Alliance-%')
            )
        )
        
        if team_number:
            query = query.join(Team).filter(Team.team_number == team_number)
        
        return query, False, None


def get_all_scouting_data(event_ids=None, team_number=None, order_by_timestamp=True):
    """
    Get all scouting data, using alliance shared data if in alliance mode.
    
    Returns:
        tuple: (data_list, is_alliance_mode, alliance_id)
    """
    query, is_alliance_mode, alliance_id = get_scouting_data_query(event_ids, team_number)
    
    if order_by_timestamp:
        if is_alliance_mode:
            query = query.order_by(AllianceSharedScoutingData.timestamp.desc())
        else:
            query = query.order_by(ScoutingData.timestamp.desc())
    
    return query.all(), is_alliance_mode, alliance_id


def get_all_pit_data(team_number=None, order_by_timestamp=True):
    """
    Get all pit scouting data, using alliance shared data if in alliance mode.
    
    Returns:
        tuple: (data_list, is_alliance_mode, alliance_id)
    """
    query, is_alliance_mode, alliance_id = get_pit_data_query(team_number)
    
    if order_by_timestamp:
        if is_alliance_mode:
            query = query.order_by(AllianceSharedPitData.timestamp.desc())
        else:
            query = query.order_by(PitScoutingData.timestamp.desc())
    
    return query.all(), is_alliance_mode, alliance_id


def get_all_qualitative_data(event_ids=None, order_by_timestamp=True):
    """
    Get all qualitative scouting data, including alliance shared data if in alliance mode.
    
    Returns:
        tuple: (data_list, is_alliance_mode, alliance_id)
    """
    try:
        current_team = current_user.scouting_team_number
    except Exception:
        current_team = None
    
    if not current_team:
        return [], False, None
    
    is_alliance = is_alliance_mode_active()
    alliance_id = None
    
    # Get own qualitative data
    query = QualitativeScoutingData.query.filter_by(
        scouting_team_number=current_team
    )
    if event_ids:
        query = query.join(Match, QualitativeScoutingData.match_id == Match.id).filter(
            Match.event_id.in_(event_ids)
        )
    if order_by_timestamp:
        query = query.order_by(QualitativeScoutingData.timestamp.desc())
    
    try:
        own_entries = query.all()
    except Exception:
        # any error leaves session in a bad state; rollback and continue with empty list
        from app import db
        db.session.rollback()
        own_entries = []
    
    if is_alliance:
        alliance_id = get_active_alliance_id()
        if alliance_id:
            # Also get shared qualitative data from alliance members (excluding own)
            alliance_query = AllianceSharedQualitativeData.query.filter_by(
                alliance_id=alliance_id,
                is_active=True
            ).filter(
                AllianceSharedQualitativeData.source_scouting_team_number != current_team
            )
            if event_ids:
                alliance_query = alliance_query.join(
                    Match, AllianceSharedQualitativeData.match_id == Match.id
                ).filter(Match.event_id.in_(event_ids))
            if order_by_timestamp:
                alliance_query = alliance_query.order_by(AllianceSharedQualitativeData.timestamp.desc())
            
            try:
                alliance_entries = alliance_query.all()
            except Exception:
                from app import db
                db.session.rollback()
                alliance_entries = []
                current_app.logger.debug('Error querying alliance shared qualitative data, returning only own entries')
            return own_entries + alliance_entries, True, alliance_id
    
    return own_entries, False, None


def get_teams_with_scouting_data(event_id=None):
    """
    Get all teams that have scouting data, using alliance data if in alliance mode.
    In alliance mode, this returns unique team_numbers from alliance shared data
    and finds corresponding Team records from ANY alliance member.
    
    Args:
        event_id: Optional event ID to filter by
    
    Returns:
        tuple: (teams_list, is_alliance_mode, alliance_id)
    """
    alliance_id = get_active_alliance_id()
    
    if alliance_id:
        # Alliance mode - get unique team_numbers from shared data
        query = db.session.query(Team.team_number).select_from(AllianceSharedScoutingData).join(
            Team, AllianceSharedScoutingData.team_id == Team.id
        ).filter(
            AllianceSharedScoutingData.alliance_id == alliance_id,
            AllianceSharedScoutingData.is_active == True
        )
        
        if event_id:
            # Filter by event code, not event_id
            event = Event.query.get(event_id)
            if event:
                query = query.join(
                    Match, AllianceSharedScoutingData.match_id == Match.id
                ).join(
                    Event, Match.event_id == Event.id
                ).filter(func.upper(Event.code) == func.upper(event.code))
        
        team_numbers = [row[0] for row in query.distinct().all()]
        
        # Get Team records for these team_numbers from the current user's team isolation
        from app.utils.team_isolation import filter_teams_by_scouting_team
        teams = filter_teams_by_scouting_team().filter(Team.team_number.in_(team_numbers)).order_by(Team.team_number).all()
        
        # If not all team_numbers found, try to get them from any alliance member
        found_numbers = {t.team_number for t in teams}
        missing_numbers = set(team_numbers) - found_numbers
        if missing_numbers:
            from app.utils.team_isolation import get_alliance_team_numbers
            alliance_team_nums = get_alliance_team_numbers() or []
            additional_teams = Team.query.filter(
                Team.team_number.in_(missing_numbers),
                Team.scouting_team_number.in_(alliance_team_nums)
            ).all()
            teams.extend(additional_teams)
            teams = sorted(teams, key=lambda t: t.team_number)
        
        return teams, True, alliance_id
    else:
        # Normal mode
        current_team = get_current_scouting_team_number()
        
        from app.utils.team_isolation import get_alliance_team_numbers
        alliance_team_numbers = get_alliance_team_numbers() or []
        
        team_filter_numbers = [current_team] if current_team else []
        if alliance_team_numbers:
            team_filter_numbers.extend(alliance_team_numbers)
        team_filter_numbers = list(set(team_filter_numbers))
        
        query = Team.query.join(ScoutingData, Team.id == ScoutingData.team_id)
        if team_filter_numbers:
            query = query.filter(ScoutingData.scouting_team_number.in_(team_filter_numbers))
        
        if event_id:
            query = query.join(Match, ScoutingData.match_id == Match.id).filter(Match.event_id == event_id)
        
        teams = query.distinct().order_by(Team.team_number).all()
        return teams, False, None


def get_matches_with_scouting_data(event_id=None, event_code=None):
    """
    Get all matches that have scouting data, using alliance data if in alliance mode.
    In alliance mode, returns unique match_number/match_type combos from alliance shared data
    and finds corresponding Match records visible to the current user.
    
    Args:
        event_id: Optional event ID to filter by
        event_code: Optional event code to filter by (preferred in alliance mode)
    
    Returns:
        tuple: (matches_list, is_alliance_mode, alliance_id)
    """
    alliance_id = get_active_alliance_id()
    
    if alliance_id:
        # Alliance mode - get unique match_number/match_type combos from shared data
        # Determine event_code to filter by
        filter_event_code = event_code
        if not filter_event_code and event_id:
            event = Event.query.get(event_id)
            if event:
                filter_event_code = event.code
        
        # Query unique match identifiers from alliance data
        query = db.session.query(
            Match.match_number,
            Match.match_type,
            func.upper(Event.code).label('event_code')
        ).select_from(AllianceSharedScoutingData).join(
            Match, AllianceSharedScoutingData.match_id == Match.id
        ).join(
            Event, Match.event_id == Event.id
        ).filter(
            AllianceSharedScoutingData.alliance_id == alliance_id,
            AllianceSharedScoutingData.is_active == True
        )
        
        if filter_event_code:
            query = query.filter(func.upper(Event.code) == func.upper(filter_event_code))
        
        match_identifiers = query.distinct().all()
        
        if not match_identifiers:
            return [], True, alliance_id
        
        # Find corresponding Match records visible to the current user
        from app.utils.team_isolation import filter_matches_by_scouting_team
        matches = []
        
        for match_num, match_type, evt_code in match_identifiers:
            # Find a Match record with this match_number/match_type from visible matches
            match = filter_matches_by_scouting_team().join(Event).filter(
                Match.match_number == match_num,
                Match.match_type == match_type,
                func.upper(Event.code) == evt_code.upper()
            ).first()
            
            if match and match not in matches:
                matches.append(match)
        
        # Sort by match type and number
        matches = sorted(matches, key=lambda m: (m.match_type or '', m.match_number or 0))
        
        return matches, True, alliance_id
    else:
        # Normal mode
        current_team = get_current_scouting_team_number()
        
        from app.utils.team_isolation import get_alliance_team_numbers, filter_matches_by_scouting_team
        alliance_team_numbers = get_alliance_team_numbers() or []
        
        team_filter_numbers = [current_team] if current_team else []
        if alliance_team_numbers:
            team_filter_numbers.extend(alliance_team_numbers)
        team_filter_numbers = list(set(team_filter_numbers))
        
        query = Match.query.join(ScoutingData, Match.id == ScoutingData.match_id)
        if team_filter_numbers:
            query = query.filter(ScoutingData.scouting_team_number.in_(team_filter_numbers))
        
        if event_id:
            query = query.filter(Match.event_id == event_id)
        
        matches = query.distinct().order_by(*Match.schedule_order()).all()
        return matches, False, None


def get_all_teams_for_alliance(event_id=None, event_code=None):
    """
    Get all Team records visible in alliance mode, optionally filtered by event.
    In alliance mode, this returns ALL teams for the event from any alliance member's data,
    not just teams with scouting data.
    
    Args:
        event_id: Optional event ID to filter by (may be a synthetic 'alliance_CODE' id)
        event_code: Optional event code to filter by
    
    Returns:
        tuple: (teams_list, is_alliance_mode)
    """
    # Support synthetic event ids of the form 'alliance_CODE' used by UI helpers
    if event_id and isinstance(event_id, str) and str(event_id).startswith('alliance_') and not event_code:
        try:
            event_code = str(event_id)[len('alliance_'):]
        except Exception:
            event_code = event_id

    alliance_id = get_active_alliance_id()
    
    if not alliance_id:
        # Not in alliance mode - use normal team isolation
        from app.utils.team_isolation import filter_teams_by_scouting_team
        query = filter_teams_by_scouting_team()
        if event_id and not (isinstance(event_id, str) and str(event_id).startswith('alliance_')):
            query = query.join(Team.events).filter(Event.id == event_id)
        return query.order_by(Team.team_number).all(), False
    
    # Alliance mode - get ALL teams for the event from any alliance member
    from app.utils.team_isolation import get_alliance_team_numbers
    alliance_team_nums = get_alliance_team_numbers() or []
    
    if not alliance_team_nums:
        return [], True
    
    # Determine event code for filtering
    filter_event_code = event_code
    if not filter_event_code and event_id:
        event = Event.query.get(event_id)
        if event:
            filter_event_code = event.code
    
    # Get ALL teams for the event from any alliance member's data
    if filter_event_code:
        # Find ALL events with this code from any alliance member (including game_config_team)
        events = Event.query.filter(
            func.upper(Event.code) == func.upper(filter_event_code),
            Event.scouting_team_number.in_(alliance_team_nums)
        ).all()
        
        if events:
            event_ids = [e.id for e in events]
            
            # Collect team numbers from team-event associations
            team_numbers_set = set()
            for evt in events:
                for team in evt.teams:
                    team_numbers_set.add(team.team_number)
            
            # ALSO get teams directly from alliance member data (in case team-event association is missing)
            # This is the key fix - get teams from ALL alliance members for these events
            direct_teams = Team.query.filter(
                Team.scouting_team_number.in_(alliance_team_nums)
            ).all()
            
            # Filter to only teams that have an event association OR are in the team_numbers_set
            # We accept all teams from alliance members that are associated with these events
            for team in direct_teams:
                # Check if this team is associated with any of the alliance events
                team_event_ids = {e.id for e in team.events}
                if team_event_ids.intersection(event_ids):
                    team_numbers_set.add(team.team_number)
            
            # If we still have teams, get unique Team records
            if team_numbers_set:
                # Get unique Team records from alliance members, deduplicated by team_number
                all_alliance_teams = Team.query.filter(
                    Team.team_number.in_(team_numbers_set),
                    Team.scouting_team_number.in_(alliance_team_nums)
                ).order_by(Team.team_number).all()
                
                # Deduplicate by team_number (keep first occurrence)
                seen = {}
                for t in all_alliance_teams:
                    if t.team_number not in seen:
                        seen[t.team_number] = t
                teams = sorted(seen.values(), key=lambda t: t.team_number)
                
                return teams, True
    
    # Fallback: Get all teams from any alliance member (no event filter)
    teams = Team.query.filter(
        Team.scouting_team_number.in_(alliance_team_nums)
    ).order_by(Team.team_number).all()
    
    # Deduplicate by team_number (prefer lowest scouting_team_number for consistency)
    seen = {}
    for t in teams:
        if t.team_number not in seen:
            seen[t.team_number] = t
    teams = sorted(seen.values(), key=lambda t: t.team_number)
    
    return teams, True


def get_all_matches_for_alliance(event_id=None, event_code=None):
    """
    Get all Match records visible in alliance mode, optionally filtered by event.
    In alliance mode, this returns ALL matches for the event from any alliance member's data,
    not just matches with scouting data.
    
    Args:
        event_id: Optional event ID to filter by (may be a synthetic 'alliance_CODE' id)
        event_code: Optional event code to filter by
    
    Returns:
        tuple: (matches_list, is_alliance_mode)
    """
    # Support synthetic event ids of the form 'alliance_CODE' used by UI helpers
    if event_id and isinstance(event_id, str) and str(event_id).startswith('alliance_') and not event_code:
        try:
            event_code = str(event_id)[len('alliance_'):]
        except Exception:
            event_code = event_id

    alliance_id = get_active_alliance_id()
    
    if not alliance_id:
        # Not in alliance mode - use normal team isolation
        from app.utils.team_isolation import filter_matches_by_scouting_team
        query = filter_matches_by_scouting_team()
        if event_id and not (isinstance(event_id, str) and str(event_id).startswith('alliance_')):
            query = query.filter(Match.event_id == event_id)
        return query.order_by(*Match.schedule_order()).all(), False
    
    # Alliance mode - get ALL matches for the event from any alliance member
    from app.utils.team_isolation import get_alliance_team_numbers
    alliance_team_nums = get_alliance_team_numbers() or []
    
    if not alliance_team_nums:
        return [], True
    
    # Determine event code for filtering
    filter_event_code = event_code
    if not filter_event_code and event_id:
        event = Event.query.get(event_id)
        if event:
            filter_event_code = event.code
    
    # Get ALL matches for the event from any alliance member's data
    if filter_event_code:
        # Find events with this code from any alliance member
        events = Event.query.filter(
            func.upper(Event.code) == func.upper(filter_event_code),
            Event.scouting_team_number.in_(alliance_team_nums)
        ).all()
        
        if events:
            event_ids = [e.id for e in events]
            # Get all matches for these events
            all_matches = Match.query.filter(
                Match.event_id.in_(event_ids)
            ).order_by(*Match.schedule_order()).all()
            
            # Deduplicate by (match_number, match_type) - prefer user's own data
            from flask_login import current_user
            user_scouting_team = getattr(current_user, 'scouting_team_number', None) if current_user and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated else None
            
            seen = {}
            for m in all_matches:
                key = (m.match_number, m.match_type)
                if key not in seen:
                    seen[key] = m
                elif user_scouting_team and m.scouting_team_number == user_scouting_team:
                    # Prefer user's own match record
                    seen[key] = m
            
            matches = sorted(seen.values(), key=lambda m: (
                m.match_type or '', {'ef': 1, 'qf': 2, 'sf': 3, 'f': 4}.get(m.comp_level or '', 0),
                m.set_number or 0, m.match_number or 0))
            
            # Populate missing times for deduped matches using other alliance match records
            try:
                alliance_events = Event.query.filter(Event.scouting_team_number.in_(alliance_team_nums)).all()
                alliance_event_ids = [e.id for e in alliance_events]
                for m in matches:
                    if (getattr(m, 'scheduled_time', None) is None or getattr(m, 'predicted_time', None) is None or getattr(m, 'actual_time', None) is None) and alliance_event_ids:
                        other = Match.query.filter(
                            Match.match_number == m.match_number,
                            Match.match_type == m.match_type,
                            Match.event_id.in_(alliance_event_ids),
                            Match.scouting_team_number.in_(alliance_team_nums)
                        ).order_by(Match.scouting_team_number == getattr(current_user, 'scouting_team_number', None)).first()
                        if other:
                            if getattr(m, 'scheduled_time', None) is None and getattr(other, 'scheduled_time', None) is not None:
                                m.scheduled_time = other.scheduled_time
                            if getattr(m, 'predicted_time', None) is None and getattr(other, 'predicted_time', None) is not None:
                                m.predicted_time = other.predicted_time
                            if getattr(m, 'actual_time', None) is None and getattr(other, 'actual_time', None) is not None:
                                m.actual_time = other.actual_time
            except Exception:
                pass

            return matches, True
    
    # Fallback: Get all matches from any alliance member
    matches = Match.query.filter(
        Match.scouting_team_number.in_(alliance_team_nums)
    ).order_by(*Match.schedule_order()).all()
    
    # Deduplicate by (match_number, match_type, event_code)
    seen = {}
    for m in matches:
        evt = Event.query.get(m.event_id)
        evt_code = evt.code.upper() if evt and evt.code else ''
        key = (m.match_number, m.match_type, evt_code)
        if key not in seen:
            seen[key] = m
    
    matches = sorted(seen.values(), key=lambda m: (
        m.match_type or '', {'ef': 1, 'qf': 2, 'sf': 3, 'f': 4}.get(m.comp_level or '', 0),
        m.set_number or 0, m.match_number or 0))
    
    # Ensure match times are populated where possible. If the deduped match has no
    # scheduled/predicted/actual times, look for any other match in the alliance
    # with the same match_type/number and take its timestamps to display in the UI.
    try:
        # Collect event ids for alliance teams to constrain lookup
        alliance_events = Event.query.filter(Event.scouting_team_number.in_(alliance_team_nums)).all()
        alliance_event_ids = [e.id for e in alliance_events]
        for m in matches:
            if (getattr(m, 'scheduled_time', None) is None or getattr(m, 'predicted_time', None) is None or getattr(m, 'actual_time', None) is None) and alliance_event_ids:
                other = Match.query.filter(
                    Match.match_number == m.match_number,
                    Match.match_type == m.match_type,
                    Match.event_id.in_(alliance_event_ids),
                    Match.scouting_team_number.in_(alliance_team_nums)
                ).order_by(Match.scouting_team_number == getattr(current_user, 'scouting_team_number', None)).first()
                if other:
                    # Only copy values that are missing on the deduped match
                    if getattr(m, 'scheduled_time', None) is None and getattr(other, 'scheduled_time', None) is not None:
                        m.scheduled_time = other.scheduled_time
                    if getattr(m, 'predicted_time', None) is None and getattr(other, 'predicted_time', None) is not None:
                        m.predicted_time = other.predicted_time
                    if getattr(m, 'actual_time', None) is None and getattr(other, 'actual_time', None) is not None:
                        m.actual_time = other.actual_time
    except Exception:
        # If anything goes wrong, just return matches as-is; we don't want a UI error
        pass

    return matches, True


def get_events_with_scouting_data():
    """
    Get all events that have scouting data, using alliance data if in alliance mode.
    In alliance mode, returns unique event_codes from alliance shared data
    and finds corresponding Event records visible to the current user.
    
    Returns:
        tuple: (events_list, is_alliance_mode, alliance_id)
    """
    alliance_id = get_active_alliance_id()
    
    if alliance_id:
        # Alliance mode - get unique event_codes from shared data
        # First get the event_codes from the alliance shared scouting data
        event_codes_query = db.session.query(func.upper(Event.code)).select_from(
            AllianceSharedScoutingData
        ).join(
            Match, AllianceSharedScoutingData.match_id == Match.id
        ).join(
            Event, Match.event_id == Event.id
        ).filter(
            AllianceSharedScoutingData.alliance_id == alliance_id,
            AllianceSharedScoutingData.is_active == True
        ).distinct()
        
        event_codes = [row[0] for row in event_codes_query.all()]
        
        if not event_codes:
            return [], True, alliance_id
        
        # Get events visible to the current user that match these codes
        from app.utils.team_isolation import filter_events_by_scouting_team
        events = filter_events_by_scouting_team().filter(
            func.upper(Event.code).in_(event_codes)
        ).order_by(Event.name).all()
        
        # If not all events found, try to get them from any alliance member
        found_codes = {e.code.upper() for e in events if e.code}
        missing_codes = set(event_codes) - found_codes
        if missing_codes:
            from app.utils.team_isolation import get_alliance_team_numbers
            alliance_team_nums = get_alliance_team_numbers() or []
            additional_events = Event.query.filter(
                func.upper(Event.code).in_(missing_codes),
                Event.scouting_team_number.in_(alliance_team_nums)
            ).all()
            events.extend(additional_events)
            # Deduplicate by event_code (case-insensitive)
            seen_codes = set()
            unique_events = []
            for e in events:
                code_upper = (e.code or '').upper()
                if code_upper not in seen_codes:
                    seen_codes.add(code_upper)
                    unique_events.append(e)
            events = sorted(unique_events, key=lambda e: (e.name or ''))
        
        return events, True, alliance_id
    else:
        # Normal mode
        current_team = get_current_scouting_team_number()
        
        from app.utils.team_isolation import get_alliance_team_numbers
        alliance_team_numbers = get_alliance_team_numbers() or []
        
        team_filter_numbers = [current_team] if current_team else []
        if alliance_team_numbers:
            team_filter_numbers.extend(alliance_team_numbers)
        team_filter_numbers = list(set(team_filter_numbers))
        
        query = Event.query.join(Match).join(ScoutingData)
        if team_filter_numbers:
            query = query.filter(ScoutingData.scouting_team_number.in_(team_filter_numbers))
        
        events = query.distinct().order_by(Event.name).all()
        return events, False, None


def normalize_scouting_entry(entry, is_alliance_mode=False):
    """
    Normalize a scouting entry to a common dictionary format.
    Works with both ScoutingData and AllianceSharedScoutingData.
    
    Returns a dict with consistent keys for templates to use.
    """
    if is_alliance_mode and isinstance(entry, AllianceSharedScoutingData):
        return {
            'id': entry.id,
            'shared_id': entry.id,  # For alliance mode delete
            'original_id': entry.original_scouting_data_id,
            'match_id': entry.match_id,
            'team_id': entry.team_id,
            'match': entry.match,
            'team': entry.team,
            'scout_name': entry.scout_name,
            'scout_id': entry.scout_id,
            'timestamp': entry.timestamp,
            'alliance': entry.alliance,
            'data': entry.data,
            'scouting_team_number': entry.source_scouting_team_number,
            'source_team': entry.source_scouting_team_number,
            'is_alliance_data': True
        }
    else:
        return {
            'id': entry.id,
            'shared_id': None,
            'original_id': entry.id,
            'match_id': entry.match_id,
            'team_id': entry.team_id,
            'match': entry.match,
            'team': entry.team,
            'scout_name': entry.scout_name,
            'scout_id': getattr(entry, 'scout_id', None),
            'timestamp': entry.timestamp,
            'alliance': entry.alliance,
            'data': entry.data,
            'scouting_team_number': entry.scouting_team_number,
            'source_team': entry.scouting_team_number,
            'is_alliance_data': False
        }


def normalize_pit_entry(entry, is_alliance_mode=False):
    """
    Normalize a pit scouting entry to a common dictionary format.
    Works with both PitScoutingData and AllianceSharedPitData.
    """
    if is_alliance_mode and isinstance(entry, AllianceSharedPitData):
        return {
            'id': entry.id,
            'shared_id': entry.id,
            'original_id': entry.original_pit_data_id,
            'team_id': entry.team_id,
            'team': entry.team,
            'scout_name': entry.scout_name,
            'timestamp': entry.timestamp,
            'data': entry.data,
            'scouting_team_number': entry.source_scouting_team_number,
            'source_team': entry.source_scouting_team_number,
            'is_alliance_data': True
        }
    else:
        return {
            'id': entry.id,
            'shared_id': None,
            'original_id': entry.id,
            'team_id': entry.team_id,
            'team': entry.team,
            'scout_name': entry.scout_name,
            'timestamp': entry.timestamp,
            'data': entry.data,
            'scouting_team_number': entry.scouting_team_number,
            'source_team': entry.scouting_team_number,
            'is_alliance_data': False
        }


def get_scouting_data_for_team(team_id, event_id=None):
    """
    Get all scouting data for a specific team, using alliance data if in alliance mode.
    This is useful for metrics/analytics calculations.
    
    Args:
        team_id: The Team.id to get scouting data for
        event_id: Optional event ID to filter by (NOTE: in alliance mode, filters by event CODE not ID)
    
    Returns:
        tuple: (scouting_data_list, is_alliance_mode)
    """
    alliance_id = get_active_alliance_id()
    
    if alliance_id:
        # Alliance mode - query from shared tables
        # IMPORTANT: In alliance mode, we need to query by team_number, not team_id,
        # because team_id references the source team's Team record which may differ
        # from the current user's Team record for the same team number.
        team = Team.query.get(team_id)
        if not team:
            return [], True
        
        team_number = team.team_number
        
        # Join with Team to filter by team_number
        query = AllianceSharedScoutingData.query.join(
            Team, AllianceSharedScoutingData.team_id == Team.id
        ).filter(
            AllianceSharedScoutingData.alliance_id == alliance_id,
            Team.team_number == team_number,
            AllianceSharedScoutingData.is_active == True
        )
        
        if event_id:
            # In alliance mode, also filter by event CODE not ID, since event IDs differ across teams
            event = Event.query.get(event_id)
            if event:
                query = query.join(
                    Match, AllianceSharedScoutingData.match_id == Match.id
                ).join(
                    Event, Match.event_id == Event.id
                ).filter(func.upper(Event.code) == event.code.upper())
            else:
                # Event not found, return empty
                return [], True
        
        return query.all(), True
    else:
        # Normal mode - query from team's data
        current_team = get_current_scouting_team_number()
        
        from app.utils.team_isolation import get_alliance_team_numbers
        alliance_team_numbers = get_alliance_team_numbers() or []
        
        team_filter_numbers = [current_team] if current_team else []
        if alliance_team_numbers:
            team_filter_numbers.extend(alliance_team_numbers)
        team_filter_numbers = list(set(team_filter_numbers))
        
        query = ScoutingData.query.filter_by(team_id=team_id)
        if team_filter_numbers:
            query = query.filter(ScoutingData.scouting_team_number.in_(team_filter_numbers))
        
        if event_id:
            query = query.join(Match).filter(Match.event_id == event_id)
        
        return query.all(), False


def get_scouting_data_for_teams(team_ids, event_id=None):
    """
    Get all scouting data for multiple teams, using alliance data if in alliance mode.
    
    Args:
        team_ids: List of Team.id values to get scouting data for
        event_id: Optional event ID to filter by
    
    Returns:
        tuple: (scouting_data_list, is_alliance_mode)
    """
    if not team_ids:
        return [], False
    
    alliance_id = get_active_alliance_id()
    
    if alliance_id:
        # Alliance mode - query from shared tables by team_number
        # First get the team_numbers for the requested team_ids
        teams = Team.query.filter(Team.id.in_(team_ids)).all()
        team_numbers = [t.team_number for t in teams]
        
        if not team_numbers:
            return [], True
        
        # Query alliance data by team_number, not team_id
        # Different alliance members have different team_id for the same team_number
        query = AllianceSharedScoutingData.query.join(
            Team, AllianceSharedScoutingData.team_id == Team.id
        ).filter(
            AllianceSharedScoutingData.alliance_id == alliance_id,
            Team.team_number.in_(team_numbers),
            AllianceSharedScoutingData.is_active == True
        )
        
        if event_id:
            # Filter by event code instead of event_id
            event = Event.query.get(event_id)
            if event:
                event_code = event.code
                query = query.join(
                    Match, AllianceSharedScoutingData.match_id == Match.id
                ).join(
                    Event, Match.event_id == Event.id
                ).filter(func.upper(Event.code) == func.upper(event_code))
            else:
                return [], True
        
        return query.all(), True
    else:
        # Normal mode - query from team's data
        current_team = get_current_scouting_team_number()
        
        from app.utils.team_isolation import get_alliance_team_numbers
        alliance_team_numbers = get_alliance_team_numbers() or []
        
        team_filter_numbers = [current_team] if current_team else []
        if alliance_team_numbers:
            team_filter_numbers.extend(alliance_team_numbers)
        team_filter_numbers = list(set(team_filter_numbers))
        
        query = ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids))
        if team_filter_numbers:
            query = query.filter(ScoutingData.scouting_team_number.in_(team_filter_numbers))
        
        if event_id:
            query = query.join(Match).filter(Match.event_id == event_id)
        
        return query.all(), False


def get_scouting_data_query_for_team(scouting_team_number, event_id=None, team_id=None, match_id=None):
    """
    Get scouting data query for a specific scouting team, using alliance data if alliance mode is active.
    
    This is designed for API endpoints that use token auth instead of current_user.
    
    Args:
        scouting_team_number: The team number requesting data
        event_id: Optional event ID to filter by
        team_id: Optional team ID (the team being scouted) to filter by
        match_id: Optional match ID to filter by
    
    Returns:
        tuple: (query, is_alliance_mode, alliance_id) - query is a SQLAlchemy query object
    """
    alliance_id = get_active_alliance_id_for_team(scouting_team_number)
    
    if alliance_id:
        # Alliance mode - query from shared tables by team_number, not team_id
        query = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        )
        
        if team_id:
            # Get team_number for the requested team_id
            team = Team.query.get(team_id)
            if team:
                # Join with Team to filter by team_number
                query = query.join(
                    Team, AllianceSharedScoutingData.team_id == Team.id
                ).filter(Team.team_number == team.team_number)
            else:
                query = query.filter(AllianceSharedScoutingData.team_id == team_id)
        
        if match_id:
            # Get match_number for the requested match_id
            match = Match.query.get(match_id)
            if match:
                # Filter by match_number and event_code instead of match_id
                query = query.join(
                    Match, AllianceSharedScoutingData.match_id == Match.id
                ).join(
                    Event, Match.event_id == Event.id
                ).filter(
                    Match.match_number == match.match_number,
                    func.upper(Event.code) == func.upper(match.event.code)
                )
            else:
                query = query.filter(AllianceSharedScoutingData.match_id == match_id)
        
        if event_id:
            # Filter by event code instead of event_id
            event = Event.query.get(event_id)
            if event:
                # Join with Match and Event to filter by event_code
                if match_id is None:  # Only join if not already joined
                    query = query.join(
                        Match, AllianceSharedScoutingData.match_id == Match.id
                    ).join(
                        Event, Match.event_id == Event.id
                    )
                query = query.filter(func.upper(Event.code) == func.upper(event.code))
        
        return query, True, alliance_id
    else:
        # Normal mode - query from team's data
        query = ScoutingData.query.filter_by(scouting_team_number=scouting_team_number)
        
        if team_id:
            query = query.filter(ScoutingData.team_id == team_id)
        
        if match_id:
            query = query.filter(ScoutingData.match_id == match_id)
        
        if event_id:
            query = query.join(Match).filter(Match.event_id == event_id)
        
        return query, False, None


def get_pit_data_query_for_team(scouting_team_number, team_id=None):
    """
    Get pit scouting data query for a specific scouting team, using alliance data if alliance mode is active.
    
    This is designed for API endpoints that use token auth instead of current_user.
    
    Args:
        scouting_team_number: The team number requesting data
        team_id: Optional team ID (the team being scouted) to filter by
    
    Returns:
        tuple: (query, is_alliance_mode, alliance_id) - query is a SQLAlchemy query object
    """
    alliance_id = get_active_alliance_id_for_team(scouting_team_number)
    
    if alliance_id:
        # Alliance mode - query from shared tables by team_number, not team_id
        query = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        )
        
        if team_id:
            # Get team_number for the requested team_id
            team = Team.query.get(team_id)
            if team:
                # Join with Team to filter by team_number
                query = query.join(
                    Team, AllianceSharedPitData.team_id == Team.id
                ).filter(Team.team_number == team.team_number)
            else:
                query = query.filter(AllianceSharedPitData.team_id == team_id)
        
        return query, True, alliance_id
    else:
        # Normal mode - query from team's data
        query = PitScoutingData.query.filter_by(scouting_team_number=scouting_team_number)
        
        if team_id:
            query = query.filter(PitScoutingData.team_id == team_id)
        
        return query, False, None


def copy_alliance_data_to_team(alliance_id, target_team_number):
    """
    Copy all alliance data (not just the team's own data) to the team's local storage.
    This allows a team to keep a local copy of all alliance data when disabling alliance mode.
    
    Args:
        alliance_id: The alliance to copy data from
        target_team_number: The team number to copy data to
    
    Returns:
        dict: Stats about what was copied
    """
    import uuid
    
    stats = {
        'scouting_copied': 0,
        'scouting_skipped': 0,
        'pit_copied': 0,
        'pit_skipped': 0,
        'errors': []
    }
    
    try:
        # Get all shared scouting data from the alliance
        shared_scouting_entries = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        ).all()
        
        for entry in shared_scouting_entries:
            try:
                # Check if this data already exists in the team's private ScoutingData
                existing_private = ScoutingData.query.filter_by(
                    match_id=entry.match_id,
                    team_id=entry.team_id,
                    alliance=entry.alliance,
                    scouting_team_number=target_team_number
                ).first()
                
                if not existing_private:
                    # Create a private copy of the data
                    # Prefix scout_name to indicate it's from alliance
                    scout_name = entry.scout_name or ''
                    if entry.source_scouting_team_number != target_team_number:
                        scout_name = f"[Alliance-{entry.source_scouting_team_number}] {scout_name}"
                    
                    private_copy = ScoutingData(
                        match_id=entry.match_id,
                        team_id=entry.team_id,
                        scouting_team_number=target_team_number,
                        scout_name=scout_name,
                        scout_id=entry.scout_id,
                        scouting_station=entry.scouting_station,
                        alliance=entry.alliance,
                        data_json=entry.data_json,
                        timestamp=entry.timestamp
                    )
                    db.session.add(private_copy)
                    stats['scouting_copied'] += 1
                else:
                    stats['scouting_skipped'] += 1
            except Exception as e:
                stats['errors'].append(f"Scouting entry {entry.id}: {str(e)}")
        
        # Get all shared pit data from the alliance
        shared_pit_entries = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        ).all()
        
        for entry in shared_pit_entries:
            try:
                # Check if this data already exists in the team's private PitScoutingData
                existing_private = PitScoutingData.query.filter_by(
                    team_id=entry.team_id,
                    scouting_team_number=target_team_number
                ).first()
                
                if not existing_private:
                    # Create a private copy of the data
                    scout_name = entry.scout_name or ''
                    if entry.source_scouting_team_number != target_team_number:
                        scout_name = f"[Alliance-{entry.source_scouting_team_number}] {scout_name}"
                    
                    private_copy = PitScoutingData(
                        team_id=entry.team_id,
                        event_id=entry.event_id,
                        scouting_team_number=target_team_number,
                        scout_name=scout_name,
                        scout_id=entry.scout_id,
                        data_json=entry.data_json,
                        timestamp=entry.timestamp,
                        local_id=str(uuid.uuid4())
                    )
                    db.session.add(private_copy)
                    stats['pit_copied'] += 1
                else:
                    stats['pit_skipped'] += 1
            except Exception as e:
                stats['errors'].append(f"Pit entry {entry.id}: {str(e)}")
        
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        stats['errors'].append(f"General error: {str(e)}")
    
    return stats


def copy_my_team_alliance_data(alliance_id, team_number):
    """
    Copy only the current team's data from the alliance shared tables back to their local storage.
    This allows a team to retrieve only data they contributed when disabling alliance mode,
    without keeping data from other alliance members.
    
    Args:
        alliance_id: The alliance to copy data from
        team_number: The team number whose data to copy (source_scouting_team_number)
    
    Returns:
        dict: Stats about what was copied
    """
    import uuid
    
    stats = {
        'scouting_copied': 0,
        'scouting_skipped': 0,
        'pit_copied': 0,
        'pit_skipped': 0,
        'errors': []
    }
    
    try:
        # Get only this team's shared scouting data from the alliance
        shared_scouting_entries = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            source_scouting_team_number=team_number,  # Only this team's data
            is_active=True
        ).all()
        
        for entry in shared_scouting_entries:
            try:
                # Check if this data already exists in the team's private ScoutingData
                existing_private = ScoutingData.query.filter_by(
                    match_id=entry.match_id,
                    team_id=entry.team_id,
                    alliance=entry.alliance,
                    scouting_team_number=team_number
                ).first()
                
                if not existing_private:
                    # Create a private copy of the data (no prefix since it's our own data)
                    private_copy = ScoutingData(
                        match_id=entry.match_id,
                        team_id=entry.team_id,
                        scouting_team_number=team_number,
                        scout_name=entry.scout_name,
                        scout_id=entry.scout_id,
                        scouting_station=entry.scouting_station,
                        alliance=entry.alliance,
                        data_json=entry.data_json,
                        timestamp=entry.timestamp
                    )
                    db.session.add(private_copy)
                    stats['scouting_copied'] += 1
                else:
                    stats['scouting_skipped'] += 1
            except Exception as e:
                stats['errors'].append(f"Scouting entry {entry.id}: {str(e)}")
        
        # Get only this team's shared pit data from the alliance
        shared_pit_entries = AllianceSharedPitData.query.filter_by(
            alliance_id=alliance_id,
            source_scouting_team_number=team_number,  # Only this team's data
            is_active=True
        ).all()
        
        for entry in shared_pit_entries:
            try:
                # Check if this data already exists in the team's private PitScoutingData
                existing_private = PitScoutingData.query.filter_by(
                    team_id=entry.team_id,
                    scouting_team_number=team_number
                ).first()
                
                if not existing_private:
                    # Create a private copy of the data (no prefix since it's our own data)
                    private_copy = PitScoutingData(
                        team_id=entry.team_id,
                        event_id=entry.event_id,
                        scouting_team_number=team_number,
                        scout_name=entry.scout_name,
                        scout_id=entry.scout_id,
                        data_json=entry.data_json,
                        timestamp=entry.timestamp,
                        local_id=str(uuid.uuid4())
                    )
                    db.session.add(private_copy)
                    stats['pit_copied'] += 1
                else:
                    stats['pit_skipped'] += 1
            except Exception as e:
                stats['errors'].append(f"Pit entry {entry.id}: {str(e)}")
        
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        stats['errors'].append(f"General error: {str(e)}")
    
    return stats
