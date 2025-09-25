from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
from app.models import (
    Team, Match, Event, ScoutingData, StrategyDrawing, PitScoutingData,
    AllianceSelection, DoNotPickEntry, AvoidEntry,
    TeamListEntry, StrategyShare, SharedGraph, SharedTeamRanks, team_event
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
from datetime import datetime, date
from sqlalchemy.exc import IntegrityError
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_effective_game_config
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code
)
from flask import jsonify
from app.utils.api_auth import team_data_access_required

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

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
        # EVENTS
        for ev in export_data.get('events', []):
            existing = None
            if ev.get('code'):
                existing = Event.query.filter_by(code=ev.get('code'), year=ev.get('year')).first()
            if not existing:
                existing = Event.query.filter_by(name=ev.get('name'), year=ev.get('year')).first()

            if existing:
                existing.location = ev.get('location')
                existing.start_date = _sanitize_date(ev.get('start_date'))
                existing.end_date = _sanitize_date(ev.get('end_date'))
                db.session.add(existing)
                mapping['events'][ev['id']] = existing.id
                report['updated'].setdefault('events', 0)
                report['updated']['events'] = report['updated']['events'] + 1 if report['updated'].get('events') else 1
            else:
                new_ev = Event(
                    name=ev.get('name'),
                    code=ev.get('code'),
                    location=ev.get('location'),
                    start_date=_sanitize_date(ev.get('start_date')),
                    end_date=_sanitize_date(ev.get('end_date')),
                    year=ev.get('year'),
                    scouting_team_number=ev.get('scouting_team_number')
                )
                db.session.add(new_ev)
                db.session.flush()
                mapping['events'][ev['id']] = new_ev.id
                report['created'].setdefault('events', 0)
                report['created']['events'] = report['created']['events'] + 1 if report['created'].get('events') else 1

        db.session.commit()

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
            if new_t and new_e:
                try:
                    db.session.execute(team_event.insert().values(team_id=new_t, event_id=new_e))
                except Exception:
                    pass
        db.session.commit()

        # MATCHES
        for m in export_data.get('matches', []):
            new_event = mapping['events'].get(m.get('event_id'))
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
                new_m = Match(
                    match_number=m.get('match_number'),
                    match_type=m.get('match_type'),
                    event_id=new_event if new_event else None,
                    red_alliance=m.get('red_alliance') or '',
                    blue_alliance=m.get('blue_alliance') or '',
                    red_score=m.get('red_score'),
                    blue_score=m.get('blue_score'),
                    winner=m.get('winner'),
                    scouting_team_number=m.get('scouting_team_number')
                )
                db.session.add(new_m)
                db.session.flush()
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
                new_event = mapping['events'].get(a.get('event_id'))
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

