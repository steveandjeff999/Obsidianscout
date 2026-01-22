from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
from app.models import (
    Team, Match, Event, ScoutingData, StrategyDrawing, PitScoutingData,
    AllianceSelection, DoNotPickEntry, AvoidEntry,
    TeamListEntry, StrategyShare, SharedGraph, SharedTeamRanks, team_event,
    AllianceSharedScoutingData, AllianceSharedPitData
)
from app import db
import pandas as pd
import json
import os
from werkzeug.utils import secure_filename
import qrcode
from io import BytesIO
import base64
import zipfile
import tempfile
from datetime import datetime, timezone, date
from sqlalchemy.exc import IntegrityError
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_effective_game_config
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, filter_scouting_data_by_scouting_team, filter_pit_scouting_data_by_scouting_team,
    get_event_by_code, get_all_teams_at_event
)
from app.utils.team_isolation import get_combined_dropdown_events
from app.utils.alliance_data import get_active_alliance_id, get_all_teams_for_alliance, get_all_matches_for_alliance
from app.utils.score_utils import match_sort_key
from flask import jsonify
from app.utils.api_auth import team_data_access_required
from app.utils.alliance_data import get_active_alliance_id, get_all_scouting_data, get_all_pit_data
from uuid import uuid4
from app import socketio

# Simple in-memory job tracking for background imports
import_jobs = {}

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }


def merge_duplicate_events(scouting_team_number=None):
    """Merge duplicate events that have the same code, name, or year.
    
    This function finds and merges duplicate events by:
    1. Finding events with the same code (normalized) - ONLY within the same scouting team
    2. Keeping the most complete event (with most data filled in)
    3. Moving all teams and matches to the kept event
    4. Updating scouting_team_number on kept event to match current team
    5. Deleting the duplicate events
    
    Args:
        scouting_team_number: Optional scouting team number to set on merged event
    """
    from collections import defaultdict
    from sqlalchemy import func
    
    try:
        # Query events ONLY for the current scouting team to avoid cross-team contamination
        if scouting_team_number is not None:
            all_events = Event.query.filter_by(scouting_team_number=scouting_team_number).all()
        else:
            all_events = Event.query.filter_by(scouting_team_number=None).all()
        
        # Group events by normalized code
        code_groups = defaultdict(list)
        for evt in all_events:
            if evt.code:
                normalized_code = evt.code.strip().upper()
                code_groups[normalized_code].append(evt)
        
        merged_count = 0
        for code, events in code_groups.items():
            if len(events) <= 1:
                continue
            
            # Sort by completeness: prefer events with more filled fields
            def event_score(e):
                score = 0
                if e.name: score += 10
                if e.location: score += 5
                if getattr(e, 'start_date', None): score += 5
                if getattr(e, 'end_date', None): score += 3
                if getattr(e, 'timezone', None): score += 2
                if e.year: score += 1
                return score
            
            events.sort(key=event_score, reverse=True)
            keep_event = events[0]
            duplicate_events = events[1:]
            
            # Set scouting_team_number if provided (prioritize the specified team)
            if scouting_team_number is not None:
                keep_event.scouting_team_number = scouting_team_number
            
            # Merge data from duplicates into the kept event
            for dup in duplicate_events:
                # Update fields if they're missing in keep_event
                if not keep_event.name and dup.name:
                    keep_event.name = dup.name
                if not keep_event.location and dup.location:
                    keep_event.location = dup.location
                if not getattr(keep_event, 'start_date', None) and getattr(dup, 'start_date', None):
                    keep_event.start_date = dup.start_date
                if not getattr(keep_event, 'end_date', None) and getattr(dup, 'end_date', None):
                    keep_event.end_date = dup.end_date
                if not getattr(keep_event, 'timezone', None) and getattr(dup, 'timezone', None):
                    keep_event.timezone = dup.timezone
                if not keep_event.year and dup.year:
                    keep_event.year = dup.year
                
                # Move all teams from duplicate to kept event
                for team in dup.teams:
                    if team not in keep_event.teams:
                        keep_event.teams.append(team)
                
                # Move all matches from duplicate to kept event
                Match.query.filter_by(event_id=dup.id).update({Match.event_id: keep_event.id})
                
                # Delete the duplicate event
                db.session.delete(dup)
                merged_count += 1
            
            db.session.add(keep_event)
        
        if merged_count > 0:
            db.session.commit()
            print(f"  Merged {merged_count} duplicate events")
        
        return merged_count
        
    except Exception as e:
        db.session.rollback()
        print(f"  Error merging duplicate events: {e}")
        return 0


def get_or_create_event(name=None, code=None, year=None, location=None, start_date=None, end_date=None, scouting_team_number=None):
    """Find or create an Event with normalization and race-condition handling.

    - Normalizes `code` to uppercase and stripped form before lookup/creation.
    - Prefers lookup by `code`+`scouting_team_number` when `code` is provided.
    - Falls back to `name`+`year`+`scouting_team_number` if `code` is not available.
    - Handles `IntegrityError` during creation by rolling back and re-querying the existing record.
    Returns an Event instance (persisted/flush may or may not have been called).
    """
    try:
        code_norm = code.strip().upper() if code else None
    except Exception:
        code_norm = code

    # Try lookup by code + scouting_team_number first (most specific)
    if code_norm:
        evt = Event.query.filter_by(code=code_norm, scouting_team_number=scouting_team_number).first()
        if evt:
            # Update basic fields if missing
            try:
                if not evt.name and name:
                    evt.name = name
                if location and not evt.location:
                    evt.location = location
                if start_date and not getattr(evt, 'start_date', None):
                    evt.start_date = start_date
                if end_date and not getattr(evt, 'end_date', None):
                    evt.end_date = end_date
                if year and not evt.year:
                    evt.year = year
                db.session.add(evt)
            except Exception:
                pass
            return evt

    # Fallback: try lookup by name+year+scouting_team_number
    if name and year is not None:
        evt = Event.query.filter_by(name=name, year=year, scouting_team_number=scouting_team_number).first()
        if evt:
            try:
                if code_norm and not evt.code:
                    evt.code = code_norm
                if location and not evt.location:
                    evt.location = location
                if start_date and not getattr(evt, 'start_date', None):
                    evt.start_date = start_date
                if end_date and not getattr(evt, 'end_date', None):
                    evt.end_date = end_date
                db.session.add(evt)
            except Exception:
                pass
            return evt

    # Ensure we have a valid year (Event.year is NOT NULL) - infer from start_date or fallback to current year
    final_year = year
    try:
        if final_year is None:
            if start_date and hasattr(start_date, 'year'):
                final_year = start_date.year
            else:
                from datetime import datetime as _dt
                final_year = _dt.now(timezone.utc).year
    except Exception:
        from datetime import datetime as _dt
        final_year = _dt.now(timezone.utc).year

    # Create new event, with normalized code if available
    new_ev = Event(
        name=name,
        code=code_norm if code_norm else code,
        location=location,
        start_date=start_date,
        end_date=end_date,
        year=final_year,
        scouting_team_number=scouting_team_number
    )
    try:
        db.session.add(new_ev)
        db.session.flush()
        return new_ev
    except IntegrityError:
        # Race: someone else created it concurrently. Rollback and re-query.
        db.session.rollback()
        if code_norm:
            evt = Event.query.filter_by(code=code_norm, scouting_team_number=scouting_team_number).first()
            if evt:
                return evt
        if name and year is not None:
            evt = Event.query.filter_by(name=name, year=year, scouting_team_number=scouting_team_number).first()
            if evt:
                return evt
        # If still no event, re-raise to let caller decide
        raise

bp = Blueprint('data', __name__, url_prefix='/data')


def _sanitize_date(val):
    """Convert incoming values to a Python date or None.

    Accepts ISO strings, datetime/date objects, pandas Timestamp, or numeric NaN.
    Returns a datetime.date or None.
    """
    try:
        if val is None:
            return None
        # pandas / numpy NA
        try:
            if pd.isna(val):
                return None
        except Exception:
            pass

        # If it's already a date (but not datetime), return
        if isinstance(val, date) and not isinstance(val, datetime):
            return val

        # If it's a datetime, return date portion
        if isinstance(val, datetime):
            return val.date()

        # Strings: try ISO parse
        if isinstance(val, str):
            s = val.strip()
            if s == '':
                return None
            try:
                dt = datetime.fromisoformat(s)
                return dt.date()
            except Exception:
                # fallback: attempt to parse just the date portion yyyy-mm-dd
                try:
                    return datetime.strptime(s[:10], '%Y-%m-%d').date()
                except Exception:
                    return None

        # pandas Timestamp-like objects have isoformat or date methods
        if hasattr(val, 'to_pydatetime'):
            try:
                return val.to_pydatetime().date()
            except Exception:
                pass

        # As a last resort, try converting via datetime
        try:
            return datetime.fromtimestamp(float(val)).date()
        except Exception:
            return None
    except Exception:
        return None


def _process_portable_data(export_data):
    """Shared logic to import portable-export-style dict into DB.

    export_data is a dict with keys like 'events','teams','matches','scouting_data', etc.
    This function largely mirrors the logic in import_portable but accepts data directly
    so it can be reused for Excel imports that contain the same sheets.
    Returns a (success, report_message) tuple.
    """
    # Duplicate the mapping/report logic from import_portable
    mapping = {
        'events': {},
        'teams': {},
        'matches': {},
        'strategy_drawings': {},
        'scouting_data': {},
        'pit_scouting': {}
    }
    report = {'created': {}, 'updated': {}, 'skipped': {}, 'errors': []}

    try:
        # Build lookup of exported events (by exported id) for later code-based resolution
        exported_events_by_id = {ev.get('id'): ev for ev in export_data.get('events', []) if ev.get('id') is not None}

        # EVENTS
        for ev in export_data.get('events', []):
            existing = None
            # Normalize code for lookup
            code = ev.get('code') if ev.get('code') else None
            if code:
                existing = Event.query.filter_by(code=code, year=ev.get('year')).first()
            if not existing:
                existing = Event.query.filter_by(name=ev.get('name'), year=ev.get('year')).first()

            if existing:
                existing.location = ev.get('location')
                existing.start_date = _sanitize_date(ev.get('start_date'))
                existing.end_date = _sanitize_date(ev.get('end_date'))
                db.session.add(existing)
                mapping['events'][ev['id']] = existing.id
                # Also map by code for resilience across servers
                if code:
                    mapping['events'][code.strip().upper()] = existing.id
                report['updated'].setdefault('events', 0)
                report['updated']['events'] = report['updated']['events'] + 1 if report['updated'].get('events') else 1
            else:
                new_ev = get_or_create_event(
                    name=ev.get('name'),
                    code=ev.get('code'),
                    year=ev.get('year'),
                    location=ev.get('location'),
                    start_date=_sanitize_date(ev.get('start_date')),
                    end_date=_sanitize_date(ev.get('end_date')),
                    scouting_team_number=ev.get('scouting_team_number')
                )
                mapping['events'][ev['id']] = new_ev.id
                if code:
                    mapping['events'][code.strip().upper()] = new_ev.id
                report['created'].setdefault('events', 0)
                report['created']['events'] = report['created']['events'] + 1 if report['created'].get('events') else 1

        db.session.commit()

        # Helper: resolve an exported event id (or create/fallback using event code from exported events)
        def _resolve_event(export_event_id, fallback_scouting_team=None):
            # Direct mapping present?
            if export_event_id in mapping['events']:
                return mapping['events'][export_event_id]

            # If export_event_id is a code already, return mapping by code
            if isinstance(export_event_id, str):
                code_key = export_event_id.strip().upper()
                if code_key in mapping['events']:
                    return mapping['events'][code_key]

            # Look up the original exported event record for extra metadata
            ev = exported_events_by_id.get(export_event_id)
            if ev:
                code = ev.get('code')
                year = ev.get('year')
                stn = ev.get('scouting_team_number') if ev.get('scouting_team_number') else fallback_scouting_team

                # Try to find an existing local event by code+year or code only
                if code:
                    try:
                        code_norm = code.strip().upper()
                    except Exception:
                        code_norm = code

                    existing = Event.query.filter_by(code=code_norm, year=year, scouting_team_number=stn).first()
                    if not existing:
                        existing = Event.query.filter_by(code=code_norm, year=year).first()
                    if existing:
                        mapping['events'][export_event_id] = existing.id
                        mapping['events'][code_norm] = existing.id
                        return existing.id

                # If no existing event, create one using exported metadata
                try:
                    created = get_or_create_event(
                        name=ev.get('name'),
                        code=ev.get('code'),
                        year=ev.get('year'),
                        location=ev.get('location'),
                        start_date=_sanitize_date(ev.get('start_date')),
                        end_date=_sanitize_date(ev.get('end_date')),
                        scouting_team_number=stn
                    )
                    mapping['events'][export_event_id] = created.id
                    if code:
                        mapping['events'][code.strip().upper()] = created.id
                    report['created']['events'] = report['created'].get('events', 0) + 1 if report.get('created') else 1
                    db.session.commit()
                    return created.id
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    # Fallback: create a minimal Event record
                    try:
                        ev_obj = Event(name='Imported (Missing Event) - Portable Import', code=ev.get('code'), year=ev.get('year') or datetime.now(timezone.utc).year)
                        ev_obj.scouting_team_number = stn
                        db.session.add(ev_obj)
                        db.session.flush()
                        mapping['events'][export_event_id] = ev_obj.id
                        if code:
                            mapping['events'][code.strip().upper()] = ev_obj.id
                        report['created']['events'] = report['created'].get('events', 0) + 1 if report.get('created') else 1
                        db.session.commit()
                        return ev_obj.id
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        return None

            # No exported event record available; fallback to global placeholder
            if mapping['events'].get(None):
                return mapping['events'].get(None)

            # Create a generic placeholder event
            try:
                placeholder = get_or_create_event(
                    name='Imported (Missing Event) - Portable Import',
                    code=f'IMPORT-NULL-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}',
                    year=datetime.now(timezone.utc).year
                )
                mapping['events'][None] = placeholder.id
                report['created']['events'] = report['created'].get('events', 0) + 1 if report.get('created') else 1
                db.session.commit()
                return placeholder.id
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                try:
                    ev_obj = Event(name='Imported (Missing Event) - Portable Import', code=None, year=datetime.now(timezone.utc).year)
                    db.session.add(ev_obj)
                    db.session.flush()
                    mapping['events'][None] = ev_obj.id
                    report['created']['events'] = report['created'].get('events', 0) + 1 if report.get('created') else 1
                    db.session.commit()
                    return ev_obj.id
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    return None

        # TEAMS
        for t in export_data.get('teams', []):
            existing = Team.query.filter_by(team_number=t.get('team_number')).first()
            if existing:
                existing.team_name = t.get('team_name')
                existing.location = t.get('location')
                existing.scouting_team_number = t.get('scouting_team_number')
                db.session.add(existing)
                mapping['teams'][t['id']] = existing.id
                report['updated']['teams'] = report['updated'].get('teams', 0) + 1 if report['updated'].get('teams') else 1
            else:
                new_t = Team(
                    team_number=t.get('team_number'),
                    team_name=t.get('team_name'),
                    location=t.get('location'),
                    scouting_team_number=t.get('scouting_team_number')
                )
                db.session.add(new_t)
                db.session.flush()
                mapping['teams'][t['id']] = new_t.id
                report['created']['teams'] = report['created'].get('teams', 0) + 1 if report['created'].get('teams') else 1

        db.session.commit()

        # Re-create team_event associations if provided
        for assoc in export_data.get('team_event', []):
            old_t = assoc.get('team_id')
            old_e = assoc.get('event_id')
            new_t = mapping['teams'].get(old_t)
            new_e = mapping['events'].get(old_e)
            if not new_e and old_e is not None:
                new_e = _resolve_event(old_e)
            if new_t and new_e:
                try:
                    db.session.execute(team_event.insert().values(team_id=new_t, event_id=new_e))
                except Exception:
                    pass
        db.session.commit()

        # Ensure we have a placeholder Event for any MATCH entries that reference a missing event
        # so inserting matches doesn't violate the NOT NULL constraint on Match.event_id.
        if export_data.get('matches'):
            need_placeholder = False
            for m in export_data.get('matches', []):
                # If the exported match references an event id that isn't in our mapping,
                # we need a placeholder event to assign it to.
                if m.get('event_id') is None or m.get('event_id') not in mapping['events']:
                    need_placeholder = True
                    break
            if need_placeholder:
                try:
                    placeholder = get_or_create_event(
                        name='Imported (Missing Event) - Portable Import',
                        code=f'IMPORT-NULL-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',
                        year=datetime.now(timezone.utc).year
                    )
                    mapping['events'][None] = placeholder.id
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    # Fallback: attempt to create a minimal Event directly
                    try:
                        ev = Event(name='Imported (Missing Event) - Portable Import', code=None, year=datetime.now(timezone.utc).year)
                        db.session.add(ev)
                        db.session.flush()
                        mapping['events'][None] = ev.id
                        db.session.commit()
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass

        # Ensure we have a placeholder Event for any MATCH entries that reference a missing event
        if export_data.get('matches'):
            need_placeholder = False
            for m in export_data.get('matches', []):
                if m.get('event_id') is None or m.get('event_id') not in mapping['events']:
                    need_placeholder = True
                    break
            if need_placeholder:
                try:
                    placeholder = get_or_create_event(
                        name='Imported (Missing Event) - Portable Import',
                        code=f'IMPORT-NULL-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',
                        year=datetime.now(timezone.utc).year
                    )
                    mapping['events'][None] = placeholder.id
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    # Fallback: attempt to create Event directly
                    try:
                        ev = Event(name='Imported (Missing Event) - Portable Import', code=None, year=datetime.now(timezone.utc).year)
                        db.session.add(ev)
                        db.session.flush()
                        mapping['events'][None] = ev.id
                        db.session.commit()
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass

        # MATCHES
        for m in export_data.get('matches', []):
            # Look up mapped event id. If mapping doesn't contain a key for the
            # exported event_id, fall back to the placeholder (mapping['events'][None])
            # Prefer resolving the exported event id via code/metadata if possible
            new_event = mapping['events'].get(m.get('event_id'))
            if new_event is None:
                new_event = _resolve_event(m.get('event_id'), fallback_scouting_team=m.get('scouting_team_number'))
                if new_event is None:
                    # If still None, ensure a global placeholder exists
                    if mapping['events'].get(None) is None:
                        try:
                            placeholder = get_or_create_event(
                                name='Imported (Missing Event) - Portable Import',
                                code=f'IMPORT-NULL-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',
                                year=datetime.now(timezone.utc).year
                            )
                            mapping['events'][None] = placeholder.id
                            db.session.commit()
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            # Fallback to creating a minimal Event directly
                            try:
                                ev = Event(name='Imported (Missing Event) - Portable Import', code=None, year=datetime.now(timezone.utc).year)
                                db.session.add(ev)
                                db.session.flush()
                                mapping['events'][None] = ev.id
                                db.session.commit()
                            except Exception:
                                try:
                                    db.session.rollback()
                                except Exception:
                                    pass
                    new_event = mapping['events'].get(None)
            existing = None
            if new_event:
                existing = Match.query.filter_by(event_id=new_event, match_type=m.get('match_type'), match_number=m.get('match_number')).first()

            if existing:
                existing.red_alliance = m.get('red_alliance') or ''
                existing.blue_alliance = m.get('blue_alliance') or ''
                existing.red_score = m.get('red_score')
                existing.blue_score = m.get('blue_score')
                existing.winner = m.get('winner')
                db.session.add(existing)
                mapping['matches'][m['id']] = existing.id
                report['updated']['matches'] = report['updated'].get('matches', 0) + 1 if report['updated'].get('matches') else 1
            else:
                # If we still don't have an event id, skip this match and report error
                if not new_event:
                    report['errors'].append(f"Skipping match import (no event): {m.get('match_number')} {m.get('match_type')}")
                    continue
                new_m = Match(
                    match_number=m.get('match_number'),
                    match_type=m.get('match_type'),
                    event_id=new_event if new_event else mapping['events'].get(None),
                    red_alliance=m.get('red_alliance') or '',
                    blue_alliance=m.get('blue_alliance') or '',
                    red_score=m.get('red_score'),
                    blue_score=m.get('blue_score'),
                    winner=m.get('winner'),
                    scouting_team_number=m.get('scouting_team_number')
                )
                db.session.add(new_m)
                db.session.flush()
                # If for some reason event_id persisted as None (race or mapping issue), assign placeholder if available
                try:
                    if (not new_m.event_id) and mapping['events'].get(None):
                        new_m.event_id = mapping['events'].get(None)
                        db.session.add(new_m)
                        db.session.flush()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                mapping['matches'][m['id']] = new_m.id
                report['created']['matches'] = report['created'].get('matches', 0) + 1 if report['created'].get('matches') else 1

        db.session.commit()

        # SCOUTING DATA - upsert by match+team+scouting_team_number
        for sd in export_data.get('scouting_data', []):
            new_match = mapping['matches'].get(sd.get('match_id'))
            new_team = mapping['teams'].get(sd.get('team_id'))
            if not new_match or not new_team:
                report['skipped']['scouting_data'] = report['skipped'].get('scouting_data', 0) + 1 if report['skipped'].get('scouting_data') else 1
                continue

            existing_sd = ScoutingData.query.filter_by(match_id=new_match, team_id=new_team, scouting_team_number=sd.get('scouting_team_number')).first()
            if existing_sd:
                # Merge JSON data conservatively: prefer incoming non-null values, keep existing otherwise
                try:
                    incoming = json.loads(sd.get('data_json')) if isinstance(sd.get('data_json'), str) else sd.get('data_json') or {}
                except Exception:
                    incoming = {}
                try:
                    existing = existing_sd.data or {}
                except Exception:
                    existing = {}

                merged = existing.copy()
                for k, v in incoming.items():
                    if v is not None:
                        merged[k] = v

                existing_sd.data_json = json.dumps(merged)
                existing_sd.scout_name = sd.get('scout_name') or existing_sd.scout_name
                existing_sd.scouting_station = sd.get('scouting_station') or existing_sd.scouting_station
                db.session.add(existing_sd)
                mapping['scouting_data'][sd['id']] = existing_sd.id
                report['updated']['scouting_data'] = report['updated'].get('scouting_data', 0) + 1 if report['updated'].get('scouting_data') else 1
            else:
                new_sd = ScoutingData(
                    match_id=new_match,
                    team_id=new_team,
                    scouting_team_number=sd.get('scouting_team_number'),
                    scout_name=sd.get('scout_name'),
                    scout_id=sd.get('scout_id'),
                    scouting_station=sd.get('scouting_station'),
                    alliance=sd.get('alliance'),
                    data_json=sd.get('data_json')
                )
                db.session.add(new_sd)
                db.session.flush()
                mapping['scouting_data'][sd['id']] = new_sd.id
                report['created']['scouting_data'] = report['created'].get('scouting_data', 0) + 1 if report['created'].get('scouting_data') else 1

        db.session.commit()

        # The rest is best-effort and mirrors import_portable - skip for brevity but handle similar upserts
        # PIT SCOUTING
        for p in export_data.get('pit_scouting', []):
            new_team = mapping['teams'].get(p.get('team_id'))
            new_event = mapping['events'].get(p.get('event_id'))
            if not new_team:
                report['skipped']['pit_scouting'] = report['skipped'].get('pit_scouting', 0) + 1 if report['skipped'].get('pit_scouting') else 1
                continue
            try:
                new_p = PitScoutingData.from_dict(p)
                new_p.team_id = new_team
                new_p.event_id = new_event
                db.session.add(new_p)
                db.session.flush()
                mapping['pit_scouting'][p['id']] = new_p.id
            except Exception:
                db.session.rollback()
                report['errors'].append(f'Failed to import pit scouting entry for team {p.get("team_id")}')

        db.session.commit()

        # STRATEGY DRAWINGS
        for s in export_data.get('strategy_drawings', []):
            try:
                new_match = mapping['matches'].get(s.get('match_id'))
                new_s = StrategyDrawing(
                    match_id=new_match if new_match else None,
                    scouting_team_number=s.get('scouting_team_number'),
                    data_json=s.get('data_json'),
                    background_image=s.get('background_image')
                )
                db.session.add(new_s)
                db.session.flush()
                mapping['strategy_drawings'][s['id']] = new_s.id
            except Exception:
                db.session.rollback()
                report['errors'].append(f'Failed to import strategy drawing {s.get("id")}')

        db.session.commit()

        # ALLIANCES / DO_NOT_PICK / AVOID
        for a in export_data.get('alliances', []):
            try:
                # Resolve event by exported id and exported metadata (prefer code match across servers)
                new_event = mapping['events'].get(a.get('event_id'))
                if new_event is None:
                    new_event = _resolve_event(a.get('event_id'), fallback_scouting_team=a.get('scouting_team_number'))
                    if new_event is None:
                        if mapping['events'].get(None) is None:
                            try:
                                placeholder = get_or_create_event(
                                    name='Imported (Missing Event) - Portable Import',
                                    code=f'IMPORT-NULL-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',
                                    year=datetime.now(timezone.utc).year,
                                    scouting_team_number=a.get('scouting_team_number') if a.get('scouting_team_number') else None
                                )
                                mapping['events'][None] = placeholder.id
                                report['created']['events'] = report['created'].get('events', 0) + 1 if report.get('created') else 1
                                current_app.logger.info(f"Created placeholder event id={placeholder.id} for missing alliance event reference")
                                db.session.commit()
                            except Exception:
                                try:
                                    db.session.rollback()
                                except Exception:
                                    pass
                                try:
                                    ev = Event(name='Imported (Missing Event) - Portable Import', code=None, year=datetime.now(timezone.utc).year)
                                    ev.scouting_team_number = a.get('scouting_team_number') if a.get('scouting_team_number') else None
                                    db.session.add(ev)
                                    db.session.flush()
                                    mapping['events'][None] = ev.id
                                    report['created']['events'] = report['created'].get('events', 0) + 1 if report.get('created') else 1
                                    db.session.commit()
                                except Exception:
                                    try:
                                        db.session.rollback()
                                    except Exception:
                                        pass
                        new_event = mapping['events'].get(None)

                new_alliance = AllianceSelection(
                    alliance_number=a.get('alliance_number'),
                    captain=mapping['teams'].get(a.get('captain')) if a.get('captain') else None,
                    first_pick=mapping['teams'].get(a.get('first_pick')) if a.get('first_pick') else None,
                    second_pick=mapping['teams'].get(a.get('second_pick')) if a.get('second_pick') else None,
                    third_pick=mapping['teams'].get(a.get('third_pick')) if a.get('third_pick') else None,
                    event_id=new_event,
                    scouting_team_number=a.get('scouting_team_number')
                )
                db.session.add(new_alliance)
            except Exception:
                db.session.rollback()
                report['errors'].append(f'Failed to import alliance selection {a.get("id")}')

        for e in export_data.get('do_not_pick', []):
            try:
                new_team = mapping['teams'].get(e.get('team_id'))
                new_event = mapping['events'].get(e.get('event_id'))
                if new_team:
                    new_e = DoNotPickEntry(
                        team_id=new_team,
                        event_id=new_event,
                        reason=e.get('reason'),
                        scouting_team_number=e.get('scouting_team_number')
                    )
                    db.session.add(new_e)
            except Exception:
                db.session.rollback()
                report['errors'].append(f'Failed to import do_not_pick entry {e.get("id")}')

        for a in export_data.get('avoid', []):
            try:
                new_team = mapping['teams'].get(a.get('team_id'))
                new_event = mapping['events'].get(a.get('event_id'))
                if new_team:
                    new_a = AvoidEntry(
                        team_id=new_team,
                        event_id=new_event,
                        reason=a.get('reason'),
                        scouting_team_number=a.get('scouting_team_number')
                    )
                    db.session.add(new_a)
            except Exception:
                db.session.rollback()
                report['errors'].append(f'Failed to import avoid entry {a.get("id")}')

        db.session.commit()

        # SHARED GRAPHS & SHARED TEAM RANKS - upsert by share_id
        for g in export_data.get('shared_graphs', []):
            try:
                share_id = g.get('share_id')
                existing_sg = None
                if share_id:
                    existing_sg = SharedGraph.query.filter_by(share_id=share_id).first()

                if existing_sg:
                    existing_sg.title = g.get('title')
                    existing_sg.description = g.get('description')
                    existing_sg.team_numbers = json.dumps(g.get('team_numbers') if g.get('team_numbers') else [])
                    existing_sg.event_id = mapping['events'].get(g.get('event_id')) if g.get('event_id') else None
                    existing_sg.metric = g.get('metric')
                    existing_sg.graph_types = json.dumps(g.get('graph_types') if g.get('graph_types') else [])
                    existing_sg.data_view = g.get('data_view')
                    existing_sg.created_by_team = g.get('created_by_team')
                    existing_sg.created_by_user = g.get('created_by_user')
                    existing_sg.created_at = datetime.fromisoformat(g['created_at']) if g.get('created_at') else None
                    existing_sg.expires_at = datetime.fromisoformat(g['expires_at']) if g.get('expires_at') else None
                    existing_sg.view_count = g.get('view_count', 0)
                    existing_sg.is_active = g.get('is_active', True)
                    db.session.add(existing_sg)
                else:
                    sg = SharedGraph(
                        share_id=share_id,
                        title=g.get('title'),
                        description=g.get('description'),
                        team_numbers=json.dumps(g.get('team_numbers') if g.get('team_numbers') else []),
                        event_id=mapping['events'].get(g.get('event_id')) if g.get('event_id') else None,
                        metric=g.get('metric'),
                        graph_types=json.dumps(g.get('graph_types') if g.get('graph_types') else []),
                        data_view=g.get('data_view'),
                        created_by_team=g.get('created_by_team'),
                        created_by_user=g.get('created_by_user'),
                        created_at=datetime.fromisoformat(g['created_at']) if g.get('created_at') else None,
                        expires_at=datetime.fromisoformat(g['expires_at']) if g.get('expires_at') else None,
                        view_count=g.get('view_count', 0),
                        is_active=g.get('is_active', True)
                    )
                    db.session.add(sg)
            except IntegrityError:
                db.session.rollback()
                try:
                    if share_id:
                        existing = SharedGraph.query.filter_by(share_id=share_id).first()
                        if existing:
                            existing.title = g.get('title')
                            existing.description = g.get('description')
                            existing.team_numbers = json.dumps(g.get('team_numbers') if g.get('team_numbers') else [])
                            existing.event_id = mapping['events'].get(g.get('event_id')) if g.get('event_id') else None
                            db.session.add(existing)
                except Exception:
                    pass
            except Exception:
                db.session.rollback()
                report['errors'].append(f'Failed to import shared graph {g.get("id") or g.get("share_id")}')

        for r in export_data.get('shared_team_ranks', []):
            try:
                share_id = r.get('share_id')
                existing_sr = None
                if share_id:
                    existing_sr = SharedTeamRanks.query.filter_by(share_id=share_id).first()

                if existing_sr:
                    existing_sr.title = r.get('title')
                    existing_sr.description = r.get('description')
                    existing_sr.event_id = mapping['events'].get(r.get('event_id')) if r.get('event_id') else None
                    existing_sr.metric = r.get('metric')
                    existing_sr.created_by_team = r.get('created_by_team')
                    existing_sr.created_by_user = r.get('created_by_user')
                    existing_sr.created_at = datetime.fromisoformat(r['created_at']) if r.get('created_at') else None
                    existing_sr.expires_at = datetime.fromisoformat(r['expires_at']) if r.get('expires_at') else None
                    existing_sr.view_count = r.get('view_count', 0)
                    existing_sr.is_active = r.get('is_active', True)
                    db.session.add(existing_sr)
                else:
                    sr = SharedTeamRanks(
                        share_id=share_id,
                        title=r.get('title'),
                        description=r.get('description'),
                        event_id=mapping['events'].get(r.get('event_id')) if r.get('event_id') else None,
                        metric=r.get('metric'),
                        created_by_team=r.get('created_by_team'),
                        created_by_user=r.get('created_by_user'),
                        created_at=datetime.fromisoformat(r['created_at']) if r.get('created_at') else None,
                        expires_at=datetime.fromisoformat(r['expires_at']) if r.get('expires_at') else None,
                        view_count=r.get('view_count', 0),
                        is_active=r.get('is_active', True)
                    )
                    db.session.add(sr)
            except IntegrityError:
                db.session.rollback()
                try:
                    if share_id:
                        existing = SharedTeamRanks.query.filter_by(share_id=share_id).first()
                        if existing:
                            existing.title = r.get('title')
                            existing.description = r.get('description')
                            existing.event_id = mapping['events'].get(r.get('event_id')) if r.get('event_id') else None
                            db.session.add(existing)
                except Exception:
                    pass
            except Exception:
                db.session.rollback()
                report['errors'].append(f'Failed to import shared team ranks {r.get("id") or r.get("share_id")}')

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error processing portable data via helper')
        return False, str(e)

    # Build short summary
    msg_parts = []
    for k in ('events', 'teams', 'matches'):
        c = report['created'].get(k, 0) if report.get('created') else 0
        u = report['updated'].get(k, 0) if report.get('updated') else 0
        if c or u:
            msg_parts.append(f"{k}: created={c} updated={u}")

    return True, '; '.join(msg_parts)