@bp.route('/')
@analytics_required
def index():
    """Data import/export dashboard"""
    # Get database statistics
    teams_count = Team.query.count()
    matches_count = Match.query.count()
    scouting_count = ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number).count()
    
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
                            event = Event.query.filter_by(name=event_name).first()
                            if not event:
                                event = Event(name=event_name, year=game_config['season'])
                                db.session.add(event)
                                db.session.flush()
                                
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
                    event = Event.query.filter_by(name=event_name).first()
                    if not event:
                        event = Event(name=event_name, year=game_config['season'])
                        db.session.add(event)
                        db.session.flush()
                    
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
                    event = Event.query.filter_by(name=event_name).first()
                    if not event:
                        event = Event(name=event_name, year=game_config['season'])
                        db.session.add(event)
                        db.session.flush()
                    
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

        events_data = []
        for event in events:
            events_data.append({
                'id': event.id,
                'name': event.name,
                'code': event.code,
                'location': event.location,
                'start_date': event.start_date.isoformat() if event.start_date else None,
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'team_count': len(event.teams)
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
            events = Event.query.order_by(Event.year.desc(), Event.name).all()
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
            teams = Team.query.order_by(Team.team_number).all()
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

        # 3) Matches
        try:
            matches = Match.query.order_by(Match.match_type, Match.match_number).all()
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

        # 4) Scouting Data (all entries for this scouting team)
        try:
            scouting_data = ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number).all()
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

        # 5) Pit Scouting
        try:
            pit_rows = [p.to_dict() for p in PitScoutingData.query.order_by(PitScoutingData.timestamp.desc()).all()]
            pd.DataFrame(pit_rows).to_excel(writer, index=False, sheet_name='Pit Scouting')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='Pit Scouting')

        # 5b) Team-Event associations (explicit)
        try:
            te_rows = []
            for t in Team.query.order_by(Team.team_number).all():
                for ev in t.events:
                    te_rows.append({'team_id': t.id, 'event_id': ev.id})
            pd.DataFrame(te_rows).to_excel(writer, index=False, sheet_name='team_event')
        except Exception:
            pd.DataFrame([]).to_excel(writer, index=False, sheet_name='team_event')

        # 6) Alliance Selections
        try:
            alliance_rows = []
            for a in AllianceSelection.query.order_by(AllianceSelection.event_id).all():
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

        # 7) Do Not Pick / Avoid lists
        try:
            dnp_rows = []
            for entry in DoNotPickEntry.query.order_by(DoNotPickEntry.timestamp.desc()).all():
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
            for entry in AvoidEntry.query.order_by(AvoidEntry.timestamp.desc()).all():
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

        # 8) Strategy Drawings
        try:
            sdg_rows = []
            for s in StrategyDrawing.query.order_by(StrategyDrawing.last_updated.desc()).all():
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
    """Export a portable ZIP containing JSON dumps of key tables so it can be imported on another server."""
    try:
        export_data = {}

        # Events
        events = Event.query.order_by(Event.year.desc(), Event.name).all()
        export_data['events'] = []
        for e in events:
            export_data['events'].append({
                'id': e.id,
                'name': e.name,
                'code': e.code,
                'location': e.location,
                'start_date': e.start_date.isoformat() if e.start_date else None,
                'end_date': e.end_date.isoformat() if e.end_date else None,
                'year': e.year,
                'scouting_team_number': e.scouting_team_number
            })

        # Teams
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
        pits = PitScoutingData.query.order_by(PitScoutingData.timestamp).all()
        export_data['pit_scouting'] = [p.to_dict() for p in pits]

        # Strategy drawings
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

        # Alliances, lists, shared graphs/ranks
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
        filename = f'portable_export_{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}.zip'
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
        return render_template('data/import_portable.html', **get_theme_context())


    

    # POST: handle uploaded file
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(request.url)

    try:
        z = zipfile.ZipFile(file.stream)
    except Exception as e:
        flash('Uploaded file is not a valid ZIP archive', 'error')
        return redirect(request.url)

    # Helper to load JSON from zip safely
    def load_json(name):
        try:
            with z.open(name) as f:
                return json.load(f)
        except KeyError:
            return []

    # Read files
    events = load_json('events.json')
    teams = load_json('teams.json')
    team_event = load_json('team_event.json')
    matches = load_json('matches.json')
    scouting_data = load_json('scouting_data.json')
    pit_scouting = load_json('pit_scouting.json')
    strategy_drawings = load_json('strategy_drawings.json')
    alliances = load_json('alliances.json')
    do_not_pick = load_json('do_not_pick.json')
    avoid = load_json('avoid.json')
    shared_graphs = load_json('shared_graphs.json')
    shared_team_ranks = load_json('shared_team_ranks.json')

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
                new_ev = Event(
                    name=ev.get('name'),
                    code=ev.get('code'),
                    location=ev.get('location'),
                    start_date=_sanitize_date(ev.get('start_date')),
                    end_date=_sanitize_date(ev.get('end_date')),
                    year=ev.get('year'),
                    scouting_team_number=ev.get('scouting_team_number')
                )
                db.session.add(new_ev)
                db.session.flush()
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
                new_m = Match(
                    match_number=m.get('match_number'),
                    match_type=m.get('match_type'),
                    event_id=new_event if new_event else None,
                    red_alliance=m.get('red_alliance') or '',
                    blue_alliance=m.get('blue_alliance') or '',
                    red_score=m.get('red_score'),
                    blue_score=m.get('blue_score'),
                    winner=m.get('winner'),
                    scouting_team_number=m.get('scouting_team_number')
                )
                db.session.add(new_m)
                db.session.flush()
                mapping['matches'][m['id']] = new_m.id
                report['created']['matches'] = report['created'].get('matches', 0) + 1 if report['created'].get('matches') else 1

        db.session.commit()

        # STRATEGY DRAWINGS
        for s in strategy_drawings:
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
        for p in pit_scouting:
            new_team = mapping['teams'].get(p.get('team_id'))
            new_event = mapping['events'].get(p.get('event_id'))
            if not new_team:
                report['skipped']['pit_scouting'] = report['skipped'].get('pit_scouting', 0) + 1 if report['skipped'].get('pit_scouting') else 1
                continue
            new_p = PitScoutingData.from_dict(p)
            # Remap ids
            new_p.team_id = new_team
            new_p.event_id = new_event
            db.session.add(new_p)
            db.session.flush()
            mapping['pit_scouting'][p['id']] = new_p.id

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
    
    # Fetch all scouting entries with eager loading of related models
    scouting_entries = (ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number)
                       .join(Match)
                       .join(Event)
                       .join(Team)
                       .order_by(ScoutingData.timestamp.desc())
                       .all())
    
    # Get teams and matches filtered by the current event if available
    if current_event:
        teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
        matches = Match.query.filter_by(event_id=current_event.id).order_by(Match.match_type, Match.match_number).all()
    else:
        teams = []  # No teams if no current event is set
        matches = []  # No matches if no current event is set
    # Always provide events list filtered by scouting team so the template can show Events tab
    try:
        events = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.name).all()
    except Exception:
        events = []

    return render_template('data/manage/index.html', 
                         scouting_entries=scouting_entries, 
                         teams=teams,
                         matches=matches,
                         events=events,
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

        # Delete teams owned by this scouting team
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
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    if event_id:
        event = Event.query.get_or_404(event_id)
    elif current_event_code:
        event = get_event_by_code(current_event_code)
    else:
        event = events[0] if events else None
    if not event:
        flash('No event selected or found.', 'danger')
        return redirect(url_for('data.index'))
    # Get all matches for this event
    matches = Match.query.filter_by(event_id=event.id).all()
    # Get API matches (official scores)
    try:
        api_matches = get_matches_dual_api(event.code)
    except Exception as e:
        flash(f'Could not fetch official match data from API: {str(e)}', 'danger')
        return redirect(url_for('data.index'))
    # Build a lookup for API scores: (match_type, match_number) -> {red_score, blue_score}
    api_score_lookup = {}
    for m in api_matches:
        key = (str(m.get('match_type', m.get('matchType', 'Qualification'))).lower(), str(m.get('match_number', m.get('matchNumber', 0))))
        api_score_lookup[key] = {
            'red_score': m.get('red_score', m.get('scoreRedFinal')),
            'blue_score': m.get('blue_score', m.get('scoreBlueFinal'))
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
    for match in matches:
        key = (match.match_type.lower(), str(match.match_number))
        api_scores = api_score_lookup.get(key, {'red_score': None, 'blue_score': None})
        # Aggregate scouting data for this match
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
        results.append({
            'match_number': match.match_number,
            'match_type': match.match_type,
            'red_api': api_scores['red_score'],
            'blue_api': api_scores['blue_score'],
            'red_scout': red_total,
            'blue_scout': blue_total,
            'discrepancy_red': (api_scores['red_score'] is not None and abs((red_total or 0) - (api_scores['red_score'] or 0)) > tolerance),
            'discrepancy_blue': (api_scores['blue_score'] is not None and abs((blue_total or 0) - (api_scores['blue_score'] or 0)) > tolerance)
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
        
        # Get database statistics
        teams_count = Team.query.count()
        matches_count = Match.query.count()
        scouting_count = ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number).count()
        pit_scouting_count = PitScoutingData.query.count()
        events_count = Event.query.count()
        
        # Event-specific stats if current event is set
        event_stats = {}
        if current_event:
            event_teams = Team.query.join(Team.events).filter(Event.id == current_event.id).count()
            event_matches = Match.query.filter_by(event_id=current_event.id).count()
            event_scouting = ScoutingData.query.join(Match).filter(Match.event_id == current_event.id).filter_by(scouting_team_number=current_user.scouting_team_number).count()
            
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