def import_portable_from_zip(zip_path):
    """Process a portable ZIP file (path) and delegate to _process_portable_data.

    This helper is robust to several bundle formats:
      - Multiple top-level JSON files (events.json, teams.json, etc.)
      - A single bundle file like export.json / portable_export.json containing a dict with keys
      - Files nested inside a top-level folder (e.g., "portable_export_.../events.json")
      - Newline-delimited JSON (JSONL) fallback when standard JSON fails

    Returns (success: bool, message: str).
    """
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            json_files = [n for n in names if n.lower().endswith('.json')]

            def basename_of(path):
                return os.path.basename(path).lower()

            # Helper: find a file by basename (handles nested folders)
            def find_file_by_basename(basename):
                basename = basename.lower()
                # prefer exact matches
                for n in json_files:
                    if basename_of(n) == basename:
                        return n
                # fallback: any path that ends with the basename
                for n in json_files:
                    if n.lower().endswith('/' + basename):
                        return n
                return None

            # Helper: load a JSON file from the zip. Falls back to JSONL if needed.
            def load_json_from_zip(path_in_zip):
                if path_in_zip is None:
                    return []
                try:
                    with z.open(path_in_zip) as f:
                        raw = f.read()
                        try:
                            return json.loads(raw.decode('utf-8'))
                        except Exception:
                            # Try lenient fallback: parse as JSONL (one JSON object per line)
                            try:
                                text = raw.decode('utf-8', errors='replace')
                                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                                objs = [json.loads(ln) for ln in lines]
                                return objs
                            except Exception:
                                current_app.logger.exception(f"Failed to decode JSON from {path_in_zip}")
                                return []
                except KeyError:
                    return []
                except Exception:
                    current_app.logger.exception(f"Error reading {path_in_zip} from zip")
                    return []

            # First: check for single-bundle JSON files which contain a dict of lists
            bundle_basenames = ('export.json', 'portable_export.json', 'data.json', 'bundle.json')
            for b in bundle_basenames:
                candidate = find_file_by_basename(b)
                if candidate:
                    try:
                        with z.open(candidate) as f:
                            bundle = json.load(f)
                    except Exception:
                        current_app.logger.exception(f"Failed to load bundle {candidate}, will attempt per-file import")
                        bundle = None

                    if isinstance(bundle, dict) and any(k in bundle for k in ('events', 'teams', 'matches', 'scouting_data')):
                        export_data = {}
                        # Normalize expected keys
                        for key in ('events','teams','team_event','matches','scouting_data','pit_scouting','strategy_drawings','alliances','do_not_pick','avoid','shared_graphs','shared_team_ranks'):
                            val = bundle.get(key, [])
                            # If someone exported a single object rather than a list, wrap it
                            if isinstance(val, dict):
                                val = [val]
                            export_data[key] = val if isinstance(val, list) else []

                        success, msg = _process_portable_data(export_data)
                        if success:
                            current_app.logger.info(f"Portable bundle import completed: {msg}")
                        else:
                            current_app.logger.error(f"Portable bundle import failed: {msg}")
                        return success, msg

            # Otherwise, assemble export_data from individual JSON files (basename-aware)
            keys_and_files = {
                'events': 'events.json',
                'teams': 'teams.json',
                'team_event': 'team_event.json',
                'matches': 'matches.json',
                'scouting_data': 'scouting_data.json',
                'pit_scouting': 'pit_scouting.json',
                'strategy_drawings': 'strategy_drawings.json',
                'alliances': 'alliances.json',
                'do_not_pick': 'do_not_pick.json',
                'avoid': 'avoid.json',
                'shared_graphs': 'shared_graphs.json',
                'shared_team_ranks': 'shared_team_ranks.json'
            }

            export_data = {}
            for key, fname in keys_and_files.items():
                matched = find_file_by_basename(fname)
                data = load_json_from_zip(matched)
                # Normalize single-object to list
                if isinstance(data, dict):
                    data = [data]
                if not isinstance(data, list):
                    data = []
                export_data[key] = data

        success, msg = _process_portable_data(export_data)
        if success:
            current_app.logger.info(f"Portable import completed: {msg}")
        else:
            current_app.logger.error(f"Portable import failed: {msg}")
        return success, msg
    except Exception as e:
        current_app.logger.exception(f"Error processing portable zip {zip_path}: {e}")
        return False, str(e)

@bp.route('/')
@analytics_required
def index():
    """Data import/export dashboard"""
    # Get database statistics
    teams_count = filter_teams_by_scouting_team().count()
    matches_count = filter_matches_by_scouting_team().count()
    scouting_count = filter_scouting_data_by_scouting_team().count()
    
    return render_template('data/index.html', 
                          teams_count=teams_count,
                          matches_count=matches_count, 
                          scouting_count=scouting_count,
                          **get_theme_context())

@bp.route('/import/excel', methods=['GET', 'POST'])
def import_excel():
    """Import data from Excel files"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and file.filename.endswith(('.xlsx', '.xls')):
            # Save file temporarily
            filename = secure_filename(file.filename)
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            try:
                # Try reading all sheets first to detect portable-style exports
                xls = pd.read_excel(file_path, sheet_name=None)

                # Normalize sheet names and detect portable-style exports robustly
                sheet_names = list(xls.keys())
                # Build map: normalized -> actual name
                norm_map = {}
                for n in sheet_names:
                    norm = n.strip().lower().replace('_', ' ').replace('-', ' ')
                    norm_map[norm] = n

                expected_norms = set(['events', 'teams', 'team event', 'team_event', 'matches', 'scouting data', 'scouting_data'])
                portable_like = any(en in norm_map for en in expected_norms)

                if portable_like:
                    export_data = {}

                    def df_to_records_by_actual(actual_name):
                        df = xls.get(actual_name)
                        if df is None:
                            return []
                        records = df.where(pd.notnull(df), None).to_dict(orient='records')
                        # Normalize datetime fields to isoformat strings
                        for r in records:
                            for k, v in list(r.items()):
                                if hasattr(v, 'isoformat'):
                                    r[k] = v.isoformat()
                        return records

                    def find_sheet(*candidates):
                        # candidates are normalized names to try; return actual sheet name or None
                        for c in candidates:
                            cn = c.strip().lower().replace('_', ' ').replace('-', ' ')
                            if cn in norm_map:
                                return norm_map[cn]
                        return None

                    export_data['events'] = df_to_records_by_actual(find_sheet('events'))
                    export_data['teams'] = df_to_records_by_actual(find_sheet('teams'))
                    export_data['team_event'] = df_to_records_by_actual(find_sheet('team_event', 'team event'))
                    export_data['matches'] = df_to_records_by_actual(find_sheet('matches'))
                    export_data['scouting_data'] = df_to_records_by_actual(find_sheet('scouting data', 'scouting_data', 'scouting'))
                    export_data['pit_scouting'] = df_to_records_by_actual(find_sheet('pit scouting', 'pit_scouting'))
                    export_data['strategy_drawings'] = df_to_records_by_actual(find_sheet('strategy drawings', 'strategy_drawings'))
                    export_data['alliances'] = df_to_records_by_actual(find_sheet('alliances'))
                    export_data['do_not_pick'] = df_to_records_by_actual(find_sheet('do not pick', 'do_not_pick', 'donotpick', 'donot_pick'))
                    export_data['avoid'] = df_to_records_by_actual(find_sheet('avoid'))
                    export_data['shared_graphs'] = df_to_records_by_actual(find_sheet('shared graphs', 'shared_graphs', 'sharedgraphs'))
                    export_data['shared_team_ranks'] = df_to_records_by_actual(find_sheet('shared team ranks', 'shared_team_ranks', 'sharedteamranks'))

                    # Call shared processor
                    success, msg = _process_portable_data(export_data)
                    if success:
                        flash('Excel portable import successful! ' + (msg or ''), 'success')
                    else:
                        flash('Excel portable import failed: ' + (msg or 'unknown error'), 'danger')

                    # Clean up and redirect
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                    return redirect(url_for('data.index'))

                # Fallback: original simple row-based import (legacy single-sheet format)
                df = pd.read_excel(file_path)
                
                # Get game configuration
                game_config = get_effective_game_config()
                
                # Process each row as scouting data
                records_added = 0
                records_updated = 0

                def _parse_int_field(val):
                    # Return int value for ints/floats/numeric-strings; return None for missing/NA
                    try:
                        if val is None:
                            return None
                        if pd.isna(val):
                            return None
                        # Strings like '1' or '1.0'
                        if isinstance(val, str):
                            s = val.strip()
                            if s == '':
                                return None
                            return int(float(s))
                        # For numpy ints, floats, Python ints
                        return int(float(val))
                    except Exception:
                        return None

                # Build a column normalization map so we can accept headers like 'Match Number' or 'match-number'
                col_norm_map = {}
                for c in df.columns:
                    try:
                        key = str(c).strip().lower().replace(' ', '_').replace('-', '_')
                        col_norm_map[key] = c
                    except Exception:
                        continue

                def find_col(name):
                    # name expected like 'match_number'
                    if name in col_norm_map:
                        return col_norm_map[name]
                    # try variations
                    alt = name.replace('_', ' ')
                    if alt in col_norm_map:
                        return col_norm_map[alt]
                    # fallback to original string if present
                    if name in df.columns:
                        return name
                    return None

                match_col = find_col('match_number')
                team_col = find_col('team_number')

                for _, row in df.iterrows():
                    # Extract basic information
                    try:
                        raw_match = row.get(match_col) if match_col else row.get('match_number')
                        raw_team = row.get(team_col) if team_col else row.get('team_number')
                        match_number = _parse_int_field(raw_match)
                        team_number = _parse_int_field(raw_team)

                        # If essential numeric fields are missing, skip with a clear message
                        if match_number is None:
                            flash(f"Skipping row: invalid or missing match_number ({raw_match})", 'warning')
                            continue
                        if team_number is None:
                            flash(f"Skipping row: invalid or missing team_number ({raw_team})", 'warning')
                            continue

                        scout_name = row.get('scout_name', 'Excel Import')
                        alliance = row.get('alliance', 'unknown')
                        
                        # Find or create team
                        team = Team.query.filter_by(team_number=team_number).first()
                        if not team:
                            team = Team(team_number=team_number, team_name=f'Team {team_number}')
                            db.session.add(team)
                            db.session.flush()
                            
                        # Find or create match
                        match_type = row.get('match_type', 'Qualification')
                        match = Match.query.filter_by(match_number=match_number, match_type=match_type).first()
                        if not match:
                            # Need to find or create an event first
                            event_name = row.get('event_name', 'Unknown Event')
                            event = get_or_create_event(name=event_name, year=game_config['season'])
                                
                            # Create the match
                            match = Match(
                                match_number=match_number,
                                match_type=match_type,
                                event_id=event.id,
                                red_alliance=str(team_number) if alliance == 'red' else '',
                                blue_alliance=str(team_number) if alliance == 'blue' else ''
                            )
                            db.session.add(match)
                            db.session.flush()
                        
                        # Build scouting data from row
                        data = {}
                        
                        # Process data based on game config
                        all_elements = []
                        all_elements.extend(game_config['auto_period']['scoring_elements'])
                        all_elements.extend(game_config['teleop_period']['scoring_elements'])
                        all_elements.extend(game_config['endgame_period']['scoring_elements'])
                        all_elements.extend(game_config['post_match']['rating_elements'])
                        all_elements.extend(game_config['post_match']['text_elements'])
                        
                        for element in all_elements:
                            element_id = element['id']
                            if element_id in row:
                                if element['type'] == 'boolean':
                                    # Convert to boolean
                                    data[element_id] = bool(row[element_id])
                                elif element['type'] == 'counter':
                                    # Convert to integer
                                    data[element_id] = int(row[element_id])
                                else:
                                    # Keep as is
                                    data[element_id] = row[element_id]
                            else:
                                # Use default if available
                                if 'default' in element:
                                    data[element_id] = element['default']
                        
                        # Check if scouting data already exists
                        existing_data = ScoutingData.query.filter_by(
                            match_id=match.id, 
                            team_id=team.id,
                            scouting_team_number=current_user.scouting_team_number
                        ).first()
                        
                        if existing_data:
                            # Merge existing and incoming conservatively
                            try:
                                incoming = data
                                existing_json = existing_data.data or {}
                            except Exception:
                                incoming = data
                                existing_json = {}
                            merged = existing_json.copy()
                            for k, v in incoming.items():
                                if v is not None:
                                    merged[k] = v
                            existing_data.data_json = json.dumps(merged)
                            existing_data.alliance = alliance or existing_data.alliance
                            existing_data.scout_name = scout_name or existing_data.scout_name
                            records_updated += 1
                        else:
                            # Create new record
                            scouting_data = ScoutingData(
                                match_id=match.id,
                                team_id=team.id,
                                scout_name=scout_name,
                                alliance=alliance,
                                data_json=json.dumps(data),
                                scouting_team_number=current_user.scouting_team_number
                            )
                            db.session.add(scouting_data)
                            records_added += 1
                    
                    except Exception as e:
                        flash(f'Error processing row: {e}', 'error')
                        continue
                
                # Commit all changes
                db.session.commit()
                
                flash(f'Import successful! {records_added} records added, {records_updated} records updated.', 'success')
            
            except Exception as e:
                flash(f'Error processing Excel file: {e}', 'error')
            
            finally:
                # Clean up the temporary file
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            
            return redirect(url_for('data.index'))
        
        else:
            flash('Invalid file format. Please upload an Excel file (.xlsx, .xls)', 'error')
            return redirect(request.url)
    
    return render_template('data/import_excel.html', **get_theme_context())

@bp.route('/import_qr', methods=['GET', 'POST'])
def import_qr():
    """Import data from QR codes (manual entry or upload)"""
    if request.method == 'POST':
        # Handle API request with JSON data
        if request.is_json:
            try:
                qr_data = request.get_json().get('data')
                if not qr_data:
                    return {'success': False, 'message': 'No data provided'}
            except Exception as e:
                return {'success': False, 'message': f'Invalid JSON: {str(e)}'}
        else:
            # Handle form submission
            qr_data = request.form.get('qr_data')
            if not qr_data:
                flash('No QR code data received', 'error')
                return redirect(request.url)
                
        try:
            # Parse QR data (assuming it's JSON)
            scouting_data_json = json.loads(qr_data)
            
            # Detect the format of the QR code
            if 'offline_generated' in scouting_data_json:
                # This is from our offline Generate QR button
                team_id = scouting_data_json.get('team_id')
                match_id = scouting_data_json.get('match_id')
                scout_name = scouting_data_json.get('scout_name', 'QR Import')
                alliance = scouting_data_json.get('alliance', 'unknown')
                
                # Get team and match directly by ID
                team = Team.query.get(team_id)
                match = Match.query.get(match_id)
                
                if not team or not match:
                    error_msg = 'Team or match not found in database'
                    if request.is_json:
                        return {'success': False, 'message': error_msg}
                    flash(error_msg, 'error')
                    return redirect(request.url)
                
                # Extract all form data, excluding metadata fields
                data = {}
                for key, value in scouting_data_json.items():
                    # Skip metadata fields
                    if key not in ['team_id', 'match_id', 'scout_name', 'alliance', 
                                  'generated_at', 'offline_generated']:
                        data[key] = value
                
            elif 't' in scouting_data_json and 'm' in scouting_data_json:
                # Compact format with single-letter keys
                team_number = scouting_data_json.get('t')  # team_number
                match_number = scouting_data_json.get('m')  # match_number
                scout_name = scouting_data_json.get('s', 'QR Import')  # scout_name
                alliance = scouting_data_json.get('a', 'unknown')  # alliance
                match_type = scouting_data_json.get('mt', 'Qualification')  # match_type
                
                # Find or create team
                team = Team.query.filter_by(team_number=team_number).first()
                if not team:
                    team = Team(team_number=team_number, team_name=f'Team {team_number}')
                    db.session.add(team)
                    db.session.flush()
                
                # Find or create match
                match = Match.query.filter_by(match_number=match_number, match_type=match_type).first()
                if not match:
                    # Need to find or create an event first
                    game_config = get_effective_game_config()
                    event_name = scouting_data_json.get('event_name', 'Unknown Event')
                    event = get_or_create_event(name=event_name, year=game_config['season'])
                    
                    # Create the match
                    match = Match(
                        match_number=match_number,
                        match_type=match_type,
                        event_id=event.id,
                        red_alliance=str(team_number) if alliance == 'red' else '',
                        blue_alliance=str(team_number) if alliance == 'blue' else ''
                    )
                    db.session.add(match)
                    db.session.flush()
                
                # Get data from compact format
                data = {}
                if 'd' in scouting_data_json:
                    data = scouting_data_json['d']
            
            else:
                # Legacy format or unknown format
                team_number = scouting_data_json.get('team_number')
                match_number = scouting_data_json.get('match_number')
                
                if not team_number or not match_number:
                    error_msg = 'Invalid QR data: missing team or match number'
                    if request.is_json:
                        return {'success': False, 'message': error_msg}
                    flash(error_msg, 'error')
                    return redirect(request.url)
                
                scout_name = scouting_data_json.get('scout_name', 'QR Import')
                alliance = scouting_data_json.get('alliance', 'unknown')
                match_type = scouting_data_json.get('match_type', 'Qualification')
                
                # Find or create team
                team = Team.query.filter_by(team_number=team_number).first()
                if not team:
                    team = Team(team_number=team_number, team_name=f'Team {team_number}')
                    db.session.add(team)
                    db.session.flush()
                
                # Find or create match
                match = Match.query.filter_by(match_number=match_number, match_type=match_type).first()
                if not match:
                    # Need to find or create an event first
                    game_config = get_effective_game_config()
                    event_name = scouting_data_json.get('event_name', 'Unknown Event')
                    event = get_or_create_event(name=event_name, year=game_config['season'])
                    
                    # Create the match
                    match = Match(
                        match_number=match_number,
                        match_type=match_type,
                        event_id=event.id,
                        red_alliance=str(team_number) if alliance == 'red' else '',
                        blue_alliance=str(team_number) if alliance == 'blue' else ''
                    )
                    db.session.add(match)
                    db.session.flush()
                
                # Check if data is in a nested field or directly in root
                if 'scouting_data' in scouting_data_json:
                    # Data is in the nested 'scouting_data' field
                    data = scouting_data_json.get('scouting_data', {})
                else:
                    # Data is directly in the root (try to extract all non-metadata fields)
                    data = {}
                    for key, value in scouting_data_json.items():
                        # Skip metadata fields we've already processed
                        if key not in ['match_number', 'team_number', 'scout_name', 'alliance', 
                                      'match_type', 'event_name', 'timestamp']:
                            data[key] = value
            
            # Check if scouting data already exists
            existing_data = ScoutingData.query.filter_by(
                match_id=match.id, 
                team_id=team.id,
                scouting_team_number=current_user.scouting_team_number
            ).first()
            
            if existing_data:
                # Update existing record
                existing_data.data = data
                existing_data.alliance = alliance
                existing_data.scout_name = scout_name
                db.session.commit()
                
                success_msg = f'Updated scouting data for Team {team.team_number} in Match {match.match_number}'
                if request.is_json:
                    return {'success': True, 'message': success_msg}
                flash(success_msg, 'success')
            else:
                # Create new record
                new_scouting_data = ScoutingData(
                    match_id=match.id,
                    team_id=team.id,
                    scout_name=scout_name,
                    alliance=alliance,
                    data_json=json.dumps(data),
                    scouting_team_number=current_user.scouting_team_number
                )
                db.session.add(new_scouting_data)
                db.session.commit()
                
                success_msg = f'Added new scouting data for Team {team.team_number} in Match {match.match_number}'
                if request.is_json:
                    return {'success': True, 'message': success_msg}
                flash(success_msg, 'success')
            
            if request.is_json:
                return {'success': True, 'message': 'Data processed successfully'}
            return redirect(url_for('data.import_qr', success=True))
            
        except json.JSONDecodeError as e:
            error_msg = 'Invalid QR code data format. Expected JSON data.'
            if request.is_json:
                return {'success': False, 'message': error_msg}
            flash(error_msg, 'error')
        except Exception as e:
            error_msg = f'Error processing QR data: {str(e)}'
            if request.is_json:
                return {'success': False, 'message': error_msg}
            flash(error_msg, 'error')
    
    success = request.args.get('success', False)
    return render_template('data/import_qr.html', success=success, **get_theme_context())


# Provide JSON access to events under /data/events to match API behavior
@bp.route('/events', methods=['GET'])
@team_data_access_required
def data_events():
    """Return events as JSON similar to /api/v1/events so clients can access via /data/events"""
    try:
        events_query = Event.query

        # Optional filters
        event_code = request.args.get('code')
        if event_code:
            events_query = events_query.filter(Event.code.ilike(f'%{event_code}%'))

        location = request.args.get('location')
        if location:
            events_query = events_query.filter(Event.location.ilike(f'%{location}%'))

        limit = request.args.get('limit', 100, type=int)
        if limit > 1000:
            limit = 1000
        offset = request.args.get('offset', 0, type=int)

        events = events_query.offset(offset).limit(limit).all()
        total_count = events_query.count()

        # Deduplicate events by normalized code (prefer most complete record)
        from app.models import ScoutingAllianceEvent
        from sqlalchemy import func
        events_by_code = {}
        def event_score(e):
            score = 0
            if e.name: score += 10
            if e.location: score += 5
            if getattr(e, 'start_date', None): score += 5
            if getattr(e, 'end_date', None): score += 3
            if getattr(e, 'timezone', None): score += 2
            if e.year: score += 1
            return score

        for e in events:
            key = (e.code or f'__id_{e.id}').strip().upper()
            if key in events_by_code:
                # prefer higher score
                if event_score(e) > event_score(events_by_code[key]):
                    events_by_code[key] = e
            else:
                events_by_code[key] = e

        events_data = []
        for key, event in events_by_code.items():
            # Mark as alliance if any active ScoutingAllianceEvent exists with this code
            is_alliance = False
            try:
                if key.startswith('__id_'):
                    is_alliance = False
                else:
                    sae = ScoutingAllianceEvent.query.filter(func.upper(ScoutingAllianceEvent.event_code) == key, ScoutingAllianceEvent.is_active == True).first()
                    is_alliance = sae is not None
            except Exception:
                is_alliance = False

            events_data.append({
                'id': event.id,
                'name': event.name,
                'code': event.code,
                'location': event.location,
                'start_date': event.start_date.isoformat() if event.start_date else None,
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'team_count': len(event.teams),
                'is_alliance': is_alliance
            })

        return jsonify({
            'success': True,
            'events': events_data,
            'count': len(events_data),
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        current_app.logger.error(f"Error getting events via /data/events: {str(e)}")
        return jsonify({'error': 'Failed to retrieve events'}), 500

@bp.route('/export/excel')
def export_excel():
    """Export all scouting data to Excel"""
    # Get game configuration
    game_config = get_effective_game_config()
    # We'll build multiple sheets to include all useful tables
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # 1) Events
        try:
            events = get_combined_dropdown_events()
            events_rows = []
            for e in events:
                events_rows.append({
                    'id': e.id,
                    'name': e.name,
                    'code': e.code,
                    'location': e.location,
                    'start_date': e.start_date,
                    'end_date': e.end_date,
                    'year': e.year,
                    'scouting_team_number': e.scouting_team_number,
                    'team_count': len(e.teams)
                })
            pd.DataFrame(events_rows).to_excel(writer, index=False, sheet_name='Events')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Events')

        # 2) Teams
        try:
            teams = filter_teams_by_scouting_team().order_by(Team.team_number).all()
            team_rows = []
            for t in teams:
                # Build a comma-separated list of event codes/names for the team
                try:
                    events_list = []
                    for ev in t.events:
                        events_list.append(ev.code or ev.name)
                    events_str = ', '.join(events_list)
                except Exception:
                    events_str = ''

                team_rows.append({
                    'id': t.id,
                    'team_number': t.team_number,
                    'team_name': t.team_name,
                    'location': t.location,
                    'scouting_team_number': t.scouting_team_number,
                    'event_count': len(t.events),
                    'events': events_str
                })
            pd.DataFrame(team_rows).to_excel(writer, index=False, sheet_name='Teams')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Teams')

        # 3) Matches (scoped to current scouting team / alliance membership)
        try:
            matches = filter_matches_by_scouting_team().order_by(Match.match_type, Match.match_number).all()
            match_rows = []
            for m in matches:
                # parse alliances into individual team slots
                def split_alliance(s):
                    try:
                        return [x.strip() for x in (s or '').split(',') if x.strip()]
                    except Exception:
                        return []

                red_parts = split_alliance(m.red_alliance)
                blue_parts = split_alliance(m.blue_alliance)

                # helper to get team name from team_number string
                def team_name_for(num_str):
                    try:
                        num = int(str(num_str))
                        team_obj = Team.query.filter_by(team_number=num).first()
                        return team_obj.team_name if team_obj else None
                    except Exception:
                        return None

                row = {
                    'id': m.id,
                    'match_type': m.match_type,
                    'match_number': m.match_number,
                    'event_id': m.event_id,
                    'event_name': m.event.name if getattr(m, 'event', None) else None,
                    'red_score': m.red_score,
                    'blue_score': m.blue_score,
                    'winner': m.winner,
                    'timestamp': m.timestamp,
                    'scouting_team_number': m.scouting_team_number
                }

                # add red slots and names
                for i in range(3):
                    key_num = f'red_{i+1}'
                    key_name = f'red_{i+1}_name'
                    val = red_parts[i] if i < len(red_parts) else None
                    row[key_num] = val
                    row[key_name] = team_name_for(val) if val else None

                # add blue slots and names
                for i in range(3):
                    key_num = f'blue_{i+1}'
                    key_name = f'blue_{i+1}_name'
                    val = blue_parts[i] if i < len(blue_parts) else None
                    row[key_num] = val
                    row[key_name] = team_name_for(val) if val else None

                match_rows.append(row)

            pd.DataFrame(match_rows).to_excel(writer, index=False, sheet_name='Matches')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Matches')

        # 4) Scouting Data (all entries - use alliance data if in alliance mode)
        try:
            alliance_id = get_active_alliance_id()
            if alliance_id:
                scouting_data = AllianceSharedScoutingData.query.filter_by(
                    alliance_id=alliance_id,
                    is_active=True
                ).all()
            else:
                # Exclude alliance-copied data (scout_name starts with [Alliance-)
                scouting_data = ScoutingData.query.filter(
                    ScoutingData.scouting_team_number == current_user.scouting_team_number,
                    db.or_(
                        ScoutingData.scout_name == None,
                        ~ScoutingData.scout_name.like('[Alliance-%')
                    )
                ).all()
            sd_rows = []
            for sd in scouting_data:
                base = {
                    'id': sd.id,
                    'match_id': sd.match_id,
                    'match_number': sd.match.match_number if sd.match else None,
                    'match_type': sd.match.match_type if sd.match else None,
                    'team_id': sd.team_id,
                    'team_number': sd.team.team_number if sd.team else None,
                    'team_name': sd.team.team_name if sd.team else None,
                    'alliance': sd.alliance,
                    'scout_name': sd.scout_name,
                    'scout_id': sd.scout_id,
                    'scouting_station': sd.scouting_station,
                    'timestamp': sd.timestamp
                }
                # Flatten JSON data into columns prefixed with data_
                try:
                    for k, v in sd.data.items():
                        # Avoid overwriting existing base keys
                        col = f'data_{k}'
                        base[col] = v
                except Exception:
                    base['data_json'] = sd.data_json
                # Always include raw JSON backup so imports can remap IDs and preserve full structure
                try:
                    base['data_json'] = sd.data_json
                except Exception:
                    base.setdefault('data_json', None)
                sd_rows.append(base)
            pd.DataFrame(sd_rows).to_excel(writer, index=False, sheet_name='Scouting Data')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Scouting Data')

        # 5) Pit Scouting (use alliance data if in alliance mode)
        try:
            if alliance_id:
                pit_data = AllianceSharedPitData.query.filter_by(
                    alliance_id=alliance_id,
                    is_active=True
                ).order_by(AllianceSharedPitData.timestamp.desc()).all()
                pit_rows = [p.to_dict() for p in pit_data]
            else:
                pit_rows = [p.to_dict() for p in PitScoutingData.query.filter_by(
                    scouting_team_number=current_user.scouting_team_number
                ).order_by(PitScoutingData.timestamp.desc()).all()]
            pd.DataFrame(pit_rows).to_excel(writer, index=False, sheet_name='Pit Scouting')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Pit Scouting')

        # 5b) Team-Event associations (explicit) - use scoped teams
        try:
            te_rows = []
            for t in filter_teams_by_scouting_team().order_by(Team.team_number).all():
                for ev in t.events:
                    te_rows.append({'team_id': t.id, 'event_id': ev.id})
            pd.DataFrame(te_rows).to_excel(writer, index=False, sheet_name='team_event')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='team_event')

        # 6) Alliance Selections (scoped to current scouting team)
        try:
            alliance_rows = []
            for a in AllianceSelection.query.filter_by(scouting_team_number=current_user.scouting_team_number).order_by(AllianceSelection.event_id).all():
                alliance_rows.append({
                    'id': a.id,
                    'event_id': a.event_id,
                    'alliance_number': a.alliance_number,
                    'captain': a.captain,
                    'first_pick': a.first_pick,
                    'second_pick': a.second_pick,
                    'third_pick': a.third_pick,
                    'timestamp': a.timestamp,
                    'scouting_team_number': a.scouting_team_number
                })
            pd.DataFrame(alliance_rows).to_excel(writer, index=False, sheet_name='Alliances')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Alliances')

        # 7) Do Not Pick / Avoid lists (scoped to current scouting team)
        try:
            dnp_rows = []
            for entry in DoNotPickEntry.query.filter_by(scouting_team_number=current_user.scouting_team_number).order_by(DoNotPickEntry.timestamp.desc()).all():
                dnp_rows.append({
                    'id': entry.id,
                    'team_id': entry.team_id,
                    'team_number': entry.team.team_number if entry.team else None,
                    'event_id': entry.event_id,
                    'reason': entry.reason,
                    'timestamp': entry.timestamp,
                    'scouting_team_number': entry.scouting_team_number
                })
            avoid_rows = []
            for entry in AvoidEntry.query.filter_by(scouting_team_number=current_user.scouting_team_number).order_by(AvoidEntry.timestamp.desc()).all():
                avoid_rows.append({
                    'id': entry.id,
                    'team_id': entry.team_id,
                    'team_number': entry.team.team_number if entry.team else None,
                    'event_id': entry.event_id,
                    'reason': entry.reason,
                    'timestamp': entry.timestamp,
                    'scouting_team_number': entry.scouting_team_number
                })
            pd.DataFrame(dnp_rows).to_excel(writer, index=False, sheet_name='DoNotPick')
            pd.DataFrame(avoid_rows).to_excel(writer, index=False, sheet_name='Avoid')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='DoNotPick')
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Avoid')

        # 8) Strategy Drawings (scoped to current scouting team)
        try:
            sdg_rows = []
            for s in StrategyDrawing.query.filter_by(scouting_team_number=current_user.scouting_team_number).order_by(StrategyDrawing.last_updated.desc()).all():
                sdg_rows.append({
                    'id': s.id,
                    'match_id': s.match_id,
                    'match_number': s.match.match_number if s.match else None,
                    'scouting_team_number': s.scouting_team_number,
                    'last_updated': s.last_updated,
                    'background_image': s.background_image,
                    'data_json': s.data_json
                })
            pd.DataFrame(sdg_rows).to_excel(writer, index=False, sheet_name='Strategy Drawings')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Strategy Drawings')

        # 9) Shared Graphs & Ranks
        try:
            sg_rows = [g.to_dict() for g in SharedGraph.query.order_by(SharedGraph.created_at.desc()).all()]
            str_rows = [r.to_dict() for r in SharedTeamRanks.query.order_by(SharedTeamRanks.created_at.desc()).all()]
            pd.DataFrame(sg_rows).to_excel(writer, index=False, sheet_name='SharedGraphs')
            pd.DataFrame(str_rows).to_excel(writer, index=False, sheet_name='SharedTeamRanks')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='SharedGraphs')
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='SharedTeamRanks')
    
    output.seek(0)

    filename = f'scouting_data_{game_config["season"]}.xlsx'

    # If the user requested a direct download, return the file as an attachment
    if request.args.get('download') or request.args.get('direct'):
        # Reset buffer position and stream file
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    # Otherwise fall back to embedding as base64 in the template for manual download
    # Encode as base64 for download
    excel_data = base64.b64encode(output.read()).decode('utf-8')

    return render_template('data/export_excel.html', excel_data=excel_data,
                          filename=filename,
                          **get_theme_context())


@bp.route('/export/portable')
def export_portable():
    """Export a portable ZIP containing JSON dumps of key tables so it can be imported on another server.

    This export is now scoped to the CURRENT user's scouting team (when available) so
    it only includes rows that belong to that scouting_team_number.
    """
    try:
        export_data = {}

        # Scope export to current user's scouting team when possible
        scouting_team_num = getattr(current_user, 'scouting_team_number', None) if getattr(current_user, 'is_authenticated', False) else None
        export_data['scoped_to_scouting_team'] = scouting_team_num

        # Events (use alliance-aware combined/deduped list when not scoped)
        if scouting_team_num:
            events = Event.query.filter_by(scouting_team_number=scouting_team_num).order_by(Event.start_date.desc()).all()
        else:
            events = get_combined_dropdown_events()

        export_data['events'] = []
        for e in events:
            # Some dropdown events may be synthetic alliance entries (SimpleNamespace) and
            # may not have all attributes (e.g., start_date/end_date). Use getattr to be safe.
            ev_start = getattr(e, 'start_date', None)
            ev_end = getattr(e, 'end_date', None)
            export_data['events'].append({
                'id': e.id,
                'name': getattr(e, 'name', None),
                'code': getattr(e, 'code', None),
                'location': getattr(e, 'location', None),
                'start_date': ev_start.isoformat() if ev_start else None,
                'end_date': ev_end.isoformat() if ev_end else None,
                'year': getattr(e, 'year', None),
                'scouting_team_number': getattr(e, 'scouting_team_number', None)
            })

        # Teams
        if scouting_team_num:
            teams = Team.query.filter_by(scouting_team_number=scouting_team_num).order_by(Team.team_number).all()
        else:
            teams = Team.query.order_by(Team.team_number).all()

        export_data['teams'] = []
        for t in teams:
            export_data['teams'].append({
                'id': t.id,
                'team_number': t.team_number,
                'team_name': t.team_name,
                'location': t.location,
                'scouting_team_number': t.scouting_team_number,
                'events': [ev.id for ev in t.events]
            })

        # Team-Event association (explicit)
        # Build from relationship to avoid DB-specific introspection
        export_data['team_event'] = []
        for t in teams:
            for ev in t.events:
                export_data['team_event'].append({'team_id': t.id, 'event_id': ev.id})

        # Matches
        if scouting_team_num:
            matches = Match.query.filter_by(scouting_team_number=scouting_team_num).order_by(Match.match_type, Match.match_number).all()
        else:
            matches = Match.query.order_by(Match.match_type, Match.match_number).all()

        export_data['matches'] = []
        for m in matches:
            export_data['matches'].append({
                'id': m.id,
                'match_number': m.match_number,
                'match_type': m.match_type,
                'event_id': m.event_id,
                'red_alliance': m.red_alliance,
                'blue_alliance': m.blue_alliance,
                'red_score': m.red_score,
                'blue_score': m.blue_score,
                'winner': m.winner,
                'timestamp': m.timestamp.isoformat() if m.timestamp else None,
                'scouting_team_number': m.scouting_team_number
            })

        # Scouting Data
        if scouting_team_num:
            sds = ScoutingData.query.filter_by(scouting_team_number=scouting_team_num).order_by(ScoutingData.timestamp).all()
        else:
            sds = ScoutingData.query.order_by(ScoutingData.timestamp).all()

        export_data['scouting_data'] = []
        for sd in sds:
            export_data['scouting_data'].append({
                'id': sd.id,
                'match_id': sd.match_id,
                'team_id': sd.team_id,
                'scouting_team_number': sd.scouting_team_number,
                'scout_name': sd.scout_name,
                'scout_id': sd.scout_id,
                'scouting_station': sd.scouting_station,
                'timestamp': sd.timestamp.isoformat() if sd.timestamp else None,
                'alliance': sd.alliance,
                'data_json': sd.data_json
            })

        # Pit Scouting
        if scouting_team_num:
            pits = PitScoutingData.query.filter_by(scouting_team_number=scouting_team_num).order_by(PitScoutingData.timestamp).all()
        else:
            pits = PitScoutingData.query.order_by(PitScoutingData.timestamp).all()
        export_data['pit_scouting'] = [p.to_dict() for p in pits]

        # Strategy drawings
        if scouting_team_num:
            sdraws = StrategyDrawing.query.filter_by(scouting_team_number=scouting_team_num).order_by(StrategyDrawing.last_updated).all()
        else:
            sdraws = StrategyDrawing.query.order_by(StrategyDrawing.last_updated).all()

        export_data['strategy_drawings'] = []
        for s in sdraws:
            export_data['strategy_drawings'].append({
                'id': s.id,
                'match_id': s.match_id,
                'scouting_team_number': s.scouting_team_number,
                'last_updated': s.last_updated.isoformat() if s.last_updated else None,
                'created_at': s.created_at.isoformat() if s.created_at else None,
                'background_image': s.background_image,
                'data_json': s.data_json
            })

        # Alliances, lists, shared graphs/ranks (scope by scouting team when possible)
        if scouting_team_num:
            export_data['alliances'] = [
                {
                    'id': a.id,
                    'alliance_number': a.alliance_number,
                    'captain': a.captain,
                    'first_pick': a.first_pick,
                    'second_pick': a.second_pick,
                    'third_pick': a.third_pick,
                    'event_id': a.event_id,
                    'timestamp': a.timestamp.isoformat() if a.timestamp else None,
                    'scouting_team_number': a.scouting_team_number
                } for a in AllianceSelection.query.filter_by(scouting_team_number=scouting_team_num).all()
            ]

            export_data['do_not_pick'] = [
                {
                    'id': e.id,
                    'team_id': e.team_id,
                    'event_id': e.event_id,
                    'reason': e.reason,
                    'timestamp': e.timestamp.isoformat() if e.timestamp else None,
                    'scouting_team_number': e.scouting_team_number
                } for e in DoNotPickEntry.query.filter_by(scouting_team_number=scouting_team_num).all()
            ]

            export_data['avoid'] = [
                {
                    'id': e.id,
                    'team_id': e.team_id,
                    'event_id': e.event_id,
                    'reason': e.reason,
                    'timestamp': e.timestamp.isoformat() if e.timestamp else None,
                    'scouting_team_number': e.scouting_team_number
                } for e in AvoidEntry.query.filter_by(scouting_team_number=scouting_team_num).all()
            ]

            # Limit shared graphs/ranks to ones created by teams that belong to this scouting team
            team_numbers = [t.team_number for t in teams] or []
            if team_numbers:
                export_data['shared_graphs'] = [g.to_dict() for g in SharedGraph.query.filter(SharedGraph.created_by_team.in_(team_numbers)).all()]
                export_data['shared_team_ranks'] = [r.to_dict() for r in SharedTeamRanks.query.filter(SharedTeamRanks.created_by_team.in_(team_numbers)).all()]
            else:
                export_data['shared_graphs'] = []
                export_data['shared_team_ranks'] = []
        else:
            export_data['alliances'] = [
                {
                    'id': a.id,
                    'alliance_number': a.alliance_number,
                    'captain': a.captain,
                    'first_pick': a.first_pick,
                    'second_pick': a.second_pick,
                    'third_pick': a.third_pick,
                    'event_id': a.event_id,
                    'timestamp': a.timestamp.isoformat() if a.timestamp else None,
                    'scouting_team_number': a.scouting_team_number
                } for a in AllianceSelection.query.all()
            ]

            export_data['do_not_pick'] = [
                {
                    'id': e.id,
                    'team_id': e.team_id,
                    'event_id': e.event_id,
                    'reason': e.reason,
                    'timestamp': e.timestamp.isoformat() if e.timestamp else None,
                    'scouting_team_number': e.scouting_team_number
                } for e in DoNotPickEntry.query.all()
            ]

            export_data['avoid'] = [
                {
                    'id': e.id,
                    'team_id': e.team_id,
                    'event_id': e.event_id,
                    'reason': e.reason,
                    'timestamp': e.timestamp.isoformat() if e.timestamp else None,
                    'scouting_team_number': e.scouting_team_number
                } for e in AvoidEntry.query.all()
            ]

            export_data['shared_graphs'] = [g.to_dict() for g in SharedGraph.query.all()]
            export_data['shared_team_ranks'] = [r.to_dict() for r in SharedTeamRanks.query.all()]

        # Write JSON files into ZIP
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, content in export_data.items():
                z.writestr(f"{name}.json", json.dumps(content, ensure_ascii=False, indent=2))

        buf.seek(0)
        filename = f'portable_export_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}.zip'
        return send_file(buf, as_attachment=True, download_name=filename, mimetype='application/zip')

    except Exception as e:
        current_app.logger.exception('Error creating portable export')
        flash(f'Error creating portable export: {e}', 'danger')
        return redirect(url_for('data.index'))


@bp.route('/import/portable', methods=['GET', 'POST'])
def import_portable():
    """Import a portable ZIP created by export_portable and remap IDs to this server.

    Strategy:
    - Import Events by matching code+year or name+year (update or create)
    - Import Teams by matching team_number (update or create)
    - Import Matches by matching event + match_type + match_number (update or create)
    - Re-create team_event associations using new IDs
    - Import ScoutingData and PitScoutingData, remapping match_id/team_id/event_id
    - Import other tables (alliances, lists, strategy drawings, shared graphs/ranks)

    Returns a summary report.
    """
    if request.method == 'GET':
        # If a job_id is provided, show its status on the page
        job_id = request.args.get('job_id')
        job_status = import_jobs.get(job_id) if job_id else None
        return render_template('data/import_portable.html', job_id=job_id, job_status=job_status, **get_theme_context())


    

    # POST: handle uploaded file
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(request.url)

    # Save uploaded file to a temporary location and queue a background import job
    import tempfile, threading
    job_id = str(uuid4())
    try:
        tmpf = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        tmpf.write(file.read())
        tmpf.close()
        tmp_path = tmpf.name
    except Exception as e:
        flash(f'Error saving uploaded file: {e}', 'error')
        return redirect(request.url)

    # Initialize job record. Mark as 'running' immediately so UI won't sit in 'queued' state
    import_jobs[job_id] = {
        'status': 'running',
        'message': 'Import queued and starting',
        'initiated_by': getattr(current_user, 'id', None) if getattr(current_user, 'is_authenticated', False) else None,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'finished_at': None
    }
    try:
        # Notify clients the job is starting (best-effort)
        try:
            socketio.emit('import_status', {'job_id': job_id, 'status': 'running', 'message': import_jobs[job_id]['message']}, broadcast=True)
        except Exception:
            pass
    except Exception:
        pass

    # Capture app for use inside thread
    app_obj = current_app._get_current_object()

    def _background_import_worker(path, app_obj, job_id, initiated_by=None):
        try:
            with app_obj.app_context():
                import_jobs[job_id]['status'] = 'running'
                import_jobs[job_id]['started_at'] = datetime.now(timezone.utc).isoformat()
                app_obj.logger.info(f"Background portable import started from {path} by {initiated_by}")
                try:
                    success, msg = import_portable_from_zip(path)
                    if success:
                        import_jobs[job_id]['status'] = 'finished'
                        import_jobs[job_id]['message'] = msg
                        app_obj.logger.info(f"Background portable import completed for {path}: {msg}")
                        try:
                            socketio.emit('import_status', {'job_id': job_id, 'status': 'finished', 'message': msg}, broadcast=True)
                        except Exception:
                            pass
                    else:
                        import_jobs[job_id]['status'] = 'error'
                        import_jobs[job_id]['message'] = msg
                        app_obj.logger.error(f"Background portable import failed for {path}: {msg}")
                        try:
                            socketio.emit('import_status', {'job_id': job_id, 'status': 'error', 'message': msg}, broadcast=True)
                        except Exception:
                            pass
                except Exception as e:
                    import_jobs[job_id]['status'] = 'error'
                    import_jobs[job_id]['message'] = str(e)
                    app_obj.logger.exception(f"Error during background portable import: {e}")
                    try:
                        socketio.emit('import_status', {'job_id': job_id, 'status': 'error', 'message': import_jobs[job_id]['message']}, broadcast=True)
                    except Exception:
                        pass
                finally:
                    import_jobs[job_id]['finished_at'] = datetime.now(timezone.utc).isoformat()
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    t = threading.Thread(target=_background_import_worker, args=(tmp_path, app_obj, job_id, getattr(current_user, 'id', None)), daemon=True)
    t.start()

    flash(f'Import started in background (job id: {job_id}). Check status on this page.', 'success')
    return redirect(url_for('data.import_portable', job_id=job_id))


@bp.route('/import/status')
def import_status():
    """Return job status. If a job has been running longer than STALLED_THRESHOLD_MINUTES,
    mark it as 'stalled' and notify clients so the UI doesn't wait forever."""
    job_id = request.args.get('job_id')
    if not job_id:
        return jsonify({'success': False, 'error': 'job_id required'}), 400
    job = import_jobs.get(job_id)
    if not job:
        return jsonify({'success': False, 'error': 'not_found'}), 404

    # If running too long, mark as stalled
    try:
        STALLED_THRESHOLD_MINUTES = current_app.config.get('IMPORT_STALLED_THRESHOLD_MINUTES', 30)
        if job.get('status') == 'running' and job.get('started_at'):
            try:
                started = datetime.fromisoformat(job['started_at'])
                age = datetime.now(timezone.utc) - started
                if age.total_seconds() > STALLED_THRESHOLD_MINUTES * 60:
                    job['status'] = 'stalled'
                    job['message'] = f"Job marked stalled after {int(age.total_seconds()//60)} minutes"
                    job['finished_at'] = datetime.now(timezone.utc).isoformat()
                    # notify clients
                    try:
                        socketio.emit('import_status', {'job_id': job_id, 'status': 'stalled', 'message': job['message']}, broadcast=True)
                    except Exception:
                        current_app.logger.exception('Error emitting stalled import_status')
            except Exception:
                # Ignore parse errors and return current status
                pass
    except Exception:
        pass

    return jsonify({'success': True, 'job': job})

    # Mapping from old_id to new_id per model
    mapping = {
        'events': {},
        'teams': {},
        'matches': {},
        'strategy_drawings': {},
        'scouting_data': {},
        'pit_scouting': {}
    }

    report = {'created': {}, 'updated': {}, 'skipped': {}, 'errors': []}

    try:
        # EVENTS
        for ev in events:
            # Matching strategy: code+year or name+year
            existing = None
            if ev.get('code'):
                existing = Event.query.filter_by(code=ev.get('code'), year=ev.get('year')).first()
            if not existing:
                existing = Event.query.filter_by(name=ev.get('name'), year=ev.get('year')).first()

            if existing:
                # update basic fields
                existing.location = ev.get('location')
                existing.start_date = _sanitize_date(ev.get('start_date'))
                existing.end_date = _sanitize_date(ev.get('end_date'))
                db.session.add(existing)
                mapping['events'][ev['id']] = existing.id
                report['updated'].setdefault('events', 0)
                report['updated']['events'] = report['updated']['events'] + 1 if report['updated'].get('events') else 1
            else:
                new_ev = get_or_create_event(
                    name=ev.get('name'),
                    code=ev.get('code'),
                    year=ev.get('year'),
                    location=ev.get('location'),
                    start_date=_sanitize_date(ev.get('start_date')),
                    end_date=_sanitize_date(ev.get('end_date')),
                    scouting_team_number=ev.get('scouting_team_number')
                )
                mapping['events'][ev['id']] = new_ev.id
                report['created'].setdefault('events', 0)
                report['created']['events'] = report['created']['events'] + 1 if report['created'].get('events') else 1

        db.session.commit()

        # TEAMS
        for t in teams:
            existing = Team.query.filter_by(team_number=t.get('team_number')).first()
            if existing:
                existing.team_name = t.get('team_name')
                existing.location = t.get('location')
                existing.scouting_team_number = t.get('scouting_team_number')
                db.session.add(existing)
                mapping['teams'][t['id']] = existing.id
                report['updated']['teams'] = report['updated'].get('teams', 0) + 1 if report['updated'].get('teams') else 1
            else:
                new_t = Team(
                    team_number=t.get('team_number'),
                    team_name=t.get('team_name'),
                    location=t.get('location'),
                    scouting_team_number=t.get('scouting_team_number')
                )
                db.session.add(new_t)
                db.session.flush()
                mapping['teams'][t['id']] = new_t.id
                report['created']['teams'] = report['created'].get('teams', 0) + 1 if report['created'].get('teams') else 1

        db.session.commit()

        # Re-create team_event associations
        for assoc in team_event:
            old_t = assoc.get('team_id')
            old_e = assoc.get('event_id')
            new_t = mapping['teams'].get(old_t)
            new_e = mapping['events'].get(old_e)
            if new_t and new_e:
                try:
                    db.session.execute(team_event.insert().values(team_id=new_t, event_id=new_e))
                except Exception:
                    # ignore duplicates
                    pass
        db.session.commit()

        # MATCHES
        for m in matches:
            # Determine new event id
            new_event = mapping['events'].get(m.get('event_id'))
            existing = None
            if new_event:
                existing = Match.query.filter_by(event_id=new_event, match_type=m.get('match_type'), match_number=m.get('match_number')).first()

            if existing:
                # update
                existing.red_alliance = m.get('red_alliance') or ''
                existing.blue_alliance = m.get('blue_alliance') or ''
                existing.red_score = m.get('red_score')
                existing.blue_score = m.get('blue_score')
                existing.winner = m.get('winner')
                db.session.add(existing)
                mapping['matches'][m['id']] = existing.id
                report['updated']['matches'] = report['updated'].get('matches', 0) + 1 if report['updated'].get('matches') else 1
            else:
                # Resolve placeholder if needed
                if not new_event and mapping['events'].get(None) is None:
                    try:
                        placeholder = get_or_create_event(
                            name='Imported (Missing Event) - Portable Import',
                            code=f'IMPORT-NULL-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',
                            year=datetime.now(timezone.utc).year
                        )
                        mapping['events'][None] = placeholder.id
                        db.session.commit()
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        try:
                            ev = Event(name='Imported (Missing Event) - Portable Import', code=None, year=datetime.now(timezone.utc).year)
                            db.session.add(ev)
                            db.session.flush()
                            mapping['events'][None] = ev.id
                            db.session.commit()
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                if not new_event and mapping['events'].get(None):
                    new_event = mapping['events'].get(None)
                # If we still don't have an event id, skip and log
                if not new_event:
                    report['errors'].append(f"Skipping match import (no event): {m.get('match_number')} {m.get('match_type')}")
                    continue
                new_m = Match(
                    match_number=m.get('match_number'),
                    match_type=m.get('match_type'),
                    event_id=new_event if new_event else mapping['events'].get(None),
                    red_alliance=m.get('red_alliance') or '',
                    blue_alliance=m.get('blue_alliance') or '',
                    red_score=m.get('red_score'),
                    blue_score=m.get('blue_score'),
                    winner=m.get('winner'),
                    scouting_team_number=m.get('scouting_team_number')
                )
                db.session.add(new_m)
                db.session.flush()
                try:
                    if (not new_m.event_id) and mapping['events'].get(None):
                        new_m.event_id = mapping['events'].get(None)
                        db.session.add(new_m)
                        db.session.flush()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                mapping['matches'][m['id']] = new_m.id
                report['created']['matches'] = report['created'].get('matches', 0) + 1 if report['created'].get('matches') else 1

        db.session.commit()

        # STRATEGY DRAWINGS
        for s in strategy_drawings:
            # Remap match id from imported mapping; skip if we couldn't map the match
            new_match = mapping['matches'].get(s.get('match_id'))
            if not new_match:
                # Couldn't find corresponding match in this DB; skip to avoid NOT NULL/UNIQUE issues
                report['skipped'].setdefault('strategy_drawings', 0)
                report['skipped']['strategy_drawings'] = report['skipped']['strategy_drawings'] + 1 if report['skipped'].get('strategy_drawings') else 1
                continue

            # If a drawing already exists for this match, update it instead of inserting (prevents UNIQUE constraint errors)
            existing = StrategyDrawing.query.filter_by(match_id=new_match).first()
            if existing:
                try:
                    existing.scouting_team_number = s.get('scouting_team_number') if s.get('scouting_team_number') is not None else existing.scouting_team_number
                    existing.data_json = s.get('data_json') or existing.data_json
                    existing.background_image = s.get('background_image') or existing.background_image
                    db.session.add(existing)
                    db.session.flush()
                    mapping['strategy_drawings'][s['id']] = existing.id
                    report['updated'].setdefault('strategy_drawings', 0)
                    report['updated']['strategy_drawings'] = report['updated']['strategy_drawings'] + 1 if report['updated'].get('strategy_drawings') else 1
                    continue
                except Exception:
                    # If update fails for any reason, rollback and try to continue
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    report['errors'].append(f"Error updating strategy_drawing for imported id {s.get('id')}")
                    continue

            # Create a new drawing if none exists
            try:
                new_s = StrategyDrawing(
                    match_id=new_match,
                    scouting_team_number=s.get('scouting_team_number'),
                    data_json=s.get('data_json') or '[]',
                    background_image=s.get('background_image')
                )
                db.session.add(new_s)
                db.session.flush()
                mapping['strategy_drawings'][s['id']] = new_s.id
                report['created'].setdefault('strategy_drawings', 0)
                report['created']['strategy_drawings'] = report['created']['strategy_drawings'] + 1 if report['created'].get('strategy_drawings') else 1
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                report['errors'].append(f"Error creating strategy_drawing for imported id {s.get('id')}: {e}")
                continue

        db.session.commit()

        # SCOUTING DATA
        for sd in scouting_data:
            new_match = mapping['matches'].get(sd.get('match_id'))
            new_team = mapping['teams'].get(sd.get('team_id'))
            if not new_match or not new_team:
                report['skipped'].setdefault('scouting_data', 0)
                report['skipped']['scouting_data'] = report['skipped']['scouting_data'] + 1 if report['skipped'].get('scouting_data') else 1
                continue

            new_sd = ScoutingData(
                match_id=new_match,
                team_id=new_team,
                scouting_team_number=sd.get('scouting_team_number'),
                scout_name=sd.get('scout_name'),
                scout_id=sd.get('scout_id'),
                scouting_station=sd.get('scouting_station'),
                alliance=sd.get('alliance'),
                data_json=sd.get('data_json')
            )
            db.session.add(new_sd)
            db.session.flush()
            mapping['scouting_data'][sd['id']] = new_sd.id

        db.session.commit()

        # PIT SCOUTING
        import uuid as _uuid
        for p in pit_scouting:
            new_team = mapping['teams'].get(p.get('team_id'))
            new_event = mapping['events'].get(p.get('event_id'))
            if not new_team:
                report['skipped']['pit_scouting'] = report['skipped'].get('pit_scouting', 0) + 1 if report['skipped'].get('pit_scouting') else 1
                continue

            local_id = p.get('local_id')
            # If local_id exists in target DB, update that record instead of inserting to avoid UNIQUE constraint errors
            existing = None
            try:
                if local_id:
                    existing = PitScoutingData.query.filter_by(local_id=local_id).first()
            except Exception:
                existing = None

            if existing:
                try:
                    # Update existing record with imported values (preserve non-null fields when incoming is None)
                    existing.team_id = new_team or existing.team_id
                    existing.event_id = new_event if new_event is not None else existing.event_id
                    existing.scouting_team_number = p.get('scouting_team_number') if p.get('scouting_team_number') is not None else existing.scouting_team_number
                    existing.scout_name = p.get('scout_name') or existing.scout_name
                    existing.scout_id = p.get('scout_id') if p.get('scout_id') is not None else existing.scout_id
                    if p.get('timestamp'):
                        try:
                            existing.timestamp = datetime.fromisoformat(p['timestamp'].replace('Z', '+00:00')) if isinstance(p['timestamp'], str) else p['timestamp']
                        except Exception:
                            pass
                    existing.data_json = json.dumps(p.get('data', {})) or existing.data_json
                    existing.is_uploaded = p.get('is_uploaded', existing.is_uploaded)
                    if p.get('upload_timestamp'):
                        try:
                            existing.upload_timestamp = datetime.fromisoformat(p['upload_timestamp'].replace('Z', '+00:00')) if isinstance(p['upload_timestamp'], str) else p['upload_timestamp']
                        except Exception:
                            pass
                    existing.device_id = p.get('device_id') or existing.device_id
                    db.session.add(existing)
                    db.session.flush()
                    mapping['pit_scouting'][p['id']] = existing.id
                    report['updated'].setdefault('pit_scouting', 0)
                    report['updated']['pit_scouting'] = report['updated']['pit_scouting'] + 1 if report['updated'].get('pit_scouting') else 1
                    continue
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    report['errors'].append(f"Error updating pit_scouting for imported id {p.get('id')}: {e}")
                    continue

            # Create new PitScoutingData
            try:
                # Ensure a unique local_id exists
                if not local_id:
                    local_id = str(_uuid.uuid4())
                    p['local_id'] = local_id

                new_p = PitScoutingData.from_dict(p)
                # Remap ids
                new_p.team_id = new_team
                new_p.event_id = new_event
                # Ensure local_id is set
                if not getattr(new_p, 'local_id', None):
                    new_p.local_id = str(_uuid.uuid4())
                db.session.add(new_p)
                db.session.flush()
                mapping['pit_scouting'][p['id']] = new_p.id
                report['created'].setdefault('pit_scouting', 0)
                report['created']['pit_scouting'] = report['created']['pit_scouting'] + 1 if report['created'].get('pit_scouting') else 1
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                # If UNIQUE local_id caused a failure, try to find the conflicting record and update it instead
                if 'UNIQUE constraint failed' in str(e) and local_id:
                    try:
                        conflict = PitScoutingData.query.filter_by(local_id=local_id).first()
                        if conflict:
                            conflict.team_id = new_team
                            conflict.event_id = new_event
                            conflict.data_json = json.dumps(p.get('data', {})) or conflict.data_json
                            db.session.add(conflict)
                            db.session.flush()
                            mapping['pit_scouting'][p['id']] = conflict.id
                            report['updated'].setdefault('pit_scouting', 0)
                            report['updated']['pit_scouting'] = report['updated']['pit_scouting'] + 1 if report['updated'].get('pit_scouting') else 1
                            continue
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                report['errors'].append(f"Error creating pit_scouting for imported id {p.get('id')}: {e}")
                continue

        db.session.commit()

        # Alliances, lists, shared graphs/ranks - attempt to remap event/team refs
        for a in alliances:
            new_event = mapping['events'].get(a.get('event_id'))
            new_a = AllianceSelection(
                alliance_number=a.get('alliance_number'),
                captain=mapping['teams'].get(a.get('captain')) if a.get('captain') else None,
                first_pick=mapping['teams'].get(a.get('first_pick')) if a.get('first_pick') else None,
                second_pick=mapping['teams'].get(a.get('second_pick')) if a.get('second_pick') else None,
                third_pick=mapping['teams'].get(a.get('third_pick')) if a.get('third_pick') else None,
                event_id=new_event,
                scouting_team_number=a.get('scouting_team_number')
            )
            db.session.add(new_a)

        for e in do_not_pick:
            new_team = mapping['teams'].get(e.get('team_id'))
            new_event = mapping['events'].get(e.get('event_id'))
            if new_team:
                new_e = DoNotPickEntry(
                    team_id=new_team,
                    event_id=new_event,
                    reason=e.get('reason'),
                    scouting_team_number=e.get('scouting_team_number')
                )
                db.session.add(new_e)

        for a in avoid:
            new_team = mapping['teams'].get(a.get('team_id'))
            new_event = mapping['events'].get(a.get('event_id'))
            if new_team:
                new_a = AvoidEntry(
                    team_id=new_team,
                    event_id=new_event,
                    reason=a.get('reason'),
                    scouting_team_number=a.get('scouting_team_number')
                )
                db.session.add(new_a)

        # Upsert shared graphs by share_id to avoid UNIQUE constraint failures
        for g in shared_graphs:
            try:
                share_id = g.get('share_id')
                existing_sg = None
                if share_id:
                    existing_sg = SharedGraph.query.filter_by(share_id=share_id).first()

                if existing_sg:
                    # Update fields on existing share
                    existing_sg.title = g.get('title')
                    existing_sg.description = g.get('description')
                    existing_sg.team_numbers = json.dumps(g.get('team_numbers') if g.get('team_numbers') else [])
                    existing_sg.event_id = mapping['events'].get(g.get('event_id')) if g.get('event_id') else None
                    existing_sg.metric = g.get('metric')
                    existing_sg.graph_types = json.dumps(g.get('graph_types') if g.get('graph_types') else [])
                    existing_sg.data_view = g.get('data_view')
                    existing_sg.created_by_team = g.get('created_by_team')
                    existing_sg.created_by_user = g.get('created_by_user')
                    existing_sg.created_at = datetime.fromisoformat(g['created_at']) if g.get('created_at') else None
                    existing_sg.expires_at = datetime.fromisoformat(g['expires_at']) if g.get('expires_at') else None
                    existing_sg.view_count = g.get('view_count', 0)
                    existing_sg.is_active = g.get('is_active', True)
                    db.session.add(existing_sg)
                else:
                    sg = SharedGraph(
                        share_id=share_id,
                        title=g.get('title'),
                        description=g.get('description'),
                        team_numbers=json.dumps(g.get('team_numbers') if g.get('team_numbers') else []),
                        event_id=mapping['events'].get(g.get('event_id')) if g.get('event_id') else None,
                        metric=g.get('metric'),
                        graph_types=json.dumps(g.get('graph_types') if g.get('graph_types') else []),
                        data_view=g.get('data_view'),
                        created_by_team=g.get('created_by_team'),
                        created_by_user=g.get('created_by_user'),
                        created_at=datetime.fromisoformat(g['created_at']) if g.get('created_at') else None,
                        expires_at=datetime.fromisoformat(g['expires_at']) if g.get('expires_at') else None,
                        view_count=g.get('view_count', 0),
                        is_active=g.get('is_active', True)
                    )
                    db.session.add(sg)
            except IntegrityError:
                db.session.rollback()
                # On unique constraint errors, attempt to update existing record
                try:
                    if share_id:
                        existing = SharedGraph.query.filter_by(share_id=share_id).first()
                        if existing:
                            existing.title = g.get('title')
                            existing.description = g.get('description')
                            existing.team_numbers = json.dumps(g.get('team_numbers') if g.get('team_numbers') else [])
                            existing.event_id = mapping['events'].get(g.get('event_id')) if g.get('event_id') else None
                            db.session.add(existing)
                except Exception:
                    pass
            except Exception:
                # best-effort; skip problematic graph
                db.session.rollback()
                continue

        # Upsert shared team ranks by share_id
        for r in shared_team_ranks:
            try:
                share_id = r.get('share_id')
                existing_sr = None
                if share_id:
                    existing_sr = SharedTeamRanks.query.filter_by(share_id=share_id).first()

                if existing_sr:
                    existing_sr.title = r.get('title')
                    existing_sr.description = r.get('description')
                    existing_sr.event_id = mapping['events'].get(r.get('event_id')) if r.get('event_id') else None
                    existing_sr.metric = r.get('metric')
                    existing_sr.created_by_team = r.get('created_by_team')
                    existing_sr.created_by_user = r.get('created_by_user')
                    existing_sr.created_at = datetime.fromisoformat(r['created_at']) if r.get('created_at') else None
                    existing_sr.expires_at = datetime.fromisoformat(r['expires_at']) if r.get('expires_at') else None
                    existing_sr.view_count = r.get('view_count', 0)
                    existing_sr.is_active = r.get('is_active', True)
                    db.session.add(existing_sr)
                else:
                    sr = SharedTeamRanks(
                        share_id=share_id,
                        title=r.get('title'),
                        description=r.get('description'),
                        event_id=mapping['events'].get(r.get('event_id')) if r.get('event_id') else None,
                        metric=r.get('metric'),
                        created_by_team=r.get('created_by_team'),
                        created_by_user=r.get('created_by_user'),
                        created_at=datetime.fromisoformat(r['created_at']) if r.get('created_at') else None,
                        expires_at=datetime.fromisoformat(r['expires_at']) if r.get('expires_at') else None,
                        view_count=r.get('view_count', 0),
                        is_active=r.get('is_active', True)
                    )
                    db.session.add(sr)
            except IntegrityError:
                db.session.rollback()
                try:
                    if share_id:
                        existing = SharedTeamRanks.query.filter_by(share_id=share_id).first()
                        if existing:
                            existing.title = r.get('title')
                            existing.description = r.get('description')
                            existing.event_id = mapping['events'].get(r.get('event_id')) if r.get('event_id') else None
                            db.session.add(existing)
                except Exception:
                    pass
            except Exception:
                db.session.rollback()
                continue

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error importing portable archive')
        flash(f'Error importing portable archive: {e}', 'danger')
        return redirect(url_for('data.import_portable'))

    # Build a summary message
    msg = []
    for k in ('events', 'teams', 'matches'):
        c = report['created'].get(k, 0) if report.get('created') else 0
        u = report['updated'].get(k, 0) if report.get('updated') else 0
        if c or u:
            msg.append(f"{k}: created={c} updated={u}")

    flash('Import complete. ' + '; '.join(msg), 'success')
    return redirect(url_for('data.index'))

@bp.route('/manage', methods=['GET'])
def manage_entries():
    """Manage database entries (view, edit, delete)."""
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Check for alliance mode
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    # Fetch all scouting entries - use alliance data if in alliance mode
    if is_alliance_mode:
        scouting_entries = (AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        )
        .join(Match)
        .join(Event)
        .join(Team)
        .order_by(AllianceSharedScoutingData.timestamp.desc())
        .all())
    else:
        # Exclude alliance-copied data (scout_name starts with [Alliance-)
        scouting_entries = (ScoutingData.query.filter(
            ScoutingData.scouting_team_number == current_user.scouting_team_number,
            db.or_(
                ScoutingData.scout_name == None,
                ~ScoutingData.scout_name.like('[Alliance-%')
            )
        )
                           .join(Match)
                           .join(Event)
                           .join(Team)
                           .order_by(ScoutingData.timestamp.desc())
                           .all())
    
    # Get ALL teams at the current event (regardless of scouting_team_number) and matches
    if current_event:
        if is_alliance_mode:
            # In alliance mode we need to gather teams and matches across alliance members
            # Allow synthetic 'alliance_CODE' event ids to be handled by the helpers
            try:
                teams, _ = get_all_teams_for_alliance(event_id=current_event.id, event_code=current_event.code)
            except Exception:
                teams = get_all_teams_at_event(event_id=current_event.id)
            try:
                matches, _ = get_all_matches_for_alliance(event_id=current_event.id, event_code=current_event.code)
            except Exception:
                matches = Match.query.filter_by(event_id=current_event.id).all()
            # Use proper match sorting (handles X-Y playoff format)
            matches = sorted(matches, key=match_sort_key)
        else:
            teams = get_all_teams_at_event(event_id=current_event.id)
            matches = Match.query.filter_by(event_id=current_event.id).all()
            # Use proper match sorting (handles X-Y playoff format)
            matches = sorted(matches, key=match_sort_key)
    else:
        teams = []  # No teams if no current event is set
        matches = []  # No matches if no current event is set
    # Always provide events list filtered by scouting team so the template can show Events tab
    try:
        events = get_combined_dropdown_events()
    except Exception:
        events = []

    return render_template('data/manage/index.html', 
                         scouting_entries=scouting_entries, 
                         teams=teams,
                         matches=matches,
                         events=events,
                         is_alliance_mode=is_alliance_mode,
                         alliance_id=alliance_id,
                         **get_theme_context())

@bp.route('/edit/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(entry_id):
    """Edit a scouting data entry"""
    # Get the scouting data entry
    entry = ScoutingData.query.filter_by(id=entry_id, scouting_team_number=current_user.scouting_team_number).first_or_404()
    
    # Get game configuration
    game_config = get_effective_game_config()
    
    if request.method == 'POST':
        # Update scout name and alliance
        scout_name = request.form.get('scout_name')
        # If blank, fall back to the account username so we always have a visible name
        if not scout_name or str(scout_name).strip() == '':
            scout_name = getattr(current_user, 'username', 'Unknown')
        entry.scout_name = scout_name
        entry.alliance = request.form.get('alliance')
        
        # Build updated data dictionary from form
        data = {}
        
        # Process all game elements from config
        all_elements = []
        all_elements.extend(game_config['auto_period']['scoring_elements'])
        all_elements.extend(game_config['teleop_period']['scoring_elements'])
        all_elements.extend(game_config['endgame_period']['scoring_elements'])
        all_elements.extend(game_config['post_match']['rating_elements'])
        all_elements.extend(game_config['post_match']['text_elements'])
        
        for element in all_elements:
            element_id = element['id']
            if element['type'] == 'boolean':
                data[element_id] = element_id in request.form
            elif element['type'] == 'counter':
                data[element_id] = int(request.form.get(element_id, 0))
            elif element['type'] == 'select':
                data[element_id] = request.form.get(element_id, element.get('default', ''))
            elif element['type'] == 'rating':
                data[element_id] = int(request.form.get(element_id, element.get('default', 0)))
            else:
                data[element_id] = request.form.get(element_id, '')
        
        # Update data
        entry.data_json = json.dumps(data)
        db.session.commit()
        
        flash('Scouting data updated successfully!', 'success')
        return redirect(url_for('data.manage_entries'))
    
    return render_template('data/manage/edit.html', entry=entry, game_config=game_config, **get_theme_context())

@bp.route('/delete/<int:entry_id>', methods=['POST'])
def delete_entry(entry_id):
    """Delete a scouting data entry"""
    entry = ScoutingData.query.filter_by(id=entry_id, scouting_team_number=current_user.scouting_team_number).first_or_404()
    
    team_number = entry.team.team_number
    match_number = entry.match.match_number
    
    db.session.delete(entry)
    db.session.commit()
    
    flash(f'Scouting data for Team {team_number} in Match {match_number} deleted!', 'success')
    return redirect(url_for('data.manage_entries'))

@bp.route('/wipe_database', methods=['POST'])
def wipe_database():
    """Wipe all data for the current scouting team from the database"""
    try:
        scouting_team_number = current_user.scouting_team_number
        
        # Check if scouting team number is None or empty string (but allow 0 for admin/superadmin)
        if scouting_team_number is None or scouting_team_number == '':
            flash("Error: No scouting team number found for current user.", "danger")
            return redirect(url_for('data.index'))
        
        # Count records before deletion for reporting (scoped where appropriate)
        scouting_data_count = ScoutingData.query.filter_by(scouting_team_number=scouting_team_number).count()
        pit_data_count = PitScoutingData.query.filter_by(scouting_team_number=scouting_team_number).count()
        strategy_count = StrategyDrawing.query.filter_by(scouting_team_number=scouting_team_number).count()
        alliance_count = AllianceSelection.query.filter_by(scouting_team_number=scouting_team_number).count()
        dnp_count = DoNotPickEntry.query.filter_by(scouting_team_number=scouting_team_number).count()
        avoid_count = AvoidEntry.query.filter_by(scouting_team_number=scouting_team_number).count()
        team_count = Team.query.filter_by(scouting_team_number=scouting_team_number).count()

        # Gather events owned by this scouting team and their ids
        events = Event.query.filter_by(scouting_team_number=scouting_team_number).all()
        event_ids = [e.id for e in events]
        event_count = len(event_ids)

        # Delete in an order that respects foreign keys. Events are referenced by many
        # tables (association table team_event, matches, team list entries, alliance selections, etc.).
        if event_ids:
            # 1) Remove association rows in team_event linking teams to these events
            try:
                db.session.execute(team_event.delete().where(team_event.c.event_id.in_(event_ids)))
            except Exception:
                # Some DB backends or SQLAlchemy versions may not support this; ignore non-fatal errors
                pass

            # 2) Delete objects that reference matches for these events (scoped by match.event_id)
            StrategyShare.query.filter(StrategyShare.match.has(Match.event_id.in_(event_ids))).delete(synchronize_session=False)
            ScoutingData.query.filter(ScoutingData.match.has(Match.event_id.in_(event_ids))).delete(synchronize_session=False)
            StrategyDrawing.query.filter(StrategyDrawing.match.has(Match.event_id.in_(event_ids))).delete(synchronize_session=False)
            # AllianceSharedScoutingData references matches and must be deleted first to avoid FK errors
            AllianceSharedScoutingData.query.filter(AllianceSharedScoutingData.match.has(Match.event_id.in_(event_ids))).delete(synchronize_session=False)

            # 3) Delete matches belonging to these events
            Match.query.filter(Match.event_id.in_(event_ids)).delete(synchronize_session=False)

            # 4) Delete event-scoped records
            TeamListEntry.query.filter(TeamListEntry.event_id.in_(event_ids)).delete(synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.event_id.in_(event_ids)).delete(synchronize_session=False)
            PitScoutingData.query.filter(PitScoutingData.event_id.in_(event_ids)).delete(synchronize_session=False)

            # 5) Nullify references in shared objects rather than deleting other teams' shares
            SharedGraph.query.filter(SharedGraph.event_id.in_(event_ids)).update({SharedGraph.event_id: None}, synchronize_session=False)
            SharedTeamRanks.query.filter(SharedTeamRanks.event_id.in_(event_ids)).update({SharedTeamRanks.event_id: None}, synchronize_session=False)

            # 6) Finally delete the events themselves
            Event.query.filter(Event.id.in_(event_ids)).delete(synchronize_session=False)

        # Delete per-team scoped objects (these are safe to delete by scouting_team_number)
        ScoutingData.query.filter_by(scouting_team_number=scouting_team_number).delete()
        PitScoutingData.query.filter_by(scouting_team_number=scouting_team_number).delete()
        StrategyDrawing.query.filter_by(scouting_team_number=scouting_team_number).delete()
        AllianceSelection.query.filter_by(scouting_team_number=scouting_team_number).delete()
        DoNotPickEntry.query.filter_by(scouting_team_number=scouting_team_number).delete()
        AvoidEntry.query.filter_by(scouting_team_number=scouting_team_number).delete()
        # Remove alliance-shared scouting entries originally created by this team
        AllianceSharedScoutingData.query.filter_by(source_scouting_team_number=scouting_team_number).delete()

        # Delete teams owned by this scouting team
        teams_to_delete = Team.query.filter_by(scouting_team_number=scouting_team_number).all()
        team_ids = [t.id for t in teams_to_delete]

        if team_ids:
            # Remove association rows in team_event linking these teams to events
            try:
                db.session.execute(team_event.delete().where(team_event.c.team_id.in_(team_ids)))
            except Exception:
                pass

            # Delete or nullify all records referencing these team ids to avoid FK constraint errors
            ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids)).delete(synchronize_session=False)
            PitScoutingData.query.filter(PitScoutingData.team_id.in_(team_ids)).delete(synchronize_session=False)
            AllianceSharedScoutingData.query.filter(AllianceSharedScoutingData.team_id.in_(team_ids)).delete(synchronize_session=False)
            AllianceSharedPitData.query.filter(AllianceSharedPitData.team_id.in_(team_ids)).delete(synchronize_session=False)
            TeamListEntry.query.filter(TeamListEntry.team_id.in_(team_ids)).delete(synchronize_session=False)

            # Nullify references to these teams in AllianceSelection (do not delete alliances)
            AllianceSelection.query.filter(AllianceSelection.captain.in_(team_ids)).update({AllianceSelection.captain: None}, synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.first_pick.in_(team_ids)).update({AllianceSelection.first_pick: None}, synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.second_pick.in_(team_ids)).update({AllianceSelection.second_pick: None}, synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.third_pick.in_(team_ids)).update({AllianceSelection.third_pick: None}, synchronize_session=False)

            # Finally delete the teams themselves
            Team.query.filter(Team.id.in_(team_ids)).delete(synchronize_session=False)
        else:
            Team.query.filter_by(scouting_team_number=scouting_team_number).delete()

        db.session.commit()
        
        # Delete custom strategy background images (these are shared across teams)
        # Only delete if this is the last scouting team or if user specifically wants to
        bg_folder = os.path.join('app', 'static', 'strategy_backgrounds')
        if os.path.exists(bg_folder):
            for f in os.listdir(bg_folder):
                if f.endswith('.png') or f.endswith('.jpg') or f.endswith('.jpeg') or f.endswith('.gif'):
                    try:
                        os.remove(os.path.join(bg_folder, f))
                    except Exception:
                        pass
        
        # Compute match count: matches that belonged to deleted events plus matches scoped to this scouting team
        matches_from_events_count = Match.query.filter(Match.event_id.in_(event_ids)).count() if event_ids else 0
        matches_scoped_count = Match.query.filter_by(scouting_team_number=scouting_team_number).count()
        match_count = max(matches_from_events_count, matches_scoped_count)

        # Build success message with deletion counts
        deleted_items = []
        if team_count > 0:
            deleted_items.append(f"{team_count} teams")
        if event_count > 0:
            deleted_items.append(f"{event_count} events")
        if match_count > 0:
            deleted_items.append(f"{match_count} matches")
        if scouting_data_count > 0:
            deleted_items.append(f"{scouting_data_count} scouting entries")
        if pit_data_count > 0:
            deleted_items.append(f"{pit_data_count} pit scouting entries")
        if alliance_count > 0:
            deleted_items.append(f"{alliance_count} alliance selections")
        if strategy_count > 0:
            deleted_items.append(f"{strategy_count} strategy drawings")
        
        if deleted_items:
            items_text = ", ".join(deleted_items)
            flash(f"Database wiped successfully for scouting team {scouting_team_number}. Deleted: {items_text}.", "success")
        else:
            flash(f"No data found to delete for scouting team {scouting_team_number}.", "info")
            
    except Exception as e:
        db.session.rollback()
        flash(f"Error wiping database for scouting team {current_user.scouting_team_number}: {str(e)}", "danger")
    return redirect(url_for('data.index'))

@bp.route('/validate', methods=['GET'])
@analytics_required
@login_required
def validate_data():
    """Validate alliance points: API vs. scouting data for each match in the selected/current event."""
    from app.utils.api_utils import get_matches_dual_api
    from app.models import Event, Match, ScoutingData, Team
    from app.utils.analysis import calculate_team_metrics
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    event_id = request.args.get('event_id', type=int)
    events = get_combined_dropdown_events()
    if event_id:
        event = filter_events_by_scouting_team().filter(Event.id == event_id).first_or_404()
    elif current_event_code:
        event = get_event_by_code(current_event_code)
    else:
        event = events[0] if events else None
    if not event:
        flash('No event selected or found.', 'danger')
        return redirect(url_for('data.index'))
    # Get all matches for this event (respecting alliance mode when active)
    # If alliance mode is active, use alliance helpers to gather matches from any alliance member
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    if is_alliance_mode:
        from app.utils.alliance_data import get_all_matches_for_alliance
        matches, _ = get_all_matches_for_alliance(event_id=event.id, event_code=event.code)
    else:
        from app.utils.team_isolation import filter_matches_by_scouting_team
        matches = filter_matches_by_scouting_team().filter(Match.event_id == event.id).all()
    # Get API matches (official scores)
    try:
        api_matches = get_matches_dual_api(event.code)
    except Exception as e:
        flash(f'Could not fetch official match data from API: {str(e)}', 'danger')
        return redirect(url_for('data.index'))
    # Additionally, for validation we want the detailed breakdowns (penalties/fouls)
    # which may not be present in the generic helpers. Fetch detailed match JSON
    # directly from FIRST API (preferred) and TBA (fallback) and use those
    # objects to extract penalty points.
    def fetch_detailed_matches(event_code):
        """Attempt to fetch detailed match objects from FIRST API, fallback to TBA.

        Returns a dict keyed by (match_type_lower, match_number_str) -> match_obj
        """
        detailed = {}
        from flask import current_app
        import requests

        # FIRST direct fetch
        try:
            base = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
            season = game_config.get('season', None) or game_config.get('year', None) or 0
            # Try the /matches endpoint first
            first_url = f"{base}/v2.0/{season}/matches/{event_code}"
            headers = None
            try:
                from app.utils.api_utils import get_api_headers
                headers = get_api_headers()
            except Exception:
                headers = {'Accept': 'application/json'}

            resp = requests.get(first_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                # FIRST often wraps matches under 'Matches' or returns list directly
                matches_list = None
                if isinstance(data, dict) and 'Matches' in data:
                    matches_list = data.get('Matches')
                elif isinstance(data, list):
                    matches_list = data
                elif isinstance(data, dict):
                    # find the first list value
                    for v in data.values():
                        if isinstance(v, list):
                            matches_list = v
                            break

                if matches_list:
                    for m in matches_list:
                        m_type = str(m.get('tournamentLevel', m.get('matchType', 'Qualification'))).lower()
                        m_num = str(m.get('matchNumber', m.get('match_number', 0)))
                        detailed[(m_type, m_num)] = m
                    return detailed
        except Exception:
            pass

        # TBA fallback
        try:
            from app.utils.tba_api_utils import get_tba_api_headers, construct_tba_event_key
            base = 'https://www.thebluealliance.com/api/v3'
            # construct event key using game config season
            season = game_config.get('season', None) or game_config.get('year', None)
            try:
                tba_key = construct_tba_event_key(event_code, season)
            except Exception:
                tba_key = event_code

            tba_url = f"{base}/event/{tba_key}/matches"
            headers = get_tba_api_headers()
            resp = requests.get(tba_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                matches_list = resp.json()
                for m in matches_list:
                    # TBA uses comp_level/match_number
                    m_type = str(m.get('comp_level', m.get('tournamentLevel', 'qualification'))).lower()
                    # normalize match number (handle set/number combos)
                    m_num = str(m.get('match_number', m.get('matchNumber', 0)))
                    detailed[(m_type, m_num)] = m
                return detailed
        except Exception:
            pass

        return detailed

    detailed_lookup = fetch_detailed_matches(event.code)
    # Build a lookup for API scores and penalty breakdowns.
    # We'll try to detect common penalty/foul fields in the API response and
    # subtract any penalty points that were awarded to an alliance so that
    # scouting (which commonly records only on-field scoring) compares more
    # accurately against the API's reported totals.
    def _extract_penalty_points(match_obj, side):
        # side: 'red' or 'blue'
        if not match_obj:
            return 0

        # Helper: attempt to coerce values to int if possible
        def _to_int(val):
            try:
                if val is None:
                    return None
                if isinstance(val, (int, float)):
                    return int(val)
                s = str(val).strip()
                if s == '':
                    return None
                return int(float(s))
            except Exception:
                return None

        # Recursive search: collect candidate numeric values whose key names
        # indicate fouls/penalties and attempt to associate them with a side
        candidates = []  # tuples of (path, key, value)

        def _walk(obj, path=None):
            if path is None:
                path = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key_lower = k.lower()
                    cur_path = path + [k]
                    # If v is a number-like and key name suggests penalty/foul
                    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip() != ''):
                        num = _to_int(v)
                        if num is not None and ('foul' in key_lower or 'penal' in key_lower or 'penalty' in key_lower):
                            candidates.append(('/'.join(cur_path), k, num))
                    # If nested dict/list, recurse
                    if isinstance(v, dict):
                        _walk(v, cur_path)
                    elif isinstance(v, list):
                        for i, item in enumerate(v):
                            _walk(item, cur_path + [str(i)])
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _walk(item, path + [str(i)])

        _walk(match_obj)

        # Prefer candidates that mention the side in their path or key
        for path, key, val in candidates:
            lk = (path + '/' + key).lower()
            if side in lk or lk.endswith(side):
                return val

        # Next prefer candidates where key contains 'red'/'blue' markers
        for path, key, val in candidates:
            if key.lower().endswith('red') and side == 'red':
                return val
            if key.lower().endswith('blue') and side == 'blue':
                return val

        # If multiple candidates found and none explicitly matched side,
        # attempt to heuristically choose one: if only one candidate, return it.
        if len(candidates) == 1:
            return candidates[0][2]

        # Fallback: check for known FIRST API keys like scoreRedFoul / scoreBlueFoul
        first_keys = {
            'red': ['scoreRedFoul', 'score_red_foul', 'red_foul', 'scoreRedPenalty', 'scoreRedPenaltyPoints'],
            'blue': ['scoreBlueFoul', 'score_blue_foul', 'blue_foul', 'scoreBluePenalty', 'scoreBluePenaltyPoints']
        }
        for fk in first_keys.get(side, []):
            if fk in match_obj:
                v = _to_int(match_obj.get(fk))
                if v is not None:
                    return v

        # No explicit penalty info found for this side
        return 0

    api_score_lookup = {}
    for m in api_matches:
        key = (str(m.get('match_type', m.get('matchType', 'Qualification'))).lower(), str(m.get('match_number', m.get('matchNumber', 0))))
        # Prefer detailed match object from direct fetch when available
        detailed_m = detailed_lookup.get(key)
        if detailed_m:
            # FIRST style
            raw_red = detailed_m.get('scoreRedFinal', detailed_m.get('score_red_final', m.get('red_score', m.get('scoreRedFinal'))))
            raw_blue = detailed_m.get('scoreBlueFinal', detailed_m.get('score_blue_final', m.get('blue_score', m.get('scoreBlueFinal'))))
            # FIRST foul keys
            red_pen = _extract_penalty_points(detailed_m, 'red') if detailed_m else _extract_penalty_points(m, 'red')
            blue_pen = _extract_penalty_points(detailed_m, 'blue') if detailed_m else _extract_penalty_points(m, 'blue')
        else:
            raw_red = m.get('red_score', m.get('scoreRedFinal'))
            raw_blue = m.get('blue_score', m.get('scoreBlueFinal'))
            red_pen = _extract_penalty_points(m, 'red')
            blue_pen = _extract_penalty_points(m, 'blue')
        try:
            red_pen = int(red_pen or 0)
        except Exception:
            red_pen = 0
        try:
            blue_pen = int(blue_pen or 0)
        except Exception:
            blue_pen = 0

        # Adjust API scores by subtracting penalty points that were awarded
        # to the alliance (so scouting points can be compared to on-field scoring)
        adj_red = None if raw_red is None else (int(raw_red) - red_pen)
        adj_blue = None if raw_blue is None else (int(raw_blue) - blue_pen)

        api_score_lookup[key] = {
            'red_score_raw': raw_red,
            'blue_score_raw': raw_blue,
            'red_penalty': red_pen,
            'blue_penalty': blue_pen,
            'red_score': adj_red,
            'blue_score': adj_blue
        }
    # Get tolerance from query params (default 15)
    try:
        tolerance = int(request.args.get('tolerance', 15))
        if tolerance < 0:
            tolerance = 15
    except Exception:
        tolerance = 15

    # Prepare comparison results
    results = []
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    for match in matches:
        key = (match.match_type.lower(), str(match.match_number))
        api_scores = api_score_lookup.get(key, {'red_score': None, 'blue_score': None})
        # Aggregate scouting data for this match - use alliance data if in alliance mode
        if is_alliance_mode:
            # In alliance mode, query by match_number and event_code since match IDs differ across teams
            from sqlalchemy import func
            scouting = AllianceSharedScoutingData.query.join(
                Match, AllianceSharedScoutingData.match_id == Match.id
            ).join(
                Event, Match.event_id == Event.id
            ).filter(
                Match.match_number == match.match_number,
                Match.match_type == match.match_type,
                func.upper(Event.code) == func.upper(event.code) if event and event.code else Match.event_id == match.event_id,
                AllianceSharedScoutingData.alliance_id == alliance_id,
                AllianceSharedScoutingData.is_active == True
            ).all()
        else:
            scouting = ScoutingData.query.filter_by(match_id=match.id, scouting_team_number=current_user.scouting_team_number).all()
        red_total = 0
        blue_total = 0
        for sd in scouting:
            try:
                pts = sd.calculate_metric('tot')
            except Exception:
                pts = 0
            if sd.alliance == 'red':
                red_total += pts
            elif sd.alliance == 'blue':
                blue_total += pts
    # Consider data valid if within +/-tolerance points of the official API score
        # Pull API values (raw, penalty, adjusted) from lookup
        red_api_raw = api_scores.get('red_score_raw') if api_scores else None
        blue_api_raw = api_scores.get('blue_score_raw') if api_scores else None
        red_pen = api_scores.get('red_penalty', 0) if api_scores else 0
        blue_pen = api_scores.get('blue_penalty', 0) if api_scores else 0
        red_api_adj = api_scores.get('red_score') if api_scores else None
        blue_api_adj = api_scores.get('blue_score') if api_scores else None

        results.append({
            'match_number': match.match_number,
            'match_type': match.match_type,
            'red_api_raw': red_api_raw,
            'blue_api_raw': blue_api_raw,
            'red_penalty': red_pen,
            'blue_penalty': blue_pen,
            'red_api': red_api_adj,
            'blue_api': blue_api_adj,
            'red_scout': red_total,
            'blue_scout': blue_total,
            'discrepancy_red': (red_api_adj is not None and abs((red_total or 0) - (red_api_adj or 0)) > tolerance),
            'discrepancy_blue': (blue_api_adj is not None and abs((blue_total or 0) - (blue_api_adj or 0)) > tolerance)
        })
    # Custom sort order: practice, qualification, semifinals, finals
    match_type_order = {
        'practice': 1,
        'qualification': 2,
        'qualifier': 2,
        'quarterfinal': 3,
        'quarter-finals': 3,
        'quarterfinals': 3,
        'semifinal': 4,
        'semifinals': 4,
        'semi-final': 4,
        'semi-finals': 4,
        'final': 5,
        'finals': 5
    }
    def match_sort_key(row):
        type_key = match_type_order.get(row['match_type'].lower(), 99)
        # Try to sort match_number numerically if possible, else as string
        try:
            num_key = int(str(row['match_number']).split('-')[0])
        except Exception:
            num_key = str(row['match_number'])
        return (type_key, num_key, str(row['match_number']))
    results = sorted(results, key=match_sort_key)
    return render_template('data/validate.html', results=results, events=events, selected_event=event, **get_theme_context())


@bp.route('/recalculate', methods=['POST'])
@analytics_required
@login_required
def recalculate_metrics():
    """Recalculate team metrics for teams in the selected event (or all teams if no event provided)."""
    from app.utils.analysis import calculate_team_metrics
    try:
        event_id = request.form.get('event_id', type=int) or request.args.get('event_id', type=int)
        # Determine target teams
        if event_id:
            event = Event.query.get(event_id)
            if not event:
                flash('Selected event not found.', 'danger')
                return redirect(url_for('data.validate_data'))
            teams = Team.query.join(Team.events).filter(Event.id == event.id).all()
        else:
            teams = Team.query.all()

        count = 0
        for team in teams:
            # calculate_team_metrics is intentionally called for side-effects (warm caches / logging)
            try:
                calculate_team_metrics(team.id)
            except Exception:
                # don't stop on individual team failures
                current_app.logger.exception(f"Error recalculating metrics for team {team.id}")
            count += 1

        flash(f'Recalculated metrics for {count} teams.', 'success')
    except Exception as e:
        current_app.logger.exception('Error during metrics recalculation')
        flash(f'Error recalculating metrics: {str(e)}', 'danger')

    # Preserve event and tolerance query params when redirecting back
    return redirect(url_for('data.validate_data', event_id=event_id, tolerance=request.form.get('tolerance', request.args.get('tolerance', 15))))

@bp.route('/api/stats')
@analytics_required
def data_stats():
    """AJAX endpoint for data management stats - used for real-time config updates"""
    try:
        from flask import jsonify
        from datetime import datetime
        
        # Get current config
        game_config = get_effective_game_config()
        current_event_code = game_config.get('current_event_code')
        
        # Get current event if configured
        current_event = None
        if current_event_code:
            current_event = get_event_by_code(current_event_code)
        
        # Check if we're in alliance mode
        alliance_id = get_active_alliance_id()
        
        # Get database statistics - use alliance-aware functions in alliance mode
        if alliance_id and current_event_code:
            all_teams, _ = get_all_teams_for_alliance(event_code=current_event_code)
            all_matches, _ = get_all_matches_for_alliance(event_code=current_event_code)
            teams_count = len(all_teams)
            matches_count = len(all_matches)
        else:
            teams_count = filter_teams_by_scouting_team().count()
            matches_count = filter_matches_by_scouting_team().count()
        
        scouting_count = filter_scouting_data_by_scouting_team().count()
        pit_scouting_count = filter_pit_scouting_data_by_scouting_team().count()
        events_count = len(get_combined_dropdown_events())
        
        # Event-specific stats if current event is set
        event_stats = {}
        if current_event:
            if alliance_id:
                # Alliance mode - use already-fetched alliance data
                event_teams = teams_count
                event_matches = matches_count
            else:
                # Use event code matching to handle cross-team event lookups
                from sqlalchemy import func as data_func
                data_event_code = getattr(current_event, 'code', None)
                if data_event_code:
                    event_teams = filter_teams_by_scouting_team(Team.query.join(Team.events)).filter(data_func.upper(Event.code) == data_event_code.upper()).count()
                    event_matches = filter_matches_by_scouting_team(Match.query.join(Event, Match.event_id == Event.id)).filter(data_func.upper(Event.code) == data_event_code.upper()).count()
                else:
                    event_teams = filter_teams_by_scouting_team(Team.query.join(Team.events)).filter(Event.id == current_event.id).count()
                    event_matches = filter_matches_by_scouting_team(Match.query.filter_by(event_id=current_event.id)).count()
            # Use the student-friendly filter for event entries (includes unassigned entries when appropriate)
            # Use event code matching for cross-team scenarios
            from sqlalchemy import func as scouting_func
            scouting_event_code = getattr(current_event, 'code', None)
            if scouting_event_code:
                event_scouting = filter_scouting_data_by_scouting_team(ScoutingData.query.join(Match).join(Event, Match.event_id == Event.id)).filter(scouting_func.upper(Event.code) == scouting_event_code.upper()).count()
            else:
                event_scouting = filter_scouting_data_by_scouting_team(ScoutingData.query.join(Match).filter(Match.event_id == current_event.id)).count()
            
            event_stats = {
                'teams': event_teams,
                'matches': event_matches,
                'scouting_entries': event_scouting
            }
        
        return jsonify({
            'success': True,
            'game_config': game_config,
            'current_event': {
                'id': current_event.id if current_event else None,
                'name': current_event.name if current_event else None,
                'code': current_event.code if current_event else None
            } if current_event else None,
            'total_stats': {
                'teams': teams_count,
                'matches': matches_count,
                'scouting_entries': scouting_count,
                'pit_scouting_entries': pit_scouting_count,
                'events': events_count
            },
            'event_stats': event_stats,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in data_stats endpoint: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
